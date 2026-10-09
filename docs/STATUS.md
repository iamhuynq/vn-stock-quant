# Project status

Last updated: 2026-10-09. Update this file at the end of every task.

## Data

- Warehouse through session 2026-10-07 (`data/.daily_done` = 2026-10-07). Collection is manual.
- Paper portfolio (frozen strategy, forward data) started 2026-10-06.

## Roadmap (design doc phases)

| Phase | State | Docs |
|-------|-------|------|
| 1 Historical database | Built (crawler, warehouse, validation, daily catch-up) | `crawler-plan.md`, `daily-pipeline-plan.md`, `data-dictionary.md` |
| 2 Feature engine | Built | `feature-engine-plan.md`, `feature-dictionary.md` |
| 3 Pattern discovery | Built and validated | `pattern-discovery-plan.md`, `validation-results-2026-10-04.md` |
| 4 Cross-stock | Built; 4b industry groups built | `cross-stock-*.md`, `group-analysis-*.md`, `group-momentum-validation-2026-10-08.md` |
| 5 Event engine | Built (catalog v1, 12 types, event study) | `event-engine-plan.md` |
| 6 Backtesting | Built; holdout failed; forward paper trading running | `backtest-plan.md`, `backtest-results-2026-10-04.md` |
| 7 Machine learning | Not started | - |

Also built: Streamlit UI (`ui-plan.md`), Market watch dashboard (`dashboard-plan.md`), run provenance and
Exposure Engine (`provenance-exposure-plan.md`), Research Registry (`research-registry-plan.md`),
Factor Engine f1 (`factor-engine-plan.md`), Regime Engine and Interaction Engine
(`regime-interaction-plan.md`), Economic Validation Layer (`economic-validation-plan.md`), Portfolio
Construction (`portfolio-construction-plan.md`).

Stopped: fundamentals (direction B), `fundamental-plan.md`, stopped by the user on 2026-10-08.

## Research conclusions

Source of truth for decisions: the Research Registry (`uv run quant registry list`, Research page >
Registry). Summary:

- No signal tested so far is profitable after trading costs.
- Only validated signal: the avoid signal `drop3_volume2_sellers` (PASS).
- Order imbalance is predictive but uneconomic after costs.
- Portfolio backtest failed on the holdout. Economic evaluation (2026-10-09): the in-sample edge was real
  selection skill (it beats random, industry-matched and beta-matched controls), but it absorbs only
  0.415% of extra cost per side, while realistic spread and impact cost 0.6% to 0.8%. Its CAGR is
  -10.9% under cost model v1, against +14.3% with flat costs (`economic-results-2026-10-09.md`).
- Portfolio construction grid (2026-10-09, six configurations): none beats equal weight after realistic
  costs.
  - Slower order-flow portfolios cut turnover but lose the signal.
  - Top-20 momentum 12-1 underperforms even before costs: extreme winners lag, and it is worse than
    random portfolios with the same turnover.
  - Order flow beats turnover-matched random portfolios, but cannot pay its costs.
  - The Bear filter helps, but not enough. `P7-IX-momentum_12_1-direction` is rejected
    (`portfolio-results-2026-10-09.md`).
- Cross-stock lead-lag lives in the opening gap (stale prices), not in tradable returns.
- Industry momentum failed validation (2026-10-08); the hypothesis is closed.
- Event study (descriptive): downside events are followed by underperformance; BREAKOUT is the only new
  positive candidate, tracked on forward data.
- Interaction scan (research period, 2026-10-08): 14 of 54 factor x regime tests pass the declared
  candidate rule (registry `P7-IX-*`). They form about 3 to 4 themes: order flow and liquidity matter more
  in weak / risk-off markets, and momentum 12-1 works in Bull, not Bear. Most effects fade after 2015.
  These are statistical only; confirmation needs a pre-registration and forward data
  (`interaction-results-2026-10-08.md`).

## Open items

- Committed on 2026-10-09 to branch `research-platform` (one commit on top of `9b8bdf8`); not pushed.
  The user pushes: `git push -u origin research-platform`, then merges into `main` on GitHub.
  `CLAUDE.md` stays local: it is ignored by the user's global gitignore.
- Whitelist tightened (2026-10-09). Tickers are upper-case letters and digits with at most one upper-case
  hyphen suffix; ICB codes are digits only. `/symbols/all-financial-data` and other lower-case endpoint
  names are rejected. All 2,012 warehouse symbols and every ICB code still pass.
- Next from `project-review-vn-stock-quant-1.md` (agreed order 2026-10-08):
  1. Research Registry: done.
  2. Factor Engine: done (f1, 9 factors; no Value / Quality without fundamentals).
  3. Regime / Interaction: done (one research-period scan, 14 candidates).
  4. Economic Validation Layer: done (cost model v1, benchmarks, matched controls, `quant econ evaluate`).
  5. Portfolio Construction: done (grid C1-C6, none passes; momentum x direction rejected).
  6. Remaining review item: ML (last; the review advises against it until a signal survives costs).
     Rule from now on: any strategy candidate passes `quant econ evaluate` / `quant portfolio evaluate`
     (research period) before a pre-registration. The portfolio control is persistence-matched
     (fixed 2026-10-09).
- Backups `data/results.before-registry.duckdb`, `data/results.before-interactions.duckdb`,
  `data/results.before-econ.duckdb`, `data/results.before-portfolio.duckdb` and
  `data/results.before-portfolio-v2.duckdb` can be deleted once the user is satisfied.
