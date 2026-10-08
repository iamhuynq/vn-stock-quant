"""Task plans for each job. A plan yields task batches; later batches may depend on earlier ones
(the universe job discovers delisted candidates from corporate actions after listing search runs)."""

import re
import string
from collections.abc import Callable, Iterator
from datetime import date, timedelta
from functools import partial
from typing import Literal

from fireant_crawler.client.fireant_client import ApiError
from fireant_crawler.jobs.runner import JobContext, Task

Mode = Literal["backfill", "update"]

HISTORY_START = date(2000, 1, 1)
INDEX_SYMBOLS = ("VNINDEX", "VN30", "HNXINDEX", "HNX30", "UPINDEX")
LISTED_EXCHANGES = ("HSX", "HNX", "UPCOM")
SEARCH_KEYWORDS = tuple(string.ascii_uppercase + string.digits)
PAGE_SIZE = 5000
MAX_PAGES = 20
UPDATE_OVERLAP_DAYS = 20
DELISTED_STALE_DAYS = 60
EVENTS_HORIZON_DAYS = 120
_VALID_SYMBOL = re.compile(r"^[A-Z0-9-]{1,30}$")

ALL_JOBS = ("corporate_actions", "universe", "icb", "quotes", "report_marks", "fundamental")
UPDATE_DEFAULT_JOBS = ("corporate_actions", "quotes")


# ---------- targets ----------

def stock_symbols(ctx: JobContext, listed_only: bool = False) -> list[str]:
    """Stocks on HSX/HNX/UPCOM, plus (unless listed_only) delisted stocks that ever had a corporate action."""
    sql = """
        SELECT symbol FROM symbols_latest
        WHERE type = 'stock' AND (exchange IN ('HSX', 'HNX', 'UPCOM')
              OR (NOT ? AND symbol IN (SELECT symbol FROM corporate_actions)))
        ORDER BY symbol
    """
    return [r[0] for r in ctx.warehouse.connection.execute(sql, [listed_only]).fetchall()]


def resolve_targets(ctx: JobContext, job: str, explicit: list[str] | None) -> list[str]:
    if explicit:
        # Indices have no reports or fundamentals (the API answers 500), so drop them for those jobs.
        return explicit if job == "quotes" else [s for s in explicit if s not in INDEX_SYMBOLS]
    if job == "quotes":
        return list(INDEX_SYMBOLS) + stock_symbols(ctx)
    if job == "report_marks":
        return stock_symbols(ctx)
    if job == "fundamental":
        return stock_symbols(ctx, listed_only=True)
    raise ValueError(f"Job {job} has no per-symbol targets")


# ---------- market-wide jobs ----------

def _fetch_events(ctx: JobContext) -> int:
    end = ctx.today + timedelta(days=EVENTS_HORIZON_DAYS)
    written = 0
    for page in range(MAX_PAGES):
        envelope, n = ctx.fetch_and_ingest(
            "corporate_actions", "all", f"{ctx.today}-p{page:02d}", "/events/search",
            {"startDate": HISTORY_START.isoformat(), "endDate": end.isoformat(),
             "offset": page * PAGE_SIZE, "limit": PAGE_SIZE},
        )
        written += n
        if len(envelope["data"]) < PAGE_SIZE:
            return written
    raise ApiError(f"events/search exceeded {MAX_PAGES} pages", None, "/events/search")


def plan_corporate_actions(ctx: JobContext) -> Iterator[list[Task]]:
    yield [Task("corporate_actions", "all", ctx.today.isoformat(), _fetch_events)]


def plan_icb(ctx: JobContext) -> Iterator[list[Task]]:
    run = lambda c: c.fetch_and_ingest("icb", "all", c.today.isoformat(), "/icb")[1]
    yield [Task("icb", "all", ctx.today.isoformat(), run)]


def _search(keyword: str, ctx: JobContext) -> int:
    return ctx.fetch_and_ingest("universe", "search", f"{ctx.today}-{keyword}", "/symbols/search",
                                {"keywords": keyword, "type": "stock", "limit": PAGE_SIZE})[1]


def _symbol_info(symbol: str, ctx: JobContext) -> int:
    return ctx.fetch_and_ingest("universe", symbol, "info", f"/symbols/{symbol}")[1]


def delisted_candidates(ctx: JobContext) -> list[str]:
    rows = ctx.warehouse.connection.execute("""
        SELECT DISTINCT symbol FROM corporate_actions
        WHERE symbol NOT IN (SELECT symbol FROM symbols_latest WHERE exchange IN ('HSX', 'HNX', 'UPCOM'))
        ORDER BY symbol
    """).fetchall()
    return [r[0] for r in rows if _VALID_SYMBOL.match(r[0])]


def plan_universe(ctx: JobContext) -> Iterator[list[Task]]:
    today = ctx.today.isoformat()
    batch = [Task("universe", "search", f"{today}-{k}", partial(_search, k)) for k in SEARCH_KEYWORDS]
    batch.append(Task("universe", "instruments", today,
                      lambda c: c.fetch_and_ingest("universe", "instruments", today, "/instruments")[1]))
    batch += [Task("universe", s, "info", partial(_symbol_info, s)) for s in INDEX_SYMBOLS]
    yield batch
    if not ctx.warehouse.count("corporate_actions"):
        ctx.log("  [universe] corporate_actions is empty: run that job first to discover delisted symbols")
        return
    yield [Task("universe", s, "info", partial(_symbol_info, s)) for s in delisted_candidates(ctx)]


# ---------- per-symbol jobs ----------

def _fetch_quotes(ctx: JobContext, symbol: str, start: date, chunk: str) -> tuple[list[dict], int]:
    rows, written = [], 0
    for page in range(MAX_PAGES):
        envelope, n = ctx.fetch_and_ingest(
            "quotes", symbol, f"{chunk}-p{page:02d}", f"/symbols/{symbol}/historical-quotes",
            {"startDate": start.isoformat(), "endDate": ctx.today.isoformat(),
             "offset": page * PAGE_SIZE, "limit": PAGE_SIZE},
        )
        rows += envelope["data"]
        written += n
        if len(envelope["data"]) < PAGE_SIZE:
            return rows, written
    raise ApiError(f"{symbol}: historical-quotes exceeded {MAX_PAGES} pages", None, symbol)


def _quotes_full(symbol: str, ctx: JobContext) -> int:
    return _fetch_quotes(ctx, symbol, HISTORY_START, "full")[1]


def _quotes_update(symbol: str, ctx: JobContext) -> int:
    con = ctx.warehouse.connection
    last = con.execute("SELECT max(date) FROM quotes_daily WHERE symbol = ?", [symbol]).fetchone()[0]
    if last is None:
        return _quotes_full(symbol, ctx)
    if _is_stale_delisted(ctx, symbol):
        return -1
    start = last - timedelta(days=UPDATE_OVERLAP_DAYS)
    stored = dict(con.execute("SELECT date, adj_ratio FROM quotes_daily WHERE symbol = ? AND date >= ?",
                              [symbol, start]).fetchall())
    fresh, written = _fetch_quotes(ctx, symbol, start, f"update-{ctx.today}")
    if _adj_ratio_changed(stored, fresh):
        ctx.log(f"  [quotes] {symbol}: adj_ratio changed (corporate action) -> full refetch")
        written += _fetch_quotes(ctx, symbol, HISTORY_START, f"refetch-{ctx.today}")[1]
    return written


def _adj_ratio_changed(stored: dict[date, float | None], fresh: list[dict]) -> bool:
    """A new corporate action rewrites adjRatio for every earlier session, including the overlap window."""
    for row in fresh:
        old = stored.get(date.fromisoformat(str(row["date"])[:10]))
        if old is not None and old != row.get("adjRatio"):
            return True
    return False


def _is_stale_delisted(ctx: JobContext, symbol: str) -> bool:
    row = ctx.warehouse.connection.execute("""
        SELECT s.exchange, t.last_traded_date
        FROM symbols_latest s LEFT JOIN symbol_trading_span t USING (symbol)
        WHERE s.symbol = ?
    """, [symbol]).fetchone()
    if row is None or row[0] in LISTED_EXCHANGES or symbol in INDEX_SYMBOLS:
        return False
    last_traded = row[1]
    return last_traded is None or last_traded < ctx.today - timedelta(days=DELISTED_STALE_DAYS)


def _report_marks(symbol: str, chunk: str, ctx: JobContext) -> int:
    return ctx.fetch_and_ingest("report_marks", symbol, chunk, f"/symbols/{symbol}/timescale-marks",
                                {"startDate": HISTORY_START.isoformat(), "endDate": ctx.today.isoformat()})[1]


def _fundamental(symbol: str, ctx: JobContext) -> int:
    return ctx.fetch_and_ingest("fundamental", symbol, ctx.today.isoformat(), f"/symbols/{symbol}/fundamental")[1]


def plan_per_symbol(ctx: JobContext, job: str, mode: Mode, symbols: list[str]) -> Iterator[list[Task]]:
    today = ctx.today.isoformat()
    builders: dict[str, Callable[[str], Task]] = {
        "quotes": (lambda s: Task("quotes", s, "full", partial(_quotes_full, s))) if mode == "backfill"
        else (lambda s: Task("quotes", s, f"update-{today}", partial(_quotes_update, s))),
        "report_marks": (lambda s: Task("report_marks", s, "full" if mode == "backfill" else today,
                                        partial(_report_marks, s, "full" if mode == "backfill" else today))),
        "fundamental": lambda s: Task("fundamental", s, today, partial(_fundamental, s)),
    }
    yield [builders[job](s) for s in symbols]


def plan(ctx: JobContext, job: str, mode: Mode, symbols: list[str] | None) -> Iterator[list[Task]]:
    if job == "corporate_actions":
        return plan_corporate_actions(ctx)
    if job == "icb":
        return plan_icb(ctx)
    if job == "universe":
        return plan_universe(ctx)
    if job in ("quotes", "report_marks", "fundamental"):
        return plan_per_symbol(ctx, job, mode, resolve_targets(ctx, job, symbols))
    raise ValueError(f"Unknown job: {job}")
