"""The CLI refuses validation runs without a pre-registration file and records its hash."""

import hashlib
import json

import duckdb

from quant_research.cli import main
from tests.research.synthetic_research import build_research_db


def test_validation_requires_prereg_and_stores_its_hash(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "none.env"))
    build_research_db(tmp_path / "research.duckdb")

    assert main(["pattern", "--name", "drop3", "--period", "validation"]) == 2
    assert "requires --prereg" in capsys.readouterr().err
    assert main(["pattern", "--name", "drop3", "--period", "holdout", "--prereg", str(tmp_path / "missing.md")]) == 2

    prereg = tmp_path / "prereg.md"
    prereg.write_text("C1: drop3, lift < 0 at 10d", encoding="utf-8")
    # drop3 uses return_1d, present in the synthetic research DB
    assert main(["pattern", "--name", "drop3", "--period", "validation", "--prereg", str(prereg)]) == 0
    with duckdb.connect(str(tmp_path / "results.duckdb"), read_only=True) as con:
        params = json.loads(con.execute("SELECT params FROM research_runs WHERE period = 'validation'").fetchone()[0])
    assert params["extra"]["sha256"] == hashlib.sha256(prereg.read_bytes()).hexdigest()
