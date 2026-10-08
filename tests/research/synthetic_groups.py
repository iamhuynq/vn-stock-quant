"""Synthetic warehouse with planted GROUP relations (Phase 4b), built through the real Warehouse class.

Industries (ICB level 2), 6 stocks each unless noted:
- A (5020): an independent industry factor.
- B (3020): true follower; its intraday move contains 0.6 x A's factor of the previous session, so the
  relation shows on open-to-close returns too.
- S (4010): stale follower; the previous session's A factor arrives in the OPENING GAP only, so the
  relation shows on close-to-close returns but not on open-to-close returns.
- D (4510): persistent positive drift (industry momentum).
- N1 (6510), N2 (1010): noise industries.
- T (1510): only 4 stocks: too few for an index.
"""

import random
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from fireant_crawler.store.warehouse import Warehouse
from tests.research.synthetic import _quote
from tests.research.synthetic_cross import calendar

NOW = datetime(2026, 10, 4, tzinfo=UTC)
GROUPS = {"A": "5020", "B": "3020", "S": "4010", "D": "4510", "N1": "6510", "N2": "1010", "T": "1510"}
SIZES = {"T": 4}


def members() -> dict[str, str]:
    return {f"{g}{i}": code for g, code in GROUPS.items() for i in range(1, SIZES.get(g, 6) + 1)}


def build_group_warehouse(path: Path, seed: int = 5, n: int = 760) -> None:
    days = calendar(n=n)
    rng = np.random.default_rng(seed)
    rnd = random.Random(seed)
    mkt = rng.normal(0.0002, 0.008, n)
    f = {g: rng.normal(0, 0.012, n) for g in GROUPS}
    f["B"][1:] = 0.6 * f["A"][:-1] + rng.normal(0, 0.006, n - 1)
    f["D"] = f["D"] + 0.004
    gap = {g: np.zeros(n) for g in GROUPS}
    gap["S"][1:] = 0.6 * f["A"][:-1]                                  # stale catch-up at the open
    icb = []
    for code in set(GROUPS.values()):
        icb += [(code[:2], 1), (code, 2), (code + "10", 3), (code + "1010", 4)]
    with Warehouse(path) as wh:
        wh.ensure_schema_for_write()
        wh.upsert("icb_industries", [{"industry_code": c, "level": lv, "name": f"ICB {c}", "description": None,
                                      "fetched_at": NOW} for c, lv in icb])
        syms = [{"symbol": s, "fetched_at": NOW, "name": f"CTCP {s}", "exchange": "HSX", "type": "stock",
                 "is_listing": True, "industry_code": None, "icb_code": code + "1010", "source": "search"}
                for s, code in members().items()]
        syms.append({"symbol": "VNINDEX", "fetched_at": NOW, "name": "VNINDEX", "exchange": None, "type": "index",
                     "is_listing": True, "industry_code": None, "icb_code": None, "source": "search"})
        wh.upsert("symbols", syms)
        quotes = _series("VNINDEX", days, np.zeros(n), mkt, 1000.0, 1e6, rnd)
        for s, code in members().items():
            g = next(k for k, v in GROUPS.items() if v == code)
            intraday = mkt + f[g] + rng.normal(0, 0.01, n)
            quotes += _series(s, days, gap[g], intraday, 20.0, 2e5, rnd)
        wh.upsert("quotes_daily", quotes)


def _series(symbol, days, gap, intraday, base, volume, rnd) -> list[dict]:
    rows, prev = [], base
    for i, day in enumerate(days):
        open_ = round(prev * float(np.exp(gap[i])), 4)
        close = round(open_ * float(np.exp(intraday[i])), 4)
        hi, lo = max(open_, close) * 1.003, min(open_, close) * 0.997
        rows.append(_quote(symbol, day, open_, hi, lo, close, prev, 1.0, volume, rnd))
        prev = close
    return rows
