"""Research Registry: allowed transitions, decision rules, append-only history, seed, migration, CLI."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from quant_research import registry
from quant_research.registry import TRANSITIONS, RegistryError, add, move
from quant_research.registry_seed import SEED_HYPOTHESES, SEED_TRANSITIONS
from quant_research.results import SCHEMA, ResultsStore

NOW = datetime(2026, 10, 9, 20, 0, tzinfo=UTC)
OLD_DECISIONS = [   # the table `quant daily` wrote until 2026-10-08
    ("drop3_volume2_sellers", "cb8daa50", "PASS", "avoid signal: lift -5.16% (q<0.001), 50 events", "6fe6d425"),
    ("momentum10_d10", "5905e5b3", "FAIL", "lift +0.48% borderline (q 0.049), -0.34% after costs", "6fe6d425"),
    ("order_imbalance_d10", "0a1952fa", "FAIL", "lift +0.47% replicated (q<0.05) but -0.35% after costs", "6fe6d425"),
    ("order_imbalance_d10_no_limit", "dc53588e", "FAIL", "lift +0.53% replicated (q<0.05) but -0.29% after costs",
     "6fe6d425"),
]


@pytest.fixture
def paths(tmp_path):
    research = tmp_path / "research.duckdb"
    duckdb.connect(str(research)).close()
    return tmp_path / "results.duckdb", research


def _run(con, run_id: str, period: str = "validation", status: str = "ok", sha: str | None = None) -> None:
    params = {"extra": {"sha256": sha} if sha else {}}
    con.execute("INSERT INTO research_runs VALUES (?, 'pattern', 'p', 'v', ?, ?, NULL, 'c', ?, ?, NULL)",
                [run_id, period, json.dumps(params), NOW, status])


def _prereg(tmp_path: Path, text: str = "rules") -> tuple[Path, str]:
    p = tmp_path / "prereg.md"
    p.write_text(text)
    return p, hashlib.sha256(p.read_bytes()).hexdigest()


def _status(con, hid: str) -> tuple:
    return con.execute("SELECT status, decision FROM hypothesis_status WHERE hypothesis_id = ?", [hid]).fetchone()


def test_full_lifecycle_through_allowed_transitions(paths, tmp_path):
    prereg, sha = _prereg(tmp_path)
    with ResultsStore(*paths) as store:
        con = store.con
        _run(con, "val-1", sha=sha)
        add(con, "N-1", "event", "New idea", "Something is true.", NOW, "explored on research data")
        move(con, "N-1", "candidate", "worth a test", NOW)
        move(con, "N-1", "preregistered", "rules written", NOW, prereg=prereg)
        move(con, "N-1", "validated", "lift held", NOW, decision="PASS", run_id="val-1", prereg=prereg)
        assert move(con, "N-1", "forward", "tracked daily", NOW) == 5
        move(con, "N-1", "expired", "stopped working", NOW)
        assert _status(con, "N-1") == ("expired", "PASS")       # the decision stays visible after later moves
        hist = con.execute("SELECT seq, status, prereg_sha FROM hypothesis_transitions WHERE hypothesis_id = 'N-1' "
                           "ORDER BY seq").fetchall()
    assert [h[1] for h in hist] == ["research", "candidate", "preregistered", "validated", "forward", "expired"]
    assert hist[2][2] == sha and [h[0] for h in hist] == [1, 2, 3, 4, 5, 6]


@pytest.mark.parametrize("start, to", [("research", "validated"), ("research", "preregistered"),
                                       ("rejected", "candidate"), ("failed", "forward"), ("monitoring", "validated")])
def test_transitions_outside_the_table_are_refused(paths, start, to):
    with ResultsStore(*paths) as store:
        con = store.con
        add(con, "N-1", "event", "t", "s", NOW, "r", status="monitoring" if start == "monitoring" else "research")
        if start in ("rejected", "failed"):
            con.execute("INSERT INTO hypothesis_transitions VALUES ('N-1', 2, ?, NULL, 'r', NULL, NULL, NULL, NULL, ?)",
                        [start, NOW])
        with pytest.raises(RegistryError, match="allowed next states"):
            move(con, "N-1", to, "try", NOW, decision=registry.DECISION_FOR.get(to))
        assert con.execute("SELECT count(*) FROM hypothesis_transitions WHERE hypothesis_id = 'N-1'").fetchone()[0] \
            == (2 if start in ("rejected", "failed") else 1)


def test_decisions_need_a_clean_valid_run_and_the_same_preregistration(paths, tmp_path):
    prereg, sha = _prereg(tmp_path)
    with ResultsStore(*paths) as store:
        con = store.con
        _run(con, "val-ok", sha=sha)
        _run(con, "val-other", sha="0" * 64)
        _run(con, "val-invalid", status="invalid", sha=sha)
        _run(con, "res-1", period="research", sha=sha)
        add(con, "N-1", "event", "t", "s", NOW, "r")
        move(con, "N-1", "candidate", "c", NOW)
        move(con, "N-1", "preregistered", "p", NOW, prereg=prereg)
        cases = [({}, "needs --decision PASS"),
                 ({"decision": "PASS"}, "needs the deciding run"),
                 ({"decision": "PASS", "run_id": "val-ok"}, "needs the deciding run"),
                 ({"decision": "PASS", "run_id": "nope", "prereg": prereg}, "No run nope"),
                 ({"decision": "PASS", "run_id": "val-invalid", "prereg": prereg}, "needs a valid run"),
                 ({"decision": "PASS", "run_id": "res-1", "prereg": prereg}, "research period"),
                 ({"decision": "PASS", "run_id": "val-other", "prereg": prereg}, "hash .* differs")]
        for kwargs, message in cases:
            with pytest.raises(RegistryError, match=message):
                move(con, "N-1", "validated", "v", NOW, **kwargs)
        with pytest.raises(RegistryError, match="needs --decision FAIL"):
            move(con, "N-1", "failed", "f", NOW, decision="PASS", run_id="val-ok", prereg=prereg)
        assert _status(con, "N-1") == ("preregistered", None)
        prereg.write_text("rules, edited after the run")              # an edited pre-registration is refused
        with pytest.raises(RegistryError, match="differs"):
            move(con, "N-1", "validated", "v", NOW, decision="PASS", run_id="val-ok", prereg=prereg)


def test_add_rules(paths):
    with ResultsStore(*paths) as store:
        con = store.con
        with pytest.raises(RegistryError, match="Unknown family"):
            add(con, "N-1", "astrology", "t", "s", NOW, "r")
        with pytest.raises(RegistryError, match="starts as"):
            add(con, "N-1", "event", "t", "s", NOW, "r", status="validated")
        with pytest.raises(RegistryError, match="already exists"):
            add(con, "P3-C1", "event", "t", "s", NOW, "r")
        with pytest.raises(RegistryError, match="required"):
            add(con, "N-2", "event", "t", " ", NOW, "r")


def test_history_is_append_only_in_code():
    src = Path(registry.__file__).parent
    for name in ("registry.py", "registry_cli.py", "registry_seed.py"):
        text = (src / name).read_text().upper()
        assert "UPDATE " not in text and "DELETE " not in text and "INSERT OR REPLACE" not in text, name


def test_seed_follows_the_transition_rules():
    ids = {h[0] for h in SEED_HYPOTHESES}
    assert len(ids) == len(SEED_HYPOTHESES) == 15
    for hid in ids:
        rows = sorted((t for t in SEED_TRANSITIONS if t[0] == hid), key=lambda t: t[1])
        assert [t[1] for t in rows] == list(range(1, len(rows) + 1)), hid
        prev = None
        for t in rows:
            assert t[2] in TRANSITIONS[prev], (hid, prev, t[2])
            assert t[3] == registry.DECISION_FOR.get(t[2]), (hid, t[2], t[3])
            if t[3]:
                assert t[5] and t[6] and len(t[7]) == 64, hid           # decision: run and full prereg hash
            prev = t[2]


def test_seed_is_idempotent_and_never_overwrites_later_transitions(paths, tmp_path):
    prereg, _ = _prereg(tmp_path)
    with ResultsStore(*paths) as store:
        move(store.con, "P5-E1", "preregistered", "rules for BREAKOUT", NOW, prereg=prereg)
        n = store.con.execute("SELECT count(*) FROM hypothesis_transitions").fetchone()[0]
    with ResultsStore(*paths) as store:
        assert store.con.execute("SELECT count(*) FROM hypothesis_transitions").fetchone()[0] == n
        assert _status(store.con, "P5-E1") == ("preregistered", None)
        assert store.con.execute("SELECT count(*) FROM hypotheses").fetchone()[0] == 15


def test_old_decision_table_becomes_a_view_with_the_same_rows(paths):
    results, research = paths
    con = duckdb.connect(str(results))
    con.execute(SCHEMA)
    con.execute("""CREATE TABLE validation_decisions (pattern VARCHAR PRIMARY KEY, version VARCHAR NOT NULL,
                   decision VARCHAR NOT NULL, reason VARCHAR, prereg_sha VARCHAR NOT NULL)""")
    con.executemany("INSERT INTO validation_decisions VALUES (?, ?, ?, ?, ?)", OLD_DECISIONS)
    con.close()
    with ResultsStore(results, research) as store:
        rows = store.con.execute("SELECT * FROM validation_decisions ORDER BY pattern").fetchall()
        kind = store.con.execute("SELECT count(*) FROM duckdb_views() WHERE view_name = 'validation_decisions'"
                                 ).fetchone()[0]
    assert rows == OLD_DECISIONS and kind == 1


def test_a_decision_table_the_registry_cannot_reproduce_is_kept(paths):
    results, research = paths
    con = duckdb.connect(str(results))
    con.execute(SCHEMA)
    con.execute("""CREATE TABLE validation_decisions (pattern VARCHAR PRIMARY KEY, version VARCHAR NOT NULL,
                   decision VARCHAR NOT NULL, reason VARCHAR, prereg_sha VARCHAR NOT NULL)""")
    con.execute("INSERT INTO validation_decisions VALUES ('momentum10_d10', '5905e5b3', 'PASS', 'edited', 'x')")
    con.close()
    with pytest.raises(RegistryError, match="not migrated"):
        ResultsStore(results, research)
    con = duckdb.connect(str(results), read_only=True)
    assert con.execute("SELECT count(*) FROM validation_decisions").fetchone()[0] == 1   # still a table, intact
    con.close()


def test_cli_list_show_and_refusal(paths, monkeypatch, capsys):
    from quant_research import cli
    results, research = paths
    monkeypatch.setattr(cli, "_store", lambda: ResultsStore(results, research))
    assert cli.main(["registry", "list", "--status", "failed"]) == 0
    out = capsys.readouterr().out
    assert "P4b-G2" in out and "P3-C3" not in out and "failed 5" in out
    assert cli.main(["registry", "show", "P3-C3"]) == 0
    assert "4. 2026-10-04 validated PASS: avoid signal" in capsys.readouterr().out
    assert cli.main(["registry", "move", "P4-X1", "--to", "candidate", "--reason", "again"]) == 2
    assert "final state" in capsys.readouterr().err
    assert cli.main(["registry", "show", "NOPE"]) == 1
