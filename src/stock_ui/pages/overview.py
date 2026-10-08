"""A. Overview: is the system healthy?"""

from datetime import UTC, datetime

import streamlit as st

from stock_ui import context, status
from stock_ui.db import VN_TZ

st.title("Overview")
data_dir = context.data_dir()
reader = context.reader()
now = datetime.now(UTC)


def _fmt_ts(value) -> str:
    if value is None:
        return "-"
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    return value.astimezone(VN_TZ).strftime("%Y-%m-%d %H:%M") if getattr(value, "tzinfo", None) else str(value)


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:,.0f} {unit}"
        n /= 1024
    return f"{n:,.1f} TB"


# Pipeline -------------------------------------------------------------------------------------
st.subheader("Pipeline")
p = status.pipeline(data_dir)
c1, c2, c3 = st.columns(3)
c1.metric("Last completed session", p.done_session or "none")
if p.lock is None:
    c2.metric("Pipeline lock", "free")
else:
    state = "stale" if p.lock.stale else "running"
    c2.metric("Pipeline lock", f"{state}: {p.lock.owner}", f"pid {p.lock.pid}, {p.lock.age_seconds / 60:.0f} min",
              delta_color="off")
c3.metric("Scheduler (launchd)", "installed" if p.launchd_installed else "not installed")
if not p.launchd_installed:
    st.caption("Runs are manual. Install with `scripts/install_launchd.sh install` when you decide to.")
if p.last_log:
    with st.expander(f"Last pipeline log: {p.last_log.name}"):
        st.code("\n".join(p.last_log_lines) or "(empty)", language=None)

# Data -----------------------------------------------------------------------------------------
st.subheader("Data (warehouse)")
wh = status.warehouse(reader)
if context.freshness(wh, "Warehouse"):
    f = wh.value
    cov = status.coverage(f)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Latest session", str(f["latest_date"]) if f["latest_date"] else "-")
    c2.metric("Rows vs previous session", "-" if cov is None else f"{cov * 100:.1f}%",
              help="Raw rows on the latest session divided by the previous one; the daily scan needs >= 95%")
    c3.metric("Last API call", _fmt_ts(f["last_api_call"]))
    c4.metric("Failed crawl tasks", f"{f['failed_count']:,}")
    if cov is not None and cov < 0.95:
        st.warning("The latest session looks incomplete in the warehouse; `quant daily` will not scan it yet.")
    if f["failed_count"]:
        with st.expander("Latest failed tasks"):
            st.dataframe(f["failed"], hide_index=True, width="stretch")
    if f["schema_changes"]:
        st.error(f"Schema: {len(f['schema_changes'])} pending change(s). Run the 'Schema check' task, "
                 "then `uv run fireant migrate` in a terminal.")
        st.code("\n".join(f["schema_changes"]), language=None)
    else:
        st.success("Schema up to date")

# Research build -------------------------------------------------------------------------------
st.subheader("Research database")
rs = status.research(reader)
if context.freshness(rs, "Research DB") and not rs.value.empty:
    b = rs.value.iloc[0]
    c1, c2, c3 = st.columns(3)
    c1.metric("Feature set", f"{b['feature_set_version']} ({b['build_id']})")
    c2.metric("Data as of", str(b["data_as_of"])[:10])
    c3.metric("Built at", _fmt_ts(b["built_at"]))
    current = status.is_current_build(b["warehouse_fetched_at"], wh.value["fetched_at"]) if wh.value else None
    if current is False:
        st.warning("The warehouse has newer data than the last build: run 'Build features'.")
    elif current:
        st.success("Built from the current warehouse")

# Daily scan -----------------------------------------------------------------------------------
st.subheader("Daily scan")
dl = status.daily(reader)
if dl.value is None and not dl.stale and dl.note is None:
    st.info("No daily scan yet: run 'Scan and daily report'.")
elif context.freshness(dl, "Results DB"):
    st.dataframe(dl.value["scans"], hide_index=True, width="stretch")
report = status.latest_report(data_dir)
if report:
    with st.expander(f"Latest daily report: {report.name}"):
        st.markdown(report.read_text())

# Validation -----------------------------------------------------------------------------------
st.subheader("Data validation")
v = status.latest_validation(data_dir)
if v is None:
    st.info("No validation report yet: run 'Validate data'.")
else:
    path, counts, errors = v
    st.write(f"Latest report: `{path.name}` - failing checks: {counts['error']} error, {counts['warn']} warn, "
             f"{counts['info']} info")
    if errors:
        st.error("Error-level checks failing: " + ", ".join(errors))

# Token and disk -------------------------------------------------------------------------------
st.subheader("Token and disk")
t = status.token(context.settings().token, now)
c1, c2 = st.columns(2)
if t.present and t.expires_at:
    c1.metric("Token expires", t.expires_at.astimezone(VN_TZ).strftime("%Y-%m-%d"), f"{t.days_left:.0f} days left",
              delta_color="off")
else:
    c1.metric("Token", "set (expiry unknown)" if t.present else "missing")
if t.warning:
    c1.error(t.warning)
if t.orders_write:
    c1.caption("The token has the orders-write scope: keep .env private. The crawler whitelist blocks order endpoints.")
c2.dataframe([{"item": n, "size": _size(s)} for n, s in status.disk(data_dir)], hide_index=True, width="stretch")
