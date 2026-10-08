"""Job tests: fake HTTP API (fixtures) + real DuckDB + real raw store on disk."""

from datetime import date, datetime
from functools import partial
from zoneinfo import ZoneInfo

import httpx
import pytest

from tests.fake_api import FakeFireAnt
from fireant_crawler.client.fireant_client import AuthError, FireAntClient
from fireant_crawler.client.rate_limiter import RateLimiter
from fireant_crawler.jobs import plans
from fireant_crawler.jobs.rebuild import rebuild
from fireant_crawler.jobs.runner import JobContext, Task, run_tasks
from fireant_crawler.store.raw_store import RawStore
from fireant_crawler.store.state import CrawlState
from fireant_crawler.store.warehouse import Warehouse

VN = ZoneInfo("Asia/Ho_Chi_Minh")


@pytest.fixture
def api():
    return FakeFireAnt()


@pytest.fixture
def make_ctx(tmp_path, api):
    opened = []

    def factory(run_at=datetime(2026, 10, 3, 18, 0, tzinfo=VN)):
        client = FireAntClient("fake-token-1234567890", RateLimiter(1e6), max_retries=2,
                               transport=api.transport(), sleep=lambda _s: None)
        wh = Warehouse(tmp_path / "warehouse.duckdb")
        wh.init_schema()
        opened.append((client, wh))
        logs: list[str] = []
        ctx = JobContext(client=client, raw=RawStore(tmp_path), warehouse=wh, state=CrawlState(wh),
                         run_at=run_at, today=run_at.date(), log=logs.append)
        ctx.logs = logs  # type: ignore[attr-defined]
        return ctx

    yield factory
    for client, wh in opened:
        client.close()
        wh.close()


def run(ctx, job, mode="backfill", symbols=None, force=False):
    total = None
    for batch in plans.plan(ctx, job, mode, symbols):
        stats = run_tasks(ctx, batch, force=force)
        total = stats if total is None else total
        if total is not stats:
            total.counts.update(stats.counts)
    return total


def scalar(ctx, sql, params=()):
    return ctx.warehouse.connection.execute(sql, list(params)).fetchone()[0]


def test_backfill_all_jobs(make_ctx, api):
    ctx = make_ctx()
    run(ctx, "corporate_actions")
    run(ctx, "universe")
    run(ctx, "icb")
    run(ctx, "quotes", symbols=["VOS", "VNINDEX", "FLC"])
    run(ctx, "report_marks", symbols=["VOS"])
    run(ctx, "fundamental", symbols=["VOS"])

    wh = ctx.warehouse
    assert wh.count("corporate_actions") == len(api.events)
    assert scalar(ctx, "SELECT count(*) FROM quotes_daily WHERE symbol = 'VOS'") == 40
    assert wh.count("report_marks") == 38 and wh.count("fundamental_snapshots") == 1
    assert wh.count("icb_industries") == 6
    assert scalar(ctx, "SELECT exchange FROM symbols_latest WHERE symbol = 'VOS'") == "HSX"
    delisted = plans.delisted_candidates(ctx)
    assert "VOS" not in delisted and delisted
    assert scalar(ctx, "SELECT count(*) FROM symbols_latest WHERE source = 'symbol' AND type = 'stock'") == len(delisted)
    assert "VOS" in plans.stock_symbols(ctx, listed_only=True)
    assert scalar(ctx, "SELECT count(*) FROM crawl_state WHERE status <> 'done'") == 0
    assert scalar(ctx, "SELECT count(*) FROM crawl_log") == len(api.calls)


def test_backfill_is_resumable_and_skips_done_tasks(make_ctx, api):
    ctx = make_ctx()
    run(ctx, "quotes", symbols=["VOS", "VNINDEX"])
    calls = len(api.calls)
    stats = run(ctx, "quotes", symbols=["VOS", "VNINDEX"])
    assert stats.counts["already_done"] == 2 and len(api.calls) == calls
    run(ctx, "quotes", symbols=["VOS"], force=True)
    assert len(api.calls) == calls + 1
    assert scalar(ctx, "SELECT count(*) FROM quotes_daily WHERE symbol = 'VOS'") == 40


def test_pagination(make_ctx, api, monkeypatch):
    monkeypatch.setattr(plans, "PAGE_SIZE", 15)
    ctx = make_ctx()
    run(ctx, "quotes", symbols=["VOS"])
    assert api.calls.count("/symbols/VOS/historical-quotes") == 3
    assert scalar(ctx, "SELECT count(*) FROM quotes_daily WHERE symbol = 'VOS'") == 40
    assert len(ctx.raw.iter_files("quotes")) == 3


def test_failure_is_recorded_and_run_continues(make_ctx, api):
    api.fail_status["/symbols/VNINDEX/historical-quotes"] = 500
    ctx = make_ctx()
    stats = run(ctx, "quotes", symbols=["VNINDEX", "VOS"])
    assert stats.counts["failed"] == 1 and stats.counts["done"] == 1
    state = CrawlState(ctx.warehouse)
    assert state.status("quotes", "VNINDEX", "full") == "failed"
    assert state.status("quotes", "VOS", "full") == "done"

    del api.fail_status["/symbols/VNINDEX/historical-quotes"]
    run(ctx, "quotes", symbols=["VNINDEX", "VOS"])
    assert state.status("quotes", "VNINDEX", "full") == "done"


def test_auth_error_stops_run_without_marking_done(make_ctx, api):
    api.fail_status["/symbols/VOS/historical-quotes"] = 401
    ctx = make_ctx()
    with pytest.raises(AuthError):
        run(ctx, "quotes", symbols=["VOS", "VNINDEX"])
    assert CrawlState(ctx.warehouse).status("quotes", "VOS", "full") is None
    assert "/symbols/VNINDEX/historical-quotes" not in api.calls


def test_update_refetches_full_history_when_adj_ratio_changes(make_ctx, api):
    ctx = make_ctx()
    run(ctx, "quotes", symbols=["VOS"])
    newest = dict(api.quotes["VOS"][0], date="2026-09-07T00:00:00", adjRatio=1.0)
    api.quotes["VOS"] = [newest] + [dict(r, adjRatio=1.2) for r in api.quotes["VOS"]]

    ctx2 = make_ctx(datetime(2026, 10, 4, 18, 0, tzinfo=VN))
    run(ctx2, "quotes", mode="update", symbols=["VOS"])
    assert any("full refetch" in line for line in ctx2.logs)
    assert scalar(ctx2, "SELECT adj_ratio FROM quotes_daily WHERE symbol = 'VOS' AND date = DATE '2026-07-08'") == 1.2
    assert scalar(ctx2, "SELECT count(*) FROM quotes_daily WHERE symbol = 'VOS'") == 41


def test_update_without_corporate_action_fetches_only_window(make_ctx, api):
    ctx = make_ctx()
    run(ctx, "quotes", symbols=["VOS"])
    before = len(api.calls)
    ctx2 = make_ctx(datetime(2026, 10, 4, 18, 0, tzinfo=VN))
    run(ctx2, "quotes", mode="update", symbols=["VOS"])
    assert len(api.calls) == before + 1
    assert not any("full refetch" in line for line in ctx2.logs)


def test_update_skips_stale_delisted_symbol(make_ctx, api):
    ctx = make_ctx()
    run_tasks(ctx, [Task("universe", "FLC", "info", partial(plans._symbol_info, "FLC"))])
    run(ctx, "quotes", symbols=["FLC"])
    assert scalar(ctx, "SELECT exchange FROM symbols_latest WHERE symbol = 'FLC'") == "OTC"
    ctx2 = make_ctx(datetime(2026, 10, 4, 18, 0, tzinfo=VN))
    stats = run(ctx2, "quotes", mode="update", symbols=["FLC"])
    assert stats.counts["skipped"] == 1


def test_normalize_rebuild_reproduces_warehouse(make_ctx, api, tmp_path):
    ctx = make_ctx()
    run(ctx, "corporate_actions")
    run(ctx, "quotes", symbols=["VOS", "VNINDEX"])
    run(ctx, "report_marks", symbols=["VOS"])
    with Warehouse(tmp_path / "rebuilt.duckdb") as rebuilt:
        rebuilt.init_schema()
        counts = rebuild(ctx.raw, rebuilt, log=lambda _m: None)
        for table in ("quotes_daily", "corporate_actions", "report_marks", "adj_ratio_segments"):
            assert rebuilt.count(table) == ctx.warehouse.count(table), table
    assert counts["quotes.files"] == 2 and not any(k.endswith(".failed") for k in counts)
    assert rebuild(ctx.raw, None)["quotes.files"] == 2


def test_circuit_breaker_stops_after_consecutive_network_failures(make_ctx, api):
    from fireant_crawler.jobs.runner import NetworkDownError

    def down(_request):
        raise httpx.ConnectError("offline")
    ctx = make_ctx()
    ctx.client._http._transport = httpx.MockTransport(down)          # every request: network error
    tasks = [Task("quotes", f"S{i}", "full", partial(plans._quotes_full, f"S{i}")) for i in range(15)]
    with pytest.raises(NetworkDownError):
        run_tasks(ctx, tasks, breaker=10)
    failed = scalar(ctx, "SELECT count(*) FROM crawl_state WHERE status = 'failed'")
    assert failed == 10                                               # stopped early, the rest untouched


def test_breaker_resets_on_success_and_ignores_per_symbol_4xx(make_ctx, api):
    api.fail_status["/symbols/BAD/historical-quotes"] = 404
    ctx = make_ctx()
    tasks = [Task("quotes", "BAD", "full", partial(plans._quotes_full, "BAD"))] * 3
    stats = run_tasks(ctx, tasks, force=True, breaker=2)              # 404s are not network failures
    assert stats.counts["failed"] == 3


def test_offline_preflight_exits_without_touching_the_warehouse(tmp_path, monkeypatch):
    from fireant_crawler import cli

    def down(_request):
        raise httpx.ConnectError("offline")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FIREANT_TOKEN", "fake-token-1234567890")
    monkeypatch.setattr(cli, "_make_client", lambda s: FireAntClient(
        s.token, RateLimiter(1e6), max_retries=1, transport=httpx.MockTransport(down), sleep=lambda _s: None))
    assert cli.main(["update"]) == cli.EXIT_OFFLINE
    assert not (tmp_path / "warehouse.duckdb").exists()


class _Clock(datetime):
    current: datetime

    @classmethod
    def now(cls, tz=None):
        return cls.current.astimezone(tz) if tz else cls.current


def test_update_during_the_session_never_stores_the_live_row(tmp_path, monkeypatch, api):
    """Run at 10:00 on a trading day, then at 18:30: the in-progress session is fetched only once final."""
    import duckdb

    from fireant_crawler import cli
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FIREANT_TOKEN", "fake-token-1234567890")
    monkeypatch.setattr(cli, "_make_client", lambda s: FireAntClient(
        s.token, RateLimiter(1e6), max_retries=1, transport=api.transport(), sleep=lambda _s: None))
    monkeypatch.setattr(cli, "datetime", _Clock)

    def close_on(day):
        con = duckdb.connect(str(tmp_path / "warehouse.duckdb"), read_only=True)
        try:
            row = con.execute("SELECT price_close FROM quotes_daily WHERE symbol = 'VOS' AND date = ?", [day]).fetchone()
        finally:
            con.close()
        return row[0] if row else None

    _Clock.current = datetime(2026, 9, 4, 19, 0, tzinfo=VN)                  # Friday evening
    assert cli.main(["backfill", "--jobs", "quotes", "--symbols", "VOS"]) == 0
    live = dict(api.quotes["VOS"][0], date="2026-09-07T00:00:00", priceClose=11.1)
    api.quotes["VOS"].insert(0, live)                                        # Monday, still trading

    _Clock.current = datetime(2026, 9, 7, 10, 0, tzinfo=VN)
    assert cli.main(["update", "--jobs", "quotes", "--symbols", "VOS"]) == 0
    assert close_on(date(2026, 9, 7)) is None                                # endDate = Friday

    api.quotes["VOS"][0] = dict(live, priceClose=12.2)                       # the closing data
    _Clock.current = datetime(2026, 9, 7, 18, 30, tzinfo=VN)
    assert cli.main(["update", "--jobs", "quotes", "--symbols", "VOS"]) == 0
    assert close_on(date(2026, 9, 7)) == 12.2                                # not skipped as "already done"
