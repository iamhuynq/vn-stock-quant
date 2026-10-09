"""Queries for the Symbol page. The symbol and dates are always bound parameters."""

from datetime import date

import duckdb
import pandas as pd

from stock_ui.db import Reader, ReadResult

FEATURE_COLUMNS = ("return_1d", "return_5d", "return_20d", "excess_return_20d", "volume_ratio_20",
                   "volatility_20", "atr_14_pct", "close_position", "order_imbalance", "buy_sell_ratio",
                   "foreign_net_value", "foreign_net_20d", "foreign_intensity", "adv_value_20",
                   "market_regime", "trend_regime", "limit_up", "limit_down", "price_jump", "session_index")


def symbols(reader: Reader) -> ReadResult:
    return reader.query("warehouse", """
        SELECT i.symbol, i.name, i.exchange, i.is_fund, i.industry_l1, i.industry_l2, i.industry_l4,
               s.is_listing, t.first_traded_date, t.last_traded_date
        FROM symbol_industry i
        LEFT JOIN symbols_latest s USING (symbol)
        LEFT JOIN symbol_trading_span t USING (symbol)
        ORDER BY coalesce(s.is_listing, false) DESC, i.symbol""")


def panel(reader: Reader, symbol: str, start: date) -> ReadResult:
    """Adjusted OHLC, volume, foreign flow, order imbalance and data-quality flags from research.duckdb."""
    return reader.query("research", """
        SELECT p.date, p.adj_open AS open, p.adj_high AS high, p.adj_low AS low, p.adj_close AS close,
               p.deal_volume AS volume, p.buy_foreign_value - p.sell_foreign_value AS foreign_net_value,
               f.order_imbalance, p.price_jump, p.foreign_inconsistent, p.bad_source_date, p.is_traded
        FROM daily_panel p LEFT JOIN stock_features f USING (symbol, date)
        WHERE p.symbol = ? AND p.date >= ? ORDER BY p.date""", (symbol, start))


def raw_prices(reader: Reader, symbol: str, start: date) -> ReadResult:
    """Unadjusted OHLC as published, from the warehouse."""
    return reader.query("warehouse", """
        SELECT date, price_open AS open, price_high AS high, price_low AS low, price_close AS close
        FROM quotes_daily WHERE symbol = ? AND date >= ? AND price_close > 0 ORDER BY date""", (symbol, start))


def corporate_actions(reader: Reader, symbol: str) -> ReadResult:
    return reader.query("warehouse", """
        SELECT ex_date, event_type_name, title, cash_per_share_vnd, ratio_held, ratio_received, record_date,
               payment_date
        FROM corporate_actions WHERE symbol = ? AND ex_date IS NOT NULL ORDER BY ex_date DESC""", (symbol,))


def report_marks(reader: Reader, symbol: str) -> ReadResult:
    return reader.query("warehouse", """
        SELECT release_date, label, title, fiscal_year, fiscal_quarter, revenue_bn, revenue_yoy_pct,
               profit_bn, profit_yoy_pct
        FROM report_marks WHERE symbol = ? AND release_date IS NOT NULL ORDER BY release_date DESC""", (symbol,))


def latest_features(reader: Reader, symbol: str) -> ReadResult:
    cols = ", ".join(FEATURE_COLUMNS)          # fixed column names, not user input
    return reader.query("research", f"""
        SELECT date, period, {cols} FROM stock_features
        WHERE symbol = ? ORDER BY date DESC LIMIT 1""", (symbol,))


def _events(con: duckdb.DuckDBPyConnection, symbol: str) -> pd.DataFrame | None:
    has = con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'daily_events'").fetchone()[0]
    if not has:
        return None
    return con.execute("""SELECT scan_date, pattern, is_forward, market_regime, close_raw, return_1d,
                                 volume_ratio_20, order_imbalance
                          FROM daily_events WHERE symbol = ? ORDER BY scan_date DESC, pattern""", [symbol]).df()


def daily_events(reader: Reader, symbol: str) -> ReadResult:
    return reader.read("results", ("daily_events", symbol), lambda con: _events(con, symbol))


def _catalog_events(con: duckdb.DuckDBPyConnection, symbol: str, start: date) -> pd.DataFrame | None:
    has = con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'stock_events'").fetchone()[0]
    if not has:
        return None
    return con.execute("""SELECT date, event_type, direction, event_score FROM stock_events
                          WHERE symbol = ? AND date >= ? ORDER BY date DESC, event_type""", [symbol, start]).df()


def catalog_events(reader: Reader, symbol: str, start: date) -> ReadResult:
    """Phase 5 catalog events of one symbol (research.duckdb stock_events)."""
    return reader.read("research", ("catalog_events", symbol, start), lambda con: _catalog_events(con, symbol, start))


def _factors(con: duckdb.DuckDBPyConnection, symbol: str) -> dict | None:
    has = con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'stock_factors'").fetchone()[0]
    if not has:
        return None
    history = con.execute("""SELECT date, factor, rank_pct FROM stock_factors
                             WHERE symbol = ? AND date >= (SELECT max(date) FROM stock_factors) - INTERVAL 365 DAY
                             ORDER BY date""", [symbol]).df()
    latest = con.execute("""SELECT f.factor, f.date, f.value, f.rank_pct, f.z, f.bucket, f.z_industry, d.sign_note
                            FROM stock_factors f LEFT JOIN factor_definitions d USING (factor)
                            WHERE f.symbol = ? AND f.date = (SELECT max(date) FROM stock_factors WHERE symbol = ?)
                            ORDER BY f.factor""", [symbol, symbol]).df()
    return {"history": history, "latest": latest}


def factors(reader: Reader, symbol: str) -> ReadResult:
    """Factor Engine scores of one symbol: latest scored date and the last year of ranks."""
    return reader.read("research", ("factors", symbol), lambda con: _factors(con, symbol))
