"""`quant audit pit`: point-in-time and survivorship audit (docs/execution-audit-plan.md, phase B).

Descriptive only: reads the warehouse and research.duckdb READ_ONLY, writes a report, logs nothing. It measures
the data limits that can bias results (coverage of delisted stocks, stocks that stop trading, attributes known
only at their current value, adjustments, data availability) and how much they move the strategies.
"""

import re
from pathlib import Path
from types import SimpleNamespace

import duckdb
import numpy as np
import pandas as pd

from quant_research import provenance
from quant_research.backtest import runner
from quant_research.backtest.benchmarks import key_matrices
from quant_research.backtest.costs import CostModel
from quant_research.backtest.data import UniverseRule
from quant_research.backtest.engine import run, signal_selector
from quant_research.backtest.metrics import curve_metrics
from quant_research.build import sql_files
from quant_research.results import research_code_hash

INDICES = "('VNINDEX', 'VN30', 'HNXINDEX', 'HNX30', 'UPINDEX')"
SILENT_DAYS = 30                    # calendar days without a trade before the latest session = stopped
WRITEDOWNS = (None, 60, 20)         # sessions without a trade before a position is valued at 0
BAND_LOW, BAND_HIGH = 0.069, 0.15   # moves whose limit flag depends on the exchange band (HOSE 7% .. UPCOM 15%)
FUTURE_TABLES = ("report_marks", "fundamental_snapshots", "stock_targets")


def _df(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None) -> pd.DataFrame:
    return con.execute(sql, params or []).df()


def coverage(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return _df(con, f"""
        WITH t AS (SELECT symbol, year(date) AS year FROM wh.quotes_daily
                   WHERE total_volume > 0 AND symbol NOT IN {INDICES} GROUP BY ALL)
        SELECT t.year, count(*) AS traded_symbols,
               count(*) FILTER (WHERE s.exchange = 'HSX') AS hose_now,
               count(*) FILTER (WHERE s.exchange = 'HNX') AS hnx_now,
               count(*) FILTER (WHERE s.exchange = 'UPCOM') AS upcom_now,
               count(*) FILTER (WHERE NOT s.is_listing) AS delisted_now
        FROM t JOIN wh.symbols s USING (symbol) GROUP BY t.year ORDER BY t.year""").set_index("year")


def stopped(con: duckdb.DuckDBPyConnection) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Symbols whose last trade is more than SILENT_DAYS before the latest session: by status, and the
    listed-but-silent ones (suspended, or trading on a venue the warehouse does not cover)."""
    base = f"""
        WITH latest AS (SELECT max(date) AS d FROM wh.quotes_daily WHERE symbol = 'VNINDEX'),
        liquid AS (SELECT DISTINCT symbol FROM rs.stock_features WHERE adv_value_20 > 1e9 AND is_traded)
        SELECT t.symbol, s.exchange, s.is_listing, t.last_traded_date, symbol IN (SELECT symbol FROM liquid) AS was_liquid
        FROM wh.symbol_trading_span t JOIN wh.symbols s USING (symbol), latest
        WHERE s.type = 'stock' AND t.last_traded_date < latest.d - INTERVAL {SILENT_DAYS} DAY"""
    rows = _df(con, base)
    summary = rows.assign(status=np.where(rows["is_listing"], "listed, silent", "delisted")).groupby("status").agg(
        symbols=("symbol", "count"), ever_liquid=("was_liquid", "sum"))
    silent = rows[rows["is_listing"] & rows["was_liquid"]].sort_values("last_traded_date")
    return summary, silent[["symbol", "exchange", "last_traded_date"]]


def band_sensitivity(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Share of liquid traded rows (research period) whose close move vs the reference price lies between the
    HOSE and UPCOM bands: there the limit flags depend on the (unknown) historical exchange."""
    return _df(con, f"""
        SELECT p.exchange_now, count(*) AS rows,
               avg((abs(p.close_raw / p.basic_raw - 1) BETWEEN {BAND_LOW} AND {BAND_HIGH})::INT) AS band_sensitive
        FROM rs.daily_panel p JOIN rs.stock_features f USING (symbol, date)
        WHERE p.period = 'research' AND f.is_traded AND f.adv_value_20 > 1e9 AND p.basic_raw > 0
        GROUP BY 1 ORDER BY 1""").set_index("exchange_now")


def adjustments(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return _df(con, """SELECT event_type_name AS event, count(*) AS events, min(ex_date)::DATE AS first,
                              max(ex_date)::DATE AS last,
                              count(*) FILTER (WHERE event_type_name = 'cash_dividend' AND cash_per_share_vnd IS NULL)
                                  AS cash_without_amount,
                              count(*) FILTER (WHERE NOT title_parsed) AS title_unparsed
                       FROM wh.corporate_actions GROUP BY 1 ORDER BY 2 DESC""").set_index("event")


def future_tables_in_features() -> list[str]:
    """Feature SQL files that read a table only known later (reports, fundamentals) or the targets."""
    hits = []
    for name, text in sql_files():
        if name.startswith("04_") or name.startswith("05_"):          # the targets and their view by design
            continue
        hits += [f"{name}: {t}" for t in FUTURE_TABLES if re.search(rf"\b{t}\b", text)]
    return hits


def _cagr(equity: np.ndarray) -> float:
    return curve_metrics(equity)["cagr"]


def writedown_sensitivity(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """CAGR of the frozen strategy and of the portfolio grid when stuck positions are written down."""
    from quant_research.daily import FROZEN_STRATEGY
    from quant_research.portfolio.evaluate import CONFIGS, cash_mask, score_matrix
    from quant_research.portfolio.engine import run_targets
    store = SimpleNamespace(con=con)
    full = runner._market(store, "research", UniverseRule())
    market = runner._slice(full, runner._active_window(full))
    rows = []
    for cname, model in (("flat", None), ("v1_k1", CostModel())):
        row = {"strategy": "frozen 72c851c7 (event engine)", "costs": cname}
        row |= {_wd(w): _cagr(run(market, FROZEN_STRATEGY, signal_selector, model, writedown_after=w).equity)
                for w in WRITEDOWNS}
        rows.append(row)
    for name, cfg in CONFIGS.items():
        scores = score_matrix(store, full, cfg.signal)
        has = np.flatnonzero(np.isfinite(scores).any(axis=1))
        window = slice(int(has[0]) if len(has) else 0, len(full.dates))
        m, sc = runner._slice(full, window), scores[window]
        industry = key_matrices(con, m)["industry"]
        cash_on = cash_mask(store, m, cfg.cash_when)
        row = {"strategy": f"portfolio {name}", "costs": "v1_k1"}
        row |= {_wd(w): _cagr(run_targets(m, cfg.construction, lambda i, sc=sc: sc[i], cfg.schedule, 1e9, industry,
                                          cash_on, CostModel(), writedown_after=w).equity) for w in WRITEDOWNS}
        rows.append(row)
    return pd.DataFrame(rows)


def _wd(w: int | None) -> str:
    return "last price" if w is None else f"0 after {w} sessions"


def _md(df: pd.DataFrame, pct: tuple[str, ...] = ()) -> list[str]:
    cols = [str(df.index.name or "")] + [str(c) for c in df.columns] if df.index.name else [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for idx, row in df.iterrows():
        cells = [f"{v:+.1%}" if c in pct and pd.notna(v) else ("-" if pd.isna(v) else
                 f"{v:%Y-%m-%d}" if isinstance(v, pd.Timestamp) else str(v)) for c, v in row.items()]
        lines.append("| " + " | ".join(([str(idx)] if df.index.name else []) + cells) + " |")
    return lines


def render(warehouse: Path, research: Path) -> tuple[str, str]:
    con = duckdb.connect()
    con.execute(f"ATTACH '{warehouse.as_posix()}' AS wh (READ_ONLY)")
    con.execute(f"ATTACH '{research.as_posix()}' AS rs (READ_ONLY)")
    try:
        prov = provenance.collect(con, research_code_hash())
        summary, silent = stopped(con)
        bands = band_sensitivity(con)
        bands["band_sensitive"] = bands["band_sensitive"].map(lambda v: f"{v:.2%}")
        future = future_tables_in_features()
        wd = writedown_sensitivity(con)
        lines = ["# Point-in-time and survivorship audit", "", provenance.line(prov), "",
                 "Descriptive (docs/execution-audit-plan.md, phase B): nothing is tested or logged.", "",
                 "## 1. Coverage: traded symbols per year by today's status", "",
                 "Delisted stocks are present (status OTC / not listing today), so the panel is not survivors-only. "
                 "The exchange columns are today's exchange, not the one of that year.", "",
                 *_md(coverage(con)), "",
                 f"## 2. Stocks that stopped trading (no trade in the last {SILENT_DAYS} days)", "",
                 *_md(summary), "",
                 "Listed but silent and once liquid (suspended, or trading somewhere the warehouse does not "
                 "cover):", "", *_md(silent.head(30).set_index("symbol")), "",
                 "## 3. Attributes known only at today's value", "",
                 "Limit flags use today's exchange band. Share of liquid traded rows (research period) whose close "
                 f"moved {BAND_LOW:.0%} to {BAND_HIGH:.0%} from the reference price, where the band decides the "
                 "flag:", "", *_md(bands), "",
                 "Industry: ICB codes are today's classification for every year (no history in the source).", "",
                 "## 4. Corporate actions (adjustment inputs)", "", *_md(adjustments(con)), "",
                 "## 5. Data availability", "",
                 ("Feature SQL reads no report, fundamental or target table: " + ("none found." if not future else
                  "FOUND " + ", ".join(future))), "",
                 "## 6. Valuation of stuck positions (CAGR, research period, 1 bn VND)", "",
                 "Positions in stocks that stop trading cannot be sold. Default: kept at the last traded price. "
                 "Sensitivity: valued at 0 after N sessions without a trade (sold normally if they trade again).", "",
                 *_md(wd, pct=tuple(_wd(w) for w in WRITEDOWNS))]
        return prov["feature_build_id"] or "unknown", "\n".join(lines)
    finally:
        con.close()
