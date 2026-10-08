-- Rows per session in the raw warehouse (stocks and funds, all exchanges, traded or not). Used by the daily
-- completeness gate: daily_panel cannot be used because it drops each stock's sessions after its latest
-- trade (no-trade days at the data end, delisting filler), which would always look like missing data.
CREATE OR REPLACE TABLE source_coverage AS
SELECT date, count(*) AS n_rows, count(*) FILTER (WHERE total_volume > 0) AS n_traded
FROM wh.quotes_daily
WHERE symbol NOT IN ('VNINDEX', 'VN30', 'HNXINDEX', 'HNX30', 'UPINDEX')
GROUP BY date;
