# Portfolio construction grid results (research period, 2026-10-09)

Plan: `docs/portfolio-construction-plan.md`.
- Runs: `20261009T104238-portfolio-C1..C6-research`, one per configuration, each logging one test.
- Report: `data/reports/research/portfolio-grid-20261009T104238.md`.
- The first runs, `20261009T103304-portfolio-C1..C6-research`, are invalidated. Their random control redrew
  scores at every rebalance, so it traded far more than the strategy. They were re-run with a
  persistence-matched control (see "Control fix").
  - Strategy numbers and test p-values are identical in both runs; only the control columns changed.

## Result: no configuration passes the declared reading rule

The reading rule, applied at 1 bn VND with cost model v1 (k = 1):
- beat equal weight;
- beat at least 19 of 20 matched random runs;
- absorb at least 0.2% of extra cost per side.

| Config | Signal, schedule, buffer, filter | CAGR flat | CAGR v1 | CAGR v1 tick | Equal weight | Turnover / yr (v1) | Verdict |
|--------|----------------------------------|-----------|---------|--------------|--------------|--------------------|---------|
| C1 | order_flow, weekly, 20 / 20 | +4.2% | -23.0% | -17.9% | +0.8% | 66 | no |
| C2 | order_flow, weekly, 20 / 40 | +6.7% | -17.3% | -12.1% | +0.8% | 47 | no |
| C3 | order_flow, monthly, 20 / 40 | +3.5% | -5.9% | -3.2% | +0.8% | 14 | no |
| C4 | momentum_12_1, monthly, 20 / 20 | -8.1% | -12.7% | -11.0% | -0.4% | 8 | no |
| C5 | momentum_12_1, monthly, 20 / 40 | -9.7% | -13.0% | -11.8% | -0.4% | 6 | no |
| C6 | C5 + cash when direction = Bear | +0.3% | -3.1% | -2.2% | -0.4% | 5 | no |

All six fail "beats equal weight" and the break-even (0 over v1 in every case).

Registry: `P7-IX-momentum_12_1-direction` moves from `candidate` to `rejected`, with run C6. The transition
cites the first C6 run (`20261009T103304`), now invalidated. The re-run `20261009T104238-portfolio-C6-research`
has identical strategy numbers, and the rejection stands; `rejected` is a final state.

## Reading

- **Slowing order flow down helps, but not enough.**
  - The buffer and the monthly schedule cut turnover from 66 to 14 times a year, and the v1 CAGR improves
    from -23% to -6%.
  - However, the order-flow information decays within days (rank persistence 0.40 after 5 sessions). A
    monthly portfolio holds mostly stale signals: its flat-cost edge shrinks to +2.7% a year over equal
    weight, and v1 costs exceed that.
  - The fast version (C1) has the information but pays too much to trade it.
- **Momentum 12-1, top 20, loses even before costs.** C4 is -8.1% a year with flat costs, against -0.4% for
  equal weight.
  - An independent check confirms it: over 196 month-starts, the top 20 by 12-1 momentum returned -0.27% in
    the next 20 sessions, against +0.34% for all scored stocks (2015-2023: +0.18% against +0.65%).
  - The factor's average IC is positive (+0.03), but the extreme winners underperform. Their returns are
    not monotonic in the top tail, so a concentrated top-20 portfolio is the wrong way to use this factor.
- **The Bear filter is a large improvement** (C5 -9.7% to C6 +0.3% with flat costs). This is consistent with
  the interaction scan, but it still does not beat equal weight after costs.

## Control fix (2026-10-09)

The matched random control now uses the same construction on random scores that keep the signal's own rank
persistence between rebalances (AR(1) per stock, rho measured on the run's window). The control therefore
trades about as much as the strategy.

At 1 bn VND with v1 costs:

| Config | Rank persistence | Strategy turnover | Control turnover | Strategy CAGR | Control median CAGR [p5, p95] | Beats control |
|--------|------------------|-------------------|------------------|---------------|-------------------------------|---------------|
| C1 | 0.42 | 65.8 | 66.1 | -23.0% | -34.5% [-40.5%, -29.1%] | 100% |
| C2 | 0.42 | 47.1 | 48.7 | -17.3% | -29.8% [-35.6%, -25.9%] | 100% |
| C3 | 0.20 | 14.4 | 16.0 | -5.9% | -12.8% [-15.6%, -10.3%] | 100% |
| C4 | 0.90 | 7.8 | 10.1 | -12.7% | -10.3% [-13.1%, -6.6%] | 10% |
| C5 | 0.90 | 5.5 | 6.4 | -13.0% | -7.5% [-10.2%, -3.8%] | 0% |
| C6 | 0.90 | 4.6 | 4.8 | -3.1% | -2.3% [-4.1%, +0.2%] | 30% |

Reading:
- **Order flow has real selection skill at the same turnover.** It is 7 to 13 points a year better than
  random portfolios that trade as much, but it cannot pay its own trading costs.
- **Momentum 12-1, top 20, is worse than random at the same turnover** (C5: 0 of 20 control runs
  beaten). Concentrating on extreme past winners is a negative selection in this market, in the research
  period.
- No verdict changes. Every configuration still fails "beats equal weight" and the break-even.

## Caveats

- **Stuck positions.** Held names can exceed 20, up to 28 in C4: sells are blocked by the floor, by days
  without trades, or by T+2. A few suspended stocks stay at their last price. This is a real constraint;
  the valuation at the last price slightly flatters every configuration.
- **Shared approximations.** Spreads, the impact coefficient, today's tick rules and today's industry codes
  are approximations; see `economic-results-2026-10-09.md`.

## State of the project after this grid

- No signal found so far survives realistic trading costs in a long-only portfolio.
- The research infrastructure is now complete for the roadmap of the review:
  - registry;
  - factors;
  - regimes;
  - interactions;
  - economic validation;
  - portfolio construction.
- The remaining value is in:
  - the validated avoid signal (P3-C3, forward);
  - risk tools: exposure, regimes, correlations;
  - forward monitoring.
