"""Market watch helpers: watchlist parsing and storage, co-movement groups, warnings table."""

from datetime import UTC, datetime

import pandas as pd

from stock_ui import watch_data, watchlist


def test_parse_keeps_order_drops_duplicates_and_unknown():
    valid, rejected = watchlist.parse("fpt, VCB  vcb\nHPG;x; TOO-LONG-SYMBOL", known={"FPT", "VCB", "HPG", "X"})
    assert valid == ["FPT", "VCB", "HPG"] and rejected == ["X", "TOO-LONG-SYMBOL"]


def test_save_and_load_roundtrip(tmp_path):
    watchlist.save(tmp_path, ["FPT", "VCB"], datetime(2026, 10, 8, tzinfo=UTC))
    assert watchlist.load(tmp_path) == ["FPT", "VCB"]
    watchlist.path(tmp_path).write_text("{broken")
    assert watchlist.load(tmp_path) == []


def test_groups_are_connected_components_above_the_threshold():
    pairs = pd.DataFrame({"a": ["A", "B", "C", "E"], "b": ["B", "C", "D", "F"], "corr": [0.7, 0.65, 0.2, 0.9]})
    assert watch_data.groups(pairs, 0.6) == [["A", "B", "C"], ["E", "F"]]


def test_warnings_table_counts_downside_flags_and_filters_liquidity():
    events = pd.DataFrame({
        "symbol": ["AAA", "AAA", "BBB", "CCC", "DDD"],
        "event_type": ["BREAKDOWN", "PRICE_DROP", "BREAKOUT", "BREAKDOWN", "BREAKDOWN"],
        "direction": ["down", "down", "up", "down", "down"], "event_score": [0.0] * 5,
        "adv_value_20": [5e9, 5e9, 5e9, 2e9, 1e8], "exchange_now": ["HSX"] * 5, "return_1d": [-0.06] * 5})
    hist = pd.DataFrame({"event_type": ["BREAKDOWN", "PRICE_DROP"], "mean": [-0.01, -0.02], "win_rate": [0.4, 0.4]})
    t = watch_data.warnings_table(events, hist, {"AAA": "Banks"}, liquid_only=True)
    assert t["symbol"].tolist() == ["AAA", "CCC"] and t["flags"].tolist() == [2, 1]
    assert t.loc[0, "hist_mean_10d"] == -0.015 and t.loc[0, "industry"] == "Banks"
    assert "DDD" in watch_data.warnings_table(events, hist, {}, liquid_only=False)["symbol"].tolist()
