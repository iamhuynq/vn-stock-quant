"""Plotly figure for the Symbol page: price with moving averages, volume, foreign flow, order imbalance."""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

MOVING_AVERAGES = (20, 50, 200)
ROW_HEIGHTS = (0.52, 0.16, 0.16, 0.16)


def _marker_y(prices: pd.DataFrame, when: pd.Series, factor: float) -> list[float]:
    """Place a marker just above (factor > 1) or below the high/low of the nearest session on or after a date."""
    idx = prices.set_index("date")
    if idx.empty:
        return [float("nan")] * len(when)
    out = []
    for d in when:
        pos = idx.index.searchsorted(d)
        row = idx.iloc[min(pos, len(idx) - 1)]
        out.append(float(row["high"] if factor > 1 else row["low"]) * factor)
    return out


EVENT_COLORS = {"up": "#27ae60", "down": "#c0392b", "none": "#7f8c8d"}


def symbol_figure(prices: pd.DataFrame, panel: pd.DataFrame, actions: pd.DataFrame, marks: pd.DataFrame,
                  title: str, events: pd.DataFrame | None = None) -> go.Figure:
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.02, row_heights=list(ROW_HEIGHTS),
                        subplot_titles=(title, "Volume (matched)", "Foreign net value (VND)", "Order imbalance"))
    fig.add_trace(go.Candlestick(x=prices["date"], open=prices["open"], high=prices["high"], low=prices["low"],
                                 close=prices["close"], name="price", showlegend=False), row=1, col=1)
    for n in MOVING_AVERAGES:
        fig.add_trace(go.Scatter(x=prices["date"], y=prices["close"].rolling(n).mean(), name=f"MA{n}",
                                 mode="lines", line={"width": 1}), row=1, col=1)

    lo, hi = prices["date"].min(), prices["date"].max()
    if not actions.empty:
        a = actions[(actions["ex_date"] >= lo) & (actions["ex_date"] <= hi)]
        if not a.empty:
            fig.add_trace(go.Scatter(x=a["ex_date"], y=_marker_y(prices, a["ex_date"], 1.03), mode="markers",
                                     marker={"symbol": "triangle-down", "size": 10, "color": "#8e44ad"},
                                     name="ex-date", text=a["event_type_name"] + ": " + a["title"].fillna(""),
                                     hoverinfo="x+text"), row=1, col=1)
    if not marks.empty:
        m = marks[(marks["release_date"] >= lo) & (marks["release_date"] <= hi)]
        if not m.empty:
            fig.add_trace(go.Scatter(x=m["release_date"], y=_marker_y(prices, m["release_date"], 0.97),
                                     mode="markers", marker={"symbol": "square", "size": 7, "color": "#2471a3"},
                                     name="report (BCTC)", text=m["title"].fillna(m["label"]),
                                     hoverinfo="x+text"), row=1, col=1)
    flagged = panel[panel["price_jump"].fillna(False) | panel["foreign_inconsistent"].fillna(False)
                    | panel["bad_source_date"].fillna(False)]
    if not flagged.empty:
        fig.add_trace(go.Scatter(x=flagged["date"], y=_marker_y(prices, flagged["date"], 1.06), mode="markers",
                                 marker={"symbol": "x", "size": 8, "color": "#c0392b"}, name="data-quality flag",
                                 hoverinfo="x"), row=1, col=1)

    if events is not None and not events.empty:
        e = events[(events["date"] >= lo) & (events["date"] <= hi)]
        if not e.empty:
            g = e.groupby("date").agg(types=("event_type", lambda s: ", ".join(s)),
                                      direction=("direction", "first")).reset_index()
            fig.add_trace(go.Scatter(x=g["date"], y=_marker_y(prices, g["date"], 0.94), mode="markers",
                                     marker={"symbol": "diamond", "size": 7,
                                             "color": [EVENT_COLORS.get(x, "#7f8c8d") for x in g["direction"]]},
                                     name="catalog event", text=g["types"], hoverinfo="x+text"), row=1, col=1)

    fig.add_trace(go.Bar(x=panel["date"], y=panel["volume"], name="volume", showlegend=False,
                         marker_color="#7f8c8d"), row=2, col=1)
    fnv = panel["foreign_net_value"]
    fig.add_trace(go.Bar(x=panel["date"], y=fnv, name="foreign net", showlegend=False,
                         marker_color=["#27ae60" if v >= 0 else "#c0392b" for v in fnv.fillna(0)]), row=3, col=1)
    fig.add_trace(go.Scatter(x=panel["date"], y=panel["order_imbalance"], name="order imbalance",
                             showlegend=False, mode="lines", line={"width": 1, "color": "#d35400"}), row=4, col=1)
    fig.update_xaxes(rangebreaks=[{"bounds": ["sat", "mon"]}], rangeslider_visible=False)
    fig.update_layout(height=820, margin={"l": 10, "r": 10, "t": 40, "b": 10},
                      legend={"orientation": "h", "y": 1.04, "x": 0}, hovermode="x unified")
    return fig


def _normalized(series: pd.Series) -> pd.Series:
    first = series.dropna()
    return series / first.iloc[0] - 1 if not first.empty and first.iloc[0] else series * float("nan")


def equity_figure(daily: pd.DataFrame, title: str) -> go.Figure:
    """Backtest: strategy vs random-control median, equal weight and VNINDEX (cumulative return), plus drawdown."""
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.72, 0.28],
                        subplot_titles=(title, "Strategy drawdown"))
    for col, name, style in (("equity", "strategy", {"width": 2, "color": "#d35400"}),
                             ("random_median", "random control (median)", {"width": 1, "dash": "dot"}),
                             ("equal_weight", "equal weight", {"width": 1}), ("vnindex", "VNINDEX", {"width": 1})):
        if col in daily:
            fig.add_trace(go.Scatter(x=daily["date"], y=_normalized(daily[col]), name=name, mode="lines", line=style),
                          row=1, col=1)
    dd = daily["equity"] / daily["equity"].cummax() - 1
    fig.add_trace(go.Scatter(x=daily["date"], y=dd, name="drawdown", fill="tozeroy", showlegend=False,
                             line={"width": 1, "color": "#c0392b"}), row=2, col=1)
    fig.update_yaxes(tickformat=".0%")
    fig.update_layout(height=560, margin={"l": 10, "r": 10, "t": 40, "b": 10},
                      legend={"orientation": "h", "y": 1.08, "x": 0}, hovermode="x unified")
    return fig


def paper_figure(daily: pd.DataFrame) -> go.Figure:
    """Forward paper portfolio vs the 5-95% band of random controls, equal weight and VNINDEX."""
    fig = go.Figure()
    base = daily["equity"].iloc[0]
    fig.add_trace(go.Scatter(x=daily["date"], y=daily["random_p95"] / base - 1, mode="lines", line={"width": 0},
                             showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=daily["date"], y=daily["random_p05"] / base - 1, mode="lines", line={"width": 0},
                             fill="tonexty", fillcolor="rgba(127,140,141,0.25)", name="random 5-95%"))
    for col, name, style in (("equity", "strategy", {"width": 2, "color": "#d35400"}),
                             ("random_median", "random median", {"width": 1, "dash": "dot"}),
                             ("equal_weight", "equal weight", {"width": 1}), ("vnindex", "VNINDEX", {"width": 1})):
        fig.add_trace(go.Scatter(x=daily["date"], y=daily[col] / base - 1, name=name, mode="lines", line=style))
    fig.update_yaxes(tickformat=".1%")
    fig.update_layout(height=420, margin={"l": 10, "r": 10, "t": 30, "b": 10},
                      legend={"orientation": "h", "y": 1.1, "x": 0}, hovermode="x unified")
    return fig
