"""Feature engine tests: real DuckDB build on a synthetic warehouse, checked against an independent
pure-Python reference, plus leakage, filtering and safety tests."""

import math
import re
from datetime import UTC, datetime
from importlib import resources

import duckdb
import pytest

from fireant_crawler.store.warehouse import Warehouse
from quant_research.build import BuildError, build, file_hash
from tests.research import reference
from tests.research.synthetic import (DELISTED_LAST_TRADE, EX_DATE_INDEX, LIMIT_UP_INDEX, ZERO_PRICE_INDEX,
                                      build_synthetic_warehouse, calendar)

BUILT_AT = datetime(2026, 10, 4, 18, 0, tzinfo=UTC)
FEATURES = ("return_1d", "return_3d", "return_5d", "return_10d", "return_20d", "excess_return_5d",
            "volume_ratio_5", "volume_ratio_20", "volume_change", "volume_zscore_20", "volatility_5", "volatility_20",
            "atr_14_pct", "high_low_range", "gap", "close_position", "close_vs_avg_price", "order_imbalance",
            "volume_imbalance", "buy_pressure", "sell_pressure", "buy_sell_ratio", "foreign_net_value",
            "foreign_net_3d", "foreign_net_5d", "foreign_net_20d", "foreign_net_ratio_20", "foreign_intensity",
            "adv_value_20", "market_regime")
TARGETS = ("fwd_ret_close_1d", "fwd_ret_close_3d", "fwd_ret_close_5d", "fwd_ret_close_10d", "fwd_ret_exec_3d",
           "fwd_ret_exec_5d", "fwd_ret_exec_10d", "fwd_ret_exec_20d", "fwd_excess_exec_5d", "fwd_excess_exec_10d",
           "fwd_excess_exec_20d", "fwd_max_return_5d", "fwd_max_drawdown_5d", "y_up3_5d")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("fe")
    wh_path, rs_path = tmp / "warehouse.duckdb", tmp / "research.duckdb"
    build_synthetic_warehouse(wh_path)
    result = build(wh_path, rs_path, BUILT_AT)
    return wh_path, rs_path, result


def rows_by_key(con, table, columns):
    cur = con.execute(f"SELECT symbol, date, {', '.join(columns)} FROM {table}")
    return {(r[0], r[1]): dict(zip(columns, r[2:])) for r in cur.fetchall()}


def reference_data(wh_path):
    con = duckdb.connect(str(wh_path), read_only=True)
    cur = con.execute("SELECT * FROM quotes_daily")
    cols = [d[0] for d in cur.description]
    quotes = [dict(zip(cols, r)) for r in cur.fetchall()]
    symbols = {s: {"is_fund": f} for s, f in con.execute("SELECT symbol, is_fund FROM symbol_industry").fetchall()}
    symbols["VNINDEX"] = {"is_fund": False}
    con.close()
    panel = reference.build_panel(quotes, symbols)
    mkt = reference.market(quotes)
    return panel, reference.features(panel, mkt), reference.targets(panel, mkt)


def assert_same(actual, expected, columns, label):
    assert set(actual) == set(expected), f"{label}: row keys differ"
    mismatches = []
    for key, exp in expected.items():
        for col in columns:
            a, e = actual[key][col], exp[col]
            if a is None or e is None or isinstance(e, (str, bool)):
                ok = a == e
            else:
                ok = math.isclose(a, e, rel_tol=1e-9, abs_tol=1e-9)
            if not ok:
                mismatches.append((key, col, a, e))
    assert not mismatches, f"{label}: {len(mismatches)} mismatches, first: {mismatches[:3]}"


def test_features_match_reference(built):
    wh_path, rs_path, _ = built
    _, ref_features, _ = reference_data(wh_path)
    with duckdb.connect(str(rs_path), read_only=True) as con:
        actual = rows_by_key(con, "stock_features", FEATURES)
    assert_same(actual, ref_features, FEATURES, "features")


def test_targets_match_reference(built):
    wh_path, rs_path, _ = built
    _, _, ref_targets = reference_data(wh_path)
    with duckdb.connect(str(rs_path), read_only=True) as con:
        actual = rows_by_key(con, "stock_targets", TARGETS)
    assert_same(actual, ref_targets, TARGETS, "targets")


def test_market_regime_is_populated_after_200_sessions(built):
    _, rs_path, _ = built
    with duckdb.connect(str(rs_path), read_only=True) as con:
        regimes = dict(con.execute("SELECT market_regime IS NULL, count(*) FROM market_daily GROUP BY 1").fetchall())
    assert regimes[True] == 199 and regimes[False] == len(calendar()) - 199


def test_panel_filters_funds_filler_and_zero_prices(built):
    _, rs_path, _ = built
    days = calendar()
    with duckdb.connect(str(rs_path), read_only=True) as con:
        symbols = {r[0] for r in con.execute("SELECT DISTINCT symbol FROM daily_panel").fetchall()}
        del_last = con.execute("SELECT max(date) FROM daily_panel WHERE symbol = 'DEL'").fetchone()[0]
        zero_row = con.execute("SELECT count(*) FROM daily_panel WHERE symbol = 'STK' AND date = ?",
                               [days[ZERO_PRICE_INDEX]]).fetchone()[0]
    assert symbols == {"STK", "UPC", "DEL"}
    assert del_last == days[DELISTED_LAST_TRADE]
    assert zero_row == 0


def test_dividend_ex_date_is_not_a_fake_drop(built):
    _, rs_path, _ = built
    days = calendar()
    with duckdb.connect(str(rs_path), read_only=True) as con:
        ret = con.execute("SELECT return_1d FROM stock_features WHERE symbol = 'STK' AND date = ?",
                          [days[EX_DATE_INDEX]]).fetchone()[0]
    assert abs(ret) < 0.035  # raw price dropped ~7.4%; adjusted move stays inside the +-3% simulation band


def test_limit_flags_and_blocked_entry(built):
    _, rs_path, _ = built
    days = calendar()
    with duckdb.connect(str(rs_path), read_only=True) as con:
        limit_up = con.execute("SELECT limit_up FROM stock_features WHERE symbol = 'STK' AND date = ?",
                               [days[LIMIT_UP_INDEX]]).fetchone()[0]
        blocked = con.execute("SELECT entry_blocked FROM stock_targets WHERE symbol = 'STK' AND date = ?",
                              [days[LIMIT_UP_INDEX]]).fetchone()[0]
        share = con.execute("SELECT avg(limit_up::INT) FROM stock_features WHERE symbol = 'STK'").fetchone()[0]
    assert limit_up is True and blocked is True and share < 0.05


def test_no_infinite_values(built):
    _, rs_path, _ = built
    with duckdb.connect(str(rs_path), read_only=True) as con:
        numeric = [c for c in FEATURES if c != "market_regime"]
        n = con.execute("SELECT " + " + ".join(f"count(*) FILTER (WHERE isinf({c}))" for c in numeric)
                        + " FROM stock_features").fetchone()[0]
    assert n == 0


def test_build_records_metadata_and_leaves_warehouse_unchanged(built):
    wh_path, rs_path, result = built
    with duckdb.connect(str(rs_path), read_only=True) as con:
        row = con.execute("SELECT feature_set_version, code_hash, feature_rows FROM feature_builds").fetchone()
    assert row == ("v2", result.code_hash, result.rows["stock_features"])
    before = file_hash(wh_path)
    build(wh_path, rs_path.parent / "second.duckdb", BUILT_AT)
    assert file_hash(wh_path) == before


def test_feature_sql_never_looks_forward_and_target_sql_never_back():
    folder = resources.files("quant_research").joinpath("sql")
    features_sql = folder.joinpath("03_stock_features.sql").read_text().upper()
    targets_sql = folder.joinpath("04_stock_targets.sql").read_text().upper()
    code = lambda sql: "\n".join(line.split("--")[0] for line in sql.splitlines())
    assert not re.search(r"\bLEAD\s*\(|FOLLOWING", code(features_sql))
    assert not re.search(r"\bLAG\s*\(|PRECEDING", code(targets_sql))


def test_perturbing_the_future_does_not_change_past_features(tmp_path):
    wh_path = tmp_path / "warehouse.duckdb"
    build_synthetic_warehouse(wh_path)
    build(wh_path, tmp_path / "a.duckdb", BUILT_AT)
    cutoff = calendar()[180]
    with Warehouse(wh_path) as wh:
        wh.connection.execute("""UPDATE quotes_daily SET price_open = price_open * 1.3, price_high = price_high * 1.3,
            price_low = price_low * 1.3, price_close = price_close * 1.3, total_value = total_value * 5,
            buy_quantity = buy_quantity * 2, buy_foreign_value = buy_foreign_value + 1e9
            WHERE date > ? AND price_close > 0""", [cutoff])
    build(wh_path, tmp_path / "b.duckdb", BUILT_AT)

    cols = [c for c in FEATURES]
    with duckdb.connect(str(tmp_path / "a.duckdb"), read_only=True) as a, \
         duckdb.connect(str(tmp_path / "b.duckdb"), read_only=True) as b:
        past_a = {k: v for k, v in rows_by_key(a, "stock_features", cols).items() if k[1] <= cutoff}
        past_b = {k: v for k, v in rows_by_key(b, "stock_features", cols).items() if k[1] <= cutoff}
        tgt_a = rows_by_key(a, "stock_targets", ["fwd_ret_close_5d"])
        tgt_b = rows_by_key(b, "stock_targets", ["fwd_ret_close_5d"])
    assert past_a == past_b
    changed = [k for k in tgt_a if k[1] <= cutoff and k[0] == "STK" and tgt_a[k] != tgt_b[k]]
    assert changed, "targets that look past the cutoff must change"


def test_build_refuses_outdated_warehouse_schema(tmp_path):
    wh_path = tmp_path / "warehouse.duckdb"
    build_synthetic_warehouse(wh_path)
    with Warehouse(wh_path) as wh:
        wh.connection.execute("DROP VIEW symbol_industry")
    with pytest.raises(BuildError, match="schema is out of date"):
        build(wh_path, tmp_path / "r.duckdb", BUILT_AT)


def test_price_jump_is_flagged_on_the_day_and_in_targets_looking_at_it(built):
    from tests.research.synthetic import JUMP_INDEX
    _, rs_path, _ = built
    days = calendar()
    with duckdb.connect(str(rs_path), read_only=True) as con:
        flagged = [r[0] for r in con.execute(
            "SELECT date FROM stock_features WHERE symbol = 'UPC' AND price_jump ORDER BY date").fetchall()]
        ahead = dict(con.execute("SELECT date, fwd_has_price_jump_20d FROM stock_targets WHERE symbol = 'UPC'").fetchall())
    assert flagged == [days[JUMP_INDEX]]
    assert ahead[days[JUMP_INDEX - 1]] and ahead[days[JUMP_INDEX - 20]]
    assert not ahead[days[JUMP_INDEX]] and not ahead[days[JUMP_INDEX - 21]]


def test_rebuild_replaces_file_atomically_and_keeps_history(tmp_path):
    wh_path, rs_path = tmp_path / "warehouse.duckdb", tmp_path / "research.duckdb"
    build_synthetic_warehouse(wh_path)
    build(wh_path, rs_path, BUILT_AT)
    size = rs_path.stat().st_size
    build(wh_path, rs_path, datetime(2026, 10, 5, tzinfo=UTC))
    with duckdb.connect(str(rs_path), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM feature_builds").fetchone()[0] == 2
    assert rs_path.stat().st_size <= size * 1.2          # no growth from replaced tables
    assert not list(tmp_path.glob("*.building.duckdb*"))

    with Warehouse(wh_path) as wh:                        # a failing build must keep the old file
        wh.connection.execute("DROP VIEW symbol_industry")
    with pytest.raises(BuildError):
        build(wh_path, rs_path, datetime(2026, 10, 6, tzinfo=UTC))
    with duckdb.connect(str(rs_path), read_only=True) as con:
        assert con.execute("SELECT count(*) FROM feature_builds").fetchone()[0] == 2


def test_periods_freeze_the_holdout_and_label_forward_data(tmp_path):
    from datetime import date
    wh, rs = tmp_path / "w.duckdb", tmp_path / "r.duckdb"
    build_synthetic_warehouse(wh, start=date(2026, 1, 5))           # 300 sessions -> crosses 2026-10-03
    build(wh, rs, BUILT_AT)
    with duckdb.connect(str(rs), read_only=True) as con:
        spans = {p: (lo, hi) for p, lo, hi in con.execute(
            "SELECT period, min(date), max(date) FROM daily_panel GROUP BY 1").fetchall()}
        crossing = con.execute("""SELECT count(*) FROM stock_targets
            WHERE date BETWEEN DATE '2026-09-01' AND DATE '2026-10-02' AND crosses_period""").fetchone()[0]
    assert spans["holdout"] == (date(2026, 1, 5), date(2026, 10, 2))
    assert spans["forward"][0] == date(2026, 10, 5)                  # first weekday after 2026-10-02
    assert crossing > 0                                              # holdout targets reaching into forward
    from quant_research.results import check_period
    check_period("forward", final=False)                             # forward needs no --final
