"""Markdown reports for pattern batches and feature scans."""

from datetime import datetime

import duckdb

from quant_research.patterns import LIBRARY
from quant_research.provenance import from_runs

Q_THRESHOLD = 0.05


def _pct(x: float | None, digits: int = 2) -> str:
    return "-" if x is None else f"{x * 100:.{digits}f}%"


def _num(x: float | None, digits: int = 3) -> str:
    return "-" if x is None else f"{x:.{digits}g}" if abs(x) < 1e-3 else f"{x:.{digits}f}"


def verdict(lift: float | None, after_cost: float | None, q: float | None) -> str:
    """Information = lift vs the universe (q-tested); tradability = absolute mean after costs (long only)."""
    if lift is None or q is None:
        return "insufficient data"
    if q >= Q_THRESHOLD:
        return "no significant difference from the universe"
    if lift > 0:
        return "outperforms; survives costs" if after_cost and after_cost > 0 else "outperforms; eaten by costs"
    return "underperforms (avoid/exit signal; shorting not available)"


def render_pattern_batch(con: duckdb.DuckDBPyConnection, run_ids: list[str], period: str, generated_at: datetime) -> str:
    lines = [f"# Pattern tests - {period} period - {generated_at.isoformat(timespec='seconds')}", "",
             *from_runs(con, run_ids),
             "Outcome: excess return vs VNINDEX, enter next open, exit close t+h. Statistics use the date as the",
             "unit (events on one date averaged), Newey-West SE (lag h-1), BH q-values over the whole hypothesis log.",
             "Costs: round trip from run params. **Research-period results are not validated.**", "",
             "**lift** = pattern minus all filtered stocks on the same dates (the tested quantity).",
             "**after cost** = absolute pattern mean minus round-trip cost (what a long trade would keep).", "",
             "## Summary (all events)", "",
             "| pattern | events | dates | h | mean | universe | lift | lift t | q | after cost | win rate (universe) | verdict |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    details: list[str] = []
    for run_id in run_ids:
        name = con.execute("SELECT pattern_name FROM research_runs WHERE run_id = ?", [run_id]).fetchone()[0]
        q = dict(con.execute("SELECT label, q_value FROM hypothesis_q WHERE run_id = ?", [run_id]).fetchall())
        rows = con.execute("""SELECT s.horizon, s.n_events, s.n_dates, s.mean, s.mean_after_cost, s.win_rate,
                                     l.baseline_mean, l.lift, l.t, l.baseline_win_rate
                              FROM pattern_stats s LEFT JOIN pattern_lifts l USING (run_id, horizon)
                              WHERE s.run_id = ? AND s.segment = 'all' AND s.horizon LIKE 'exec_excess_%'""",
                           [run_id]).fetchall()
        for h, n, nd, mean, ac, wr, base, lift, lt, bwr in sorted(rows, key=lambda r: int(r[0].split("_")[-1][:-1])):
            qv = q.get(f"lift_{h}")
            lines.append(f"| {name} | {n:,} | {nd:,} | {h.split('_')[-1]} | {_pct(mean)} | {_pct(base)} | {_pct(lift)} "
                         f"| {_num(lt, 2)} | {_num(qv)} | {_pct(ac)} | {_pct(wr, 1)} ({_pct(bwr, 1)}) | {verdict(lift, ac, qv)} |")
        details += _pattern_detail(con, run_id, name, q)
    return "\n".join(lines + [""] + details) + "\n"


def _pattern_detail(con: duckdb.DuckDBPyConnection, run_id: str, name: str, q: dict) -> list[str]:
    p = LIBRARY.get(name)
    out = [f"## {name}", "", f"- run: `{run_id}`"]
    if p:
        out += [f"- condition: `{p.where}`", f"- hypothesis: {p.hypothesis} (doc {p.doc_ref})"]
    out += ["", "| horizon | segment | events | dates | mean | median | win rate | t | p |", "|---|---|---|---|---|---|---|---|---|"]
    for h, seg, n, nd, mean, med, wr, t, pv in con.execute(
            """SELECT horizon, segment, n_events, n_dates, mean, median, win_rate, t, p FROM pattern_stats
               WHERE run_id = ? AND n_events > 0 ORDER BY horizon, segment""", [run_id]).fetchall():
        out.append(f"| {h} | {seg} | {n:,} | {nd:,} | {_pct(mean)} | {_pct(med)} | {_pct(wr, 1)} | {_num(t, 2)} | {_num(pv)} |")
    comps = con.execute("""SELECT horizon, base_name, n_dates, diff_mean, t, p FROM pattern_comparisons
                           WHERE run_id = ? ORDER BY horizon""", [run_id]).fetchall()
    if comps:
        out += ["", f"Does the extra condition add information versus `{comps[0][1]}`? "
                    "(refined minus base-only events, same dates)", "",
                "| horizon | dates | difference | t | q |", "|---|---|---|---|---|"]
        for h, _, nd, diff, t, _ in comps:
            out.append(f"| {h} | {nd:,} | {_pct(diff)} | {_num(t, 2)} | {_num(q.get(f'vs_base_{h}'))} |")
    return out + [""]


def render_scan(con: duckdb.DuckDBPyConnection, run_id: str, generated_at: datetime, top: int = 12) -> str:
    period = con.execute("SELECT period FROM research_runs WHERE run_id = ?", [run_id]).fetchone()[0]
    q = dict(con.execute("SELECT label, q_value FROM hypothesis_q WHERE run_id = ?", [run_id]).fetchall())
    lines = [f"# Feature scan - {period} period - {generated_at.isoformat(timespec='seconds')}", "",
             *from_runs(con, [run_id]),
             f"Run `{run_id}`. Deciles formed within each date; spread = decile 10 minus decile 1 (excess",
             "return, next-open entry); IC = mean daily Spearman correlation. Newey-West t-stats; q = BH over the log.", ""]
    horizons = [r[0] for r in con.execute(
        "SELECT DISTINCT horizon FROM scan_stats WHERE run_id = ? ORDER BY 1", [run_id]).fetchall()]
    for h in sorted(horizons, key=lambda x: int(x.split("_")[-1][:-1])):
        lines += [f"## {h}: strongest features (segment all)", "",
                  "| feature | spread D10-D1 | t | q | IC | IC t | monotonicity | Bull spread | Sideway spread | Bear spread |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        rows = con.execute("""
            SELECT a.feature, a.spread, a.spread_t, a.ic_mean, a.ic_t, a.monotonicity,
                   (SELECT spread FROM scan_stats s WHERE s.run_id = a.run_id AND s.feature = a.feature AND s.horizon = a.horizon AND s.segment = 'regime=Bull'),
                   (SELECT spread FROM scan_stats s WHERE s.run_id = a.run_id AND s.feature = a.feature AND s.horizon = a.horizon AND s.segment = 'regime=Sideway'),
                   (SELECT spread FROM scan_stats s WHERE s.run_id = a.run_id AND s.feature = a.feature AND s.horizon = a.horizon AND s.segment = 'regime=Bear')
            FROM scan_stats a WHERE a.run_id = ? AND a.horizon = ? AND a.segment = 'all'
            ORDER BY abs(a.spread_t) DESC NULLS LAST LIMIT ?""", [run_id, h, top]).fetchall()
        for f, sp, st, ic, ict, mono, bull, side, bear in rows:
            lines.append(f"| {f} | {_pct(sp)} | {_num(st, 2)} | {_num(q.get(f'spread_{f}_{h}'))} | {_num(ic)} | {_num(ict, 2)} "
                         f"| {_num(mono, 2)} | {_pct(bull)} | {_pct(side)} | {_pct(bear)} |")
        lines.append("")
    return "\n".join(lines) + "\n"
