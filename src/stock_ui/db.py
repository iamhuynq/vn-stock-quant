"""Read-only access to the DuckDB files for the UI.

DuckDB allows one read-write process OR many read-only processes per file. The UI therefore never
keeps a connection: every read opens the file read-only, runs, and closes it. While the pipeline lock
is held (and not stale), or a writer holds the file, the last good result is returned and marked stale
instead of failing. A cached result is reused only while the file is unchanged and younger than the TTL.
"""

import threading
import time
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb

from fireant_crawler.store.locking import is_lock_error
from stock_ui.locks import lock_info

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
DB_FILES = {"warehouse": "warehouse.duckdb", "research": "research.duckdb", "results": "results.duckdb",
            "cross": "cross.duckdb"}
TTL_SECONDS = 60.0


@dataclass(frozen=True)
class ReadResult:
    value: Any                 # None when nothing could be read yet
    read_at: datetime | None   # when value was read from the file
    stale: bool                # True: the file could not be read now, value is from read_at
    note: str | None = None    # why the value is stale or missing


class Reader:
    def __init__(self, data_dir: Path, ttl: float = TTL_SECONDS, clock: Callable[[], float] = time.time) -> None:
        self.data_dir = data_dir
        self._ttl = ttl
        self._clock = clock
        self._cache: dict[Hashable, tuple[float, tuple, Any]] = {}
        self._guard = threading.Lock()

    def path(self, db: str) -> Path:
        return self.data_dir / DB_FILES[db]

    def pipeline_running(self) -> bool:
        info = lock_info(self.data_dir)
        return info is not None and not info.stale

    def _signature(self, path: Path) -> tuple:
        """Changes when a writer commits (main file or WAL) or the file is replaced (quant build)."""
        out = []
        for p in (path, path.with_name(path.name + ".wal")):
            try:
                st = p.stat()
                out.append((st.st_ino, st.st_mtime_ns, st.st_size))
            except FileNotFoundError:
                out.append(None)
        return tuple(out)

    def clear(self) -> None:
        with self._guard:
            self._cache.clear()

    def read(self, db: str, key: Hashable, fn: Callable[[duckdb.DuckDBPyConnection], Any]) -> ReadResult:
        cache_key = (db, key)
        with self._guard:
            cached = self._cache.get(cache_key)
        now = self._clock()
        path = self.path(db)
        sig = self._signature(path)
        if cached and now - cached[0] < self._ttl and cached[1] == sig:
            return ReadResult(cached[2], _as_dt(cached[0]), stale=False)
        if not path.exists():
            return ReadResult(None, None, stale=False, note=f"{path.name} not found")
        if self.pipeline_running():
            return _stale(cached, "pipeline is running")
        try:
            con = duckdb.connect(str(path), read_only=True)
        except duckdb.IOException as exc:
            if is_lock_error(exc):
                return _stale(cached, "database is being updated")
            raise
        try:
            value = fn(con)
        finally:
            con.close()
        with self._guard:
            self._cache[cache_key] = (now, sig, value)
        return ReadResult(value, _as_dt(now), stale=False)

    def query(self, db: str, sql: str, params: tuple = ()) -> ReadResult:
        """DataFrame result; values are always bound parameters, never formatted into sql."""
        return self.read(db, ("sql", sql, params), lambda con: con.execute(sql, list(params)).df())


def _as_dt(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, VN_TZ)


def _stale(cached: tuple[float, tuple, Any] | None, why: str) -> ReadResult:
    if cached is None:
        return ReadResult(None, None, stale=True, note=f"{why}; no earlier data in this session")
    return ReadResult(cached[2], _as_dt(cached[0]), stale=True, note=why)
