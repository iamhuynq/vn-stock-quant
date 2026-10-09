"""D. Research: runs, run detail, hypothesis log with BH q-values, research registry, invalidate a run."""

import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from stock_ui import context, research_data, tasks

st.title("Research")
reader = context.reader()
data_dir = context.data_dir()

tab_runs, tab_log, tab_registry, tab_ix, tab_events = st.tabs(["Runs", "Hypothesis log", "Registry",
                                                                 "Interactions", "Event study"])

with tab_runs:
    runs = research_data.runs(reader)
    if context.freshness(runs, "Runs"):
        df = runs.value
        c1, c2, c3 = st.columns(3)
        kinds = c1.multiselect("Kind", sorted(df["kind"].unique()), default=sorted(df["kind"].unique()))
        periods = c2.multiselect("Period", sorted(df["period"].unique()), default=sorted(df["period"].unique()))
        show_invalid = c3.toggle("Show invalidated runs", value=False)
        view = df[df["kind"].isin(kinds) & df["period"].isin(periods)]
        if not show_invalid:
            view = view[view["status"] == "ok"]
        st.caption(f"{len(view)} of {len(df)} runs. Lift = pattern minus the whole universe on the same dates, "
                   f"{research_data.LIFT_HORIZON}; q = Benjamini-Hochberg over every logged test of every valid run.")
        st.dataframe(view, hide_index=True, width="stretch", height=360,
                     column_config={"pattern_mean": st.column_config.NumberColumn(format="percent"),
                                    "baseline_mean": st.column_config.NumberColumn(format="percent"),
                                    "lift": st.column_config.NumberColumn(format="percent")})

        pick = st.selectbox("Run detail", view["run_id"].tolist(), index=None, placeholder="Choose a run")
        if pick:
            detail = research_data.run_detail(reader, pick)
            if context.freshness(detail, "Run detail") and not detail.value["run"].empty:
                d = detail.value
                run = d["run"].iloc[0]
                st.markdown(f"**{run['kind']}** `{run['pattern_name'] or ''}` - period **{run['period']}** - "
                            f"status **{run['status']}**" + (f" ({run['invalid_reason']})" if run["invalid_reason"] else ""))
                if not d["definition"].empty:
                    defn = d["definition"].iloc[0]
                    st.code(defn["where_sql"], language="sql")
                    st.caption(f"Hypothesis: {defn['hypothesis']} - doc {defn['doc_ref']} - base {defn['base'] or '-'}")
                for key, label in (("lifts", "Lift vs universe"), ("comparisons", "Comparison with base pattern"),
                                   ("stats", "Statistics by segment"), ("scan", "Scan: features by |IC t|"),
                                   ("tests", "Logged tests and q-values")):
                    if not d[key].empty:
                        st.markdown(f"**{label}**")
                        st.dataframe(d[key], hide_index=True, width="stretch")
                with st.expander("Parameters"):
                    st.json(json.loads(run["params"]))

        st.divider()
        st.markdown("**Invalidate a run**")
        st.caption("The run stays in the log for the record but leaves the q-value family. Use it for runs "
                   "built on a bug or a wrong definition, never to drop an unwelcome result.")
        valid_ids = df.loc[df["status"] == "ok", "run_id"].tolist()
        with st.form("invalidate", clear_on_submit=True):
            target = st.selectbox("Run", valid_ids, index=None, placeholder="Choose a valid run")
            reason = st.text_input("Reason (required)", max_chars=tasks.REASON_MAX)
            sure = st.checkbox("I understand this changes the q-values of every other test")
            submitted = st.form_submit_button("Invalidate", disabled=tasks.busy_reason(data_dir) is not None)
        if submitted:
            if not target or not sure:
                st.error("Choose a run and tick the confirmation.")
            else:
                try:
                    ui_run = tasks.start(data_dir, "invalidate_run", run_id=target, reason=reason)
                except (tasks.TaskError, ValueError) as exc:
                    st.error(str(exc))
                else:
                    st.success(f"Started as task {ui_run}; follow it on the Run tasks page.")

with tab_log:
    log = research_data.hypothesis_log(reader)
    if context.freshness(log, "Hypothesis log"):
        df = log.value
        m = int(df["m"].max()) if len(df) else 0
        c1, c2 = st.columns(2)
        c1.metric("Tests in the family (m)", f"{m:,}")
        c2.metric("Tests with q < 0.05", f"{int((df['q_value'] < 0.05).sum()):,}")
        only_sig = st.toggle("Only q < 0.05", value=False)
        st.dataframe(df[df["q_value"] < 0.05] if only_sig else df, hide_index=True, width="stretch", height=480)

with tab_registry:
    reg = research_data.registry(reader)
    if reg.value is None and not reg.stale and reg.note is None:
        st.info("No registry yet: any `quant` command that opens the results store creates it "
                "(for example `uv run quant registry list`).")
    elif context.freshness(reg, "Registry"):
        status, history, linked = reg.value["status"], reg.value["history"], reg.value["runs"]
        st.caption("Every hypothesis and its decision, failures included (doc 31: the registry keeps every "
                   "failure). Decisions are recorded verbatim; history is append-only. Changes: "
                   "`uv run quant registry move` (CLI only).")
        counts = status["status"].value_counts()
        cols = st.columns(len(counts))
        for col, (name, n) in zip(cols, counts.items()):
            col.metric(name, int(n))
        family = st.selectbox("Family", ["all", *sorted(status["family"].unique())], key="registry_family")
        shown = status if family == "all" else status[status["family"] == family]
        st.dataframe(shown.drop(columns=["statement", "pattern_version", "prereg_doc"]), hide_index=True,
                     width="stretch")
        pick = st.selectbox("Hypothesis", shown["hypothesis_id"].tolist(), key="registry_pick")
        if pick:
            row = status[status["hypothesis_id"] == pick].iloc[0]
            st.markdown(f"**{pick}: {row['title']}** ({row['family']}, now `{row['status']}`)")
            st.caption(row["statement"])
            st.dataframe(history[history["hypothesis_id"] == pick].drop(columns=["hypothesis_id"]),
                         hide_index=True, width="stretch")
            runs_of = linked[linked["hypothesis_id"] == pick].drop(columns=["hypothesis_id"])
            if not runs_of.empty:
                st.caption("Linked runs; min_q = smallest BH q-value of the run's logged tests, recomputed over "
                           "the whole log (it can differ from the value quoted when the decision was taken).")
                st.dataframe(runs_of, hide_index=True, width="stretch")

with tab_ix:
    ixr = research_data.interactions(reader)
    if ixr.value is None and not ixr.stale and ixr.note is None:
        st.info("No interaction scan yet: `uv run quant interactions scan` (research period, logged).")
    elif context.freshness(ixr, "Interactions"):
        tests, stats = ixr.value["tests"], ixr.value["stats"]
        st.caption(f"Run {ixr.value['run_id']}. IC difference = mean daily Spearman IC (factor vs 10-session "
                   "execution excess return) in state A minus state B, research period only. Candidate rule "
                   "(declared before the run): q < 0.05, |difference| >= 0.02, same sign in 2006-2014 and "
                   "2015-2023. Not economic value.")
        st.metric("Candidates", f"{int(tests['candidate'].sum())} of {len(tests)}")
        grid = tests.pivot(index="factor", columns="dimension", values="diff")
        qtext = tests.pivot(index="factor", columns="dimension", values="q_value").map(
            lambda q: "" if pd.isna(q) else f"q {q:.2g}")
        fig = go.Figure(go.Heatmap(z=grid.values, x=grid.columns, y=grid.index, colorscale="RdBu", zmid=0,
                                   text=qtext.values, texttemplate="%{text}"))
        fig.update_layout(height=420, margin={"l": 10, "r": 10, "t": 30, "b": 10},
                          title="IC difference (A - B) by factor and dimension")
        st.plotly_chart(fig, width="stretch", key="research_ix")
        st.dataframe(tests.drop(columns=["run_id"]), hide_index=True, width="stretch")
        factor = st.selectbox("Factor", sorted(stats["factor"].unique()), key="ix_factor")
        st.dataframe(stats[stats["factor"] == factor].drop(columns=["factor"]), hide_index=True, width="stretch")

with tab_events:
    es = research_data.event_study(reader)
    if es.value is None and not es.stale and es.note is None:
        st.info("No event study yet: `uv run quant events study` (descriptive, research period).")
    elif context.freshness(es, "Event study"):
        st.caption(f"Run {es.value['run_id']}. Descriptive (doc 24): not in the hypothesis log; lift t-statistics "
                   "are not corrected for multiple testing. close_* = raw close-to-close; exec_excess_* = from the "
                   "next open, minus VNINDEX. Compare means with the 0.4% round-trip cost.")
        df = es.value["stats"]
        c1, c2 = st.columns(2)
        horizon = c1.selectbox("Horizon", sorted(df["horizon"].unique()),
                               index=sorted(df["horizon"].unique()).index("exec_excess_10d")
                               if "exec_excess_10d" in set(df["horizon"]) else 0)
        segment = c2.selectbox("Segment", sorted(df["segment"].unique()),
                               index=sorted(df["segment"].unique()).index("all"))
        view = df[(df["horizon"] == horizon) & (df["segment"] == segment)].drop(columns=["horizon", "segment"])
        pct = st.column_config.NumberColumn(format="percent")
        st.dataframe(view, hide_index=True, width="stretch",
                     column_config={c: pct for c in ("mean", "median", "win_rate", "std", "p05", "p95",
                                                     "mean_max_gain_5d", "mean_max_loss_5d", "lift")})
