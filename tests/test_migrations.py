"""Schema guard, migrate command and read-only commands, on real DuckDB files."""

import hashlib
from datetime import UTC, datetime

import duckdb
import pytest

from fireant_crawler.cli import main
from fireant_crawler.store.warehouse import SchemaOutOfDateError, Warehouse

NOW = datetime(2026, 10, 3, tzinfo=UTC)


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "no.env"))
    monkeypatch.delenv("FIREANT_TOKEN", raising=False)
    return tmp_path


def make_warehouse(path):
    with Warehouse(path) as wh:
        wh.ensure_schema_for_write()
        wh.upsert("icb_industries", [{"industry_code": "50", "level": 1, "name": "X", "description": None, "fetched_at": NOW}])


def test_empty_warehouse_is_bootstrapped_and_up_to_date(tmp_path):
    make_warehouse(tmp_path / "w.duckdb")
    with Warehouse(tmp_path / "w.duckdb", read_only=True) as wh:
        assert wh.pending_schema_changes() == []


def test_view_changes_block_writes_until_migrated(tmp_path):
    path = tmp_path / "w.duckdb"
    make_warehouse(path)
    with Warehouse(path) as wh:
        wh.connection.execute("DROP VIEW symbol_industry")
        wh.connection.execute("CREATE OR REPLACE VIEW symbols_latest AS SELECT 1 AS x")
        kinds = {(c.kind, c.name) for c in wh.pending_schema_changes()}
        assert kinds == {("create_view", "symbol_industry"), ("replace_view", "symbols_latest")}
        with pytest.raises(SchemaOutOfDateError):
            wh.ensure_schema_for_write()
        wh.init_schema()
        assert wh.pending_schema_changes() == []
        assert wh.count("icb_industries") == 1


def test_table_drift_is_reported_and_never_applied(tmp_path):
    path = tmp_path / "w.duckdb"
    make_warehouse(path)
    with Warehouse(path) as wh:
        wh.connection.execute("ALTER TABLE icb_industries ADD COLUMN extra INTEGER")
        changes = wh.pending_schema_changes()
        assert [(c.kind, c.name, c.auto_applicable) for c in changes] == [("table_drift", "icb_industries", False)]
        wh.init_schema()
        assert [c.kind for c in wh.pending_schema_changes()] == ["table_drift"]
        assert wh.count("icb_industries") == 1


def test_read_only_warehouse_cannot_write(tmp_path):
    path = tmp_path / "w.duckdb"
    make_warehouse(path)
    with Warehouse(path, read_only=True) as wh, pytest.raises(duckdb.Error):
        wh.connection.execute("DELETE FROM icb_industries")


def test_status_validate_export_and_dry_run_do_not_modify_warehouse(data_dir, capsys):
    path = data_dir / "warehouse.duckdb"
    make_warehouse(path)
    with Warehouse(path) as wh:
        wh.connection.execute("DROP VIEW symbol_industry")
    before = file_hash(path)

    assert main(["status"]) == 0
    assert main(["migrate", "--dry-run"]) == 0
    assert main(["validate"]) == 4      # refuses: views it reads are out of date
    assert main(["export"]) == 4
    assert file_hash(path) == before
    captured = capsys.readouterr()
    assert "1 pending change(s)" in captured.out and "create_view      symbol_industry" in captured.out
    assert "Dry run" in captured.out and "Refusing to run" in captured.err

    assert main(["migrate"]) == 0
    migrated = file_hash(path)
    assert main(["status"]) == 0 and main(["validate"]) == 0 and main(["export"]) == 0
    assert file_hash(path) == migrated


def test_normalize_refuses_when_schema_out_of_date_then_migrate_fixes(data_dir, capsys):
    path = data_dir / "warehouse.duckdb"
    make_warehouse(path)
    with Warehouse(path) as wh:
        wh.connection.execute("DROP VIEW symbol_industry")

    assert main(["normalize"]) == 4
    assert "Refusing to run" in capsys.readouterr().err
    assert main(["migrate"]) == 0
    assert main(["normalize"]) == 0
    with Warehouse(path, read_only=True) as wh:
        assert wh.pending_schema_changes() == []
