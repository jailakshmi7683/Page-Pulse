"""
Tests for app/audit.py.

We mock the network (requests.get) throughout — these are unit tests for
the parsing/validation logic, not integration tests against the live
internet. That keeps them fast and deterministic (no flaky network calls
in CI).
"""
import requests
import pytest

from app.audit import (
    InvalidURLError,
    NonHTMLError,
    TimeoutErrorAudit,
    UnreachableError,
    fetch_and_analyze,
    validate_url,
)

SAMPLE_HTML = """
<html>
  <head>
    <title>  Example Domain  </title>
    <meta name="description" content="An example page for testing.">
  </head>
  <body>
    <h1>Welcome</h1>
    <p>This is a short paragraph with exactly ten words in it here.</p>
    <img src="a.png" alt="A described image">
    <img src="b.png">
    <img src="c.png" alt="">
  </body>
</html>
"""


class FakeResponse:
    """Minimal stand-in for requests.Response, enough for our code path."""

    def __init__(self, text, status_code=200, content_type="text/html; charset=utf-8"):
        self._text = text
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self.encoding = "utf-8"

    def iter_content(self, chunk_size=8192):
        data = self._text.encode("utf-8")
        for i in range(0, len(data), chunk_size):
            yield data[i:i + chunk_size]

    def close(self):
        pass


# ---------------------------------------------------------------------------
# validate_url — pure function, no network
# ---------------------------------------------------------------------------

def test_validate_url_accepts_https():
    assert validate_url("https://example.com") == "https://example.com"


def test_validate_url_rejects_missing_scheme():
    with pytest.raises(InvalidURLError):
        validate_url("example.com")


def test_validate_url_rejects_empty_string():
    with pytest.raises(InvalidURLError):
        validate_url("")


def test_validate_url_rejects_garbage():
    with pytest.raises(InvalidURLError):
        validate_url("not a url at all")


# ---------------------------------------------------------------------------
# fetch_and_analyze — happy path
# ---------------------------------------------------------------------------

def test_happy_path_parses_all_fields(monkeypatch):
    monkeypatch.setattr(
        "app.audit.requests.get",
        lambda *a, **kw: FakeResponse(SAMPLE_HTML),
    )

    report = fetch_and_analyze("https://example.com")

    assert report.status_code == 200
    assert report.title == "Example Domain"
    assert report.meta_description == "An example page for testing."
    assert report.h1_count == 1
    assert report.total_images == 3
    # b.png has no alt attr at all, c.png has alt="" -> both count as missing
    assert report.images_missing_alt == 2
    assert report.word_count >= 10
    assert report.response_time_ms >= 0


def test_happy_path_handles_missing_title_and_description(monkeypatch):
    html = "<html><body><h1>Only a heading</h1></body></html>"
    monkeypatch.setattr(
        "app.audit.requests.get",
        lambda *a, **kw: FakeResponse(html),
    )

    report = fetch_and_analyze("https://example.com")

    assert report.title is None
    assert report.meta_description is None
    assert report.h1_count == 1


# ---------------------------------------------------------------------------
# fetch_and_analyze — failure cases (Task A requirement: never crash)
# ---------------------------------------------------------------------------

def test_invalid_url_raises_before_any_network_call(monkeypatch):
    called = {"hit": False}

    def fake_get(*a, **kw):
        called["hit"] = True
        return FakeResponse(SAMPLE_HTML)

    monkeypatch.setattr("app.audit.requests.get", fake_get)

    with pytest.raises(InvalidURLError):
        fetch_and_analyze("ftp://example.com")

    assert called["hit"] is False


def test_timeout_raises_timeout_error(monkeypatch):
    def fake_get(*a, **kw):
        raise requests.exceptions.Timeout("simulated timeout")

    monkeypatch.setattr("app.audit.requests.get", fake_get)

    with pytest.raises(TimeoutErrorAudit):
        fetch_and_analyze("https://slow.example.com")


def test_connection_error_raises_unreachable(monkeypatch):
    def fake_get(*a, **kw):
        raise requests.exceptions.ConnectionError("simulated DNS failure")

    monkeypatch.setattr("app.audit.requests.get", fake_get)

    with pytest.raises(UnreachableError):
        fetch_and_analyze("https://does-not-exist.invalid")


def test_non_html_response_raises_non_html_error(monkeypatch):
    monkeypatch.setattr(
        "app.audit.requests.get",
        lambda *a, **kw: FakeResponse(
            '{"not": "html"}', content_type="application/json"
        ),
    )

    with pytest.raises(NonHTMLError):
        fetch_and_analyze("https://api.example.com/data.json")
