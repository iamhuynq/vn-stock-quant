"""Queries for the Market watch page (read-only, bound parameters). Uses the latest data on purpose:
the page is for monitoring, not for building hypotheses (the research pages keep their 2023 cap)."""

from datetime import date

import duckdb
import numpy as np
import pandas as pd

from stock_ui.db import Reader, ReadResult

AVOID_PATTERN = "drop3_volume2_sellers"
DOWNSIDE_EVENTS = ("ORDER_IMBALANCE_SPIKE_SELL", "BREAKDOWN", "PRICE_DROP", "DIVERGENCE_DOWN_FOREIGN_BUY",
                   "FOREIGN_SELL_SPIKE")
LIQUID_ADV = 1e9
TOGETHER = 0.6          # correlation at which two holdings behave like one position


def header(reader: Reader) -> ReadResult:
    """Latest data date, regime, VNINDEX now and 5 sessions earlier."""
    return reader.query("research", """
        WITH m AS (SELECT date, market_regime, mkt_close, row_number() OVER (ORDER BY date DESC) AS k FROM market_daily)
        SELECT max(date) FILTER (WHERE k = 1) AS date, any_value(market_regime) FILTER (WHERE k = 1) AS regime,
               any_value(mkt_close) FILTER (WHERE k = 1) AS vnindex,
               any_value(mkt_close) FILTER (WHERE k = 6) AS vnindex_5ago FROM m WHERE k <= 6""")


def avoid(reader: Reader) -> ReadResult:
    """Validated avoid signal over the last 5 scanned sessions, and the recorded validation decision."""
    def run(con: duckdb.DuckDBPyConnection) -> dict | None:
        has = con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'daily_scans'").fetchone()[0]
        if not has:
            return None
        days = [r[0] for r in con.execute("""SELECT scan_date FROM daily_scans WHERE status = 'scanned'
                                             ORDER BY scan_date DESC LIMIT 5""").fetchall()]
        events = con.execute("""SELECT scan_date, symbol, return_1d, volume_ratio_20, order_imbalance FROM daily_events
                                WHERE pattern = ? AND scan_date IN (SELECT unnest(?::DATE[]))
                                ORDER BY scan_date DESC, symbol""", [AVOID_PATTERN, days]).df()
        decision = con.execute("SELECT decision, reason FROM validation_decisions WHERE pattern = ?",
                               [AVOID_PATTERN]).fetchone()
        return {"days": days, "events": events, "decision": decision}
    return reader.read("results", "watch_avoid", run)


def events_on(reader: Reader, day: date) -> ReadResult:
    """All catalog events of one session with liquidity, from research.duckdb."""
    return reader.query("research", """
        SELECT e.symbol, e.event_type, e.direction, e.event_score, f.adv_value_20, f.exchange_now, f.return_1d
        FROM stock_events e JOIN stock_features f USING (symbol, date)
        WHERE e.date = ? ORDER BY e.symbol, e.event_type""", (day,))


def event_history(reader: Reader) -> ReadResult:
    """Latest event study: mean and win rate of the execution excess return over 10 sessions, per event."""
    def run(con: duckdb.DuckDBPyConnection) -> pd.DataFrame | None:
        has = con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'event_study_stats'").fetchone()[0]
        if not has:
            return None
        return con.execute("""
            SELECT event_type, mean, win_rate FROM event_study_stats
            WHERE segment = 'all' AND horizon = 'exec_excess_10d' AND run_id = (
                SELECT run_id FROM research_runs WHERE kind = 'event_study' AND status = 'ok'
                ORDER BY created_at DESC LIMIT 1)""").df()
    return reader.read("results", "watch_event_history", run)


def industry_of(reader: Reader) -> ReadResult:
    return reader.query("warehouse", "SELECT symbol, industry_l2 FROM symbol_industry")


def warnings_table(events: pd.DataFrame, history: pd.DataFrame | None, industry: dict[str, str],
                   liquid_only: bool) -> pd.DataFrame:
    """One row per symbol with downside events, sorted by number of flags (then liquidity)."""
    ev = events[events["event_type"].isin(DOWNSIDE_EVENTS)]
    if liquid_only:
        ev = ev[ev["adv_value_20"] > LIQUID_ADV]
    if ev.empty:
        return pd.DataFrame(columns=["symbol", "flags", "events", "industry", "adv_value_20", "return_1d",
                                     "hist_mean_10d"])
    hist = {} if history is None else dict(zip(history["event_type"], history["mean"]))
    out = ev.groupby("symbol").agg(flags=("event_type", "count"),
                                   events=("event_type", lambda s: ", ".join(sorted(s))),
                                   adv_value_20=("adv_value_20", "first"), return_1d=("return_1d", "first"),
                                   hist_mean_10d=("event_type", lambda s: float(np.mean([hist.get(x, np.nan)
                                                                                           for x in s]))))
    out = out.reset_index()
    out.insert(3, "industry", out["symbol"].map(industry))
    return out.sort_values(["flags", "adv_value_20"], ascending=[False, False]).reset_index(drop=True)


def watch_corr(reader: Reader, symbols: tuple[str, ...]) -> ReadResult:
    """Pairwise 120-session correlations among the watchlist at the latest snapshot."""
    if len(symbols) < 2:
        return ReadResult(pd.DataFrame(columns=["a", "b", "corr"]), None, False)
    marks = ", ".join("?" for _ in symbols)
    return reader.query("cross", f"""
        WITH ids AS (SELECT id, symbol FROM symbols WHERE symbol IN ({marks})),
        last AS (SELECT max(month_end) AS d FROM corr_snapshots)
        SELECT sa.symbol AS a, sb.symbol AS b, s.corr, last.d AS snapshot
        FROM corr_snapshots s, last JOIN ids sa ON sa.id = s.a JOIN ids sb ON sb.id = s.b
        WHERE s.month_end = last.d AND s.win = 120""", symbols)


def groups(pairs: pd.DataFrame, threshold: float = TOGETHER) -> list[list[str]]:
    """Connected groups of symbols whose pairwise correlation reaches the threshold (union-find)."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b, c in pairs[["a", "b", "corr"]].itertuples(index=False):
        if c is not None and c >= threshold:
            parent[find(a)] = find(b)
    out: dict[str, list[str]] = {}
    for x in parent:
        out.setdefault(find(x), []).append(x)
    return sorted((sorted(g) for g in out.values() if len(g) > 1), key=len, reverse=True)


def top_pairs(reader: Reader, limit: int = 20) -> ReadResult:
    return reader.query("cross", """
        WITH last AS (SELECT max(month_end) AS d FROM corr_snapshots)
        SELECT sa.symbol AS a, sb.symbol AS b, s.corr, last.d AS snapshot
        FROM corr_snapshots s, last JOIN symbols sa ON sa.id = s.a JOIN symbols sb ON sb.id = s.b
        WHERE s.month_end = last.d AND s.win = 120 ORDER BY s.corr DESC LIMIT ?""", (limit,))
