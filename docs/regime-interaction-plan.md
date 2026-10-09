# Plan: Regime Engine + Interaction Engine

<!-- type: feature -->
<!-- status: built and run 2026-10-08 (approved 2026-10-08) -->

Source: `project-review-vn-stock-quant-1.md`, sections 25 (Regime Engine), 26 (Interaction Engine) and 39
(roadmap, priorities 3 and 4).

Constraint: validation (2024-2025) and holdout (2026-01..10-02) are already used. Exploration is therefore
limited to the research period (<= 2023). Any candidate can only be confirmed later on forward data
(>= 2026-10-03), under a new pre-registration.

## Part 1: Regime Engine (infrastructure, no outcomes)

### Table `market_regimes` (`research.duckdb`, built by `quant build`)

One row per market session. Every label uses data up to that session only.

| Dimension | Underlying value | States |
|-----------|------------------|--------|
| `direction` | existing `market_regime` (VNINDEX vs MA50 / MA200) | Bull / Sideway / Bear |
| `volatility` | VNINDEX 20-session volatility | low / normal / high |
| `liquidity` | market turnover: total `deal_value` of all stocks, 20-session mean | low / normal / high |
| `breadth` | share of liquid stocks (ADV20 > 1bn VND) closing above their own 50-session mean | weak / neutral / strong |
| `foreign` | market foreign net value over 20 sessions / turnover over 20 sessions | selling / neutral / buying |
| `risk` | composite (rule below) | risk_off / neutral / risk_on |

How states are set:
- **Tercile states.** For `volatility`, `liquidity`, `breadth` and `foreign`, the state is the tercile of
  today's value within the **trailing 500 sessions**, today included. The label is NULL until 250 values
  exist.
  - No fixed threshold is tuned.
  - The labels adapt to the market's own history; for example, today's liquidity is not compared with 2007.
- **Risk composite**, declared here before any outcome is looked at:
  - `risk_off`: (volatility high **and** breadth weak) **or** VNINDEX is at least 20% below its 250-session
    high.
  - `risk_on`: volatility is not high, breadth is strong and direction is Bull.
  - `neutral`: otherwise.

The underlying values are stored next to the labels: percentile, raw value and drawdown.

### UI

- Market watch header: one line with today's state in each of the six dimensions.
- A new "Regimes" chart on the Overview page: VNINDEX with the risk state shaded, over the last 3 years.

## Part 2: Interaction Engine (research-period exploration, logged)

Question (section 26): **is a factor more informative when condition B holds?**

### Measure

- **Daily IC per factor.** For each date, the Spearman correlation between the factor's `rank_pct`
  (Factor Engine f1) and the percentile rank of `fwd_excess_exec_10d`, over the scored stocks.
  - Rows must pass the `ResearchParams()` universe: no `entry_blocked`, no `price_jump` in the next 20
    sessions, no `crosses_period`.
- **One test per factor x dimension**, comparing the two extreme states:

  | Dimension | State A | State B |
  |-----------|---------|---------|
  | direction | Bull | Bear |
  | volatility | high | low |
  | liquidity | high | low |
  | breadth | strong | weak |
  | foreign | buying | selling |
  | risk | risk_on | risk_off |

  - The test regresses the daily IC on a dummy (A = 1, B = 0; other dates dropped), using Newey-West
    standard errors with lag 9 (`hac_ols`).
  - The estimate is mean IC in A minus mean IC in B.
- **Family size: 9 factors x 6 dimensions = 54 tests.** Each test is logged in `hypothesis_log` (label
  `ix_<factor>_<dimension>`, period research), so BH q-values cover them together with every earlier
  test.
- **Descriptive, not logged:**
  - the mean IC of each factor in every state (all 3 states of each dimension);
  - the unconditional IC.

### Candidate rule (declared before the run)

An interaction is a **candidate** only if all three hold:
1. q < 0.05 (BH over the whole hypothesis log);
2. |IC difference| >= 0.02;
3. the difference has the same sign in both halves of the research period (2006-2014 and 2015-2023).

Candidates go to the Research Registry as `candidate`, in a new family `interaction`. Everything else is
reported as not a candidate, and the run is registered as one hypothesis family `P7-IX` in state
`rejected`, or with the candidates listed.

What a candidate means: a statistical interaction is **not** economic value. A candidate still needs:
- a cost-aware conditional portfolio test;
- a new pre-registration;
- forward data.

This is not done in this plan.

### Run rules

- `quant interactions scan` accepts only `--period research`. Validation and holdout are refused: both
  are used.
- Forward is refused until a pre-registration exists (a later plan).
- One run per period: a second run is refused until the first is invalidated with a reason (the same
  guard as the cross tests).

### Storage (`results.duckdb`)

- `interaction_stats (run_id, factor, dimension, state, n_dates, mean_ic, t)`
- `interaction_tests (run_id, factor, dimension, state_a, state_b, n_a, n_b, diff, se, t, p, diff_first_half, diff_second_half)`
- Report: `data/reports/research/interactions-<run>.md`, plus a results doc
  `docs/interaction-results-<date>.md`.

### UI

The Research page gets an "Interactions" tab:
- a heatmap of IC difference by factor x dimension, with q-values;
- per-state mean IC for a selected factor.

## Tests

**Regimes**
- Each tercile label equals a pandas rolling-percentile reference.
- The risk composite equals its rule.
- Point in time: perturbing data after a cut leaves every label up to the cut unchanged; the test is
  non-vacuous.
- Labels are NULL before 250 sessions.

**Interactions**
- The daily IC equals pandas `spearmanr` per date.
- The difference and t equal `hac_ols` on a hand-built series.
- Exactly 54 tests are logged.
- Periods other than research are refused, and the duplicate-run guard works.
- The halves split at 2015-01-01.

**General**
- The UI pages render read-only; the full suite stays green.

## Rollback

- **`research.duckdb`** is derived: revert the code and run `quant build`.
- **`results.duckdb`**: back it up before the first write. The interaction run itself is never deleted:
  if it is wrong, it is invalidated with a reason, so its tests leave the q-value family. Then the code is
  fixed and the scan is re-run.
- **Registry**: entries are corrected only by new transitions, never by edits.

## Open questions (defaults used unless you say otherwise)

1. Tercile states over a trailing 500-session window (no fixed thresholds), and the risk composite as
   defined above.
2. Run the interaction scan once on the research period as part of this plan, logged (+54 tests), with the
   candidate rule above. Alternative: build only, and run later.
3. Horizon: 10 sessions only (`fwd_excess_exec_10d`), to keep the family small. 5 and 20 sessions would
   triple the tests.

## Result (2026-10-08)

Built as planned; open questions answered with the defaults. Full suite: 280 passed (15 new). Results and
reading: `docs/interaction-results-2026-10-08.md`.

### Regime Engine

- `src/quant_research/regimes.py` (`RegimeParams`) builds `market_regimes` inside `quant build`.
- Real build `20261008T220620`: 30.4 s, 6,373 sessions labelled; the warehouse hash is unchanged.
- States today (2026-10-07):
  - direction Bear, volatility normal, liquidity low;
  - breadth weak, foreign neutral, risk neutral.
- Breadth (and therefore risk) is NULL for the first 1,299 sessions, while too few liquid stocks have a
  50-session mean.
- The dimension name `foreign` is a SQL keyword in some positions; it is quoted in every query.
- UI:
  - a regime line in the Market watch header;
  - "Market regimes" on Overview (VNINDEX with risk_on / risk_off shading over 3 years).

### Interaction Engine

- `src/quant_research/interactions.py`, `interaction_report.py` and `quant interactions scan`.
  - Research period only, with a duplicate-run guard.
  - The daily IC uses average ranks: exact Spearman, checked against scipy.
- UI: the Research page has an "Interactions" tab (heatmap, test table, per-state IC).
- Run `20261008T220700-interaction-interaction_scan-research`:
  - 54 tests logged;
  - **14 candidates** under the declared rule, all registered as `candidate` (`P7-IX-*`).
  - They form about 3 to 4 independent themes, and most effects fade after 2015; see the results doc.

### Tests

- Regimes (4):
  - the underlying values equal pandas;
  - the tercile labels equal a rolling percentile and are NULL before `min_obs`;
  - the risk rule holds;
  - point in time (non-vacuous).
- Interactions (9):
  - the daily IC equals `scipy.stats.spearmanr`;
  - the contrast equals the mean difference and `hac_ols`;
  - 54 labels are logged;
  - other periods are refused;
  - the duplicate guard works, and a re-run is allowed after invalidation;
  - the halves are correct;
  - the candidate rule cases.
- UI: two tests (regimes on Overview and Market watch; the Interactions tab without a scan).

### Data safety

- Backup before the run: `data/results.before-interactions.duckdb`.
- The UI pages render on real data with no database change.
