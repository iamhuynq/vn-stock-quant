# Backtest results: order-imbalance portfolio (Phase 6)

Pre-registration: `docs/preregistration-backtest-2026-10-04.md`, SHA-256 `43e9950402bb481b...`
(stored with every validation/holdout run; unchanged after the runs). Strategy version `72c851c7`.
Holdout runs in `results.duckdb`: 2 (the pre-registered 1e9 VND test and the pre-declared 10e9 report).

## Decision (holdout 2026-01-05 to 2026-10-02, 184 sessions, 1e9 VND)

| Criterion | Required | Observed | Result |
|-----------|----------|----------|--------|
| Primary: beat random-control runs | >= 19 of 20 | **5 of 20** | FAIL |
| Secondary: total return after costs | > 0 | **-21.0%** | FAIL |
| **Overall** | both | | **FAIL** |

## All out-of-sample runs

| Period | Capital | Strategy | Random median [p5, p95] | Beats random | Equal weight | VNINDEX | Max DD | Exposure | Turnover/yr |
|--------|---------|----------|-------------------------|--------------|--------------|---------|--------|----------|-------------|
| 2024-2025 (seen) | 1e9 | -2.9% | -2.9% [-21.6%, +13.0%] | 10/20 | +17.4% | +57.7% | -21.3% | 92% | 33 |
| 2024-2025 (seen) | 10e9 | -7.2% | -1.4% [-12.9%, +8.4%] | 6/20 | +17.4% | +57.7% | -13.6% | 37% | 14 |
| 2026 holdout | **1e9** | **-21.0%** | -18.9% [-24.3%, -11.2%] | **5/20** | -12.3% | -2.8% | -26.1% | 92% | 36 |
| 2026 holdout | 10e9 | -9.6% | -13.1% [-15.9%, -7.0%] | 15/20 | -12.3% | -2.8% | -14.1% | 41% | 17 |

In-sample (research period, 2007-07 to 2023, same configuration): CAGR 14.3%, beat 20/20 random runs.

## Reading

- **The portfolio edge did not survive out of sample.** After 2023 the strategy performs like random
  selection under identical mechanics (2024-2025: -2.9% vs -2.9%; 2026: -21.0% vs -18.9%).
- This is consistent with the Phase 3 evidence: the event-level lift of the top decile fell from +0.73%
  per 10 sessions (research) to +0.47% (2024-2025), while the portfolio pays about 0.4% per round trip
  at ~33-36x turnover a year (roughly 13-14% of capital per year in costs).
- The in-sample result was selected twice on the same data (signal from 30 features, variant from 24
  runs). The holdout did its job: it prevented trading a strategy whose in-sample CAGR was largely
  selection and cost-insensitive optimism.
- 2024-2026 were also poor years for the small/mid-cap universe relative to VNINDEX (large caps led),
  but the random control faces the same market, so this does not explain the failure.

## What is not concluded

- The order-imbalance *information* (Phase 3 lift) is not refuted; a tradable implementation of it is.
- A redesign (lower turnover, cost-aware entry, hedging, different universe) is a new hypothesis. It must
  be pre-registered and tested on data no decision has seen: forward data from 2026-10-03 onward.
