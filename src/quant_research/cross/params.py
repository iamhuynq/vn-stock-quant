"""Settings of the cross-stock build (stored with every build and test run)."""

from dataclasses import asdict, dataclass

INDEX_SYMBOLS = ("VNINDEX", "VN30", "HNXINDEX", "HNX30", "UPINDEX")


@dataclass(frozen=True)
class CrossParams:
    universe_size: int = 200          # most liquid stocks per month end
    min_adv_value: float = 1e9        # and at least this 20-session average traded value (VND)
    min_coverage: float = 0.9         # share of a window's sessions a stock must have a return for
    windows: tuple[int, ...] = (60, 120, 250)
    cluster_window: int = 250
    lags: tuple[int, ...] = (1, 2, 3, 5)
    n_leaders: int = 3                # per ICB level-2 industry
    n_large: int = 30                 # large-cap basket for H2
    coint_window: int = 250
    coint_p: float = 0.05
    coint_z: float = 2.0
    start_year: int = 2006

    def as_dict(self) -> dict:
        return asdict(self)
