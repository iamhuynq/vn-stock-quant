import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from fireant_crawler.normalize.corporate_actions import normalize_corporate_actions
from fireant_crawler.normalize.quotes import adj_ratio_segments, last_traded_date, normalize_quotes
from fireant_crawler.normalize.reference import normalize_fundamental, normalize_icb, normalize_symbol
from fireant_crawler.normalize.report_marks import normalize_report_marks
from fireant_crawler.normalize.values import NormalizationError, parse_vn_number

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 3, tzinfo=UTC)


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("text", "expected"),
    [("1.100", 1100.0), ("1.538,7", 1538.7), ("-23,3", -23.3), ("+8,4", 8.4), ("26.224,8", 26224.8),
     ("1e+05", 100000.0), ("900", 900.0), ("", None), (None, None)],
)
def test_parse_vn_number(text, expected):
    assert parse_vn_number(text) == expected


def test_parse_vn_number_rejects_garbage():
    with pytest.raises(NormalizationError):
        parse_vn_number("abc")


def test_quotes_fixtures_map_all_fields():
    rows = load("quotes_vos_2026_07.json") + load("quotes_vos_2026_08.json")
    quotes = normalize_quotes("vos", rows, NOW)
    assert len(quotes) == 40
    assert quotes[0]["date"] == date(2026, 7, 8) and quotes[-1]["date"] == date(2026, 9, 4)
    last = quotes[-1]
    assert last["symbol"] == "VOS"
    assert (last["price_close"], last["price_basic"], last["total_volume"]) == (11.25, 11.15, 422000.0)
    assert last["sell_foreign_quantity"] == 34700.0 and last["adj_ratio"] == 1.0769230769
    assert all(v is not None for k, v in last.items())


def test_quotes_deduplicate_dates_and_reject_schema_changes():
    row = load("quotes_vos_2026_08.json")[0]
    assert len(normalize_quotes("VOS", [row, dict(row, priceClose=99.0)], NOW)) == 1
    assert normalize_quotes("VOS", [row, dict(row, priceClose=99.0)], NOW)[0]["price_close"] == 99.0
    with pytest.raises(NormalizationError, match="unknown quote fields"):
        normalize_quotes("VOS", [dict(row, newField=1)], NOW)
    with pytest.raises(NormalizationError, match="belongs to"):
        normalize_quotes("HPG", [row], NOW)


def test_adj_ratio_segments_match_vos_corporate_actions():
    quotes = normalize_quotes("VOS", load("quotes_vos_adj_points.json"), NOW)
    segments = adj_ratio_segments(quotes, NOW)
    starts = [(s["start_date"], round(s["adj_ratio"], 4)) for s in segments]
    assert starts[1:] == [(date(2011, 5, 16), 1.157), (date(2025, 9, 18), 1.0769), (date(2026, 10, 1), 1.0)]
    assert segments[-1]["end_date"] == date(2026, 10, 2)


def test_last_traded_date_skips_zero_volume_filler():
    flc = normalize_quotes("FLC", load("quotes_flc_tail.json"), NOW)
    assert all(r["total_volume"] == 0 for r in flc)
    assert last_traded_date(flc) is None
    vos = normalize_quotes("VOS", load("quotes_vos_2026_08.json"), NOW)
    assert last_traded_date(vos) == date(2026, 9, 4)


def test_index_quotes_normalize():
    rows = normalize_quotes("VNINDEX", load("quotes_vnindex_sample.json"), NOW)
    assert len(rows) == 10 and rows[-1]["price_close"] == 1737.71


def test_corporate_actions_field_mapping_and_title_parsing():
    actions = {a["event_id"]: a for a in normalize_corporate_actions(load("events_sample.json"), NOW)}
    vos = actions[64605]
    assert vos["ex_date"] == date(2026, 10, 1)
    assert vos["record_date"] == date(2026, 10, 2)
    assert vos["payment_date"] == date(2026, 10, 26)
    assert (vos["period_year"], vos["installment"], vos["cash_per_share_vnd"]) == (2025, 1, 900.0)
    assert vos["event_type_name"] == "cash_dividend" and vos["title_parsed"]

    by_type = {}
    for a in actions.values():
        by_type.setdefault(a["event_type"], []).append(a)
    stock = next(a for a in by_type[2] if a["ratio_held"] and a["ratio_received"])
    assert stock["title_parsed"] and stock["period_year"]
    rights = next(a for a in by_type[3] if a["issue_price_vnd"])
    assert rights["ratio_held"] and rights["ratio_received"]
    assert all(a["title_parsed"] for a in actions.values())
    assert any(a["payment_date"] is None for a in actions.values())


def test_report_marks_parse_c_json_fixture():
    marks = normalize_report_marks("VOS", load("timescale_marks_vos.json"), NOW)
    assert len(marks) == 38
    by_id = {m["mark_id"]: m for m in marks}
    q2_2019 = by_id["F_2019_2"]
    assert (q2_2019["period_type"], q2_2019["fiscal_year"], q2_2019["fiscal_quarter"]) == ("Q", 2019, 2)
    assert (q2_2019["revenue_bn"], q2_2019["revenue_yoy_pct"]) == (414.5, 8.4)
    assert (q2_2019["profit_bn"], q2_2019["profit_yoy_pct"]) == (-23.3, -3.9)
    assert by_id["F_2024_2"]["profit_yoy_pct"] == 26224.8
    assert by_id["F_2019_0"]["period_type"] == "Y" and by_id["F_2019_0"]["revenue_bn"] == 1538.7
    assert by_id["E_64605"]["label"] == "D" and by_id["E_64605"]["release_date"] == date(2026, 10, 1)
    assert all(m["title_parsed"] for m in marks)
    for m in marks:
        if m["label"] == "F":
            year, period = m["mark_id"].split("_")[1:]
            assert m["fiscal_year"] == int(year)
            assert (m["fiscal_quarter"] or 0) == int(period)


def test_report_marks_without_yoy():
    rows = [{"id": "F_2008_1", "label": "F", "date": "2008-04-30T00:00:00", "title": "BCTC quý 1/2008|DT: 300,1 tỷ|LN: -5 tỷ"}]
    mark = normalize_report_marks("VOS", rows, NOW)[0]
    assert (mark["revenue_bn"], mark["revenue_yoy_pct"], mark["profit_bn"]) == (300.1, None, -5.0)
    assert mark["title_parsed"]


def test_report_marks_missing_revenue_and_corporate_action_labels():
    rows = [
        {"id": "F_2016_2", "label": "F", "date": "2016-07-30T00:00:00",
         "title": "BCTC quý 2/2016|DT:  tỷ|LN: 283,4 tỷ, -16,2% (vs. Q2/15)"},
        {"id": "E_1", "label": "I", "date": "2025-12-08T00:00:00",
         "title": "Phát hành CP cho CĐHH, tỷ lệ 5:1, giá 15000đ/CP|Ngày KHQ: 08/12/2025"},
        {"id": "E_2", "label": "S", "date": "2024-06-01T00:00:00", "title": "Cổ tức năm 2023 bằng cổ phiếu, tỷ lệ 100:15"},
        {"id": "X_1", "label": "Z", "date": "2024-06-01T00:00:00", "title": "unknown"},
    ]
    marks = {m["mark_id"]: m for m in normalize_report_marks("SSI", rows, NOW)}
    assert marks["F_2016_2"]["title_parsed"] and marks["F_2016_2"]["revenue_bn"] is None
    assert marks["F_2016_2"]["profit_bn"] == 283.4
    assert marks["E_1"]["title_parsed"] and marks["E_2"]["title_parsed"]
    assert not marks["X_1"]["title_parsed"]


def test_reference_normalizers():
    flc = normalize_symbol(load("symbol_flc.json"), NOW, source="symbol")
    assert (flc["symbol"], flc["is_listing"], flc["exchange"], flc["icb_code"]) == ("FLC", False, "OTC", "35101015")
    fundamental = normalize_fundamental("VOS", load("fundamental_vos.json"), NOW)
    assert fundamental["shares_outstanding"] == 140_000_000 and fundamental["low_52w_vnd"] == 9285.71
    icb = normalize_icb(load("icb_sample.json"), NOW)
    assert icb[0]["industry_code"] == "10" and icb[0]["level"] == 1
