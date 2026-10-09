# Plan: Reproducibility metadata + Exposure Engine

<!-- type: feature -->
<!-- status: built 2026-10-08 (approved 2026-10-08) -->

Source: `project-review-vn-stock-quant.md`, sections 27 (Exposure Engine), 30 and 37 (reproducibility),
39 (roadmap). Both items were chosen because they do not consume validation data.

## Part 1: Reproducibility metadata

Today each run stores `feature_build_id`, `code_hash` (top-level `quant_research/*.py` and SQL only), the
pre-registration hash, and for cross runs the cross build id. Missing: the **git commit**, a
**dataset version**, the **configuration hash**, and code in the subpackages (`backtest/`, `cross/`).

| Change | Detail |
|--------|--------|
| `provenance()` helper | Returns `git_sha` (`git rev-parse HEAD`), `git_dirty` (uncommitted changes in `src/`), `warehouse_sha` (SHA-256 of warehouse.duckdb, recorded by `quant build`), `feature_build_id`, `code_hash`, `config_hash` (hash of the run parameters) |
| `quant build` | Stores `warehouse_sha` in `feature_builds` (new column; history carried over by column name). The file is already hashed before and after every build, so this adds no cost |
| `code_hash` | Covers every `.py` file under `quant_research/` and its SQL, including subpackages. Future runs get a new hash value; old runs keep theirs |
| Every run | `ResultsStore.start_run` adds `provenance` to the stored `params` JSON: pattern, scan, backtest, cross, event study and daily runs alike |
| Reports | One "Provenance" line at the top of the research, backtest, cross, event-study and daily reports |
| UI | The Research page run detail shows the provenance |

A run is then traceable to "commit + dataset + features + code + configuration". If the code was not
committed at run time, `git_dirty` says so, so the gap is visible instead of hidden.

## Part 2: Exposure Engine (`src/quant_research/exposure.py`)

Answers "what am I really holding?" for any list of positions: the watchlist, the paper portfolio, or later
a real portfolio.

| Metric | Definition (last 120 sessions, as of the latest data) |
|--------|--------------------------------------------------------|
| Market beta | OLS slope of the daily return on VNINDEX, per stock and for the portfolio |
| Portfolio volatility | Annualized, from the covariance of daily returns (pairwise complete) |
| Risk contribution | Share of portfolio variance per position: w_i (S w)_i / w'S w; the shares sum to 1 |
| Effective number of bets | (sum of eigenvalues)^2 / sum of eigenvalues^2 of the holdings' correlation matrix. It is N for N independent stocks and 1 for N copies of one stock |
| Concentration | Weight HHI and effective N of positions (1 / HHI) |
| Industry and cluster exposure | Weights summed by ICB level 2 and by the latest correlation cluster |
| Factor tilts | Weighted cross-sectional z-scores on the latest session: size proxy (ln ADV20), volatility_20, momentum (return_20d), order_imbalance, foreign_net_ratio_20. Each is ranked against the liquid universe that day |

Weights are equal by default. The paper portfolio uses its actual position values.

UI:
- Market watch, watchlist section: an "Exposure" panel with beta, volatility, effective number of bets vs
  number of stocks, industry and cluster bars, the top risk contributors and the factor tilts.
- Backtest and paper page: the same panel for the paper portfolio's open positions.

It is descriptive risk information; no test is logged.

## Tests

- Effective number of bets: N for an identity correlation matrix, 1 for an all-ones matrix.
- Beta equals `numpy.polyfit`; risk contributions sum to 1.
- Industry weights sum to 1; missing data is reported, not silently dropped.
- Provenance: the git SHA is recorded (or "unknown" outside a repo), `warehouse_sha` matches the file
  hash after a build, and every run type stores provenance.
- The UI pages render read-only; the full suite stays green.

## Rollback

Additive. The `feature_builds` column is new and nullable for old rows. Removing `exposure.py` and the UI
panels restores the previous state.

## Result (2026-10-08)

Built as planned. Full suite: 244 passed (10 new tests).

### Part 1: provenance

- `src/quant_research/provenance.py`: `git_info()` (HEAD SHA and a dirty flag for `src/`, "unknown" outside a
  repo), `config_hash`, `collect`, `line`, `from_runs`.
- `ResultsStore.start_run` stores `params.provenance` for every run: git SHA and dirty flag, `warehouse_sha`,
  `feature_build_id`, `code_hash`, `config_hash`.
- `code_hash` now covers every `.py` and `.sql` file under `quant_research/` recursively (relative path plus
  bytes). This changes the hash value compared with older runs; old runs keep their stored value.
- `feature_builds.warehouse_sha` (nullable); history rows are copied by name, so research databases built
  before the column existed keep their history.
- Reports show one provenance line: pattern and scan reports, backtest, cross-stock, event study, daily.
- Tests: `tests/research/test_provenance.py` (3).

### Part 2: Exposure Engine

- `src/quant_research/exposure.py`: pure functions (`normalize`, `betas`, `effective_bets`, `risk_shares`,
  `compute`). A symbol needs clean returns on at least 80% of the window; otherwise it is listed as missing,
  left out, and the remaining weights are re-normalized.
- `src/stock_ui/exposure_data.py`: read-only queries with bound parameters. Returns are close-to-close on
  adjusted prices, set to NULL when either day is untraded, a price jump, or a bad source date. Factor tilts
  are cross-sectional z-scores (winsorized at 1% / 99%) against liquid stocks (ADV20 > 1bn VND) on the latest
  feature date; the tilt is the weighted mean over covered symbols, with the covered weight shown.
- `src/stock_ui/exposure_panel.py`: shared panel. Wired into Market watch (watchlist, equal weights) and
  Backtest and paper (open positions of the latest re-simulation, market-value weights).
- Tests: `tests/research/test_exposure.py` (7); `tests/ui/test_pages.py` asserts the panel on both pages,
  including the "left out" note for a delisted position.

On real data (as of 2026-10-07; database files unchanged by rendering):

| Holdings | Beta | Volatility (annual) | Effective bets |
|----------|------|---------------------|----------------|
| Watchlist SSI, HCM, VND, FTS, BSI, FPT, VCB (equal weights) | 0.87 | 23.0% | 2.8 of 7 |
| Paper portfolio (20 positions) | 0.38 | 11.7% | 13.3 of 20 |

The watchlist behaves like fewer than three independent positions: the five brokers move as one. Its factor
tilts are large size (+1.18) and weak recent momentum (-0.79). Descriptive only; nothing was logged.
