"""Exposure panel shared by the Market watch (watchlist) and Backtest and paper (paper portfolio) pages."""

import pandas as pd
import plotly.express as px
import streamlit as st

from quant_research.exposure import compute
from stock_ui import context, exposure_data
from stock_ui.db import Reader

PCT = st.column_config.NumberColumn(format="percent")


def render(reader: Reader, weights: dict[str, float], key: str) -> None:
    symbols = tuple(sorted(weights))
    data = exposure_data.returns(reader, symbols)
    if not context.freshness(data, "Returns for exposure") or data.value["returns"].empty:
        return
    fz = exposure_data.factor_z(reader).value
    factor_z = fz["z"] if fz else None
    ind = exposure_data.industries(reader).value
    cl = exposure_data.clusters(reader).value
    labels = {}
    if ind is not None:
        labels["industry"] = dict(zip(ind["symbol"], ind["industry_l2"]))
    if cl is not None:
        labels["cluster"] = dict(zip(cl["symbol"], cl["label"]))
    ex = compute(data.value["returns"], data.value["market"], weights, labels, factor_z)
    per_stock = ex.per_stock
    if fz is not None:
        per_stock = per_stock.assign(beta_250=per_stock["symbol"].map(fz["beta_250"]))
    p = ex.portfolio
    as_of = pd.Timestamp(data.value["as_of"]).date()
    st.caption(f"Last {exposure_data.SESSIONS} sessions to {as_of}. Descriptive risk information, "
               "not a forecast.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Market beta", "-" if p["beta"] is None else f"{p['beta']:.2f}")
    c2.metric("Volatility (annual)", "-" if p["vol_ann"] is None else f"{p['vol_ann']:.1%}")
    c3.metric("Effective bets", "-" if p["effective_bets"] is None else f"{p['effective_bets']:.1f} of {p['n']}",
              help="How many independent positions the holdings behave like (correlation eigenvalues). "
                   "N independent stocks give N; N copies of one stock give 1.")
    c4.metric("Effective N (weights)", "-" if p["effective_n_weights"] is None else f"{p['effective_n_weights']:.1f}",
              help="1 / sum of squared weights: concentration of the weights alone.")
    if ex.missing:
        st.caption("Not enough clean returns in the window (left out): " + ", ".join(ex.missing))
    left, right = st.columns(2)
    with left:
        st.markdown("**Risk contribution by position**")
        st.caption(f"beta = {exposure_data.SESSIONS} sessions; beta_250 = Factor Engine (250 sessions).")
        st.dataframe(per_stock, hide_index=True, width="stretch",
                     column_config={"weight": PCT, "vol_ann": PCT, "risk_share": PCT})
        if ex.tilts is not None:
            st.markdown("**Factor tilts** (weighted z-score vs the liquid universe, Factor Engine f1; 0 = average)")
            st.dataframe(ex.tilts, hide_index=True, width="stretch", column_config={"coverage": PCT})
        elif fz is None:
            st.caption("No factor scores: run `quant build` (Factor Engine).")
    with right:
        for name, frame in ex.groups.items():
            fig = px.bar(frame, x="weight", y=name, orientation="h")
            fig.update_layout(height=min(60 + 28 * len(frame), 420), margin={"l": 10, "r": 10, "t": 30, "b": 10},
                              title=f"Exposure by {name}", xaxis={"tickformat": ".0%"}, yaxis={"title": None})
            st.plotly_chart(fig, width="stretch", key=f"{key}_{name}")
