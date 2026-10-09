# Interaction scan results (research period, 2026-10-08)

Plan: `docs/regime-interaction-plan.md`. Run: `20261008T220700-interaction-interaction_scan-research`, one run.

- Report: `data/reports/research/interactions-20261008T220700-interaction-interaction_scan-research.md`.
- Inputs: factor set f1 and regimes from build `20261008T220620`.
- 54 tests are logged; the hypothesis log now has m = 289.

## Result

Applying the candidate rule declared before the run gives **14 candidates of 54**. The rule:
- q < 0.05;
- |IC difference| >= 0.02;
- the same sign in 2006-2014 and in 2015-2023.

All 14 are recorded in the Research Registry as `candidate` (family `interaction`, IDs `P7-IX-*`).

| Candidate | A vs B | IC diff | q | 2006-2014 | 2015-2023 |
|-----------|--------|---------|---|-----------|-----------|
| order_flow x breadth | strong vs weak | -0.058 | 8e-06 | -0.099 | -0.024 |
| volume_surge x breadth | strong vs weak | -0.044 | 1e-05 | -0.078 | -0.015 |
| order_flow x risk | risk_on vs risk_off | -0.061 | 0.0001 | -0.101 | -0.019 |
| liquidity x risk | risk_on vs risk_off | -0.064 | 0.0002 | -0.106 | -0.028 |
| liquidity x breadth | strong vs weak | -0.055 | 0.0004 | -0.080 | -0.033 |
| order_flow x direction | Bull vs Bear | -0.041 | 0.002 | -0.080 | -0.005 |
| momentum_12_1 x direction | Bull vs Bear | +0.061 | 0.005 | +0.082 | +0.044 |
| reversal_1w x volatility | high vs low | +0.047 | 0.005 | +0.081 | +0.023 |
| order_flow x liquidity | high vs low | -0.036 | 0.005 | -0.048 | -0.025 |
| reversal_1w x foreign | buying vs selling | -0.047 | 0.008 | -0.085 | -0.007 |
| reversal_1w x liquidity | high vs low | +0.040 | 0.03 | +0.074 | +0.008 |
| foreign_flow x breadth | strong vs weak | -0.022 | 0.03 | -0.029 | -0.016 |
| order_flow x foreign | buying vs selling | +0.029 | 0.04 | +0.060 | +0.002 |
| liquidity x liquidity | high vs low | -0.032 | 0.04 | -0.059 | -0.006 |

Unconditional IC (descriptive), for scale:

| Factor | Mean IC |
|--------|---------|
| order_flow | +0.040 |
| volatility | -0.064 |
| momentum_12_1 | +0.030 |
| momentum_1m | +0.026 |
| beta | -0.029 |
| reversal_1w | -0.013 |
| liquidity, foreign_flow, volume_surge | about 0 |

## Reading

- **One theme, not 14 findings.**
  - In weak, risk-off markets, the cross-section is more predictable from order flow, liquidity and volume
    surges. In strong, broad markets these factors lose most of their information.
  - Momentum 12-1 behaves the other way: it works in Bull markets and not in Bear markets, the well-known
    momentum crash pattern.
  - The 14 tests overlap heavily:
    - `order_flow` appears 5 times;
    - `risk` is built from `breadth` and `direction`;
    - `liquidity` and `breadth` move together.
  - The number of independent findings is closer to 3 or 4.
- **The effects fade.** In 10 of 14 candidates the 2015-2023 difference is less than half of the
  2006-2014 one. Four are close to zero after 2015:
  - order_flow x direction (-0.005);
  - reversal_1w x foreign (-0.007);
  - order_flow x foreign (+0.002);
  - liquidity x liquidity (-0.006).

  The fade matches the Phase 3 evidence, where the order-imbalance edge shrank out of sample.
- **The most stable after 2015** (second-half |difference| >= 0.02):
  - momentum_12_1 x direction (+0.044);
  - liquidity x breadth (-0.033);
  - liquidity x risk (-0.028);
  - order_flow x liquidity (-0.025);
  - order_flow x breadth (-0.024);
  - reversal_1w x volatility (+0.023).
- **Not economic value.** An IC of a few hundredths was already shown to be uneconomic after costs
  (order imbalance: predictive, FAIL after costs). A conditional version has to beat costs on fewer dates.

## Caveats

- **Regime labels are trailing terciles.** Liquidity and foreign flow trend upward over the years, so
  "high" and "buying" occur about twice as often as "low" and "selling" (research period: liquidity high
  2,856 vs low 1,390 sessions).
- **Newey-West on date-ordered ICs.** The test runs on the IC series of the A and B dates in date order;
  dropped neutral dates make some neighbours non-adjacent.
- **Industry codes** are today's classification, as everywhere in the project.

## Next step (not done; needs your decision)

Validation and holdout are used, so no candidate can be confirmed on past data. A confirmation would need:
1. a cost-aware conditional portfolio test;
2. a new pre-registration, written before any forward data is examined for this purpose;
3. enough forward data, likely more than a year for regime-conditional effects, since each state occupies
   only part of the sessions.

The most defensible single candidate for that path is **momentum_12_1 x direction**: it is the largest
effect after 2015, it is consistent with the literature, and it is not part of the order-flow cluster.
