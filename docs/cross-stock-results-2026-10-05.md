# Results: Cross-stock Analysis (Phase 4), research period

<!-- status: research period done 2026-10-05; validation not run (no candidate worth pre-registering) -->

Plan: `docs/cross-stock-plan.md`. Data: research period only (snapshots and test outcomes up to
2023-12-31). Reports: `data/reports/cross/describe-20261005T193438.md` and
`data/reports/cross/tests-research-20261005T192527.md` (H1, H3) +
`data/reports/cross/tests-research-20261005T193435.md` (lead-lag, H2, cointegration after the review fixes).

## Answers to the MVP questions (doc 30)

**Which stocks are related?** Two kinds of relation show up:
- Excess-return correlations are low on average: 0.03-0.19 by year (120-session window).
- The strongest and most durable relations are within a few groups:
  - Brokers: SSI-HCM has a mean correlation of 0.63 over 166 monthly snapshots; BVS, KLS, VND, MBS, CTS
    and FTS are also in this group.
  - Song Da construction: SD6, SD7 and SD9.
  - Oil and gas: BSR-OIL and PVC-PVE.
- Clusters built from correlations agree only loosely with ICB level-2 industries: the adjusted Rand
  index is 0.02-0.25, against about 0 for shuffled labels. Industry labels explain part of the
  co-movement, but not most of it.
- The UI page "Cross-stock" shows the peers of any symbol, the rolling correlation of any pair, the
  clusters and the central stocks.

**Is the relation stable?** Partly:
- The correlation matrix 12 months later still correlates with today's matrix at 0.28 (60-session
  window), 0.39 (120) and 0.53 (250).
- Individual pairs drift a lot. Even SSI-HCM has dropped as low as 0.29.

## Tested hypotheses (logged; q = BH over the whole hypothesis log)

| Test | Result | Verdict |
|------|--------|---------|
| Lead-lag persistence, follower close-to-close, lag 1 | Top-decile pairs of year Y keep +0.022 more lag correlation in Y+1 (t = 6.0, q = 0.0001) | Real, but see the next row |
| Same, follower **next open-to-close** (what a buyer at the open sees), lags 1/2/3/5 | -0.0001 / -0.001 / -0.0004 / -0.001, none significant | **Not tradable**: the "follow" happens in the opening gap (stale closes / nonsynchronous trading), exactly the trap the plan anticipated |
| H1 industry leaders -> followers, decile spread of 5-session execution excess return | +0.12% (t = 2.3, q = 0.049); 10d +0.11% and 20d +0.09% not significant; stronger in Bull regimes | Statistically marginal and far below the 0.4% round-trip cost: **no** |
| H2 large caps -> small caps, slope on the large-cap excess return with the market return as control | 5d 0.19 (q = 0.058), 10d 0.21 (q = 0.24), 20d 0.22 (q = 0.57) | **No** once the market factor is controlled (the first, confounded version looked significant; see below) |
| H3 leaders jump +5% excess, follower flat | 192 dates; lift +0.16% / -0.11% / -0.33% at 5/10/20d, none significant | **No** |
| Cointegration long leg (cheap leg after the spread crosses 2 sigma) | Lift 0.00% / -0.11% / -0.13%, none significant; the spread keeps **widening** after events (mean abs(z): 2.28 at entry, 2.44 after 10 sessions, 2.65 after 20) | **No**: same-industry spreads do not mean-revert within a quarter |

Descriptive (not logged): about 9% of same-industry pairs pass the Engle-Granger test at p < 0.05. That
is only modestly above the 5% expected by chance, and the spreads do not revert out of sample. The lag-1
pairs that a naive search would pick (for example SCR -> HQC, HSG -> HBC) have tiny Granger p-values on
close-to-close returns. These are the same stale-price relations that show nothing on open-to-close
returns.

## Corrections made after code review (runs invalidated, never deleted)

| Run (invalidated) | Problem | Fix |
|-------------------|---------|-----|
| `20261005T192527-cross-h2_large_to_small-research` | Regressor was the raw large-cap return: market autocorrelation times small-cap beta looked like a lead-lag (t = 3.25, q = 0.004) | v2: large-cap **excess** return, market return as a control, HAC OLS (matches statsmodels) |
| `20261005T192527-cross-leadlag_persistence-research` | Top decile ranked after dropping pairs that were not measurable in Y+1 (uses Y+1 information) | v2: rank all formation pairs; the result is unchanged to 3 decimals |
| `20261005T192527-pattern-cross_coint_long_leg-research` | Pair orientation followed each quarter's liquidity rank; Engle-Granger is not symmetric | Fixed orientation (by symbol id); still no effect |

Other fixes from the same review:
- Pair orientation is now canonical (a < b) in the correlation snapshots, so stable-pair counts are
  complete.
- Descriptive spread outcomes are cut 40 days before the research end.
- Granger uses a full-session panel, so a lag never spans a gap.
- The Cross-stock UI page stops at 2023-12-31 by default. Its toggle for later data warns that
  hypotheses picked from it cannot be tested honestly on the same period.

## Decision and next steps

- **No cross-stock candidate is worth a pre-registered validation run.** Every effect is either not
  tradable (lead-lag lives in the opening gap) or far below costs (H1). Spending the 2024-2025 validation
  period on them would only use up clean data. Validation stays unused for cross-stock hypotheses.
- Phase 4 is still useful as a **descriptive tool**:
  - peers and clusters (risk concentration: holding SSI, HCM and VND is close to one position);
  - group co-movement for the daily report.
- The forward data (from 2026-10-03) remains the clean test set for any new idea.
