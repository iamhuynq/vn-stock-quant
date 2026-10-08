# Plan: Event Engine completion (Phase 5)

<!-- type: feature -->
<!-- status: built 2026-10-08; event study run 20261008T163321-event_study-catalog_d9f85c2d-research -->

Source: `quant_research_chung_khoan_viet_nam.md` sections 14 (anomaly), 15 (event engine), 21.5
(`stock_events` table), 24 (event-driven research) and 26 (Phase 5). Already built (Phase 5, part 1): the
daily scanner of the pattern library, forward event outcomes, the daily report
(`docs/daily-pipeline-plan.md`).

## What is missing

| Doc requirement | Today | To build |
|-----------------|-------|----------|
| Event types PRICE_SURGE, PRICE_DROP, VOLUME_SPIKE, FOREIGN_BUY_SPIKE, FOREIGN_SELL_SPIKE, ORDER_IMBALANCE_SPIKE, VOLATILITY_SPIKE, BREAKOUT, BREAKDOWN, DIVERGENCE (doc 15, 24) | Some exist as library patterns (drop3, volume_spike, foreign_divergence_up), with different thresholds; there is no BREAKOUT, BREAKDOWN, VOLATILITY_SPIKE, FOREIGN or ORDER-IMBALANCE spike | A typed **event catalog** with all ten families |
| `stock_events (stock_id, date, event_type, event_score, metadata)` over the full history (doc 21.5) | Events are stored only for scanned forward sessions | `stock_events` table in research.duckdb, built by `quant build`, point in time |
| "After this event, what usually happens?" with sample size, mean, median, win rate, std, max gain, max loss at 1/3/5 sessions (doc 24) | Pattern runs report lifts, not the doc's event table | **Event study** per type, by regime and exchange |
| Today's events with their history (doc 15, 25) | The daily report lists library patterns | The daily report and UI also show catalog events with their event-study figures |

## Key decisions (defaults; change any you disagree with)

| Topic | Default | Why |
|-------|---------|-----|
| Thresholds | Fixed from the **distribution of the feature itself** on the research period (about the 2% tails), never from outcomes; see the catalog below | Choosing thresholds by looking at results would be p-hacking |
| Event score | The defining quantity (e.g. 3.8 for a 3.8x volume spike, +6.1% for a surge) | Doc 15 `event_strength` |
| Metadata | JSON: exchange, regime, return_1d, volume_ratio_20, order_imbalance, foreign_net_value / ADV | Doc 21.5 |
| Point in time | Events use only data up to the event session. BREAKOUT / BREAKDOWN compare with the **previous** 60 sessions (today excluded) | Same rule as every feature; covered by a perturbation test |
| Where events live | `stock_events` in research.duckdb, rebuilt with the features (new SQL step `06_stock_events.sql`) | Derived data; the daily scanner reads it like `stock_features` |
| Event study: tested or descriptive? | **Descriptive** (research period only, **not** added to the hypothesis log) | Ten families x horizons would add about 30-60 tests overlapping Phase 3 patterns. Doc 24 asks for a statistics table, not significance claims. An event that looks useful is promoted later through a normal pattern test or pre-registration |
| Event study figures | n events, n dates, mean, median, win rate, std, mean max gain and mean max loss within 5 sessions, p5 / p95, at close 1/3/5 sessions (doc 24) and execution excess 5/10/20 sessions (tradable view), plus lift vs the universe on the same dates. By regime and exchange. Costs shown next to the means | Covers the doc's list and our tradable view |
| Daily use | The daily scan copies today's catalog events into `daily_events` (as `EVENT_<TYPE>`). The report gets an "Events" section with today's symbols and the historical figures of each type. The forward scoreboard then covers events automatically | Reuses the forward event-study machinery already built |

## Event catalog (v1)

| Event | Condition (session t) | Score |
|-------|-----------------------|-------|
| PRICE_SURGE | return_1d >= +5% | return_1d |
| PRICE_DROP | return_1d <= -5% | return_1d |
| VOLUME_SPIKE | volume_ratio_20 >= 3 (doc 24) | volume_ratio_20 |
| FOREIGN_BUY_SPIKE | foreign net value >= 50% of the 20-session average traded value | that ratio |
| FOREIGN_SELL_SPIKE | foreign net value <= -50% of it | that ratio |
| ORDER_IMBALANCE_SPIKE (buy / sell) | order_imbalance >= +0.5 / <= -0.5 | order_imbalance |
| VOLATILITY_SPIKE | day range >= 2.5 x ATR(14) | range / ATR |
| BREAKOUT | adjusted close above the highest adjusted close of the previous 60 sessions (at least 50 traded) | close / previous max - 1 |
| BREAKDOWN | adjusted close below the lowest of the previous 60 sessions | close / previous min - 1 |
| DIVERGENCE (up / down) | return_5d >= +5% with foreign net selling over 5 sessions / return_5d <= -5% with foreign net buying | return_5d |

Research-period tails used to set the thresholds (liquid universe, about 0.96M rows):
- return_1d 2% / 98%: -6.9% / +7.0%;
- volume_ratio_20 98%: 4.0;
- order_imbalance 2% / 98%: -0.51 / +0.48;
- foreign net / ADV 2% / 98%: -0.48 / +0.53;
- range / ATR 98%: 2.3.

Only the existing rows were inspected, not any outcome.

## UI

- Symbol page: event markers on the price chart (type in the tooltip) and the symbol's event history.
- Research page: a new "Event study" tab (per event, horizons, segments).
- Daily report page: catalog events appear with the patterns.

## Tests

- Each event equals a direct SQL query of its condition on the synthetic data, and the planted cases fire
  (a 60-session high, a 3x volume day, a -5% day).
- BREAKOUT excludes today: a new high equal to today's close is not compared with itself.
- Look-ahead perturbation: changing data after a date leaves every earlier event unchanged.
- Event study figures equal a direct pandas computation on a small case, and nothing is written to
  `hypothesis_log`.
- The daily scan copies only the scan date's events; the report and UI pages render read-only.
- The full suite stays green.

## Rollback

Additive. Removing `06_stock_events.sql` and rebuilding (`quant build`) drops the table. The `EVENT_*` rows
in `daily_events` are informational and can stay. Event-study runs are kept, never deleted (invalidate
them if needed).

## Open questions (defaults used unless you say otherwise)

1. Thresholds as in the catalog: surge and drop at +/-5%, volume 3x, foreign 50% of ADV, imbalance
   +/-0.5, range 2.5x ATR, 60-session breakout.
2. Event study **descriptive only** (not logged as hypotheses); promising events go through a separate,
   pre-registered test later.

## Result (2026-10-08)

- `sql/06_stock_events.sql` (catalog v1, version `d9f85c2d`), built by `quant build`: 12 event types over
  the full history. `quant_research/events.py` holds the names, descriptions and catalog version.
- `quant events study`: event study `20261008T163321-event_study-catalog_d9f85c2d-research`. It is
  descriptive (0 rows in the hypothesis log); report in `data/reports/research/events-*.md`.
- The daily scan copies the catalog events as `EVENT_<TYPE>` rows. Forward sessions 2026-10-05..07 were
  re-scanned (`quant daily --date`). The daily report has a "Catalog events today" section, and the
  forward scoreboard covers these events.
- UI:
  - Symbol page: event markers (diamonds) and a "Catalog events" tab.
  - Research page: an "Event study" tab.
  - Daily report page: catalog events shown with the patterns.
- 228 tests pass (5 new in `tests/research/test_events.py`):
  - each event equals its condition;
  - BREAKOUT excludes today (pandas reference);
  - perturbation (point in time, non-vacuous);
  - the event study matches pandas and logs nothing;
  - the daily copy covers only the scan date.

Research-period figures (liquid universe, execution excess return over 10 sessions; lift vs the universe
on the same dates; descriptive t, not corrected):

| Event | Events | Mean | Win rate | Lift | t |
|-------|--------|------|----------|------|---|
| BREAKOUT | 66,393 | +1.24% | 47% | +0.81% | 4.1 |
| ORDER_IMBALANCE_SPIKE_BUY | 15,975 | +1.62% | 48% | +1.00% | 3.2 |
| FOREIGN_SELL_SPIKE | 17,854 | +0.67% | 50% | +0.52% | 3.8 |
| DIVERGENCE_UP_FOREIGN_SELL | 68,911 | +1.00% | 47% | +0.46% | 2.7 |
| FOREIGN_BUY_SPIKE | 20,435 | +0.18% | 46% | -0.06% | -0.4 |
| VOLUME_SPIKE | 38,630 | +0.15% | 44% | -0.33% | -2.6 |
| VOLATILITY_SPIKE | 11,939 | -0.29% | 44% | -0.66% | -3.4 |
| PRICE_SURGE | 57,014 | +0.03% | 43% | -0.72% | -4.4 |
| DIVERGENCE_DOWN_FOREIGN_BUY | 68,173 | -0.63% | 44% | -1.48% | -9.5 |
| PRICE_DROP | 48,924 | -0.51% | 46% | -1.90% | -7.7 |
| BREAKDOWN | 45,587 | -0.89% | 44% | -2.37% | -11.5 |
| ORDER_IMBALANCE_SPIKE_SELL | 19,317 | -2.80% | 37% | -2.49% | -10.8 |

How to read it:
- **Bad news persists more than good news.** Downside events (breakdown, sell-side imbalance, sharp
  drops, falling price with foreign buying) are followed by clear underperformance. This is consistent
  with the validated avoid signal of Phase 3. They are useful as **avoid / exit** information, not as long
  signals.
- **Close-to-close figures overstate what can be traded.** Buy-side imbalance spikes show +4.4% over 5
  sessions close-to-close, but +1.0% lift from the next open: most of the move happens in the next opening
  gap (limit-up continuation).
- **Medians are below means** for the positive events (BREAKOUT median -0.54%). The averages rest on a
  minority of large winners, and win rates stay below 50%.
- **Overlap with tested hypotheses.** ORDER_IMBALANCE_SPIKE_BUY overlaps the order-imbalance top decile,
  which failed validation after costs. BREAKOUT is the only positive event not already tested; promoting
  it needs a logged test and a pre-registration on clean data (forward). Its forward outcomes are now
  tracked automatically by the forward scoreboard.
- DIVERGENCE fires often (about 7% of liquid stock-days) because the foreign condition only requires a
  sign. A size threshold would be a v2 of the catalog.
