"""The "Industries" tab of the Cross-stock page (Phase 4b): industry indexes, correlations, momentum."""

from datetime import date

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from stock_ui import context, cross_data
from stock_ui.db import Reader

PCT = st.column_config.NumberColumn(format="percent")


def industry_tab(reader: Reader, as_of: date) -> None:
    st.caption("Equal-weight index of each ICB level-2 industry's liquid members (at least 5 that day), daily "
               "return in excess of VNINDEX. Members are fixed at each month end. Descriptive: the tested "
               "results (lead-lag, momentum, reversal, laggards) are in the Reports tab.")
    inds = cross_data.industries(reader)
    if not context.freshness(inds, "Industries") or inds.value.empty:
        st.info("No industry indexes yet: run `uv run quant cross build`.")
        return
    table = inds.value
    names = dict(zip(table["group_code"], table["name"]))
    codes = list(names)

    pick = st.multiselect("Industries", codes, default=codes[:4], format_func=names.get, key="ind_pick")
    cum = cross_data.industry_cumulative(reader, tuple(pick), as_of)
    if pick and context.freshness(cum, "Industry indexes") and not cum.value.empty:
        fig = px.line(cum.value, x="date", y="cum_excess", color="name")
        fig.update_layout(height=380, yaxis={"tickformat": ".0%", "title": "cumulative excess vs VNINDEX"},
                          margin={"l": 10, "r": 10, "t": 20, "b": 10}, legend={"orientation": "h", "y": 1.12})
        st.plotly_chart(fig, width="stretch")

    c1, c2 = st.columns([1, 1])
    with c1:
        win = st.radio("Correlation window (sessions)", [60, 120, 250], index=1, horizontal=True, key="ind_win")
        corr = cross_data.industry_corr(reader, win, as_of)
        if context.freshness(corr, "Industry correlation") and not corr.value.empty:
            df = corr.value
            mat = df.pivot(index="a", columns="b", values="corr").combine_first(
                df.pivot(index="b", columns="a", values="corr"))
            for n in mat.index:
                mat.loc[n, n] = 1.0
            fig = go.Figure(go.Heatmap(z=mat.values, x=mat.columns, y=mat.index, zmin=-1, zmax=1,
                                       colorscale="RdBu", reversescale=True))
            fig.update_layout(height=520, margin={"l": 10, "r": 10, "t": 30, "b": 10},
                              title=f"Snapshot {df['month_end'].iloc[0]}")
            st.plotly_chart(fig, width="stretch")
    with c2:
        mom = cross_data.industry_momentum(reader, as_of)
        st.markdown("**Momentum ranking** (excess return of the index)")
        if context.freshness(mom, "Industry momentum") and not mom.value.empty:
            st.dataframe(mom.value, hide_index=True, width="stretch", height=480,
                         column_config={c: PCT for c in ("ret_5d", "ret_21d", "ret_63d")})

    st.markdown("**Rolling correlation of two industries**")
    a1, a2 = st.columns(2)
    ia = a1.selectbox("Industry A", codes, index=0, format_func=names.get, key="ind_a")
    ib = a2.selectbox("Industry B", codes, index=min(1, len(codes) - 1), format_func=names.get, key="ind_b")
    if ia != ib:
        pair = cross_data.industry_pair_rolling(reader, ia, ib, as_of)
        if context.freshness(pair, "Industry pair") and not pair.value.empty:
            df = pair.value
            fig = go.Figure([go.Scatter(x=df["date"], y=df[f"corr_{w}"], name=f"{w} sessions", mode="lines")
                             for w in cross_data.ROLLING])
            fig.update_layout(height=360, yaxis={"range": [-1, 1]}, margin={"l": 10, "r": 10, "t": 20, "b": 10},
                              hovermode="x unified", legend={"orientation": "h", "y": 1.1})
            st.plotly_chart(fig, width="stretch")
