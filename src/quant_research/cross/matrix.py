"""Pairwise statistics on return matrices with missing values (rows = sessions, columns = stocks).

Everything is vectorized: one call computes all pairs from a few matrix products, so 200 x 200 pairs
per snapshot cost milliseconds. A pair uses only the sessions where both values are present.
"""

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform


def pairwise_corr(x: np.ndarray, y: np.ndarray | None = None, min_obs: int = 2) -> tuple[np.ndarray, np.ndarray]:
    """corr[i, j] = Pearson correlation of x[:, i] and y[:, j] over rows where both are finite.

    Returns (corr, n_obs). corr is NaN where fewer than min_obs rows overlap or a variance is zero.
    """
    y = x if y is None else y
    mx, my = np.isfinite(x), np.isfinite(y)
    x0, y0 = np.where(mx, x, 0.0), np.where(my, y, 0.0)
    fx, fy = mx.astype(float), my.astype(float)
    n = fx.T @ fy
    sx, sy = x0.T @ fy, fx.T @ y0
    sxx, syy = (x0 * x0).T @ fy, fx.T @ (y0 * y0)
    sxy = x0.T @ y0
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = sxy - sx * sy / n
        vx = sxx - sx * sx / n
        vy = syy - sy * sy / n
        corr = cov / np.sqrt(vx * vy)
    corr[(n < min_obs) | ~(vx > 1e-18) | ~(vy > 1e-18)] = np.nan
    return np.clip(corr, -1.0, 1.0), n.astype(np.int64)


def lag_corr(lead: np.ndarray, follow: np.ndarray, lag: int, min_obs: int = 2) -> tuple[np.ndarray, np.ndarray]:
    """corr[i, j] = corr(lead[t, i], follow[t + lag, j]): does stock i today relate to stock j later?"""
    if lag <= 0 or lag >= len(lead):
        shape = (lead.shape[1], follow.shape[1])
        return np.full(shape, np.nan), np.zeros(shape, dtype=np.int64)
    return pairwise_corr(lead[:-lag], follow[lag:], min_obs)


def upper_pairs(corr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(i, j, value) for i < j with a finite value."""
    i, j = np.triu_indices(corr.shape[0], k=1)
    v = corr[i, j]
    keep = np.isfinite(v)
    return i[keep], j[keep], v[keep]


def clusters(corr: np.ndarray, k: int) -> np.ndarray:
    """Hierarchical clustering (average linkage) on distance 1 - corr; missing correlations count as 0."""
    n = corr.shape[0]
    if n < 2 or k < 1:
        return np.ones(n, dtype=int)
    d = 1.0 - np.nan_to_num(corr, nan=0.0)
    d = (d + d.T) / 2
    np.fill_diagonal(d, 0.0)
    z = linkage(squareform(np.clip(d, 0.0, 2.0), checks=False), method="average")
    return fcluster(z, t=min(k, n), criterion="maxclust")


def adjusted_rand_index(a: np.ndarray, b: np.ndarray) -> float:
    """Agreement of two labelings beyond chance: 1 = identical, about 0 = unrelated."""
    _, ia = np.unique(a, return_inverse=True)
    _, ib = np.unique(b, return_inverse=True)
    table = np.zeros((ia.max() + 1, ib.max() + 1))
    np.add.at(table, (ia, ib), 1)
    comb = lambda x: x * (x - 1) / 2  # noqa: E731
    index = comb(table).sum()
    sa, sb = comb(table.sum(1)).sum(), comb(table.sum(0)).sum()
    expected = sa * sb / comb(len(a)) if len(a) > 1 else 0.0
    maximum = (sa + sb) / 2
    return float((index - expected) / (maximum - expected)) if maximum != expected else 1.0
