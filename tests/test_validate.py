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


def _two_recent_sessions_with_peers(con, n: int = 10):
    """Copies of one VOS row as n stocks traded on the last two VNINDEX sessions."""
    d1, d2 = [r[0] for r in con.execute("""SELECT DISTINCT date FROM quotes_daily WHERE symbol = 'VNINDEX'
                                           ORDER BY date DESC LIMIT 2""").fetchall()][::-1]
    for i in range(n):
        for d in (d1, d2):
            con.execute("""INSERT INTO quotes_daily SELECT * REPLACE (? AS symbol, ?::DATE AS date)
                           FROM quotes_daily WHERE symbol = 'VOS' AND total_volume > 0 LIMIT 1""", [f"PEER{i}", d])
    return d1, d2


def test_error_checks_are_clean_on_normal_data(wh):
    _two_recent_sessions_with_peers(wh.connection)
    results = results_by_name(wh.connection)
    assert {r.check.name: r.count for r in results.values() if r.check.severity == "error"} == {
        "latest_session_incomplete": 0, "recent_missing_required_fields": 0, "recent_nonpositive_prices": 0,
        "recent_corrupt_source_dates": 0}


def test_error_checks_detect_a_broken_latest_session(wh):
    con = wh.connection
    _, d2 = _two_recent_sessions_with_peers(con)
    con.execute("UPDATE quotes_daily SET total_volume = 0 WHERE symbol IN ('PEER0', 'PEER1', 'PEER2') AND date = ?", [d2])
    con.execute("UPDATE quotes_daily SET price_close = 0 WHERE symbol = 'PEER5' AND date = ?", [d2])
    con.execute("UPDATE quotes_daily SET deal_volume = total_volume + 1000 WHERE symbol LIKE 'PEER%' AND date = ?", [d2])
    results = results_by_name(con)
    assert results["latest_session_incomplete"].count == 1            # 7 of 10 traded: below 80%
    assert results["recent_nonpositive_prices"].count == 1
    assert results["recent_corrupt_source_dates"].count == 1
    report = render_validation_report(list(results.values()), {"quotes_daily": 50}, NOW)
    assert "## latest_session_incomplete (error, 1)" in report


def test_accepted_findings_are_reported_but_not_counted(wh):
    con = wh.connection
    _, d2 = _two_recent_sessions_with_peers(con)
    con.execute("UPDATE quotes_daily SET price_close = 0 WHERE symbol = 'PEER5' AND date = ?", [d2])
    accepted = {"recent_nonpositive_prices": {str(d2): "test: investigated"}}
    r = {x.check.name: x for x in run_checks(con, accepted=accepted)}["recent_nonpositive_prices"]
    assert (r.count, r.accepted) == (0, 1)
    report = render_validation_report([r], {"quotes_daily": 50}, NOW)
    assert "(+1 accepted)" in report


def test_accepted_list_has_reasons():
    from fireant_crawler.validate.accepted import ACCEPTED
    names = {c.name for c in CHECKS if c.severity == "error"}
    for check, entries in ACCEPTED.items():
        assert check in names and all(len(reason) > 20 for reason in entries.values())


@pytest.mark.parametrize("column", ["price_open", "price_high", "price_low", "price_close", "price_basic",
                                    "total_volume", "deal_volume", "putthrough_volume"])
def test_missing_required_fields_are_errors(wh, column):
    """A NULL makes `x <= 0` or `abs(...) > 0.5` NULL, not TRUE: missing data needs its own check."""
    con = wh.connection
    _, d2 = _two_recent_sessions_with_peers(con)
    con.execute(f"UPDATE quotes_daily SET {column} = NULL WHERE symbol = 'PEER3' AND date = ?", [d2])
    results = results_by_name(con)
    assert results["recent_missing_required_fields"].count == 1, column
    assert results["recent_nonpositive_prices"].count == 0 and results["recent_corrupt_source_dates"].count == 0


def test_missing_fields_on_no_trade_rows_only_require_close_basic_and_volume(wh):
    con = wh.connection
    _, d2 = _two_recent_sessions_with_peers(con)
    con.execute("""UPDATE quotes_daily SET total_volume = 0, deal_volume = NULL, price_open = NULL
                   WHERE symbol = 'PEER4' AND date = ?""", [d2])            # a no-trade row: not required
    assert results_by_name(con)["recent_missing_required_fields"].count == 0
