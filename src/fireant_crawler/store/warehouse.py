"""DuckDB warehouse: schema bootstrap and idempotent upserts."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa

from fireant_crawler.store.locking import connect_with_retry
from fireant_crawler.store.migrations import SchemaChange, is_empty, plan_schema_changes, schema_sql

PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    "symbols": ("symbol", "fetched_at"),
    "quotes_daily": ("symbol", "date"),
    "adj_ratio_segments": ("symbol", "fetched_at", "start_date"),
    "corporate_actions": ("event_id",),
    "report_marks": ("symbol", "mark_id"),
    "fundamental_snapshots": ("symbol", "fetched_at"),
    "icb_industries": ("industry_code",),
    "crawl_state": ("job", "key", "chunk"),
}


class SchemaOutOfDateError(RuntimeError):
    def __init__(self, changes: list[SchemaChange]) -> None:
        super().__init__("Warehouse schema differs from schema.sql; run `fireant migrate --dry-run`, then `fireant migrate`")
        self.changes = changes


class Warehouse:
    def __init__(self, path: Path | str, read_only: bool = False) -> None:
        if isinstance(path, Path) and not read_only:
            path.parent.mkdir(parents=True, exist_ok=True)
        self._con = connect_with_retry(path, read_only=read_only)
        self._columns: dict[str, list[str]] = {}

    def close(self) -> None:
        self._con.close()

    def __enter__(self) -> "Warehouse":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        return self._con

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """All writes inside commit together, so a task's data and its checkpoint never diverge."""
        self._con.begin()
        try:
            yield
        except BaseException:
            self._con.rollback()
            raise
        self._con.commit()

    def init_schema(self) -> None:
        """Apply schema.sql (adds tables/views/sequences, redefines views; never alters or drops tables)."""
        self._con.execute(schema_sql())

    def pending_schema_changes(self) -> list[SchemaChange]:
        return plan_schema_changes(self._con)

    def ensure_schema_for_write(self) -> None:
        """Bootstrap an empty warehouse; otherwise refuse to write while schema changes are pending."""
        if is_empty(self._con):
            self.init_schema()
            return
        changes = self.pending_schema_changes()
        if changes:
            raise SchemaOutOfDateError(changes)

    def upsert(self, table: str, rows: list[dict[str, Any]]) -> int:
        """Insert or replace by primary key. Within a batch the last row per key wins."""
        if table not in PRIMARY_KEYS:
            raise ValueError(f"Unknown table: {table}")
        if not rows:
            return 0
        columns = self._table_columns(table)
        unknown = set().union(*rows) - set(columns)
        if unknown:
            raise ValueError(f"{table}: unknown columns {sorted(unknown)}")

        key_columns = PRIMARY_KEYS[table]
        deduped = {tuple(r.get(k) for k in key_columns): r for r in rows}
        arrow = pa.Table.from_pylist([{c: r.get(c) for c in columns} for r in deduped.values()])
        self._con.register("_incoming", arrow)
        try:
            column_list = ", ".join(columns)
            self._con.execute(f"INSERT OR REPLACE INTO {table} ({column_list}) SELECT {column_list} FROM _incoming")
        finally:
            self._con.unregister("_incoming")
        return len(deduped)

    def count(self, table: str) -> int:
        if table not in PRIMARY_KEYS:
            raise ValueError(f"Unknown table: {table}")
        return self._con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def _table_columns(self, table: str) -> list[str]:
        if table not in self._columns:
            rows = self._con.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = ? ORDER BY ordinal_position",
                [table],
            ).fetchall()
            self._columns[table] = [r[0] for r in rows]
        return self._columns[table]
