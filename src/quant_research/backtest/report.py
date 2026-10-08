"""Markdown report for a set of backtest runs."""

from datetime import datetime

import duckdb

GRID = [(h, k, renew) for h in (5, 10, 20) for k in (10, 20) for renew in (True, False)]


def grid_label(h: int, k: int, renew: bool) -> str:
    return f"oi_d10_h{h}_k{k}_{'renew' if renew else 'norenew'}"


def _pct(x, d=1):
    return "-" if x is None else f"{x * 100:.{d}f}%"


def _f(x, d=2):
    return "-" if x is None else f"{x:.{d}f}"


def render_backtest(con: duckdb.DuckDBPyConnection, run_ids: list[str], generated_at: datetime) -> str:
    def metrics(run_id: str) -> dict:
        return {(s, m): v for s, m, v in con.execute(
            "SELECT series, metric, value FROM backtest_metrics WHERE run_id = ?", [run_id]).fetchall()}

    q = dict(con.execute("SELECT run_id, q_value FROM hypothesis_q WHERE label = 'excess_vs_equal_weight'").fetchall())
    meta = {r[0]: r[1:] for r in con.execute(
        "SELECT run_id, pattern_name, period FROM research_runs WHERE run_id IN (SELECT unnest(?))", [run_ids]).fetchall()}
    period = meta[run_ids[0]][1] if run_ids else "?"
    first = metrics(run_ids[0]) if run_ids else {}
    lines = [f"# Backtest - order-imbalance top decile - {period} period - {generated_at.isoformat(timespec='seconds')}", "",
             "Long-only, equal weight, next-open entry, close exit, T+2, ceiling/floor rules, 5% of ADV cap,",
             "0.4% round trip (0.15% fee each side + 0.1% tax). Benchmarks are gross (no costs).", "",
             f"Benchmarks over the same window: equal-weight universe CAGR {_pct(first.get(('equal_weight', 'cagr')))}"
             f" (max DD {_pct(first.get(('equal_weight', 'max_drawdown')))}), VNINDEX CAGR {_pct(first.get(('vnindex', 'cagr')))}"
             f" (max DD {_pct(first.get(('vnindex', 'max_drawdown')))}).", "",
             "## Variants", "",
             "| variant | CAGR | Sharpe | max DD | turnover/yr | costs (x initial) | win rate | avg hold | exposure "
             "| random CAGR median [p5, p95] | beats random | excess vs EW t | q |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for run_id in run_ids:
        m = metrics(run_id)
        lines.append(
            f"| {meta[run_id][0]} | {_pct(m.get(('strategy', 'cagr')))} | {_f(m.get(('strategy', 'sharpe')))} "
            f"| {_pct(m.get(('strategy', 'max_drawdown')))} | {_f(m.get(('strategy', 'turnover_per_year')), 1)} "
            f"| {_f(m.get(('strategy', 'costs_paid_pct_of_initial')))} | {_pct(m.get(('strategy', 'win_rate')))} "
            f"| {_f(m.get(('strategy', 'avg_holding_sessions')), 1)} | {_pct(m.get(('strategy', 'exposure')), 0)} "
            f"| {_pct(m.get(('random_median', 'cagr')))} [{_pct(m.get(('random_p05', 'cagr')))}, {_pct(m.get(('random_p95', 'cagr')))}] "
            f"| {_pct(m.get(('test', 'share_of_random_runs_beaten')), 0)} | {_f(m.get(('test', 'excess_vs_equal_weight_t')))} "
            f"| {_f(q.get(run_id), 3)} |")
    for run_id in run_ids:
        m = metrics(run_id)
        years = sorted({s.split("=")[1] for s, _ in m if s.startswith("year=")})
        lines += ["", f"## {meta[run_id][0]}", "", f"Run `{run_id}`. Data-error exits: "
                  f"{_f(m.get(('strategy', 'data_error_exits')), 0)}, entries blocked: {_f(m.get(('strategy', 'entries_blocked')), 0)}, "
                  f"exits delayed: {_f(m.get(('strategy', 'exits_delayed')), 0)}, capacity-capped entries: "
                  f"{_f(m.get(('strategy', 'capacity_capped_entries')), 0)}, open at end: {_f(m.get(('strategy', 'open_at_end')), 0)}.", "",
                  "| year | strategy | equal weight | VNINDEX |", "|---|---|---|---|"]
        for y in years:
            lines.append(f"| {y} | {_pct(m.get((f'year={y}', 'strategy_return')))} | {_pct(m.get((f'year={y}', 'equal_weight_return')))} "
                         f"| {_pct(m.get((f'year={y}', 'vnindex_return')))} |")
        lines += ["", "| regime | sessions | strategy (annual log) | equal weight (annual log) |", "|---|---|---|---|"]
        for regime in ("Bull", "Sideway", "Bear"):
            if (f"regime={regime}", "sessions") in m:
                lines.append(f"| {regime} | {_f(m[(f'regime={regime}', 'sessions')], 0)} "
                             f"| {_pct(m[(f'regime={regime}', 'strategy_annual_log_return')])} "
                             f"| {_pct(m[(f'regime={regime}', 'equal_weight_annual_log_return')])} |")
    return "\n".join(lines) + "\n"
