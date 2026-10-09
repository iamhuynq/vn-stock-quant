"""Exposure Engine (docs/provenance-exposure-plan.md, part 2): what a list of positions really holds.

Pure functions over a matrix of daily returns (rows = sessions, columns = symbols, NaN = no clean return)
and a market return series. Descriptive risk information; nothing here is a tested claim.
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TRADING_DAYS = 250
MIN_OBS_SHARE = 0.8


@dataclass
class Exposure:
    per_stock: pd.DataFrame                 # symbol, weight, beta, vol_ann, risk_share
    portfolio: dict                         # beta, vol_ann, n, effective_bets, effective_n_weights
    groups: dict[str, pd.DataFrame] = field(default_factory=dict)     # industry / cluster weights
    tilts: pd.DataFrame | None = None       # factor, weighted z-score
    missing: list[str] = field(default_factory=list)                  # symbols without enough data


def normalize(weights: dict[str, float]) -> pd.Series:
    w = pd.Series({k: float(v) for k, v in weights.items() if v and v > 0}, dtype=float)
    return w / w.sum() if w.sum() > 0 else w


def betas(returns: pd.DataFrame, market: pd.Series, min_obs: int) -> pd.Series:
    """OLS slope of each stock's daily return on the market return, sessions where both exist."""
    out = {}
    for s in returns:
        both = pd.concat([returns[s], market], axis=1).dropna()
        if len(both) >= min_obs and both.iloc[:, 1].var() > 0:
            out[s] = float(np.cov(both.iloc[:, 0], both.iloc[:, 1], ddof=1)[0, 1] / both.iloc[:, 1].var(ddof=1))
    return pd.Series(out, dtype=float)


def effective_bets(corr: np.ndarray) -> float:
    """Participation ratio of the correlation eigenvalues: N for independent stocks, 1 for identical ones."""
    lam = np.clip(np.linalg.eigvalsh((corr + corr.T) / 2), 0.0, None)
    return float(lam.sum() ** 2 / (lam ** 2).sum()) if (lam ** 2).sum() > 0 else float("nan")


def risk_shares(cov: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Share of portfolio variance per position: w_i (S w)_i / w'S w (sums to 1)."""
    total = float(w @ cov @ w)
    return (w * (cov @ w)) / total if total > 0 else np.full(len(w), np.nan)


def compute(returns: pd.DataFrame, market: pd.Series, weights: dict[str, float],
            labels: dict[str, dict[str, str]] | None = None, factor_z: pd.DataFrame | None = None) -> Exposure:
    """returns: sessions x symbols; weights: symbol -> weight (normalized here); labels: {"industry": {...}};
    factor_z: symbols x factors of cross-sectional z-scores (latest session)."""
    w_all = normalize(weights)
    min_obs = int(MIN_OBS_SHARE * len(returns))
    have = [s for s in w_all.index if s in returns and returns[s].notna().sum() >= min_obs]
    missing = [s for s in w_all.index if s not in have]
    w = normalize(w_all[have].to_dict()) if have else pd.Series(dtype=float)
    r = returns[have] if have else pd.DataFrame()
    if len(have) == 0:
        return Exposure(pd.DataFrame(columns=["symbol", "weight", "beta", "vol_ann", "risk_share"]),
                        {"beta": None, "vol_ann": None, "n": 0, "effective_bets": None,
                         "effective_n_weights": None}, missing=missing)
    cov = r.cov(min_periods=min_obs).to_numpy() * TRADING_DAYS
    cov = np.nan_to_num(cov)
    corr = r.corr(min_periods=min_obs).to_numpy()
    corr = np.where(np.isfinite(corr), corr, 0.0)
    np.fill_diagonal(corr, 1.0)
    b = betas(r, market, min_obs).reindex(have)
    wv = w.reindex(have).to_numpy()
    shares = risk_shares(cov, wv)
    per = pd.DataFrame({"symbol": have, "weight": wv, "beta": b.to_numpy(),
                        "vol_ann": np.sqrt(np.clip(np.diag(cov), 0, None)), "risk_share": shares})
    portfolio = {"beta": float(np.nansum(wv * b.to_numpy())), "vol_ann": float(np.sqrt(max(wv @ cov @ wv, 0.0))),
                 "n": len(have), "effective_bets": effective_bets(corr),
                 "effective_n_weights": float(1 / (wv ** 2).sum())}
    groups = {}
    for name, mapping in (labels or {}).items():
        g = pd.Series(wv, index=have).groupby(lambda s: mapping.get(s) or "unknown").sum()
        groups[name] = g.sort_values(ascending=False).rename("weight").reset_index().rename(columns={"index": name})
    tilts = None
    if factor_z is not None and not factor_z.empty:
        z = factor_z.reindex(have)
        tilts = pd.DataFrame({"factor": z.columns,
                              "weighted_z": [float(np.nansum(wv * z[c].to_numpy()) / max(np.sum(wv[z[c].notna()]), 1e-12))
                                             if z[c].notna().any() else None for c in z.columns],
                              "coverage": [float(np.sum(wv[z[c].notna()])) for c in z.columns]})
    return Exposure(per.sort_values("risk_share", ascending=False).reset_index(drop=True), portfolio, groups,
                    tilts, missing)
