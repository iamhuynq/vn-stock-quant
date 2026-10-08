"""B. Run tasks: start allowlisted commands, follow the log, cancel, history."""

from datetime import date

import pandas as pd
import streamlit as st

from stock_ui import context, tasks

st.title("Run tasks")
data_dir = context.data_dir()

busy = tasks.busy_reason(data_dir)
if busy:
    st.warning(f"Busy: {busy}. Buttons are disabled until it finishes.")

cols = st.columns(2)
for i, spec in enumerate(t for t in tasks.TASKS.values() if not t.hidden):
    with cols[i % 2].container(border=True):
        st.markdown(f"**{spec.label}**")
        st.caption(spec.help)
        on_date = None
        if spec.takes_date:
            on_date = st.date_input("Re-scan session (optional)", value=None, key=f"date_{spec.name}",
                                    max_value=date.today())
        if st.button("Run", key=f"run_{spec.name}", disabled=busy is not None):
            try:
                run_id = tasks.start(data_dir, spec.name, on_date)
            except (tasks.TaskError, ValueError) as exc:
                st.error(str(exc))
            else:
                st.session_state["watch"] = run_id
                st.rerun()

st.divider()


@st.fragment(run_every=2)
def live() -> None:
    if (tasks.busy_reason(data_dir) is None) != (busy is None):
        st.rerun()                          # a run started or ended (any tab, or daily.sh): redraw the buttons
    active = tasks.active_run(data_dir)
    watch = active.run_id if active else st.session_state.get("watch")
    if not watch:
        st.caption("No task started from this page yet.")
        return
    try:
        rec = tasks.load_record(data_dir, watch)
    except FileNotFoundError:
        return
    state = rec.status()
    st.subheader(f"{rec.task}: {state}")
    st.caption(f"run {rec.run_id} - `{' '.join(rec.argv)}`")
    if state == "running" and st.button("Cancel", key=f"cancel_{rec.run_id}"):
        tasks.cancel(data_dir, rec.run_id)
    if rec.ended_at:
        msg = f"exit {rec.exit_code}: {rec.meaning()}" if rec.exit_code is not None else rec.meaning()
        (st.success if state == "ok" else st.error)(msg)
    st.code(tasks.tail(data_dir, rec.run_id) or "(no output yet)", language=None)


live()

st.subheader("History")
rows = [{"run": r.run_id, "task": r.task, "status": r.status(), "started": r.started_at,
         "seconds": None if r.duration() is None else round(r.duration()), "exit": r.exit_code,
         "meaning": r.meaning()} for r in tasks.history(data_dir)]
if rows:
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    pick = st.selectbox("Show log of", [r["run"] for r in rows], index=None)
    if pick:
        st.code(tasks.tail(data_dir, pick) or "(empty)", language=None)
else:
    st.caption("No runs yet.")
