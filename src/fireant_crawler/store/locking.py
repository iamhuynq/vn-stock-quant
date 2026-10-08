"""Open DuckDB files for writing while short-lived readers (the local UI) may hold them.

DuckDB allows one read-write process OR many read-only processes per file. The UI opens a read-only
connection per query and closes it at once, so a writer only has to wait out an in-flight read.
"""

import time
from collections.abc import Callable
from pathlib import Path

import duckdb

LOCK_WAIT_SECONDS = 60.0


def is_lock_error(exc: BaseException) -> bool:
    return isinstance(exc, duckdb.IOException) and "Could not set lock" in str(exc)


def connect_with_retry(path: Path | str, read_only: bool = False, wait_seconds: float = LOCK_WAIT_SECONDS,
                       sleep: Callable[[float], None] = time.sleep,
                       clock: Callable[[], float] = time.monotonic) -> duckdb.DuckDBPyConnection:
    deadline = clock() + wait_seconds
    delay = 0.2
    while True:
        try:
            return duckdb.connect(str(path), read_only=read_only)
        except duckdb.IOException as exc:
            if not is_lock_error(exc) or clock() >= deadline:
                raise
        sleep(delay)
        delay = min(delay * 2, 2.0)
