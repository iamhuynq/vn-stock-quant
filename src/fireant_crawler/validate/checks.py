"""Data-quality checks on the warehouse. Each check is one SQL query returning offending rows.

Severity: error = the crawler or mapping is wrong; warn = suspicious source data; info = expected
market reality (suspensions, holidays) worth knowing about. Rules come from the probe and pilot.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import duckdb

Severity = Literal["error", "warn", "info"]
INDEX_FILTER = "symbol NOT IN ('VNINDEX', 'VN30', 'HNXINDEX', 'HNX30', 'UPINDEX')"


@dataclass(frozen=True)
class Check:
    name: str
    severity: Severity
    description: str
    sql: str          # returns offending rows; first column should identify the symbol/entity


@dataclass
class CheckResult:
    check: Check
    count: int
    sample: list[tuple]
    columns: list[str]
    accepted: int = 0     # error-level rows listed in validate/accepted.py (not counted)


# The last sessions of the VNINDEX calendar: error checks look at the data the next build will use.
RECENT_SESSIONS = 5
_RECENT = f"""(SELECT date FROM (SELECT DISTINCT date FROM quotes_daily WHERE symbol = 'VNINDEX')
              ORDER BY date DESC LIMIT {RECENT_SESSIONS})"""
LATEST_COVERAGE = 0.8      # since 2015 only one session fell below this ratio of traded stocks

CHECKS: tuple[Check, ...] = (
    Check("latest_session_incomplete", "error",
          f"the latest session has fewer than {LATEST_COVERAGE:.0%} of the previous session's traded stocks "
          "(incomplete download or mapping error)", f"""
        WITH s AS (SELECT date, row_number() OVER (ORDER BY date DESC) AS k
                   FROM (SELECT DISTINCT date FROM quotes_daily WHERE symbol = 'VNINDEX')),
        n AS (SELECT q.date, count(*) FILTER (WHERE q.total_volume > 0) AS traded FROM quotes_daily q
              JOIN s USING (date) WHERE s.k <= 2 AND {INDEX_FILTER} GROUP BY q.date)
        SELECT cur.date::VARCHAR AS date, cur.traded, prev.traded AS previous_traded
        FROM n cur JOIN n prev ON prev.date < cur.date
        WHERE cur.date = (SELECT max(date) FROM n) AND cur.traded < {LATEST_COVERAGE} * prev.traded"""),
    Check("recent_missing_required_fields", "error",
          f"NULL in a required field in the last {RECENT_SESSIONS} sessions: price_close, price_basic or total_volume on "
          "any row; price_open/high/low, deal_volume or putthrough_volume on a traded row (missing data, as opposed to "
          "values that disagree)", f"""
        SELECT date::VARCHAR AS date, symbol, price_open, price_high, price_low, price_close, price_basic,
               total_volume, deal_volume, putthrough_volume
        FROM quotes_daily
        WHERE date IN {_RECENT} AND {INDEX_FILTER}
          AND (price_close IS NULL OR price_basic IS NULL OR total_volume IS NULL
               OR (total_volume > 0 AND (price_open IS NULL OR price_high IS NULL OR price_low IS NULL
                                         OR deal_volume IS NULL OR putthrough_volume IS NULL)))"""),
    Check("recent_nonpositive_prices", "error",
          f"traded rows with a zero or negative price in the last {RECENT_SESSIONS} sessions", f"""
        SELECT date::VARCHAR AS date, symbol, price_open, price_high, price_low, price_close, total_volume
        FROM quotes_daily
        WHERE date IN {_RECENT} AND {INDEX_FILTER} AND total_volume > 0
          AND (price_open <= 0 OR price_high <= 0 OR price_low <= 0 OR price_close <= 0)"""),
    Check("recent_corrupt_source_dates", "error",
          f"source-wide volume-split corruption (> 20% of traded stocks) in the last {RECENT_SESSIONS} sessions",
          f"""
        SELECT date::VARCHAR AS date,
               count(*) FILTER (WHERE abs(total_volume - deal_volume - putthrough_volume) > 0.5) AS bad,
               count(*) AS traded
        FROM quotes_daily WHERE date IN {_RECENT} AND {INDEX_FILTER} AND total_volume > 0
        GROUP BY date HAVING bad > 0.2 * traded AND bad >= 5 ORDER BY date"""),
    Check("ohlc_consistency", "warn", "low <= min(open, close) and high >= max(open, close) (source anomalies)", """
        SELECT symbol, date, price_open, price_high, price_low, price_close FROM quotes_daily
        WHERE total_volume > 0 AND (price_low > least(price_open, price_close) + 1e-9
                                    OR price_high < greatest(price_open, price_close) - 1e-9)"""),
    Check("nonpositive_prices", "warn", "rows with a zero or negative open/high/low/close (source placeholders)", """
        SELECT symbol, date, price_open, price_high, price_low, price_close, total_volume FROM quotes_daily
        WHERE price_open <= 0 OR price_high <= 0 OR price_low <= 0 OR price_close <= 0"""),
    Check("adj_change_without_event", "warn",
          "adj_ratio change points (factor != 1) with no corporate action within 5 days; the source also adjusts "
          "for events outside the 3 event types (e.g. bonus shares)", """
        WITH x AS (SELECT symbol, date, adj_ratio, lag(adj_ratio) OVER (PARTITION BY symbol ORDER BY date) AS prev
                   FROM quotes_daily)
        SELECT symbol, date, prev, adj_ratio, prev / adj_ratio AS factor FROM x
        WHERE prev IS NOT NULL AND abs(prev / adj_ratio - 1) > 1e-6
          AND NOT EXISTS (SELECT 1 FROM corporate_actions a
                          WHERE a.symbol = x.symbol AND abs(datediff('day', a.ex_date, x.date)) <= 5)"""),
    Check("vwap_identity", "warn",
          "price_average ~ (total_value - putthrough_value) / (deal_volume * unit); price_average is rounded to the "
          "tick on many rows (UPCOM uses it as the next reference price), so allow max(0.1, 0.5%)", f"""
        SELECT symbol, date, price_average,
               (total_value - putthrough_value) / (deal_volume * unit) AS implied_average
        FROM quotes_daily
        WHERE {INDEX_FILTER} AND deal_volume > 0 AND total_value > putthrough_value
          AND abs((total_value - putthrough_value) / (deal_volume * unit) - price_average)
              > greatest(0.1, 0.005 * price_average)"""),
    Check("volume_split", "warn", "total_volume = deal_volume + putthrough_volume", """
        SELECT symbol, date, total_volume, deal_volume, putthrough_volume FROM quotes_daily
        WHERE abs(total_volume - deal_volume - putthrough_volume) > 0.5"""),
    Check("corrupt_source_dates", "warn",
          "dates where more than 20% of traded stocks break the volume split (source-wide corruption)", f"""
        SELECT date, count(*) FILTER (WHERE abs(total_volume - deal_volume - putthrough_volume) > 0.5) AS bad,
               count(*) AS traded
        FROM quotes_daily WHERE {INDEX_FILTER} AND total_volume > 0
        GROUP BY date HAVING bad > 0.2 * traded AND bad >= 5 ORDER BY date"""),
    Check("reference_price_rule", "warn",
          "price_basic = previous close (HOSE/HNX) or previous average price (UPCOM), except on adj_ratio change "
          "points; tolerance 0.1 for tick rounding (stocks, previous session traded)", f"""
        WITH x AS (SELECT symbol, date, price_basic, adj_ratio,
                          lag(price_close) OVER w AS prev_close, lag(price_average) OVER w AS prev_average,
                          lag(adj_ratio) OVER w AS prev_adj, lag(total_volume) OVER w AS prev_volume
                   FROM quotes_daily WHERE {INDEX_FILTER} WINDOW w AS (PARTITION BY symbol ORDER BY date))
        SELECT symbol, date, prev_close, prev_average, price_basic FROM x
        WHERE prev_close IS NOT NULL AND prev_volume > 0 AND adj_ratio = prev_adj
          AND abs(price_basic - prev_close) > 1e-6 AND abs(price_basic - prev_average) > 0.1"""),
    Check("marks_unparsed", "warn", "report mark titles the parser does not understand", """
        SELECT symbol, mark_id, label, title FROM report_marks WHERE NOT title_parsed"""),
    Check("events_unparsed", "warn", "corporate action titles the parser does not understand", """
        SELECT symbol, event_id, title FROM corporate_actions WHERE NOT title_parsed"""),
    Check("events_date_order", "warn", "payment_date or record_date earlier than ex_date", """
        SELECT symbol, event_id, ex_date, record_date, payment_date, title FROM corporate_actions
        WHERE payment_date < ex_date OR record_date < ex_date"""),
    Check("cash_dividend_without_amount", "warn", "cash dividends with no amount", """
        SELECT symbol, event_id, ex_date, title FROM corporate_actions
        WHERE event_type = 1 AND cash_per_share_vnd IS NULL"""),
    Check("universe_without_quotes", "warn", "listed stocks in the universe with no quote rows", """
        SELECT s.symbol, s.exchange FROM symbols_latest s
        WHERE s.type = 'stock' AND s.exchange IN ('HSX', 'HNX', 'UPCOM')
          AND NOT EXISTS (SELECT 1 FROM quotes_daily q WHERE q.symbol = s.symbol)"""),
    Check("targets_without_quotes", "info", "symbols whose quote task finished but returned no rows", """
        SELECT key AS symbol FROM crawl_state cs
        WHERE job = 'quotes' AND status = 'done'
          AND NOT EXISTS (SELECT 1 FROM quotes_daily q WHERE q.symbol = cs.key)"""),
    Check("failed_tasks", "warn", "crawl tasks currently marked failed", """
        SELECT key, job, chunk, last_error FROM crawl_state WHERE status = 'failed'"""),
    Check("missing_sessions", "info",
          "VNINDEX sessions missing between a symbol's first and last traded date (suspensions)", """
        WITH cal AS (SELECT date FROM quotes_daily WHERE symbol = 'VNINDEX')
        SELECT t.symbol, count(*) AS missing FROM symbol_trading_span t
        JOIN cal ON cal.date BETWEEN t.first_traded_date AND t.last_traded_date
        LEFT JOIN quotes_daily q ON q.symbol = t.symbol AND q.date = cal.date
        WHERE t.symbol <> 'VNINDEX' AND q.date IS NULL
        GROUP BY t.symbol ORDER BY missing DESC"""),
    Check("dates_outside_calendar", "info", "quote dates that VNINDEX does not have (HOSE closed)", """
        SELECT symbol, count(*) AS extra FROM quotes_daily
        WHERE symbol <> 'VNINDEX' AND date NOT IN (SELECT date FROM quotes_daily WHERE symbol = 'VNINDEX')
        GROUP BY symbol ORDER BY extra DESC"""),
    Check("forward_filled_tail", "info", "zero-volume rows after the last traded date (delisted filler)", """
        SELECT q.symbol, t.last_traded_date, count(*) AS filler_rows FROM quotes_daily q
        JOIN symbol_trading_span t USING (symbol)
        WHERE q.date > t.last_traded_date GROUP BY ALL HAVING count(*) > 5 ORDER BY filler_rows DESC"""),
)

SAMPLE_SIZE = 8


def run_checks(con: duckdb.DuckDBPyConnection, checks: tuple[Check, ...] = CHECKS,
               accepted: dict[str, dict[str, str]] | None = None) -> list[CheckResult]:
    """Error-level rows whose first column is listed in `accepted` (default: validate/accepted.py) are not
    counted; they are reported as accepted."""
    if accepted is None:
        from fireant_crawler.validate.accepted import ACCEPTED as accepted
    results = []
    for check in checks:
        if check.severity == "error":
            cursor = con.execute(check.sql)
            columns = [d[0] for d in cursor.description]
            rows = cursor.fetchall()
            keys = accepted.get(check.name, {})
            open_rows = [r for r in rows if str(r[0]) not in keys]
            results.append(CheckResult(check, len(open_rows), open_rows[:SAMPLE_SIZE], columns,
                                       len(rows) - len(open_rows)))
            continue
        count = con.execute(f"SELECT count(*) FROM ({check.sql})").fetchone()[0]
        cursor = con.execute(f"SELECT * FROM ({check.sql}) LIMIT {SAMPLE_SIZE}")
        columns = [d[0] for d in cursor.description]
        results.append(CheckResult(check, count, cursor.fetchall(), columns))
    return results


def render_validation_report(results: list[CheckResult], totals: dict[str, int], generated_at: datetime) -> str:
    lines = [f"# Validation report - {generated_at.isoformat(timespec='seconds')}", "", "## Table sizes"]
    lines += [f"- {name}: {count:,}" for name, count in totals.items()]
    lines += ["", "## Summary", "", "| check | severity | offending rows | rule |", "|---|---|---|---|"]
    lines += [f"| {r.check.name} | {r.check.severity} | {r.count:,}" + (f" (+{r.accepted} accepted)" if r.accepted else "")
              + f" | {r.check.description} |" for r in results]
    for r in results:
        if not r.count:
            continue
        lines += ["", f"## {r.check.name} ({r.check.severity}, {r.count:,})", r.check.description, "",
                  "| " + " | ".join(r.columns) + " |", "|" + "---|" * len(r.columns)]
        lines += ["| " + " | ".join("" if v is None else str(v) for v in row) + " |" for row in r.sample]
    return "\n".join(lines) + "\n"
