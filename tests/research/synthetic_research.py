"""A small research database with a planted signal, for engine tests.

volume_ratio_20 truly predicts the outcomes (+5% per unit); return_1d is pure noise.
Deterministic: pseudo-random numbers come from hash(), not random().
"""

from pathlib import Path

import duckdb

N_SYMBOLS, N_DATES = 60, 300


def u(k: int) -> str:
    return f"((hash(s * 100003 + d * 7 + {k}) % 1000000) / 1e6)"


def build_research_db(path: Path) -> None:
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE feature_builds (build_id VARCHAR, built_at TIMESTAMPTZ)")
    con.execute("INSERT INTO feature_builds VALUES ('test-build', TIMESTAMPTZ '2026-10-04 00:00:00+00')")
    con.execute(f"""
        CREATE TABLE feature_target AS
        WITH g AS (SELECT s, d FROM range({N_SYMBOLS}) a(s), range({N_DATES}) b(d)),
        r AS (SELECT s, d, {u(1)} AS signal, {u(2)} AS noise, {u(3)} AS e5, {u(4)} AS e10, {u(5)} AS e20 FROM g)
        SELECT 'S' || s AS symbol, DATE '2020-01-01' + d::INT AS date,
               CASE WHEN d < 240 THEN 'research' WHEN d < 270 THEN 'validation' ELSE 'holdout' END AS period,
               CASE d % 3 WHEN 0 THEN 'Bull' WHEN 1 THEN 'Sideway' ELSE 'Bear' END AS market_regime,
               CASE s % 3 WHEN 0 THEN 'HSX' WHEN 1 THEN 'HNX' ELSE 'UPCOM' END AS exchange_now,
               TRUE AS is_traded, 2e9 AS adv_value_20, 100 AS session_index,
               FALSE AS price_jump, FALSE AS fwd_has_price_jump_20d, FALSE AS bad_source_date,
               FALSE AS entry_blocked, FALSE AS crosses_period,
               signal AS volume_ratio_20, noise AS return_1d,
               0.05 * (signal - 0.5) + 0.04 * (e5 - 0.5)  AS fwd_excess_exec_5d,
               0.05 * (signal - 0.5) + 0.04 * (e10 - 0.5) AS fwd_excess_exec_10d,
               0.05 * (signal - 0.5) + 0.04 * (e20 - 0.5) AS fwd_excess_exec_20d,
               0.02 * (e5 - 0.5) AS fwd_ret_close_1d, 0.02 * (e10 - 0.5) AS fwd_ret_close_3d
        FROM r""")
    con.close()
