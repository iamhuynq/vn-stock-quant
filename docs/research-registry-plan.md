# Plan: Research Registry

<!-- type: feature -->
<!-- status: built 2026-10-08 (approved 2026-10-08) -->

Source: `project-review-vn-stock-quant-1.md`, sections 29 (Research Registry), 31 (multiple testing) and 39
(roadmap, priority 1). It uses no validation, holdout or forward data.

## Problem

The lifecycle of each hypothesis lives in markdown only. The code knows runs (`research_runs`), p-values
(`hypothesis_log`, BH q in `hypothesis_q`) and four Phase 3 decisions, which are hard-coded in
`daily.py` (`VALIDATION_DECISIONS`) and copied into `validation_decisions` by every `quant daily`. The
following are not recorded anywhere a program can read:

- which hypotheses exist, and which family each one belongs to;
- which ones failed, were rejected in research, or are tracked forward;
- which pre-registration and which run decided each one.

Examples: the Phase 6 holdout FAIL, the Phase 4 rejections, the industry momentum FAIL and BREAKOUT on
forward watch.

## Design

### Tables (in `results.duckdb`, created by `ResultsStore`)

```sql
hypotheses (                       -- one row per hypothesis; written once, never updated
  hypothesis_id VARCHAR PRIMARY KEY,   -- e.g. 'P3-C1'
  family VARCHAR NOT NULL,             -- single_stock_pattern | portfolio | cross_stock | industry | event
  title VARCHAR NOT NULL,
  statement VARCHAR NOT NULL,          -- one sentence: what would be true
  pattern VARCHAR, pattern_version VARCHAR,   -- code identity when there is one
  created_at TIMESTAMPTZ NOT NULL)

hypothesis_transitions (           -- append-only history; the current state is the latest row
  hypothesis_id VARCHAR NOT NULL, seq INTEGER NOT NULL,
  status VARCHAR NOT NULL, decision VARCHAR,  -- decision: PASS | FAIL | NULL
  reason VARCHAR NOT NULL,
  run_id VARCHAR,                       -- the deciding run, must exist in research_runs with status 'ok'
  prereg_doc VARCHAR, prereg_sha VARCHAR,     -- checked against the file when given
  result_doc VARCHAR,
  moved_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (hypothesis_id, seq))

VIEW hypothesis_status                -- latest transition per hypothesis, plus run counts and min q-value
```

`validation_decisions` becomes a **view** over the registry with the same columns (pattern, version,
decision, reason, prereg_sha), so the daily report, Market watch and the Research page keep working
unchanged. `run_daily` stops writing it. `VALIDATION_DECISIONS` moves from `daily.py` into the seed.

### States and allowed transitions

| From | To |
|------|----|
| (new) | research, monitoring |
| research | rejected, candidate, monitoring |
| candidate | preregistered, rejected |
| preregistered | validated, failed |
| validated | forward, failed |
| monitoring | preregistered, rejected |
| forward | failed, expired |

Meaning:
- **research**: explored on data up to 2023 only.
- **rejected**: closed in research, never spent clean data.
- **candidate**: worth a test, no pre-registration yet.
- **preregistered**: rules written and hashed, test not run.
- **validated** / **failed**: decided on clean data. Only these two carry PASS/FAIL, and a decision
  requires a pre-registration and an `ok` run.
- **forward**: validated and tracked on forward data.
- **monitoring**: collected on forward data with no decision rule (a monitored hypothesis must be
  pre-registered before any decision).
- **expired**: a forward signal that has stopped working.

Any other transition is refused. Mistakes are corrected by a new transition with a reason, never by an
edit, matching the "invalidate, never delete" rule.

### Seed (the decisions already taken, copied verbatim from the result docs)

| ID | Family | Final state | Decision | Deciding run / doc |
|----|--------|-------------|----------|--------------------|
| P3-C1 `order_imbalance_d10` | single_stock_pattern | failed | FAIL | `...-order_imbalance_d10-validation`, `validation-results-2026-10-04.md` |
| P3-C1b `order_imbalance_d10_no_limit` | single_stock_pattern | failed | FAIL | same |
| P3-C2 `momentum10_d10` | single_stock_pattern | failed | FAIL | same |
| P3-C3 `drop3_volume2_sellers` | single_stock_pattern | forward | PASS (avoid) | same; tracked in the daily scan |
| P6-B1 portfolio `72c851c7` (1e9 VND) | portfolio | failed | FAIL | `...-holdout`, `backtest-results-2026-10-04.md`; the paper portfolio keeps running as information |
| P4-X1 lead-lag persistence | cross_stock | rejected | - | not tradable (opening gap) |
| P4-X2 H1 leaders to followers | cross_stock | rejected | - | below costs |
| P4-X3 H2 large to small caps | cross_stock | rejected | - | none once the market is controlled |
| P4-X4 H3 leader jump, follower flat | cross_stock | rejected | - | not significant |
| P4-X5 cointegration long leg | cross_stock | rejected | - | spreads do not revert |
| P4b-G1 industry lead-lag | industry | rejected | - | close prices only |
| P4b-G2 industry momentum 21d | industry | failed | FAIL | `...-group_momentum-validation`, prereg `da8ff1d0` |
| P4b-G3 weak industries keep underperforming (1 week) | industry | candidate | - | possible avoid signal; not pre-registered |
| P4b-G4 laggards in strong industries | industry | rejected | - | not significant |
| P5-E1 BREAKOUT | event | monitoring | - | event study `...-event_catalog_d9f85c2d`; forward scoreboard |

The seed runs on store open, inserts only missing rows (by ID and seq), and never changes existing rows.
Each seeded row records the path of the intermediate states (for example research -> candidate ->
preregistered -> failed), with their dates taken from the docs.

### CLI

- `quant registry list [--family F] [--status S]`
- `quant registry show ID`: history, linked runs, q-values from `hypothesis_q`.
- `quant registry add ID --family F --title T --statement S [--pattern P --version V]`
- `quant registry move ID --to STATUS --reason TEXT [--decision PASS|FAIL] [--run RUN] [--prereg DOC] [--result-doc DOC]`
  - the transition must be allowed;
  - a PASS/FAIL needs `--run` (an existing `ok` run) and `--prereg`;
  - `--prereg` stores the file's SHA-256 and refuses a file whose hash differs from the one stored with
    the run.

All writes go through the shared lock, like `quant runs --invalidate`.

### UI

- Research page: a new "Registry" tab, replacing the "Validation decisions" tab. It shows:
  - the table of hypotheses with status, decision, reason and docs;
  - for a selected hypothesis: its history and linked runs with q-values;
  - counts per status. "Rejected/failed" is reported as prominently as "validated" (section 31: the
    registry keeps every failure).
- Read-only, like every page. Moves are made with the CLI only, not from the UI.

## Not in scope

- Forcing every validation run to name a pre-registered hypothesis (`--hypothesis ID`). This would change
  how `quant pattern`/`cross test` behave. Validation and holdout are already used, so there is no
  validation run left to protect. It is proposed for later, together with the next pre-registration.
- A shared `ResearchResult` object (section 30) and moving the `docs/` folders (section 38).

## Tests

- Allowed transitions pass; every other transition is refused. PASS/FAIL without a run or a
  pre-registration is refused. A pre-registration whose hash differs is refused.
- History is append-only: there is no code path that updates or deletes a row.
- The seed is idempotent and never overwrites later transitions; it applies cleanly to an old
  `results.duckdb` that still has the `validation_decisions` table.
- The `validation_decisions` view returns exactly the four current rows (same values as today).
- The daily report and Market watch show the same avoid decision as before; the Research page renders the
  Registry tab read-only.
- The full suite stays green.

## Rollback

Commands:

```bash
cp data/results.duckdb data/results.before-registry.duckdb      # taken before the first write
# rollback: restore the copy and the previous code
cp data/results.before-registry.duckdb data/results.duckdb
```

Triggers: the `validation_decisions` view does not return the four current rows; the daily report or
Market watch shows a different avoid decision; any run row or hypothesis_log count changes.

Blast radius: only `results.duckdb` changes:
- two new tables and one new view;
- `validation_decisions` is replaced by a view, after its four rows are checked against the seed.

No run, statistic or log row is touched. Restoring the copy loses only registry transitions made after the
copy.

Tested in: the migration test on a copy of an old-style `results.duckdb`, then on a copy of the real file
in the scratchpad before touching `data/`.

## Open questions (defaults used unless you say otherwise)

1. P6-B1: `failed`, with a note that the paper portfolio keeps running as information.
2. P4b-G3 (weak industries keep underperforming): recorded as `candidate`, since it is a possible avoid
   signal and the research doc said it is not a long candidate. It is not pre-registered: doing so would
   be a separate decision.
3. P5-E1 BREAKOUT: `monitoring` (forward events are collected, no decision rule yet).

## Result (2026-10-08)

Built as planned; open questions answered with the defaults. Full suite: 259 passed (15 new).

- `src/quant_research/registry.py`: tables, views (`hypothesis_decision`, `hypothesis_status`,
  `validation_decisions`), transition rules, `add`, `move`, migration. `ResultsStore` calls
  `registry.ensure` on open.
- `src/quant_research/registry_seed.py`: the 15 hypotheses and 43 transitions, frozen.
  `VALIDATION_DECISIONS` was removed from `daily.py`; `run_daily` no longer writes decisions.
- `src/quant_research/registry_cli.py`: `quant registry list | show | add | move`. Writes use the same
  connection retry as `quant runs --invalidate`; refusals exit 2.
- UI: the Research page "Registry" tab replaces "Validation decisions". It shows:
  - counts per status;
  - the table, filtered by family;
  - the history and linked runs, with the minimum BH q-value, for a selected hypothesis.
- Deviation: the transition time column is named `moved_at` (`at` is reserved in DuckDB).
- Tests: `tests/research/test_registry.py` (14) and one Research-page test:
  - transitions: the full lifecycle, refused transitions, and the add rules;
  - decisions: decision rules, including an edited pre-registration being refused;
  - storage: the append-only code check, and seed rules and idempotence;
  - migration, and refusal when the old table holds rows the registry does not reproduce;
  - the CLI.

Migration of the real `data/results.duckdb`:
1. Backup: `data/results.before-registry.duckdb`.
2. Rehearsed first on a copy in the scratchpad (twice, to check idempotence).
3. Then applied.

Checks:
- `validation_decisions` returns the same 4 rows as before.
- `research_runs` (73), `hypothesis_log` (381) and `hypothesis_q` (235) are unchanged.
- Every seeded run id exists with status `ok`.
- The 6 seeded decisions carry the same pre-registration SHA-256 as their runs and as the files on disk.
- The Research, Market watch and Daily pages render on real data without changing any database file.

Current registry: failed 5, rejected 7, forward 1 (P3-C3 avoid signal), candidate 1 (P4b-G3), monitoring 1
(P5-E1 BREAKOUT).
