"""Warehouse tests run against a real DuckDB file (no mocks)."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from fireant_crawler.normalize.corporate_actions import normalize_corporate_actions
from fireant_crawler.normalize.quotes import adj_ratio_segments, normalize_quotes
from fireant_crawler.normalize.report_marks import normalize_report_marks
from fireant_crawler.store.warehouse import Warehouse

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 3, tzinfo=UTC)


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def wh(tmp_path):
    with Warehouse(tmp_path / "warehouse.duckdb") as warehouse:
        warehouse.init_schema()
        yield warehouse


def test_init_schema_is_idempotent(wh):
    wh.init_schema()
    assert wh.count("quotes_daily") == 0


def test_quote_upsert_is_idempotent_and_replaces(wh):
    quotes = normalize_quotes("VOS", load("quotes_vos_2026_07.json") + load("quotes_vos_2026_08.json"), NOW)
    assert wh.upsert("quotes_daily", quotes) == 40
    wh.upsert("quotes_daily", quotes)
    assert wh.count("quotes_daily") == 40

    changed = dict(quotes[-1], price_close=12.0)
    wh.upsert("quotes_daily", [changed])
    close = wh.connection.execute(
        "SELECT price_close FROM quotes_daily WHERE symbol = 'VOS' AND date = DATE '2026-09-04'"
    ).fetchone()[0]
    assert close == 12.0 and wh.count("quotes_daily") == 40


def test_upsert_dedupes_within_batch_and_rejects_unknown_columns(wh):
    quote = normalize_quotes("VOS", load("quotes_vos_2026_08.json"), NOW)[0]
    assert wh.upsert("quotes_daily", [quote, dict(quote, price_close=1.0)]) == 1
    with pytest.raises(ValueError, match="unknown columns"):
        wh.upsert("quotes_daily", [dict(quote, bogus=1)])
    with pytest.raises(ValueError, match="Unknown table"):
        wh.upsert("quotes_daily; DROP TABLE symbols", [quote])


def test_adjusted_view_and_trading_span(wh):
    quotes = normalize_quotes("VOS", load("quotes_vos_adj_points.json"), NOW)
    wh.upsert("quotes_daily", quotes)
    wh.upsert("adj_ratio_segments", adj_ratio_segments(quotes, NOW))
    adj_close, raw_close = wh.connection.execute(
        "SELECT a.adj_close, q.price_close FROM quotes_daily_adjusted a JOIN quotes_daily q USING (symbol, date) "
        "WHERE symbol = 'VOS' AND date = DATE '2026-09-30'"
    ).fetchone()
    assert raw_close == 12.6 and adj_close == pytest.approx(11.7)
    span = wh.connection.execute("SELECT last_traded_date FROM symbol_trading_span WHERE symbol = 'VOS'").fetchone()[0]
    assert span == date(2026, 10, 2)
    assert wh.count("adj_ratio_segments") == 4


def test_corporate_actions_and_marks_round_trip(wh):
    wh.upsert("corporate_actions", normalize_corporate_actions(load("events_sample.json"), NOW))
    ex_date, cash = wh.connection.execute(
        "SELECT ex_date, cash_per_share_vnd FROM corporate_actions WHERE event_id = 64605"
    ).fetchone()
    assert (ex_date, cash) == (date(2026, 10, 1), 900.0)
    wh.upsert("report_marks", normalize_report_marks("VOS", load("timescale_marks_vos.json"), NOW))
    assert wh.count("report_marks") == 38


def test_symbol_industry_view_hierarchy_and_fund_flag(wh):
    icb = [("50", 1, "Công nghiệp"), ("5020", 2, "SP & DV công nghiệp"), ("502060", 3, "Vận tải công nghiệp"),
           ("50206030", 4, "Vận tải biển"), ("30", 1, "Tài chính")]
    wh.upsert("icb_industries", [{"industry_code": c, "level": lv, "name": n, "description": None, "fetched_at": NOW}
                                 for c, lv, n in icb])
    symbols = [("VOS", "CTCP Vận tải Biển Việt Nam", "50206030"), ("FUEVN100", "Quỹ ETF VINACAPITALVN100", "30205000"),
               ("FUEMITEC", "Quỹ ETF VINACAPITAL VNMITECH", None), ("VBT", "CTCP Vận tải Bảo Thắng", "00000000"),
               ("AAN", "CTCP Lương thực A An", None)]
    wh.upsert("symbols", [{"symbol": s, "fetched_at": NOW, "name": n, "exchange": "HSX", "type": "stock",
                           "is_listing": True, "industry_code": None, "icb_code": code, "source": "search"}
                          for s, n, code in symbols])
    rows = {r[0]: r[1:] for r in wh.connection.execute(
        "SELECT symbol, is_fund, icb_code, industry_l1, industry_l3, industry_l4 FROM symbol_industry").fetchall()}
    assert rows["VOS"] == (False, "50206030", "Công nghiệp", "Vận tải công nghiệp", "Vận tải biển")
    assert rows["FUEVN100"][0] and rows["FUEMITEC"][0]
    assert rows["VBT"] == (False, None, None, None, None)
    assert rows["AAN"] == (False, None, None, None, None)  # is_fund must be false, not NULL
