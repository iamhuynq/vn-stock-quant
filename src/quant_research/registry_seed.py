"""Registry seed: the hypotheses and decisions recorded before the registry existed (2026-10-04..08).

Copied verbatim from the result docs. This seed is frozen: later state changes go through
`quant registry move`, never through edits here. Rows are inserted only when missing.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

VN = ZoneInfo("Asia/Ho_Chi_Minh")


def _at(day: int) -> datetime:
    return datetime(2026, 10, day, tzinfo=VN)


PREREG_P3 = ("docs/preregistration-2026-10-04.md",
             "6fe6d42544e7d1caab320c1ea77b7bcecb69ce31c0be3501fc6957c89324ed0e")
PREREG_P6 = ("docs/preregistration-backtest-2026-10-04.md",
             "43e9950402bb481b12353e41c842b0f001209b6c99d510c7f31bc16142ff8248")
PREREG_G2 = ("docs/preregistration-group-momentum-2026-10-08.md",
             "da8ff1d0750524751a713af792516545b581fe6663dfa2e9dbd95cad55fe0b94")
DOC_P3 = "docs/validation-results-2026-10-04.md"
DOC_P4 = "docs/cross-stock-results-2026-10-05.md"
DOC_P4B = "docs/group-analysis-results-2026-10-07.md"
P3_VALIDATION = "20261004T183943-pattern-{}-validation"

# hypothesis_id, family, title, statement, pattern, pattern_version, created_at
SEED_HYPOTHESES = [
    ("P3-C1", "single_stock_pattern", "Order imbalance top decile",
     "Stocks in the top decile of order_imbalance beat the universe over the next 10 sessions after costs.",
     "order_imbalance_d10", "0a1952fa", _at(4)),
    ("P3-C1b", "single_stock_pattern", "Order imbalance top decile, no limit-up days",
     "C1 excluding limit-up days beats the universe over the next 10 sessions after costs.",
     "order_imbalance_d10_no_limit", "dc53588e", _at(4)),
    ("P3-C2", "single_stock_pattern", "Momentum 10 sessions top decile",
     "Stocks in the top decile of return_10d beat the universe over the next 10 sessions after costs.",
     "momentum10_d10", "5905e5b3", _at(4)),
    ("P3-C3", "single_stock_pattern", "Sharp drop + heavy volume + sellers dominate (avoid)",
     "Stocks with return_1d < -3%, volume_ratio_20 > 2 and order_imbalance < -0.4 underperform the universe "
     "over the next 10 sessions.",
     "drop3_volume2_sellers", "cb8daa50", _at(4)),
    ("P6-B1", "portfolio", "Order-imbalance portfolio, frozen strategy 72c851c7 (1e9 VND)",
     "The top-decile order-imbalance portfolio (hold 10, 20 positions, renew) beats random portfolios with "
     "the same mechanics and earns a positive return after costs.",
     "oi_d10_h10_k20_renew_eq1bn", "72c851c7", _at(4)),
    ("P4-X1", "cross_stock", "Stock lead-lag persistence",
     "Pairs with a strong lag-1 lead-lag in one year keep it in the next year in tradable returns.",
     "leadlag_persistence", "v2", _at(5)),
    ("P4-X2", "cross_stock", "H1 industry leaders lead followers",
     "Followers of industry leaders that rose earn excess returns over the next sessions.",
     None, None, _at(5)),
    ("P4-X3", "cross_stock", "H2 large caps lead small caps",
     "The large-cap excess return predicts small-cap returns with the market return controlled.",
     "h2_large_to_small", "v2", _at(5)),
    ("P4-X4", "cross_stock", "H3 leader jump, follower flat",
     "When industry leaders jump +5% excess and a follower stays flat, the follower catches up.",
     "cross_h3_leader_jump_follower_flat", "23c6b7a3", _at(5)),
    ("P4-X5", "cross_stock", "Cointegration long leg",
     "The cheap leg of a cointegrated same-industry pair outperforms after the spread crosses 2 sigma.",
     "cross_coint_long_leg", "efb5c01c", _at(5)),
    ("P4b-G1", "industry", "Industry lead-lag persistence",
     "Industry index lead-lag relations persist in tradable (next open-to-close) returns.",
     "group_leadlag_persistence", "v1", _at(7)),
    ("P4b-G2", "industry", "Industry momentum, 21 sessions",
     "The top tercile of industries by 21-session return beats the average industry over the next month, "
     "net of rotation costs.",
     "group_momentum", "v1", _at(7)),
    ("P4b-G3", "industry", "Weak industries keep underperforming (1 week)",
     "The bottom tercile of industries by 5-session return underperforms the average industry over the next "
     "5 sessions (possible avoid signal).",
     "group_reversal", "v1", _at(7)),
    ("P4b-G4", "industry", "Laggards in strong industries",
     "Stocks lagging inside a strong industry catch up over the next sessions.",
     "cross_g4_laggard_in_strong_industry", "a43fa3b5", _at(7)),
    ("P5-E1", "event", "BREAKOUT event",
     "Stocks closing above the highest close of the previous 60 sessions beat the universe over the next "
     "10 sessions.",
     "EVENT_BREAKOUT", "d9f85c2d", _at(8)),
]


def _p3(hid: str, pattern: str, lift: str, decision: str, reason: str) -> list[tuple]:
    status = "validated" if decision == "PASS" else "failed"
    return [
        (hid, 1, "research", None, "Phase 3 pattern discovery, research period", None, None, None, None, _at(4)),
        (hid, 2, "candidate", None, f"research-period lift 10d {lift}", None, None, None, None, _at(4)),
        (hid, 3, "preregistered", None, "pre-registered for the 2024-2025 validation", None, *PREREG_P3, None, _at(4)),
        (hid, 4, status, decision, reason, P3_VALIDATION.format(pattern), *PREREG_P3, DOC_P3, _at(4)),
    ]


def _rejected(hid: str, day: int, run_id: str, reason: str, doc: str, research: str) -> list[tuple]:
    return [(hid, 1, "research", None, research, None, None, None, None, _at(day)),
            (hid, 2, "rejected", None, reason, run_id, None, None, doc, _at(day))]


# hypothesis_id, seq, status, decision, reason, run_id, prereg_doc, prereg_sha, result_doc, moved_at
SEED_TRANSITIONS = [
    *_p3("P3-C1", "order_imbalance_d10", "+0.73% (t 7.1)", "FAIL",
         "lift +0.47% replicated (q<0.05) but -0.35% after costs"),
    *_p3("P3-C1b", "order_imbalance_d10_no_limit", "+0.74% (t 7.4)", "FAIL",
         "lift +0.53% replicated (q<0.05) but -0.29% after costs"),
    *_p3("P3-C2", "momentum10_d10", "+0.72% (t 4.7)", "FAIL",
         "lift +0.48% borderline (q 0.049), -0.34% after costs"),
    *_p3("P3-C3", "drop3_volume2_sellers", "-4.55% (t -3.5)", "PASS",
         "avoid signal: lift -5.16% (q<0.001), 50 events"),
    ("P3-C3", 5, "forward", None, "tracked by the daily scan on forward data (from 2026-10-03) as an avoid signal",
     None, None, None, "docs/daily-pipeline-plan.md", _at(5)),
    ("P6-B1", 1, "research", None, "12-variant grid, research period", None, None, None, None, _at(4)),
    ("P6-B1", 2, "candidate", None, "in-sample CAGR 14.3%, beat 20 of 20 random runs", None, None, None, None, _at(4)),
    ("P6-B1", 3, "preregistered", None, "pre-registered for the 2026 holdout", None, *PREREG_P6, None, _at(4)),
    ("P6-B1", 4, "failed", "FAIL",
     "holdout 2026: beat 5 of 20 random runs (needed 19), -21.0% after costs; the paper portfolio keeps "
     "running as information", "20261004T202206-backtest-oi_d10_h10_k20_renew_eq1bn-holdout", *PREREG_P6,
     "docs/backtest-results-2026-10-04.md", _at(4)),
    *_rejected("P4-X1", 5, "20261005T193435-cross-leadlag_persistence-research",
               "not tradable: the follow happens in the opening gap (next open-to-close lags 1/2/3/5 not significant)",
               DOC_P4, "Phase 4 cross-stock, research period"),
    *_rejected("P4-X2", 5, "20261005T192527-cross-h1_leaders_to_followers-research",
               "5d spread +0.12% (t 2.3, q 0.049), far below the 0.4% round-trip cost", DOC_P4,
               "Phase 4 cross-stock, research period"),
    *_rejected("P4-X3", 5, "20261005T193435-cross-h2_large_to_small-research",
               "no effect once the market return is controlled (5d q 0.058, 10d q 0.24, 20d q 0.57)", DOC_P4,
               "Phase 4 cross-stock, research period"),
    *_rejected("P4-X4", 5, "20261005T192527-pattern-cross_h3_leader_jump_follower_flat-research",
               "lift +0.16% / -0.11% / -0.33% at 5/10/20d, none significant", DOC_P4,
               "Phase 4 cross-stock, research period"),
    *_rejected("P4-X5", 5, "20261005T193435-pattern-cross_coint_long_leg-research",
               "no lift; same-industry spreads keep widening instead of reverting", DOC_P4,
               "Phase 4 cross-stock, research period"),
    *_rejected("P4b-G1", 7, "20261007T180725-cross-group_leadlag_persistence-research",
               "real in close prices only: next open-to-close not significant after BH (opening gap)", DOC_P4B,
               "Phase 4b industry analysis, research period"),
    ("P4b-G2", 1, "research", None, "Phase 4b industry analysis, research period", None, None, None, None, _at(7)),
    ("P4b-G2", 2, "candidate", None, "research: +0.53% / month (t 2.7, q 0.019), net +0.26% / month",
     "20261007T180725-cross-group_momentum-research", None, None, DOC_P4B, _at(7)),
    ("P4b-G2", 3, "preregistered", None, "pre-registered for one validation run", None, *PREREG_G2, None, _at(8)),
    ("P4b-G2", 4, "failed", "FAIL",
     "validation: -0.18% / month (t -0.53), net -0.44%; hypothesis closed, not tracked forward",
     "20261008T152452-cross-group_momentum-validation", *PREREG_G2, "docs/group-momentum-validation-2026-10-08.md",
     _at(8)),
    ("P4b-G3", 1, "research", None, "Phase 4b industry analysis, research period", None, None, None, None, _at(7)),
    ("P4b-G3", 2, "candidate", None,
     "-0.15% / week (t -3.4, q 0.002): weak industries keep underperforming; not a long candidate (net -0.42% / "
     "week), possible avoid signal; not pre-registered",
     "20261007T180725-cross-group_reversal-research", None, None, DOC_P4B, _at(7)),
    *_rejected("P4b-G4", 7, "20261007T180725-pattern-cross_g4_laggard_in_strong_industry-research",
               "lift +0.01% / +0.05% / +0.13% at 5/10/20d, none significant", DOC_P4B,
               "Phase 4b industry analysis, research period"),
    ("P5-E1", 1, "research", None, "event study: lift +0.81% at 10d (t 4.1, descriptive, not corrected)",
     "20261008T163321-event_study-catalog_d9f85c2d-research", None, None, "docs/event-engine-plan.md", _at(8)),
    ("P5-E1", 2, "monitoring", None, "forward events collected by the daily scan; no decision rule yet",
     None, None, None, None, _at(8)),
]
