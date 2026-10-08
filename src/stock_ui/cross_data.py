"""Queries over cross.duckdb for the Cross-stock page (read-only, bound parameters).

Every view takes `as_of`: by default the end of the research period, so that browsing never shows
relations of periods whose cross-stock tests have not run yet (validation 2024-2025, forward).
"""

from datetime import date

import duckdb
import numpy as np
import pandas as pd

from stock_ui.db import Reader, ReadResult

ROLLING = (20, 60, 120)
RESEARCH_END = date(2023, 12, 31)


def symbols(reader: Reader) -> ReadResult:
    return reader.query("cross", "SELECT id, symbol FROM symbols ORDER BY symbol")


def latest_month(reader: Reader, as_of: date) -> ReadResult:
    return reader.read("cross", ("latest_month", as_of), lambda con: con.execute(
        "SELECT max(month_end) FROM corr_snapshots WHERE month_end <= ?", [as_of]).fetchone()[0])


def peers(reader: Reader, symbol: str, as_of: date, limit: int = 20) -> ReadResult:
    """Most correlated stocks at the last snapshot up to as_of (120 sessions), with 60/250 for comparison."""
    return reader.query("cross", """
        WITH me AS (SELECT id FROM symbols WHERE symbol = ?),
        last AS (SELECT max(month_end) AS d FROM corr_snapshots WHERE month_end <= ?),
        c AS (SELECT CASE WHEN s.a = me.id THEN s.b ELSE s.a END AS peer, s.win, s.corr
              FROM corr_snapshots s, me, last WHERE s.month_end = last.d AND (s.a = me.id OR s.b = me.id))
        SELECT p.symbol AS peer,
               max(corr) FILTER (WHERE win = 120) AS corr_120,
               max(corr) FILTER (WHERE win = 60) AS corr_60,
               max(corr) FILTER (WHERE win = 250) AS corr_250,
               (SELECT any_value(industry_l2_code) FROM returns_daily r WHERE r.symbol = p.symbol)
                 = (SELECT any_value(industry_l2_code) FROM returns_daily r WHERE r.symbol = ?) AS same_industry
        FROM c JOIN symbols p ON p.id = c.peer
        GROUP BY p.symbol ORDER BY corr_120 DESC NULLS LAST LIMIT ?""", (symbol, as_of, symbol, limit))


def _pair(con: duckdb.DuckDBPyConnection, a: str, b: str, as_of: date) -> pd.DataFrame:
    df = con.execute("""SELECT x.date, x.ex_cc AS a, y.ex_cc AS b FROM returns_daily x
                        JOIN returns_daily y ON y.date = x.date AND y.symbol = ?
                        WHERE x.symbol = ? AND x.date <= ? ORDER BY x.date""", [b, a, as_of]).df()
    out = pd.DataFrame({"date": df["date"]})
    for w in ROLLING:
        out[f"corr_{w}"] = df["a"].rolling(w, min_periods=int(0.8 * w)).corr(df["b"])
    return out.replace([np.inf, -np.inf], np.nan)


def pair_rolling(reader: Reader, a: str, b: str, as_of: date) -> ReadResult:
    """Daily rolling correlation of the two stocks' excess returns (each window ends on that session)."""
    return reader.read("cross", ("pair", a, b, as_of), lambda con: _pair(con, a, b, as_of))


def clusters(reader: Reader, as_of: date) -> ReadResult:
    return reader.query("cross", """
        WITH last AS (SELECT max(month_end) AS d FROM clusters_monthly WHERE month_end <= ?)
        SELECT c.cluster, count(*) AS stocks, string_agg(s.symbol, ', ' ORDER BY s.symbol) AS members,
               mode(c.industry_l2_code) AS main_industry_l2,
               avg((c.industry_l2_code = m.main)::INT) AS share_main_industry
        FROM clusters_monthly c JOIN last ON c.month_end = last.d JOIN symbols s ON s.id = c.symbol_id
        JOIN (SELECT cluster, mode(industry_l2_code) AS main FROM clusters_monthly, last
              WHERE month_end = last.d GROUP BY 1) m USING (cluster)
        GROUP BY c.cluster ORDER BY stocks DESC""", (as_of,))


def central(reader: Reader, as_of: date, limit: int = 15) -> ReadResult:
    return reader.query("cross", """
        WITH last AS (SELECT max(month_end) AS d FROM centrality_monthly WHERE month_end <= ?)
        SELECT s.symbol, c.avg_corr, c.n_peers FROM centrality_monthly c JOIN last ON c.month_end = last.d
        JOIN symbols s ON s.id = c.symbol_id WHERE c.win = 120 ORDER BY c.avg_corr DESC LIMIT ?""", (as_of, limit))


def cross_runs(reader: Reader) -> ReadResult:
    return reader.query("results", """
        SELECT r.run_id, r.kind, r.pattern_name, r.period, r.status, r.created_at FROM research_runs r
        WHERE r.kind = 'cross' OR r.pattern_name LIKE 'cross\\_%' ESCAPE '\\' ORDER BY r.created_at DESC""")


# Industries (Phase 4b) ---------------------------------------------------------------------------

def industries(reader: Reader) -> ReadResult:
    """ICB level-2 groups that have an index, with display names."""
    return reader.query("cross", """
        SELECT n.group_code, any_value(n.name) AS name, count(g.ew_cc) AS sessions
        FROM group_names n JOIN group_returns_daily g USING (level, group_code)
        WHERE n.level = 'l2' GROUP BY 1 HAVING count(g.ew_cc) > 0 ORDER BY 2""")


def industry_cumulative(reader: Reader, codes: tuple[str, ...], as_of: date) -> ReadResult:
    """Cumulative sum of daily equal-weight excess returns (sessions without an index count as 0)."""
    if not codes:
        return ReadResult(pd.DataFrame(), None, False)
    marks = ", ".join("?" for _ in codes)
    return reader.query("cross", f"""
        SELECT g.date, n.name, sum(coalesce(g.ew_cc, 0)) OVER (PARTITION BY g.group_code ORDER BY g.date) AS cum_excess
        FROM group_returns_daily g JOIN group_names n USING (level, group_code)
        WHERE g.level = 'l2' AND g.group_code IN ({marks}) AND g.date <= ? ORDER BY g.date""", (*codes, as_of))


def industry_corr(reader: Reader, win: int, as_of: date) -> ReadResult:
    return reader.query("cross", """
        WITH last AS (SELECT max(month_end) AS d FROM group_corr_snapshots WHERE level = 'l2' AND month_end <= ?),
        n AS (SELECT group_code, any_value(name) AS name FROM group_names WHERE level = 'l2' GROUP BY 1)
        SELECT last.d AS month_end, na.name AS a, nb.name AS b, s.corr
        FROM group_corr_snapshots s, last JOIN n na ON na.group_code = s.a JOIN n nb ON nb.group_code = s.b
        WHERE s.level = 'l2' AND s.month_end = last.d AND s.win = ?""", (as_of, win))


def _industry_pair(con: duckdb.DuckDBPyConnection, a: str, b: str, as_of: date) -> pd.DataFrame:
    df = con.execute("""SELECT x.date, x.ew_cc AS a, y.ew_cc AS b FROM group_returns_daily x
                        JOIN group_returns_daily y ON y.date = x.date AND y.level = 'l2' AND y.group_code = ?
                        WHERE x.level = 'l2' AND x.group_code = ? AND x.date <= ? ORDER BY x.date""",
                     [b, a, as_of]).df()
    out = pd.DataFrame({"date": df["date"]})
    for w in ROLLING:
        out[f"corr_{w}"] = df["a"].rolling(w, min_periods=int(0.8 * w)).corr(df["b"])
    return out.replace([np.inf, -np.inf], np.nan)


def industry_pair_rolling(reader: Reader, a: str, b: str, as_of: date) -> ReadResult:
    return reader.read("cross", ("industry_pair", a, b, as_of), lambda con: _industry_pair(con, a, b, as_of))


def industry_momentum(reader: Reader, as_of: date) -> ReadResult:
    """Excess return of each industry index over the last 5, 21 and 63 sessions up to as_of."""
    return reader.query("cross", """
        WITH d AS (SELECT date, row_number() OVER (ORDER BY date DESC) AS k
                   FROM (SELECT DISTINCT date FROM group_returns_daily WHERE level = 'l2' AND date <= ?)),
        n AS (SELECT group_code, any_value(name) AS name FROM group_names WHERE level = 'l2' GROUP BY 1)
        SELECT n.name AS industry, max(d.date) AS as_of,
               sum(g.ew_cc) FILTER (WHERE d.k <= 5) AS ret_5d,
               sum(g.ew_cc) FILTER (WHERE d.k <= 21) AS ret_21d,
               sum(g.ew_cc) FILTER (WHERE d.k <= 63) AS ret_63d,
               any_value(g.n_members) FILTER (WHERE d.k = 1) AS members
        FROM group_returns_daily g JOIN d USING (date) JOIN n USING (group_code)
        WHERE g.level = 'l2' AND d.k <= 63 GROUP BY 1 HAVING count(g.ew_cc) FILTER (WHERE d.k <= 21) >= 17
        ORDER BY ret_21d DESC""", (as_of,))
