"""Small HTTP helper with bounded retries. Standard library only."""
from __future__ import annotations

import time
import urllib.error
import urllib.request
from typing import Callable, Mapping, Optional

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_RETRY_WAIT = 30.0


class HTTPFailure(Exception):
    """A request failed. status is 0 for network-level failures."""

    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status} for {url}: {body[:300]}")
        self.status = status
        self.body = body
        self.url = url


def _retry_wait(attempt: int, headers: Optional[Mapping[str, str]]) -> float:
    if headers:
        raw = None
        for key in headers:
            if key.lower() == "retry-after":
                raw = headers[key]
                break
        if raw is not None:
            try:
                return max(0.0, min(float(raw), MAX_RETRY_WAIT))
            except (TypeError, ValueError):
                pass
    return min(float(2**attempt), MAX_RETRY_WAIT)


def request(
    method: str,
    url: str,
    *,
    headers: Optional[Mapping[str, str]] = None,
    data: Optional[bytes] = None,
    timeout: float = 30,
    urlopen: Optional[Callable] = None,
    retries: int = 2,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[int, dict, bytes]:
    """Send a request. Returns (status, headers, body). Raises HTTPFailure."""
    if not url.startswith(("https://", "http://")):
        raise HTTPFailure(0, "URL must start with http:// or https://", url)
    opener = urlopen or urllib.request.urlopen
    attempt = 0
    while True:
        req = urllib.request.Request(url, data=data, method=method, headers=dict(headers or {}))
        try:
            with opener(req, timeout=timeout) as resp:
                status = getattr(resp, "status", 200)
                return status, dict(resp.headers.items()), resp.read()
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")
            except Exception:  # noqa: BLE001 - body is best effort only
                pass
            if exc.code in RETRY_STATUSES and attempt < retries:
                sleep(_retry_wait(attempt, dict(exc.headers.items()) if exc.headers else None))
                attempt += 1
                continue
            raise HTTPFailure(exc.code, body, url) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if attempt < retries:
                sleep(_retry_wait(attempt, None))
                attempt += 1
                continue
            raise HTTPFailure(0, str(exc), url) from exc
