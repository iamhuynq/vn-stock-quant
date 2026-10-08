-- VNINDEX returns and regimes. Trailing windows only; a window value is NULL until it is full.
CREATE OR REPLACE TABLE market_daily AS
WITH m AS (
    SELECT date,
           price_open  / adj_ratio AS mkt_open,
           price_close / adj_ratio AS mkt_close
    FROM wh.quotes_daily
    WHERE symbol = 'VNINDEX' AND adj_ratio > 0
),
r AS (
    SELECT *,
        mkt_close / lag(mkt_close, 1)  OVER o - 1 AS mkt_ret_1d,
        mkt_close / lag(mkt_close, 3)  OVER o - 1 AS mkt_ret_3d,
        mkt_close / lag(mkt_close, 5)  OVER o - 1 AS mkt_ret_5d,
        mkt_close / lag(mkt_close, 10) OVER o - 1 AS mkt_ret_10d,
        mkt_close / lag(mkt_close, 20) OVER o - 1 AS mkt_ret_20d,
        CASE WHEN count(mkt_close) OVER (o ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) = 50
             THEN avg(mkt_close) OVER (o ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) END AS mkt_ma50,
        CASE WHEN count(mkt_close) OVER (o ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) = 200
             THEN avg(mkt_close) OVER (o ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) END AS mkt_ma200
    FROM m
    WINDOW o AS (ORDER BY date)
),
v AS (
    SELECT *,
        CASE WHEN count(mkt_ret_1d) OVER (o ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) = 20
             THEN stddev_samp(mkt_ret_1d) OVER (o ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) END AS mkt_vol_20
    FROM r
    WINDOW o AS (ORDER BY date)
),
med AS (
    SELECT *,
        CASE WHEN count(mkt_vol_20) OVER (o ROWS BETWEEN 249 PRECEDING AND CURRENT ROW) = 250
             THEN quantile_cont(mkt_vol_20, 0.5) OVER (o ROWS BETWEEN 249 PRECEDING AND CURRENT ROW) END
             AS mkt_vol_20_median_250
    FROM v
    WINDOW o AS (ORDER BY date)
)
SELECT *,
    CASE WHEN mkt_ma200 IS NULL THEN NULL
         WHEN mkt_close > mkt_ma200 THEN 'above_ma200' ELSE 'below_ma200' END AS trend_regime,
    CASE WHEN mkt_ma200 IS NULL OR mkt_ma50 IS NULL THEN NULL
         WHEN mkt_close > mkt_ma200 AND mkt_ma50 > mkt_ma200 THEN 'Bull'
         WHEN mkt_close < mkt_ma200 AND mkt_ma50 < mkt_ma200 THEN 'Bear'
         ELSE 'Sideway' END AS market_regime,
    CASE WHEN mkt_vol_20_median_250 IS NULL THEN NULL
         WHEN mkt_vol_20 > mkt_vol_20_median_250 THEN 'high' ELSE 'low' END AS vol_regime
FROM med;
