# Plan: Pattern Discovery (Phase 3 of the Quant Research System)

<!-- type: feature -->
<!-- status: done 2026-10-04 (research scan + patterns, pre-registered validation); see docs/validation-results-2026-10-04.md -->

Source of requirements: `quant_research_chung_khoan_viet_nam.md` sections 5, 14, 18, 19, 23, 24, 26
(Phase 3) and 28. Input: `data/research.duckdb` (Phase 2, read-only).

## Goal

Answer, with honest statistics, the doc's central question: **"After state X, what usually happens
over the next sessions?"** Two tools:

1. **Feature scan** (doc 26, Phase 3: "feature -> T+1/T+3/T+5/T+10"): for every feature, does a
   higher value predict higher or lower future excess return?
2. **Pattern test** (doc 5.1, 5.2, 14, 28): for a named condition such as
   `return_1d < -0.03 AND volume_ratio_20 > 2`, what are the future outcomes, by regime and exchange,
   after costs, and does each extra condition add information?

Every run is stored, reproducible and counted for multiple-testing control.

## Scope

In scope: results database, statistics module, feature scan, pattern engine, a starter pattern library
taken from the doc, Markdown reports, holdout gate.
Out of scope: cross-stock analysis (Phase 4), event engine and daily scanner (Phase 5), portfolio
backtest (Phase 6), ML (Phase 7), dashboards.

## Key decisions (defaults chosen; change any you disagree with)

| Topic | Default | Why |
|-------|---------|-----|
| Outcome measured | `fwd_excess_exec_5d/10d/20d` (enter next open, minus VNINDEX); `fwd_ret_close_1d/3d` reported as descriptive only | Tradable and market-neutral; T+1/T+3 are not tradable under T+2 |
| Universe filter | `is_traded`, `adv_value_20 > 1e9`, `session_index > 20`, `NOT price_jump`, `NOT fwd_has_price_jump_20d`, `NOT bad_source_date`, `NOT entry_blocked`, `NOT crosses_period` | From Phase 2 findings; about 1.1M rows |
| Statistical unit | **the date**: average outcomes of all events on the same date, then test the series of dates | Events on one day are not independent (a market drop triggers hundreds) |
| Overlapping horizons | Newey-West standard errors with lag = horizon - 1 on the date series | 10-day outcomes of consecutive days overlap |
| Costs | 0.4% round trip (2 x 0.15% fee + 0.1% sell tax), configurable | Doc 17, 19 |
| Feature scan buckets | Deciles **within each date** (cross-sectional ranks) | Robust to heavy tails; removes market-wide level shifts |
| Multiple testing | Every test p-value logged; Benjamini-Hochberg q-values recomputed over the whole log | Doc 18; many features x horizons x patterns |
| Periods | `research` (<= 2023) by default; `--period validation` explicit; `holdout` only with `--final`, which is logged and counted | Doc 18; protects the unseen test set |

## Architecture

```
research.duckdb (READ_ONLY)          results.duckdb (persistent, never rebuilt)
   feature_target  ----------->        pattern_definitions   name, version, condition SQL, hypothesis
                    quant scan         research_runs         run_id, kind, pattern, period, params,
                    quant pattern                            feature build_id, code hash, created_at
                                       pattern_stats         run_id, horizon, segment, n_events, n_dates,
                                                             mean, median, win_rate, std, se_nw, t, p,
                                                             ci_low, ci_high, mean_after_cost
                                       scan_stats            run_id, feature, horizon, decile, mean, n_dates,
                                                             + spread (D10-D1), rank IC, t, p
                                       pattern_occurrences   run_id, symbol, date, outcomes (for drill-down)
                                       hypothesis_log        run_id, test label, p_value, q_value, period
                                   -> data/reports/research/{run_id}.md
```

`results.duckdb` is separate because `research.duckdb` is replaced on every feature build. Each run
records the feature `build_id` it used, so a result can always be traced to its data.

## 1. Statistics module (`quant_research/stats.py`)

- `date_series(events)`: mean outcome per date, plus event counts.
- `newey_west_se(series, lag)`: HAC standard error of the mean (Bartlett weights).
- Summary for a set of events: `n_events`, `n_dates`, mean, median, win rate, std, p01/p99, NW t-stat,
  two-sided p-value, 95% CI, mean after cost.
- `rank_ic(feature, outcome)` per date (Spearman), then mean IC and NW t-stat over dates.
- `benjamini_hochberg(p_values)`.
- Dependencies: `numpy`, `scipy` (t distribution); `statsmodels` used **only in tests** to cross-check
  Newey-West and BH results.

## 2. Feature scan (`quant scan`)

For each numeric feature (30) x outcome horizon (5d, 10d, 20d), on the filtered universe:
- decile by date -> mean excess return per decile (date-level), monotonicity;
- spread D10 - D1 with NW t-stat; rank IC with NW t-stat;
- split by `market_regime` (Bull / Sideway / Bear) and by `exchange_now`.
Output: a ranked table of features by |t| of spread and IC, each with its q-value.
About 30 x 3 = 90 logged tests per scan.

## 3. Pattern engine (`quant pattern`)

A pattern is a named, versioned condition over `feature_target` columns:

```python
Pattern(
    name="drop3_volume2",
    hypothesis="Sharp drop on heavy volume -> mean reversion over 5-10 sessions",
    where="return_1d < -0.03 AND volume_ratio_20 > 2",
    base="drop3",          # optional: the simpler pattern it refines (doc 5.2)
)
```

For each horizon: summary statistics (section 1), by regime and exchange, after cost, plus the
comparison with `base` (difference of means with NW t-stat) to answer "does the extra condition add
information?". Occurrences are stored for drill-down (e.g. where VOS 2026-07-30 sits).

Pattern conditions are SQL fragments run on a **read-only** connection; they come only from the
repository's pattern library or from the user's own command line.

## 4. Starter pattern library (taken from the doc)

| Name | Condition | Doc |
|------|-----------|-----|
| `drop3` | `return_1d < -0.03` | 5.1 |
| `drop3_volume2` | `drop3 AND volume_ratio_20 > 2` | 5.2 |
| `drop3_volume2_sellers` | `drop3_volume2 AND order_imbalance < -0.4` | 5.2 |
| `surge4_volume_close_high` | `return_1d > 0.04 AND volume_zscore_20 > 2 AND close_position > 0.8` | 28 |
| `volume_spike` | `volume_ratio_20 > 3` | 24 |
| `volume_spike_flat` | `volume_ratio_20 > 8 AND abs(return_1d) < 0.002` | 14 |
| `foreign_accumulation_no_breakout` | `foreign_net_ratio_20 > 0.1 AND return_20d < 0.02` | 13, 28 |
| `foreign_divergence_up` | `return_5d > 0.05 AND foreign_net_5d < 0` | 13 |
| `imbalance_positive_price_down` | `order_imbalance > 0.5 AND return_1d < -0.02` | 14 |
| `drop3_volume2_foreign_sell` | `drop3_volume2 AND foreign_net_value < 0 AND order_imbalance < -0.3` | 28 |

## 5. Reports

`data/reports/research/{run_id}.md`: definition, period, universe, sample sizes, per-horizon table,
regime/exchange split, after-cost line, comparison with base, q-value, and a plain-language verdict
(effect / effect eaten by costs / no effect), with the caveat that research-period results are not
yet validated.

## 6. Implementation steps

1. `stats.py` + tests (synthetic series with known answers; cross-check against statsmodels).
2. `results.duckdb` schema + run registry + hypothesis log with BH recomputation + holdout gate.
3. Pattern engine + library + report; tests on the synthetic warehouse from Phase 2.
4. Feature scan + report; tests.
5. Run the scan and the 10 starter patterns on the `research` period.
6. **Checkpoint: review results with the user.** Only then, and only for chosen candidates, run
   `--period validation`. The holdout stays untouched.

## Success criteria

- [ ] NW standard errors and BH q-values match statsmodels in tests
- [ ] A pattern with no real effect (random condition) is not significant after BH in a test
- [ ] Holdout runs are refused without `--final`; `--final` runs are logged and counted
- [ ] Every run stores pattern version, feature build_id, code hash, params and period
- [ ] research.duckdb and warehouse.duckdb file hashes unchanged by any `quant scan/pattern` run
- [ ] Scan + 10 patterns complete on the research period with reports

## Testing

- All: `uv run pytest`
- Single file: `uv run pytest tests/research/test_stats.py`
- Single test: `uv run pytest tests/research/test_stats.py::test_newey_west_matches_statsmodels`
- Integration: scan and patterns on the real research database

## Rollback

Phase 3 writes only `data/results.duckdb` and `data/reports/research/`. Inputs are opened read-only.
Bad results (e.g. a bug found later): mark the affected runs `invalid` with a reason (`quant runs
invalidate <run_id>`) instead of deleting them. Deleting the results database would also erase the
hypothesis log and silently weaken the multiple-testing correction, so it is reserved for a broken
schema and must be recorded in `docs/pattern-discovery-plan.md`.

## Changes during execution (2026-10-04)

- **Primary test changed to lift vs the universe.** The first batch tested each pattern's mean
  against zero. The tested quantity is now the date-level *lift*: pattern mean minus the mean of all
  filtered stocks on the same dates (`pattern_lifts`, logged as `lift_*`). Absolute mean after costs is
  still reported for tradability. Universe baseline on the research period: +0.07% / +0.16% / +0.37%
  (5/10/20d, not significant), event-level win rate about 46% (right-skewed returns), so a ~45% win
  rate is normal and not a signal by itself.
- The first batch (10 runs) was **invalidated, not deleted** (reason recorded); its 42 logged tests stay
  in `hypothesis_log` but are excluded from q-values.
- Bug fixed: `fetchnumpy()` returns masked arrays for NULLs; converting with `np.asarray` exposed the
  data under the mask, so missing outcomes could be read as 0. NULLs are now filled with NaN explicitly
  and occurrences are inserted in SQL (regression test added). The earlier attempt also crashed
  pyarrow on masked object arrays.
- A flaky single-sample test was replaced by a null-calibration test (400 simulated overlapping series,
  rejection rate within 2-10% at the 5% level).
- Bug fixed: DuckDB `corr()` returns NaN (not NULL) on zero-variance days; the SQL only filtered NULL,
  so a single NaN day made a feature's mean IC NaN (seen for `sell_pressure`, 4 of 4,091 days). The
  first scan run was invalidated (reason recorded) and the scan re-run; regression test added.
- Note for reading the scan: `order_imbalance` and `buy_sell_ratio` are monotonic transforms of each
  other, so their decile and rank results are identical (one feature, not two pieces of evidence).
