"""Industry groups (Phase 4b): members, daily industry indexes, correlations, lead-lag, group features.

Point in time: members are fixed at each month end from that day's liquidity (the research universe
filter) and used for the sessions of the next month. An index return on a session averages the members'
returns that session (equal weight; ADV-weighted for comparison) and is NULL with fewer than
MIN_MEMBERS returns. Group features of a stock on a session use only index and stock returns up to it.
"""

import duckdb
import numpy as np
import pandas as pd

from quant_research.cross.matrix import lag_corr, pairwise_corr
from quant_research.cross.params import CrossParams

LEVELS = {"l2": "industry_l2_code", "l3": "industry_l3_code"}
MIN_MEMBERS = 5
MOMENTUM_SESSIONS = 21          # 1 month, for the laggard features

GROUPS_SQL = """
CREATE TABLE group_members_monthly AS
WITH e AS (
    SELECT m.month_end, f.symbol, f.adv_value_20, p.industry_l2_code, p.industry_l3_code
    FROM month_ends m
    JOIN rs.stock_features f ON f.date = m.month_end
    JOIN rs.daily_panel p ON p.symbol = f.symbol AND p.date = f.date
    WHERE f.is_traded AND f.adv_value_20 > ? AND f.session_index > 20 AND NOT f.price_jump
      AND NOT f.bad_source_date)
SELECT month_end, 'l2' AS level, industry_l2_code AS group_code, symbol, adv_value_20 FROM e
WHERE industry_l2_code IS NOT NULL
UNION ALL
SELECT month_end, 'l3', industry_l3_code, symbol, adv_value_20 FROM e WHERE industry_l3_code IS NOT NULL;

CREATE TABLE group_returns_daily AS
WITH r AS (SELECT d.symbol, d.date, d.ex_cc, d.ex_oc, m.month_end
           FROM returns_daily d ASOF JOIN month_ends m ON d.date > m.month_end)
SELECT r.date, g.level, g.group_code,
       CASE WHEN count(r.ex_cc) >= {min_members} THEN avg(r.ex_cc) END AS ew_cc,
       CASE WHEN count(r.ex_cc) >= {min_members}
            THEN sum(r.ex_cc * g.adv_value_20) / sum(g.adv_value_20) FILTER (WHERE r.ex_cc IS NOT NULL) END AS vw_cc,
       CASE WHEN count(r.ex_oc) >= {min_members} THEN avg(r.ex_oc) END AS ew_oc,
       count(r.ex_cc) AS n_members
FROM r JOIN group_members_monthly g ON g.symbol = r.symbol AND g.month_end = r.month_end
GROUP BY 1, 2, 3;
"""

# Laggard features: the stock's industry (level 2) 1-month index return and its tercile among industries
# that day, and whether the stock's own 1-month excess return is in the bottom half of its industry.
GROUP_FEATURES_SQL = """
CREATE TABLE group_features AS
WITH g AS (
    SELECT date, group_code,
           CASE WHEN count(ew_cc) OVER w >= {min_obs} THEN sum(ew_cc) OVER w END AS grp_ret_21
    FROM group_returns_daily WHERE level = 'l2'
    WINDOW w AS (PARTITION BY group_code ORDER BY date ROWS BETWEEN {lookback_m1} PRECEDING AND CURRENT ROW)),
gt AS (SELECT *, ntile(3) OVER (PARTITION BY date ORDER BY grp_ret_21) AS grp_tercile
       FROM g WHERE grp_ret_21 IS NOT NULL),
s AS (
    SELECT d.symbol, d.date,
           CASE WHEN count(d.ex_cc) OVER w >= {min_obs} THEN sum(d.ex_cc) OVER w END AS own_ret_21
    FROM returns_daily d
    WINDOW w AS (PARTITION BY d.symbol ORDER BY d.date ROWS BETWEEN {lookback_m1} PRECEDING AND CURRENT ROW)),
m AS (SELECT s.*, mm.month_end FROM s ASOF JOIN month_ends mm ON s.date > mm.month_end),
j AS (SELECT m.symbol, m.date, gm.group_code, m.own_ret_21, gt.grp_ret_21, gt.grp_tercile
      FROM m JOIN group_members_monthly gm ON gm.symbol = m.symbol AND gm.month_end = m.month_end AND gm.level = 'l2'
      JOIN gt ON gt.date = m.date AND gt.group_code = gm.group_code
      WHERE m.own_ret_21 IS NOT NULL)
SELECT symbol, date, group_code, own_ret_21, grp_ret_21, grp_tercile,
       percent_rank() OVER (PARTITION BY date, group_code ORDER BY own_ret_21) < 0.5 AS own_bottom_half
FROM j
"""


def build_group_tables(con: duckdb.DuckDBPyConnection, params: CrossParams) -> dict[str, int]:
    for sql in GROUPS_SQL.format(min_members=MIN_MEMBERS).split(";"):
        if sql.strip():
            con.execute(sql, [params.min_adv_value] if "rs.stock_features" in sql else [])
    con.execute(GROUP_FEATURES_SQL.format(min_obs=int(0.8 * MOMENTUM_SESSIONS), lookback_m1=MOMENTUM_SESSIONS - 1))
    rows = {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("group_members_monthly", "group_returns_daily", "group_features")}
    corr, ll = [], []
    month_ends = [np.datetime64(r[0], "D") for r in con.execute("SELECT month_end FROM month_ends ORDER BY 1").fetchall()]
    for level in LEVELS:
        dates, codes, cc, oc = _wide(con, level)
        if not codes:
            continue
        corr.append(_corr_snapshots(level, dates, codes, cc, month_ends, params))
        ll.append(_leadlag(level, dates, codes, cc, oc, params))
    rows["group_corr_snapshots"] = _store(con, "group_corr_snapshots", corr)
    rows["group_leadlag_pairs"] = _store(con, "group_leadlag_pairs", ll)
    return rows


def _wide(con: duckdb.DuckDBPyConnection, level: str) -> tuple[np.ndarray, list[str], np.ndarray, np.ndarray]:
    df = con.execute("SELECT date, group_code, ew_cc, ew_oc FROM group_returns_daily WHERE level = ?", [level]).df()
    dates = np.array([r[0] for r in con.execute("SELECT DISTINCT date FROM returns_daily ORDER BY 1").fetchall()],
                     dtype="datetime64[D]")
    codes = sorted(df["group_code"].unique().tolist())
    df["date"] = df["date"].values.astype("datetime64[D]")
    wide = {c: df.pivot(index="date", columns="group_code", values=c).reindex(index=dates, columns=codes)
            .to_numpy(dtype=float) for c in ("ew_cc", "ew_oc")}
    return dates, codes, wide["ew_cc"], wide["ew_oc"]


def _corr_snapshots(level: str, dates: np.ndarray, codes: list[str], cc: np.ndarray, month_ends: list,
                    params: CrossParams) -> pd.DataFrame:
    out = []
    for day in month_ends:
        end = int(np.searchsorted(dates, day)) + 1
        for w in params.windows:
            if end - w < 0:
                continue
            block = cc[end - w:end]
            keep = np.isfinite(block).mean(axis=0) >= params.min_coverage
            idx = np.nonzero(keep)[0]
            if len(idx) < 2:
                continue
            corr, _ = pairwise_corr(block[:, idx], min_obs=int(0.8 * w))
            i, j = np.triu_indices(len(idx), k=1)
            v = corr[i, j]
            ok = np.isfinite(v)
            out.append(pd.DataFrame({"level": level, "month_end": day, "win": w,
                                     "a": [codes[k] for k in idx[i[ok]]], "b": [codes[k] for k in idx[j[ok]]],
                                     "corr": v[ok]}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def _leadlag(level: str, dates: np.ndarray, codes: list[str], cc: np.ndarray, oc: np.ndarray,
             params: CrossParams, min_form: int = 100, min_test: int = 60) -> pd.DataFrame:
    """Directed group pairs per formation year; lead == follow rows are the industry's own autocorrelation."""
    years = dates.astype("datetime64[Y]").astype(int) + 1970
    out = []
    for year in sorted(set(years.tolist()))[:-1]:
        form, test = years == year, years == year + 1
        for lag in params.lags:
            cf, nf = lag_corr(cc[form], cc[form], lag, min_form)
            ct, nt = lag_corr(cc[test], cc[test], lag, min_test)
            co, _ = lag_corr(cc[test], oc[test], lag, min_test)
            fo, _ = lag_corr(cc[form], oc[form], lag, min_form)
            li, fi = np.nonzero(np.isfinite(cf))
            out.append(pd.DataFrame({
                "level": level, "form_year": year, "lag": lag,
                "lead": [codes[k] for k in li], "follow": [codes[k] for k in fi],
                "corr_form": cf[li, fi], "corr_form_oc": fo[li, fi], "n_form": nf[li, fi],
                "corr_test_cc": ct[li, fi], "corr_test_oc": co[li, fi], "n_test": nt[li, fi]}))
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def _store(con: duckdb.DuckDBPyConnection, table: str, frames: list[pd.DataFrame]) -> int:
    frames = [f for f in frames if not f.empty]
    if not frames:
        con.execute(f"CREATE TABLE {table} (level VARCHAR)")
        return 0
    frame = pd.concat(frames, ignore_index=True)
    con.register("frame", frame)
    con.execute(f"CREATE TABLE {table} AS SELECT * FROM frame")
    con.unregister("frame")
    return len(frame)


def add_names(con: duckdb.DuckDBPyConnection, warehouse_attached: bool) -> None:
    """group_names(level, group_code, name) from the warehouse ICB table when available, else the code."""
    if warehouse_attached:
        con.execute("""CREATE TABLE group_names AS
            SELECT DISTINCT g.level, g.group_code, coalesce(i.name, g.group_code) AS name
            FROM group_members_monthly g LEFT JOIN wh.icb_industries i ON i.industry_code = g.group_code""")
    else:
        con.execute("""CREATE TABLE group_names AS
            SELECT DISTINCT level, group_code, group_code AS name FROM group_members_monthly""")
