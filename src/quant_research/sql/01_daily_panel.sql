-- Clean stock-session panel. Reads the warehouse attached READ_ONLY as `wh`.
-- Keeps stocks only (no funds/ETFs, no indices) between first and last traded date, which drops the
-- zero-volume filler that the source adds after delisting.
-- Rows with any price <= 0 are dropped (1,498 source placeholders: no-trade days with all-zero prices,
-- plus one traded row with low = 0); they would otherwise produce infinite returns.
-- adj_* = raw / adj_ratio (back-adjusted, thousand VND): use only in ratios. *_raw: absolute levels.
CREATE OR REPLACE TABLE daily_panel AS
WITH base AS (
    SELECT
        q.symbol,
        q.date,
        si.exchange                                  AS exchange_now,
        si.industry_l1_code, si.industry_l2_code, si.industry_l3_code, si.industry_l4_code,
        q.price_open  / q.adj_ratio                  AS adj_open,
        q.price_high  / q.adj_ratio                  AS adj_high,
        q.price_low   / q.adj_ratio                  AS adj_low,
        q.price_close / q.adj_ratio                  AS adj_close,
        q.price_open                                 AS open_raw,
        q.price_close                                AS close_raw,
        q.price_basic                                AS basic_raw,
        q.unit,
        q.deal_volume,
        -- negative only on corrupt source rows (16 rows, mostly 2025-07-16): treat as missing
        CASE WHEN q.total_value >= q.putthrough_value THEN q.total_value - q.putthrough_value END AS deal_value,
        q.total_value,
        q.buy_quantity                               AS buy_qty,
        q.sell_quantity                              AS sell_qty,
        q.buy_count,
        q.sell_count,
        q.buy_foreign_quantity, q.sell_foreign_quantity,
        q.buy_foreign_value,    q.sell_foreign_value,
        CASE si.exchange WHEN 'HSX' THEN 0.07 WHEN 'HNX' THEN 0.10 WHEN 'UPCOM' THEN 0.15 END AS limit_band
    FROM wh.quotes_daily q
    JOIN wh.symbol_industry si USING (symbol)
    JOIN wh.symbol_trading_span t USING (symbol)
    WHERE NOT si.is_fund
      AND q.adj_ratio > 0
      AND q.price_open > 0 AND q.price_high > 0 AND q.price_low > 0 AND q.price_close > 0
      AND q.date BETWEEN t.first_traded_date AND t.last_traded_date
),
ticked AS (
    SELECT *,
        -- Tick size (thousand VND): HOSE 0.01 / 0.05 / 0.1 by price level; HNX and UPCOM 0.1.
        CASE WHEN exchange_now = 'HSX' THEN
                 CASE WHEN basic_raw < 10 THEN 0.01 WHEN basic_raw < 50 THEN 0.05 ELSE 0.1 END
             ELSE 0.1 END AS tick
    FROM base
)
SELECT
    * EXCLUDE (limit_band, tick),
    CASE WHEN deal_volume > 0 AND deal_value > 0 THEN deal_value / (deal_volume * unit) END AS vwap_deal,
    deal_volume > 0                                                      AS is_traded,
    row_number() OVER (PARTITION BY symbol ORDER BY date)                AS session_index,
    -- Approximate daily limits: band of the CURRENT exchange (no exchange history), rounded to tick.
    close_raw >= floor(basic_raw * (1 + limit_band) / tick + 1e-6) * tick - 1e-9 AS limit_up,
    close_raw <= ceil(basic_raw * (1 - limit_band) / tick - 1e-6) * tick + 1e-9  AS limit_down,
    open_raw  >= floor(basic_raw * (1 + limit_band) / tick + 1e-6) * tick - 1e-9 AS open_limit_up,
    date = DATE '2025-07-16'                                             AS bad_source_date,
    -- A one-day adjusted move above 40% exceeds every Vietnamese daily limit, including special
    -- sessions (UPCOM first/resumed trading +-40%, HOSE listing day +-20%): a source error.
    -- A band-based test is NOT used: exchange history is unknown and many stocks moved from UPCOM
    -- (+-15%) to HOSE/HNX, so the current band would flag legitimate historical moves.
    abs(adj_close / lag(adj_close) OVER (PARTITION BY symbol ORDER BY date) - 1) > 0.4 AS price_jump,
    buy_foreign_value > total_value * 1.01 OR sell_foreign_value > total_value * 1.01 AS foreign_inconsistent,
    -- holdout was used once (2026-10-04) and is frozen; data from 2026-10-03 on is 'forward'
    CASE WHEN date <= DATE '2023-12-31' THEN 'research'
         WHEN date <= DATE '2025-12-31' THEN 'validation'
         WHEN date <= DATE '2026-10-02' THEN 'holdout'
         ELSE 'forward' END                                              AS period
FROM ticked;
