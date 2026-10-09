# Plan: Execution and data audit (review of 2026-10-09)

<!-- type: bug -->
<!-- status: built 2026-10-09 (approved 2026-10-09): phases A, B and C done -->

Source: the external review `vn-stock-quant-review-toan-dien.md` (2026-10-09). Every finding was checked
against the code and the real data before this plan. It uses no validation, holdout or forward data.

## Findings checked

| Finding | Check | Measured |
|---------|-------|----------|
| T+2 tracked per position, not per lot | True in `portfolio/engine.py`: `last_buy[j]` is overwritten by every top-up buy, and top-ups happen at most rebalances, so a new lot can lock older shares. The event engine is not affected: a position is bought once, and renewals do not buy | Counted after the fix |
| Invalid ADV gives an infinite cap in the event engine | True in the logic. In practice entries always come from universe stocks (ADV > 1bn VND) | 0 of 5,704 strategy entries and 0 of 6,510 random entries (research period) have a non-finite ADV |
| Positions marked at prices of sessions without trades | True in both engines. On a no-trade session the close is the reference price, which differs from the last traded close (UPCOM reference = previous average price) | 51,596 no-trade rows move against the previous row; 40,753 move by more than 1% |
| Pipeline continues after validation errors | The mechanism is true, but there is no error-level check today: all 17 checks are warn or info, so `fireant validate` never fails | The gap is the absence of error-level checks for the latest session |
| Point-in-time and survivorship limits | Documented but not measured | To be measured |

## Phase A: execution correctness

**A1. T+2 per lot (portfolio engine).**
- Each stock keeps a list of lots (buy session, shares).
- A sale may only use shares whose lot is at least `sell_lag` sessions old, oldest first (FIFO).
- A partial sale of the eligible shares is allowed; the rest waits.
- `orders_blocked_t2` counts orders blocked entirely; `orders_partial_t2` counts orders reduced.
- Tests:
  - buy, top up, sale inside T+2: only the old lot is sold;
  - the rest is sold once eligible;
  - a sale never exceeds the eligible shares (an invariant checked on random markets).

**A2. Invalid ADV in the event engine.**
- An entry is blocked when the ADV of the signal close is NaN, infinite or <= 0; it is counted in
  `entries_blocked_no_adv`.
- Sells are not capped in that engine, so nothing else changes.
- Because no real entry is affected, the frozen strategy and the paper portfolio stay bit-identical. A
  test re-runs the research-period backtest and compares equity arrays exactly.

**A3. Last traded price for marking (both engines).**
- Positions are marked at the last **traded** close (`last_traded_price`). A no-trade session keeps the
  previous mark and never uses the reference price.
- Execution is unchanged: it already requires a traded session.
- New metrics:
  - the share of portfolio value marked with a stale price (more than 5 sessions since the last trade);
  - the longest stale period.
- Default for new runs: traded-price marking.
- Exception: the paper portfolio's pre-registered measurement (open question 1).

**A4. Invariant tests (both engines), on many random markets:**
- cash never negative;
- shares never negative;
- no sale beyond the eligible shares;
- every order within its cap;
- equity = cash + marked positions;
- costs equal the sum of trade costs.

**A5. Error-level validation for the latest session.** New `error` checks:
- duplicate primary keys in `quotes_daily`;
- the latest session has fewer than 80% of the traded stocks of the previous session (an incomplete
  download);
- non-positive prices on traded rows of the last 5 sessions;
- a new source-wide corrupt date in the last 5 sessions.

`scripts/daily.sh` stops before `quant build` when `fireant validate` exits 1. Known accepted findings
(for example 2025-07-16) go in a reviewed allowlist (`fireant_crawler/validate/accepted.py`), each with a
reason. Warn and info do not block, as today.

**Re-runs after A1 to A3.**
- The portfolio grid C1 to C6 (logged) and the economic evaluation (descriptive) are re-run. The current
  runs are invalidated with the reason.
- `results.duckdb` is backed up first.
- The verdicts are reported as they come out; no rule changes.

## Phase B: point-in-time audit (descriptive report, `quant audit pit`)

- **Coverage by year:** symbols by exchange and listing status, delisted symbols present, symbols with gaps.
- **Current-only attributes:** industry and exchange. Count the stocks whose band-based limit flags would
  differ under another exchange's band; share of backtest trades in such stocks.
- **Adjustment checks:** corporate-action coverage (cash, stock, rights) against `adj_ratio` change
  points, from the existing validation checks.
- **Availability timing:** report marks used only after their publication date (already true; a test is
  added).
- **Trades exposed to unknown rules:** share of strategy trades in stocks or dates with an unknown or
  approximate rule.

The report quantifies the limits; rebuilding the warehouse is a separate decision.

## Phase C: operations and documentation

- `docs/STATUS.md`: PR #1 merged and CI green; the review backlog recorded.
- **CI fixture:** extend the synthetic warehouse with a rights issue, missing days and an ADV gap, and add
  one end-to-end CLI test: `fireant validate` -> `quant build` -> `quant daily` on the synthetic data (no
  token, no network).
- **Industry cap policy:** declared as a rebalance-time cap. Actual weights and breaches are reported, as
  today. A drift-triggered rebalance is not added.
- **Cost report:** add the median and 95th percentile of order value / ADV.

## Not in scope

- ML.
- Installing a scheduler: the user decided on manual runs.
- Changing the frozen strategy, a pre-registration or any recorded decision.

## Tests

The tests listed under A1 to A5 and C. Afterwards, the full suite runs locally, and in the Linux CI after
the user pushes.

## Rollback

- Code: revert the commits.
- `results.duckdb`: back up before the re-runs; runs are invalidated, never deleted.
- `research.duckdb`: rebuild.
- Validation: the new error checks can be disabled by reverting `checks.py`.

## Open questions (defaults used unless you say otherwise)

1. **Paper portfolio marking.** Keep the current marking (the pre-registered forward measurement) and add a
   second line in the daily report with traded-price marking. The alternative is to switch the paper
   portfolio to traded-price marking, which changes its past numbers.
2. **Validation error thresholds.** The latest session must have at least 80% of the previous session's
   traded stocks, with a 5-session window for the other checks.
3. **Order of work.** Phase A, then B, then C, each with its own Result section and commit, on a new branch
   (`execution-audit`); the user pushes and opens the PR.

## Result, phase A (2026-10-09)

Built on branch `execution-audit`; open questions answered with the defaults. Full suite: 362 passed
(41 new).

### A1 to A3: engines

- **Portfolio engine.**
  - T+2 is applied per lot: FIFO over eligible lots, partial sales, and the counters
    `orders_blocked_t2` and `orders_partial_t2`.
  - Positions are marked at the last traded close.
  - `stale_value_share_mean` and `stale_value_share_max` report the share of invested value whose mark
    is more than 5 sessions old.
- **Event engine.**
  - An entry without a valid ADV is blocked and counted in `entries_blocked_no_adv`.
  - `mark="traded"` is the default; `mark="legacy"` keeps the reference-price marks and is used only by
    the pre-registered paper portfolio.
  - `paper_daily.equity_traded_mark` stores the traded-mark equity, and the daily report prints it as an
    information line.
- **Identity check.** On the same research data, the new event engine with `mark="legacy"` gives
  bit-identical equity to the engine on `main`. This holds for the strategy with flat and v1 costs and for
  a random control.
  - The paper portfolio of 2026-10-07 is bit-identical to its stored record.
  - The stored 2026-10-04 research backtest differs only because the data was rebuilt since: the source
    re-adjusts history after new dividends. Its CAGR is 14.25% instead of the recorded 14.3%.

### A4: invariant tests

`tests/backtest/test_invariants.py` checks both engines on 12 random markets, each with no-trade
sessions, price limits, missing ADV and data-error jumps:
- no negative cash or shares;
- orders within the ADV cap;
- no sale beyond the eligible lots;
- costs that add up;
- marks taken from traded sessions only.

The edge cases are actually hit: 28 partial T+2 sales, 193 orders blocked for a missing ADV and 41
data-error exits.

### A5: validation errors

- Three `error` checks on the last 5 sessions: `latest_session_incomplete` (< 80% of the previous
  session's traded stocks), `recent_nonpositive_prices` and `recent_corrupt_source_dates`.
  - A duplicate-key check was not added: `quotes_daily` already has a primary key.
  - Thresholds were checked on history: since 2015 only one session (2018-01-23) fell below 80%.
- `validate/accepted.py` lists reviewed exceptions, each with a reason (2025-07-16).
- `daily.sh` exits 8 before `quant build` on error-level findings, and the UI shows the meaning of exit 8.
- On the real warehouse, all three checks are 0, so they do not block today's pipeline.

### Re-runs

Backup `data/results.before-execution-audit.duckdb`. The economic evaluation and the portfolio grid were
re-run; the earlier runs are invalidated with the reason.

- **Economic evaluation** `20261009T153612-econ-frozen-research`.
  - At 1 bn VND the results are unchanged to 0.1 point: flat +14.3%, v1 -10.9%.
  - Break-even over flat costs is 0.392% per side (it was 0.415%).
  - Entries blocked for a missing ADV: 0.
  - Stale-marked invested value at 1 bn VND with v1: mean 13.7%, max 48.6%.
- **Portfolio grid** `20261009T153933-portfolio-C*-research`. No verdict changes.

| Config | CAGR v1 (before -> after) | T+2 blocked / partial | Stale-marked invested value, mean / max | CAGR with sell lag 2 |
|--------|---------------------------|------------------------|------------------------------------------|----------------------|
| C1 | -23.0% -> -23.1% | 65 / 50 | 30.7% / 85% | -23.0% |
| C2 | -17.3% -> -17.8% | 43 / 81 | 23.4% / 72% | -17.3% |
| C3 | -6.0% -> -6.3% | 0 / 22 | 8.6% / 47% | -6.3% |
| C4 | -12.7% -> -12.7% | 0 / 37 | 5.6% / 38% | -12.7% |
| C5 | -12.8% -> -12.7% | 0 / 55 | 5.6% / 37% | -12.7% |
| C6 | -3.6% -> -3.5% | 0 / 27 | 10.4% / 100% | -3.5% |

### New finding: stuck positions

The stale-marked value comes almost entirely from positions in stocks that **stop trading**.
- These positions cannot be sold, so they stay at their last traded price. Examples: KLS, last trade
  2016-07-20; PCB, 2013-09-23; HBB, 2012-08-16.
- C1 with flat costs ends with 14 such positions, and about 10% of invested value is stale-marked on
  average.
- Under v1 costs the portfolio shrinks to about 1% of its capital, so the stuck positions become a large
  share of what is left (31% mean).
- Valuing them at the last price **flatters** every configuration.

Two questions belong to phase B (delisting coverage) and need a decision there:
- whether such stocks really stopped trading (delisted), or moved to a venue the warehouse lacks;
- which valuation policy to apply (for example a write-down after N sessions without trades).

## Result, phase B (2026-10-09)

- `quant audit pit` (`src/quant_research/audit.py`) is descriptive and read-only; it logs nothing. Report:
  `data/reports/research/audit-pit-<build>.md`.
- Both engines gained a `writedown_after` option (default None, so nothing changes): a position is valued
  at 0 while it has not traded for more than N sessions. It is still sold if the stock trades again.
- Tests: the audit is read-only and complete; feature SQL reads no report, fundamental or target table;
  write-down in both engines. Full suite: 365 passed.

### Findings (real data, build `20261009T112210`)

1. **Survivorship.** Delisted stocks are present: 459 symbols are OTC / not listing today, and up to 221
   of them traded in a single year. The panel is not survivors-only. Whether the source covers *every*
   delisted company cannot be checked without an outside list.
2. **Stocks that stopped trading** (no trade in the last 30 days):
   - 360 delisted, of which 163 were liquid at some time;
   - 173 still listed but silent, of which 51 were liquid at some time (for example SVH since 2019, ROS
     since 2022).

   These are the stuck positions of phase A: suspensions and delistings are real market events, not data
   gaps.
3. **Attributes known only at today's value.**
   - Limit flags: 2.2% (HOSE) to 8.4% (HNX) of liquid traded rows move 7% to 15% from the reference price.
     There, the band (that is, the unknown historical exchange) decides the flag. This is an upper bound
     on the rows whose limit flag could be wrong.
   - Industry: today's ICB code for every year.
4. **Adjustments.** 18,489 cash dividends (3 without an amount), 4,057 stock dividends and 2,411 rights
   issues; every title was parsed. The validation report also lists 9 `adj_ratio` change points without a
   matching event.
5. **Availability.** Feature SQL reads no report, fundamental or target table (now a test).
6. **Valuation of stuck positions** (CAGR, research period, 1 bn VND):

| Strategy | Costs | Last price (default) | 0 after 60 sessions | 0 after 20 sessions |
|----------|-------|----------------------|---------------------|---------------------|
| Frozen 72c851c7 | flat | +14.3% | +13.8% | +13.8% |
| Frozen 72c851c7 | v1 | -10.9% | -12.7% | -12.7% |
| C1 | v1 | -23.1% | -30.5% | -30.5% |
| C2 | v1 | -17.8% | -22.4% | -22.4% |
| C3 | v1 | -6.3% | -6.7% | -6.9% |
| C4 | v1 | -12.7% | -13.7% | -13.6% |
| C5 | v1 | -12.7% | -13.6% | -13.3% |
| C6 | v1 | -3.5% | -3.4% | -3.6% |

Reading:
- Keeping stuck positions at their last price flatters the results: by 0.5 point a year for the frozen
  strategy with flat costs, up to 7 points for C1.
- 20 and 60 sessions give almost the same numbers, because the stuck positions almost never trade again.
- No verdict changes; every number gets worse.

### Decision needed: valuation policy for future evaluations

Recommended:
- Keep the last traded price as the reported default.
- Report the 60-session write-down next to it in `quant econ evaluate` and `quant portfolio evaluate`.
- Apply the reading rule of any future pre-registration to the **worse** of the two numbers.

## Result, phase C and valuation policy (2026-10-09)

**Valuation policy (approved).**
- The last traded price stays the reported default.
- `quant econ evaluate` and `quant portfolio evaluate` also report the CAGR with stuck positions written
  down to 0 after 60 sessions without a trade (`WRITEDOWN_SESSIONS`).
- **A future pre-registered rule is judged on the worse of the two valuations.**
- The current econ and portfolio runs predate these columns. Their write-down numbers are in the phase B
  audit report, so they were not re-run (nothing else changed).

**Order size.** Both evaluations report order value / ADV20 at the decision close (median and 95th
percentile). Computed for the current strategies (research period, v1):

| Strategy | Median | 95th percentile |
|----------|--------|-----------------|
| Frozen 72c851c7, 1 bn VND | 0.47% | 3.1% |
| Frozen 72c851c7, 10 and 100 bn VND | 5.0% | 5.0% (every order at the 5% cap: no capacity left) |
| Portfolio C1 to C6, 1 bn VND | 0.03% to 0.36% | 1.4% to 4.9% |

**CI integration test.** `tests/test_end_to_end.py`:
- Fixture: the synthetic warehouse plus a rights issue, three sessions missing for one stock, and a
  26-session gap that leaves a missing ADV. The synthetic base already has a delisted stock, no-trade
  sessions, a cash dividend, limit sessions and a data-error jump.
- It runs the real commands as subprocesses, with no token and no network: `fireant validate`,
  `quant build`, `quant daily`, `quant audit pit`, `quant registry list`.
- It then breaks the latest session: validation must exit 1.
- Run time: about 5 s.

**Industry cap policy.** Declared as a rebalance-time cap: targets respect it, and actual weights can
drift above it between rebalances. Actual weights and breaches are reported (phase A). No drift-triggered
rebalance.

**Docs.** STATUS (PR #1 merged, audit state), README (`quant audit pit`), and the project instructions
(valuation rule).

Full suite: 367 passed. `scripts/daily.sh` was also checked with GNU-like `date`/`stat` shims.

## PR #2 review fixes (2026-10-09, approved)

Code review of PR #2: two P2 findings and one P3, all confirmed in the code and fixed.

| Finding | Fix |
|---------|-----|
| P2: validation misses NULLs (`price <= 0` and `abs(...) > 0.5` are NULL, not TRUE; a NULL `total_volume` even hides a row from every traded-row check) | New error check `recent_missing_required_fields`, last 5 sessions. `price_close`, `price_basic` and `total_volume` must be present on every row; OHLC, `deal_volume` and `putthrough_volume` on traded rows. Missing data and values that disagree are reported by separate checks. The real warehouse has no such NULLs, so nothing is blocked today |
| P2: the write-down policy did not enter pass/fail | `verdict()` judges CAGR and break-even on the **worse** of the default marks and the 60-session write-down; the evaluation now also computes the write-down break-even. A missing write-down number fails. The matched-random criterion stays on the default marks, the valuation its control runs use |
| P3: `mark="legacy"` set `last_trade` on no-trade sessions | `last_trade` is the last session that really traded, in every mode; `legacy` changes only the mark. The paper portfolio stays bit-identical (checked on the 2026-10-07 record) |

Tests:
- each NULL case is an error, and no-trade rows only need close, reference price and volume;
- the reading rule fails when only the default valuation passes, and when the write-down number is
  missing.

Full suite: 377 passed.

Grid re-run: `20261009T171446-portfolio-C*-research`; the earlier runs were invalidated because they
predate the write-down numbers. Backup: `data/results.before-pr2-fixes.duckdb`.
- No verdict changes: all six fail "beats equal weight" and the break-even, on the worse valuation.
- The default numbers are unchanged; the write-down CAGRs match the phase B audit (C1 -30.5% to C6 -3.4%).

**Scope of the audit.** The point-in-time audit measures the data limits and makes them public. It does
not remove survivorship bias, and it does not make attributes known only today (exchange, industry)
point in time. It is not evidence that the data is fully point in time.
