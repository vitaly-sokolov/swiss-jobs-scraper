from __future__ import annotations

import time

import httpx
import pytest

from jobscraper.config import ProxyConfig
from jobscraper.fetch.http import FetchError, HttpClient, SourceTimeout, Throttle


def client_with(handler, sleeps: list[float]) -> HttpClient:
    return HttpClient(
        user_agent="ua",
        proxy=None,
        throttle=Throttle(0),
        sleep=sleeps.append,
        transport=httpx.MockTransport(handler),
    )


def test_retries_on_429_then_succeeds():
    responses = [httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(503), httpx.Response(200, json=[1])]
    sleeps: list[float] = []
    client = client_with(lambda r: responses.pop(0), sleeps)
    assert client.get_json("https://example.org/x") == [1]
    assert sleeps == [3.0, 4.0]


def test_gives_up_after_three_attempts():
    sleeps: list[float] = []
    client = client_with(lambda r: httpx.Response(500), sleeps)
    with pytest.raises(FetchError) as exc:
        client.get("https://example.org/x")
    assert exc.value.status == 500 and len(sleeps) == 2


def test_no_retry_on_404():
    calls = []
    client = client_with(lambda r: calls.append(r) or httpx.Response(404), [])
    with pytest.raises(FetchError):
        client.get("https://example.org/x")
    assert len(calls) == 1


def test_sends_identifiable_user_agent():
    seen = {}
    client = client_with(lambda r: seen.update(ua=r.headers["user-agent"]) or httpx.Response(200), [])
    client.get("https://example.org/")
    assert seen["ua"] == "ua"


def test_deadline():
    client = client_with(lambda r: httpx.Response(200), [])
    client.deadline = time.monotonic() - 1
    with pytest.raises(SourceTimeout):
        client.get("https://example.org/")


def test_throttle_spaces_requests_per_host():
    sleeps: list[float] = []
    throttle = Throttle(2.0, sleep=sleeps.append)
    throttle.wait("a.example")
    throttle.wait("b.example")
    throttle.wait("a.example")
    assert len(sleeps) == 1 and 1.9 < sleeps[0] <= 2.0


def test_proxy_url_and_safe_description():
    proxy = ProxyConfig(enabled=True, url="http://proxy.example:8080", username="u@x", password="p:w")
    assert proxy.httpx_proxy() == "http://u%40x:p%3Aw@proxy.example:8080"
    assert proxy.describe() == "proxy proxy.example:8080"
    assert "p:w" not in repr(proxy)
    assert ProxyConfig(enabled=False, url="http://h:1").httpx_proxy() is None
