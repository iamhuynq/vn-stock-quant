"""Portfolio construction (docs/portfolio-construction-plan.md): signal score -> eligibility -> ranking with a
buffer -> target weights -> constraints. Pure functions over one rebalance date.
"""

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Construction:
    n_names: int = 20
    entry_rank: int = 20               # a new name must rank inside this
    exit_rank: int = 20                # a held name is kept while it ranks inside this (buffer when > entry_rank)
    weighting: str = "equal"           # "equal" or "inverse_vol"
    max_position_weight: float = 0.10
    max_industry_weight: float = 0.30
    min_adv_value: float = 1e9
    max_participation: float = 0.05    # order value / ADV20 at the decision close

    def __post_init__(self) -> None:
        if not 0 < self.entry_rank <= self.exit_rank:
            raise ValueError("need 0 < entry_rank <= exit_rank")
        if self.weighting not in ("equal", "inverse_vol"):
            raise ValueError(f"unknown weighting {self.weighting!r}")


def ranks(scores: np.ndarray, eligible: np.ndarray) -> np.ndarray:
    """Rank 1 = highest score among eligible columns (ties by column order); 0 = not ranked."""
    out = np.zeros(len(scores), dtype=int)
    cols = np.flatnonzero(eligible & np.isfinite(scores))
    order = cols[np.lexsort((cols, -scores[cols]))]
    out[order] = np.arange(1, len(order) + 1)
    return out


def select(rank: np.ndarray, held: set[int], c: Construction) -> list[int]:
    """Held names still inside exit_rank are kept (best first); new names inside entry_rank fill the rest."""
    keep = sorted((j for j in held if 0 < rank[j] <= c.exit_rank), key=lambda j: rank[j])[:c.n_names]
    new = [int(j) for j in np.argsort(np.where(rank > 0, rank, np.iinfo(int).max))
           if 0 < rank[j] <= c.entry_rank and j not in held]
    return keep + new[:max(0, c.n_names - len(keep))]


def target_weights(chosen: list[int], c: Construction, sigma: np.ndarray, industry: np.ndarray) -> dict[int, float]:
    """Each of the n_names slots is worth 1 / n_names (empty slots stay cash). Then the position cap, then the
    industry cap; the excess of a cap goes to cash (never forced fully invested)."""
    if not chosen:
        return {}
    invested = len(chosen) / c.n_names
    if c.weighting == "inverse_vol":
        inv = np.array([1 / sigma[j] if np.isfinite(sigma[j]) and sigma[j] > 0 else np.nan for j in chosen])
        inv = np.where(np.isfinite(inv), inv, np.nanmedian(inv) if np.isfinite(inv).any() else 1.0)
        raw = inv / inv.sum() * invested
    else:
        raw = np.full(len(chosen), 1 / c.n_names)
    w = {j: min(float(x), c.max_position_weight) for j, x in zip(chosen, raw)}
    by_ind: dict = {}
    for j in chosen:
        by_ind.setdefault(industry[j] if industry[j] is not None else f"none:{j}", []).append(j)
    for names in by_ind.values():
        total = sum(w[j] for j in names)
        if total > c.max_industry_weight:
            scale = c.max_industry_weight / total
            for j in names:
                w[j] *= scale
    return w
