"""Market watch: what to avoid today, warnings, the watchlist's concentration, what moves together."""

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from fireant_crawler.sessions import final_session
from stock_ui import context, cross_data, exposure_panel, regime_data, watch_data, watchlist
from stock_ui.db import VN_TZ

PCT = st.column_config.NumberColumn(format="percent")

st.title("Market watch")
reader = context.reader()
data_dir = context.data_dir()
now = datetime.now(VN_TZ)
st.caption("Monitoring page with the latest data. Historical figures are averages over many cases, not "
           "forecasts and not investment advice. Do not build research hypotheses from this page.")

# Header -----------------------------------------------------------------------------------------
head = watch_data.header(reader)
if not context.freshness(head, "Market data") or head.value.empty or head.value["date"].iloc[0] is None:
    st.stop()
h = head.value.iloc[0]
data_day = h["date"].date() if hasattr(h["date"], "date") else h["date"]
final = final_session(now)
c1, c2, c3 = st.columns(3)
c1.metric("Data date", str(data_day))
c2.metric("Market regime", h["regime"] or "-")
change = (h["vnindex"] / h["vnindex_5ago"] - 1) if h["vnindex_5ago"] else None
c3.metric("VNINDEX", f"{h['vnindex']:,.2f}", None if change is None else f"{change:+.2%} over 5 sessions")
reg = regime_data.regimes(reader).value
if reg is not None and reg["latest"] is not None:
    latest = reg["latest"]
    st.caption("Regimes today (Regime Engine; terciles vs the last 500 sessions): " + " | ".join(
        f"{d}: **{'-' if pd.isna(latest[d]) else latest[d]}**" for d in regime_data.DIMENSIONS))
if data_day < final:
    st.warning(f"Data stops at {data_day} but the latest final session is {final}: run 'Full daily pipeline' "
               "on the Run tasks page.")

# Avoid and warnings ---------------------------------------------------------------------------------
left, right = st.columns([2, 3])
with left:
    st.subheader("Avoid (validated)")
    av = watch_data.avoid(reader)
    if av.value is None and not av.stale and av.note is None:
        st.info("No daily scan yet.")
    elif context.freshness(av, "Avoid list"):
        a = av.value
        if a["decision"]:
            st.caption(f"Sharp drop + heavy volume + sellers dominate. Validation: {a['decision'][0]} "
                       f"({a['decision'][1]}).")
        latest = a["days"][0] if a["days"] else None
        today = a["events"][a["events"]["scan_date"].dt.date == latest] if latest else a["events"]
        if today.empty:
            st.success(f"No stock to avoid on {latest}.")
        else:
            st.error("Avoid: " + ", ".join(today["symbol"]))
        st.caption("Last 5 scanned sessions")
        st.dataframe(a["events"], hide_index=True, width="stretch",
                     column_config={"return_1d": PCT})
with right:
    st.subheader("Warnings today (not validated)")
    liquid = st.toggle("Liquid stocks only (ADV > 1bn VND)", value=True)
    ev = watch_data.events_on(reader, data_day)
    hist = watch_data.event_history(reader).value
    ind = watch_data.industry_of(reader).value
    industry = dict(zip(ind["symbol"], ind["industry_l2"])) if ind is not None else {}
    if context.freshness(ev, "Events"):
        table = watch_data.warnings_table(ev.value, hist, industry, liquid)
        st.caption("Downside catalog events. hist_mean_10d = research-period average excess return over the next "
                   "10 sessions after such events (event study, descriptive).")
        st.dataframe(table, hide_index=True, width="stretch", height=360,
                     column_config={"return_1d": PCT, "hist_mean_10d": PCT,
                                    "adv_value_20": st.column_config.NumberColumn(format="compact")})

# Watchlist ----------------------------------------------------------------------------------------
st.subheader("My watchlist")
saved = watchlist.load(data_dir)
with st.form("watchlist"):
    text = st.text_area("Symbols (comma or space separated)", value=", ".join(saved), height=70)
    if st.form_submit_button("Save watchlist"):
        known = set(ind["symbol"]) if ind is not None else None
        symbols, rejected = watchlist.parse(text, known)
        watchlist.save(data_dir, symbols, now)
        saved = symbols
        if rejected:
            st.warning("Ignored: " + ", ".join(rejected))
if saved:
    flags = ev.value[ev.value["symbol"].isin(saved)] if ev.value is not None else None
    if flags is not None and not flags.empty:
        st.markdown("**Events today on your watchlist**")
        st.dataframe(flags.groupby("symbol")["event_type"].apply(lambda s: ", ".join(sorted(s))).reset_index(),
                     hide_index=True, width="stretch")
    else:
        st.caption(f"No catalog event on {data_day} for your watchlist.")
    wc = watch_data.watch_corr(reader, tuple(saved))
    if context.freshness(wc, "Watchlist correlations") and not wc.value.empty:
        pairs = wc.value
        grp = watch_data.groups(pairs)
        for g in grp:
            st.warning(f"About one position (correlation >= {watch_data.TOGETHER}): {', '.join(g)}")
        names = sorted(set(pairs["a"]) | set(pairs["b"]))
        mat = pairs.pivot(index="a", columns="b", values="corr").combine_first(
            pairs.pivot(index="b", columns="a", values="corr")).reindex(index=names, columns=names)
        for n in names:
            mat.loc[n, n] = 1.0
        fig = go.Figure(go.Heatmap(z=mat.values, x=names, y=names, zmin=-1, zmax=1, colorscale="RdBu",
                                   reversescale=True, text=mat.round(2).values, texttemplate="%{text}"))
        fig.update_layout(height=max(320, 28 * len(names)), margin={"l": 10, "r": 10, "t": 30, "b": 10},
                          title=f"120-session correlation, snapshot {pairs['snapshot'].iloc[0]}")
        st.plotly_chart(fig, width="stretch")
        missing = sorted(set(saved) - set(names))
        if missing:
            st.caption("Not among the 200 most liquid stocks of the snapshot (no correlation): " + ", ".join(missing))

if saved:
    with st.expander("Exposure of the watchlist (equal weights)", expanded=True):
        exposure_panel.render(reader, {s: 1.0 for s in saved}, key="watch")

# Moves together ----------------------------------------------------------------------------------
st.subheader("Moves together")
tp = watch_data.top_pairs(reader)
c1, c2 = st.columns(2)
with c1:
    if context.freshness(tp, "Top pairs") and not tp.value.empty:
        st.caption(f"Most correlated pairs (120 sessions, snapshot {tp.value['snapshot'].iloc[0]}). "
                   "Run 'Build cross-stock data' to refresh.")
        st.dataframe(tp.value.drop(columns=["snapshot"]), hide_index=True, width="stretch", height=380)
with c2:
    cl = cross_data.clusters(reader, now.date())
    if context.freshness(cl, "Clusters") and not cl.value.empty:
        small = cl.value[(cl.value["stocks"] >= 3) & (cl.value["stocks"] <= 14)]
        st.caption("Groups of stocks that move together (clusters of 3-14 stocks, 250 sessions)")
        st.dataframe(small[["stocks", "members", "main_industry_l2"]], hide_index=True, width="stretch", height=380)

st.subheader("Industry strength (descriptive)")
st.caption("Industry excess return vs VNINDEX. Industry momentum failed validation on 2026-10-08: this is "
           "context, not a signal.")
mom = cross_data.industry_momentum(reader, now.date())
if context.freshness(mom, "Industry strength") and not mom.value.empty:
    st.dataframe(mom.value, hide_index=True, width="stretch",
                 column_config={c: PCT for c in ("ret_5d", "ret_21d", "ret_63d")})
