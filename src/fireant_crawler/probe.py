"""Step 0 probe: answer open questions about the FireAnt API before building the real jobs.

Every response is saved under data/raw/probe/ so findings can be re-checked offline.
"""

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fireant_crawler.client.fireant_client import AuthError, FireAntClient, FireAntError
from fireant_crawler.store.raw_store import RawStore

HISTORY_START = "2000-01-01"
LIMIT_CANDIDATES = (20, 100, 500, 1000, 2000, 5000)
INDEX_CANDIDATES = ("VNINDEX", "VN30", "HNXINDEX", "HNX30", "UPINDEX", "HNX-INDEX", "UPCOM-INDEX", "VN100", "VNXALL")
DELISTED_CANDIDATES = ("FLC", "ROS", "KLF", "ART", "TGG", "HAI", "OGC", "DLG")
EX_DATE_SYMBOL, EX_DATE = "VOS", "2026-10-01"
MAX_PAGES = 40


@dataclass
class Section:
    title: str
    lines: list[str] = field(default_factory=list)


def _table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return out


class Probe:
    def __init__(self, client: FireAntClient, raw: RawStore, today: date, fetched_at: datetime,
                 fixture_path: Path | None = None) -> None:
        self._client = client
        self._raw = raw
        self._today = today.isoformat()
        self._fetched_at = fetched_at
        self._fixture_path = fixture_path
        self._page_size = 20
        self._requests = 0
        self.rate_limit_headers: dict[str, str] = {}
        self.sections: list[Section] = []

    @property
    def request_count(self) -> int:
        return self._requests

    def run(self) -> list[Section]:
        checks: list[tuple[str, Callable[[Section], None]]] = [
            ("Max page size (historical-quotes)", self._check_limit),
            ("History depth and pagination", self._check_history),
            ("Index symbols", self._check_indices),
            ("Delisted symbols", self._check_delisted),
            (f"Adjusted or raw prices ({EX_DATE_SYMBOL} ex-date {EX_DATE})", self._check_ex_date),
            ("Retroactive changes vs a.json", self._check_fixture_drift),
            ("Instruments universe", self._check_instruments),
            ("Corporate actions (events/search)", self._check_events),
            ("Other endpoints", self._check_other),
        ]
        for title, check in checks:
            section = Section(title)
            self.sections.append(section)
            try:
                check(section)
            except AuthError:
                raise
            except FireAntError as exc:
                section.lines.append(f"FAILED: {exc}")
        return self.sections

    def _get(self, chunk: str, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self._client.get(path, params)
        self._requests += 1
        self._raw.write("probe", "all", chunk, response, self._fetched_at)
        self.rate_limit_headers.update(response.rate_limit_headers)
        return response.data

    def _quotes(self, chunk: str, symbol: str, start: str, end: str, limit: int, offset: int = 0) -> list[dict]:
        data = self._get(chunk, f"/symbols/{symbol}/historical-quotes",
                         {"startDate": start, "endDate": end, "offset": offset, "limit": limit})
        return data if isinstance(data, list) else []

    def _check_limit(self, s: Section) -> None:
        symbol = "VNINDEX"
        try:
            if not self._quotes("limit-check-VNINDEX", symbol, HISTORY_START, self._today, 20):
                symbol = "VOS"
        except AuthError:
            raise
        except FireAntError:
            symbol = "VOS"
        rows = []
        for limit in LIMIT_CANDIDATES:
            count = len(self._quotes(f"limit-{symbol}-{limit}", symbol, HISTORY_START, self._today, limit))
            rows.append([limit, count])
            if count == limit:
                self._page_size = limit
        s.lines += [f"Symbol used: {symbol}", ""] + _table(["limit requested", "rows returned"], rows)
        s.lines += ["", f"Page size chosen for the probe: {self._page_size}"]

    def _check_history(self, s: Section) -> None:
        rows = []
        for symbol in ("VOS", "VNINDEX"):
            dates: list[str] = []
            pages = 0
            for page in range(MAX_PAGES):
                batch = self._quotes(f"history-{symbol}-p{page}", symbol, HISTORY_START, self._today,
                                     self._page_size, offset=page * self._page_size)
                pages += 1
                dates += [str(r.get("date", ""))[:10] for r in batch]
                if len(batch) < self._page_size:
                    break
            order = "newest first" if dates and dates[0] > dates[-1] else "oldest first"
            dupes = len(dates) - len(set(dates))
            rows.append([symbol, len(dates), min(dates, default="-"), max(dates, default="-"), pages, dupes, order])
        s.lines += _table(["symbol", "rows", "first date", "last date", "pages", "duplicate dates", "order"], rows)

    def _symbol_info(self, chunk: str, symbol: str) -> dict | None:
        try:
            data = self._get(chunk, f"/symbols/{symbol}")
        except AuthError:
            raise
        except FireAntError:
            return None
        return data if isinstance(data, dict) else None

    def _check_indices(self, s: Section) -> None:
        rows = []
        for code in INDEX_CANDIDATES:
            info = self._symbol_info(f"index-{code}", code)
            rows.append([code, "yes" if info else "no", (info or {}).get("type", "-"),
                         (info or {}).get("exchange", "-"), (info or {}).get("name", "-")])
        s.lines += _table(["code", "found", "type", "exchange", "name"], rows)
        found = self._get("index-search", "/symbols/search", {"keywords": "INDEX", "type": "index", "limit": 100})
        if isinstance(found, list):
            s.lines += ["", f"/symbols/search?keywords=INDEX&type=index returned {len(found)}: "
                        + ", ".join(sorted(str(x.get("symbol")) for x in found))]

    def _check_delisted(self, s: Section) -> None:
        rows, delisted = [], []
        for code in DELISTED_CANDIDATES:
            info = self._symbol_info(f"delisted-{code}", code)
            listing = (info or {}).get("isListing", "-")
            rows.append([code, "yes" if info else "no", listing, (info or {}).get("exchange", "-")])
            if info and listing is False:
                delisted.append(code)
        s.lines += _table(["code", "found", "isListing", "exchange"], rows)
        for code in delisted[:2]:
            batch = self._quotes(f"delisted-quotes-{code}", code, HISTORY_START, self._today, 5)
            last = [str(r.get("date", ""))[:10] for r in batch]
            s.lines.append(f"- {code}: quotes served = {bool(batch)}, latest dates = {last}")

    def _check_ex_date(self, s: Section) -> None:
        batch = sorted(self._quotes("ex-date", EX_DATE_SYMBOL, "2026-09-15", self._today, 50),
                       key=lambda r: r.get("date", ""))
        rows, prev_close = [], None
        for r in batch:
            d = str(r.get("date", ""))[:10]
            basic = r.get("priceBasic")
            gap = round(basic - prev_close, 4) if isinstance(basic, (int, float)) and isinstance(prev_close, (int, float)) else "-"
            rows.append([d, basic, prev_close, gap, r.get("priceClose"), r.get("adjRatio")])
            prev_close = r.get("priceClose")
        s.lines += _table(["date", "priceBasic", "prev close", "basic - prev close", "close", "adjRatio"], rows)
        s.lines += ["", "Raw prices: expect basic - prev close of about -0.9 on the ex-date and unchanged history."]

    def _check_fixture_drift(self, s: Section) -> None:
        if not self._fixture_path or not self._fixture_path.exists():
            s.lines.append("Skipped: fixture a.json not found")
            return
        fixture = {r["date"][:10]: r for r in json.loads(self._fixture_path.read_text(encoding="utf-8"))}
        dates = sorted(fixture)
        live = {str(r["date"])[:10]: r for r in self._quotes("fixture-drift", "VOS", dates[0], dates[-1], 50)}
        changed: Counter[str] = Counter()
        for d, old in fixture.items():
            new = live.get(d)
            if new is None:
                changed["<missing row>"] += 1
                continue
            for key, value in old.items():
                if new.get(key) != value:
                    changed[key] += 1
        s.lines.append(f"Compared {len(fixture)} rows ({dates[0]} .. {dates[-1]}).")
        s.lines += ["No field changed."] if not changed else _table(
            ["field", "rows changed"], [[k, v] for k, v in changed.most_common()])
        sample = live.get(dates[-1], {})
        s.lines.append(f"Example {dates[-1]}: adjRatio was {fixture[dates[-1]].get('adjRatio')}, now {sample.get('adjRatio')}; "
                       f"close was {fixture[dates[-1]].get('priceClose')}, now {sample.get('priceClose')}")

    def _check_instruments(self, s: Section) -> None:
        data = self._get("instruments", "/instruments")
        if not isinstance(data, list):
            s.lines.append(f"Unexpected payload type: {type(data).__name__}")
            return
        s.lines.append(f"Total instruments: {len(data)}; fields: {sorted(data[0]) if data else []}")
        pairs = Counter((str(x.get("exchange")), str(x.get("type"))) for x in data)
        s.lines += _table(["exchange", "type", "count"], [[e, t, c] for (e, t), c in pairs.most_common()])

    def _check_events(self, s: Section) -> None:
        vos = self._get("events-VOS", "/events/search",
                        {"symbol": "VOS", "startDate": HISTORY_START, "endDate": "2026-12-31", "limit": 100})
        vos = vos if isinstance(vos, list) else []
        s.lines.append(f"VOS events since {HISTORY_START}: {len(vos)}; types: {dict(Counter(e.get('type') for e in vos))}")
        if vos:
            s.lines.append(f"Fields: {sorted(vos[0])}")
            s.lines.append(f"Example: {json.dumps(vos[0], ensure_ascii=False)[:300]}")
        market = self._get("events-market", "/events/search",
                           {"type": 1, "startDate": "2026-09-01", "endDate": "2026-10-31", "limit": 1000})
        n = len(market) if isinstance(market, list) else "n/a"
        s.lines.append(f"Market-wide cash dividends 2026-09-01..2026-10-31 with limit=1000: {n} rows")

    def _check_other(self, s: Section) -> None:
        marks = self._get("marks-VOS", "/symbols/VOS/timescale-marks",
                          {"startDate": HISTORY_START, "endDate": self._today})
        marks = marks if isinstance(marks, list) else []
        s.lines.append(f"- timescale-marks VOS: {len(marks)} rows, labels {dict(Counter(m.get('label') for m in marks))}, "
                       f"earliest {min((str(m.get('date'))[:10] for m in marks), default='-')}")
        dividends = self._get("dividends-VOS", "/symbols/VOS/dividends", {"count": 50})
        years = sorted(d.get("year") for d in dividends) if isinstance(dividends, list) else []
        s.lines.append(f"- dividends VOS count=50: {len(years)} rows, years {years[:3]}..{years[-3:]}")
        fundamental = self._get("fundamental-VOS", "/symbols/VOS/fundamental")
        if isinstance(fundamental, dict):
            keys = ("sharesOutstanding", "freeShares", "marketCap", "foreignOwnership", "eps", "pe")
            s.lines.append("- fundamental VOS: " + ", ".join(f"{k}={fundamental.get(k)}" for k in keys))
        icb = self._get("icb", "/icb")
        s.lines.append(f"- icb: {len(icb) if isinstance(icb, list) else 'n/a'} industries")


def render_report(probe: Probe, token_lines: list[str], generated_at: datetime) -> str:
    lines = [f"# FireAnt API probe - {generated_at.isoformat(timespec='seconds')}", "",
             "## Token", *token_lines, "",
             f"Requests sent: {probe.request_count}", "",
             "## Rate-limit headers observed",
             *([f"- {k}: {v}" for k, v in sorted(probe.rate_limit_headers.items())] or ["- none"]), ""]
    for section in probe.sections:
        lines += [f"## {section.title}", *section.lines, ""]
    return "\n".join(lines)
