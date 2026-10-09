"""Markdown report of a `quant cross test` batch: every test with its estimate, p and BH q-value."""

import json
from datetime import datetime

import pandas as pd

from quant_research.cross.describe import _md
from quant_research.provenance import from_runs
from quant_research.results import ResultsStore


def _q(store: ResultsStore, run_ids: list[str]) -> pd.DataFrame:
    marks = ", ".join("?" for _ in run_ids)
    return store.con.execute(f"SELECT run_id, label, q_value, m FROM hypothesis_q WHERE run_id IN ({marks})",
                             run_ids).df()


def render_cross_tests(store: ResultsStore, run_ids: list[str], period: str, now: datetime) -> str:
    marks = ", ".join("?" for _ in run_ids)
    q = _q(store, run_ids)
    qmap = {(r.run_id, r.label): r.q_value for r in q.itertuples()}
    m = int(q["m"].max()) if len(q) else 0
    lines = [f"# Cross-stock tests - period {period} - {now.isoformat(timespec='minutes')}", "",
             *from_runs(store.con, run_ids),
             f"- Runs: {', '.join(f'`{r}`' for r in run_ids)}",
             f"- q = Benjamini-Hochberg over all {m} logged tests of all valid runs (not only these).",
             "- Outcomes are execution returns (enter at the next open) in excess of VNINDEX; costs 0.4% round "
             "trip are not subtracted from lifts and spreads; compare them with the cost.", ""]

    stats = store.con.execute(f"""SELECT run_id, test, horizon, n, estimate, se, t, p FROM cross_stats
                                  WHERE run_id IN ({marks}) ORDER BY test, horizon""", run_ids).df()
    if not stats.empty:
        stats["q"] = [qmap.get((r.run_id, f"{r.test}_{r.horizon}")) for r in stats.itertuples()]
        persist = stats[stats["test"].str.contains("leadlag_persist")]
        if not persist.empty:
            lines += ["## Lead-lag persistence (top-decile pairs of year Y, measured in year Y + 1)", "",
                      "`leadlag_persist_*` = stock pairs; `group_leadlag_persist_*` = ICB level-2 industry pairs.", "",
                      "estimate = mean over test years of (top-decile pairs' lag correlation minus all pairs'). "
                      "`cc` = follower close-to-close (includes stale-price effects); `oc` = follower's next "
                      "open-to-close (what a buyer at the open would see).", "",
                      *_md(persist.drop(columns=["run_id"]), "{:.4f}")]
        h2 = stats[stats["test"] == "h2_slope"]
        if not h2.empty:
            lines += ["## H2 large caps -> small caps (slope of small-cap future excess return on large-cap "
                      "return today)", "", *_md(h2.drop(columns=["run_id"]), "{:.4f}")]

    groups = stats[stats["test"].str.startswith(("group_momentum", "group_reversal"))] if not stats.empty else stats
    if not groups.empty:
        detail = store.con.execute(f"""SELECT run_id, test, horizon, detail FROM cross_stats
                                       WHERE run_id IN ({marks}) AND (test LIKE 'group_momentum%'
                                          OR test LIKE 'group_reversal%')""", run_ids).df()
        extra = {(r.run_id, r.test, r.horizon): json.loads(r.detail) for r in detail.itertuples()}
        groups = groups.assign(
            turnover=[extra[(r.run_id, r.test, r.horizon)].get("turnover") for r in groups.itertuples()],
            net_of_rotation_cost=[extra[(r.run_id, r.test, r.horizon)].get("net_of_rotation_cost")
                                  for r in groups.itertuples()])
        lines += ["## Industry momentum and reversal (ICB level 2, equal weight, long-only)", "",
                  "estimate = selected tercile minus the average industry per period (momentum: top tercile of the "
                  "last 21 or 63 sessions, next 20 sessions, monthly; reversal: bottom tercile of the last 5 "
                  "sessions, next 5 sessions, weekly). net_of_rotation_cost subtracts turnover x 0.4% per period.", "",
                  *_md(groups.drop(columns=["run_id"]), "{:.4f}")]

    scan = store.con.execute(f"""SELECT run_id, horizon, segment, n_dates, spread, spread_t, spread_p, ic_mean, ic_t
                                 FROM scan_stats WHERE run_id IN ({marks}) ORDER BY horizon, segment""", run_ids).df()
    if not scan.empty:
        scan["q"] = [qmap.get((r.run_id, f"spread_leader_excess_1d_{r.horizon}")) if r.segment == "all" else None
                     for r in scan.itertuples()]
        lines += ["## H1 industry leaders -> followers (deciles of the leaders' excess return today, "
                  "followers only)", "", "spread = decile 10 minus decile 1 of the followers' future excess "
                  "return.", "", *_md(scan.drop(columns=["run_id"]), "{:.4f}")]

    lifts = store.con.execute(f"""SELECT r.pattern_name, l.run_id, l.horizon, l.n_dates, l.pattern_mean,
                                         l.baseline_mean, l.lift, l.t, l.p
                                  FROM pattern_lifts l JOIN research_runs r USING (run_id)
                                  WHERE l.run_id IN ({marks}) ORDER BY 1, 3""", run_ids).df()
    if not lifts.empty:
        lifts["q"] = [qmap.get((r.run_id, f"lift_{r.horizon}")) for r in lifts.itertuples()]
        lines += ["## Patterns: H3, cointegration long leg, G4 laggards (lift vs the universe on the same dates)", "",
                  *_md(lifts.drop(columns=["run_id"]), "{:.4f}")]
    return "\n".join(lines) + "\n"
