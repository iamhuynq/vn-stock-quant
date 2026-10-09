"""Report of an interaction scan, with the candidate rule declared in docs/regime-interaction-plan.md."""

import pandas as pd

from quant_research.provenance import from_runs
from quant_research.results import ResultsStore

Q_MAX = 0.05
MIN_DIFF = 0.02


def tests_with_q(store: ResultsStore, run_id: str) -> pd.DataFrame:
    df = store.con.execute("""
        SELECT t.*, q.q_value FROM interaction_tests t
        LEFT JOIN hypothesis_q q ON q.run_id = t.run_id AND q.label = 'ix_' || t.factor || '_' || t.dimension
        WHERE t.run_id = ? ORDER BY t.factor, t.dimension""", [run_id]).df()
    df["candidate"] = df.apply(is_candidate, axis=1)
    return df


def is_candidate(r: pd.Series) -> bool:
    """q < 0.05, |IC difference| >= 0.02, and the same sign in both halves of the research period."""
    if pd.isna(r["q_value"]) or pd.isna(r["diff"]) or pd.isna(r["diff_first_half"]) or pd.isna(r["diff_second_half"]):
        return False
    same_sign = (r["diff"] > 0) == (r["diff_first_half"] > 0) == (r["diff_second_half"] > 0)
    return bool(r["q_value"] < Q_MAX and abs(r["diff"]) >= MIN_DIFF and same_sign
                and r["diff_first_half"] != 0 and r["diff_second_half"] != 0)


def _f(v, fmt: str) -> str:
    return "-" if v is None or pd.isna(v) else format(v, fmt)


def render(store: ResultsStore, run_id: str) -> str:
    tests = tests_with_q(store, run_id)
    stats = store.con.execute("SELECT * FROM interaction_stats WHERE run_id = ?", [run_id]).df()
    m = store.con.execute("SELECT max(m) FROM hypothesis_q").fetchone()[0]
    lines = [f"# Interaction scan {run_id}", "", *from_runs(store.con, [run_id]), "",
             "Daily IC = Spearman(factor, fwd_excess_exec_10d) per date over the research universe. Test: IC in "
             "state A minus IC in state B, Newey-West lag 9. q = BH over the whole hypothesis log "
             f"(m = {m}). Research period only; nothing here is validated.", "",
             f"Candidate rule (declared before the run): q < {Q_MAX}, |difference| >= {MIN_DIFF}, same sign in "
             "2006-2014 and 2015-2023.", "",
             f"**Candidates: {int(tests['candidate'].sum())} of {len(tests)} tests.**", "",
             "## Unconditional IC (descriptive)", "", "| Factor | Dates | Mean IC | t |", "|---|---|---|---|"]
    for _, r in stats[stats["dimension"] == "all"].sort_values("factor").iterrows():
        lines.append(f"| {r['factor']} | {r['n_dates']} | {_f(r['mean_ic'], '+.4f')} | {_f(r['t'], '.2f')} |")
    lines += ["", "## Tests (A - B)", "",
              "| Factor | Dimension | A vs B | Dates A/B | Diff | t | p | q | 1st half | 2nd half | Candidate |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in tests.sort_values(["q_value", "factor"], na_position="last").iterrows():
        lines.append(f"| {r['factor']} | {r['dimension']} | {r['state_a']} vs {r['state_b']} | {r['n_a']}/{r['n_b']} | "
                     f"{_f(r['diff'], '+.4f')} | {_f(r['t'], '.2f')} | {_f(r['p'], '.3g')} | {_f(r['q_value'], '.3g')} | "
                     f"{_f(r['diff_first_half'], '+.4f')} | {_f(r['diff_second_half'], '+.4f')} | "
                     f"{'**yes**' if r['candidate'] else 'no'} |")
    lines += ["", "## Mean IC per state (descriptive)", ""]
    per = stats[stats["dimension"] != "all"].pivot_table(index=["dimension", "state"], columns="factor",
                                                         values="mean_ic")
    lines += ["| Dimension | State | " + " | ".join(per.columns) + " |", "|---|---|" + "---|" * len(per.columns)]
    for (dim, state), row in per.iterrows():
        lines.append(f"| {dim} | {state} | " + " | ".join(_f(v, "+.3f") for v in row) + " |")
    lines += ["", "> A statistical interaction is not economic value: a candidate needs a cost-aware conditional",
              "> portfolio test, a new pre-registration and forward data."]
    return "\n".join(lines)
