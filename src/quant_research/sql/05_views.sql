-- Research-facing view: features at t joined with outcomes after t.
CREATE OR REPLACE VIEW feature_target AS
SELECT f.*, t.* EXCLUDE (symbol, date, period)
FROM stock_features f
JOIN stock_targets t USING (symbol, date);
