"""Sanity report for a build: null rates by period, distributions, infinities, spot checks."""

from datetime import datetime

import duckdb

FEATURE_COLUMNS = (
    "return_1d", "return_3d", "return_5d", "return_10d", "return_20d", "excess_return_5d", "excess_return_20d",
    "volume_ratio_5", "volume_ratio_20", "volume_change", "volume_zscore_20",
    "volatility_5", "volatility_20", "atr_14_pct", "high_low_range", "gap",
    "close_position", "close_vs_avg_price",
    "order_imbalance", "volume_imbalance", "buy_pressure", "sell_pressure", "buy_sell_ratio",
    "foreign_net_volume", "foreign_net_value", "foreign_net_3d", "foreign_net_5d", "foreign_net_20d",
    "foreign_net_ratio_20", "foreign_intensity", "adv_value_20",
)
TARGET_COLUMNS = (
    "fwd_ret_close_1d", "fwd_ret_close_3d", "fwd_ret_close_5d", "fwd_ret_close_10d",
    "fwd_ret_exec_3d", "fwd_ret_exec_5d", "fwd_ret_exec_10d", "fwd_ret_exec_20d",
    "fwd_excess_exec_5d", "fwd_excess_exec_10d", "fwd_excess_exec_20d",
    "fwd_max_return_5d", "fwd_max_drawdown_5d",
)
SPOT_CHECKS = (
    ("VOS cash dividend 900 VND, ex-date 2026-10-01: return_1d should be ~-0.85%, not ~-7.9%",
     "SELECT round(return_1d * 100, 2) FROM stock_features WHERE symbol = 'VOS' AND date = DATE '2026-10-01'"),
    ("VOS 2026-07-30 closed at the ceiling (limit_up should be true)",
     "SELECT limit_up FROM stock_features WHERE symbol = 'VOS' AND date = DATE '2026-07-30'"),
    ("ETFs excluded from the panel (expect 0)",
     "SELECT count(*) FROM daily_panel WHERE symbol LIKE 'FUE%' OR symbol = 'E1VFVN30'"),
    ("FLC rows after its last trade 2022-09-08 (expect 0)",
     "SELECT count(*) FROM daily_panel WHERE symbol = 'FLC' AND date > DATE '2022-09-08'"),
    ("Infinite feature or target values (expect 0)", None),
)


def _table(headers: list[str], rows: list[tuple]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    return out + ["| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in rows]


def render_sanity_report(con: duckdb.DuckDBPyConnection, generated_at: datetime) -> str:
    build = con.execute("SELECT * FROM feature_builds ORDER BY built_at DESC LIMIT 1").fetchone()
    cols = [d[0] for d in con.description]
    lines = [f"# Feature build sanity report - {generated_at.isoformat(timespec='seconds')}", "",
             "## Build", *[f"- {k}: {v}" for k, v in zip(cols, build)], ""]

    periods = [r[0] for r in con.execute("SELECT DISTINCT period FROM stock_features ORDER BY 1").fetchall()]
    lines += ["## Null rate by period (%)", ""]
    rows = []
    for col in FEATURE_COLUMNS:
        sql = ", ".join(f"round(100 * avg(({col} IS NULL)::INT) FILTER (WHERE period = '{p}'), 1)" for p in periods)
        rows.append((col, *con.execute(f"SELECT {sql} FROM stock_features").fetchone()))
    for col in TARGET_COLUMNS:
        sql = ", ".join(f"round(100 * avg(({col} IS NULL)::INT) FILTER (WHERE period = '{p}'), 1)" for p in periods)
        rows.append((col, *con.execute(f"SELECT {sql} FROM stock_targets").fetchone()))
    lines += _table(["column", *periods], rows)

    lines += ["", "## Distributions (traded rows)", ""]
    rows = []
    for table, columns in (("stock_features", FEATURE_COLUMNS), ("stock_targets", TARGET_COLUMNS)):
        for col in columns:
            q = con.execute(f"""SELECT count({col}),
                round(quantile_cont({col}, 0.01), 4), round(quantile_cont({col}, 0.5), 4),
                round(quantile_cont({col}, 0.99), 4), round(min({col}), 4), round(max({col}), 4)
                FROM {table}""").fetchone()
            rows.append((col, *q))
    lines += _table(["column", "n", "p01", "p50", "p99", "min", "max"], rows)

    inf_sql = " + ".join(f"count(*) FILTER (WHERE isinf({c}))" for c in FEATURE_COLUMNS)
    inf_sql_t = " + ".join(f"count(*) FILTER (WHERE isinf({c}))" for c in TARGET_COLUMNS)
    lines += ["", "## Spot checks", ""]
    for label, sql in SPOT_CHECKS:
        if sql is None:
            value = con.execute(f"SELECT {inf_sql} FROM stock_features").fetchone()[0] \
                + con.execute(f"SELECT {inf_sql_t} FROM stock_targets").fetchone()[0]
        else:
            row = con.execute(sql).fetchone()
            value = row[0] if row else "no row"
        lines.append(f"- {label}: **{value}**")

    lines += ["", "## Market regime share of sessions", ""]
    lines += _table(["market_regime", "sessions"], con.execute(
        "SELECT market_regime, count(*) FROM market_daily GROUP BY 1 ORDER BY 1 NULLS FIRST").fetchall())
    return "\n".join(lines) + "\n"
