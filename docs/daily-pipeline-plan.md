# Plan: Daily pipeline - event scanner (Phase 5) + forward paper trading

<!-- type: feature -->
<!-- status: built 2026-10-05; manual runs (launchd not installed); first real update pending after 18:00 -->

Source: `quant_research_chung_khoan_viet_nam.md` sections 15, 24, 25 (daily system), 18 (out-of-sample).
Builds on Phases 1-6. Motivation: `docs/backtest-results-2026-10-04.md` (holdout failed; new ideas need
data no decision has seen, i.e. data from 2026-10-03 onward).

## Goals

1. **Daily event scanner**: after each session, list which library patterns fired today, with each
   pattern's historical statistics and validation status (doc 15, 24, 25).
2. **Forward test ("paper trading")**: from 2026-10-03, track (a) the outcomes of every pattern event and
   (b) the frozen order-imbalance portfolio and its random control, on data nobody has seen.
3. A one-page daily report.

## Key design decisions

| Topic | Decision | Why |
|-------|----------|-----|
| Freeze the holdout | `period` becomes: research <= 2023, validation 2024-2025, **holdout 2026-01-01..2026-10-02**, **forward >= 2026-10-03** | The 2026 holdout was used once; new data must not leak into it, and forward data gets its own label |
| Paper portfolio state | **Re-simulate** the frozen strategy over the forward period every day with the Phase 6 engine (deterministic), instead of keeping mutable position state | No state to corrupt; identical rules to the backtest; adj_ratio rewrites are handled automatically |
| What is paper-traded | Strategy `72c851c7` (H10, K20, renew, 1e9 VND) exactly as frozen, plus 20 random controls | Measures post-holdout behaviour without changing anything; any redesign is a separate, later pre-registration |
| Event outcomes | Forward events stored daily; 5/10/20-session outcomes filled in as they mature | A forward event study for every pattern, accumulating automatically |
| Avoid signal | C3 `drop3_volume2_sellers` (the only candidate that passed validation) is highlighted in the report as an avoid/exit warning | Directly usable without shorting |
| Scheduling | `scripts/daily.sh` + a **launchd** agent (`~/Library/LaunchAgents/`), Mon-Fri from 18:30 Asia/Ho_Chi_Minh, see Reliability. **Installed only after you confirm**, since it changes your system and uses your token daily | Outward-facing change; launchd catches up after sleep, cron does not |
| Report | Markdown `data/reports/daily/YYYY-MM-DD.md` | Readable in the IDE; an HTML page can be added later |

## Daily run (scripts/daily.sh)

1. `fireant update` (corporate actions + quotes); on Fridays also `--jobs report_marks,fundamental`.
2. `fireant validate` (report kept; does not block).
3. `quant build` (about 15 s).
4. `quant daily`:
   - scan today's features with every library pattern (data <= today only);
   - store events in `daily_events`; update matured outcomes of earlier forward events;
   - re-simulate the paper portfolio and controls over the forward period; store in `paper_*` tables;
   - write the daily report.
5. Log to `data/logs/daily-YYYY-MM-DD.log`; stop at the first failing step (a 401 means the token
   expired; the report says so).

## Reliability (laptop: may be asleep, off, or offline)

| Risk | Handling |
|------|----------|
| Mac asleep or off at 18:30 | **launchd** (not cron) job: runs at 18:30 and every 30 min until 23:30, plus at login; launchd runs a missed slot on wake. A "latest session done" marker makes extra triggers exit in about a second |
| Several days missed | The run is **catch-up**, not "today only": `fireant update` already refetches from the last stored date; `quant daily` scans every session after the last scanned one |
| Network down at start | Pre-flight request (`/symbols/VOS`); on failure exit with code 10 ("offline, retry next slot") without touching any database |
| Network lost mid-run | Existing per-request retries + per-task transactions; new **circuit breaker**: 10 consecutive network failures abort the run (instead of ~8 h of retries); failed/undone tasks resume next slot |
| Partial update (some symbols fetched, others not) | **Completeness gate**: a session is scanned only if >= 95% of the previous session's universe has a row for it; otherwise the report says "data incomplete, not scanned" and the next slot retries |
| Overlapping runs | Lock file (`data/.daily.lock`, PID + start time; stale after 3 h); a second run exits immediately |
| Token expired (401) | Stop, report, macOS notification; nothing retried until the token is replaced |
| Visibility | macOS notification on success (one line) and on every failure, with the reason and next retry time |

## Report contents

- Data date, market regime (VNINDEX vs MA50/MA200), data-quality warnings.
- **Avoid list**: today's C3 events.
- Today's events per pattern: symbols, plus the pattern's research lift, validation result, q-value and
  verdict (labelled clearly: historical statistics, not a forecast).
- Forward scoreboard per pattern: forward events so far, matured outcomes, forward lift vs universe.
- Paper portfolio: equity since 2026-10-03 vs random-control band, equal weight and VNINDEX; open
  positions; trades of the day.

## Storage (results.duckdb, additive tables)

`daily_events (scan_date, pattern, version, symbol, features snapshot, regime)`,
`forward_outcomes (pattern, symbol, date, out_5d, out_10d, out_20d, matured_at)`,
`paper_runs (run_date, strategy_version, equity, random_p05/median/p95, ew, vnindex)`,
`paper_positions (run_date, symbol, entry_date, shares, last_price)`.

## Tests

- Period assignment: 2026-10-02 -> holdout, 2026-10-03 -> forward (feature build tests updated).
- Scanner uses only rows of the scan date; events equal a direct SQL query; no target columns read.
- Forward outcomes appear only after enough sessions have passed.
- Paper re-simulation is deterministic and equals a direct engine run on the forward window.
- Report renders with zero events, with events, and before any forward session exists.
- `daily.sh` stops on the first failure (shell test with a failing stub).
- Circuit breaker aborts after 10 consecutive network errors (fake transport); completeness gate skips a
  session with 60% coverage and scans it once coverage reaches 100%; catch-up scans every missed
  session exactly once; a second concurrent run exits on the lock; offline pre-flight touches no database.

## Rollback

- Code: the period change is a feature-set version bump (`v2`); `quant build` rebuilds from the warehouse.
- Data: daily tables are additive; a bad day is re-run (`quant daily --date YYYY-MM-DD`) and replaces only
  that day's rows.
- Scheduling: `launchctl bootout gui/$(id -u) <plist>` and delete the plist; nothing else is installed.

## Open questions

1. Install the launchd agent on this Mac, or run `scripts/daily.sh` manually for now?
   Default: manual until you confirm.
2. Anything else to paper-trade from day one? Default: only the frozen strategy (no redesign yet).

## Result (2026-10-05)

- Feature set **v2**: `period` = research / validation / holdout (2026-01-01..2026-10-02, frozen) / forward
  (>= 2026-10-03). New table `source_coverage` (raw warehouse rows per session).
- Crawler: circuit breaker (10 consecutive gave-up tasks -> exit 10) and offline pre-flight (exit 10, no
  database touched).
- `quant daily`: catch-up scanner on `stock_features` only, completeness gate, paper portfolio by
  re-simulation, daily report `data/reports/daily/{date}.md`; recorded validation decisions shown verbatim.
- `scripts/daily.sh` (lock, done-marker, exit codes, notifications) and `scripts/install_launchd.sh`
  (install | uninstall | status | print). **Not installed.**
- 156 tests pass (including 7 shell tests with stub commands).

Bugs found while building and fixed:
- The completeness gate first counted `daily_panel` rows; the panel drops each stock's sessions after its
  latest trade, so the latest session would always have looked incomplete (about a third of rows are
  no-trade sessions). It now counts raw warehouse rows.
- The report first recomputed "validated" from the lift q-value, labelling C1/C1b as passed although they
  failed the pre-registered after-cost rule. It now shows the recorded decisions (`validation_decisions`).
- Weekly jobs keyed on the weekday of the run instead of the target session (missed on Saturday catch-up).

First real run on 2026-10-05 08:55 (no API call, before the session): build v2 + `quant daily` on data of
2026-10-02, coverage 100%, warehouse hash unchanged. The first `scripts/daily.sh` with `fireant update`
should run after 18:00.


## Fix (2026-10-05): sessions still in progress

- **Problem:** `fireant update` fetched quotes up to today's date, and the per-symbol update checkpoint was
  keyed by that date. A run during trading hours could store a session still in progress. The 18:30 run
  then skipped those symbols as "already done", so the row stayed, and `quant daily` scanned it as final.
  This was reproduced with a test that runs the update at 10:00 and at 18:30: without the fix the mid-session
  price is stored.
- **Fix:** `fireant_crawler/sessions.py` `final_session(now)` returns today after 18:00 Vietnam time on a
  weekday, else the previous weekday (the same rule as `target_day()` in `daily.sh`).
  - The crawler uses it as `endDate` and as the checkpoint key, so any run is safe, and the evening run
    fetches the session once it is final.
  - `quant daily` scans and paper-trades only up to it, and `--date` refuses a session that is not final
    (exit 2).
- **Tests:** `tests/test_sessions.py`, the 10:00 then 18:30 update in `tests/test_jobs.py`, and the
  session-in-progress test in `tests/research/test_daily.py`. 199 tests pass.

## Catch-up after missed days (2026-10-05)

A run after several missed days already fetched every missing session (`fireant update` starts from the last
stored date) and scanned each one once (`quant daily` catch-up). Two gaps are now closed:

- **Weekly jobs** (`report_marks`, `fundamental`) run when the target session is a Friday **or** when the
  last successful weekly update (`data/.weekly_done`) is 7 or more days old, or missing. Before, a missed
  Friday was only caught up on the next Friday-target run. Missed weeks of `fundamental` snapshots cannot
  be recovered, because the API returns current values only; report marks are fetched in full each time.
- **One report per scanned session**: `write_reports` writes `data/reports/daily/{session}.md` for every
  session scanned in the run. Earlier sessions get a "catch-up report" with their regime, avoid list,
  events and paper equity on that date. The forward scoreboard and open positions are only in the latest
  report.
- Tests: weekly catch-up, skip and retry in `tests/test_daily_script.py`; one report per missed session in
  `tests/research/test_daily.py`. 203 tests pass.
