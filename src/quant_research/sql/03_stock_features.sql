-- Features at session t using data <= t ONLY (doc sections 2-3, 12, 13, 21.4).
-- Rules: windows count the symbol's own sessions; a window feature is NULL until the window is full;
-- zero denominators give NULL; volume features use matched value (VND), not shares, so stock
-- dividends/splits do not create fake spikes. This file must never look forward (enforced by a test).
CREATE OR REPLACE TABLE stock_features AS
WITH s1 AS (
    SELECT p.*,
        adj_close / lag(adj_close, 1)  OVER w - 1                         AS return_1d,
        adj_close / lag(adj_close, 3)  OVER w - 1                         AS return_3d,
        adj_close / lag(adj_close, 5)  OVER w - 1                         AS return_5d,
        adj_close / lag(adj_close, 10) OVER w - 1                         AS return_10d,
        adj_close / lag(adj_close, 20) OVER w - 1                         AS return_20d,
        lag(adj_close, 1) OVER w                                          AS prev_adj_close,
        lag(deal_value, 1) OVER w                                         AS prev_deal_value,
        CASE WHEN deal_value IS NOT NULL THEN ln(1 + deal_value) END      AS log_value,  -- not greatest(): it skips NULLs
        buy_foreign_value - sell_foreign_value                            AS foreign_net_value,
        buy_foreign_quantity - sell_foreign_quantity                      AS foreign_net_volume
    FROM daily_panel p
    WINDOW w AS (PARTITION BY symbol ORDER BY date)
),
s2 AS (
    SELECT *,
        -- greatest() skips NULLs in DuckDB, so guard the first session (no previous close) explicitly
        CASE WHEN prev_adj_close IS NOT NULL THEN
             greatest(adj_high - adj_low, abs(adj_high - prev_adj_close), abs(adj_low - prev_adj_close)) END AS true_range,
        -- volume baselines exclude today
        CASE WHEN count(deal_value) OVER (w ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) = 5
             THEN avg(deal_value) OVER (w ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING) END   AS base_value_5,
        CASE WHEN count(deal_value) OVER (w ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) = 20
             THEN avg(deal_value) OVER (w ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) END  AS base_value_20,
        CASE WHEN count(log_value) OVER (w ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) = 20
             THEN avg(log_value) OVER (w ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) END   AS base_log_mean_20,
        CASE WHEN count(log_value) OVER (w ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) = 20
             THEN stddev_samp(log_value) OVER (w ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) END AS base_log_std_20,
        -- windows including today
        CASE WHEN count(return_1d) OVER (w ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) = 5
             THEN stddev_samp(return_1d) OVER (w ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) END AS volatility_5,
        CASE WHEN count(return_1d) OVER (w ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) = 20
             THEN stddev_samp(return_1d) OVER (w ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) END AS volatility_20,
        CASE WHEN count(foreign_net_value) OVER (w ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) = 3
             THEN sum(foreign_net_value) OVER (w ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) END AS foreign_net_3d,
        CASE WHEN count(foreign_net_value) OVER (w ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) = 5
             THEN sum(foreign_net_value) OVER (w ROWS BETWEEN 4 PRECEDING AND CURRENT ROW) END AS foreign_net_5d,
        CASE WHEN count(foreign_net_value) OVER (w ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) = 20
             THEN sum(foreign_net_value) OVER (w ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) END AS foreign_net_20d,
        CASE WHEN count(deal_value) OVER (w ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) = 20
             THEN sum(deal_value) OVER (w ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) END AS sum_value_20,
        CASE WHEN count(deal_value) OVER (w ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) = 20
             THEN avg(deal_value) OVER (w ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) END AS adv_value_20
    FROM s1
    WINDOW w AS (PARTITION BY symbol ORDER BY date)
),
s3 AS (
    SELECT *,
        CASE WHEN count(true_range) OVER (w ROWS BETWEEN 13 PRECEDING AND CURRENT ROW) = 14
             THEN avg(true_range) OVER (w ROWS BETWEEN 13 PRECEDING AND CURRENT ROW) END AS atr_14
    FROM s2
    WINDOW w AS (PARTITION BY symbol ORDER BY date)
)
SELECT
    s.symbol, s.date, s.period, s.exchange_now,
    s.industry_l1_code, s.industry_l2_code, s.industry_l3_code, s.industry_l4_code,
    -- return (3.1)
    s.return_1d, s.return_3d, s.return_5d, s.return_10d, s.return_20d,
    s.return_5d  - m.mkt_ret_5d                                                AS excess_return_5d,
    s.return_20d - m.mkt_ret_20d                                               AS excess_return_20d,
    -- volume (3.2), on matched value
    s.deal_value / nullif(s.base_value_5, 0)                                   AS volume_ratio_5,
    s.deal_value / nullif(s.base_value_20, 0)                                  AS volume_ratio_20,
    s.deal_value / nullif(s.prev_deal_value, 0) - 1                            AS volume_change,
    (s.log_value - s.base_log_mean_20) / nullif(s.base_log_std_20, 0)          AS volume_zscore_20,
    -- volatility (3.3)
    s.volatility_5, s.volatility_20,
    s.atr_14 / nullif(s.adj_close, 0)                                          AS atr_14_pct,
    (s.adj_high - s.adj_low) / nullif(s.adj_close, 0)                          AS high_low_range,
    s.adj_open / nullif(s.prev_adj_close, 0) - 1                               AS gap,
    -- price position (3.4, 3.5)
    (s.adj_close - s.adj_low) / nullif(s.adj_high - s.adj_low, 0)              AS close_position,
    (s.close_raw - s.vwap_deal) / nullif(s.vwap_deal, 0)                       AS close_vs_avg_price,
    -- supply/demand (2.2): order placements; NULL when the source has no order statistics
    (s.buy_qty - s.sell_qty) / nullif(s.buy_qty + s.sell_qty, 0)               AS order_imbalance,
    (s.buy_count - s.sell_count) / nullif(s.buy_count + s.sell_count, 0)       AS volume_imbalance,
    CASE WHEN s.buy_qty + s.sell_qty > 0 THEN s.buy_qty  / nullif(s.deal_volume, 0) END AS buy_pressure,
    CASE WHEN s.buy_qty + s.sell_qty > 0 THEN s.sell_qty / nullif(s.deal_volume, 0) END AS sell_pressure,
    s.buy_qty / nullif(s.sell_qty, 0)                                          AS buy_sell_ratio,
    -- foreign flow (2.3, 13)
    s.foreign_net_volume, s.foreign_net_value,
    s.foreign_net_3d, s.foreign_net_5d, s.foreign_net_20d,
    s.foreign_net_20d / nullif(s.sum_value_20, 0)                              AS foreign_net_ratio_20,
    (s.buy_foreign_value + s.sell_foreign_value) / nullif(s.total_value, 0)    AS foreign_intensity,
    -- market regime (12)
    m.market_regime, m.trend_regime, m.vol_regime,
    -- liquidity and quality flags
    s.adv_value_20, s.close_raw, s.is_traded, s.limit_up, s.limit_down, s.bad_source_date, s.session_index,
    s.price_jump, s.foreign_inconsistent
FROM s3 s
LEFT JOIN market_daily m USING (date);
