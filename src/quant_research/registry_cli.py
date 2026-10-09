"""`quant registry list | show | add | move`: the Research Registry (wired into quant_research.cli)."""

import argparse
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from quant_research.registry import FAMILIES, TRANSITIONS, RegistryError, add, move
from quant_research.results import ResultsStore

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
STATUSES = tuple(s for s in TRANSITIONS if s)


def add_parser(sub: argparse._SubParsersAction) -> None:
    rg = sub.add_parser("registry", help="Research Registry: hypotheses, lifecycle, decisions")
    rs = rg.add_subparsers(dest="registry_command", required=True)
    ls = rs.add_parser("list", help="Every hypothesis with its current state")
    ls.add_argument("--family", choices=FAMILIES)
    ls.add_argument("--status", choices=STATUSES)
    sh = rs.add_parser("show", help="History, linked runs and q-values of one hypothesis")
    sh.add_argument("id")
    ad = rs.add_parser("add", help="Register a new hypothesis (state research or monitoring)")
    ad.add_argument("id")
    ad.add_argument("--family", required=True, choices=FAMILIES)
    ad.add_argument("--title", required=True)
    ad.add_argument("--statement", required=True, help="One sentence: what would be true")
    ad.add_argument("--reason", required=True)
    ad.add_argument("--status", default="research", choices=TRANSITIONS[None])
    ad.add_argument("--pattern")
    ad.add_argument("--version")
    mv = rs.add_parser("move", help="Append an allowed transition (never edits history)")
    mv.add_argument("id")
    mv.add_argument("--to", required=True, choices=STATUSES)
    mv.add_argument("--reason", required=True)
    mv.add_argument("--decision", choices=("PASS", "FAIL"))
    mv.add_argument("--run", help="Deciding run id (required with --decision)")
    mv.add_argument("--prereg", type=Path, help="Pre-registration file (hashed and checked against the run)")
    mv.add_argument("--result-doc")


def _list(store: ResultsStore, family: str | None, status: str | None) -> int:
    rows = store.con.execute("""SELECT hypothesis_id, family, status, coalesce(decision, '-'), title
                                FROM hypothesis_status
                                WHERE (? IS NULL OR family = ?) AND (? IS NULL OR status = ?)
                                ORDER BY hypothesis_id""", [family, family, status, status]).fetchall()
    for r in rows:
        print(f"  {r[0]:<8} {r[1]:<21} {r[2]:<13} {r[3]:<5} {r[4]}")
    counts = store.con.execute("SELECT status, count(*) FROM hypothesis_status GROUP BY 1 ORDER BY 1").fetchall()
    print("Totals: " + ", ".join(f"{s} {n}" for s, n in counts))
    return 0


def _show(store: ResultsStore, hid: str) -> int:
    head = store.con.execute("""SELECT title, family, statement, pattern, pattern_version, status, decision, reason
                                FROM hypothesis_status WHERE hypothesis_id = ?""", [hid]).fetchone()
    if head is None:
        print(f"Unknown hypothesis {hid}", file=sys.stderr)
        return 1
    title, family, statement, pattern, version, status, decision, reason = head
    print(f"{hid}: {title} ({family})\n  {statement}")
    print(f"  pattern {pattern or '-'} {version or ''}; state {status}; decision {decision or '-'}: {reason}")
    print("History:")
    for r in store.con.execute("""SELECT seq, moved_at, status, coalesce(decision, ''), reason, run_id, prereg_doc,
                                         left(prereg_sha, 12), result_doc
                                  FROM hypothesis_transitions WHERE hypothesis_id = ? ORDER BY seq""", [hid]).fetchall():
        extra = "; ".join(f"{k} {v}" for k, v in (("run", r[5]), ("prereg", r[6] and f"{r[6]} ({r[7]})"),
                                                   ("doc", r[8])) if v)
        label = f"{r[2]} {r[3]}" if r[3] else r[2]
        print(f"  {r[0]}. {r[1]:%Y-%m-%d} {label}: {r[4]}" + (f" [{extra}]" if extra else ""))
    print("Linked runs (min BH q over their logged tests):")
    for r in store.con.execute("""
            SELECT r.run_id, r.period, r.status, min(q.q_value) FROM research_runs r
            LEFT JOIN hypothesis_q q USING (run_id)
            WHERE r.run_id IN (SELECT run_id FROM hypothesis_transitions WHERE hypothesis_id = ?)
               OR (r.pattern_name = ? AND r.pattern_name IS NOT NULL)
            GROUP BY ALL ORDER BY r.run_id""", [hid, pattern]).fetchall():
        print(f"  {r[0]} {r[1]} {r[2]} q {'-' if r[3] is None else f'{r[3]:.3g}'}")
    return 0


def run(args: argparse.Namespace, store_factory: Callable[[], ResultsStore]) -> int:
    now = datetime.now(VN_TZ).replace(microsecond=0)
    with store_factory() as store:
        try:
            if args.registry_command == "list":
                return _list(store, args.family, args.status)
            if args.registry_command == "show":
                return _show(store, args.id)
            if args.registry_command == "add":
                add(store.con, args.id, args.family, args.title, args.statement, now, args.reason, args.status,
                    args.pattern, args.version)
                print(f"Registered {args.id} ({args.status}).")
                return 0
            seq = move(store.con, args.id, args.to, args.reason, now, args.decision, args.run, args.prereg,
                       args.result_doc)
            print(f"{args.id}: transition {seq} -> {args.to}" + (f" ({args.decision})" if args.decision else ""))
            return 0
        except RegistryError as exc:
            print(f"Refused: {exc}", file=sys.stderr)
            return 2
