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


def test_industry_strength_v2_applies_validity_and_coverage_per_window():
    """Each 5/21/63-session window: NULL with an invalid return (<= -1) or under 80% valid sessions; else the
    cumulative relative return exp(sum(log_rel)) - 1."""
    from datetime import date, timedelta
    import duckdb
    import numpy as np
    from stock_ui.cross_data import _industry_momentum
    con = duckdb.connect()
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(70)]
    rng = np.random.default_rng(1)
    rows = []
    for code in ("A", "B", "C"):
        for i, d in enumerate(days):
            k = len(days) - i                                              # 1 = latest session
            lr = float(rng.normal(0, 0.01))
            invalid = code == "B" and k == 3                               # inside every window
            if code == "C" and 6 <= k <= 15:
                lr = None                                                  # 10 of 21 missing: only the 5d window ok
            rows.append((d, "l2", code, 0.001, None if invalid else lr, invalid, 10))
    con.execute("CREATE TABLE group_returns_daily (date DATE, level VARCHAR, group_code VARCHAR, ew_cc DOUBLE, "
                "log_rel DOUBLE, rel_invalid BOOLEAN, n_members INTEGER)")
    con.executemany("INSERT INTO group_returns_daily VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    con.execute("CREATE TABLE group_names AS SELECT * FROM (VALUES ('l2', 'A', 'Alpha'), ('l2', 'B', 'Beta'), "
                "('l2', 'C', 'Gamma')) t(level, group_code, name)")
    out = _industry_momentum(con, days[-1]).set_index("industry")
    a = [r for r in rows if r[2] == "A"]
    for k, col in ((5, "ret_5d"), (21, "ret_21d"), (63, "ret_63d")):
        want = np.expm1(sum(r[4] for r in a[-k:]))
        assert abs(out.loc["Alpha", col] - want) < 1e-12, col
        assert np.isnan(out.loc["Beta", col]), col                       # invalid return in the window
    assert not np.isnan(out.loc["Gamma", "ret_5d"]) and np.isnan(out.loc["Gamma", "ret_21d"])


def test_industry_strength_v2_coverage_is_at_least_80_percent_rounded_up():
    """16/21 and 50/63 valid sessions are below 80% and give NULL; 17/21 and 51/63 give a value."""
    from datetime import date, timedelta
    import duckdb
    import numpy as np
    from stock_ui.cross_data import _industry_momentum
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(70)]
    missing = {"D16": range(17, 22), "E17": range(18, 22),                 # k = 1 is the latest session
               "F50": range(51, 64), "G51": range(52, 64)}
    rows = []
    for code, gaps in missing.items():
        for i, d in enumerate(days):
            k = len(days) - i
            rows.append((d, "l2", code, 0.001, None if k in gaps else 0.001, False, 10))
    con = duckdb.connect()
    con.execute("CREATE TABLE group_returns_daily (date DATE, level VARCHAR, group_code VARCHAR, ew_cc DOUBLE, "
                "log_rel DOUBLE, rel_invalid BOOLEAN, n_members INTEGER)")
    con.executemany("INSERT INTO group_returns_daily VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    con.execute("CREATE TABLE group_names AS SELECT 'l2' AS level, c AS group_code, c AS name "
                "FROM (VALUES ('D16'), ('E17'), ('F50'), ('G51')) t(c)")
    out = _industry_momentum(con, days[-1]).set_index("industry")
    assert np.isnan(out.loc["D16", "ret_21d"]) and not np.isnan(out.loc["E17", "ret_21d"])
    assert np.isnan(out.loc["F50", "ret_63d"]) and not np.isnan(out.loc["G51", "ret_63d"])
    assert not np.isnan(out.loc["F50", "ret_21d"])                         # its 21-session window is complete
