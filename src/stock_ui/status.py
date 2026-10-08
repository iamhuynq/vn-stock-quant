"""Facts for the Overview page. Files are read directly; databases only through the read-only Reader."""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from fireant_crawler.client.token_info import inspect_token
from fireant_crawler.store.migrations import plan_schema_changes
from stock_ui.db import Reader, ReadResult
from stock_ui.locks import LockInfo, lock_info

LAUNCHD_PLIST = Path.home() / "Library" / "LaunchAgents" / "com.stock.daily.plist"
INDEX_SYMBOLS = ("VNINDEX", "VN30", "HNXINDEX", "HNX30", "UPINDEX")   # same list as 02b_source_coverage.sql
TOKEN_WARN_DAYS = 14


@dataclass(frozen=True)
class PipelineStatus:
    done_session: str | None
    lock: LockInfo | None
    last_log: Path | None
    last_log_lines: list[str]
    launchd_installed: bool


def pipeline(data_dir: Path, plist: Path = LAUNCHD_PLIST) -> PipelineStatus:
    marker = data_dir / ".daily_done"
    done = marker.read_text().strip() if marker.exists() else None
    logs = sorted((data_dir / "logs").glob("daily-*.log"))
    last = logs[-1] if logs else None
    lines = last.read_text(errors="replace").splitlines()[-8:] if last else []
    return PipelineStatus(done, lock_info(data_dir), last, lines, plist.exists())


@dataclass(frozen=True)
class TokenStatus:
    present: bool
    is_jwt: bool
    expires_at: datetime | None
    days_left: float | None
    orders_write: bool

    @property
    def warning(self) -> str | None:
        if not self.present:
            return "FIREANT_TOKEN is not set in .env"
        if self.days_left is not None and self.days_left <= 0:
            return "token expired: paste a fresh one into .env"
        if self.days_left is not None and self.days_left < TOKEN_WARN_DAYS:
            return f"token expires in {self.days_left:.0f} days"
        return None


def token(value: str | None, now: datetime) -> TokenStatus:
    """Only expiry and scopes leave this function; the token string never does."""
    if not value:
        return TokenStatus(False, False, None, None, False)
    info = inspect_token(value)
    days = (info.expires_at - now).total_seconds() / 86400 if info.expires_at else None
    return TokenStatus(True, info.is_jwt, info.expires_at, days, "orders-write" in info.scopes)


def disk(data_dir: Path) -> list[tuple[str, int]]:
    out = []
    for name in ("raw", "warehouse.duckdb", "research.duckdb", "results.duckdb", "parquet", "reports", "logs"):
        p = data_dir / name
        if p.is_file():
            out.append((name, p.stat().st_size))
        elif p.is_dir():
            out.append((name, sum(f.stat().st_size for f in p.rglob("*") if f.is_file())))
    return out


_ROW = re.compile(r"^\| (\w+) \| (error|warn|info) \| ([\d,]+) \|")


def latest_validation(data_dir: Path) -> tuple[Path, dict[str, int], list[str]] | None:
    """Newest validation report: count of failing checks per severity, and the failing error checks."""
    reports = sorted((data_dir / "reports").glob("validation-*.md"))
    if not reports:
        return None
    counts = {"error": 0, "warn": 0, "info": 0}
    errors = []
    for line in reports[-1].read_text().splitlines():
        m = _ROW.match(line)
        if m and int(m.group(3).replace(",", "")) > 0:
            counts[m.group(2)] += 1
            if m.group(2) == "error":
                errors.append(m.group(1))
    return reports[-1], counts, errors


def _warehouse_facts(con: duckdb.DuckDBPyConnection) -> dict:
    marks = ", ".join("?" for _ in INDEX_SYMBOLS)
    sessions = con.execute(f"""
        SELECT date, count(*) FROM quotes_daily
        WHERE symbol NOT IN ({marks}) AND date >= (SELECT max(date) - INTERVAL 20 DAY FROM quotes_daily)
        GROUP BY date ORDER BY date DESC LIMIT 2""", list(INDEX_SYMBOLS)).fetchall()
    failed = con.execute("""SELECT job, key, chunk, last_error, updated_at FROM crawl_state
                            WHERE status = 'failed' ORDER BY updated_at DESC LIMIT 10""").df()
    return {
        "latest_date": sessions[0][0] if sessions else None,
        "latest_rows": sessions[0][1] if sessions else 0,
        "previous_rows": sessions[1][1] if len(sessions) > 1 else None,
        "fetched_at": con.execute("SELECT max(fetched_at) FROM quotes_daily").fetchone()[0],
        "last_api_call": con.execute("SELECT max(logged_at) FROM crawl_log").fetchone()[0],
        "failed_count": con.execute("SELECT count(*) FROM crawl_state WHERE status = 'failed'").fetchone()[0],
        "failed": failed,
        "schema_changes": [c.describe() for c in plan_schema_changes(con)],
    }


def warehouse(reader: Reader) -> ReadResult:
    return reader.read("warehouse", "overview", _warehouse_facts)


def coverage(facts: dict) -> float | None:
    prev = facts.get("previous_rows")
    return facts["latest_rows"] / prev if prev else None


def research(reader: Reader) -> ReadResult:
    return reader.query("research", """SELECT build_id, feature_set_version, built_at, data_as_of,
        warehouse_fetched_at, feature_rows, seconds FROM feature_builds ORDER BY built_at DESC LIMIT 1""")


def _daily_facts(con: duckdb.DuckDBPyConnection) -> dict | None:
    has = con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'daily_scans'").fetchone()[0]
    if not has:
        return None
    return {"scans": con.execute("""SELECT scan_date, status, coverage, is_forward, n_events, scanned_at
                                    FROM daily_scans ORDER BY scan_date DESC LIMIT 5""").df()}


def daily(reader: Reader) -> ReadResult:
    return reader.read("results", "daily_overview", _daily_facts)


def latest_report(data_dir: Path) -> Path | None:
    reports = sorted((data_dir / "reports" / "daily").glob("*.md"))
    return reports[-1] if reports else None


def is_current_build(build_fetched_at, warehouse_fetched_at) -> bool | None:
    if build_fetched_at is None or warehouse_fetched_at is None:
        return None
    return _utc(build_fetched_at) == _utc(warehouse_fetched_at)


def _utc(value) -> datetime:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day)
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
