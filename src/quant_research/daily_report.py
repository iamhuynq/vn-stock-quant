"""One-page daily report: avoid list, today's events with historical stats, forward scoreboard, paper portfolio.

When a run scans several sessions (catch-up after missed days), each scanned session gets its own report.
Reports for earlier sessions are "catch-up" reports with that session's regime, avoid list, events and paper
equity (the same values an on-time run would have shown, since features and the paper re-simulation only use
data up to each session); the forward scoreboard and open positions are only in the latest session's report.
"""

from datetime import date, datetime
from pathlib import Path

from quant_research.daily import AVOID_PATTERN, FORWARD_START, DailyResult
from quant_research.events import DAILY_PREFIX, EVENT_TYPES
from quant_research.provenance import line
from quant_research.patterns import LIBRARY
from quant_research.results import ResearchParams, ResultsStore

MAX_SYMBOLS = 15


def _pct(x, d=2):
    return "-" if x is None else f"{x * 100:+.{d}f}%"


def _historical(store: ResultsStore) -> dict[str, dict]:
    """Latest valid research and validation lift (10d) per pattern, with q-values."""
    rows = store.con.execute("""
        WITH l AS (SELECT r.pattern_name, r.period, l.lift, l.t, r.created_at, r.run_id
                   FROM pattern_lifts l JOIN research_runs r USING (run_id)
                   WHERE r.status = 'ok' AND l.horizon = 'exec_excess_10d'),
             ranked AS (SELECT *, row_number() OVER (PARTITION BY pattern_name, period ORDER BY created_at DESC) rn FROM l)
        SELECT ranked.pattern_name, ranked.period, ranked.lift, ranked.t, q.q_value
        FROM ranked LEFT JOIN hypothesis_q q ON q.run_id = ranked.run_id AND q.label = 'lift_exec_excess_10d'
        WHERE rn = 1""").fetchall()
    out: dict[str, dict] = {}
    for name, period, lift, t, q in rows:
        out.setdefault(name, {})[period] = (lift, t, q)
    return out


def _catalog_lines(store: ResultsStore, d: date) -> list[str]:
    """Today's catalog events (Phase 5) with the latest event study's research-period figures (descriptive)."""
    con = store.con
    rows = con.execute(f"""SELECT substr(pattern, {len(DAILY_PREFIX) + 1}), list(symbol ORDER BY symbol)
                           FROM daily_events WHERE scan_date = ? AND pattern LIKE '{DAILY_PREFIX}%'
                           GROUP BY 1""", [d]).fetchall()
    today = dict(rows)
    hist: dict = {}
    has = con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = 'event_study_stats'").fetchone()[0]
    if has:
        run = con.execute("""SELECT run_id FROM research_runs WHERE kind = 'event_study' AND status = 'ok'
                             ORDER BY created_at DESC LIMIT 1""").fetchone()
        if run:
            hist = {r[0]: r[1:] for r in con.execute("""
                SELECT event_type, n_events, mean, win_rate, lift FROM event_study_stats
                WHERE run_id = ? AND segment = 'all' AND horizon = 'exec_excess_10d'""", [run[0]]).fetchall()}
    lines = ["", "## Catalog events today (descriptive event study, research period, 10 sessions from the next open)",
             "", "| event | today | symbols | past events | mean excess 10d | win rate | lift vs universe |",
             "|---|---|---|---|---|---|---|"]
    for event in EVENT_TYPES:
        syms = today.get(event, [])
        n, mean, win, lift = hist.get(event, (None, None, None, None))
        shown = ", ".join(syms[:MAX_SYMBOLS]) + (f" (+{len(syms) - MAX_SYMBOLS})" if len(syms) > MAX_SYMBOLS else "")
        lines.append(f"| {event} | {len(syms)} | {shown or '-'} | {n if n is not None else '-'} | {_pct(mean)} | "
                     f"{'-' if win is None else f'{win:.0%}'} | {_pct(lift)} |")
    return lines + ["", "> Event-study figures are historical averages, not tested claims (not in the hypothesis log)."]


def _status(store: ResultsStore, name: str, version: str) -> str:
    """The recorded pre-registered decision, verbatim; a changed definition (new version) is 'not validated'."""
    row = store.con.execute("SELECT version, decision, reason FROM validation_decisions WHERE pattern = ?",
                            [name]).fetchone()
    if row is None:
        return "not validated"
    if row[0] != version:
        return "not validated (definition changed since validation)"
    return f"**{row[1]}**: {row[2]}"


def render_daily(store: ResultsStore, result: DailyResult, now: datetime, day: date | None = None) -> str:
    con = store.con
    d = day or result.latest_date
    catch_up = day is not None and day != result.latest_date
    lines = [f"# Daily report - data {d} - generated {now.isoformat(timespec='minutes')}", "",
             line(store.provenance()), ""]
    if d is None:
        return "\n".join(lines + ["No data."]) + "\n"
    if catch_up:
        lines += [f"> Catch-up report: this session was scanned late, on {now.date()}. The forward scoreboard and",
                  f"> open positions are in the report of the latest session ({result.latest_date}).", ""]
    regime = con.execute("SELECT market_regime, mkt_close FROM rs.market_daily WHERE date = ?", [d]).fetchone()
    scan = con.execute("SELECT status, coverage FROM daily_scans WHERE scan_date = ?", [d]).fetchone()
    lines += [f"- Market regime: **{regime[0]}** (VNINDEX {regime[1]:,.2f})",
              f"- Scan of {d}: **{scan[0] if scan else 'not scanned'}**"
              + (f" (coverage {scan[1] * 100:.1f}%)" if scan else ""),
              f"- Sessions scanned this run: {len(result.scanned)}"
              + (f"; incomplete: {', '.join(f'{x} ({c * 100:.0f}%)' for x, c in result.incomplete)}" if result.incomplete else ""),
              f"- Forward test since {FORWARD_START}: {'not started yet' if d < FORWARD_START else 'running'}",
              "", "> Historical statistics describe past averages over thousands of cases. They are not a forecast for",
              "> any single stock and not investment advice.", ""]

    avoid = [r[0] for r in con.execute("""SELECT symbol FROM daily_events WHERE scan_date = ? AND pattern = ?
                                          ORDER BY symbol""", [d, AVOID_PATTERN]).fetchall()]
    lines += ["## Avoid list (validated: sharp drop + heavy volume + sellers dominate)", "",
              ", ".join(avoid) if avoid else "_None today._", ""]

    hist = _historical(store)
    lines += ["## Today's events", "",
              "| pattern | events | symbols | research lift 10d (q) | validation | doc |", "|---|---|---|---|---|---|"]
    for name, p in LIBRARY.items():
        syms = [r[0] for r in con.execute("""SELECT symbol FROM daily_events WHERE scan_date = ? AND pattern = ?
                                             ORDER BY symbol""", [d, name]).fetchall()]
        h = hist.get(name, {})
        res = h.get("research")
        res_txt = "-" if res is None else f"{_pct(res[0])} (q {res[2]:.3g})" if res[2] is not None else _pct(res[0])
        shown = ", ".join(syms[:MAX_SYMBOLS]) + (f" (+{len(syms) - MAX_SYMBOLS})" if len(syms) > MAX_SYMBOLS else "")
        lines.append(f"| {name} | {len(syms)} | {shown or '-'} | {res_txt} | {_status(store, name, p.version)} | {p.doc_ref} |")

    lines += _catalog_lines(store, d)
    if catch_up:
        return "\n".join(lines + _paper_lines(con, result.latest_date, d, positions=False)) + "\n"
    lines += ["", "## Forward scoreboard (events since " + str(FORWARD_START) + ")", ""]
    universe = ResearchParams().universe_sql()
    board = con.execute(f"""
        WITH e AS (SELECT e.pattern, e.scan_date AS date, t.fwd_excess_exec_10d AS y
                   FROM daily_events e LEFT JOIN rs.stock_targets t ON t.symbol = e.symbol AND t.date = e.scan_date
                   WHERE e.is_forward),
             u AS (SELECT date, avg(fwd_excess_exec_10d) AS uy FROM rs.feature_target
                   WHERE date >= ? AND fwd_excess_exec_10d IS NOT NULL AND {universe} GROUP BY date),
             per_date AS (SELECT pattern, date, avg(y) AS py FROM e WHERE y IS NOT NULL GROUP BY 1, 2)
        SELECT e.pattern, count(*) AS events, count(e.y) AS matured,
               (SELECT avg(p.py - u.uy) FROM per_date p JOIN u USING (date) WHERE p.pattern = e.pattern) AS lift
        FROM e GROUP BY 1 ORDER BY 1""", [FORWARD_START]).fetchall()
    if board:
        lines += ["| pattern | forward events | matured (10d) | forward lift 10d |", "|---|---|---|---|"]
        lines += [f"| {n} | {ev} | {mat} | {_pct(lift)} |" for n, ev, mat, lift in board]
    else:
        lines.append("_No forward events yet._")

    return "\n".join(lines + _paper_lines(con, result.latest_date, d, positions=True)) + "\n"


def _paper_lines(con, run_date: date | None, d: date, positions: bool) -> list[str]:
    """Paper portfolio as of session d, from the latest re-simulation (run_date)."""
    lines = ["", "## Paper portfolio (frozen strategy 72c851c7, since " + str(FORWARD_START) + ")", ""]
    last = con.execute("""SELECT date, equity, random_p05, random_median, random_p95, equal_weight, vnindex, n_positions,
                                 equity_traded_mark
                          FROM paper_daily WHERE run_date = ? AND date <= ? ORDER BY date DESC LIMIT 1""",
                       [run_date, d]).fetchone()
    if last is None:
        lines.append("_Not started: fewer than two forward sessions so far._")
    else:
        start = 1e9
        lines += [f"- Strategy: {_pct(last[1] / start - 1)} | random control median {_pct(last[3] / start - 1)} "
                  f"[p5 {_pct(last[2] / start - 1)}, p95 {_pct(last[4] / start - 1)}] | equal weight "
                  f"{_pct(last[5] / start - 1)} | VNINDEX {_pct(last[6] / start - 1)} | positions {last[7]}"]
        if last[8] is not None:
            lines.append(f"- Marked at last traded closes (information; the pre-registered record above keeps the "
                         f"reference price of no-trade sessions): {_pct(last[8] / start - 1)}")
        pos = con.execute("""SELECT symbol, entry_date, entry_price, last_price FROM paper_positions
                             WHERE run_date = ? ORDER BY symbol""", [run_date]).fetchall() if positions else []
        if pos:
            lines += ["", "| symbol | entry | entry price (adj) | last (adj) | P&L |", "|---|---|---|---|---|"]
            lines += [f"| {s} | {e} | {ep:.2f} | {lp:.2f} | {_pct(lp / ep - 1)} |" for s, e, ep, lp in pos]
    return lines


def write_reports(store: ResultsStore, result: DailyResult, now: datetime, out_dir: Path) -> list[Path]:
    """One report per session scanned in this run, plus the latest session's report (always rewritten)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    days = sorted({*result.scanned, *([result.latest_date] if result.latest_date else [])})
    written = []
    for d in days:
        path = out_dir / f"{d}.md"
        path.write_text(render_daily(store, result, now, day=d), encoding="utf-8")
        written.append(path)
    if not days:
        path = out_dir / f"{now.date()}.md"
        path.write_text(render_daily(store, result, now), encoding="utf-8")
        written.append(path)
    return written
