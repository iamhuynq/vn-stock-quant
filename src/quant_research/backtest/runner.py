"""Run a strategy with benchmarks and a random control; store everything in results.duckdb."""

import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime

import numpy as np

from quant_research.backtest.data import Market, UniverseRule, load_market
from quant_research.backtest.engine import Result, Strategy, random_selector, run, signal_selector
from quant_research.backtest.metrics import curve_metrics, equal_weight_curve, strategy_metrics
from quant_research.results import ResearchParams, ResultsStore, check_period
from quant_research.stats import mean_test

PERIOD_RANGES = {
    "research": (date(2000, 1, 1), date(2023, 12, 31)),
    "validation": (date(2024, 1, 1), date(2025, 12, 31)),
    "holdout": (date(2026, 1, 1), date(2026, 10, 2)),
    "forward": (date(2026, 10, 3), date(2099, 12, 31)),
}
N_RANDOM = 20
TEST_LAG = 10

SCHEMA = """
CREATE TABLE IF NOT EXISTS backtest_metrics (
    run_id VARCHAR NOT NULL, series VARCHAR NOT NULL, metric VARCHAR NOT NULL, value DOUBLE,
    PRIMARY KEY (run_id, series, metric));
CREATE TABLE IF NOT EXISTS backtest_daily (
    run_id VARCHAR NOT NULL, date DATE NOT NULL, equity DOUBLE, cash DOUBLE, invested DOUBLE,
    n_positions INTEGER, equal_weight DOUBLE, vnindex DOUBLE, random_median DOUBLE, PRIMARY KEY (run_id, date));
CREATE TABLE IF NOT EXISTS backtest_trades (
    run_id VARCHAR NOT NULL, symbol VARCHAR NOT NULL, entry_date DATE NOT NULL, exit_date DATE,
    entry_price DOUBLE, exit_price DOUBLE, shares DOUBLE, gross_pnl DOUBLE, costs DOUBLE,
    renewals INTEGER, exit_reason VARCHAR);
"""


def _market(store: ResultsStore, period: str, rule: UniverseRule) -> Market:
    cache = store.__dict__.setdefault("_market_cache", {})
    key = (period, rule)
    if key not in cache:
        start, end = PERIOD_RANGES[period]
        cache[key] = load_market(store.con, start, end, rule)
    return cache[key]


def _active_window(m: Market) -> slice:
    """From the first session with a signal to the end (no trading is possible before signals exist)."""
    has = np.flatnonzero((~np.isnan(m.signal)).any(axis=1))
    return slice(int(has[0]) if len(has) else 0, len(m.dates))


def _slice(m: Market, w: slice) -> Market:
    arrays = {k: v[w] for k, v in m.__dict__.items() if isinstance(v, np.ndarray) and k != "symbols"}
    return Market(symbols=m.symbols, **arrays)


def run_backtest(store: ResultsStore, label: str, strategy: Strategy, period: str, now: datetime,
                 rule: UniverseRule = UniverseRule(), final: bool = False, extra: dict | None = None,
                 n_random: int = N_RANDOM) -> str:
    check_period(period, final)
    store.con.execute(SCHEMA)
    market = _slice(_market(store, period, rule), _active_window(_market(store, period, rule)))
    run_id = f"{now:%Y%m%dT%H%M%S}-backtest-{label}-{period}"
    params = ResearchParams(extra={"strategy": asdict(strategy), "universe": asdict(rule), **(extra or {})})
    version = hashlib.sha256(json.dumps([asdict(strategy), asdict(rule)], sort_keys=True).encode()).hexdigest()[:8]
    store.start_run(run_id, "backtest", period, params, now, (label, version))

    res = run(market, strategy, signal_selector)
    randoms = [run(market, strategy, random_selector(seed)) for seed in range(n_random)]
    initial = strategy.initial_equity
    ew = equal_weight_curve(market.close, market.universe, initial)
    vn = initial * market.index_close / market.index_close[0]
    rnd = np.array([r.equity for r in randoms])

    rows = [(run_id, "strategy", k, v) for k, v in strategy_metrics(res, initial).items()]
    rows += [(run_id, name, k, v) for name, curve in (("equal_weight", ew), ("vnindex", vn))
             for k, v in curve_metrics(curve).items()]
    rnd_metrics = [strategy_metrics(r, initial) for r in randoms]
    for k in rnd_metrics[0]:
        vals = np.array([x[k] for x in rnd_metrics], dtype=float)
        if not np.isfinite(vals).any():          # e.g. profit factor undefined in every random run
            continue
        rows += [(run_id, "random_median", k, float(np.nanmedian(vals))),
                 (run_id, "random_p05", k, float(np.nanpercentile(vals, 5))),
                 (run_id, "random_p95", k, float(np.nanpercentile(vals, 95)))]
    rank = float((rnd[:, -1] < res.equity[-1]).mean())
    excess = np.diff(np.log(res.equity)) - np.diff(np.log(ew))
    _, t, p, lo, hi = mean_test(excess, TEST_LAG)
    rows += [(run_id, "test", "share_of_random_runs_beaten", rank),
             (run_id, "test", "excess_vs_equal_weight_daily_log_mean", float(excess.mean())),
             (run_id, "test", "excess_vs_equal_weight_t", t), (run_id, "test", "excess_vs_equal_weight_p", p)]
    rows += _regime_rows(run_id, market, res.equity, ew)
    rows += _year_rows(run_id, market, res.equity, ew, vn)
    store.con.executemany("INSERT INTO backtest_metrics VALUES (?, ?, ?, ?)",
                          [(a, b, c, None if d is None or not np.isfinite(d) else float(d)) for a, b, c, d in rows])
    store.log_hypothesis(run_id, "excess_vs_equal_weight", period, p, now)
    _store_series(store, run_id, market, res, ew, vn, np.median(rnd, axis=0))
    return run_id


def _regime_rows(run_id: str, m: Market, eq: np.ndarray, ew: np.ndarray) -> list:
    out = []
    r, b = np.diff(np.log(eq)), np.diff(np.log(ew))
    for regime in ("Bull", "Sideway", "Bear"):
        mask = m.regime[1:] == regime
        if mask.any():
            out += [(run_id, f"regime={regime}", "strategy_annual_log_return", float(r[mask].mean() * 250)),
                    (run_id, f"regime={regime}", "equal_weight_annual_log_return", float(b[mask].mean() * 250)),
                    (run_id, f"regime={regime}", "sessions", float(mask.sum()))]
    return out


def _year_rows(run_id: str, m: Market, eq: np.ndarray, ew: np.ndarray, vn: np.ndarray) -> list:
    years = m.dates.astype("datetime64[Y]").astype(int) + 1970
    out = []
    for y in np.unique(years):
        idx = np.flatnonzero(years == y)
        start = max(idx[0] - 1, 0)
        for name, curve in (("strategy", eq), ("equal_weight", ew), ("vnindex", vn)):
            out.append((run_id, f"year={y}", f"{name}_return", float(curve[idx[-1]] / curve[start] - 1)))
    return out


def _store_series(store: ResultsStore, run_id: str, m: Market, res: Result, ew, vn, rnd_med) -> None:
    import pyarrow as pa
    daily = pa.table({"run_id": [run_id] * len(m.dates), "date": m.dates, "equity": res.equity, "cash": res.cash,
                      "invested": res.invested, "n_positions": res.n_positions.astype(np.int32),
                      "equal_weight": ew, "vnindex": vn, "random_median": rnd_med})
    trades = pa.table({
        "run_id": [run_id] * len(res.trades), "symbol": [t.symbol for t in res.trades],
        "entry_date": m.dates[np.array([t.entry_index for t in res.trades], dtype=int)],
        "exit_date": m.dates[np.array([t.exit_index for t in res.trades], dtype=int)],
        "entry_price": [t.entry_price for t in res.trades], "exit_price": [t.exit_price for t in res.trades],
        "shares": [t.shares for t in res.trades], "gross_pnl": [t.gross_pnl for t in res.trades],
        "costs": [t.costs for t in res.trades], "renewals": pa.array([t.renewals for t in res.trades], pa.int32()),
        "exit_reason": [t.exit_reason for t in res.trades]})
    for name, table in (("backtest_daily", daily), ("backtest_trades", trades)):
        store.con.register("_bt", table)
        store.con.execute(f"INSERT INTO {name} SELECT * FROM _bt")
        store.con.unregister("_bt")
