from __future__ import annotations

import httpx
import pytest

from finlens.ingest.client import EdgarClient, EdgarError, EdgarNotFound


def make_client(handler, settings, **kwargs) -> EdgarClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(
        transport=transport,
        headers={"User-Agent": settings.sec_user_agent},
        follow_redirects=True,
    )
    return EdgarClient(settings, client=http, **kwargs)


def test_sends_the_configured_user_agent(settings):
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={"ok": True})

    with make_client(handler, settings) as client:
        client.get_json("https://data.sec.gov/x.json")

    # SEC blocks automated access without a descriptive agent and contact.
    assert "FinLens-test" in seen["user-agent"]


def test_404_raises_by_default(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with make_client(handler, settings) as client, pytest.raises(EdgarNotFound):
        client.fetch("https://data.sec.gov/missing.json")


def test_404_returns_none_when_allowed(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with make_client(handler, settings) as client:
        # Companies with no XBRL history genuinely have no companyfacts
        # document; that is data, not an error.
        assert client.fetch("https://data.sec.gov/x.json", allow_missing=True) is None


def test_retries_then_succeeds(settings, monkeypatch):
    monkeypatch.setattr("finlens.ingest.client.time.sleep", lambda _: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    with make_client(handler, settings) as client:
        assert client.get_json("https://data.sec.gov/x.json") == {"ok": True}
    assert calls["n"] == 3


def test_403_is_retried_not_raised(settings, monkeypatch):
    # EDGAR's edge answers impoliteness with 403, and it clears on its own.
    monkeypatch.setattr("finlens.ingest.client.time.sleep", lambda _: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(403) if calls["n"] == 1 else httpx.Response(200, json={})

    with make_client(handler, settings) as client:
        client.get_json("https://www.sec.gov/x.json")
    assert calls["n"] == 2


def test_gives_up_after_max_retries(settings, monkeypatch):
    monkeypatch.setattr("finlens.ingest.client.time.sleep", lambda _: None)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with make_client(handler, settings) as client, pytest.raises(EdgarError, match="giving up"):
        client.fetch("https://data.sec.gov/x.json")


def test_html_error_page_served_with_200_is_an_error(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>Your request has been blocked</html>")

    with make_client(handler, settings) as client, pytest.raises(EdgarError, match="did not return JSON"):
        client.get_json("https://data.sec.gov/x.json")


def test_400_is_not_retried(settings, monkeypatch):
    monkeypatch.setattr("finlens.ingest.client.time.sleep", lambda _: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, text="bad")

    with make_client(handler, settings) as client, pytest.raises(EdgarError):
        client.fetch("https://data.sec.gov/x.json")
    assert calls["n"] == 1


def test_cache_avoids_a_second_request(settings, tmp_path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"ok": True})

    with make_client(handler, settings, cache_dir=tmp_path / "cache") as client:
        client.get_json("https://data.sec.gov/x.json")
        second = client.fetch("https://data.sec.gov/x.json")

    assert calls["n"] == 1
    assert second is not None and second.from_cache
