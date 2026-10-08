"""Synthetic warehouse with known traps, built through the real Phase 1 Warehouse class."""

import random
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fireant_crawler.store.warehouse import Warehouse

NOW = datetime(2026, 10, 4, tzinfo=UTC)
N_SESSIONS = 300
START = date(2023, 1, 2)
EX_DATE_INDEX = 150          # STK: cash dividend; adj_ratio steps from 1.08 to 1.0 here
ZERO_PRICE_INDEX = 40        # STK: source placeholder row with all-zero prices
LIMIT_UP_INDEX = 100         # STK: closes exactly at the HOSE ceiling
OPEN_LIMIT_INDEX = 101       # STK: opens at the ceiling (entry blocked for t = 100)
DELISTED_LAST_TRADE = 200    # DEL: forward-filled with zero volume after this session
JUMP_INDEX = 120             # UPC: price triples in one session (source error / relisting)


def calendar(start: date = START) -> list[date]:
    days, d = [], start
    while len(days) < N_SESSIONS:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


def _quote(symbol: str, day: date, o: float, h: float, low: float, c: float, basic: float, adj: float,
           volume: float, rng: random.Random) -> dict:
    deal_value = volume * (low + h) / 2 * 1000
    pt_volume = 1000.0 if rng.random() < 0.1 and volume else 0.0
    pt_value = pt_volume * c * 1000
    buy_q, sell_q = (rng.uniform(0.5, 2) * volume, rng.uniform(0.5, 2) * volume) if volume else (0.0, 0.0)
    return {
        "symbol": symbol, "date": day, "fetched_at": NOW,
        "price_open": o, "price_high": h, "price_low": low, "price_close": c,
        "price_average": (low + h) / 2, "price_basic": basic,
        "total_volume": volume + pt_volume, "deal_volume": volume, "putthrough_volume": pt_volume,
        "total_value": deal_value + pt_value, "putthrough_value": pt_value,
        "buy_foreign_quantity": rng.choice([0.0, 500.0, 1500.0]), "buy_foreign_value": rng.choice([0.0, 1e7, 3e7]),
        "sell_foreign_quantity": rng.choice([0.0, 700.0]), "sell_foreign_value": rng.choice([0.0, 2e7]),
        "buy_count": float(rng.randint(1, 50)) if volume else 0.0, "buy_quantity": buy_q,
        "sell_count": float(rng.randint(1, 50)) if volume else 0.0, "sell_quantity": sell_q,
        "adj_ratio": adj, "current_foreign_room": 1e6,
        "prop_trading_net_deal_value": 0.0, "prop_trading_net_pt_value": 0.0, "prop_trading_net_value": 0.0,
        "unit": 1000.0,
    }


def _series(symbol: str, days: list[date], seed: int, base_price: float, exchange_band: float) -> list[dict]:
    rng = random.Random(seed)
    rows, prev_close = [], base_price
    for i, day in enumerate(days):
        basic = prev_close
        adj = 1.08 if (symbol == "STK" and i < EX_DATE_INDEX) else 1.0
        if symbol == "STK" and i == EX_DATE_INDEX:
            basic = round(prev_close / 1.08, 2)          # reference price cut by the dividend
        c = round(basic * (1 + rng.uniform(-0.03, 0.03)), 2)
        if symbol == "STK" and i == LIMIT_UP_INDEX:
            c = round(int(basic * 1.07 / 0.05 + 1e-6) * 0.05, 2)  # HOSE ceiling, tick 0.05
        o = round(basic * (1 + rng.uniform(-0.01, 0.01)), 2)
        if symbol == "STK" and i == OPEN_LIMIT_INDEX:
            o = round(int(basic * 1.07 / 0.05 + 1e-6) * 0.05, 2)
            c = o
        if symbol == "UPC" and i == JUMP_INDEX:
            o = c = round(basic * 3, 2)
        h, low = max(o, c) * (1 + rng.uniform(0, 0.01)), min(o, c) * (1 - rng.uniform(0, 0.01))
        volume = float(rng.randint(1, 100) * 1000)
        if symbol == "DEL" and i > DELISTED_LAST_TRADE:
            o = h = low = c = basic = prev_close
            volume = 0.0
        row = _quote(symbol, day, o, h, low, c, basic, adj, volume, rng)
        if symbol == "STK" and i == ZERO_PRICE_INDEX:
            row.update(price_open=0.0, price_high=0.0, price_low=0.0, price_close=0.0, price_basic=0.0,
                       total_volume=0.0, deal_volume=0.0, total_value=0.0, putthrough_volume=0.0, putthrough_value=0.0)
        else:
            prev_close = c
        rows.append(row)
    return rows


def build_synthetic_warehouse(path: Path, start: date = START) -> None:
    days = calendar(start)
    with Warehouse(path) as wh:
        wh.ensure_schema_for_write()
        icb = [("50", 1, "L1"), ("5020", 2, "L2"), ("502060", 3, "L3"), ("50206030", 4, "L4"),
               ("30", 1, "Fin"), ("3020", 2, "Fin2"), ("302050", 3, "Fin3"), ("30205000", 4, "ETF")]
        wh.upsert("icb_industries", [{"industry_code": c, "level": lv, "name": n, "description": None, "fetched_at": NOW}
                                     for c, lv, n in icb])
        symbols = [("STK", "CTCP Stock", "HSX", "stock", "50206030"), ("UPC", "CTCP Upcom", "UPCOM", "stock", "50206030"),
                   ("DEL", "CTCP Delisted", "OTC", "stock", "50206030"), ("FUETF", "Quỹ ETF Test", "HSX", "stock", "30205000"),
                   ("VNINDEX", "Chỉ số VNINDEX", None, "index", None)]
        wh.upsert("symbols", [{"symbol": s, "fetched_at": NOW, "name": n, "exchange": ex, "type": t, "is_listing": True,
                               "industry_code": None, "icb_code": icb_code, "source": "search"}
                              for s, n, ex, t, icb_code in symbols])
        quotes = (_series("STK", days, 1, 20.0, 0.07) + _series("UPC", days, 2, 8.0, 0.15)
                  + _series("DEL", days, 3, 5.0, 0.0) + _series("FUETF", days, 4, 15.0, 0.07)
                  + _series("VNINDEX", days, 5, 1200.0, 0.0))
        wh.upsert("quotes_daily", quotes)
