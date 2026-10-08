"""results.duckdb: persistent store of research runs, statistics and the hypothesis log.

Never rebuilt. Runs are invalidated, not deleted, so the multiple-testing log stays complete.
The research database is attached READ_ONLY as `rs`.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any

import numpy as np

from fireant_crawler.store.locking import connect_with_retry

PERIODS = ("research", "validation", "holdout", "forward")

SCHEMA = """
CREATE TABLE IF NOT EXISTS pattern_definitions (
    name VARCHAR NOT NULL, version VARCHAR NOT NULL, where_sql VARCHAR NOT NULL, base VARCHAR,
    hypothesis VARCHAR, doc_ref VARCHAR, created_at TIMESTAMPTZ NOT NULL, PRIMARY KEY (name, version));
CREATE TABLE IF NOT EXISTS research_runs (
    run_id VARCHAR PRIMARY KEY, kind VARCHAR NOT NULL, pattern_name VARCHAR, pattern_version VARCHAR,
    period VARCHAR NOT NULL, params VARCHAR NOT NULL, feature_build_id VARCHAR, code_hash VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL, status VARCHAR NOT NULL, invalid_reason VARCHAR);
CREATE TABLE IF NOT EXISTS pattern_stats (
    run_id VARCHAR NOT NULL, horizon VARCHAR NOT NULL, segment VARCHAR NOT NULL,
    n_events BIGINT, n_dates BIGINT, mean DOUBLE, event_mean DOUBLE, median DOUBLE, win_rate DOUBLE,
    std DOUBLE, se DOUBLE, t DOUBLE, p DOUBLE, ci_low DOUBLE, ci_high DOUBLE, mean_after_cost DOUBLE,
    PRIMARY KEY (run_id, horizon, segment));
CREATE TABLE IF NOT EXISTS pattern_comparisons (
    run_id VARCHAR NOT NULL, horizon VARCHAR NOT NULL, base_name VARCHAR NOT NULL,
    n_dates BIGINT, diff_mean DOUBLE, se DOUBLE, t DOUBLE, p DOUBLE, PRIMARY KEY (run_id, horizon));
-- Primary test: pattern minus the whole filtered universe on the same dates (date-level lift).
CREATE TABLE IF NOT EXISTS pattern_lifts (
    run_id VARCHAR NOT NULL, horizon VARCHAR NOT NULL, n_dates BIGINT, pattern_mean DOUBLE,
    baseline_mean DOUBLE, baseline_win_rate DOUBLE, lift DOUBLE, se DOUBLE, t DOUBLE, p DOUBLE,
    PRIMARY KEY (run_id, horizon));
CREATE TABLE IF NOT EXISTS pattern_occurrences (
    run_id VARCHAR NOT NULL, symbol VARCHAR NOT NULL, date DATE NOT NULL, market_regime VARCHAR,
    exchange_now VARCHAR, out_5d DOUBLE, out_10d DOUBLE, out_20d DOUBLE, PRIMARY KEY (run_id, symbol, date));
CREATE TABLE IF NOT EXISTS scan_deciles (
    run_id VARCHAR NOT NULL, feature VARCHAR NOT NULL, horizon VARCHAR NOT NULL, segment VARCHAR NOT NULL,
    decile INTEGER NOT NULL, mean DOUBLE, n_dates BIGINT, n_events BIGINT,
    PRIMARY KEY (run_id, feature, horizon, segment, decile));
CREATE TABLE IF NOT EXISTS scan_stats (
    run_id VARCHAR NOT NULL, feature VARCHAR NOT NULL, horizon VARCHAR NOT NULL, segment VARCHAR NOT NULL,
    n_dates BIGINT, spread DOUBLE, spread_t DOUBLE, spread_p DOUBLE, ic_mean DOUBLE, ic_t DOUBLE, ic_p DOUBLE,
    monotonicity DOUBLE, PRIMARY KEY (run_id, feature, horizon, segment));
CREATE TABLE IF NOT EXISTS hypothesis_log (
    run_id VARCHAR NOT NULL, label VARCHAR NOT NULL, period VARCHAR NOT NULL, p_value DOUBLE,
    logged_at TIMESTAMPTZ NOT NULL, PRIMARY KEY (run_id, label));
-- BH q-values over every test of every valid run, recomputed on each read.
CREATE OR REPLACE VIEW hypothesis_q AS
WITH h AS (
    SELECT h.*, r.kind, r.pattern_name FROM hypothesis_log h JOIN research_runs r USING (run_id)
    WHERE r.status = 'ok' AND h.p_value IS NOT NULL
), ranked AS (
    SELECT *, row_number() OVER (ORDER BY p_value, run_id, label) AS rk, count(*) OVER () AS m FROM h
)
SELECT run_id, label, period, kind, pattern_name, p_value, rk, m,
       least(1.0, min(p_value * m / rk) OVER (ORDER BY rk DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)) AS q_value
FROM ranked;
"""


class HoldoutLockedError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResearchParams:
    """Universe filter and test settings (stored with every run)."""
    min_adv_value: float = 1e9
    min_session_index: int = 20
    min_stocks_per_date: int = 30      # for cross-sectional deciles / IC
    cost_round_trip: float = 0.004
    horizons: tuple[int, ...] = (5, 10, 20)
    extra: dict[str, Any] = field(default_factory=dict)

    def universe_sql(self) -> str:
        return (f"is_traded AND adv_value_20 > {self.min_adv_value} AND session_index > {self.min_session_index}"
                " AND NOT price_jump AND NOT coalesce(fwd_has_price_jump_20d, false) AND NOT bad_source_date"
                " AND NOT coalesce(entry_blocked, false) AND NOT coalesce(crosses_period, false)")


def code_hash() -> str:
    digest = hashlib.sha256()
    package = resources.files("quant_research")
    for name in sorted(p.name for p in package.iterdir() if p.name.endswith(".py")):
        digest.update(package.joinpath(name).read_bytes())
    for p in sorted(package.joinpath("sql").iterdir(), key=lambda x: x.name):
        digest.update(p.read_bytes())
    return digest.hexdigest()[:16]


def check_period(period: str, final: bool) -> None:
    if period not in PERIODS:
        raise ValueError(f"Unknown period {period!r}; use one of {PERIODS}")
    if period == "holdout" and not final:
        raise HoldoutLockedError("The holdout period is locked. Use --final only for the final, pre-registered test.")


class ResultsStore:
    def __init__(self, results_path: Path, research_path: Path) -> None:
        if not research_path.exists():
            raise FileNotFoundError(f"No research database at {research_path}; run `quant build`")
        results_path.parent.mkdir(parents=True, exist_ok=True)
        self.con = connect_with_retry(results_path)  # the local UI may be reading
        self.con.execute(SCHEMA)
        self.con.execute(f"ATTACH '{research_path.as_posix().replace(chr(39), chr(39) * 2)}' AS rs (READ_ONLY)")
        self._universe_cache: dict[tuple, tuple] = {}

    def close(self) -> None:
        self.con.execute("DETACH rs")
        self.con.close()

    def __enter__(self) -> "ResultsStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def feature_build_id(self) -> str | None:
        row = self.con.execute("SELECT build_id FROM rs.feature_builds ORDER BY built_at DESC LIMIT 1").fetchone()
        return row[0] if row else None

    def start_run(self, run_id: str, kind: str, period: str, params: ResearchParams, now: datetime,
                  pattern: tuple[str, str] | None = None) -> None:
        self.con.execute(
            "INSERT INTO research_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ok', NULL)",
            [run_id, kind, pattern[0] if pattern else None, pattern[1] if pattern else None, period,
             json.dumps(asdict(params), default=str), self.feature_build_id(), code_hash(), now],
        )

    def log_hypothesis(self, run_id: str, label: str, period: str, p_value: float | None, now: datetime) -> None:
        self.con.execute("INSERT OR REPLACE INTO hypothesis_log VALUES (?, ?, ?, ?, ?)",
                         [run_id, label, period, p_value, now])

    def invalidate(self, run_id: str, reason: str) -> int:
        cur = self.con.execute("UPDATE research_runs SET status = 'invalid', invalid_reason = ? WHERE run_id = ?",
                               [reason, run_id])
        return cur.fetchone()[0]

    def q_values(self, run_id: str) -> dict[str, float]:
        return dict(self.con.execute("SELECT label, q_value FROM hypothesis_q WHERE run_id = ?", [run_id]).fetchall())

    def universe_by_date(self, period: str, params: "ResearchParams", column: str) -> tuple:
        """(date ints, mean outcome per date, win rate) of the filtered universe; cached per run batch."""
        key = (period, params.universe_sql(), column)
        cache = self._universe_cache
        if key not in cache:
            rows = self.con.execute(f"""SELECT date, avg({column}) AS m, avg(({column} > 0)::INT) AS w
                FROM rs.feature_target WHERE {params.universe_sql()} AND period = ? AND {column} IS NOT NULL
                GROUP BY date ORDER BY date""", [period]).fetchall()
            dates = np.array([r[0].toordinal() for r in rows], dtype=np.int64) - 719163  # days since 1970-01-01
            cache[key] = (dates, np.array([r[1] for r in rows], dtype=float), float(np.mean([r[2] for r in rows])) if rows else None)
        return cache[key]

    def holdout_runs(self) -> int:
        return self.con.execute("SELECT count(*) FROM research_runs WHERE period = 'holdout'").fetchone()[0]
