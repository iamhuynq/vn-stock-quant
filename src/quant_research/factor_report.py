"""`quant factors describe`: structure of factor set f1 on the research period (descriptive, no returns).

Reads research.duckdb only (READ_ONLY). No forward return is used, nothing is tested, and nothing is written to
results.duckdb or the hypothesis log.
"""

from itertools import combinations
from pathlib import Path

import duckdb
import pandas as pd

from quant_research import provenance
from quant_research.factors import FACTORS, version
from quant_research.results import research_code_hash

LAGS = (1, 5, 20)
RESEARCH = "f.date <= DATE '2023-12-31'"   # research period (see 01_daily_panel.sql)


def _query(con: duckdb.DuckDBPyConnection, sql: str) -> pd.DataFrame:
    return con.execute(sql).df()


def coverage(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    df = _query(con, f"""SELECT year(f.date) AS year, factor, count(*) / count(DISTINCT f.date) AS stocks
                         FROM rs.stock_factors f WHERE {RESEARCH} GROUP BY ALL""")
    return df.pivot(index="year", columns="factor", values="stocks").round(0).reindex(columns=list(FACTORS))


def correlations(con: duckdb.DuckDBPyConnection) -> dict[str, pd.DataFrame]:
    """Average cross-sectional Spearman correlation (Pearson on rank_pct per date), by market regime."""
    names = list(FACTORS)
    cols = ", ".join(f"max(rank_pct) FILTER (WHERE factor = '{n}') AS \"{n}\"" for n in names)
    pairs = list(combinations(names, 2))
    corr = ", ".join(f'corr("{a}", "{b}") AS "{a}|{b}"' for a, b in pairs)
    df = _query(con, f"""
        WITH w AS (SELECT f.date, f.symbol, {cols} FROM rs.stock_factors f WHERE {RESEARCH} GROUP BY ALL),
        d AS (SELECT date, {corr} FROM w GROUP BY date)
        SELECT coalesce(m.market_regime, 'unknown') AS regime, d.* EXCLUDE (date)
        FROM d JOIN rs.market_daily m USING (date)""")
    out = {}
    for regime, g in [("all", df), *df.groupby("regime")]:
        mat = pd.DataFrame(1.0, index=names, columns=names)
        for a, b in pairs:
            mat.loc[a, b] = mat.loc[b, a] = g[f"{a}|{b}"].mean()
        out[str(regime)] = mat.round(2)
    return out


def persistence(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Average cross-sectional correlation of rank_pct with its value k market sessions earlier."""
    frames = []
    for k in LAGS:
        frames.append(_query(con, f"""
            WITH s AS (SELECT date, row_number() OVER (ORDER BY date) AS i FROM rs.market_daily),
            f AS (SELECT f.*, s.i FROM rs.stock_factors f JOIN s USING (date) WHERE {RESEARCH})
            SELECT a.factor, avg(c) AS "lag_{k}" FROM (
                SELECT a.factor, a.date, corr(a.rank_pct, b.rank_pct) AS c
                FROM f a JOIN f b ON a.symbol = b.symbol AND a.factor = b.factor AND b.i = a.i - {k}
                GROUP BY ALL) a WHERE isfinite(c) GROUP BY 1""").set_index("factor"))
    return pd.concat(frames, axis=1).reindex(list(FACTORS)).round(2)


def industry_share(con: duckdb.DuckDBPyConnection) -> pd.Series:
    """Share of each factor's cross-sectional variance explained by industry (between-industry R^2)."""
    df = _query(con, f"""
        WITH g AS (SELECT f.date, factor,
                          1 - sum(z_industry * z_industry) / nullif(sum((z - zbar) * (z - zbar)), 0) AS r2
                   FROM (SELECT *, avg(z) OVER (PARTITION BY date, factor) AS zbar
                         FROM rs.stock_factors f WHERE {RESEARCH} AND z_industry IS NOT NULL) f
                   GROUP BY ALL)
        SELECT factor, avg(r2) AS r2 FROM g GROUP BY 1""")
    return df.set_index("factor")["r2"].reindex(list(FACTORS)).round(3)


def _md(df: pd.DataFrame) -> list[str]:
    cols = [str(df.index.name or "")] + [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for idx, row in df.iterrows():
        cells = ["-" if pd.isna(v) else (f"{v + 0.0:g}" if isinstance(v, float) else str(v)) for v in row]
        lines.append("| " + " | ".join([str(idx), *cells]) + " |")
    return lines


def render(research_path: Path) -> tuple[str, str]:
    """(build id, markdown report)."""
    con = duckdb.connect()
    con.execute(f"ATTACH '{research_path.as_posix().replace(chr(39), chr(39) * 2)}' AS rs (READ_ONLY)")
    try:
        if not con.execute("""SELECT count(*) FROM duckdb_tables() WHERE database_name = 'rs'
                              AND table_name = 'stock_factors'""").fetchone()[0]:
            raise RuntimeError("No stock_factors in research.duckdb: run `quant build`")
        prov = provenance.collect(con, research_code_hash())
        lines = [f"# Factor structure, factor set f1 (version {version()}), research period", "",
                 provenance.line(prov), "",
                 "Descriptive only: no forward return is used, nothing is tested or logged. Scores per date over",
                 "the liquid universe (docs/factor-engine-plan.md).", "", "## Definitions", "",
                 "| Factor | Definition | Sign |", "|---|---|---|",
                 *[f"| `{n}` | {d} | {s} |" for n, (d, s) in FACTORS.items()],
                 "", "## Coverage (average scored stocks per date)", "", *_md(coverage(con)),
                 "", "## Rank persistence (correlation of rank with its value k sessions earlier)", "",
                 "High persistence means low turnover for a portfolio sorted on the factor.", "",
                 *_md(persistence(con)),
                 "", "## Share of variance explained by industry (ICB level 2, today's classification)", "",
                 *_md(industry_share(con).to_frame("r2")), "",
                 "## Cross-factor correlation (average per-date Spearman)", ""]
        for regime, mat in correlations(con).items():
            lines += [f"### Regime: {regime}", "", *_md(mat), ""]
        return prov["feature_build_id"] or "unknown", "\n".join(lines)
    finally:
        con.close()
