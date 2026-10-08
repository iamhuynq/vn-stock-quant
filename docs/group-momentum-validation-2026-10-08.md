# Validation result: industry momentum (Phase 4b candidate)

Pre-registration: `docs/preregistration-group-momentum-2026-10-08.md`, SHA-256
`da8ff1d0750524751a713af792516545b581fe6663dfa2e9dbd95cad55fe0b94`. The same hash is stored with the run.
Run: `20261008T152452-cross-group_momentum-validation`, one run, no retries. Report:
`data/reports/cross/tests-validation-20261008T152452.md`.

## Result (validation months 2024-01 to 2025-11, n = 23)

| Lookback | Mean spread / month | t | p | Turnover | Net of rotation cost | Role |
|----------|---------------------|---|---|----------|----------------------|------|
| 21 sessions | **-0.18%** | -0.53 | 0.60 | 0.65 | **-0.44%** | decides |
| 63 sessions | -0.44% | -1.24 | 0.23 | 0.43 | -0.62% | information |

Research period for comparison: 21 sessions +0.53% (t 2.7), net +0.26%.

## Decision: **FAIL**

The mean is <= 0 and the net is <= 0. Following the pre-registered rule:
- the hypothesis is **closed**;
- it is **not** added to forward tracking;
- no parameter will be changed and the validation period will not be used again for it.

## Reading

- On validation data the top industries of the last month did slightly **worse** than the average
  industry. The 3-month version did too.
- Together with the fading research sub-period (2020-2023: +0.21%, t 0.65), the most likely explanation
  is a historical effect that is no longer present, or one that was never strong enough to survive out of
  sample.
- Validation has low power (23 months). A FAIL with a negative sign is still informative: it does not
  look like a weak positive effect hidden by noise.

## State of the cross-stock family after Phase 4 and 4b

- Nothing tradable was found.
- Lead-lag at stock and industry level lives in the opening gap (stale prices).
- Group and stock spillovers are below costs.
- Cointegrated spreads do not revert.
- Industry momentum failed validation.

What remains useful is the descriptive layer: peers, industry blocks, rolling correlations (risk
concentration). The validation period has now been used once for the cross-stock family (this run only).
