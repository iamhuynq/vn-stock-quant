"""Research Registry (docs/research-registry-plan.md): every hypothesis, its lifecycle and its decision.

`hypotheses` holds one row per hypothesis, written once. `hypothesis_transitions` is append-only: the
current state is the latest row, and mistakes are corrected by a new transition with a reason. There is no
code path that updates or deletes a row of either table.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path

import duckdb

from quant_research.registry_seed import SEED_HYPOTHESES, SEED_TRANSITIONS

FAMILIES = ("single_stock_pattern", "portfolio", "cross_stock", "industry", "event", "interaction")
TRANSITIONS = {
    None: ("research", "monitoring"),
    "research": ("rejected", "candidate", "monitoring"),
    "candidate": ("preregistered", "rejected"),
    "preregistered": ("validated", "failed"),
    "validated": ("forward", "failed"),
    "monitoring": ("preregistered", "rejected"),
    "forward": ("failed", "expired"),
    "rejected": (),
    "failed": (),
    "expired": (),
}
DECISION_FOR = {"validated": "PASS", "failed": "FAIL"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS hypotheses (
    hypothesis_id VARCHAR PRIMARY KEY, family VARCHAR NOT NULL, title VARCHAR NOT NULL,
    statement VARCHAR NOT NULL, pattern VARCHAR, pattern_version VARCHAR, created_at TIMESTAMPTZ NOT NULL);
CREATE TABLE IF NOT EXISTS hypothesis_transitions (
    hypothesis_id VARCHAR NOT NULL, seq INTEGER NOT NULL, status VARCHAR NOT NULL, decision VARCHAR,
    reason VARCHAR NOT NULL, run_id VARCHAR, prereg_doc VARCHAR, prereg_sha VARCHAR, result_doc VARCHAR,
    moved_at TIMESTAMPTZ NOT NULL, PRIMARY KEY (hypothesis_id, seq));
"""
VIEWS = """
-- The latest decision (PASS / FAIL) per hypothesis, with the transition that carried it.
CREATE OR REPLACE VIEW hypothesis_decision AS
SELECT * EXCLUDE (rk) FROM (
    SELECT *, row_number() OVER (PARTITION BY hypothesis_id ORDER BY seq DESC) AS rk
    FROM hypothesis_transitions WHERE decision IS NOT NULL) WHERE rk = 1;
CREATE OR REPLACE VIEW hypothesis_status AS
WITH last AS (SELECT * EXCLUDE (rk) FROM (
    SELECT *, row_number() OVER (PARTITION BY hypothesis_id ORDER BY seq DESC) AS rk
    FROM hypothesis_transitions) WHERE rk = 1)
SELECT h.hypothesis_id, h.family, h.title, h.pattern, h.pattern_version, last.status, d.decision,
       coalesce(d.reason, last.reason) AS reason, last.moved_at AS updated_at, d.run_id AS decision_run,
       d.prereg_doc, d.prereg_sha, coalesce(d.result_doc, last.result_doc) AS result_doc, h.statement
FROM hypotheses h JOIN last USING (hypothesis_id) LEFT JOIN hypothesis_decision d USING (hypothesis_id);
-- Former table (written by `quant daily` until 2026-10-08), now derived from the registry.
CREATE OR REPLACE VIEW validation_decisions AS
SELECT h.pattern, h.pattern_version AS version, d.decision, d.reason, left(d.prereg_sha, 8) AS prereg_sha
FROM hypotheses h JOIN hypothesis_decision d USING (hypothesis_id)
WHERE h.family = 'single_stock_pattern' AND h.pattern IS NOT NULL;
"""


class RegistryError(ValueError):
    pass


def ensure(con: duckdb.DuckDBPyConnection) -> None:
    """Create the tables, add the seed rows that are missing, and replace the old decision table by a view."""
    con.execute(SCHEMA)
    for row in SEED_HYPOTHESES:
        con.execute("INSERT INTO hypotheses SELECT ?, ?, ?, ?, ?, ?, ? WHERE NOT EXISTS "
                    "(SELECT 1 FROM hypotheses WHERE hypothesis_id = ?)", [*row, row[0]])
    for row in SEED_TRANSITIONS:
        con.execute("INSERT INTO hypothesis_transitions SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ? WHERE NOT EXISTS "
                    "(SELECT 1 FROM hypothesis_transitions WHERE hypothesis_id = ? AND seq = ?)",
                    [*row, row[0], row[1]])
    old = con.execute("""SELECT count(*) FROM duckdb_tables()
                         WHERE table_name = 'validation_decisions' AND schema_name = 'main'
                           AND database_name = current_database()""").fetchone()[0]
    if old:
        _migrate_decisions(con)
    con.execute(VIEWS)


def _migrate_decisions(con: duckdb.DuckDBPyConnection) -> None:
    """Drop the old copy only if every row it holds is reproduced by the registry."""
    rows = con.execute("SELECT pattern, version, decision, reason, prereg_sha FROM validation_decisions").fetchall()
    con.execute(VIEWS.replace("validation_decisions", "registry_decisions_check"))
    derived = con.execute("""SELECT pattern, version, decision, reason, prereg_sha
                             FROM registry_decisions_check""").fetchall()
    con.execute("DROP VIEW registry_decisions_check")
    if not set(rows) <= set(derived):
        raise RegistryError("validation_decisions holds rows the registry does not reproduce; not migrated: "
                            f"{sorted(set(rows) - set(derived))}")
    con.execute("DROP TABLE validation_decisions")


def current(con: duckdb.DuckDBPyConnection, hypothesis_id: str) -> tuple[int, str] | None:
    """(seq, status) of the latest transition, or None for an unknown hypothesis."""
    return con.execute("""SELECT seq, status FROM hypothesis_transitions WHERE hypothesis_id = ?
                          ORDER BY seq DESC LIMIT 1""", [hypothesis_id]).fetchone()


def add(con: duckdb.DuckDBPyConnection, hypothesis_id: str, family: str, title: str, statement: str,
        now: datetime, reason: str, status: str = "research", pattern: str | None = None,
        version: str | None = None) -> None:
    if family not in FAMILIES:
        raise RegistryError(f"Unknown family {family!r}; use one of {FAMILIES}")
    if status not in TRANSITIONS[None]:
        raise RegistryError(f"A new hypothesis starts as one of {TRANSITIONS[None]}, not {status!r}")
    if not (hypothesis_id.strip() and title.strip() and statement.strip() and reason.strip()):
        raise RegistryError("id, title, statement and reason are required")
    if con.execute("SELECT 1 FROM hypotheses WHERE hypothesis_id = ?", [hypothesis_id]).fetchone():
        raise RegistryError(f"Hypothesis {hypothesis_id} already exists")
    con.execute("INSERT INTO hypotheses VALUES (?, ?, ?, ?, ?, ?, ?)",
                [hypothesis_id, family, title, statement, pattern, version, now])
    con.execute("INSERT INTO hypothesis_transitions VALUES (?, 1, ?, NULL, ?, NULL, NULL, NULL, NULL, ?)",
                [hypothesis_id, status, reason, now])


def _file_sha(path: Path) -> str:
    if not path.is_file():
        raise RegistryError(f"No pre-registration file at {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_decision_run(con: duckdb.DuckDBPyConnection, run_id: str | None, sha: str | None) -> None:
    if run_id is None or sha is None:
        raise RegistryError("A PASS / FAIL needs the deciding run (--run) and its pre-registration (--prereg)")
    row = con.execute("SELECT status, period, params FROM research_runs WHERE run_id = ?", [run_id]).fetchone()
    if row is None:
        raise RegistryError(f"No run {run_id}")
    status, period, params = row
    if status != "ok":
        raise RegistryError(f"Run {run_id} is {status}; a decision needs a valid run")
    if period == "research":
        raise RegistryError(f"Run {run_id} is on the research period; a decision needs clean data")
    stored = (json.loads(params).get("extra") or {}).get("sha256")
    if stored != sha:
        raise RegistryError(f"The pre-registration hash ({sha[:12]}) differs from the one stored with run "
                            f"{run_id} ({(stored or 'none')[:12]})")


def move(con: duckdb.DuckDBPyConnection, hypothesis_id: str, to: str, reason: str, now: datetime,
         decision: str | None = None, run_id: str | None = None, prereg: Path | None = None,
         result_doc: str | None = None) -> int:
    """Append one allowed transition; returns its seq. Every rule failure raises RegistryError."""
    cur = current(con, hypothesis_id)
    if cur is None:
        raise RegistryError(f"Unknown hypothesis {hypothesis_id}")
    seq, status = cur
    if to not in TRANSITIONS[status]:
        allowed = ", ".join(TRANSITIONS[status]) or "none (final state)"
        raise RegistryError(f"{hypothesis_id} is {status}; allowed next states: {allowed}")
    if not reason.strip():
        raise RegistryError("--reason is required")
    if decision != DECISION_FOR.get(to):
        need = DECISION_FOR.get(to)
        raise RegistryError(f"Moving to {to} needs --decision {need}" if need else
                            f"Only validated (PASS) and failed (FAIL) carry a decision, not {to}")
    if to == "preregistered" and prereg is None:
        raise RegistryError("Moving to preregistered needs --prereg <file>")
    if run_id is not None and not con.execute("SELECT 1 FROM research_runs WHERE run_id = ?", [run_id]).fetchone():
        raise RegistryError(f"No run {run_id}")
    sha = _file_sha(prereg) if prereg is not None else None
    if decision is not None:
        _check_decision_run(con, run_id, sha)
    con.execute("INSERT INTO hypothesis_transitions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [hypothesis_id, seq + 1, to, decision, reason, run_id,
                 None if prereg is None else prereg.as_posix(), sha, result_doc, now])
    return seq + 1
