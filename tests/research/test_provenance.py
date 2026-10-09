"""Reproducibility metadata: warehouse hash per build, provenance per run, report line."""

import json
import re
from datetime import UTC, datetime

import duckdb

from quant_research.build import build, file_hash
from quant_research.provenance import from_runs, git_info, line
from quant_research.results import ResearchParams, ResultsStore
from tests.research.synthetic import build_synthetic_warehouse

NOW = datetime(2026, 10, 8, 21, 0, tzinfo=UTC)


def test_build_records_the_warehouse_hash_and_keeps_old_history(tmp_path):
    wh, rs = tmp_path / "w.duckdb", tmp_path / "r.duckdb"
    build_synthetic_warehouse(wh)
    con = duckdb.connect(str(rs))                          # a research db from before the column existed
    con.execute("""CREATE TABLE feature_builds (build_id VARCHAR PRIMARY KEY, feature_set_version VARCHAR,
                   built_at TIMESTAMPTZ, data_as_of DATE, warehouse_fetched_at TIMESTAMPTZ, code_hash VARCHAR,
                   panel_rows BIGINT, feature_rows BIGINT, target_rows BIGINT, seconds DOUBLE)""")
    con.execute("INSERT INTO feature_builds VALUES ('old', 'v1', ?, NULL, NULL, 'x', 0, 0, 0, 1.0)", [NOW])
    con.close()
    build(wh, rs, NOW)
    con = duckdb.connect(str(rs), read_only=True)
    rows = dict(con.execute("SELECT build_id, warehouse_sha FROM feature_builds").fetchall())
    con.close()
    assert rows["old"] is None and rows[NOW.strftime("%Y%m%dT%H%M%S")] == file_hash(wh)


def test_every_run_stores_provenance_and_reports_show_it(tmp_path):
    wh, rs = tmp_path / "w.duckdb", tmp_path / "r.duckdb"
    build_synthetic_warehouse(wh)
    build(wh, rs, NOW)
    with ResultsStore(tmp_path / "results.duckdb", rs) as store:
        store.start_run("run-x", "pattern", "research", ResearchParams(), NOW, ("p", "v1"))
        params = json.loads(store.con.execute("SELECT params FROM research_runs").fetchone()[0])
        lines = from_runs(store.con, ["run-x"])
    p = params["provenance"]
    assert p["warehouse_sha"] == file_hash(wh) and p["feature_build_id"] == NOW.strftime("%Y%m%dT%H%M%S")
    assert len(p["config_hash"]) == 16 and len(p["code_hash"]) == 16
    sha, dirty = git_info()
    assert p["git_sha"] == sha and p["git_dirty"] == dirty
    assert sha == "unknown" or re.fullmatch(r"[0-9a-f]{40}", sha)
    assert len(lines) == 1 and file_hash(wh)[:12] in lines[0]


def test_line_flags_uncommitted_code():
    p = {"git_sha": "a" * 40, "git_dirty": True, "warehouse_sha": "b" * 64, "feature_build_id": "B",
         "code_hash": "c" * 16}
    text = line(p)
    assert "aaaaaaaaaa" in text and "uncommitted" in text and "bbbbbbbbbbbb" in text
