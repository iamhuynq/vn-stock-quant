"""Data for the Exposure panel (read-only, bound parameters): returns, factor z-scores (Factor Engine),
labels, paper weights."""

import duckdb
import pandas as pd

from stock_ui.db import Reader, ReadResult

SESSIONS = 120


def _returns(con: duckdb.DuckDBPyConnection, symbols: tuple[str, ...]) -> dict:
    marks = ", ".join("?" for _ in symbols)
    start = con.execute(f"SELECT min(date) FROM (SELECT date FROM market_daily ORDER BY date DESC LIMIT {SESSIONS + 1})"
                        ).fetchone()[0]
    stocks = con.execute(f"""
        WITH p AS (SELECT symbol, date, adj_close, is_traded AND NOT price_jump AND NOT bad_source_date AS ok,
                          lag(adj_close) OVER w AS prev_close,
                          lag(is_traded AND NOT price_jump AND NOT bad_source_date) OVER w AS prev_ok
                   FROM daily_panel WHERE symbol IN ({marks}) AND date >= ?
                   WINDOW w AS (PARTITION BY symbol ORDER BY date))
        SELECT symbol, date, CASE WHEN ok AND prev_ok AND prev_close > 0 THEN adj_close / prev_close - 1 END AS r
        FROM p WHERE date > ?""", [*symbols, start, start]).df()
    market = con.execute("SELECT date, mkt_ret_1d FROM market_daily WHERE date > ? ORDER BY date", [start]).df()
    wide = stocks.pivot(index="date", columns="symbol", values="r") if not stocks.empty else pd.DataFrame()
    dates = pd.Index(market["date"])
    return {"returns": wide.reindex(dates), "market": market.set_index("date")["mkt_ret_1d"],
            "as_of": market["date"].max()}


def returns(reader: Reader, symbols: tuple[str, ...]) -> ReadResult:
    if not symbols:
        return ReadResult(None, None, False, "no symbols")
    return reader.read("research", ("exposure_returns", symbols), lambda con: _returns(con, symbols))


def _factor_z(con: duckdb.DuckDBPyConnection) -> dict | None:
    """Factor z-scores (symbols x factors) and the 250-session beta on the latest scored date (stock_factors)."""
    has = con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'stock_factors'").fetchone()[0]
    if not has:
        return None
    df = con.execute("""SELECT symbol, factor, z, value FROM stock_factors
                        WHERE date = (SELECT max(date) FROM stock_factors)""").df()
    if df.empty:
        return None
    z = df.pivot(index="symbol", columns="factor", values="z")
    beta = df[df["factor"] == "beta"].set_index("symbol")["value"]
    return {"z": z, "beta_250": beta}


def factor_z(reader: Reader) -> ReadResult:
    return reader.read("research", "exposure_factor_z", _factor_z)


def industries(reader: Reader) -> ReadResult:
    return reader.query("warehouse", "SELECT symbol, industry_l2 FROM symbol_industry")


def clusters(reader: Reader) -> ReadResult:
    return reader.query("cross", """
        WITH last AS (SELECT max(month_end) AS d FROM clusters_monthly),
        main AS (SELECT cluster, mode(industry_l2_code) AS code, count(*) AS n FROM clusters_monthly, last
                 WHERE month_end = last.d GROUP BY 1)
        SELECT s.symbol, 'cluster ' || c.cluster || ' (' || main.n || ' stocks)' AS label
        FROM clusters_monthly c JOIN last ON c.month_end = last.d JOIN symbols s ON s.id = c.symbol_id
        JOIN main USING (cluster)""")


def paper_weights(reader: Reader) -> ReadResult:
    """Open positions of the latest paper-portfolio re-simulation, weighted by market value."""
    def run(con: duckdb.DuckDBPyConnection) -> dict | None:
        has = con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'paper_positions'").fetchone()[0]
        if not has:
            return None
        rows = con.execute("""SELECT symbol, shares * last_price FROM paper_positions
                              WHERE run_date = (SELECT max(run_date) FROM paper_positions)""").fetchall()
        return {s: float(v) for s, v in rows if v}
    return reader.read("results", "paper_weights", run)
