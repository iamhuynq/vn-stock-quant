"""`quant cross build | describe | test`: Phase 4 commands (wired into quant_research.cli)."""

import argparse
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from quant_research.cross.build import CrossBuildError, build_cross
from quant_research.cross.describe import render_describe
from quant_research.cross.hypotheses import TESTS, attach, run_all
from quant_research.cross.params import CrossParams
from quant_research.cross.report import render_cross_tests
from quant_research.results import ResearchParams, ResultsStore

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def add_parser(sub: argparse._SubParsersAction) -> None:
    cx = sub.add_parser("cross", help="Cross-stock analysis (Phase 4): build, describe, test")
    cs = cx.add_subparsers(dest="cross_command", required=True)
    cs.add_parser("build", help="Rebuild data/cross.duckdb from research.duckdb (read-only)")
    cs.add_parser("describe", help="Descriptive report (research period only)")
    t = cs.add_parser("test", help="Lead-lag persistence, H1-H3 and cointegration tests (logged)")
    t.add_argument("--period", default="research", choices=("research", "validation", "holdout", "forward"))
    t.add_argument("--final", action="store_true", help="Required for the holdout period (logged)")
    t.add_argument("--prereg", type=Path, help="Pre-registration file (required outside the research period)")
    t.add_argument("--tests", default=",".join(TESTS), help=f"Comma list from {','.join(TESTS)} (default: all)")


def _write(data_dir: Path, name: str, text: str) -> Path:
    out = data_dir / "reports" / "cross" / f"{name}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out


def run(args: argparse.Namespace, paths: Callable[[], tuple[Path, Path]],
        prereg_extra: Callable[[str, Path | None], dict | None]) -> int:
    warehouse, research = paths()
    data_dir = warehouse.parent
    cross_path = data_dir / "cross.duckdb"
    now = datetime.now(VN_TZ).replace(microsecond=0)
    if args.cross_command == "build":
        try:
            result = build_cross(research, cross_path, now, warehouse_path=warehouse)
        except CrossBuildError as exc:
            print(f"Cross build failed: {exc}", file=sys.stderr)
            return 4
        print(f"Cross build {result.build_id} done in {result.seconds}s")
        for table, n in result.rows.items():
            print(f"  {table}: {n:,}")
        print("research.duckdb file hash unchanged.")
        return 0
    if not cross_path.exists():
        print(f"No cross database at {cross_path}; run `quant cross build`", file=sys.stderr)
        return 1
    if args.cross_command == "describe":
        con = duckdb.connect(str(cross_path), read_only=True)
        try:
            text = render_describe(con, now)
        finally:
            con.close()
        print(f"Report: {_write(data_dir, f'describe-{now:%Y%m%dT%H%M%S}', text)}")
        return 0
    extra = prereg_extra(args.period, args.prereg)
    if extra is None:
        return 2
    with ResultsStore(data_dir / "results.duckdb", research) as store:
        attach(store, cross_path)
        tests = tuple(t.strip() for t in args.tests.split(",") if t.strip())
        try:
            runs = run_all(store, args.period, ResearchParams(extra=extra), now, CrossParams(), args.final, tests)
        except ValueError as exc:
            print(f"Refused: {exc}", file=sys.stderr)
            return 2
        if not runs:
            print("Nothing run.")
            return 0
        text = render_cross_tests(store, runs, args.period, now)
    print(f"{len(runs)} runs. Report: {_write(data_dir, f'tests-{args.period}-{now:%Y%m%dT%H%M%S}', text)}")
    return 0
