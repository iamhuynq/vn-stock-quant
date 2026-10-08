-- Event catalog v1 (doc 15, 21.5, 24; docs/event-engine-plan.md). Point in time: every condition uses data
-- up to the event session only; BREAKOUT / BREAKDOWN compare with the PREVIOUS 60 sessions (today excluded).
-- Thresholds were set from the research-period distribution of each feature (about the 2% tails), never from
-- outcomes. One row per (symbol, date, event_type); event_score is the defining quantity.
CREATE OR REPLACE TABLE stock_events AS
WITH prior AS (
    SELECT symbol, date,
           max(CASE WHEN is_traded THEN adj_close END) OVER w AS prev_max_close,
           min(CASE WHEN is_traded THEN adj_close END) OVER w AS prev_min_close,
           count(CASE WHEN is_traded THEN 1 END) OVER w AS prev_traded,
           adj_close
    FROM daily_panel
    WINDOW w AS (PARTITION BY symbol ORDER BY date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING)
),
f AS (
    SELECT s.*, p.prev_max_close, p.prev_min_close, p.prev_traded, p.adj_close,
           s.foreign_net_value / nullif(s.adv_value_20, 0) AS foreign_net_adv,
           s.high_low_range / nullif(s.atr_14_pct, 0) AS range_atr
    FROM stock_features s JOIN prior p USING (symbol, date)
    WHERE s.is_traded AND NOT s.price_jump AND NOT s.bad_source_date
),
ev AS (
    SELECT symbol, date, 'PRICE_SURGE' AS event_type, 'up' AS direction, return_1d AS event_score
    FROM f WHERE return_1d >= 0.05
    UNION ALL SELECT symbol, date, 'PRICE_DROP', 'down', return_1d FROM f WHERE return_1d <= -0.05
    UNION ALL SELECT symbol, date, 'VOLUME_SPIKE', 'none', volume_ratio_20 FROM f WHERE volume_ratio_20 >= 3
    UNION ALL SELECT symbol, date, 'FOREIGN_BUY_SPIKE', 'up', foreign_net_adv FROM f
              WHERE foreign_net_adv >= 0.5 AND NOT foreign_inconsistent
    UNION ALL SELECT symbol, date, 'FOREIGN_SELL_SPIKE', 'down', foreign_net_adv FROM f
              WHERE foreign_net_adv <= -0.5 AND NOT foreign_inconsistent
    UNION ALL SELECT symbol, date, 'ORDER_IMBALANCE_SPIKE_BUY', 'up', order_imbalance FROM f WHERE order_imbalance >= 0.5
    UNION ALL SELECT symbol, date, 'ORDER_IMBALANCE_SPIKE_SELL', 'down', order_imbalance FROM f WHERE order_imbalance <= -0.5
    UNION ALL SELECT symbol, date, 'VOLATILITY_SPIKE', 'none', range_atr FROM f WHERE range_atr >= 2.5
    UNION ALL SELECT symbol, date, 'BREAKOUT', 'up', adj_close / prev_max_close - 1 FROM f
              WHERE prev_traded >= 50 AND adj_close > prev_max_close
    UNION ALL SELECT symbol, date, 'BREAKDOWN', 'down', adj_close / prev_min_close - 1 FROM f
              WHERE prev_traded >= 50 AND adj_close < prev_min_close
    UNION ALL SELECT symbol, date, 'DIVERGENCE_UP_FOREIGN_SELL', 'up', return_5d FROM f
              WHERE return_5d >= 0.05 AND foreign_net_5d < 0
    UNION ALL SELECT symbol, date, 'DIVERGENCE_DOWN_FOREIGN_BUY', 'down', return_5d FROM f
              WHERE return_5d <= -0.05 AND foreign_net_5d > 0
)
SELECT ev.symbol, ev.date, ev.event_type, ev.direction, ev.event_score,
       json_object('exchange', f.exchange_now, 'regime', f.market_regime, 'return_1d', f.return_1d,
                   'volume_ratio_20', f.volume_ratio_20, 'order_imbalance', f.order_imbalance,
                   'foreign_net_adv', f.foreign_net_adv) AS metadata
FROM ev JOIN f USING (symbol, date)
WHERE ev.event_score IS NOT NULL AND isfinite(ev.event_score);
