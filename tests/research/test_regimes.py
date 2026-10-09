"""Regime Engine: underlying values, tercile labels, risk rule, point in time."""

from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from fireant_crawler.store.warehouse import Warehouse
from quant_research.build import build
from quant_research.regimes import DIMENSIONS, TERCILE_DIMENSIONS, RegimeParams
from tests.research.synthetic import build_synthetic_warehouse

NOW = datetime(2026, 10, 9, 20, 0, tzinfo=UTC)
SMALL = RegimeParams(window=100, min_obs=50, breadth_min_adv=0)    # 300 synthetic sessions


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp("regimes")
    build_synthetic_warehouse(d / "w.duckdb")
    build(d / "w.duckdb", d / "r.duckdb", NOW, regime_params=SMALL)
    return d


def _df(path: Path, sql: str, params: list | None = None) -> pd.DataFrame:
    con = duckdb.connect(str(path), read_only=True)
    try:
        return con.execute(sql, params or []).df()
    finally:
        con.close()


def test_underlying_values_equal_pandas(built):
    r = built / "r.duckdb"
    reg = _df(r, "SELECT * FROM market_regimes ORDER BY date").set_index("date")
    panel = _df(r, "SELECT p.*, f.adv_value_20 FROM daily_panel p JOIN stock_features f USING (symbol, date)")
    mkt = _df(r, "SELECT date, mkt_close, mkt_vol_20 FROM market_daily ORDER BY date").set_index("date")
    ok = panel["is_traded"].fillna(False) & ~panel["bad_source_date"].fillna(True)
    turnover = panel[ok].groupby("date")["deal_value"].sum().reindex(mkt.index)
    fnet = (panel["buy_foreign_value"] - panel["sell_foreign_value"])
    foreign = fnet[ok & ~panel["foreign_inconsistent"].fillna(True)].groupby(panel["date"]).sum().reindex(mkt.index)
    panel = panel.sort_values(["symbol", "date"])
    ma = panel.groupby("symbol")["adj_close"].transform(lambda s: s.rolling(50, min_periods=50).mean())
    live = ok & ~panel["price_jump"].fillna(True) & (panel["adv_value_20"] > 0) & ma.notna()
    breadth = (panel["adj_close"] > ma)[live].astype(float).groupby(panel["date"]).mean().reindex(mkt.index)
    n20 = turnover.rolling(20, min_periods=1).count()
    liquidity = turnover.rolling(20, min_periods=1).mean().where(n20 >= 15)
    flow = (foreign.rolling(20, min_periods=1).sum() / turnover.rolling(20, min_periods=1).sum()).where(n20 >= 15)
    drawdown = mkt["mkt_close"] / mkt["mkt_close"].rolling(250, min_periods=1).max() - 1
    for col, want in (("volatility_value", mkt["mkt_vol_20"]), ("liquidity_value", liquidity),
                      ("breadth_value", breadth), ("foreign_value", flow), ("drawdown", drawdown)):
        got = reg[col].astype(float)
        assert got.notna().sum() > 50, col
        np.testing.assert_allclose(got.to_numpy(), want.astype(float).to_numpy(), rtol=1e-9, atol=1e-12,
                                   equal_nan=True, err_msg=col)


def test_tercile_labels_equal_a_rolling_percentile(built):
    reg = _df(built / "r.duckdb", "SELECT * FROM market_regimes ORDER BY date").reset_index(drop=True)
    for dim in TERCILE_DIMENSIONS:
        values = reg[f"{dim}_value"].astype(float).to_numpy()
        low, mid, high = DIMENSIONS[dim][0]
        want = []
        for i, v in enumerate(values):
            win = values[max(0, i - SMALL.window + 1):i + 1]
            win = win[~np.isnan(win)]
            if np.isnan(v) or len(win) < SMALL.min_obs:
                want.append(None)
                continue
            pct = (win <= v).mean()
            want.append(low if pct <= 1 / 3 else high if pct > 2 / 3 else mid)
        got = [None if pd.isna(x) else x for x in reg[dim]]
        assert got == want, dim
        assert {low, mid, high} <= set(filter(None, got)), dim                 # every state occurs
        assert all(x is None for x in got[:SMALL.min_obs - 1]), dim             # NULL before min_obs values


def test_risk_follows_the_declared_rule(built):
    reg = _df(built / "r.duckdb", "SELECT * FROM market_regimes ORDER BY date")
    for _, r in reg.iterrows():
        if pd.isna(r["volatility"]) or pd.isna(r["breadth"]) or pd.isna(r["direction"]):
            want = None
        elif (r["volatility"] == "high" and r["breadth"] == "weak") or r["drawdown"] <= -0.20:
            want = "risk_off"
        elif r["volatility"] != "high" and r["breadth"] == "strong" and r["direction"] == "Bull":
            want = "risk_on"
        else:
            want = "neutral"
        assert (None if pd.isna(r["risk"]) else r["risk"]) == want, r["date"]
    assert reg["risk"].notna().sum() > 0


def test_regimes_are_point_in_time(built, tmp_path):
    cut = date(2023, 11, 1)
    wh = tmp_path / "w.duckdb"
    wh.write_bytes((built / "w.duckdb").read_bytes())
    with Warehouse(wh) as w:
        w.connection.execute("""UPDATE quotes_daily SET price_close = price_close * 0.6, deal_volume = deal_volume * 5
                                WHERE date > ?""", [cut])
    build(wh, tmp_path / "r.duckdb", NOW, regime_params=SMALL)
    sql = "SELECT * FROM market_regimes WHERE date {} ? ORDER BY date"
    pd.testing.assert_frame_equal(_df(built / "r.duckdb", sql.format("<="), [cut]),
                                  _df(tmp_path / "r.duckdb", sql.format("<="), [cut]))
    assert not _df(built / "r.duckdb", sql.format(">"), [cut]).equals(_df(tmp_path / "r.duckdb", sql.format(">"), [cut]))
