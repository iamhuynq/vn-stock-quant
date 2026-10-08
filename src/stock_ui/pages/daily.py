"""F. Daily report: the rendered report for a chosen date, scan status, and a filterable event table."""

import streamlit as st

from stock_ui import context, research_data
from quant_research.daily import AVOID_PATTERN

st.title("Daily report")
reader = context.reader()
data_dir = context.data_dir()

reports = sorted((data_dir / "reports" / "daily").glob("*.md"), reverse=True)
data = research_data.daily(reader)

tab_report, tab_events, tab_scans = st.tabs(["Report", "Events", "Scan status"])

with tab_report:
    if not reports:
        st.info("No daily report yet: run 'Scan and daily report' (or the full pipeline) on the Run tasks page.")
    else:
        pick = st.selectbox("Report date", reports, format_func=lambda p: p.stem)
        st.markdown(pick.read_text())

if data.value is None and not data.stale and data.note is None:
    for tab in (tab_events, tab_scans):
        tab.info("No daily scan yet.")
elif context.freshness(data, "Daily scans"):
    d = data.value
    with tab_events:
        ev = d["events"]
        if ev.empty:
            st.caption("No events recorded.")
        else:
            dates = sorted(ev["scan_date"].dt.date.unique(), reverse=True)
            c1, c2, c3 = st.columns(3)
            day = c1.selectbox("Session", dates)
            patterns = sorted(ev["pattern"].unique())
            chosen = c2.multiselect("Patterns", patterns, default=patterns)
            only_forward = c3.toggle("Forward sessions only", value=False)
            view = ev[(ev["scan_date"].dt.date == day) & ev["pattern"].isin(chosen)]
            if only_forward:
                view = view[view["is_forward"]]
            avoid = sorted(view.loc[view["pattern"] == AVOID_PATTERN, "symbol"])
            if avoid:
                st.warning("Avoid list (validated: sharp drop + heavy volume + sellers dominate): " + ", ".join(avoid))
            st.caption(f"{len(view)} events on {day}. Historical statistics are averages over many cases, not a "
                       "forecast for any single stock.")
            st.dataframe(view, hide_index=True, width="stretch", height=480,
                         column_config={"return_1d": st.column_config.NumberColumn(format="percent")})
    with tab_scans:
        st.dataframe(d["scans"], hide_index=True, width="stretch",
                     column_config={"coverage": st.column_config.NumberColumn(format="percent")})
