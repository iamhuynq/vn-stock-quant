"""`quant cross build`: research.duckdb (read-only) -> data/cross.duckdb (derived, rebuilt each time).

Built into a fresh temporary file and atomically moved into place, like `quant build`. Tables:
- symbols(id, symbol), returns_daily, month_ends, universe_monthly, leaders_monthly, cross_features
- corr_snapshots, centrality_monthly, clusters_monthly, leadlag_pairs, coint_pairs, coint_events
- cross_builds (one row per build: params, research build id, code hash, row counts)
"""

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from quant_research.build import file_hash
from quant_research.cross import coint, groups, snapshots
from quant_research.cross.params import INDEX_SYMBOLS, CrossParams
from quant_research.cross.snapshots import Panel


class CrossBuildError(RuntimeError):
    pass


@dataclass
class CrossBuildResult:
    build_id: str
    rows: dict[str, int]
    seconds: float


def cross_code_hash() -> str:
    digest = hashlib.sha256()
    package = resources.files("quant_research.cross")
    for name in sorted(p.name for p in package.iterdir() if p.name.endswith(".py")):
        digest.update(package.joinpath(name).read_bytes())
    return digest.hexdigest()[:16]


RETURNS_SQL = """
CREATE TABLE returns_daily AS
WITH m AS (SELECT date, mkt_open, mkt_close, mkt_ret_1d, lag(date) OVER (ORDER BY date) AS prev_session
           FROM rs.market_daily),
p AS (SELECT symbol, date, period, adj_open, adj_close, industry_l2_code, industry_l3_code,
             is_traded AND NOT price_jump AND NOT bad_source_date AS ok,
             lag(adj_close) OVER w AS prev_close,
             lag(is_traded AND NOT price_jump AND NOT bad_source_date) OVER w AS prev_ok,
             lag(date) OVER w AS prev_date
      FROM rs.daily_panel WINDOW w AS (PARTITION BY symbol ORDER BY date))
SELECT p.symbol, p.date, p.period, p.industry_l2_code, p.industry_l3_code,
       CASE WHEN p.ok THEN p.adj_close END AS adj_close,
       CASE WHEN p.ok AND p.prev_ok AND p.prev_date = m.prev_session AND p.prev_close > 0
            THEN p.adj_close / p.prev_close - 1 END AS raw_cc,
       CASE WHEN p.ok AND p.prev_ok AND p.prev_date = m.prev_session AND p.prev_close > 0
            THEN p.adj_close / p.prev_close - 1 - m.mkt_ret_1d END AS ex_cc,
       CASE WHEN p.ok AND p.adj_open > 0 AND m.mkt_open > 0
            THEN p.adj_close / p.adj_open - m.mkt_close / m.mkt_open END AS ex_oc
FROM p JOIN m USING (date)
WHERE p.symbol NOT IN ({indices}) AND year(p.date) >= ?
"""

UNIVERSE_SQL = """
CREATE TABLE month_ends AS
SELECT max(date) AS month_end FROM rs.market_daily WHERE year(date) >= ? GROUP BY year(date), month(date);
CREATE TABLE universe_monthly AS
SELECT * FROM (
    SELECT m.month_end, f.symbol, f.adv_value_20,
           row_number() OVER (PARTITION BY m.month_end ORDER BY f.adv_value_20 DESC, f.symbol) AS rk
    FROM month_ends m JOIN rs.stock_features f ON f.date = m.month_end
    WHERE f.is_traded AND f.adv_value_20 > ?)
WHERE rk <= ?;
CREATE TABLE leaders_monthly AS
SELECT month_end, symbol, industry_l2_code, rk FROM (
    SELECT u.month_end, u.symbol, r.industry_l2_code,
           row_number() OVER (PARTITION BY u.month_end, r.industry_l2_code ORDER BY u.adv_value_20 DESC, u.symbol) AS rk,
           count(*) OVER (PARTITION BY u.month_end, r.industry_l2_code) AS n_industry
    FROM universe_monthly u JOIN returns_daily r ON r.symbol = u.symbol AND r.date = u.month_end
    WHERE r.industry_l2_code IS NOT NULL)
WHERE rk <= ? AND n_industry > ?;
"""

# Each session uses the leaders, universe and large-cap basket of the latest month end BEFORE it.
FEATURES_SQL = """
CREATE TABLE cross_features AS
WITH r AS (SELECT d.*, m.month_end FROM returns_daily d ASOF JOIN month_ends m ON d.date > m.month_end),
lead AS (SELECT r.date, l.industry_l2_code, avg(r.ex_cc) AS leader_excess_1d, count(r.ex_cc) AS n_leaders
         FROM r JOIN leaders_monthly l ON l.symbol = r.symbol AND l.month_end = r.month_end GROUP BY 1, 2),
large AS (SELECT r.date, avg(r.raw_cc) AS large_ret_1d, count(r.raw_cc) AS n_large
          FROM r JOIN universe_monthly u ON u.symbol = r.symbol AND u.month_end = r.month_end AND u.rk <= ?
          GROUP BY 1)
SELECT r.symbol, r.date, r.month_end AS universe_month, r.industry_l2_code,
       l.symbol IS NOT NULL AS is_leader,
       CASE WHEN ld.n_leaders >= 2 THEN ld.leader_excess_1d END AS leader_excess_1d,
       r.ex_cc AS own_excess_1d,
       CASE WHEN lg.n_large >= ? THEN lg.large_ret_1d END AS large_ret_1d,
       u.symbol IS NOT NULL AS in_cross_universe
FROM r
LEFT JOIN leaders_monthly l ON l.symbol = r.symbol AND l.month_end = r.month_end
LEFT JOIN lead ld ON ld.date = r.date AND ld.industry_l2_code = r.industry_l2_code
LEFT JOIN large lg ON lg.date = r.date
LEFT JOIN universe_monthly u ON u.symbol = r.symbol AND u.month_end = r.month_end
"""


def _load_panel(con: duckdb.DuckDBPyConnection, start_year: int) -> Panel:
    syms = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM universe_monthly ORDER BY 1").fetchall()]
    dates = np.array([r[0] for r in con.execute(
        "SELECT date FROM rs.market_daily WHERE year(date) >= ? ORDER BY date", [start_year]).fetchall()],
        dtype="datetime64[D]")
    df = con.execute("""SELECT symbol, date, ex_cc, ex_oc, ln(adj_close) AS logp FROM returns_daily
                        WHERE symbol IN (SELECT symbol FROM universe_monthly)""").df()
    df["date"] = df["date"].values.astype("datetime64[D]")
    wide = {c: df.pivot(index="date", columns="symbol", values=c).reindex(index=dates, columns=syms)
            .to_numpy(dtype=float) for c in ("ex_cc", "ex_oc", "logp")}
    codes = {s: (a, b) for s, a, b in con.execute("""SELECT symbol, any_value(industry_l2_code),
                 any_value(industry_l3_code) FROM returns_daily GROUP BY 1""").fetchall()}
    l2 = np.array([codes.get(s, (None, None))[0] for s in syms], dtype=object)
    l3 = np.array([codes.get(s, (None, None))[1] for s in syms], dtype=object)
    return Panel(dates, syms, wide["ex_cc"], wide["ex_oc"], wide["logp"], l2, l3)


def _members(con: duckdb.DuckDBPyConnection, ids: dict[str, int], where: str = "TRUE") -> dict:
    out: dict = {}
    for day, symbol in con.execute(f"""SELECT month_end, symbol FROM universe_monthly WHERE {where}
                                       ORDER BY month_end, rk""").fetchall():
        out.setdefault(np.datetime64(day, "D"), []).append(ids[symbol])
    return out


def _write(con: duckdb.DuckDBPyConnection, table: str, chunks: list[dict], columns: list[str]) -> int:
    """Column chunks (dict of equal-length arrays) -> a new table."""
    frame = (pd.DataFrame({c: np.concatenate([ch[c] for ch in chunks]) for c in columns}) if chunks
             else pd.DataFrame({c: pd.Series(dtype=float) for c in columns}))
    return _write_frame(con, table, frame)


def _write_frame(con: duckdb.DuckDBPyConnection, table: str, frame: pd.DataFrame) -> int:
    con.register("frame", frame)
    con.execute(f"CREATE TABLE {table} AS SELECT * FROM frame")
    con.unregister("frame")
    return len(frame)


def _compute(con: duckdb.DuckDBPyConnection, params: CrossParams) -> dict[str, int]:
    panel = _load_panel(con, params.start_year)
    ids = {s: i for i, s in enumerate(panel.symbols)}
    _write_frame(con, "symbols", pd.DataFrame({"id": np.arange(len(panel.symbols), dtype=np.int32),
                                               "symbol": panel.symbols}))
    month_members = _members(con, ids)
    out: dict[str, list] = {"corr": [], "centrality": [], "cluster": []}
    for kind, chunk in snapshots.correlation_snapshots(panel, month_members, params):
        out[kind].append(chunk)
    rows = {"corr_snapshots": _write(con, "corr_snapshots", out["corr"], ["month_end", "win", "a", "b", "corr"]),
            "centrality_monthly": _write(con, "centrality_monthly", out["centrality"],
                                         ["month_end", "win", "symbol_id", "avg_corr", "n_peers"]),
            "clusters_monthly": _write(con, "clusters_monthly", out["cluster"],
                                       ["month_end", "symbol_id", "cluster", "industry_l2_code"])}
    year_end = {}
    for day, cols in month_members.items():
        year_end[int(str(day)[:4])] = cols                           # last month end of each year wins
    ll = list(snapshots.leadlag_pairs(panel, year_end, params))
    rows["leadlag_pairs"] = _write(con, "leadlag_pairs", ll, ["form_year", "lag", "lead", "follow", "corr_form",
                                                             "n_form", "corr_test_cc", "corr_test_oc", "n_test"])
    quarters = {d: c for d, c in month_members.items() if int(str(d)[5:7]) in (3, 6, 9, 12)}
    pairs, events = [], []
    for kind, row in coint.run(panel, quarters, params):
        (pairs if kind == "pair" else events).append(row)
    pair_cols = ["formation_date", "a", "b", "alpha", "beta", "mu", "sigma", "p"]
    event_cols = ["symbol_id", "date", "a", "b", "side", "z", "formation_date", "z_after_10", "z_after_20"]
    rows["coint_pairs"] = _write_frame(con, "coint_pairs", pd.DataFrame(pairs, columns=pair_cols))
    rows["coint_events"] = _write_frame(con, "coint_events", pd.DataFrame(events, columns=event_cols))
    con.execute("""CREATE OR REPLACE TABLE coint_events AS
                   SELECT s.symbol, e.* FROM coint_events e JOIN symbols s ON s.id = e.symbol_id""")
    return rows


def _attach_warehouse(con: duckdb.DuckDBPyConnection, warehouse_path: Path | None) -> bool:
    """Read-only, for industry names only; skipped (codes used as names) if absent or locked by a writer."""
    if warehouse_path is None or not warehouse_path.exists():
        return False
    try:
        con.execute(f"ATTACH '{warehouse_path.as_posix().replace(chr(39), chr(39) * 2)}' AS wh (READ_ONLY)")
    except duckdb.IOException:
        return False
    return True


def build_cross(research_path: Path, cross_path: Path, now: datetime, params: CrossParams = CrossParams(),
                warehouse_path: Path | None = None) -> CrossBuildResult:
    if not research_path.exists():
        raise CrossBuildError(f"No research database at {research_path}; run `quant build`")
    before = file_hash(research_path)
    started = time.monotonic()
    tmp = cross_path.with_name(cross_path.stem + ".building.duckdb")
    for p in (tmp, tmp.with_name(tmp.name + ".wal")):
        p.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        con.execute(f"ATTACH '{research_path.as_posix().replace(chr(39), chr(39) * 2)}' AS rs (READ_ONLY)")
        indices = ", ".join(f"'{s}'" for s in INDEX_SYMBOLS)        # constants, not user input
        con.execute(RETURNS_SQL.format(indices=indices), [params.start_year])
        month_sql, universe_sql, leaders_sql = (q.strip() for q in UNIVERSE_SQL.split(";") if q.strip())
        con.execute(month_sql, [params.start_year])
        con.execute(universe_sql, [params.min_adv_value, params.universe_size])
        con.execute(leaders_sql, [params.n_leaders, params.n_leaders])
        con.execute(FEATURES_SQL, [params.n_large, params.n_large // 2])
        rows = _compute(con, params)
        rows |= groups.build_group_tables(con, params)
        has_wh = _attach_warehouse(con, warehouse_path)
        groups.add_names(con, has_wh)
        if has_wh:
            con.execute("DETACH wh")
        for t in ("returns_daily", "universe_monthly", "leaders_monthly", "cross_features"):
            rows[t] = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        research_build = con.execute("SELECT build_id FROM rs.feature_builds ORDER BY built_at DESC LIMIT 1").fetchone()
        build_id = now.strftime("%Y%m%dT%H%M%S")
        seconds = round(time.monotonic() - started, 2)
        con.execute("""CREATE TABLE cross_builds AS SELECT ? AS build_id, ?::TIMESTAMPTZ AS built_at,
                       ? AS research_build_id, ? AS params, ? AS code_hash, ? AS row_counts, ? AS seconds""",
                    [build_id, now, research_build[0] if research_build else None, json.dumps(params.as_dict()),
                     cross_code_hash(), json.dumps(rows), seconds])
        con.execute("DETACH rs")
        con.execute("CHECKPOINT")
    except BaseException:
        con.close()
        tmp.unlink(missing_ok=True)
        raise
    con.close()
    os.replace(tmp, cross_path)
    if file_hash(research_path) != before:
        raise CrossBuildError("research.duckdb changed during the cross build; this must never happen")
    return CrossBuildResult(build_id, rows, seconds)
