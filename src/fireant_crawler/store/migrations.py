"""Compare a warehouse with schema.sql and describe the changes before anything is applied.

The reference is schema.sql executed in an in-memory DuckDB; objects are compared by name, columns
and stored view SQL. schema.sql only uses CREATE ... IF NOT EXISTS and CREATE OR REPLACE VIEW, so
applying it can add tables/views/sequences and redefine views, but never alters or drops a table.
A changed table definition is reported as drift and must be migrated by hand.
"""

from dataclasses import dataclass
from importlib import resources
from typing import Literal

import duckdb

ChangeKind = Literal["create_table", "create_view", "replace_view", "create_sequence", "table_drift"]


@dataclass(frozen=True)
class SchemaChange:
    kind: ChangeKind
    name: str
    detail: str = ""

    @property
    def auto_applicable(self) -> bool:
        return self.kind != "table_drift"

    def describe(self) -> str:
        return f"{self.kind:16} {self.name}" + (f"  ({self.detail})" if self.detail else "")


def schema_sql() -> str:
    return resources.files("fireant_crawler.store").joinpath("schema.sql").read_text(encoding="utf-8")


def _tables(con: duckdb.DuckDBPyConnection) -> dict[str, list[tuple[str, str]]]:
    rows = con.execute("""
        SELECT c.table_name, c.column_name, c.data_type FROM duckdb_columns() c
        JOIN duckdb_tables() t ON t.table_name = c.table_name AND t.schema_name = c.schema_name
        WHERE NOT c.internal ORDER BY c.table_name, c.column_index
    """).fetchall()
    out: dict[str, list[tuple[str, str]]] = {}
    for table, column, dtype in rows:
        out.setdefault(table, []).append((column, dtype))
    return out


def _views(con: duckdb.DuckDBPyConnection) -> dict[str, str]:
    return dict(con.execute("SELECT view_name, sql FROM duckdb_views() WHERE NOT internal").fetchall())


def _sequences(con: duckdb.DuckDBPyConnection) -> set[str]:
    return {r[0] for r in con.execute("SELECT sequence_name FROM duckdb_sequences()").fetchall()}


def plan_schema_changes(con: duckdb.DuckDBPyConnection) -> list[SchemaChange]:
    """Read-only: works on a read-only connection."""
    ref = duckdb.connect(":memory:")
    try:
        ref.execute(schema_sql())
        want_tables, want_views, want_seqs = _tables(ref), _views(ref), _sequences(ref)
    finally:
        ref.close()
    have_tables, have_views, have_seqs = _tables(con), _views(con), _sequences(con)

    changes = [SchemaChange("create_sequence", s) for s in sorted(want_seqs - have_seqs)]
    for name, columns in sorted(want_tables.items()):
        if name not in have_tables:
            changes.append(SchemaChange("create_table", name))
        elif have_tables[name] != columns:
            missing = [c for c, _ in columns if c not in dict(have_tables[name])]
            extra = [c for c, _ in have_tables[name] if c not in dict(columns)]
            changes.append(SchemaChange("table_drift", name,
                                        f"missing columns {missing}, extra {extra}, or type/order changes"))
    for name, sql in sorted(want_views.items()):
        if name not in have_views:
            changes.append(SchemaChange("create_view", name))
        elif have_views[name] != sql:
            changes.append(SchemaChange("replace_view", name, "definition changed"))
    return changes


def is_empty(con: duckdb.DuckDBPyConnection) -> bool:
    return not _tables(con)
