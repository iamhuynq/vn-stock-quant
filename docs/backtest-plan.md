# Plan: Portfolio Backtest (Phase 6) - order-imbalance signal

<!-- type: feature -->
<!-- status: done 2026-10-04: holdout FAIL (see docs/backtest-results-2026-10-04.md) -->

Source of requirements: `quant_research_chung_khoan_viet_nam.md` sections 17-19, 26 (Phase 6), 27.
Inputs: `data/research.duckdb` (read-only). Motivation: `docs/validation-results-2026-10-04.md`
(order-imbalance top decile: lift replicated out of sample, but a one-trade-per-signal implementation
did not cover 0.4% costs against VNINDEX).

## Question

Can a realistic **long-only portfolio** built on the order-imbalance signal earn a positive return
after costs, and how does it compare with sensible benchmarks, under Vietnamese market constraints?

## Data discipline (most important section)

| Period | Status for this signal | Use in Phase 6 |
|--------|------------------------|----------------|
| research (<= 2023) | in-sample | build the engine, choose a small set of variants, all logged |
| validation (2024-2025) | **already seen** in Phase 3 | reported, clearly labelled "seen", never used to choose |
| holdout (2026-01-01 to latest) | untouched | **one** run of **one** pre-registered configuration, with `--final` |

The holdout is short (about 185 sessions in 2026 so far), so it can refute but not strongly confirm.
That limitation is stated in the final report whatever the outcome.

## Strategy definition (to be frozen before the holdout run)

- Signal at close of t: stock is in the top decile of `order_imbalance` within the filtered universe
  (same universe as Phase 3).
- Entry: buy at the open of t+1; skipped if t+1 opens at the ceiling (`entry_blocked`).
- Holding: hold at least H sessions; at the planned exit, **renew** instead of selling if the stock is
  in the top decile again (saves a round trip). T+2 settlement is respected by construction.
- Exit: sell at the close of the exit session; if that close is at the floor (`limit_down`) or the stock
  did not trade, retry the next session.
- Sizing: equal weight, at most K positions; a new position gets 1/K of equity; no leverage, cash earns 0.
- Capacity: a position is capped at 5% of `adv_value_20`; the cap and the unfilled share are reported.
- Costs: buy fee + sell fee + 0.1% sell tax; base case 0.15% fee each side (0.4% round trip); sensitivity
  at 0.25% and 0.3% round trip reported alongside (not used for the decision).

Variants allowed on the research period (each run logged): H in {5, 10, 20}, K in {10, 20},
renewal on/off -> 12 variants. The chosen variant and the reason are written into the pre-registration
before the holdout run.

## Point-in-time rules (added before coding)

- **Universe is point-in-time**: `is_traded`, `adv_value_20 > 1e9`, `session_index > 20`, no `price_jump`
  today, no `bad_source_date`. The Phase 3 filters `fwd_has_price_jump_20d`, `crosses_period` and
  `entry_blocked` look forward and are **not** used to select stocks (entry blocking is checked at the
  t+1 open, when it is known).
- **Order statistics are end-of-day**: the decision to renew at the close of day d uses the signal of
  day d-1; new entries at the open of d use the signal of d-1.
- **Data-error jumps** (`price_jump`, adjusted one-day move > 40%): a held position is closed at its last
  valid close and the event is counted (`exit_reason = data_error`), so source errors cannot create
  fake profits or losses.
- Prices are back-adjusted (dividends reinvested implicitly); fractional shares (no 100-share lots).

## Benchmarks

1. VNINDEX (buy and hold).
2. Equal-weight filtered universe, rebalanced daily (what an untimed small/mid-cap basket earned).
3. Random-selection control: same engine, same H/K/costs, positions drawn at random from the universe
   (seeded, 20 repetitions): isolates the signal from the portfolio mechanics.

No futures hedge in v1: the warehouse has no VN30 futures history (would need a new crawl).

## Metrics (doc 17)

Net return, CAGR, annualised volatility, Sharpe (rf = 0), max drawdown and duration, profit factor,
win rate per position, average holding, turnover, costs paid, exposure, capacity-capped share; per year
and per market regime; equity curves of strategy and benchmarks.

## Engine design

- `quant_research/backtest/` (pure Python + numpy/pandas): data loader (one query, needed columns only),
  daily event loop (signals -> orders -> fills -> positions -> equity), cost model, metrics, report.
- Deterministic: same inputs and seed give identical results; every run stored in `results.duckdb`
  (`backtest_runs`, `backtest_daily`, `backtest_trades`) with params, feature build id and code hash.
- Holdout gate as in Phase 3 (`--final`, logged) plus `--prereg` file hash.

## Tests

- Hand-built price paths with exact expected P&L: one round trip, renewal, costs, tax only on sells.
- Constraints: T+2 (no sale before t+3 for a buy at open t+1), blocked entry at ceiling, delayed exit at
  floor and on no-trade days, capacity cap, K limit, no leverage (cash never negative).
- No look-ahead: perturbing all data after day d leaves every decision up to d unchanged.
- Random-selection control on a planted-signal dataset earns ~0 lift; the signal earns the planted edge.
- Engine reconciliation: equity change = sum of position P&L - costs, every day.

## Steps

1. Engine + tests on synthetic data.
2. Benchmarks + random control + metrics + report.
3. Research-period runs of the 12 variants (logged); report.
4. **Checkpoint with user**: choose one variant; write and hash the pre-registration.
5. Validation-period run of the chosen variant (labelled "seen").
6. Holdout run, once, with `--final`; results document; no changes afterwards.

## Success criteria (for the engine; the strategy outcome is whatever the holdout says)

- [ ] All constraint and reconciliation tests pass; deterministic reruns
- [ ] research.duckdb hash unchanged by any backtest run
- [ ] 12 research variants + benchmarks + random control reported with costs
- [ ] One pre-registered holdout run with stored prereg hash; holdout run count = 1

## Rollback

Writes only `results.duckdb` (new tables) and `data/reports/backtest/`. Runs are invalidated, never
deleted. Inputs are read-only.

## Decisions taken by default (change if you disagree)

- Long-only, no leverage, no futures hedge (no data yet).
- Entry next open, exit at close; 0.4% round trip base case.
- Universe and signal identical to Phase 3 C1 (no new tuning of the signal itself).
- 12 variants maximum on the research period.
