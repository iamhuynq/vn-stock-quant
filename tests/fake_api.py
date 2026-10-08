"""In-memory fake of the FireAnt endpoints used by the jobs, backed by test fixtures."""

import json
from pathlib import Path

import httpx

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeFireAnt:
    def __init__(self) -> None:
        vos = load("quotes_vos_2026_07.json") + load("quotes_vos_2026_08.json")
        self.quotes: dict[str, list[dict]] = {
            "VOS": sorted(vos, key=lambda r: r["date"], reverse=True),
            "VNINDEX": load("quotes_vnindex_sample.json"),
            "FLC": load("quotes_flc_tail.json"),
        }
        self.events = load("events_sample.json")
        self.symbols = {
            "VOS": {"symbol": "VOS", "isListing": True, "name": "VOSCO", "exchange": "HSX", "type": "stock",
                    "industryCode": "2770", "icbCode": "50206060"},
            "FLC": load("symbol_flc.json"),
        }
        self.fail_status: dict[str, int] = {}   # path -> forced HTTP status
        self.calls: list[str] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path, params = request.url.path, request.url.params
        self.calls.append(path)
        if path in self.fail_status:
            return httpx.Response(self.fail_status[path], json={"message": "forced"})
        offset, limit = int(params.get("offset", 0)), int(params.get("limit", 20))

        if path == "/events/search":
            return httpx.Response(200, json=self.events[offset:offset + limit])
        if path == "/symbols/search":
            key = params.get("keywords", "")
            hits = [s for s in self.symbols.values() if s.get("exchange") in ("HSX", "HNX", "UPCOM") and key in s["symbol"] + s["name"]]
            return httpx.Response(200, json=hits)
        if path == "/instruments":
            return httpx.Response(200, json=[{"symbol": "VOS", "type": "stock", "exchange": "HSX"}])
        if path == "/icb":
            return httpx.Response(200, json=load("icb_sample.json"))
        parts = path.strip("/").split("/")
        if len(parts) == 2 and parts[0] == "symbols":
            code = parts[1]
            if code in self.symbols:
                return httpx.Response(200, json=self.symbols[code])
            if code.endswith(("INDEX", "30")):
                return httpx.Response(200, json={"symbol": code, "type": "index", "isListing": True, "name": code})
            return httpx.Response(200, json={"symbol": code, "type": "stock", "exchange": "OTC", "isListing": False, "name": code})
        if len(parts) == 3 and parts[2] == "historical-quotes":
            start, end = params["startDate"], params["endDate"]
            rows = [r for r in self.quotes.get(parts[1], []) if start <= r["date"][:10] <= end]
            return httpx.Response(200, json=rows[offset:offset + limit])
        if len(parts) == 3 and parts[2] == "timescale-marks":
            return httpx.Response(200, json=load("timescale_marks_vos.json") if parts[1] == "VOS" else [])
        if len(parts) == 3 and parts[2] == "fundamental":
            return httpx.Response(200, json=load("fundamental_vos.json"))
        return httpx.Response(404, json={})
