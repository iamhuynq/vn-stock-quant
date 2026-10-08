"""Cross-stock (Phase 4): peers of a symbol, rolling pair correlation, clusters, central stocks, test reports."""

from datetime import date

import plotly.graph_objects as go
import streamlit as st

from stock_ui import context, cross_data
from stock_ui.industries_tab import industry_tab

st.title("Cross-stock")
reader = context.reader()
data_dir = context.data_dir()
st.caption("Correlations use daily returns in excess of VNINDEX over sessions where both stocks traded. "
           "Correlation describes co-movement; it is not a forecast. Tested results are in the Reports tab.")

syms = cross_data.symbols(reader)
if syms.value is None and not syms.stale and syms.note and "not found" in syms.note:
    st.info("No cross-stock database yet: run `uv run quant cross build` in a terminal.")
    st.stop()
if not context.freshness(syms, "Cross-stock database"):
    st.stop()
names = syms.value["symbol"].tolist()
latest = st.toggle("Include data after 2023 (not yet covered by cross-stock tests)", value=False,
                   help="Off: everything stops at the end of the research period, so browsing cannot suggest "
                        "hypotheses from data that will later test them.")
as_of = date.today() if latest else cross_data.RESEARCH_END
if latest:
    st.warning("Showing relations from 2024 onward. Use them for information only: a hypothesis picked from "
               "this view can no longer be tested honestly on the same period.")
month = cross_data.latest_month(reader, as_of).value

tab_peers, tab_pair, tab_ind, tab_clusters, tab_reports = st.tabs(
    ["Peers", "Pair", "Industries", "Clusters", "Reports"])

with tab_peers:
    sym = st.selectbox("Symbol", names, index=names.index("FPT") if "FPT" in names else 0, key="cross_symbol")
    st.caption(f"Snapshot of {month}: the 200 most liquid stocks at that month end.")
    peers = cross_data.peers(reader, sym, as_of)
    if context.freshness(peers, "Peers"):
        if peers.value.empty:
            st.info(f"{sym} is not in the latest snapshot (not among the most liquid stocks).")
        else:
            st.dataframe(peers.value, hide_index=True, width="stretch")

with tab_pair:
    c1, c2 = st.columns(2)
    a = c1.selectbox("Stock A", names, index=names.index("SSI") if "SSI" in names else 0, key="pair_a")
    b = c2.selectbox("Stock B", names, index=names.index("HCM") if "HCM" in names else min(1, len(names) - 1),
                     key="pair_b")
    if a == b:
        st.info("Choose two different stocks.")
    else:
        pair = cross_data.pair_rolling(reader, a, b, as_of)
        if context.freshness(pair, "Pair") and not pair.value.empty:
            df = pair.value
            fig = go.Figure([go.Scatter(x=df["date"], y=df[f"corr_{w}"], name=f"{w} sessions", mode="lines",
                                        line={"width": 1 if w == 20 else 2}) for w in cross_data.ROLLING])
            fig.update_layout(height=420, yaxis={"range": [-1, 1], "title": "rolling correlation"},
                              margin={"l": 10, "r": 10, "t": 20, "b": 10}, hovermode="x unified",
                              legend={"orientation": "h", "y": 1.1})
            st.plotly_chart(fig, width="stretch")
            last = df.dropna().tail(1)
            if not last.empty:
                st.caption("Latest: " + ", ".join(f"{w} sessions {last[f'corr_{w}'].iloc[0]:.2f}"
                                                  for w in cross_data.ROLLING))

with tab_ind:
    industry_tab(reader, as_of)

with tab_clusters:
    st.caption(f"Hierarchical clusters on 250-session correlations at {month}; the number of clusters equals "
               "the number of ICB level-2 industries present. share_main_industry = share of members in the "
               "cluster's most common industry.")
    cl = cross_data.clusters(reader, as_of)
    if context.freshness(cl, "Clusters"):
        st.dataframe(cl.value, hide_index=True, width="stretch", height=420,
                     column_config={"share_main_industry": st.column_config.NumberColumn(format="percent")})
    st.markdown("**Central stocks** (highest average correlation with the rest, 120 sessions)")
    ce = cross_data.central(reader, as_of)
    if context.freshness(ce, "Central stocks"):
        st.dataframe(ce.value, hide_index=True, width="stretch")

with tab_reports:
    runs = cross_data.cross_runs(reader)
    if context.freshness(runs, "Cross-stock runs") and not runs.value.empty:
        st.dataframe(runs.value, hide_index=True, width="stretch")
    reports = sorted((data_dir / "reports" / "cross").glob("*.md"), reverse=True)
    if not reports:
        st.info("No report yet: `uv run quant cross describe` and `uv run quant cross test`.")
    else:
        pick = st.selectbox("Report", reports, format_func=lambda p: p.stem)
        st.markdown(pick.read_text())
