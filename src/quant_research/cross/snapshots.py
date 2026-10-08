"""Monthly correlation snapshots, centrality, clusters and yearly lead-lag matrices (pure numpy).

Point in time: a snapshot at month end D uses only sessions up to D, and the members chosen at D.
Lead-lag "formation" statistics of year Y use only year Y; the "test" statistics of the same pairs use
year Y + 1 and are outcomes, never inputs of a selection.
"""

from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np

from quant_research.cross.matrix import clusters, lag_corr, pairwise_corr, upper_pairs
from quant_research.cross.params import CrossParams


@dataclass
class Panel:
    dates: np.ndarray            # datetime64[D], all market sessions, ascending
    symbols: list[str]           # column order; symbol id = position
    ex_cc: np.ndarray            # close-to-close return minus VNINDEX (NaN: no trade, stale, flagged)
    ex_oc: np.ndarray            # open-to-close return minus VNINDEX open-to-close
    logp: np.ndarray             # log adjusted close (NaN on non-traded sessions)
    l2: np.ndarray               # ICB level-2 code per symbol (object, may be None)
    l3: np.ndarray               # ICB level-3 code per symbol

    def index_of(self, day: np.datetime64) -> int:
        return int(np.searchsorted(self.dates, day))


def _covered(block: np.ndarray, min_coverage: float) -> np.ndarray:
    return np.isfinite(block).mean(axis=0) >= min_coverage


def correlation_snapshots(panel: Panel, members: dict[np.datetime64, list[int]], params: CrossParams
                          ) -> Iterator[tuple[str, dict[str, np.ndarray]]]:
    """Yields ("corr" | "centrality" | "cluster", column arrays) per snapshot and window."""
    for month_end, cols in members.items():
        end = panel.index_of(month_end) + 1                       # include month_end itself
        for w in params.windows:
            start = end - w
            if start < 0 or len(cols) < 3:
                continue
            ids = np.sort(np.array(cols))                         # canonical pair orientation: a < b by id
            block = panel.ex_cc[start:end][:, ids]
            keep = _covered(block, params.min_coverage)
            ids, block = ids[keep], block[:, keep]
            if len(ids) < 3:
                continue
            corr, _ = pairwise_corr(block, min_obs=int(0.8 * w))
            i, j, v = upper_pairs(corr)
            day = np.full(len(v), month_end)
            yield "corr", {"month_end": day, "win": np.full(len(v), w, dtype=np.int16),
                           "a": ids[i].astype(np.int32), "b": ids[j].astype(np.int32), "corr": v.astype(np.float32)}
            off = corr.copy()
            np.fill_diagonal(off, np.nan)
            with np.errstate(invalid="ignore"):
                avg = np.nanmean(np.where(np.isfinite(off), off, np.nan), axis=1)
            yield "centrality", {"month_end": np.full(len(ids), month_end), "win": np.full(len(ids), w, dtype=np.int16),
                                 "symbol_id": ids.astype(np.int32), "avg_corr": avg.astype(np.float32),
                                 "n_peers": np.isfinite(off).sum(axis=1).astype(np.int32)}
            if w == params.cluster_window:
                codes = panel.l2[ids]
                k = len({c for c in codes if c is not None}) or 1
                yield "cluster", {"month_end": np.full(len(ids), month_end), "symbol_id": ids.astype(np.int32),
                                  "cluster": clusters(corr, k).astype(np.int32),
                                  "industry_l2_code": np.array(codes, dtype=object)}


def leadlag_pairs(panel: Panel, year_members: dict[int, list[int]], params: CrossParams,
                  min_form: int = 100, min_test: int = 60) -> Iterator[dict[str, np.ndarray]]:
    """Directed pairs (lead -> follow) per formation year and lag: corr in year Y and the same pairs in Y + 1."""
    years = panel.dates.astype("datetime64[Y]").astype(int) + 1970
    for year, cols in year_members.items():
        form, test = years == year, years == year + 1
        if not test.any() or len(cols) < 3:
            continue
        ids = np.array(cols)
        f_cc = panel.ex_cc[form][:, ids]
        t_cc, t_oc = panel.ex_cc[test][:, ids], panel.ex_oc[test][:, ids]
        for lag in params.lags:
            cf, nf = lag_corr(f_cc, f_cc, lag, min_form)
            ct, nt = lag_corr(t_cc, t_cc, lag, min_test)
            co, _ = lag_corr(t_cc, t_oc, lag, min_test)       # tradable view: follower's next open-to-close
            np.fill_diagonal(cf, np.nan)
            li, fi = np.nonzero(np.isfinite(cf))
            yield {"form_year": np.full(len(li), year, dtype=np.int16), "lag": np.full(len(li), lag, dtype=np.int8),
                   "lead": ids[li].astype(np.int32), "follow": ids[fi].astype(np.int32),
                   "corr_form": cf[li, fi].astype(np.float32), "n_form": nf[li, fi].astype(np.int32),
                   "corr_test_cc": ct[li, fi].astype(np.float32), "corr_test_oc": co[li, fi].astype(np.float32),
                   "n_test": nt[li, fi].astype(np.int32)}
