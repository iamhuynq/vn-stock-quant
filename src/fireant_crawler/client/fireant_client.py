"""GET-only FireAnt client: whitelist, rate limit, retry with backoff, token redaction."""

import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from fireant_crawler.client.rate_limiter import RateLimiter
from fireant_crawler.client.redact import redact
from fireant_crawler.client.whitelist import is_allowed
from fireant_crawler.config import API_BASE_URL

_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_BACKOFF_SECONDS = 60.0
_KEPT_HEADER_PREFIXES = ("x-ratelimit", "ratelimit", "x-rate-limit", "retry-after")


class FireAntError(Exception):
    pass


class ForbiddenRequestError(FireAntError):
    """The request is not on the whitelist; it was never sent."""


class AuthError(FireAntError):
    """401/403: token missing, expired or lacking scope. The run must stop."""


class ApiError(FireAntError):
    def __init__(self, message: str, status: int | None, path: str) -> None:
        super().__init__(message)
        self.status = status
        self.path = path


@dataclass(frozen=True)
class ApiResponse:
    path: str
    params: dict[str, Any]
    status: int
    data: Any
    rate_limit_headers: dict[str, str]
    elapsed_seconds: float
    attempts: int


class FireAntClient:
    def __init__(
        self,
        token: str,
        rate_limiter: RateLimiter,
        max_retries: int = 5,
        timeout_seconds: float = 30.0,
        base_url: str = API_BASE_URL,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not token:
            raise AuthError("FIREANT_TOKEN is not set")
        self._token = token
        self._limiter = rate_limiter
        self._max_retries = max_retries
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=timeout_seconds,
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "FireAntClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> ApiResponse:
        if not is_allowed("GET", path):
            raise ForbiddenRequestError(f"Path not on whitelist: {self._safe(path)}")
        query = {k: v for k, v in (params or {}).items() if v is not None}

        last_error = ""
        for attempt in range(1, self._max_retries + 1):
            self._limiter.acquire()
            started = time.monotonic()
            try:
                response = self._http.get(path, params=query)
            except httpx.TransportError as exc:
                last_error = f"network error: {type(exc).__name__}"
                self._backoff(attempt, retry_after=None)
                continue

            elapsed = time.monotonic() - started
            if response.status_code in (401, 403):
                raise AuthError(
                    f"HTTP {response.status_code} on {path}: token expired or missing scope"
                )
            if response.status_code in _RETRYABLE_STATUSES:
                last_error = f"HTTP {response.status_code}"
                self._backoff(attempt, retry_after=response.headers.get("retry-after"))
                continue
            if response.status_code >= 400:
                body = self._safe(response.text[:300])
                raise ApiError(f"HTTP {response.status_code} on {path}: {body}", response.status_code, path)

            return ApiResponse(
                path=path,
                params=query,
                status=response.status_code,
                data=self._decode(response),
                rate_limit_headers=self._rate_limit_headers(response.headers),
                elapsed_seconds=round(elapsed, 3),
                attempts=attempt,
            )

        raise ApiError(
            f"Giving up on {path} after {self._max_retries} attempts ({last_error})", None, path
        )

    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        if attempt >= self._max_retries:
            return
        if retry_after is not None and retry_after.strip().isdigit():
            delay = float(retry_after)
        else:
            delay = 2.0 ** (attempt - 1) + random.uniform(0, 1)
        self._sleep(min(delay, _MAX_BACKOFF_SECONDS))

    def _safe(self, text: str) -> str:
        return redact(text, [self._token])

    @staticmethod
    def _decode(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text

    @staticmethod
    def _rate_limit_headers(headers: httpx.Headers) -> dict[str, str]:
        return {k: v for k, v in headers.items() if k.lower().startswith(_KEPT_HEADER_PREFIXES)}
