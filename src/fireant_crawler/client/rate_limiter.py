"""Minimum-interval rate limiter for a single sequential worker."""

import time
from collections.abc import Callable


class RateLimiter:
    def __init__(
        self,
        requests_per_second: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be positive")
        self._interval = 1.0 / requests_per_second
        self._clock = clock
        self._sleep = sleep
        self._next_allowed: float | None = None

    def acquire(self) -> None:
        now = self._clock()
        if self._next_allowed is not None and now < self._next_allowed:
            self._sleep(self._next_allowed - now)
            now = self._next_allowed
        self._next_allowed = now + self._interval
