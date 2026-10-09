"""End-to-end CLI run on an integration fixture (no token, no network, no real data).

The fixture extends the synthetic warehouse with the cases the unit tests cover one at a time: a rights
issue, sessions missing for one stock, an ADV gap (a run of missing rows), a delisted stock (DEL), sessions
without trades, a cash dividend, limit sessions and a data-error jump (all from tests/research/synthetic.py).
The real commands run as subprocesses: fireant validate -> quant build -> quant daily -> quant audit pit
-> quant registry list; then a broken latest session must stop validation (exit 1).
"""

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from fireant_crawler.store.warehouse import Warehouse
from tests.research.synthetic import build_synthetic_warehouse, calendar

NOW = datetime(2026, 10, 9, tzinfo=UTC)


def build_integration_warehouse(path: Path) -> None:
    build_synthetic_warehouse(path)
    days = calendar()
    with Warehouse(path) as wh:
        wh.upsert("corporate_actions", [{
            "event_id": 900001, "symbol": "STK", "company_name": "CTCP Stock", "event_type": 3,
            "event_type_name": "rights_issue", "title": "Phat hanh CP cho CDHH, ty le 100:15, gia 15000",
            "ex_date": datetime.combine(days[220], datetime.min.time()), "record_date": None, "payment_date": None,
            "period_year": None, "installment": None, "cash_per_share_vnd": None, "ratio_held": 100.0,
            "ratio_received": 15.0, "issue_price_vnd": 15000.0, "title_parsed": True, "fetched_at": NOW}])
        con = wh.connection
        con.execute("DELETE FROM quotes_daily WHERE symbol = 'UPC' AND date IN (?, ?, ?)", days[60:63])  # missing days
        con.execute("DELETE FROM quotes_daily WHERE symbol = 'FUETF' AND date BETWEEN ? AND ?",          # ADV gap
                    [days[230], days[255]])


def _env(tmp_path: Path) -> dict:
    env_file = tmp_path / ".env"
    env_file.write_text("FIREANT_TOKEN=\n")                       # no token: these commands must not need one
    env = {k: v for k, v in os.environ.items() if k not in ("FIREANT_TOKEN", "DATA_DIR", "ENV_FILE")}
    return env | {"DATA_DIR": str(tmp_path / "data"), "ENV_FILE": str(env_file)}


def _run(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", *args], env=env, capture_output=True, text=True, timeout=600)


def test_cli_pipeline_on_the_integration_fixture(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    build_integration_warehouse(data / "warehouse.duckdb")
    env = _env(tmp_path)
    validate = _run(env, "fireant_crawler.cli", "validate")
    assert validate.returncode == 0, validate.stdout + validate.stderr
    assert "latest_session_incomplete" in validate.stdout
    for args in (("build",), ("daily",), ("audit", "pit"), ("registry", "list")):
        proc = _run(env, "quant_research.cli", *args)
        assert proc.returncode == 0, (args, proc.stdout[-2000:], proc.stderr[-2000:])
    con = duckdb.connect(str(data / "research.duckdb"), read_only=True)
    try:
        upc_rows = con.execute("SELECT count(*) FROM daily_panel WHERE symbol = 'UPC'").fetchone()[0]
        costs = con.execute("SELECT count(*) FROM stock_trading_costs").fetchone()[0]
    finally:
        con.close()
    assert upc_rows > 0 and costs > 0
    assert list((data / "reports" / "research").glob("audit-pit-*.md"))
    assert list((data / "reports" / "daily").glob("*.md"))
    # a broken latest session: most stocks missing on the last VNINDEX date -> error-level finding, exit 1
    with Warehouse(data / "warehouse.duckdb") as wh:
        last = wh.connection.execute("SELECT max(date) FROM quotes_daily WHERE symbol = 'VNINDEX'").fetchone()[0]
        wh.connection.execute("DELETE FROM quotes_daily WHERE date = ? AND symbol IN ('STK', 'UPC')", [last])
    broken = _run(env, "fireant_crawler.cli", "validate")
    assert broken.returncode == 1 and "latest_session_incomplete" in broken.stdout
