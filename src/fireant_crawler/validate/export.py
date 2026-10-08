"""Export warehouse tables and views to Parquet for research (pandas / polars / duckdb)."""

from pathlib import Path

import duckdb

EXPORTS: tuple[str, ...] = (
    "quotes_daily",
    "quotes_daily_adjusted",
    "adj_ratio_segments",
    "corporate_actions",
    "report_marks",
    "fundamental_snapshots",
    "symbols_latest",
    "symbol_trading_span",
    "icb_industries",
    "symbol_industry",
)


def export_parquet(con: duckdb.DuckDBPyConnection, out_dir: Path) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for name in EXPORTS:
        target = out_dir / f"{name}.parquet"
        tmp = target.with_suffix(".parquet.tmp")
        con.execute(f"COPY (SELECT * FROM {name}) TO '{tmp.as_posix()}' (FORMAT parquet, COMPRESSION zstd)")
        tmp.replace(target)
        written[name] = con.execute(f"SELECT count(*) FROM read_parquet('{target.as_posix()}')").fetchone()[0]
    return written
