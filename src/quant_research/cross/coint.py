"""Cointegration of same-industry pairs (doc 10): Engle-Granger formation, then spread events.

At each quarter end D: for liquid pairs in the same ICB level-3 industry, regress log price A on log
price B over the formation window ending at D. If the residual is stationary (Engle-Granger p below the
threshold) and beta > 0, follow the spread z-score over the next quarter with the formation's alpha,
beta, mean and std (nothing re-estimated with later data). An event is the day the spread first moves
beyond +/- z: the cheap leg is the long candidate (VN cash market: no short leg).
"""

import warnings
from collections.abc import Iterator

import numpy as np
from statsmodels.tsa.stattools import coint

from quant_research.cross.params import CrossParams
from quant_research.cross.snapshots import Panel


def _pairs_same_industry(panel: Panel, ids: np.ndarray) -> list[tuple[int, int]]:
    out = []
    for x in range(len(ids)):
        for y in range(x + 1, len(ids)):
            code = panel.l3[ids[x]]
            if code is not None and code == panel.l3[ids[y]]:
                out.append((int(ids[x]), int(ids[y])))
    return out


def formation(panel: Panel, a: int, b: int, start: int, end: int, params: CrossParams) -> dict | None:
    la, lb = panel.logp[start:end, a], panel.logp[start:end, b]
    ok = np.isfinite(la) & np.isfinite(lb)
    if ok.mean() < params.min_coverage:
        return None
    ya, yb = la[ok], lb[ok]
    beta, alpha = np.polyfit(yb, ya, 1)
    if beta <= 0:
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _t, p, _crit = coint(ya, yb, trend="c", maxlag=1, autolag=None)
    resid = ya - alpha - beta * yb
    sd = float(resid.std(ddof=1))
    if not np.isfinite(p) or sd <= 0:
        return None
    return {"alpha": float(alpha), "beta": float(beta), "mu": float(resid.mean()), "sigma": sd, "p": float(p)}


def run(panel: Panel, quarter_members: dict[np.datetime64, list[int]], params: CrossParams
        ) -> Iterator[tuple[str, dict]]:
    """Yields ("pair", row) for every tested pair and ("event", row) for spread events."""
    ends = sorted(quarter_members)
    for q, day in enumerate(ends):
        end = panel.index_of(day) + 1
        start = end - params.coint_window
        if start < 0:
            continue
        stop = panel.index_of(ends[q + 1]) + 1 if q + 1 < len(ends) else len(panel.dates)
        ids = np.sort(np.array(quarter_members[day]))     # fixed orientation (Engle-Granger is not symmetric)
        for a, b in _pairs_same_industry(panel, ids):
            f = formation(panel, a, b, start, end, params)
            if f is None:
                continue
            yield "pair", {"formation_date": day, "a": a, "b": b, **f}
            if f["p"] >= params.coint_p:
                continue
            yield from (("event", e) for e in _events(panel, a, b, f, end - 1, stop, day, params))


def _events(panel: Panel, a: int, b: int, f: dict, prev: int, stop: int, day, params: CrossParams) -> Iterator[dict]:
    spread = panel.logp[:, a] - f["alpha"] - f["beta"] * panel.logp[:, b]
    z = (spread - f["mu"]) / f["sigma"]
    for t in range(prev + 1, stop):
        if not (np.isfinite(z[t]) and np.isfinite(z[t - 1])):
            continue
        side = None
        if z[t] > params.coint_z >= z[t - 1]:
            side, long_leg = "b_cheap", b
        elif z[t] < -params.coint_z <= z[t - 1]:
            side, long_leg = "a_cheap", a
        if side is None:
            continue
        after = {f"z_after_{h}": float(z[t + h]) if t + h < len(z) and np.isfinite(z[t + h]) else None
                 for h in (10, 20)}
        yield {"symbol_id": long_leg, "date": panel.dates[t], "a": a, "b": b, "side": side, "z": float(z[t]),
               "formation_date": day, **after}
