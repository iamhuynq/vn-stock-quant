# Plan: fixes from the repository review of 2026-10-10

<!-- type: bug -->
<!-- status: built 2026-10-14 (approved 2026-10-10) -->

Source: `vn-stock-quant-review-toan-bo-2026-10-10.md` (review of `main` at `6a107b2`). Every finding was
checked against the code and the real data first. No validation, holdout or forward data is used for a
decision.

## Findings checked

| # | Finding | Code | Measured on real data |
|---|---------|------|-----------------------|
| 1 | Runs are `ok` before their work is done | True: `ResultsStore.start_run` inserts `status = 'ok'` | No `ok` run lacks result rows today: the risk is preventive |
| 2 | The paper portfolio ignores the completeness gate | True: `run_daily` re-simulates the paper portfolio up to `latest_final` (the latest market date), even when that session was marked `incomplete` | Not yet hit (every forward session complete) |
| 3 | Decile-scan IC uses `rank()`, not average ranks; `ntile` ties are arbitrary | True in `engine.run_scan` | Tied values: 0.07% of order-imbalance rows and 4% of `return_20d` rows. The order-imbalance top-decile boundary is tied on 0 of 4,122 research dates, so the frozen strategy is not affected |
| 4 | Stale-value share is wrong with a write-down | True in both engines: the numerator uses the last price, the denominator the written-down value | Diagnostic only; not used by any verdict |
| 5 | Group momentum sums daily returns instead of compounding | True in `cross/groups.py` (`grp_ret_21`, `own_ret_21`) | Same industry tercile in 97.8% of research dates and the same top-tercile flag in 98.9%: small but real |

## Fixes

**1. Run lifecycle.**
- `start_run` inserts `status = 'running'`. A new `finish_run` sets `ok` after the results and the
  hypothesis rows are written, and an exception sets `failed`.
- A context manager `store.recording(run_id, ...)` wraps every run type: pattern, scan, backtest, cross
  tests, event study, interactions, economic and portfolio evaluations.
- `hypothesis_q` already counts only `ok` runs; the duplicate-run guards look for `ok`, so a failed run
  can be re-run.
- A process killed mid-run leaves `running`, which counts as not valid.
- Test: an error injected after `start_run` leaves the run `failed`, keeps its hypothesis rows out of
  the q-values, and allows a re-run.

**2. Paper portfolio and completeness.**
- The paper portfolio is re-simulated only up to the latest session that the scan marked `scanned`
  (complete), not up to the latest market date.
- Test: the latest session is incomplete; the paper record stops at the previous complete session; it
  catches up once the session is complete.

**3. Decile scan statistics.**
- IC uses average ranks (exact Spearman), as in `interactions.py`.
- Deciles get a deterministic tie-break: the feature value, then the symbol.
- Pattern definitions (`patterns.py`) and the backtest loader are **not** changed: they are versioned by
  hash and validated. The measured 0 tied boundaries shows the frozen strategy is unaffected.
- Re-run the research-period scan once. The old scan run is invalidated with the reason, and the report
  shows the largest change in IC t-statistics. Logged tests are replaced one for one, so the family size
  does not grow.
- Tests: IC equals `scipy.stats.spearmanr` on a feature with many ties; deciles are identical across
  repeated runs.

**4. Stale-value share.**
- Numerator and denominator use the same marks (after the write-down): stale-marked value divided by
  marked value. A session with no marked value is skipped.
- Tests: with a write-down, the share stays between 0 and 1, and the zero denominator is handled.

**5. Group returns.**
- Add compounded 21-session industry and own returns (`exp(sum(log1p(r))) - 1`, same minimum count) as
  definition **v2**.
- The closed hypothesis P4b-G2 (industry momentum) was pre-registered, validated and failed on the v1
  definition. It is **not** re-tested: validation data cannot be reused. Its record states the v1
  definition and the measured agreement (97.8% / 98.9%).
- Candidate P4b-G3 and any future group test use v2. Re-running the research-period group tests under
  v2 is optional (see the open questions).

## Rollback

- Back up `results.duckdb` before the scan re-run.
- Runs are invalidated, never deleted.
- The status change is additive: old runs keep `ok`.
- Code: revert the commit.

## Open questions (defaults used unless you say otherwise)

1. Re-run the research-period decile scan after fix 3: yes, once.
2. Group returns: add v2 for future use and leave the closed and research-period group results on v1
   (documented). The alternative is to re-run the research-period group tests under v2 now.
3. Branch: `review-2026-10-10-fixes`, one commit; the user pushes and opens the pull request.

## Result (2026-10-14)

Built on branch `review-2026-10-10-fixes`; open questions answered with the defaults. Full suite: 384 passed
(new: lifecycle, paper gate, Spearman with ties, stale share, v2 group returns). Every new test was
mutation-checked: each fails on the old code.

1. **Run lifecycle.**
   - Status goes `running` -> `ok` (`finish_run`, called by all 11 run functions) or `failed` (an exception
     inside the store, with the error as the reason).
   - The UI fixture, which builds a run by hand, now finishes it.
   - Test: a run that raises is `failed`, stays out of the q-values, and can be re-run.
2. **Paper portfolio.** It is re-simulated up to the latest `scanned` (complete) session, and the daily
   report says so when a later session is incomplete. Test: a partial last session; the paper portfolio
   stops one session earlier and catches up once the session is complete.
3. **Decile scan.**
   - IC uses average ranks (exact Spearman), and deciles break ties by symbol.
   - Test: a 5-level feature (unequal tie groups); the IC equals scipy per date, and deciles are identical
     across runs. The first version of this test used a binary feature, where min and average ranks give
     the same correlation; it passed with the old code and was replaced.
   - Research scan re-run as `20261014T172253-scan-features-research`; the old run was invalidated.
     Backup: `data/results.before-review-1010.duckdb`.
   - Results:
     - The 90 logged spread tests are replaced one for one (family m stays 295), and **no p-value crosses
       0.05**.
     - IC changes are concentrated in `close_vs_avg_price`, which has many zeros: its 5-session IC t goes
       from -7.4 to -4.6, and its 20-session IC t from -2.6 to 0.0.
     - Over all 630 statistics: max |delta IC| 0.013, max |delta spread| 0.0089. Five IC t-statistics
       change sign in the all-stocks segment, all of them near zero.
   - Pattern definitions and the backtest loader are unchanged; the frozen strategy's top-decile
     boundary has 0 ties.
4. **Stale-value share.** Numerator and denominator use the same written-down marks in both engines.
   Tests: the share stays within [0, 1] for write-downs of 3 and 8 sessions, and the old formula fails
   them.
5. **Group returns.**
   - v2 compounded columns `grp_ret_21_c` and `own_ret_21_c`, and `definition="v2"` for the momentum and
     reversal tests (own run names, so the v1 duplicate guard does not apply).
   - v1 is unchanged for every recorded result (P4b-G2 FAIL, G1, G3, G4).
   - The Market watch "industry strength" table now shows compounded returns.
   - The v2 columns appear in `cross.duckdb` at the next `quant cross build`.

## PR #3 review fixes (2026-10-15, approved)

Code review of PR #3: two P2 findings and one P3, all confirmed and fixed. Full suite: 386 passed. Each new
test was mutation-checked against the previous commit.

| Finding | Fix |
|---------|-----|
| P2: the v2 group return compounded daily **excess** returns (stock return minus market return). That is a daily-rebalanced long-group / short-market index, not the cumulative relative return, and `ln(1 + r)` was unguarded | v2 is now defined as the **cumulative relative return versus the market**: prod(1 + group) / prod(1 + market) - 1 = exp(sum(log_rel)) - 1. `group_returns_daily` gains `ew_raw`, `mkt_cc` (= raw - excess, by construction), `log_rel` and `rel_invalid`. Missing sessions are skipped in both products, with the same minimum count (16 of 21). A return <= -1 makes the window NULL. Columns `grp_rel_21` / `own_rel_21` replace the earlier `*_c` (never built or used). The Market watch industry table uses v2 when the cross build has it, else v1 (sums) |
| P2: the paper portfolio could cross an incomplete session between two complete ones | It now stops at the end of the **unbroken** run of complete forward sessions, before the first forward session that is not `scanned`, even if a later one is. A scanned session is re-scanned only by `quant daily --date`; the paper record is rebuilt from the forward start on every run |
| P3: `finish_run` did not check the transition | It raises unless exactly one run moves from `running` to `ok` (missing run, or a run already `ok` / `invalid` / `failed`). `quant runs` lists runs left `running` by a killed process; recovery is `quant runs --invalidate RUN --reason "process killed"`, then run again |

Tests:
- v2 equals a hand calculation; it differs from compounded excess returns; an invalid day empties the
  window; the SQL `grp_rel_21` equals a pandas product ratio; v1 is unchanged.
- complete -> incomplete -> complete: the paper portfolio stops before the incomplete session.
- `finish_run` on a missing, finished or invalidated run; stuck-run listing.

No research result is re-run: v2 was never used in a recorded result. Real data: no run is `running`.

## PR #3 updated review fixes (2026-10-15, approved)

Updated review of PR #3: two P2 findings and one P3, all confirmed and fixed. Full suite: 389 passed. Each new
test was mutation-checked against the previous commit.

| Finding | Fix |
|---------|-----|
| P2: Market watch v2 ignored `rel_invalid`, and only the 21-session window had a coverage check (on `ew_cc`) | Each 5, 21 and 63-session window applies the group-feature rules: at least 80% of its sessions with a valid `log_rel` and no invalid return, else NULL. Sorting puts NULLs last |
| P2: `paper_date` had no lower bound (the real results store has one scanned pre-forward session, from `quant daily --date`), and readers took `max(run_date)`, so an older, no longer valid re-simulation could still show as current | `scan_date >= FORWARD_START` is added. A one-row table `paper_state` records the current paper date (NULL when there is none) on every `run_daily`. The Backtest page and the Exposure panel read it (falling back to `max(run_date)` for stores from before it). Older `run_date` rows stay as history |
| P3: `invalidate()` left the run open, so a later error could overwrite `invalid` with `failed` | `invalidate()` closes the run, and `_fail_open_runs` only changes runs that are still `running` |

Found while testing: `run_paper` crashed when the paper portfolio held no open position (an empty
`executemany`). It now writes no position rows in that case; the new paper-state test covers it.

Checks on real data:
- The real stores do not have `paper_state` or `log_rel` yet: they appear at the next `quant daily` and
  `quant cross build`.
- Meanwhile the fallbacks work: Market watch, Backtest and Cross-stock render, with no database change.
