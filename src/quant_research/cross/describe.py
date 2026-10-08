"""Descriptive cross-stock report (no trading claims, nothing logged as a hypothesis).

Restricted to the research period (snapshots up to 2023-12-31) so that describing the data never
shows validation-period relations before they are tested.
"""

from datetime import datetime

import duckdb
import numpy as np
import pandas as pd
from scipy import stats as sps

from quant_research.cross.matrix import adjusted_rand_index

RESEARCH_END = "2023-12-31"
OUTCOME_MARGIN_DAYS = 40       # 20 sessions after an event stay inside the research period
STABILITY_LAG_MONTHS = 12


def _md(df: pd.DataFrame, floatfmt: str = "{:.3f}") -> list[str]:
    if df.empty:
        return ["_none_", ""]
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in df.itertuples(index=False):
        out.append("| " + " | ".join(floatfmt.format(v) if isinstance(v, float) else str(v) for v in row) + " |")
    return out + [""]


def matrix_stability(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Correlation between a month's pair correlations and the same pairs 12 months later, per window."""
    return con.execute(f"""
        WITH m AS (SELECT month_end, row_number() OVER (ORDER BY month_end) AS k
                   FROM (SELECT DISTINCT month_end FROM corr_snapshots WHERE month_end <= DATE '{RESEARCH_END}')),
        c AS (SELECT s.*, m.k FROM corr_snapshots s JOIN m USING (month_end))
        SELECT a.win AS window, count(DISTINCT a.month_end) AS months, avg(r) AS avg_corr_of_corr FROM (
            SELECT x.win, x.month_end, corr(x.corr, y.corr) AS r FROM c x
            JOIN c y ON y.a = x.a AND y.b = x.b AND y.win = x.win AND y.k = x.k + {STABILITY_LAG_MONTHS}
            GROUP BY 1, 2 HAVING count(*) >= 10) a
        WHERE isfinite(r) GROUP BY 1 ORDER BY 1""").df()


def level_by_year(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute(f"""SELECT year(month_end) AS year, count(DISTINCT a) AS stocks, avg(corr) AS avg_corr,
                                  quantile_cont(corr, 0.9) AS p90_corr
                           FROM corr_snapshots WHERE win = 120 AND month(month_end) = 12
                             AND month_end <= DATE '{RESEARCH_END}' GROUP BY 1 ORDER BY 1""").df()


def stable_pairs(con: duckdb.DuckDBPyConnection, limit: int = 15) -> pd.DataFrame:
    """Pairs are stored in a canonical orientation (a < b), so one pair is one group."""
    return con.execute(f"""SELECT sa.symbol AS a, sb.symbol AS b, count(*) AS snapshots, avg(corr) AS mean_corr,
                                  stddev_samp(corr) AS std_corr, min(corr) AS min_corr
                           FROM corr_snapshots c JOIN symbols sa ON sa.id = c.a JOIN symbols sb ON sb.id = c.b
                           WHERE win = 120 AND month_end <= DATE '{RESEARCH_END}'
                           GROUP BY 1, 2 HAVING count(*) >= 36 ORDER BY mean_corr DESC LIMIT {int(limit)}""").df()


def clusters_vs_industry(con: duckdb.DuckDBPyConnection, seed: int = 7) -> pd.DataFrame:
    rows = con.execute(f"""SELECT month_end, cluster, industry_l2_code FROM clusters_monthly
                           WHERE month(month_end) = 12 AND month_end <= DATE '{RESEARCH_END}'
                             AND industry_l2_code IS NOT NULL ORDER BY month_end""").df()
    rng = np.random.default_rng(seed)
    out = []
    for day, g in rows.groupby("month_end"):
        ind = g["industry_l2_code"].to_numpy()
        out.append({"year": pd.Timestamp(day).year, "stocks": len(g),
                    "ari_vs_icb": adjusted_rand_index(g["cluster"].to_numpy(), ind),
                    "ari_shuffled": adjusted_rand_index(g["cluster"].to_numpy(), rng.permutation(ind))})
    return pd.DataFrame(out)


def central_stocks(con: duckdb.DuckDBPyConnection, limit: int = 10) -> pd.DataFrame:
    return con.execute(f"""SELECT s.symbol, count(*) AS snapshots, avg(avg_corr) AS mean_avg_corr
                           FROM centrality_monthly c JOIN symbols s ON s.id = c.symbol_id
                           WHERE win = 120 AND month_end <= DATE '{RESEARCH_END}'
                           GROUP BY 1 HAVING count(*) >= 24 ORDER BY 3 DESC LIMIT {int(limit)}""").df()


def leadlag_overview(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute("""SELECT lag, count(*) AS pairs, avg(corr_form) AS mean_corr,
                                 avg((corr_form > 0)::INT) AS share_positive, quantile_cont(corr_form, 0.9) AS p90
                          FROM leadlag_pairs WHERE form_year <= 2023 GROUP BY 1 ORDER BY 1""").df()


def persistent_pairs(con: duckdb.DuckDBPyConnection, limit: int = 15) -> pd.DataFrame:
    """Directed lag-1 pairs most often in the top decile of their formation year (descriptive)."""
    return con.execute(f"""
        WITH r AS (SELECT form_year, lead, follow, corr_form,
                          percent_rank() OVER (PARTITION BY form_year ORDER BY corr_form DESC) AS pr
                   FROM leadlag_pairs WHERE lag = 1 AND form_year <= 2023)
        SELECT sl.symbol AS lead, sf.symbol AS follow, count(*) AS top_decile_years, avg(corr_form) AS mean_lag1_corr
        FROM r JOIN symbols sl ON sl.id = r.lead JOIN symbols sf ON sf.id = r.follow
        WHERE pr < 0.1 GROUP BY 1, 2 HAVING count(*) >= 4 ORDER BY 3 DESC, 4 DESC LIMIT {int(limit)}""").df()


def granger_p(y: np.ndarray, x: np.ndarray, lags: int) -> float | None:
    """F-test p of x's lags 1..lags on y given y's own lags; series are aligned by session (NaN = missing),
    so a lag is always one session, never a gap."""
    cols = [y] + [np.roll(y, k) for k in range(1, lags + 1)] + [np.roll(x, k) for k in range(1, lags + 1)]
    m = np.column_stack(cols)[lags:]
    m = m[np.isfinite(m).all(axis=1)]
    n = len(m)
    if n < 250:
        return None
    ones = np.ones((n, 1))
    restricted = np.hstack([ones, m[:, 1:lags + 1]])
    full = np.hstack([ones, m[:, 1:]])
    rss = [float(np.sum((m[:, 0] - a @ np.linalg.lstsq(a, m[:, 0], rcond=None)[0]) ** 2)) for a in (restricted, full)]
    df2 = n - full.shape[1]
    f = ((rss[0] - rss[1]) / lags) / (rss[1] / df2)
    return float(sps.f.sf(f, lags, df2))


def granger(con: duckdb.DuckDBPyConnection, pairs: pd.DataFrame, maxlag: int = 3) -> list[float | None]:
    out = []
    for lead, follow in zip(pairs["lead"], pairs["follow"]):
        df = con.execute(f"""SELECT d.date, f.ex_cc AS y, l.ex_cc AS x
                             FROM (SELECT DISTINCT date FROM returns_daily WHERE date <= DATE '{RESEARCH_END}') d
                             LEFT JOIN returns_daily f ON f.date = d.date AND f.symbol = ?
                             LEFT JOIN returns_daily l ON l.date = d.date AND l.symbol = ?
                             ORDER BY d.date""", [follow, lead]).df()
        ps = [granger_p(df["y"].to_numpy(float), df["x"].to_numpy(float), k) for k in range(1, maxlag + 1)]
        ps = [p for p in ps if p is not None]
        out.append(min(ps) if ps else None)
    return out


def coint_overview(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return con.execute(f"""
        SELECT (SELECT count(*) FROM coint_pairs WHERE formation_date <= DATE '{RESEARCH_END}') AS pairs_tested,
               (SELECT avg((p < 0.05)::INT) FROM coint_pairs WHERE formation_date <= DATE '{RESEARCH_END}') AS share_p_below_5pct,
               count(*) AS events, avg(abs(z)) AS mean_abs_z_at_event,
               avg(abs(z_after_10)) AS mean_abs_z_after_10, avg(abs(z_after_20)) AS mean_abs_z_after_20
        FROM coint_events WHERE date <= DATE '{RESEARCH_END}' - INTERVAL {OUTCOME_MARGIN_DAYS} DAY""").df()


def industry_sections(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Group-level description (ICB level 2 equal-weight indexes), research period only."""
    names = "(SELECT group_code, any_value(name) AS name FROM group_names WHERE level = 'l2' GROUP BY 1)"
    sizes = con.execute(f"""SELECT g.group_code, n.name, count(g.ew_cc) AS sessions, avg(g.n_members) AS avg_members
                            FROM group_returns_daily g JOIN {names} n USING (group_code)
                            WHERE g.level = 'l2' AND g.date <= DATE '{RESEARCH_END}' GROUP BY 1, 2
                            ORDER BY sessions DESC""").df()
    level = con.execute(f"""SELECT year(month_end) AS year, avg(corr) AS avg_corr, count(*) AS pairs
                            FROM group_corr_snapshots WHERE level = 'l2' AND win = 120 AND month(month_end) = 12
                              AND month_end <= DATE '{RESEARCH_END}' GROUP BY 1 ORDER BY 1""").df()
    stability = con.execute(f"""
        WITH m AS (SELECT month_end, row_number() OVER (ORDER BY month_end) AS k
                   FROM (SELECT DISTINCT month_end FROM group_corr_snapshots
                         WHERE level = 'l2' AND month_end <= DATE '{RESEARCH_END}')),
        c AS (SELECT s.*, m.k FROM group_corr_snapshots s JOIN m USING (month_end) WHERE s.level = 'l2')
        SELECT win AS window, avg(r) AS avg_corr_of_corr FROM (
            SELECT x.win, x.month_end, corr(x.corr, y.corr) AS r FROM c x
            JOIN c y ON y.a = x.a AND y.b = x.b AND y.win = x.win AND y.k = x.k + {STABILITY_LAG_MONTHS}
            GROUP BY 1, 2 HAVING count(*) >= 10) WHERE isfinite(r) GROUP BY 1 ORDER BY 1""").df()
    top = con.execute(f"""SELECT na.name AS industry_a, nb.name AS industry_b, avg(corr) AS mean_corr, count(*) AS months
                          FROM group_corr_snapshots s JOIN {names} na ON na.group_code = s.a
                          JOIN {names} nb ON nb.group_code = s.b
                          WHERE s.level = 'l2' AND s.win = 120 AND s.month_end <= DATE '{RESEARCH_END}'
                          GROUP BY 1, 2 HAVING count(*) >= 36 ORDER BY 3 DESC LIMIT 10""").df()
    own = con.execute("""SELECT lag, avg(corr_form) AS own_autocorr_cc, avg(corr_form_oc) AS own_autocorr_oc
                         FROM group_leadlag_pairs WHERE level = 'l2' AND lead = follow AND form_year <= 2023
                         GROUP BY 1 ORDER BY 1""").df()
    cross = con.execute("""SELECT lag, avg(corr_form) AS cross_cc, avg(corr_form_oc) AS cross_oc,
                                  quantile_cont(corr_form, 0.9) AS p90_cc
                           FROM group_leadlag_pairs WHERE level = 'l2' AND lead <> follow AND form_year <= 2023
                           GROUP BY 1 ORDER BY 1""").df()
    return ["## Industries (ICB level 2, equal-weight index of liquid members, at least 5 members a day)", "",
            *_md(sizes),
            "### Correlation between industries (120 sessions, December snapshots)", "", *_md(level),
            "### Stability (industry correlations at month m vs m + 12)", "", *_md(stability),
            "### Most correlated industry pairs", "", *_md(top),
            "### Lead-lag of industry indexes (formation years): own autocorrelation and cross-industry",
            "", "`cc` = close-to-close of the follower; `oc` = its open-to-close. A large cc value with an oc "
            "value near zero is the stale-price signature.", "", *_md(own), *_md(cross)]


def render_describe(con: duckdb.DuckDBPyConnection, now: datetime) -> str:
    build = con.execute("SELECT build_id, research_build_id, params FROM cross_builds").fetchone()
    pp = persistent_pairs(con)
    if not pp.empty:
        pp["granger_min_p"] = granger(con, pp)
    lines = [f"# Cross-stock description - {now.isoformat(timespec='minutes')}", "",
             f"- Cross build {build[0]} (research build {build[1]}), research period only (to {RESEARCH_END}).",
             f"- Parameters: `{build[2]}`",
             "- Returns are excess returns vs VNINDEX; a pair uses only sessions where both stocks traded.",
             "- Descriptive only: nothing here is a tested or tradable claim.", "",
             "## Correlation level (120-session window, December snapshots)", "", *_md(level_by_year(con)),
             "## Is the correlation structure stable?", "",
             f"Correlation between all pair correlations at month m and at month m + {STABILITY_LAG_MONTHS}:", "",
             *_md(matrix_stability(con)),
             "## Most correlated pairs over time (120 sessions, at least 36 monthly snapshots)", "",
             *_md(stable_pairs(con)),
             "## Clusters vs ICB level-2 industries (adjusted Rand index; shuffled labels as a baseline)", "",
             *_md(clusters_vs_industry(con)),
             "## Central stocks (highest average correlation with the rest)", "", *_md(central_stocks(con)),
             "## Lead-lag overview (formation-year lag correlations, all directed pairs)", "",
             *_md(leadlag_overview(con)),
             "## Lag-1 pairs most often in their year's top decile (Granger min p over lags 1-3)", "",
             "These are the candidates a naive search would pick; whether such pairs persist is tested by "
             "`quant cross test` (lead-lag persistence), not here.", "", *_md(pp, "{:.4f}"),
             "## Cointegration (same ICB level-3 pairs, quarterly formation)", "",
             "Under no relation about 5% of tests fall below p = 0.05.", "", *_md(coint_overview(con)),
             *industry_sections(con)]
    return "\n".join(lines) + "\n"
