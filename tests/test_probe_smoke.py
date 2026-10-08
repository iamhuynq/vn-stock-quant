"""Offline smoke test: the probe completes and renders a report against a fake API."""

import json
from datetime import UTC, date, datetime

import httpx

from fireant_crawler.client.fireant_client import FireAntClient
from fireant_crawler.client.rate_limiter import RateLimiter
from fireant_crawler.probe import Probe, render_report
from fireant_crawler.store.raw_store import RawStore

QUOTE = {"date": "2026-10-01T00:00:00", "symbol": "VOS", "priceBasic": 10.35, "priceClose": 10.5, "adjRatio": 1.0}


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/historical-quotes"):
        limit = int(request.url.params.get("limit", 20))
        offset = int(request.url.params.get("offset", 0))
        rows = [dict(QUOTE, date=f"2026-01-{i % 28 + 1:02d}T00:00:00") for i in range(offset, min(offset + limit, 1500))]
        return httpx.Response(200, json=rows[:1000])
    if path == "/symbols/FLC":
        return httpx.Response(200, json={"symbol": "FLC", "isListing": False, "exchange": "UPCOM"})
    if path == "/symbols/XYZ":
        return httpx.Response(404, json={})
    if path.startswith("/symbols/") and path.count("/") == 2 and path != "/symbols/search":
        return httpx.Response(200, json={"symbol": path.split("/")[-1], "type": "index", "isListing": True})
    if path == "/symbols/VOS/fundamental":
        return httpx.Response(200, json={"sharesOutstanding": 140_000_000})
    return httpx.Response(200, json=[])


def test_probe_runs_end_to_end(tmp_path):
    fixture = tmp_path / "a.json"
    fixture.write_text(json.dumps([QUOTE]), encoding="utf-8")
    client = FireAntClient("fake-token-1234567890", RateLimiter(1e6), transport=httpx.MockTransport(handler))
    now = datetime(2026, 10, 3, tzinfo=UTC)

    probe = Probe(client, RawStore(tmp_path), today=date(2026, 10, 3), fetched_at=now, fixture_path=fixture)
    sections = probe.run()
    report = render_report(probe, ["- token info"], now)

    assert not [s.title for s in sections if any(line.startswith("FAILED") for line in s.lines)]
    assert "| 1000 | 1000 |" in report and "| 2000 | 1000 |" in report
    assert "FLC | yes | False" in report
    assert probe.request_count > 20
    assert any((tmp_path / "raw" / "probe").rglob("*.json.gz"))
