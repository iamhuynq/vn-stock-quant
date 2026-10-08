"""Validator and export tests on a real DuckDB built from fixtures."""

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pytest

from fireant_crawler.normalize.corporate_actions import normalize_corporate_actions
from fireant_crawler.normalize.quotes import normalize_quotes
from fireant_crawler.normalize.report_marks import normalize_report_marks
from fireant_crawler.store.warehouse import Warehouse
from fireant_crawler.validate.checks import CHECKS, render_validation_report, run_checks
from fireant_crawler.validate.export import EXPORTS, export_parquet

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 3, tzinfo=UTC)


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def wh(tmp_path):
    with Warehouse(tmp_path / "w.duckdb") as warehouse:
        warehouse.init_schema()
        warehouse.upsert("quotes_daily", normalize_quotes("VOS", load("quotes_vos_2026_07.json") + load("quotes_vos_2026_08.json"), NOW))
        warehouse.upsert("quotes_daily", normalize_quotes("VNINDEX", load("quotes_vnindex_sample.json"), NOW))
        warehouse.upsert("corporate_actions", normalize_corporate_actions(load("events_sample.json"), NOW))
        warehouse.upsert("report_marks", normalize_report_marks("VOS", load("timescale_marks_vos.json"), NOW))
        yield warehouse


def results_by_name(con):
    return {r.check.name: r for r in run_checks(con)}


def test_clean_fixture_has_no_errors(wh):
    results = results_by_name(wh.connection)
    assert set(results) == {c.name for c in CHECKS}
    assert results["ohlc_consistency"].count == 0
    assert results["adj_change_without_event"].count == 0
    assert results["vwap_identity"].count == 0
    assert results["reference_price_rule"].count == 0
    assert results["marks_unparsed"].count == 0


def test_checks_detect_injected_problems(wh):
    con = wh.connection
    con.execute("UPDATE quotes_daily SET price_low = price_high + 1 WHERE symbol = 'VOS' AND date = DATE '2026-08-05'")
    con.execute("UPDATE quotes_daily SET adj_ratio = 2.0 WHERE symbol = 'VOS' AND date >= DATE '2026-09-01'")
    con.execute("UPDATE quotes_daily SET deal_volume = total_volume + 1000 WHERE symbol = 'VOS' AND date = DATE '2026-08-06'")
    results = results_by_name(con)
    assert results["ohlc_consistency"].count == 1
    assert results["adj_change_without_event"].count == 1
    assert results["volume_split"].count == 1
    report = render_validation_report(list(results.values()), {"quotes_daily": 50}, NOW)
    assert "## ohlc_consistency (warn, 1)" in report


def test_export_parquet_round_trip(wh, tmp_path):
    written = export_parquet(wh.connection, tmp_path / "parquet")
    assert set(written) == set(EXPORTS)
    assert written["quotes_daily"] == 50
    rows = duckdb.sql(f"SELECT count(*) FROM read_parquet('{(tmp_path / 'parquet' / 'report_marks.parquet').as_posix()}')").fetchone()[0]
    assert rows == 38
