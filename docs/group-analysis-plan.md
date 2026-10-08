# Plan: Group-level cross-stock analysis (Phase 4b)

<!-- type: feature -->
<!-- status: built 2026-10-07; results in docs/group-analysis-results-2026-10-07.md -->

Source: `quant_research_chung_khoan_viet_nam.md` sections 6 (correlation), 7 (lead-lag), 8 (groups that
follow others), 11 (stock network: clusters, sector relationships, leaders and laggards) and 23 ("which
groups of stocks move together, and which have lead-lag relations?"). Extends Phase 4
(`docs/cross-stock-plan.md`, `docs/cross-stock-results-2026-10-05.md`), which works on pairs of stocks.

## Goals

1. **Industry indexes**: a daily return series for each industry, so groups can be compared like stocks.
2. **Group co-movement**: correlation between industries, how stable it is, and a heatmap in the UI.
3. **Group lead-lag**: does industry A today move with industry B over the next sessions, and does a
   relation found in year Y still hold in year Y + 1?
4. **Industry momentum and rotation**: do the strongest industries of the last 1-3 months keep
   outperforming, and do last week's weakest bounce back? Measured on tradable returns, against costs.
5. **Laggards in strong industries** (doc 8): do members that lag their strong industry catch up?

Non-goals: new single-stock features, ML, changes to the daily scanner (a confirmed group signal would be
added later, after validation).

## Key decisions (defaults; change any you disagree with)

| Topic | Default | Why |
|-------|---------|-----|
| Groups tested | **ICB level 2** (20 industries) | Few groups mean few tests (380 directed pairs instead of about 40,000 stock pairs) and enough members per group |
| Groups described only | ICB level 3 (38) and the correlation clusters of Phase 4 | Level 3 groups are often too small. Cluster labels change every year, so a "cluster index" has no stable identity to test across years |
| Members | Stocks passing the research universe filter (traded, ADV > 1bn VND, ...) at each month end, valid for the next month; a group needs >= 5 members that day | Point in time; tiny groups are too noisy |
| Index return | **Equal weight** (primary) and ADV-weighted (descriptive), close-to-close excess vs VNINDEX, plus next-session **open-to-close** | Equal weight is not dominated by one or two giants; open-to-close guards against stale prices |
| Lead-lag test | Same walk-forward family test as Phase 4: rank directed industry pairs by lag correlation in year Y, measure the top decile in Y + 1 against all pairs; lags 1, 2, 3, 5; cc and oc | Already validated machinery; answers "is it stable?" |
| Momentum | At each month end, rank industries by past excess return over 1 and 3 months. Outcome: next ~20 sessions' execution excess return (enter at the next open) of the members, equal weight. **Primary (logged): top tercile minus the average industry**, which is tradable long-only. Top minus bottom is descriptive. Monthly, non-overlapping | No short selling; costs 0.4% round trip per monthly rotation are subtracted in the report |
| Short-term reversal | Weekly: bottom tercile of last 5 sessions minus the average, next 5 sessions | Common pattern in emerging markets; one test |
| Laggards (doc 8) | Pattern: member of a top-tercile 1-month industry whose own 1-month excess return is in the bottom half of its industry -> lift vs universe (5/10/20 sessions) | Reuses the pattern engine and its lift test |
| Logged tests | Lead-lag 8, momentum 2, reversal 1, laggards 3 = **14** | Small family; nothing tested pair by pair |
| Periods | Discovery on research (<= 2023). Validation 2024-2025 only via a new pre-registration, and only for a candidate that beats costs | Same discipline as Phases 3-4 |
| Storage | New tables in the rebuildable `cross.duckdb`: `group_members_monthly`, `group_returns_daily`, `group_corr_snapshots`, `group_leadlag_pairs`; tests in `results.duckdb` | No new database |

## Traps and guards

| Trap | Guard |
|------|-------|
| **Stale prices inside an index**: an average of illiquid stocks is autocorrelated and "follows" liquid industries by construction (well known for portfolios) | Liquid members only; every lead-lag result shown side by side on close-to-close and next open-to-close; momentum and laggards measured on execution returns |
| **Market factor** | Excess returns vs VNINDEX everywhere |
| **Look-ahead in membership or ranking** | Members fixed at the previous month end; momentum ranks use returns up to the ranking date only; the perturbation test from Phase 4 extended to the new tables |
| **One giant dominates an index** (e.g. a bank or VIC group) | Equal weight is primary; ADV weight is reported for comparison |
| **Snooping 2024 onward in the UI** | Industry views stop at 2023-12-31 by default, like the Cross-stock page |

## UI (Cross-stock page, new "Industries" tab)

- Cumulative excess return of selected industries (equal weight).
- Correlation heatmap between industries at a snapshot, with a 60/120/250-session window choice.
- Rolling correlation of two industries.
- Momentum ranking at the snapshot date (1 and 3 months).
- Same `as_of` cap (2023-12-31 by default, toggle with a warning).

## Tests

- Planted data:
  - industry B follows industry A by one session, with its effect visible on open-to-close: found, and
    it persists;
  - an industry made of stale-close stocks: the effect appears on close-to-close only;
  - an industry with a persistent drift: ranked top by momentum, positive spread.
- Index returns equal a direct pandas computation on small inputs; groups with fewer than 5 members
  produce no index row.
- Look-ahead perturbation: changing data after month M leaves members, index returns, snapshots and
  momentum ranks up to M unchanged, and changes later outputs (non-vacuity).
- Full suite stays green; the UI tab renders read-only.

## Pre-mortem

- **Most likely failure**: "industry A leads B" that is only stale prices in B's small members. First
  symptom: a close-to-close effect with no open-to-close counterpart; both are always reported.
- **Second**: momentum that exists before costs only. The report subtracts 0.4% per monthly rotation
  and shows turnover.
- **Third**: a few industries with few members dominate the results. Results are also shown per
  industry size, and groups need at least 5 members.

## Rollback

Additive. `quant cross build` recreates `cross.duckdb` without the new tables if the code is reverted.
Runs are invalidated with a reason, never deleted.

## Open questions (defaults used unless you say otherwise)

1. Test level: **ICB level 2** (20 groups). Level 3 is described only.
2. Momentum lookbacks: **1 and 3 months**, monthly rebalancing.
