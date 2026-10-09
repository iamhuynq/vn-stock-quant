# Plan: Factor Engine

<!-- type: feature -->
<!-- status: built 2026-10-08 (approved 2026-10-08) -->

Source: `project-review-vn-stock-quant-1.md`, section 24 (Factor Engine) and 39 (roadmap, priority 2). It is
infrastructure: no hypothesis is tested, and no validation, holdout or forward outcome is read.

## Problem

Each piece of code that needs a cross-sectional score builds its own:
- the decile scans and patterns rank raw features per date;
- the Exposure panel winsorizes and z-scores five features in the UI, on the latest date only;
- the planned Regime and Interaction work would add more copies.

There is no shared, point-in-time table of normalized factor scores. There is also no view of how the
factors relate to each other ("is this feature independent of the other factors?", section 45).

## Design

### Factor set f1 (only what the data supports)

| Factor | Raw value (trailing data only) | Notes |
|--------|--------------------------------|-------|
| `liquidity` | `ln(adv_value_20)` | Also the size proxy: there is no market capitalization in the warehouse (no shares outstanding) |
| `momentum_12_1` | `adj_close_{t-21} / adj_close_{t-250} - 1` | Classic 12-1 momentum, skips the last month; NULL before 250 sessions |
| `momentum_1m` | `return_20d` | |
| `reversal_1w` | `-return_5d` | Sign: high = recent loser |
| `volatility` | `volatility_20` | |
| `beta` | `regr_slope(return_1d, mkt_ret_1d)` over 250 sessions, at least 200 traded | Market beta |
| `order_flow` | mean `order_imbalance` over 5 sessions | Order placements, not fills |
| `foreign_flow` | `foreign_net_ratio_20` | NULL where `foreign_inconsistent` in the window |
| `volume_surge` | `volume_ratio_20` | |

Value and Quality are **not possible**: they need fundamentals, and direction B was stopped on 2026-10-08.

### Normalization (per date, over the scoring universe)

- **Scoring universe**: `is_traded`, `adv_value_20 > 1e9`, `session_index > 20`, `NOT price_jump`, and
  `NOT bad_source_date` (the same as `ResearchParams()`), with at least 30 stocks per date. Rows outside
  the universe get no score.
- **Pipeline**: raw → winsorize at the 1st / 99th percentile → percentile rank (0 to 1) → z-score of the
  winsorized value → quintile bucket (1 to 5).
- **Industry-neutral z**: z minus the mean z of the stock's ICB level-2 industry on that date, for
  industries with at least 3 scored stocks.
  - Limitation: industry codes are today's classification, not point in time (the same caveat as
    Phase 4b).

### Storage (`research.duckdb`, rebuilt by `quant build`)

```sql
stock_factors (date, symbol, factor, value, winsorized, rank_pct, z, bucket, z_industry,
               PRIMARY KEY (date, symbol, factor))
factor_definitions (factor, version, definition, sign_note)   -- version = hash of the factor SQL
```

- The data comes from a new `sql/07_stock_factors.sql`, run after the features in the same atomic build.
- Estimated size: about 1.2M scored rows x 9 factors, roughly 11M rows. Expected extra build time: under
  a minute (today's build takes 19 s). If the build becomes too slow, the fallback is to score month-ends
  only for the research period; that would need your decision.

### Factor structure report (descriptive, no returns)

`quant factors describe` writes `data/reports/research/factors-<build>.md` for the research period only
(<= 2023). The report uses no forward returns, so nothing is tested and nothing goes into the hypothesis
log. Contents:
- coverage per factor and per year;
- the average cross-sectional Spearman correlation between factors, per regime (Bull / Bear / Sideway);
- rank persistence: autocorrelation of `rank_pct` at 1, 5 and 20 sessions, which shows how much turnover a
  factor implies;
- the share of each factor's variance explained by industry (R² of z on industry dummies).

### Consumers switched to the shared table

- The Exposure panel reads factor z-scores from `stock_factors` on the latest date instead of computing
  them in the UI. The tilts then cover all nine factors, and the panel adds a "beta (250d)" column.
- Patterns and the decile scan are **not** changed: their definitions are frozen by version hashes, and
  changing them would change the meaning of logged runs.

### UI

The Symbol page gets a "Factors" tab: the stock's factor ranks on the latest date and their history over
the last year.

## Not in scope

- Testing factor returns (IC or long-short spreads against forward returns). A factor return study is a
  new hypothesis family. It needs a pre-registration, and it can only be confirmed on forward data. It will
  be planned separately if you want it.
- Regime and Interaction engines (the next roadmap items).

## Tests

- Each factor equals a pandas reference on the synthetic warehouse: raw value, winsorization, rank, z,
  bucket and industry-neutral z.
- Point in time: perturbing data after date t leaves every factor at t unchanged; the test is non-vacuous.
- Universe: no score outside the universe, no score on dates with fewer than 30 stocks, and NULL raw
  values stay unscored.
- The Exposure panel tilts equal the `stock_factors` z-scores on the latest date.
- The describe report contains no forward-return column and writes no row to `hypothesis_log`.
- The full suite stays green; the build is still atomic, and the warehouse hash is unchanged by a build.

## Rollback

Additive: one new table pair in the rebuilt `research.duckdb`, one SQL file, one CLI command, and UI
reads. `results.duckdb` and the warehouse are not touched. To roll back, revert the code and run
`uv run quant build`, which rebuilds `research.duckdb` without the table. No data is lost: the research
database is derived and rebuilt atomically.

## Open questions (defaults used unless you say otherwise)

1. Factor set f1 as in the table. Value and Quality are left out because there are no fundamentals.
2. Score every session; switch to month-ends for the research period only if the build exceeds about
   2 minutes.
3. The 12-1 momentum window is 250 sessions and skips the last 21.

## Result (2026-10-08)

Built as planned; open questions answered with the defaults. Full suite: 265 passed (6 new in
`tests/research/test_factors.py`). The UI page tests still pass.

### What was built

- `src/quant_research/factors.py`:
  - factor set f1 (9 factors) and the normalization SQL;
  - `FactorParams`, so tests can use small universes; real builds use the defaults;
  - factor version `28f1eba3`.
- `quant build` builds factors in the same atomic transaction. `code_hash` now includes `factors.py`.
- `src/quant_research/factor_report.py` and `quant factors describe`. They read `research.duckdb` read-only;
  no forward return is used and nothing is logged.
- Consumers:
  - The Exposure panel reads `stock_factors`. Its tilts now cover all 9 factors, and positions show
    `beta_250` next to the 120-session beta.
  - The Symbol page has a "Factors" tab: latest ranks and z-scores, plus a 12-month rank chart.
- Details not in the plan:
  - Return factors are NULL when a `price_jump` lies in their window.
  - Rank ties share the lowest rank.
  - Single-stock dates have a NULL z (zero variance).

### Tests

- All 9 raw factors equal a pandas reference on the synthetic warehouse, with SQL NULL semantics.
- Winsorize, rank, z, bucket and industry-neutral z equal pandas on random data with ties, a tiny
  industry, a NULL industry and a date below the minimum.
- Nothing is scored outside the universe; the 30-stock minimum is enforced.
- Point in time: a perturbation after the cut date leaves every column up to that date identical; the
  test is non-vacuous.
- The Exposure z-scores equal `stock_factors`.
- The describe report's source has no `fwd_` or target table, and it writes no file in the data
  directory.

### Real data

- Build `20261008T214841`:
  - 26.9 s, against 19 s before;
  - 10,490,677 factor rows;
  - the warehouse hash is unchanged.
- The Symbol, Market watch and Backtest pages render with no database change.
- The paper portfolio's tilts show order flow +1.52, consistent with its order-imbalance selection.
- Report: `data/reports/research/factors-20261008T214841.md`.

### Factor structure, research period (descriptive)

- **Turnover.**
  - `beta`, `liquidity` and `momentum_12_1` are very persistent: rank correlation after 20 sessions is
    0.98, 0.86 and 0.90.
  - `momentum_1m` (0.03), `reversal_1w` (0.01) and `volume_surge` (-0.08) are fully renewed within a
    month: a portfolio sorted on them implies high turnover, hence high costs.
  - `order_flow` keeps 0.40 after 5 sessions and 0.20 after 20.
- **Overlap.**
  - `momentum_1m` and `reversal_1w` correlate at -0.44 (shared recent days).
  - `order_flow` correlates with `reversal_1w` at -0.32: buyers dominate in stocks that just rose.
  - `beta` correlates with `liquidity` (0.30) and `volatility` (0.29; 0.43 in Bear markets).
  - Otherwise the factors are close to independent (|rho| < 0.15).
- **Industry.** It explains 10% to 23% of each factor's cross-sectional variance; beta has the most at
  23%.
