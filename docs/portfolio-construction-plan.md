# Plan: Portfolio Construction

<!-- type: feature -->
<!-- status: built and run 2026-10-09 (approved 2026-10-09) -->

Source: `project-review-vn-stock-quant-1.md`, sections 35 (Portfolio Construction) and 39 (roadmap,
priority 6).

Motivation: `docs/economic-results-2026-10-09.md`. The only strategy built so far had real selection skill,
but lost it to costs:
- it turns its capital over 23 to 35 times a year;
- it trades small stocks;
- its signal and its implementation are fused in one engine (enter on the signal, hold 10 sessions).

## Design

### 1. Separate the signal from the portfolio (`quant_research/portfolio/`)

```
Signal score (date x symbol)  ->  Eligibility  ->  Ranking  ->  Target weights  ->  Constraints  ->  Trades
```

- **Signal:** any score known at the close of date t. It comes from a Factor Engine factor (`rank_pct`),
  a feature, or a pattern flag. Higher means more wanted.
- **Eligibility (point in time):**
  - the backtest universe (`UniverseRule`);
  - a minimum ADV20;
  - no buy at an open at the ceiling, and no sell at a close at the floor (both already modelled).
- **Ranking and selection with a buffer (hysteresis):**
  - buy names ranked in the top `entry_rank` (for example the top 20);
  - keep a held name while it stays inside `exit_rank` (for example the top 40).

  The buffer is the main turnover control: names near the cut-off do not churn.
- **Target weights:** `equal` (default) or `inverse_vol` (1 / sigma_20, normalized).
- **Constraints**, applied in this order with weights re-normalized:
  - `max_position_weight` (default 10%);
  - `max_industry_weight` (default 30%, ICB level 2);
  - an order cap of `max_participation` x ADV20 (default 5%, as today);
  - cash when not enough names qualify. The portfolio is never forced fully invested.
- **Rebalance schedule:** `weekly` (first session of the week) or `monthly` (first session of the month).
  Between rebalances, positions drift with prices and nothing is traded.
- **Optional market filter:** hold cash when a `market_regimes` dimension is in a given state. This is the
  economic form of an interaction candidate; for example, momentum invested only when direction is not Bear.

### 2. Target-weight engine (`portfolio/engine.py`)

The current event engine stays unchanged: it serves the paper portfolio and the frozen strategy. The new
engine:
- at each rebalance close t, computes target weights;
- trades at the open of t + 1 toward the targets;
- respects T+2 (no sell of shares bought less than 2 sessions ago), ceiling and floor locks, and the order
  cap;
- charges cost model v1 per trade (flat as an option);
- reports equity, turnover, costs paid, the number of names, cash share and the industry weights over time.

### 3. Evaluation

`quant portfolio evaluate --config <name>` runs on the research period only. It reuses the economic
evaluation:
- capitals 1 / 10 / 100 bn VND;
- costs flat, v1 k = 1, and v1 tick-only;
- the gross benchmarks;
- a **matched random control**: the same construction (buffer, constraints, schedule) applied to a random
  score, with 20 seeds.

Each configuration logs **one test** in `hypothesis_log`: the excess daily log return vs the equal-weight
universe at 1 bn VND with v1 k = 1, Newey-West, as in the existing backtests. The construction grid is
therefore counted in the BH family.

### 4. Pre-declared research grid (run once, all cells reported)

| Config | Signal | Rebalance | Buffer (entry / exit rank) | Market filter |
|--------|--------|-----------|-----------------------------|---------------|
| C1 | `order_flow` (factor, 5-session order imbalance) | weekly | 20 / 20 (no buffer) | none |
| C2 | `order_flow` | weekly | 20 / 40 | none |
| C3 | `order_flow` | monthly | 20 / 40 | none |
| C4 | `momentum_12_1` | monthly | 20 / 20 | none |
| C5 | `momentum_12_1` | monthly | 20 / 40 | none |
| C6 | `momentum_12_1` | monthly | 20 / 40 | cash when direction = Bear |

- All configurations use 20 names, equal weights, max position 10%, max industry 30% and 5% ADV
  participation.
- The grid has six configurations and logs six tests.
- C1 to C3 ask whether a slower implementation rescues the order-flow edge. C4 to C6 test a persistent
  factor. C6 is the economic test of registry candidate `P7-IX-momentum_12_1-direction`.

**Reading rule, declared before the run.** A configuration is worth a forward pre-registration only if,
at 1 bn VND with v1 k = 1:
- its CAGR beats the equal-weight universe;
- it beats at least 19 of 20 matched random runs;
- its break-even extra cost per side is at least 0.2%.

Anything else is reported as not worth it. The registry records the result: C6 moves `P7-IX-momentum_12_1-direction` to
`preregistered` later, or to `rejected` now.

## Not in scope

- Optimizers (mean-variance, risk parity with covariance targets) and beta or volatility targeting. They
  are possible later, once a signal survives costs.
- Short selling and leverage (not available to retail in this market).
- Changing the paper portfolio or the frozen strategy.
- Any run on validation, holdout or forward data.

## Tests

- **Hysteresis.** A held name inside `exit_rank` is kept; a new name needs `entry_rank`.
- **Constraints.**
  - No weight exceeds `max_position_weight`.
  - Industry weights stay at or below `max_industry_weight` after re-normalization; the excess goes to
    other names or to cash.
  - Orders respect the ADV cap.
- **Schedule.** Trades happen only on the session after a rebalance close; prices drift in between.
- **Market rules.** T+2, ceiling and floor locks are respected (hand-built markets with exact expected
  trades).
- **Accounting.** Costs equal cost model v1 per trade, and equity reconciles to initial capital plus trade
  P&L minus costs.
- **Point in time.** Perturbing data after t does not change the targets at t.
- **Random control.** It uses the same construction, and is deterministic per seed.
- **Evaluate.** It refuses periods other than research, and logs exactly one test per configuration.
- The full suite stays green.

## Rollback

- Additive: a new package, CLI and tables. The existing engine, the paper portfolio and the frozen
  strategy are untouched. To roll back, revert the code.
- Back up `results.duckdb` before the grid run. Runs are never deleted; they are invalidated with a reason
  if wrong.

## Open questions (defaults used unless you say otherwise)

1. The six-configuration grid above, 20 names, and buffer 20 / 40.
2. Log one test per configuration (6 tests) so the construction search counts in BH. The alternative is
   descriptive only, with nothing logged.
3. Reading rule: beat equal weight, beat at least 19 of 20 matched random runs, and a break-even of at
   least 0.2% per side, all at 1 bn VND with v1 k = 1.

## Result (2026-10-09)

Built as planned; open questions answered with the defaults. Full suite: 300 passed (9 new in
`tests/backtest/test_portfolio.py`). Results and reading: `docs/portfolio-results-2026-10-09.md`.

### What was built

- `src/quant_research/portfolio/`:
  - `construction.py`: ranks, buffer selection, slot weights, position and industry caps; the excess of a
    cap goes to cash.
  - `engine.py`: the target-weight engine. It enforces T+2 (a sale from the open of b + 3), ceiling and
    floor locks, the ADV order cap, cost model v1 and data-error exits.
  - `evaluate.py`: the grid C1 to C6 and the matched random construction. One test per configuration is
    logged.
  - `report.py`: the reading rule.
- `quant portfolio evaluate --config all|C1..C6`: research period only, with a duplicate-run guard.

### Tests

- Buffer and selection; caps and cash.
- Weekly and monthly schedules.
- Exact trades and costs at the open after a decision close.
- T+2 (mutation-checked: the test fails without the rule).
- Floor and ceiling locks; ADV cap with v1 costs.
- Accounting reconciliation and point in time.
- Grid rules: periods refused, one logged test per configuration, the duplicate guard, the cash filter.
- The reading rule.

### Run

- Run `20261009T103304-portfolio-C*-research`. Backup before the run:
  `data/results.before-portfolio.duckdb`.
- **No configuration passes.** `P7-IX-momentum_12_1-direction` moved to `rejected`.
- Control fix (same day, approved). The random-score control redrew scores at every rebalance, so it
  traded far more than the strategy.
  - It is replaced by a persistence-matched control: AR(1) random scores with the signal's rank
    persistence. Its turnover now matches the strategy's within about 25%.
  - The first six runs were invalidated with that reason. The grid was re-run as
    `20261009T104238-portfolio-C*-research` (backup `data/results.before-portfolio-v2.duckdb`).
  - Strategy numbers and p-values are identical, and no verdict changes.
  - With the matched control, order flow beats random at the same turnover (C1 to C3: 100%), and top-20
    momentum is worse than random (C4 10%, C5 0%).
  - Four new tests: the target persistence is reproduced, determinism, and control turnover matching a
    persistent signal (unlike the old control).
