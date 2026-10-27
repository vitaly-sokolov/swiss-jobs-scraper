"""httpx client with per-host throttle, retries and deadline checks (§14)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

log = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
MAX_RETRY_AFTER = 120.0


class SourceTimeout(RuntimeError):
    """The per-source or global deadline passed."""


class FetchError(RuntimeError):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class Throttle:
    """Minimum spacing between requests to the same host."""

    def __init__(self, default_interval: float, sleep: Callable[[float], None] = time.sleep) -> None:
        self.default_interval = default_interval
        self.intervals: dict[str, float] = {}
        self._last: dict[str, float] = {}
        self._sleep = sleep

    def set_interval(self, host: str, seconds: float) -> None:
        self.intervals[host] = seconds

    def wait(self, host: str) -> None:
        interval = self.intervals.get(host, self.default_interval)
        last = self._last.get(host)
        now = time.monotonic()
        if last is not None and (delay := last + interval - now) > 0:
            self._sleep(delay)
        self._last[host] = time.monotonic()


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError):
            return None


class HttpClient:
    def __init__(
        self,
        *,
        user_agent: str,
        proxy: str | None,
        throttle: Throttle,
        timeout: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.throttle = throttle
        self._sleep = sleep
        self.deadline: float | None = None  # time.monotonic() value
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Language": "en,de;q=0.8,fr;q=0.7"},
            proxy=proxy,
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def check_deadline(self) -> None:
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise SourceTimeout("deadline exceeded")

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        host = urlsplit(url).netloc
        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self.check_deadline()
            self.throttle.wait(host)
            try:
                response = self._client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                last_error = exc
                log.warning("transport error", extra={"url": url, "attempt": attempt, "error": str(exc)})
                if attempt < MAX_ATTEMPTS:
                    self._sleep(2**attempt)
                continue
            if response.status_code in RETRY_STATUSES and attempt < MAX_ATTEMPTS:
                delay = _retry_after_seconds(response) or float(2**attempt)
                log.warning(
                    "retryable status",
                    extra={"url": url, "status": response.status_code, "attempt": attempt, "delay": delay},
                )
                self._sleep(min(delay, MAX_RETRY_AFTER))
                continue
            if response.status_code >= 400:
                raise FetchError(f"HTTP {response.status_code} for {url}", response.status_code)
            return response
        raise FetchError(f"giving up on {url}: {last_error}") from last_error

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def get_json(self, url: str, **kwargs: Any) -> Any:
        return self.get(url, **kwargs).json()

    def get_text(self, url: str, **kwargs: Any) -> str:
        return self.get(url, **kwargs).text
