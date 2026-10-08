# Results: Group-level cross-stock analysis (Phase 4b), research period

<!-- status: research period done 2026-10-07; industry momentum FAILED pre-registered validation 2026-10-08 (docs/group-momentum-validation-2026-10-08.md) -->

Plan: `docs/group-analysis-plan.md`. Data: research period (to 2023-12-31). Reports:
`data/reports/cross/tests-research-20261007T180725.md` (logged tests) and
`data/reports/cross/describe-20261007T180754.md` (description). An independent code review found no defect
that could manufacture the results; its checks are summarised below.

## Description (not tested)

**Industries move together much more than single stocks.**
- The average correlation between ICB level-2 industry indexes (excess vs VNINDEX) is 0.20-0.58 by year.
  For pairs of single stocks it is 0.03-0.19.
- The structure is stable: correlations agree with the same month a year later at 0.61 / 0.73 / 0.82 for
  the 60 / 120 / 250-session windows. For stock pairs the figures are 0.27 / 0.38 / 0.53.

**Most connected industries.** Real estate and Construction & materials have an average correlation of
0.71 over 184 months. Construction is also connected with Industrial goods & services (0.63) and Basic
resources (0.61), and Real estate with Basic resources (0.60). Together these four form a
"construction-real estate" block. Financial services is linked to both Construction and Real estate
(about 0.51).

**Stale-price signature at the industry level.**
- The own lag-1 autocorrelation of industry indexes is +0.145 on close-to-close returns and -0.026 on
  next open-to-close returns.
- Cross-industry lag-1 correlation shows the same pattern: 0.070 close-to-close against 0.014
  open-to-close.

## Tested hypotheses (14 logged; q = BH over all 233 logged tests)

| Test | Result | Verdict |
|------|--------|---------|
| Industry lead-lag persistence, close-to-close, lag 1 | +0.054 (t 3.8, q 0.006) | Real in close prices only |
| Same, next open-to-close, lags 1/2/3/5 | +0.009 / +0.006 / +0.014 (p 0.05, q 0.10) / +0.005 | **Not tradable**: as with stock pairs, the relation lives in the opening gap (lag 3 is borderline and not significant after BH) |
| **Industry momentum, 21 sessions** (top tercile minus the average industry, members' next 20 sessions from the next open, monthly) | **+0.53% / month (t 2.7, q 0.019)**; turnover 66% of the selected industries per month; net of 0.4% x turnover: **+0.26% / month** | **Candidate** (see caveats) |
| Industry momentum, 63 sessions | +0.48% / month (t 2.0, q 0.09); net +0.33% | Not significant after BH; same direction |
| Weekly reversal (bottom tercile of the last 5 sessions minus the average, next 5 sessions) | -0.15% / week (t -3.4, q 0.002) | The opposite of reversal: **weak industries keep underperforming** for a week. Buying them loses money (net -0.42% / week); not a long candidate, but useful as an avoid signal |
| G4 laggards in strong industries | Lift +0.01% / +0.05% / +0.13% at 5/10/20d, none significant | **No** |

## Code review of the momentum result (independent recomputation)

- **No look-ahead.** The ranking window ends at the ranking date. The index on a session uses the members
  of the previous month end. The outcome enters at the next open.
- **Placebos.** Ranking one month too early gives +0.15% (t 0.8). Ranking by the future 20 sessions gives
  +5.3%. The pipeline therefore ranks on the past only.
- **Membership.** Restricting outcomes to stocks that were members both before and at the ranking date
  gives +0.58% (t 3.0).
- **Magnitude.** The recomputation gives +0.525% / month over 184 months, matching the reported value.
- **Robustness.** The effect is weak and not stable across sub-periods:

  | Period | Months | Mean / month | t |
  |---|---|---|---|
  | 2006-2010 | 29 | +0.41% | 0.7 |
  | 2011-2015 | 60 | +0.74% | 1.7 |
  | 2016-2019 | 48 | +0.64% | 2.6 |
  | 2020-2023 | 47 | +0.21% | 0.65 |

  Dropping the 5 best months gives +0.31%.
- **The loser side is stronger.** The bottom tercile minus the average is -0.63% / month. The long-only
  side, which is the only one implementable in VN, is the weaker half.
- **Cost realism.** The 0.4% round trip assumes small members (ADV from 1bn VND) trade at that cost; there
  is no market-impact model. Restricting members to ADV > 5bn gives +0.45% (t 2.1, 143 months).
- **Missing early months.** 32 early months (2006-2009) are missing because fewer than 6 industries had
  an index then.

Known limitations (low impact, documented, not changed after the run):
- The G4 laggard feature's 21-row window can span more than 21 sessions when an industry has no index
  for some days. Momentum is not affected, because it uses a full session calendar.
- `start_run` marks a run "ok" before it finishes, so a crash mid-run blocks a rerun (duplicate guard)
  until the run is invalidated by hand.

## Decision needed

**Industry momentum (21 sessions)** is the first idea since Phase 3 that survives:
- the multiple-testing correction;
- a rough cost model;
- an independent recomputation.

It is weak and fading (2020-2023). Options:

1. **Pre-register and test it once on validation (2024-2025)**, with the specification frozen exactly as
   tested here:
   - ICB level 2, equal weight, 21-session lookback, top tercile, monthly, next 20 sessions from the next
     open;
   - pass rule: net of rotation cost > 0 with p < 0.05 on validation months.

   About 24 months of validation data gives low power: a true +0.26% / month would likely not reach
   p < 0.05. A failure would therefore not prove the effect is absent.
2. **Track it forward only** (paper portfolio from 2026-10-03 like the frozen order-imbalance strategy),
   which keeps validation unused but takes years to be conclusive.
3. **Drop it.**

Recommendation: option 1 together with option 2.
- Run the validation test to see whether the sign and size hold.
- Then, whatever the result, add it to the forward paper tracking.
- Only real forward data should decide whether to act on it.
