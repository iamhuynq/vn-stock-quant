"""End to end: Phase 1 synthetic warehouse -> Phase 2 build -> Phase 6 backtest on real column names."""

from datetime import UTC, date, datetime

import duckdb
import numpy as np
import pytest

from quant_research.backtest.data import UniverseRule, load_market
from quant_research.backtest.engine import Strategy
from quant_research.backtest.report import render_backtest
from quant_research.backtest.runner import run_backtest
from quant_research.build import build, file_hash
from quant_research.results import HoldoutLockedError, ResultsStore
from tests.research.synthetic import build_synthetic_warehouse

NOW = datetime(2026, 10, 4, 21, 0, tzinfo=UTC)
# Only 3 synthetic stocks: ntile(10) yields deciles 1-3, so the "top decile" here is 3.
RELAXED = UniverseRule(min_adv_value=0, min_session_index=0, min_stocks_per_date=2, signal_decile=3)


@pytest.fixture
def research(tmp_path):
    warehouse, research = tmp_path / "warehouse.duckdb", tmp_path / "research.duckdb"
    build_synthetic_warehouse(warehouse)
    build(warehouse, research, NOW)
    return research


def test_load_market_is_point_in_time_and_aligned(research):
    con = duckdb.connect(":memory:")
    con.execute(f"ATTACH '{research.as_posix()}' AS rs (READ_ONLY)")
    m = load_market(con, date(2023, 1, 1), date(2023, 12, 31), RELAXED)
    assert list(m.symbols) == ["DEL", "STK", "UPC"]                  # no ETF, no index
    assert m.close.shape == (len(m.dates), 3) and m.regime is not None
    per_day = (~np.isnan(m.signal)).sum(axis=1)
    assert per_day.max() == 1 and (per_day == 1).mean() > 0.5         # exactly the top-ranked stock most days
    assert not m.universe[m.price_jump].any()                         # point-in-time filter drops jump days


def test_run_backtest_stores_everything_and_respects_gates(research, tmp_path):
    before = file_hash(research)
    with ResultsStore(tmp_path / "results.duckdb", research) as store:
        run_id = run_backtest(store, "t", Strategy(hold_sessions=5, max_positions=2, initial_equity=1e9),
                              "research", NOW, rule=RELAXED, n_random=2)
        n_daily = store.con.execute("SELECT count(*) FROM backtest_daily WHERE run_id = ?", [run_id]).fetchone()[0]
        n_trades = store.con.execute("SELECT count(*) FROM backtest_trades WHERE run_id = ?", [run_id]).fetchone()[0]
        logged = store.con.execute("SELECT count(*) FROM hypothesis_log WHERE run_id = ?", [run_id]).fetchone()[0]
        report = render_backtest(store.con, [run_id], NOW)
        with pytest.raises(HoldoutLockedError):
            run_backtest(store, "t", Strategy(), "holdout", NOW, rule=RELAXED, n_random=1)
    assert n_daily > 100 and n_trades > 5 and logged == 1
    assert "| t |" in report and "year" in report
    assert file_hash(research) == before
