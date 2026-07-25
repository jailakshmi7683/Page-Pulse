"""
Thin tests for the Flask layer: making sure errors from audit.py map to
the right HTTP status codes and that the API never returns a raw 500
crash page (Task A requirement: sensible errors, never a crash).
"""
import pytest

from app.main import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.get_json() == {"status": "ok"}


def test_audit_missing_url_returns_400(client):
    res = client.post("/api/audit", json={})
    assert res.status_code == 400
    assert "error" in res.get_json()


def test_audit_invalid_url_returns_400(client):
    res = client.post("/api/audit", json={"url": "not-a-url"})
    assert res.status_code == 400
    body = res.get_json()
    assert "error" in body


def test_audit_never_returns_raw_500_html(client, monkeypatch):
    """
    Even if something unexpected blows up deep inside audit logic,
    the API should still respond with JSON, not a Flask debug traceback.
    """
    def boom(url, timeout=8):
        raise RuntimeError("unexpected explosion")

    monkeypatch.setattr("app.main.fetch_and_analyze", boom)

    res = client.post("/api/audit", json={"url": "https://example.com"})
    assert res.status_code == 500
    assert res.is_json
    assert "error" in res.get_json()