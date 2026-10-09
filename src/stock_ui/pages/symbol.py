"""C. Symbol lookup: chart with markers, latest features, events the symbol triggered."""

from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from stock_ui import context, symbol_data
from stock_ui.charts import symbol_figure

RANGES = {"6M": 182, "1Y": 365, "3Y": 3 * 365, "5Y": 5 * 365, "All": None}
MA_WARMUP_DAYS = 300          # extra history so MA200 is defined at the left edge

st.title("Symbol lookup")
reader = context.reader()

syms = symbol_data.symbols(reader)
if not context.freshness(syms, "Symbol list"):
    st.stop()
table = syms.value


by_symbol = table.set_index("symbol", drop=False)
options = list(by_symbol.index)


def _label(sym: str) -> str:
    r = by_symbol.loc[sym]
    status = "" if r["is_listing"] else " - delisted"
    return f"{sym} - {r['name']} ({r['exchange']}{status})"


c1, c2, c3 = st.columns([3, 2, 1])
symbol = c1.selectbox("Symbol", options, format_func=_label, index=options.index("FPT") if "FPT" in options else 0,
                      key="symbol")
span = c2.radio("Range", list(RANGES), index=1, horizontal=True)
adjusted = c3.toggle("Adjusted", value=True, help="Back-adjusted for dividends and rights (raw / adj_ratio)")
row = by_symbol.loc[symbol]

st.markdown(f"### {symbol} - {row['name']}")
st.caption(" | ".join(str(x) for x in (
    row["exchange"], row["industry_l1"] or "unclassified", row["industry_l4"] or "",
    "fund/ETF" if row["is_fund"] else "stock", "listed" if row["is_listing"] else "delisted",
    f"traded {row['first_traded_date']} to {row['last_traded_date']}") if x))

days = RANGES[span]
view_start = date(1990, 1, 1) if days is None else date.today() - timedelta(days=days)
query_start = view_start if days is None else view_start - timedelta(days=MA_WARMUP_DAYS)

panel = symbol_data.panel(reader, symbol, query_start)
if not context.freshness(panel, "Price history") or panel.value.empty:
    st.info("No price history for this symbol in the research database.")
    st.stop()
pdf = panel.value
if adjusted:
    prices = pdf[["date", "open", "high", "low", "close"]]
else:
    raw = symbol_data.raw_prices(reader, symbol, query_start)
    if not context.freshness(raw, "Raw prices") or raw.value.empty:
        st.info("Raw prices are not available right now; switch 'Adjusted' back on.")
        st.stop()
    prices = raw.value

actions = symbol_data.corporate_actions(reader, symbol).value
marks = symbol_data.report_marks(reader, symbol).value
actions = actions if actions is not None else pd.DataFrame(columns=["ex_date", "event_type_name", "title"])
marks = marks if marks is not None else pd.DataFrame(columns=["release_date", "label", "title"])

events = symbol_data.catalog_events(reader, symbol, query_start).value
if events is not None:
    events = events.assign(date=pd.to_datetime(events["date"]))      # copy: the cached frame stays untouched
fig = symbol_figure(prices, pdf, actions, marks, f"{symbol} {'adjusted' if adjusted else 'raw'} price", events)
fig.update_xaxes(range=[pd.Timestamp(max(view_start, pdf["date"].min().date())), pdf["date"].max()])
st.plotly_chart(fig, width="stretch")
st.caption("Markers: triangle = ex-date (corporate action), square = financial report release, "
           "diamond = catalog event (green up, red down, grey neutral; types in the tooltip), "
           "x = data-quality flag (price jump > 40%, foreign value > total value, or corrupt source date).")

c1, c2 = st.columns(2)
with c1:
    st.subheader("Latest features")
    feats = symbol_data.latest_features(reader, symbol)
    if context.freshness(feats, "Features") and not feats.value.empty:
        f = feats.value.iloc[0]
        st.caption(f"as of {str(f['date'])[:10]} (period: {f['period']})")
        st.dataframe(pd.DataFrame({"feature": f.index[2:], "value": [str(v) for v in f.values[2:]]}),
                     hide_index=True, width="stretch", height=420)
with c2:
    st.subheader("Pattern events (daily scanner)")
    ev = symbol_data.daily_events(reader, symbol)
    if ev.value is None and not ev.stale and ev.note is None:
        st.caption("No daily scan has run yet.")
    elif context.freshness(ev, "Events"):
        if ev.value.empty:
            st.caption("This symbol has not triggered any pattern in the scanned sessions.")
        else:
            st.dataframe(ev.value, hide_index=True, width="stretch", height=420)

t1, t2, t3, t4 = st.tabs(["Corporate actions", "Financial reports", "Catalog events", "Factors"])
t1.dataframe(actions, hide_index=True, width="stretch")
t2.dataframe(marks, hide_index=True, width="stretch")
if events is None:
    t3.caption("No event catalog in the research database yet: run `quant build`.")
else:
    t3.dataframe(events, hide_index=True, width="stretch")
fac = symbol_data.factors(reader, symbol)
with t4:
    if fac.value is None and not fac.stale and fac.note is None:
        st.caption("No factor scores in the research database yet: run `quant build`.")
    elif context.freshness(fac, "Factors"):
        latest, history = fac.value["latest"], fac.value["history"]
        if latest.empty:
            st.caption("Not in the scoring universe on any recent date (liquid stocks only, ADV > 1bn VND).")
        else:
            st.caption(f"Factor set f1 on {latest['date'].iloc[0]:%Y-%m-%d}: rank_pct 0 = lowest, 1 = highest of the "
                       "liquid universe that day; bucket = quintile; z_industry = z minus its industry average. "
                       "Descriptive, not a forecast.")
            st.dataframe(latest.drop(columns=["date"]), hide_index=True, width="stretch",
                         column_config={"rank_pct": st.column_config.ProgressColumn(min_value=0, max_value=1)})
            fig = px.line(history, x="date", y="rank_pct", color="factor")
            fig.update_layout(height=360, margin={"l": 10, "r": 10, "t": 30, "b": 10},
                              title="Rank in the liquid universe, last 12 months", yaxis={"range": [0, 1]})
            st.plotly_chart(fig, width="stretch", key="symbol_factors")
