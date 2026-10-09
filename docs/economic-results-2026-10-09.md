# Economic evaluation of the frozen strategy 72c851c7 (research period, 2026-10-09)

Plan: `docs/economic-validation-plan.md`. Run: `20261009T094028-econ-frozen-research`.

- Report: `data/reports/research/econ-20261009T094028-econ-frozen-research.md`.
- The first run, `20261009T093634-econ-frozen-research`, was invalidated: its break-even was computed only
  on top of v1, which gives an uninformative 0. Its tables are identical to the second run's.
- The evaluation is descriptive: nothing went into the hypothesis log, and no recorded decision changes.

Strategy: the frozen order-imbalance portfolio. It buys the top decile of order imbalance, holds 10
sessions, keeps 20 positions and renews. Its backtest window is 2007-07 to 2023.

## Main numbers

| Capital | Costs | CAGR | vs equal weight (gross +0.9%) |
|---------|-------|------|-------------------------------|
| 1 bn VND | flat (commission + tax, the backtest default) | **+14.3%** | +13.4% |
| 1 bn VND | v1, tick-floor spread only, k = 1 (lower bound) | -5.8% | -6.7% |
| 1 bn VND | v1, k = 0.5 | -7.7% | -8.6% |
| 1 bn VND | **v1, k = 1** | **-10.9%** | -11.7% |
| 1 bn VND | v1, k = 2 | -15.2% | -16.1% |
| 10 bn VND | flat / v1 k = 1 | +4.8% / -11.6% | |
| 100 bn VND | flat / v1 k = 1 | +0.4% / -2.6% | |

**Break-even.** At 1 bn VND the strategy can absorb **0.415% of extra cost per side** on top of
commission and tax before it falls to the equal-weight universe. The average extra cost per side it
actually pays, by model:

| Cost model | Extra per side |
|------------|----------------|
| tick floor only, no impact | 0.28% |
| max(tick, CHL) spread, no impact | 0.48% |
| v1 with tick spread, k = 1 | 0.62% |
| v1, k = 1 | 0.79% |

Only the unrealistic "tick spread, no impact" case stays below the break-even.

**Controls.** The strategy beats 100% of the random, industry-matched and beta-matched runs at every capital
and cost level (95% for beta-matched at 100 bn VND with flat costs).

## Reading

- **The in-sample edge was real selection skill.** The strategy beats random portfolios, and also random
  portfolios with the same industry mix and the same beta mix. The in-sample result was therefore not an
  industry bet or a high-beta bet.
- **Realistic costs remove it.**
  - The strategy turns over its capital about 23 to 35 times a year and buys small, recently active
    stocks.
  - Spread and market impact for such trades cost more per side (0.6% to 0.8%) than the edge can absorb
    (0.4%).
  - Even with the lowest spread estimate and half the impact coefficient, the research-period CAGR is
    negative.
- **Capacity is low.**
  - At 10 bn VND the flat-cost CAGR already falls to +4.8%, because the 5% ADV cap blocks entries.
  - At 100 bn VND it is about zero before spread and impact.
- **This explains the holdout failure in economic terms.** The holdout (2026) and validation (2024-2025)
  runs used flat costs and still failed. Under realistic costs the strategy would not have been worth
  testing.
- **The forward paper portfolio** keeps its pre-registered flat costs, as the paper trading record. Its
  economic value should be read with this evaluation in mind.

## Caveats

- **Spreads.** There is no quote data. The CHL estimator is noisy over 21 sessions: its median is 0 after
  flooring, but it is sometimes very high. Taking max(tick, CHL) therefore overstates spreads of liquid
  stocks (FPT on 2026-10-07: 50.8 bps against a tick floor of 8.4 bps). The tick-only variant is the lower
  bound.
- **Impact coefficient.** k is not fitted, because there are no fills. 0.5 to 2 brackets common values.
- **Ticks and exchanges.** Today's tick rules and today's exchange are used for all years, as in
  `daily_panel`.
- **Benchmark.** The ADV-weighted benchmark (-4.8% CAGR) is a poor capitalization proxy: it overweights
  stocks right after volume spikes. VNINDEX (+0.8%) is the cap-weighted reference.

## Consequence for future work

Any new strategy candidate must pass this evaluation **before** a pre-registration is written. The
recommended evaluation:
- cost model v1 at k = 1, with the tick-only variant as the optimistic bound;
- break-even per side reported against the estimated extra cost;
- matched controls (industry and beta).

High-turnover signals in small stocks are very unlikely to survive. The interaction candidates (registry
`P7-IX-*`) would need low-turnover implementations; momentum 12-1 has a 20-session rank persistence of 0.90.
