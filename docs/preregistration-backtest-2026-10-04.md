# Pre-registration: holdout test of the order-imbalance portfolio

Written 2026-10-04, before any backtest run on the validation (2024-2025) or holdout (2026) period.
Holdout runs so far: 0. The SHA-256 of this file is stored with the validation and holdout runs.
This file must not be edited after those runs.

## Configuration (frozen)

| Item | Value |
|------|-------|
| Strategy version | `72c851c7` (hash of strategy + universe parameters below) |
| Signal | top decile of `order_imbalance` per date, point-in-time universe (`UniverseRule()` defaults: `adv_value_20 > 1e9`, `session_index > 20`, traded, no `price_jump`, no `bad_source_date`, at least 30 ranked stocks) |
| Holding | `hold_sessions = 10`, renewal on (decided with the previous close's signal) |
| Positions | `max_positions = 20`, equal weight (equity / 20 at the previous close) |
| Capital | `initial_equity = 1e9` VND |
| Capacity | each entry capped at 5% of `adv_value_20` of the signal date |
| Costs | fee 0.15% each side, sell tax 0.1% (0.4% round trip) |
| Execution | buy at next open (skip if ceiling open or no trade); sell at close (retry if floor or no trade); T+2 |
| Data | feature build `20261004T180805` (data as of 2026-10-02); code hash `d6d9ef266e5fa42b` |
| Random control | 20 runs, seeds 0-19, same engine/parameters, random 10% of the universe per day |

Why this variant: best research-period evidence against the equal-weight universe (q = 0.017), holding
period equal to the signal horizon, renewal lowers turnover, and its neighbours (H5/K20, H10/K10) give
similar results. Research-period figures are in-sample twice over (signal chosen from 30 features and
variant chosen from 24 runs on the same period) and are expected to overstate future performance.

## Holdout test (2026-01-01 to the latest data, run once with `--final`)

1. **Primary**: the strategy's final equity beats at least **19 of the 20** random-control runs
   (about p < 0.05).
2. **Secondary**: total return after costs > 0.
3. Pass = primary and secondary both hold. Anything else = fail, recorded as such.
4. Reported but not decisive: equal-weight universe and VNINDEX comparison, drawdown, turnover,
   capacity-capped entries, the 2024-2025 run (labelled "already seen"), and the same configuration at
   10e9 VND capital.
5. The holdout is about 185 sessions: a pass is weak confirmation, a fail is meaningful. No parameter is
   changed after seeing the result; a new idea is a new hypothesis for future data.
