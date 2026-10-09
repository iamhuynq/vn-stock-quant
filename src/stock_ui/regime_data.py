"""Market regimes (Regime Engine) for the Market watch header and the Overview chart (read-only)."""

import duckdb
import pandas as pd

from stock_ui.db import Reader, ReadResult

DIMENSIONS = ("direction", "volatility", "liquidity", "breadth", "foreign", "risk")
RISK_COLORS = {"risk_on": "rgba(46, 160, 67, 0.15)", "neutral": "rgba(0, 0, 0, 0)",
               "risk_off": "rgba(218, 54, 51, 0.15)"}


def _regimes(con: duckdb.DuckDBPyConnection) -> dict | None:
    has = con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'market_regimes'").fetchone()[0]
    if not has:
        return None
    cols = ", ".join(f'r."{d}"' for d in DIMENSIONS)          # "foreign" is a SQL keyword
    history = con.execute(f"""SELECT r.date, m.mkt_close, {cols}, r.drawdown FROM market_regimes r
                              JOIN market_daily m USING (date)
                              WHERE r.date >= (SELECT max(date) FROM market_regimes) - INTERVAL 3 YEAR
                              ORDER BY r.date""").df()
    return {"latest": history.iloc[-1] if len(history) else None, "history": history}


def regimes(reader: Reader) -> ReadResult:
    return reader.read("research", "market_regimes", _regimes)


def risk_spans(history: pd.DataFrame) -> list[tuple]:
    """(start, end, risk state) runs of consecutive sessions with the same risk state, for shading."""
    spans, start, state = [], None, None
    for d, s in zip(history["date"], history["risk"]):
        s = None if pd.isna(s) else s
        if s != state:
            if state is not None:
                spans.append((start, d, state))
            start, state = d, s
    if state is not None and len(history):
        spans.append((start, history["date"].iloc[-1], state))
    return spans
