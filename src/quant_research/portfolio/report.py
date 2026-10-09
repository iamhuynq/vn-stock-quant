"""Report of the construction grid, with the reading rule declared in docs/portfolio-construction-plan.md."""

import pandas as pd

from quant_research.backtest.metrics import WRITEDOWN_SESSIONS
from quant_research.portfolio.evaluate import CAPITALS, COSTS, DECISION
from quant_research.provenance import from_runs
from quant_research.results import ResultsStore

MIN_SHARE_BEATEN = 0.95        # at least 19 of 20 matched random runs
MIN_BREAK_EVEN = 0.002         # extra cost per side on top of v1 k = 1


def _pct(v) -> str:
    return "-" if v is None or pd.isna(v) else f"{v:+.1%}"


def _num(v, fmt: str = ".2f") -> str:
    return "-" if v is None or pd.isna(v) else format(v, fmt)


def latest_runs(store: ResultsStore) -> dict[str, str]:
    rows = store.con.execute("""SELECT pattern_name, run_id FROM research_runs WHERE kind = 'portfolio'
                                AND status = 'ok' ORDER BY created_at""").fetchall()
    return dict(rows)


def verdict(get, capital: float = DECISION[0]) -> tuple[bool, list[str]]:
    cagr = get((capital, DECISION[1], "strategy", "cagr"))
    ew = get((capital, "gross", "equal_weight", "cagr"))
    share = get((capital, DECISION[1], "random_construction", "share_beaten"))
    be = get((capital, DECISION[1], "strategy", "break_even_extra_cost_per_side"))
    checks = [("beats equal weight", cagr is not None and ew is not None and cagr > ew),
              (f"beats >= {MIN_SHARE_BEATEN:.0%} of matched random runs", share is not None and share >= MIN_SHARE_BEATEN),
              (f"break-even >= {MIN_BREAK_EVEN:.1%} per side over v1", be is not None and be >= MIN_BREAK_EVEN)]
    return all(ok for _, ok in checks), [f"{'pass' if ok else 'fail'}: {name}" for name, ok in checks]


def render(store: ResultsStore, run_ids: dict[str, str]) -> str:
    q = dict(store.con.execute("""SELECT run_id, q_value FROM hypothesis_q
                                  WHERE label = 'portfolio_excess_vs_equal_weight'""").fetchall())
    lines = ["# Portfolio construction grid (research period)", "", *from_runs(store.con, list(run_ids.values())), "",
             "Pre-declared grid and reading rule: docs/portfolio-construction-plan.md. Decision setting: "
             f"{DECISION[0] / 1e9:g} bn VND, cost model `{DECISION[1]}`. Benchmarks are gross.", "",
             "Matched random = the same construction on random scores with the signal's rank persistence between "
             "rebalances (rho), so the control trades about as much as the strategy.", "",
             "| Config | CAGR flat | CAGR v1 | CAGR v1 tick | Equal weight | Turnover / yr (v1) | Control turnover | "
             "Rank persistence | Cash share | Beats matched random | Break-even over v1 | Test p / q | "
             "Worth a pre-registration |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    details = []
    for name, run_id in sorted(run_ids.items()):
        df = store.con.execute("SELECT * FROM portfolio_results WHERE run_id = ?", [run_id]).df()
        g = df.set_index(["capital", "cost_model", "series", "metric"])["value"]
        get = lambda key, g=g: None if key not in g.index else g[key]  # noqa: E731
        ok, checks = verdict(get)
        c = DECISION[0]
        lines.append(f"| {name} | {_pct(get((c, 'flat', 'strategy', 'cagr')))} | {_pct(get((c, 'v1_k1', 'strategy', 'cagr')))} | "
                     f"{_pct(get((c, 'v1_k1_tick', 'strategy', 'cagr')))} | {_pct(get((c, 'gross', 'equal_weight', 'cagr')))} | "
                     f"{_num(get((c, 'v1_k1', 'strategy', 'turnover_per_year')), '.1f')} | "
                     f"{_num(get((c, 'v1_k1', 'random_construction', 'median_turnover_per_year')), '.1f')} | "
                     f"{_num(get((c, 'v1_k1', 'strategy', 'rank_persistence')), '.2f')} | "
                     f"{_num(get((c, 'v1_k1', 'strategy', 'avg_cash_share')), '.0%')} | "
                     f"{_num(get((c, 'v1_k1', 'random_construction', 'share_beaten')), '.0%')} | "
                     f"{_num(get((c, 'v1_k1', 'strategy', 'break_even_extra_cost_per_side')), '.3%')} | "
                     f"{_num(get((c, 'v1_k1', 'test', 'excess_vs_equal_weight_p')), '.3g')} / {_num(q.get(run_id), '.3g')} | "
                     f"{'**yes**' if ok else 'no'} |")
        d = (c, "v1_k1", "strategy")
        details += ["", f"## {name} ({run_id})", "", "; ".join(checks), "",
                    f"At {c / 1e9:g} bn VND, v1: max industry weight target "
                    f"{_num(get((*d[:2], 'strategy', 'max_target_industry_weight')), '.0%')}, actual "
                    f"{_num(get((*d[:2], 'strategy', 'max_actual_industry_weight')), '.0%')}; closes above the cap "
                    f"{_num(get((*d[:2], 'strategy', 'industry_cap_breach_sessions')), '.0f')} (after trades "
                    f"{_num(get((*d[:2], 'strategy', 'industry_cap_breach_after_trades')), '.0f')}); orders blocked "
                    f"{_num(get((*d[:2], 'strategy', 'orders_blocked')), '.0f')} (T+2 "
                    f"{_num(get((*d[:2], 'strategy', 'orders_blocked_t2')), '.0f')}, T+2 partial "
                    f"{_num(get((*d[:2], 'strategy', 'orders_partial_t2')), '.0f')}, no ADV "
                    f"{_num(get((*d[:2], 'strategy', 'orders_blocked_no_adv')), '.0f')}); data-error exits "
                    f"{_num(get((*d[:2], 'strategy', 'data_error_exits')), '.0f')}; value marked with a price older than "
                    f"5 sessions: mean {_num(get((*d[:2], 'strategy', 'stale_value_share_mean')), '.1%')}, max "
                    f"{_num(get((*d[:2], 'strategy', 'stale_value_share_max')), '.1%')}. Sensitivity sell lag 2 (optimistic "
                    f"T+2): CAGR {_pct(get((*d[:2], 'sell_lag_2', 'cagr')))} vs {_pct(get((*d[:2], 'strategy', 'cagr')))}. "
                    f"Stuck positions written down after {WRITEDOWN_SESSIONS} sessions: CAGR "
                    f"{_pct(get((*d[:2], f'writedown_{WRITEDOWN_SESSIONS}', 'cagr')))}. Order value / ADV20: median "
                    f"{_num(get((*d[:2], 'strategy', 'participation_median')), '.2%')}, p95 "
                    f"{_num(get((*d[:2], 'strategy', 'participation_p95')), '.2%')}.",
                    "",
                    "| Capital (bn VND) | Costs | CAGR | Sharpe | Max DD | Turnover / yr | Costs paid (x initial) | "
                    "Avg names | vs equal weight | vs VNINDEX | Matched random median CAGR |",
                    "|---|---|---|---|---|---|---|---|---|---|---|"]
        for cap in CAPITALS:
            for cost in COSTS:
                details.append(
                    f"| {cap / 1e9:g} | {cost} | {_pct(get((cap, cost, 'strategy', 'cagr')))} | "
                    f"{_num(get((cap, cost, 'strategy', 'sharpe')))} | {_pct(get((cap, cost, 'strategy', 'max_drawdown')))} | "
                    f"{_num(get((cap, cost, 'strategy', 'turnover_per_year')), '.1f')} | "
                    f"{_num(get((cap, cost, 'strategy', 'costs_paid_x_initial')), '.2f')} | "
                    f"{_num(get((cap, cost, 'strategy', 'avg_names')), '.1f')} | "
                    f"{_pct(get((cap, cost, 'strategy', 'excess_cagr_vs_equal_weight')))} | "
                    f"{_pct(get((cap, cost, 'strategy', 'excess_cagr_vs_vnindex')))} | "
                    f"{_pct(get((cap, cost, 'random_construction', 'median_cagr')))} |")
    return "\n".join(lines + details)
