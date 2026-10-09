# Plan: Economic Validation Layer (cost model v1 + benchmarks)

<!-- type: feature -->
<!-- status: built and run 2026-10-09 (approved 2026-10-09) -->

Source: `project-review-vn-stock-quant-1.md`, sections 32 (economic validation), 33 (transaction cost model)
and 34 (benchmarking). It is a prerequisite for:
- Portfolio Construction;
- any pre-registered forward test, which must fix its cost model before data is seen.

It uses no validation, holdout or forward data.

## Problem

- **Costs are a flat assumption.** Today's cost model is commission 0.15% per side, sell tax 0.10% and a
  cap of 5% of ADV20 per position. There is no spread and no market impact. A strategy that trades
  illiquid stocks, or trades often, looks cheaper than it is.
- **Benchmarks are incomplete.** They are VNINDEX, the equal-weight universe and random portfolios. There
  is no capitalization-style benchmark and no control that matches the strategy's industry or beta mix. A
  strategy can therefore look good just by holding high-beta stocks or one hot industry.

## Design

### 1. Cost model v1 (`quant_research/backtest/costs.py`; inputs built by `quant build`)

Cost per side, as a fraction of the traded value:

```
commission  0.15%                                   (as today)
sell tax    0.10% on sells                          (as today)
half-spread max(tick floor, CHL estimate)           (new)
impact      k * sigma_20 * sqrt(order value / ADV20) (new, square-root law)
```

- **Tick floor:** half a tick divided by the raw price. It uses the same tick rule as `daily_panel`:
  - HOSE: 10 / 50 / 100 VND by price level;
  - HNX and UPCOM: 100 VND.
- **CHL estimate:** the Abdi-Ranaldo (2017) close-high-low effective spread, made point in time.
  - For each session, the pair product (c_k - eta_k)(c_k - eta_{k+1}) is formed, with eta the mid of log
    high and log low.
  - The estimate is averaged over the pairs fully inside the previous 21 sessions (no pair uses data
    after t).
  - Negative means are floored at 0.
- **Impact:** square-root law with `sigma_20` = `volatility_20` and k = 1.0. Sensitivity runs use
  k = 0.5 and 2.0.
- **Timing:** all inputs are known at the previous close (the decision time). The table is
  `stock_trading_costs (date, symbol, tick_half_spread, chl_half_spread, half_spread, sigma_20, adv_value_20)`.
- **Engine:** `run(market, strategy, selector, costs=None)` takes an optional cost model.
  - `costs=None` reproduces today's results exactly: frozen strategies keep their version hash, and the
    paper portfolio is not changed.

### 2. Benchmarks and controls (`quant_research/backtest/benchmarks.py`)

| Series | Definition | Question it answers |
|--------|------------|---------------------|
| VNINDEX | as today | beat the market? |
| Equal-weight universe | as today | beat holding everything liquid? |
| **Liquidity-weighted universe** (new) | daily weights proportional to ADV20, as the value-weight proxy (no market capitalization in the warehouse) | beat a large-cap-style basket? |
| Random portfolios | as today: 20 runs, same mechanics | beat random selection? |
| **Industry-matched random** (new) | each day, every signal candidate is replaced by a random universe stock of the same ICB level-2 industry | is the edge more than an industry bet? |
| **Beta-matched random** (new) | the same, matching the Factor Engine beta quintile | is the edge more than a beta bet? |

The two matched controls run 20 seeds each, through the same engine and cost model.

### 3. Economic evaluation (`quant econ evaluate`)

For one strategy, on the **research period only** (other periods are refused: validation and holdout are
used; forward needs a pre-registration):
- **Capital grid** of 1e9, 10e9 and 100e9 VND, run with costs: flat (today), v1 (k = 1), and v1 with
  k = 0.5 and k = 2.
- **Metrics per run:**
  - CAGR, Sharpe and maximum drawdown;
  - turnover per year, and cost drag (the CAGR lost to costs);
  - excess over each benchmark;
  - share of random, industry-matched and beta-matched runs beaten.
- **Break-even:** the extra cost per side at which the net CAGR equals the equal-weight universe.
- **Storage and logging:** results go to `economic_results` in `results.duckdb`. The evaluation is
  descriptive: nothing is written to `hypothesis_log`, because it re-measures known strategies and makes no
  new claim.
- **Report:** `data/reports/research/econ-<run>.md`.

### 4. First use (one run, research period, descriptive)

Evaluate the frozen strategy `72c851c7`. Its in-sample result was CAGR 14.3% and it beat 20 of 20 random
runs. The evaluation shows how much of that survives:
- realistic spread and impact;
- the new benchmarks and matched controls.

This explains the holdout failure in economic terms, without touching the holdout.

## Not in scope

- Changing the paper portfolio or any recorded decision. The pre-registered cost assumptions stay as
  written.
- Portfolio Construction (the next roadmap item; it will use this cost model).
- Intraday data, order-book spreads and fitting k from real fills (none are available).

## Tests

- **Tick floor:** the half-spread per exchange and price level matches the `daily_panel` tick rule.
- **CHL estimator:**
  - equals a pandas implementation;
  - is point in time (a perturbation after t leaves the estimate at t unchanged; the test is
    non-vacuous);
  - recovers a known spread on a simulated price path, within tolerance.
- **Impact:** matches the formula, and is 0 for a 0 order.
- **Engine:** `costs=None` gives bit-identical results to the current engine on the synthetic market. With
  v1, every trade's cost equals the formula, and the costs paid add up.
- **Matched controls:** each day, the replacement stocks have the same industry / beta-bucket counts as the
  candidates, and runs are deterministic per seed.
- **Benchmark:** the liquidity-weighted curve equals a pandas reference.
- **Evaluate:** periods other than research are refused, and nothing is logged.
- The full suite stays green; the UI pages render.

## Rollback

- Additive: one table in the rebuilt `research.duckdb`, one table in `results.duckdb`, new modules and one
  CLI command. The engine default (`costs=None`) is unchanged.
- To roll back: revert the code and run `quant build`.
- Back up `results.duckdb` before the first evaluation. Evaluation runs are never deleted; they are
  invalidated with a reason if wrong.

## Open questions (defaults used unless you say otherwise)

1. Impact coefficient k = 1.0 as the main value, with 0.5 and 2.0 as sensitivity. There is no data to fit
   it.
2. The ADV20-weighted universe as the capitalization benchmark, because there is no market capitalization.
3. Evaluate only the frozen strategy `72c851c7` now. Other strategies can be evaluated later with the same
   command.

## Result (2026-10-09)

Built as planned; open questions answered with the defaults. Full suite: 291 passed (11 new in
`tests/backtest/test_costs.py`). Results and reading: `docs/economic-results-2026-10-09.md`.

### What was built

- `src/quant_research/backtest/costs.py`:
  - `stock_trading_costs`, built by `quant build`: tick floor, point-in-time CHL, `half_spread`,
    `sigma_20`, ADV20;
  - `CostModel`, with `k`, `spread` (`max` / `tick` / `none`) and `extra_flat`.
  - Real build `20261009T093420`: 5,213,849 rows; CHL coverage 99.9% of liquid rows.
- Engine: `run(..., costs=None)` is unchanged. Inputs come from the previous close, and missing inputs use
  counted fallbacks.
- `src/quant_research/backtest/benchmarks.py`: the liquidity-weighted curve, matched random selectors and
  the key matrices (industry, beta quintile).
- `src/quant_research/econ.py`, `econ_report.py` and `quant econ evaluate --strategy frozen`:
  - research period only, not logged;
  - table `economic_results` in `results.duckdb`.

### Deviations from the plan

- **Tick-only lower-bound variant** (`v1_k1_tick`). It was added after the spread inputs were inspected
  and before any evaluation: the 21-session CHL estimate is noisy, so `max(tick, CHL)` overstates the
  spreads of liquid stocks.
- **Second break-even.** The break-even is also reported on top of flat costs (the extra spread and impact
  the strategy can absorb). The first run had it only on top of v1, which gives 0. That run was
  invalidated with a reason; its tables were identical.

### Tests

- The tick floor and CHL equal pandas; CHL is point in time and recovers a known simulated spread.
- The cost formula is correct, and fallbacks are counted.
- `costs=None` is unchanged, and zero inputs add nothing. The frozen strategy keeps hash `72c851c7`.
- Each trade pays the v1 formula; the tick-only spread works; the flat-as-model run equals flat.
- Matched controls keep the key mix and are deterministic per seed.
- The liquidity-weighted curve equals pandas.
- Evaluation is research only and is not logged.

### Data safety

- Backup before the evaluation: `data/results.before-econ.duckdb`.
- The warehouse hash is unchanged by the build.
