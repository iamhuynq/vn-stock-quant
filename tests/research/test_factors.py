"""Factor Engine f1: raw definitions, normalization, universe, point in time, consumers, describe report."""

from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from fireant_crawler.store.warehouse import Warehouse
from quant_research import factor_report
from quant_research.build import build
from quant_research.factors import FACTORS, NORMALIZE_SQL, FactorParams, version
from tests.research.synthetic import build_synthetic_warehouse

NOW = datetime(2026, 10, 9, 20, 0, tzinfo=UTC)
SMALL = FactorParams(min_adv_value=0, min_session_index=0, min_stocks=1, min_industry=2)   # 3 synthetic stocks


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp("factors")
    build_synthetic_warehouse(d / "w.duckdb")
    build(d / "w.duckdb", d / "r.duckdb", NOW, SMALL)
    return d


def _df(path: Path, sql: str, params: list | None = None) -> pd.DataFrame:
    con = duckdb.connect(str(path), read_only=True)
    try:
        return con.execute(sql, params or []).df()
    finally:
        con.close()


def _raw(built: Path, factor: str) -> pd.Series:
    df = _df(built / "r.duckdb", "SELECT symbol, date, value FROM stock_factors WHERE factor = ?", [factor])
    return df.set_index(["symbol", "date"])["value"].sort_index()


def _reference(built: Path) -> pd.DataFrame:
    """Raw f1 values computed with pandas from the panel, features and market tables."""
    r = built / "r.duckdb"
    panel = _df(r, "SELECT * FROM daily_panel ORDER BY symbol, date")
    feats = _df(r, "SELECT * FROM stock_features ORDER BY symbol, date")
    mkt = _df(r, "SELECT date, mkt_ret_1d FROM market_daily").set_index("date")["mkt_ret_1d"]
    out = []
    for sym, g in panel.groupby("symbol"):
        g = g.reset_index(drop=True)
        f = feats[feats["symbol"] == sym].reset_index(drop=True)
        jumps = g["price_jump"].fillna(False).astype(int)              # SQL sum() skips NULL
        prev = g["adj_close"].shift(1)
        clean = (g["is_traded"] & ~g["price_jump"] & ~g["bad_source_date"] & g["is_traded"].shift(1)
                 & (prev > 0)).fillna(False).astype(bool)              # NULL in SQL boolean logic: not clean
        ret = (g["adj_close"] / prev - 1).where(clean)
        m = g["date"].map(mkt)
        beta = []
        for i in range(len(g)):
            lo = max(0, i - 249)
            pair = pd.DataFrame({"r": ret[lo:i + 1], "m": m[lo:i + 1]}).dropna()
            beta.append(np.cov(pair["r"], pair["m"], ddof=0)[0, 1] / pair["m"].var(ddof=0) if len(pair) >= 200 else np.nan)
        oi = f["order_imbalance"]
        flow = oi.rolling(5, min_periods=1).mean().where(oi.rolling(5, min_periods=1).count() >= 3)
        bad_foreign = g["foreign_inconsistent"].fillna(False).astype(int).rolling(20, min_periods=1).sum()
        out.append(pd.DataFrame({
            "symbol": sym, "date": g["date"],
            "liquidity": np.log(f["adv_value_20"].where(f["adv_value_20"] > 0)),
            "momentum_12_1": (g["adj_close"].shift(21) / g["adj_close"].shift(250) - 1)
                .where(jumps.rolling(251, min_periods=1).sum() == 0),
            "momentum_1m": f["return_20d"].where(jumps.rolling(21, min_periods=1).sum() == 0),
            "reversal_1w": (-f["return_5d"]).where(jumps.rolling(6, min_periods=1).sum() == 0),
            "volatility": f["volatility_20"], "beta": beta, "order_flow": flow,
            "foreign_flow": f["foreign_net_ratio_20"].where(bad_foreign == 0),
            "volume_surge": f["volume_ratio_20"],
            "in_universe": (f["is_traded"] & ~f["price_jump"] & ~f["bad_source_date"] & (f["adv_value_20"] > 0)
                            & (f["session_index"] > 0)).fillna(False).astype(bool),
        }))
    return pd.concat(out)


def test_raw_factors_equal_a_pandas_reference(built):
    ref = _reference(built)
    ref = ref[ref["in_universe"]].set_index(["symbol", "date"])
    for factor in FACTORS:
        got = _raw(built, factor)
        want = ref[factor].replace([np.inf, -np.inf], np.nan).dropna().sort_index()
        assert len(got) > 0, factor
        assert got.index.equals(want.index), factor
        np.testing.assert_allclose(got.to_numpy(), want.to_numpy(), rtol=1e-9, atol=1e-12, err_msg=factor)


def test_normalization_equals_pandas(tmp_path):
    rng = np.random.default_rng(7)
    rows = []
    for d, n in ((date(2024, 1, 2), 60), (date(2024, 1, 3), 45), (date(2024, 1, 4), 5)):   # last date: too few
        for i in range(n):
            ind = "tiny" if i < 2 else f"I{i % 4}"
            for factor in ("a", "b"):
                v = float(rng.standard_t(3)) if factor == "a" else float(rng.integers(0, 4))     # b: many ties
                rows.append((f"S{i:03d}", d, ind if i != 5 else None, factor, v))
    raw = pd.DataFrame(rows, columns=["symbol", "date", "industry", "factor", "value"])
    con = duckdb.connect()
    con.execute("CREATE TABLE factor_raw AS SELECT * FROM raw")
    con.execute(NORMALIZE_SQL.format(winsor=0.01, min_stocks=30, min_industry=3))
    got = con.execute("SELECT * FROM stock_factors ORDER BY date, factor, symbol").df()
    con.close()
    want = []
    for (d, factor), g in raw.groupby(["date", "factor"]):
        if len(g) < 30:
            continue
        g = g.copy()
        lo, hi = np.quantile(g["value"], [0.01, 0.99])
        g["winsorized"] = g["value"].clip(lo, hi)
        g["rank_pct"] = (g["value"].rank(method="min") - 1) / (len(g) - 1)
        g["z"] = (g["winsorized"] - g["winsorized"].mean()) / g["winsorized"].std(ddof=0)
        g["bucket"] = 1 + np.minimum(4, np.floor(g["rank_pct"] * 5)).astype(int)
        size = g.groupby("industry")["z"].transform("count")
        g["z_industry"] = (g["z"] - g.groupby("industry")["z"].transform("mean")).where(
            g["industry"].notna() & (size >= 3))
        want.append(g)
    want = pd.concat(want).sort_values(["date", "factor", "symbol"]).reset_index(drop=True)
    assert set(got["date"]) == {date(2024, 1, 2), date(2024, 1, 3)} or set(pd.to_datetime(got["date"]).dt.date) == \
        {date(2024, 1, 2), date(2024, 1, 3)}
    for col in ("winsorized", "rank_pct", "z", "z_industry"):
        np.testing.assert_allclose(got[col].to_numpy(dtype=float), want[col].to_numpy(dtype=float), rtol=1e-9,
                                   atol=1e-12, err_msg=col)
    assert (got["bucket"].to_numpy() == want["bucket"].to_numpy()).all()
    assert got[got["industry"] == "tiny"]["z_industry"].isna().all()


def test_universe_and_minimum_stocks(built, tmp_path):
    scored = _df(built / "r.duckdb", """SELECT s.* FROM stock_factors s JOIN stock_features f USING (symbol, date)
        WHERE NOT (f.is_traded AND NOT f.price_jump AND NOT f.bad_source_date)""")
    assert scored.empty                                                   # nothing outside the universe
    per_date = _df(built / "r.duckdb", "SELECT date, factor, count(*) AS n FROM stock_factors GROUP BY ALL")
    assert per_date["n"].min() >= SMALL.min_stocks
    build(built / "w.duckdb", tmp_path / "r.duckdb", NOW)                  # default: 30 stocks per date
    assert _df(tmp_path / "r.duckdb", "SELECT count(*) AS n FROM stock_factors")["n"][0] == 0
    defs = _df(tmp_path / "r.duckdb", "SELECT factor, factor_set, version FROM factor_definitions")
    assert set(defs["factor"]) == set(FACTORS) and set(defs["version"]) == {version()}


def test_factors_are_point_in_time(built, tmp_path):
    cut = date(2023, 9, 1)
    wh = tmp_path / "w.duckdb"
    wh.write_bytes((built / "w.duckdb").read_bytes())
    with Warehouse(wh) as w:
        w.connection.execute("""UPDATE quotes_daily SET price_close = price_close * 1.3, price_high = price_high * 1.3,
                                deal_volume = deal_volume * 2 WHERE date > ? AND symbol <> 'VNINDEX'""", [cut])
    build(wh, tmp_path / "r.duckdb", NOW, SMALL)
    sql = "SELECT * FROM stock_factors WHERE date {} ? ORDER BY date, factor, symbol"
    before = _df(built / "r.duckdb", sql.format("<="), [cut])
    after = _df(tmp_path / "r.duckdb", sql.format("<="), [cut])
    pd.testing.assert_frame_equal(before, after)
    assert len(before) > 0
    later_a = _df(built / "r.duckdb", sql.format(">"), [cut])
    later_b = _df(tmp_path / "r.duckdb", sql.format(">"), [cut])
    assert not later_a.equals(later_b)                                      # the perturbation did bite


def test_exposure_reads_the_shared_scores(built):
    from stock_ui.exposure_data import _factor_z
    con = duckdb.connect(str(built / "r.duckdb"), read_only=True)
    try:
        fz = _factor_z(con)
        latest = con.execute("""SELECT symbol, factor, z FROM stock_factors
                                WHERE date = (SELECT max(date) FROM stock_factors)""").df()
    finally:
        con.close()
    for _, row in latest.iterrows():
        assert fz["z"].loc[row["symbol"], row["factor"]] == pytest.approx(row["z"], nan_ok=True)
    assert set(fz["beta_250"].index) <= set(latest["symbol"])


def test_describe_report_uses_no_returns_and_writes_nothing(built):
    src = Path(factor_report.__file__).read_text()
    assert "fwd_" not in src and "stock_targets" not in src and "feature_target" not in src
    before = sorted(p.name for p in built.iterdir())
    build_id, text = factor_report.render(built / "r.duckdb")
    assert sorted(p.name for p in built.iterdir()) == before                # no results.duckdb, no log
    assert build_id == NOW.strftime("%Y%m%dT%H%M%S")
    assert "## Rank persistence" in text and "### Regime: all" in text and "fwd_" not in text
    for factor in FACTORS:
        assert f"`{factor}`" in text
