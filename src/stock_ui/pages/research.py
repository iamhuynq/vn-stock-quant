"""D. Research: runs, run detail, hypothesis log with BH q-values, validation decisions, invalidate a run."""

import json

import streamlit as st

from stock_ui import context, research_data, tasks

st.title("Research")
reader = context.reader()
data_dir = context.data_dir()

tab_runs, tab_log, tab_decisions, tab_events = st.tabs(["Runs", "Hypothesis log", "Validation decisions",
                                                        "Event study"])

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

with tab_decisions:
    dec = research_data.decisions(reader)
    if dec.value is None and not dec.stale and dec.note is None:
        st.info("No validation decisions recorded yet (written by `quant daily`).")
    elif context.freshness(dec, "Validation decisions"):
        st.caption("Recorded outcomes of the pre-registered validation, shown verbatim.")
        st.dataframe(dec.value, hide_index=True, width="stretch")

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
