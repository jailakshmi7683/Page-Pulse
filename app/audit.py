"""
Core audit logic for Page Pulse.

Kept separate from the Flask layer on purpose: this module has no knowledge
of HTTP status codes or request/response objects, so it can be unit tested
in isolation and reused from a CLI, a worker queue, etc.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, asdict
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

DEFAULT_TIMEOUT = 8  # seconds, connect+read
MAX_CONTENT_BYTES = 5 * 1024 * 1024  # 5 MB safety cap, avoid huge downloads
USER_AGENT = "PagePulse/1.0 (+https://digitalheroesco.com)"


class AuditError(Exception):
    """
    Base class for all "expected" failure modes.

    Each subclass carries an HTTP-ish status code so the API layer can map
    it straight to a response without re-deciding what went wrong.
    """
    status_code = 400

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidURLError(AuditError):
    status_code = 400


class UnreachableError(AuditError):
    status_code = 502


class TimeoutErrorAudit(AuditError):
    status_code = 504


class NonHTMLError(AuditError):
    status_code = 422


@dataclass
class AuditReport:
    url: str
    status_code: int
    response_time_ms: int
    title: str | None
    meta_description: str | None
    h1_count: int
    images_missing_alt: int
    total_images: int
    word_count: int
    content_type: str

    def to_dict(self) -> dict:
        return asdict(self)


def validate_url(url: str) -> str:
    """
    Normalize and validate a URL before we ever try to fetch it.

    Raises InvalidURLError for anything that isn't a well-formed http(s)
    URL. We deliberately reject bare hostnames like "example.com" without
    a scheme instead of guessing — silently prepending "https://" hides
    typos from the user and makes error messages confusing.
    """
    if not url or not isinstance(url, str):
        raise InvalidURLError("URL is required.")

    url = url.strip()
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise InvalidURLError(
            "URL must start with http:// or https://."
        )
    if not parsed.netloc:
        raise InvalidURLError("URL is missing a host, e.g. 'example.com'.")

    return url


def _extract_text_word_count(soup: BeautifulSoup) -> int:
    """
    Approximate word count of visible page text.

    We strip <script>, <style>, <noscript>, and <template> content since
    that's markup/code, not something a reader (or search engine) would
    count as page copy.
    """
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    words = re.findall(r"\b[\w'-]+\b", text)
    return len(words)


def fetch_and_analyze(url: str, timeout: int = DEFAULT_TIMEOUT) -> AuditReport:
    """
    Fetch `url` and return an AuditReport.

    Raises AuditError subclasses for invalid input, network failure,
    timeouts, or non-HTML responses. Never raises a bare/unexpected
    exception for network-related failures — callers (the API layer)
    should not need to guard against arbitrary requests.* exceptions.
    """
    url = validate_url(url)

    start = time.perf_counter()
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
            stream=True,  # so we can cap bytes read before it's all in memory
        )
    except requests.exceptions.Timeout as exc:
        raise TimeoutErrorAudit(f"Request to {url} timed out after {timeout}s.") from exc
    except requests.exceptions.ConnectionError as exc:
        raise UnreachableError(f"Could not connect to {url}.") from exc
    except requests.exceptions.RequestException as exc:
        raise UnreachableError(f"Request to {url} failed: {exc}") from exc

    elapsed_ms = int((time.perf_counter() - start) * 1000)

    content_type = response.headers.get("Content-Type", "")
    if "text/html" not in content_type.lower():
        response.close()
        raise NonHTMLError(
            f"Expected an HTML page but got Content-Type '{content_type or 'unknown'}'."
        )

    # Read the body ourselves with a size cap rather than trusting
    # response.text on an unbounded stream.
    raw = b""
    for chunk in response.iter_content(chunk_size=8192):
        raw += chunk
        if len(raw) > MAX_CONTENT_BYTES:
            response.close()
            break

    html = raw.decode(response.encoding or "utf-8", errors="replace")
    soup = BeautifulSoup(html, "html.parser")

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else None

    meta_tag = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})
    meta_description = meta_tag.get("content", "").strip() if meta_tag and meta_tag.get("content") else None

    h1_count = len(soup.find_all("h1"))

    images = soup.find_all("img")
    total_images = len(images)
    images_missing_alt = sum(
        1 for img in images
        if not img.get("alt") or not img.get("alt").strip()
    )

    word_count = _extract_text_word_count(soup)

    return AuditReport(
        url=url,
        status_code=response.status_code,
        response_time_ms=elapsed_ms,
        title=title,
        meta_description=meta_description,
        h1_count=h1_count,
        images_missing_alt=images_missing_alt,
        total_images=total_images,
        word_count=word_count,
        content_type=content_type,
    )
