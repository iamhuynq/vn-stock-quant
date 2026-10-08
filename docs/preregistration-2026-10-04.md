# Pre-registration: validation of Phase 3 candidates

Written 2026-10-04, **before** any query on the validation period (2024-01-01 to 2025-12-31).
The SHA-256 of this file is stored with every validation run (`research_runs.params.extra`).
Any change to this file after the validation runs invalidates the pre-registration.

## Data and settings (fixed)

- Feature build: latest `quant build` at run time (feature set v1); results store `data/results.duckdb`.
- Universe: `ResearchParams()` defaults: `is_traded`, `adv_value_20 > 1e9`, `session_index > 20`,
  no `price_jump` (today or in the next 20 sessions), no `bad_source_date`, no `entry_blocked`,
  no `crosses_period`.
- Outcome: `fwd_excess_exec_{5,10,20}d` (enter next open, exit close t+h, minus VNINDEX).
- Cost: 0.4% round trip.
- Statistics: date-level means, Newey-West SE (lag h-1), lift = pattern minus universe on the same dates.

## Candidates (exact definitions = `src/quant_research/patterns.py`, versions below)

| ID | Pattern | Definition | Research-period lift 10d (t) | Direction expected |
|----|---------|------------|------------------------------|--------------------|
| C1 | `order_imbalance_d10` | top decile of `order_imbalance` per date | +0.73% (7.1) | positive |
| C1b | `order_imbalance_d10_no_limit` | C1 excluding `limit_up` days | +0.74% (7.4) | positive |
| C2 | `momentum10_d10` | top decile of `return_10d` per date | +0.72% (4.7) | positive |
| C3 | `drop3_volume2_sellers` | `return_1d < -0.03 AND volume_ratio_20 > 2 AND order_imbalance < -0.4` | -4.55% (-3.5) | negative |

Not carried forward: the foreign-selling refinement of 5-session momentum (`momentum5_foreign_sell` vs
`momentum5`) added no significant information in the research period (difference +0.24%, q = 0.22).

Pattern versions (hash of the definition; a different hash means a different hypothesis):

- `order_imbalance_d10` version `0a1952fa`
- `order_imbalance_d10_no_limit` version `dc53588e`
- `momentum10_d10` version `5905e5b3`
- `drop3_volume2_sellers` version `cb8daa50`

## Decision rule (primary horizon: 10 sessions)

1. Primary family: the four 10d lift tests (C1, C1b, C2, C3). Benjamini-Hochberg over these four.
2. **C1, C1b, C2 pass** if lift_10d > 0 with BH-adjusted p < 0.05 **and** the absolute pattern mean
   after cost at 10d is > 0.
3. **C3 passes** (as an avoid/exit signal) if lift_10d < 0 with BH-adjusted p < 0.05.
4. 5d and 20d results are reported as secondary evidence only; they do not change the decision.
5. A candidate that fails is recorded as failed. Changing a definition after seeing validation results
   creates a new hypothesis that can only be tested on data the definition has not seen (the 2026
   holdout, or future data).

## What a pass means

A pass means the effect replicated out of sample, after costs, on the stated universe. It is not yet a
trading strategy: turnover, position sizing, capacity and portfolio construction belong to Phase 6
(backtest).
