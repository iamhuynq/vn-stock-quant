"""Group-level tests (Phase 4b, docs/group-analysis-plan.md): industry momentum and short-term reversal.

Both rank ICB level-2 industries by their past equal-weight excess return (index of cross.duckdb, up to
and including the ranking date) and measure the members' execution excess return afterwards (enter at
the next open). The logged quantity is long-only: selected tercile minus the average industry.
"""

from datetime import datetime

import numpy as np

from quant_research.results import ResearchParams, ResultsStore, check_period
from quant_research.stats import mean_test

MOMENTUM_LOOKBACKS = (21, 63)     # sessions: about 1 and 3 months
REVERSAL_LOOKBACK = 5
MIN_GROUP_MEMBERS = 5


def _index(store: ResultsStore) -> tuple[np.ndarray, list[str], np.ndarray]:
    df = store.con.execute("SELECT date, group_code, ew_cc FROM cx.group_returns_daily WHERE level = 'l2'").df()
    dates = np.array([r[0] for r in store.con.execute("SELECT DISTINCT date FROM cx.returns_daily ORDER BY 1")
                      .fetchall()], dtype="datetime64[D]")
    codes = sorted(df["group_code"].unique().tolist())
    df["date"] = df["date"].values.astype("datetime64[D]")
    wide = df.pivot(index="date", columns="group_code", values="ew_cc").reindex(index=dates, columns=codes)
    return dates, codes, wide.to_numpy(dtype=float)


def _past(dates: np.ndarray, ret: np.ndarray, day: np.datetime64, lookback: int) -> np.ndarray:
    """Sum of the last `lookback` session returns up to and including `day`; NaN below 80% coverage."""
    end = int(np.searchsorted(dates, day, side="right"))
    block = ret[max(0, end - lookback):end]
    ok = np.isfinite(block).sum(axis=0) >= 0.8 * lookback
    return np.where(ok, np.nansum(block, axis=0), np.nan)


def _outcomes(store: ResultsStore, params: ResearchParams, period: str, horizon: int, at_month_end: bool) -> dict:
    """{date: {group: mean member outcome}}; members of the month end (momentum) or of the month in force."""
    y = f"fwd_excess_exec_{horizon}d"
    member_month = ("SELECT month_end AS date, month_end FROM cx.month_ends" if at_month_end else
                    """SELECT d.date, m.month_end FROM (SELECT DISTINCT date FROM rs.feature_target WHERE period = ?) d
                       ASOF JOIN cx.month_ends m ON d.date > m.month_end""")
    binds = ([] if at_month_end else [period]) + [period, MIN_GROUP_MEMBERS]
    rows = store.con.execute(f"""
        WITH dm AS ({member_month})
        SELECT dm.date, gm.group_code, avg(f.{y}) AS y
        FROM dm JOIN cx.group_members_monthly gm ON gm.month_end = dm.month_end AND gm.level = 'l2'
        JOIN (SELECT symbol, date, {y} FROM rs.feature_target
              WHERE {params.universe_sql()} AND period = ? AND {y} IS NOT NULL) f
          ON f.symbol = gm.symbol AND f.date = dm.date
        GROUP BY 1, 2 HAVING count(*) >= ? ORDER BY 1""", binds).fetchall()
    out: dict = {}
    for day, code, val in rows:
        out.setdefault(np.datetime64(day, "D"), {})[code] = val
    return out


def _tercile_spread(dates, codes, ret, outcomes: dict, lookback: int, pick: str, sample_every: int = 1):
    """Per date: mean outcome of the top (or bottom) tercile by past return minus the mean of all groups."""
    series, chosen = [], []
    for k, day in enumerate(sorted(outcomes)):
        if k % sample_every:
            continue
        past = _past(dates, ret, day, lookback)
        col = {c: i for i, c in enumerate(codes)}
        groups = [(past[col[c]], c, v) for c, v in outcomes[day].items() if c in col and np.isfinite(past[col[c]])]
        if len(groups) < 6:
            continue
        groups.sort(key=lambda g: (g[0], g[1]))
        n = len(groups) // 3
        sel = groups[-n:] if pick == "top" else groups[:n]
        series.append(np.mean([v for _, _, v in sel]) - np.mean([v for _, _, v in groups]))
        chosen.append({c for _, c, _ in sel})
    turnover = [len(a - b) / max(len(a), 1) for a, b in zip(chosen[1:], chosen[:-1])]
    return np.array(series, dtype=float), float(np.mean(turnover)) if turnover else None


def run_group_momentum(store: ResultsStore, period: str, params: ResearchParams, now: datetime, record,
                       final: bool = False) -> str:
    check_period(period, final)
    run_id = f"{now:%Y%m%dT%H%M%S}-cross-group_momentum-{period}"
    store.start_run(run_id, "cross", period, params, now, ("group_momentum", "v1"))
    dates, codes, ret = _index(store)
    outcomes = _outcomes(store, params, period, 20, at_month_end=True)
    for lookback in MOMENTUM_LOOKBACKS:
        d, turnover = _tercile_spread(dates, codes, ret, outcomes, lookback, "top")
        se, t, p, _, _ = mean_test(d, 1)
        mean = float(d.mean()) if len(d) else None
        net = mean - turnover * params.cost_round_trip if mean is not None and turnover is not None else None
        record(store, run_id, f"group_momentum_{lookback}d", "exec_excess_20d", len(d), mean, se, t, p, period, now,
               {"turnover": turnover, "net_of_rotation_cost": net, "months": len(d)})
    return run_id


def run_group_reversal(store: ResultsStore, period: str, params: ResearchParams, now: datetime, record,
                       final: bool = False) -> str:
    check_period(period, final)
    run_id = f"{now:%Y%m%dT%H%M%S}-cross-group_reversal-{period}"
    store.start_run(run_id, "cross", period, params, now, ("group_reversal", "v1"))
    dates, codes, ret = _index(store)
    outcomes = _outcomes(store, params, period, 5, at_month_end=False)
    d, turnover = _tercile_spread(dates, codes, ret, outcomes, REVERSAL_LOOKBACK, "bottom",
                                  sample_every=REVERSAL_LOOKBACK)
    se, t, p, _, _ = mean_test(d, 0)
    mean = float(d.mean()) if len(d) else None
    net = mean - turnover * params.cost_round_trip if mean is not None and turnover is not None else None
    record(store, run_id, f"group_reversal_{REVERSAL_LOOKBACK}d", "exec_excess_5d", len(d), mean, se, t, p, period,
           now, {"turnover": turnover, "net_of_rotation_cost": net, "weeks": len(d)})
    return run_id
