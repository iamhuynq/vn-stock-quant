# Validation results (2024-01-01 to 2025-12-31)

Pre-registration: `docs/preregistration-2026-10-04.md`, SHA-256 `6fe6d425...` (stored with every run;
the file was not edited after the runs). Report: `data/reports/research/patterns-validation-20261004T183943.md`.
The holdout (2026+) remains untouched.

## Primary decision (10 sessions, BH over the 4 pre-registered tests)

| ID | Pattern | Events (dates) | Pattern mean | Universe | Lift | t | q | Mean after cost | Rule | Result |
|----|---------|----------------|--------------|----------|------|---|---|-----------------|------|--------|
| C1 | `order_imbalance_d10` | 17,093 (478) | +0.05% | -0.42% | **+0.47%** | 4.36 | 3.2e-05 | -0.35% | lift > 0, q < 0.05, after cost > 0 | **FAIL** (after cost) |
| C1b | `order_imbalance_d10_no_limit` | 14,959 (478) | +0.11% | -0.42% | **+0.53%** | 4.73 | 1.2e-05 | -0.29% | same | **FAIL** (after cost) |
| C2 | `momentum10_d10` | 17,176 (478) | +0.06% | -0.42% | +0.48% | 1.97 | 0.049 | -0.34% | same | **FAIL** (after cost; lift borderline) |
| C3 | `drop3_volume2_sellers` | 50 (34) | -6.07% | -0.91% | **-5.16%** | -3.84 | 7.2e-04 | -6.47% | lift < 0, q < 0.05 | **PASS** (avoid signal) |

Secondary (5d / 20d lift): C1 +0.32% / +0.67%, C1b +0.39% / +0.73%, C2 +0.16% / +0.68%,
C3 -3.72% / -7.80%. Consistent in sign with the primary horizon.

## Reading

- **C1/C1b: the information replicated; the stand-alone long trade did not.** The order-imbalance lift
  over the universe held out of sample with t > 4 (about two thirds of its research-period size). It
  fails the pre-registered rule only because the whole filtered universe trailed VNINDEX by 0.42% per
  10 sessions in 2024-2025, so the top decile's excess return (+0.05%) could not cover 0.4% costs.
- **C2: weak replication.** Lift +0.48% with t = 1.97 (q = 0.049) and negative after costs.
- **C3: replicated as an avoid/exit signal** (-5.16% lift, larger than in research), but on only 50
  events over 34 dates; treat the size of the effect with caution.

## Lessons recorded (not applied retroactively)

- The tradability criterion depends on the benchmark. Excess return vs VNINDEX (cap-weighted, driven by
  a few large caps in 2024-2025) penalises every small/mid-cap long signal. A different benchmark or
  hedge (equal-weight universe, VN30 futures) is a **new hypothesis**: it must be pre-registered and
  tested on data the decision has not seen (the 2026 holdout or future data), not used to rescue C1.
- Per-trade cost of 0.4% assumes a full round trip every signal. A portfolio that holds overlapping
  signals trades less; measuring that belongs to the Phase 6 backtest, again as a new, pre-registered test.
