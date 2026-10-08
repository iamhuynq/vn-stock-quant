# Plan: Cross-stock Analysis (Phase 4 of the Quant Research System)

<!-- type: feature -->
<!-- status: built 2026-10-05; research results in docs/cross-stock-results-2026-10-05.md -->

Source: `quant_research_chung_khoan_viet_nam.md` sections 6 (correlation), 7 (lead-lag), 8 (stocks that
follow others), 9 (Granger), 10 (pair trading / cointegration), 11 (stock network), 23 (questions), 26
(Phase 4) and 30 (MVP: correlation matrix, lead-lag; "which stocks are related?", "is the relation stable?").
Input: `data/research.duckdb` (read-only). Builds on Phases 2, 3 and 6.

## Goals

Answer with honest statistics:
1. **Which stocks move together, and is that stable?** Rolling correlation, clusters, central stocks
   (doc 6, 11).
2. **Does stock or group A move before B?** Lead-lag at 1, 2, 3 and 5 sessions, and whether a lead-lag
   found in one year still holds the next year (doc 7, 8, 9).
3. **Do spreads of related pairs revert?** Cointegration of same-industry pairs (doc 10).
4. A UI page: peers of a symbol, rolling correlation of a pair, clusters, lead-lag results.

Non-goals: ML (Phase 7), new single-stock patterns, changes to the daily scanner (adding confirmed
cross-stock signals to it is a later step after validation).

## Traps this design guards against

| Trap | Why it matters here | Guard |
|------|---------------------|-------|
| **Nonsynchronous trading** | An illiquid stock's close is stale, so it "follows" liquid stocks on the next day by construction (well known; not tradable) | Liquid universe only; both stocks must trade on both days; tradable tests use **execution returns** (enter at the next open), where a stale-price effect is already in the opening gap |
| **Market factor** | Most correlation and lead-lag between two VN stocks is just VNINDEX | Work on **excess returns vs VNINDEX** (raw returns reported for reference) |
| **Multiple testing** | 200 stocks give about 20,000 pairs x 4 lags | Pairs are never tested one by one for significance. Only family-level tests are logged: e.g. "do the top-decile pairs of year Y keep a positive lag correlation in year Y+1, compared with shuffled pairs?". A handful of group hypotheses are logged individually |
| **Look-ahead** | Choosing pairs, leaders or a hedge ratio with data from the test window | Every selection (universe, leaders, pairs, beta, clusters) uses only the formation window that ends **before** the test window; covered by a perturbation test (change future data, past outputs must not change) |
| **No short selling** | VN cash market is long-only; a classic pair trade needs a short leg | Pair results are reported for the **long leg only** (buy the cheap leg), measured against the universe like every other pattern |
| **Data-period reuse** | Validation 2024-2025 was used for Phase 3; holdout 2026 is spent | Discovery on `research` (<= 2023) only. Confirmation of chosen hypotheses on validation with a **new pre-registration** (separate approval step). Forward data (>= 2026-10-03) keeps accumulating for a final check |

## Key decisions (defaults; change any you disagree with)

| Topic | Default | Why |
|-------|---------|-----|
| Universe per month | Top 200 by `adv_value_20` at the month end (and >= 1bn VND), traded on >= 90% of the window's sessions | Liquid enough for prices to be informative; about 20k pairs |
| Correlation windows | 60, 120 and 250 sessions, snapshot at each month end | Doc 6.1 (20 days is too noisy for pairs of daily returns; 20d is kept for the pair chart only) |
| Return series | Daily close-to-close excess return vs VNINDEX (descriptive); execution returns for tradable tests | See traps |
| Lags | 1, 2, 3, 5 sessions | Doc 7 |
| Lead-lag stability test | Walk-forward by year: rank pairs by lag correlation in year Y, test the top decile in year Y+1 against shuffled pairs | Directly answers "is the relationship stable?" |
| Group hypotheses (logged, few) | H1 industry leaders (top 3 by ADV in an ICB level-2 industry) -> other members, next 1-5 sessions; H2 large caps -> small caps; H3 strong leader event (leader +5% excess) -> followers that did not move yet | Doc 8 examples (FPT -> CMG, CTR); few, economically motivated |
| Clusters | Hierarchical clustering on `1 - correlation` (scipy, average linkage), compared with ICB industries (adjusted Rand index) | Doc 11 without a new graph library |
| Central stocks | Average correlation with the rest of the universe; leaders from H1 | Doc 11 "central stocks / potential leaders" |
| Cointegration | Engle-Granger on log adjusted prices, same ICB level-3 industry pairs, 250-session formation, next 60 sessions trading; entry when spread z > 2 | Doc 10; same-industry only keeps pair count and spurious hits down |
| Granger | For the pairs that pass the walk-forward stability test only, descriptive | Doc 9; testing every pair would only add noise |
| Dependency | `statsmodels` moves from dev to runtime (ADF / cointegration / Granger) | Well-tested implementations instead of our own |
| Storage | Derived matrices in a new rebuildable `data/cross.duckdb` (like research.duckdb); runs, tests and summaries in `results.duckdb` | Matrices are derived data; results are permanent and enter the hypothesis log |

## Architecture

```
research.duckdb (READ_ONLY)
   |  quant cross build            (fresh file + atomic replace, like quant build)
   v
cross.duckdb                       universe_monthly, corr_snapshots (pair, window, month, corr),
                                   leadlag_yearly (pair, lag, year, corr), clusters_monthly,
                                   centrality_monthly, coint_formation (pair, window, beta, adf_p)
   |  quant cross test --period research | validation --prereg FILE
   v
results.duckdb                     research_runs (kind = cross_*), cross_stats, hypothesis_log
   -> data/reports/cross/{run_id}.md    and the "Cross-stock" UI page (read-only)
```

Size estimate: about 20k pairs x 216 months x 3 windows = 13M correlation rows (DuckDB handles this
in seconds; file about 300 MB). Computed with numpy per month (200 x 200 matrices), not pair by pair.

## Steps

1. `cross build`: monthly universe, excess-return matrix, correlation snapshots, yearly lead-lag
   matrices, clusters, centrality, cointegration formation. Perturbation test for look-ahead.
2. Descriptive report: correlation level and stability (snapshot-to-snapshot correlation of the matrix,
   per-pair mean and spread over time), clusters vs ICB, most central stocks. No trading claims.
3. Lead-lag: walk-forward stability test (family level), H1-H3 with the Phase 3 machinery (date-level
   lift vs the universe, Newey-West, costs, segments by regime and exchange).
4. Cointegration: long-leg test of the spread rule; Granger for stable pairs (descriptive).
5. UI page "Cross-stock" (peers of a symbol, pair chart with rolling 20/60/120 correlation, clusters,
   lead-lag results).
6. Results write-up; candidate hypotheses for a pre-registration (validation needs your approval, as in
   Phase 3).

## Tests

- Synthetic data with a planted relation: B copies A's excess return one session later (with noise) ->
  lag-1 correlation found, persists in the walk-forward test; an unrelated pair does not.
- Planted nonsynchronous trap: B is A with a stale close (no trades some days) -> filtered out or shows
  no effect on execution returns.
- Planted cointegrated pair -> ADF p small, spread rule fires; random walks -> no cointegration.
- Look-ahead perturbation: altering data after month M leaves every snapshot up to M unchanged.
- Correlation, lag correlation and clustering cross-checked against pandas / scipy reference
  implementations on small inputs.
- The build never writes research.duckdb (file hash unchanged), same as `quant build`.

## Pre-mortem

- **Most likely failure**: a "strong" lead-lag that is really stale prices or the market factor. First
  symptom: the effect is large on close-to-close returns and vanishes on execution returns. Both are
  always reported side by side.
- **Second**: q-values of earlier work shift. Only a small number of family-level tests are logged; the
  report shows the family size before and after.
- **Third**: memory or time. 200 x 200 per month is small; pairs are never looped in Python.

## Rollback

- Additive: `rm data/cross.duckdb`, delete `src/quant_research/cross/`, the UI page and the tests;
  move `statsmodels` back to the dev group (`uv remove statsmodels && uv add --group dev statsmodels`).
- Runs in `results.duckdb` are invalidated with a reason, never deleted (`quant runs --invalidate`).

## Open questions (defaults used unless you say otherwise)

1. Universe size: **top 200** by liquidity per month (smaller = cleaner signals, fewer stocks covered).
2. Group hypotheses H1-H3 as listed, or others you want tested first (for example specific pairs such as
   VIC -> VHM, HPG -> HSG, VCB -> BID from the doc, tested as one pre-declared family)?
