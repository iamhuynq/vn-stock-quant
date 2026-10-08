"""Synthetic warehouse with planted cross-stock relations, built through the real Warehouse class.

- Industry X (ICB 5020): leaders LX1-3 (high volume) and followers FX1-3; industry Y (ICB 3020): leaders
  LY1-3 and followers FY1-3. Each follower's excess return = 0.6 x its leader's excess return of the
  previous session + noise: six planted lag-1 relations.
- CA / CB (ICB 4010): log price of CB = log price of CA + a mean-reverting gap (cointegrated pair).
- ILLIQ: trades only every other session (a stale close); no two consecutive returns exist.
- N01-N08: independent noise stocks.
"""

import random
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np

from fireant_crawler.store.warehouse import Warehouse
from tests.research.synthetic import _quote

NOW = datetime(2026, 10, 4, tzinfo=UTC)
START = date(2020, 1, 2)
N_SESSIONS = 760
PLANTED = [("LX1", "FX1"), ("LX2", "FX2"), ("LX3", "FX3"), ("LY1", "FY1"), ("LY2", "FY2"), ("LY3", "FY3")]
INDUSTRY = {**{s: "50206030" for s in ("LX1", "LX2", "LX3", "FX1", "FX2", "FX3", "N01", "N02", "N03", "N04")},
            **{s: "30201030" for s in ("LY1", "LY2", "LY3", "FY1", "FY2", "FY3", "N05", "N06", "N07", "N08")},
            "CA": "40101010", "CB": "40101010", "ILLIQ": "40101010"}
ICB = [("50", 1, "Industrials"), ("5020", 2, "Ind2"), ("502060", 3, "Ind3"), ("50206030", 4, "Ind4"),
       ("30", 1, "Fin"), ("3020", 2, "Fin2"), ("302010", 3, "Fin3"), ("30201030", 4, "Fin4"),
       ("40", 1, "Cons"), ("4010", 2, "Cons2"), ("401010", 3, "Cons3"), ("40101010", 4, "Cons4")]


def calendar(start: date = START, n: int = N_SESSIONS) -> list[date]:
    days, d = [], start
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def log_returns(n: int, seed: int) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """(market log return, {symbol: log return}) with the planted structure."""
    rng = np.random.default_rng(seed)
    mkt = rng.normal(0.0003, 0.01, n)
    ex = {s: rng.normal(0, 0.02, n) for s in INDUSTRY}
    for lead, follow in PLANTED:
        ex[follow][1:] = 0.6 * ex[lead][:-1] + rng.normal(0, 0.012, n - 1)
    gap = np.zeros(n)
    for t in range(1, n):
        gap[t] = 0.85 * gap[t - 1] + rng.normal(0, 0.01)
    ex["CB"] = ex["CA"] + np.diff(gap, prepend=0.0)
    return mkt, ex


def _rows(symbol: str, days: list[date], r: np.ndarray, base: float, volume: float, rng: random.Random,
          trades=lambda i: True) -> list[dict]:
    rows, prev = [], base
    for i, day in enumerate(days):
        if not trades(i):
            rows.append(_quote(symbol, day, prev, prev, prev, prev, prev, 1.0, 0.0, rng))
            continue
        close = round(prev * float(np.exp(r[i])), 3)
        open_ = round(prev * (1 + rng.uniform(-0.003, 0.003)), 3)
        hi, lo = max(open_, close) * 1.005, min(open_, close) * 0.995
        rows.append(_quote(symbol, day, open_, hi, lo, close, prev, 1.0, volume, rng))
        prev = close
    return rows


def build_cross_warehouse(path: Path, seed: int = 11, days: list[date] | None = None) -> list[date]:
    days = days or calendar()
    n = len(days)
    mkt, ex = log_returns(n, seed)
    rng = random.Random(seed)
    with Warehouse(path) as wh:
        wh.ensure_schema_for_write()
        wh.upsert("icb_industries", [{"industry_code": c, "level": lv, "name": nm, "description": None,
                                      "fetched_at": NOW} for c, lv, nm in ICB])
        syms = [{"symbol": s, "fetched_at": NOW, "name": f"CTCP {s}", "exchange": "HSX", "type": "stock",
                 "is_listing": True, "industry_code": None, "icb_code": code, "source": "search"}
                for s, code in INDUSTRY.items()]
        syms.append({"symbol": "VNINDEX", "fetched_at": NOW, "name": "VNINDEX", "exchange": None, "type": "index",
                     "is_listing": True, "industry_code": None, "icb_code": None, "source": "search"})
        wh.upsert("symbols", syms)
        quotes = _rows("VNINDEX", days, mkt, 1000.0, 1e6, rng)
        for s in INDUSTRY:
            volume = 5e6 if s.startswith("L") else 2e5     # leaders: 25x the volume
            trades = (lambda i: i % 2 == 0) if s == "ILLIQ" else (lambda i: True)
            quotes += _rows(s, days, mkt + ex[s], 20.0, volume, rng, trades)
        wh.upsert("quotes_daily", quotes)
    return days
