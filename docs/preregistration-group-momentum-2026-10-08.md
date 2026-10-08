# Pre-registration: industry momentum (Phase 4b candidate) on the validation period

Written 2026-10-08, **before** any query of group-momentum outcomes in the validation period (2024-01-01
to 2025-12-31). No cross-stock or group test has ever been run on the validation period
(`research_runs`: 0 validation runs of kind `cross` or pattern `cross_*` at the time of writing). The
SHA-256 of this file is stored with the validation run (`research_runs.params.extra.sha256`). Any change to
this file after the run invalidates the pre-registration.

## Origin

Research period result (`20261007T180725-cross-group_momentum-research`,
`docs/group-analysis-results-2026-10-07.md`):
- 21-session lookback: +0.53% / month (t 2.7, q 0.019 over 233 logged tests), turnover 0.66, net of
  rotation cost +0.26% / month;
- 63-session lookback: +0.48% / month (t 2.0, q 0.09).

The independent review found no artifact, but the effect is weak and faded in 2020-2023 (+0.21%, t 0.65).

## Frozen specification (exactly as tested on the research period)

- Code: `src/quant_research/cross/group_tests.py` (`run_group_momentum`), `src/quant_research/cross/groups.py`;
  cross code hash `67a9b2ccd6cd494a`, `CrossParams()` defaults, built with `quant cross build`.
- Groups: ICB level 2. Members are fixed at each month end: `is_traded`, `adv_value_20 > 1e9`,
  `session_index > 20`, no `price_jump`, no `bad_source_date`. An index day needs at least 5 member returns.
- Index: equal-weight daily close-to-close return in excess of VNINDEX. Members are those of the previous
  month end.
- Ranking at each month end t: the sum of the last 21 index sessions up to and including t, with at least
  80% coverage. A month needs at least 6 ranked industries with outcomes. The top tercile is
  `floor(n / 3)` industries.
- Outcome: for each industry, the mean `fwd_excess_exec_20d` at t over its members chosen at t that pass the
  research universe filter (`ResearchParams()` defaults, including no `crosses_period`). The industry needs
  at least 5 such members. Entry is at the next open.
- Statistic per month: mean outcome of the top-tercile industries minus the mean of all ranked industries.
  The test is the mean of the monthly series, Newey-West lag 1, two-sided t-test.
- Rotation cost: turnover (share of the top-tercile industries replaced from one month to the next) x 0.4%.

## Command (one run, no retries)

```
uv run quant cross test --period validation --tests g_momentum --prereg docs/preregistration-group-momentum-2026-10-08.md
```

The run computes both lookbacks, and both are logged. **Only the 21-session lookback decides**; the
63-session result is reported for information.

## Decision rule (21-session lookback, validation months 2024-01 to 2025-11; 2025-12 is excluded by `crosses_period`)

- **PASS**: mean monthly spread > 0 **and** p < 0.05 **and** net of rotation cost > 0.
- **CONSISTENT (not confirmed)**: mean > 0 and net > 0 but p >= 0.05. With about 23 months the test has
  low power. A true +0.26% / month would usually not reach p < 0.05, so this outcome is expected even if
  the effect is real.
- **FAIL**: mean <= 0 or net <= 0.

Whatever the outcome, no parameter is changed, and the validation period is not used again for this
hypothesis.

## What follows

- **PASS or CONSISTENT**: the frozen specification is tracked on forward data (sessions from 2026-10-03)
  as a paper portfolio. It is acted on only if the same rule (mean > 0, p < 0.05, net > 0) holds on at least
  24 forward months.
- **FAIL**: the hypothesis is closed. Forward tracking is not started.

## Known caveats (stated in advance)

- The 0.4% round trip is assumed for small members (ADV from 1bn VND); there is no market-impact model.
- 32 early research months (2006-2009) were missing (fewer than 6 industries).
- The long-only side is the weaker half: losers underperform more than winners outperform.
- The 21-session lookback was one of two lookbacks searched. q = 0.019 already accounts for this through
  BH over all logged tests.
