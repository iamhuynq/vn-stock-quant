"""Independent pure-Python reference implementation of the panel, features and targets.

Written from the plan's definitions with plain loops, sharing no code with the SQL, so agreement
between the two is real evidence that the SQL implements the plan.
"""

import math
from statistics import mean, median, stdev

INDICES = {"VNINDEX", "VN30", "HNXINDEX", "HNX30", "UPINDEX"}


def _div(a, b):
    return None if a is None or b in (None, 0) else a / b


def _window(values, end, n):
    """values[end-n+1 .. end] if all present and the window is full, else None."""
    if end - n + 1 < 0:
        return None
    win = values[end - n + 1:end + 1]
    return None if any(v is None for v in win) else win


def build_panel(quotes: list[dict], symbols: dict[str, dict]) -> dict[str, list[dict]]:
    by_symbol: dict[str, list[dict]] = {}
    for q in sorted(quotes, key=lambda r: (r["symbol"], r["date"])):
        info = symbols[q["symbol"]]
        if q["symbol"] in INDICES or info["is_fund"]:
            continue
        by_symbol.setdefault(q["symbol"], []).append(q)
    panel = {}
    for sym, rows in by_symbol.items():
        traded = [r["date"] for r in rows if r["total_volume"] > 0]
        first, last = min(traded), max(traded)
        kept = [r for r in rows if first <= r["date"] <= last and r["adj_ratio"] > 0
                and min(r["price_open"], r["price_high"], r["price_low"], r["price_close"]) > 0]
        out = []
        for r in kept:
            a = r["adj_ratio"]
            deal_value = r["total_value"] - r["putthrough_value"] if r["total_value"] >= r["putthrough_value"] else None
            out.append({**r, "adj_open": r["price_open"] / a, "adj_high": r["price_high"] / a,
                        "adj_low": r["price_low"] / a, "adj_close": r["price_close"] / a,
                        "deal_value": deal_value,
                        "vwap_deal": deal_value / (r["deal_volume"] * r["unit"]) if r["deal_volume"] > 0 and deal_value and deal_value > 0 else None})
        panel[sym] = out
    return panel


def market(quotes: list[dict]) -> dict:
    rows = sorted((q for q in quotes if q["symbol"] == "VNINDEX"), key=lambda r: r["date"])
    closes = [r["price_close"] / r["adj_ratio"] for r in rows]
    out = {}
    rets = [None] + [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
    vols = []
    for i, r in enumerate(rows):
        ma50 = mean(closes[i - 49:i + 1]) if i >= 49 else None
        ma200 = mean(closes[i - 199:i + 1]) if i >= 199 else None
        w = _window(rets, i, 20)
        vol20 = stdev(w) if w else None
        vols.append(vol20)
        vw = _window(vols, i, 250)
        med = median(vw) if vw else None
        regime = None
        if ma50 is not None and ma200 is not None:
            regime = "Bull" if closes[i] > ma200 and ma50 > ma200 else "Bear" if closes[i] < ma200 and ma50 < ma200 else "Sideway"
        out[r["date"]] = {
            "close": closes[i], "open": r["price_open"] / r["adj_ratio"],
            **{f"ret_{n}": (closes[i] / closes[i - n] - 1 if i >= n else None) for n in (1, 3, 5, 10, 20)},
            "market_regime": regime,
            "trend_regime": None if ma200 is None else ("above_ma200" if closes[i] > ma200 else "below_ma200"),
            "vol_regime": None if med is None else ("high" if vol20 > med else "low"),
        }
    return out


def features(panel: dict[str, list[dict]], mkt: dict) -> dict[tuple, dict]:
    out = {}
    for sym, rows in panel.items():
        close = [r["adj_close"] for r in rows]
        value = [r["deal_value"] for r in rows]
        logv = [None if v is None else math.log(1 + v) for v in value]
        ret1 = [None] + [close[i] / close[i - 1] - 1 for i in range(1, len(rows))]
        fnet = [r["buy_foreign_value"] - r["sell_foreign_value"] for r in rows]
        tr = [None] + [max(rows[i]["adj_high"] - rows[i]["adj_low"], abs(rows[i]["adj_high"] - close[i - 1]),
                           abs(rows[i]["adj_low"] - close[i - 1])) for i in range(1, len(rows))]
        for i, r in enumerate(rows):
            m = mkt.get(r["date"], {})
            f = {f"return_{n}d": (close[i] / close[i - n] - 1 if i >= n else None) for n in (1, 3, 5, 10, 20)}
            f["excess_return_5d"] = None if f["return_5d"] is None or m.get("ret_5") is None else f["return_5d"] - m["ret_5"]
            for n in (5, 20):
                base = _window(value, i - 1, n)
                f[f"volume_ratio_{n}"] = _div(value[i], mean(base)) if base else None
            f["volume_change"] = None if i == 0 or not value[i - 1] else value[i] / value[i - 1] - 1
            base = _window(logv, i - 1, 20)
            sd = stdev(base) if base else None
            f["volume_zscore_20"] = (logv[i] - mean(base)) / sd if base and sd else None
            for n in (5, 20):
                w = _window(ret1, i, n)
                f[f"volatility_{n}"] = stdev(w) if w else None
            w = _window(tr, i, 14)
            f["atr_14_pct"] = mean(w) / close[i] if w else None
            f["high_low_range"] = (r["adj_high"] - r["adj_low"]) / close[i]
            f["gap"] = r["adj_open"] / close[i - 1] - 1 if i else None
            f["close_position"] = _div(close[i] - r["adj_low"], r["adj_high"] - r["adj_low"])
            f["close_vs_avg_price"] = _div(r["price_close"] - r["vwap_deal"], r["vwap_deal"]) if r["vwap_deal"] else None
            bq, sq, bc, sc = r["buy_quantity"], r["sell_quantity"], r["buy_count"], r["sell_count"]
            f["order_imbalance"] = _div(bq - sq, bq + sq)
            f["volume_imbalance"] = _div(bc - sc, bc + sc)
            f["buy_pressure"] = _div(bq, r["deal_volume"]) if bq + sq > 0 else None
            f["sell_pressure"] = _div(sq, r["deal_volume"]) if bq + sq > 0 else None
            f["buy_sell_ratio"] = _div(bq, sq)
            f["foreign_net_value"] = fnet[i]
            for n in (3, 5, 20):
                w = _window(fnet, i, n)
                f[f"foreign_net_{n}d"] = sum(w) if w else None
            v20 = _window(value, i, 20)
            f["foreign_net_ratio_20"] = _div(f["foreign_net_20d"], sum(v20)) if v20 else None
            f["foreign_intensity"] = _div(r["buy_foreign_value"] + r["sell_foreign_value"], r["total_value"])
            f["adv_value_20"] = mean(v20) if v20 else None
            f["market_regime"] = m.get("market_regime")
            out[(sym, r["date"])] = f
    return out


def targets(panel: dict[str, list[dict]], mkt: dict) -> dict[tuple, dict]:
    out = {}
    for sym, rows in panel.items():
        n = len(rows)
        for i, r in enumerate(rows):
            c0 = rows[i]["adj_close"]
            t = {}
            for h in (1, 3, 5, 10):
                t[f"fwd_ret_close_{h}d"] = rows[i + h]["adj_close"] / c0 - 1 if i + h < n else None
            o1 = rows[i + 1]["adj_open"] if i + 1 < n else None
            for h in (3, 5, 10, 20):
                t[f"fwd_ret_exec_{h}d"] = rows[i + h]["adj_close"] / o1 - 1 if i + h < n else None
            for h in (5, 10, 20):
                if i + h < n:
                    m1, mh = mkt.get(rows[i + 1]["date"]), mkt.get(rows[i + h]["date"])
                    t[f"fwd_excess_exec_{h}d"] = (t[f"fwd_ret_exec_{h}d"] - (mh["close"] / m1["open"] - 1)) if m1 and mh else None
                else:
                    t[f"fwd_excess_exec_{h}d"] = None
            nxt = rows[i + 1:i + 6]
            t["fwd_max_return_5d"] = max(x["adj_high"] for x in nxt) / o1 - 1 if len(nxt) == 5 else None
            t["fwd_max_drawdown_5d"] = min(x["adj_low"] for x in nxt) / o1 - 1 if len(nxt) == 5 else None
            t["y_up3_5d"] = None if t["fwd_ret_close_5d"] is None else t["fwd_ret_close_5d"] > 0.03
            out[(sym, r["date"])] = t
    return out
