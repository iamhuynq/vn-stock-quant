# Data Dictionary - FireAnt Research Warehouse

Source: `api.fireant.vn` (GET only), crawled by `fireant_crawler`. Warehouse: `data/warehouse.duckdb`.
Parquet copies: `data/parquet/*.parquet` (`uv run fireant export`).

## Reading the data

```python
import duckdb
con = duckdb.connect("data/warehouse.duckdb", read_only=True)
df = con.sql("SELECT * FROM quotes_daily_adjusted WHERE symbol = 'VOS' ORDER BY date").df()

# or from Parquet, no database needed
import pandas as pd
quotes = pd.read_parquet("data/parquet/quotes_daily.parquet")
```

## Units (read this first)

| Data | Unit |
|------|------|
| `quotes_daily` prices | **thousand VND, raw (unadjusted)**; `unit = 1000` |
| `quotes_daily` values (total, foreign, prop trading) | VND |
| `quotes_daily` volumes and counts | shares / orders, stored as DOUBLE (a few historical rows are non-integer) |
| `corporate_actions.cash_per_share_vnd`, `issue_price_vnd` | VND per share |
| `report_marks.revenue_bn`, `profit_bn` | billion VND |
| `fundamental_snapshots.*_vnd` | VND (52-week prices too, unlike quotes) |

## Tables and views

### `quotes_daily` - one row per symbol and session (PK `symbol, date`)

| Column | Meaning | Notes |
|--------|---------|-------|
| `price_open/high/low/close` | OHLC | raw; divide by `adj_ratio` for back-adjusted prices |
| `price_basic` | reference price (gia tham chieu) | HOSE/HNX: previous close; **UPCOM: previous average price**; differs on ex-dates |
| `price_average` | **matched-order VWAP, excludes put-through, often rounded to the tick** | `~ (total_value - putthrough_value) / (deal_volume * unit)`; compute the exact VWAP yourself if needed |
| `total_volume`, `deal_volume`, `putthrough_volume` | total = matched + put-through | **2025-07-16 is corrupt in the source** (`total < deal` for all stocks) |
| `total_value`, `putthrough_value` | VND | |
| `buy/sell_foreign_quantity/value` | foreign investor flow | |
| `buy_count`, `buy_quantity`, `sell_count`, `sell_quantity` | **order placements** (not fills) | basis for order-imbalance features |
| `current_foreign_room` | remaining foreign room | does not reconcile with daily foreign net flow; do not derive flows from it |
| `prop_trading_net_*` | proprietary trading net value | mostly zero before recent years |
| `adj_ratio` | cumulative adjustment factor relative to the latest session | rewritten for all earlier rows after every corporate action |
| `fetched_at` | crawl time | |

Indices (`VNINDEX`, `VN30`, `HNXINDEX`, `HNX30`, `UPINDEX`) share the table; `price_average` and
`price_basic` have index-specific meanings there.

### `quotes_daily_adjusted` (view)
`adj_open/high/low/close/basic = raw / adj_ratio`. Volumes stay raw. Use this for returns.

### `adj_ratio_segments` - every `adj_ratio` observed per fetch (PK `symbol, fetched_at, start_date`)
Lets you see how adjustment factors changed over time. Adjacent segments of the same fetch with the
same `adj_ratio` are one segment split at a page/window boundary.

### `symbol_trading_span` (view)
`first_traded_date`, `last_traded_date` (last session with volume > 0), `last_row_date`.
Delisted symbols are forward-filled with zero volume after `last_traded_date`: **filter
`date <= last_traded_date`** in research.

### `corporate_actions` - market-wide since 2000 (PK `event_id`)

| Column | Meaning |
|--------|---------|
| `event_type` / `event_type_name` | 1 cash_dividend, 2 stock_dividend, 3 rights_issue |
| `ex_date` | **ex-rights date (KHQ)** - FireAnt calls it `recordDate` |
| `record_date` | record date (chot danh sach) - FireAnt `registrationDate` |
| `payment_date` | payment/execution date - FireAnt `executionDate`; null for ~9% |
| `period_year`, `installment` | e.g. "dot 1/2025" -> 2025, 1 |
| `cash_per_share_vnd` | cash dividends |
| `ratio_held`, `ratio_received` | "ty le 100:15": hold 100, receive 15 (stock dividends, rights) |
| `issue_price_vnd` | rights issue price |

### `report_marks` - financial report releases and corporate-action marks (PK `symbol, mark_id`)
Label `F` = financial report: `period_type` (Q/Y), `fiscal_year`, `fiscal_quarter`, `revenue_bn`,
`profit_bn`, `*_yoy_pct` as published (the source restates prior periods, so do not recompute growth
from these columns). Labels `D`, `S`, `I` = cash dividend, stock dividend, rights issue marks.

**Point-in-time rule:** `release_date` has no time of day. Treat a report as known from the
**next session** after `release_date` to avoid look-ahead bias.

### `fundamental_snapshots` (PK `symbol, fetched_at`)
Current values only (shares outstanding, free float, ownership, EPS/PE TTM). History accumulates one
snapshot per crawl day; values before the first crawl do not exist.

### `symbols_latest` (view over `symbols`)
`exchange` (HSX/HNX/UPCOM; OTC = delisted or never listed), `type`, `is_listing` (unreliable alone),
`icb_code` (8-digit ICB), `source` (`search` = listed universe, `symbol` = delisted candidate lookup).

### `icb_industries` (PK `industry_code`)
ICB levels 1-4 (2/4/6/8-digit codes). Use the `symbol_industry` view rather than joining by hand.

### `symbol_industry` (view) - industry hierarchy per stock-typed symbol
`industry_l1..l4` and `industry_l1_code..l4_code` from the 8-digit `icb_code` (prefixes of 2/4/6/8 digits).
**`is_fund`**: the API types funds and ETFs as `stock` (24 listed: `FUE*`, `E1VFVN30`, `FUCT*`...,
plus delisted closed-end funds). Always filter `NOT is_fund` for equity research.
Listed universe today: 1,546 = 1,522 equities + 24 funds; 6 equities have no industry
(`VBT`, `GDH` coded `00000000`; `AAN`, `DTR`, `GTX`, `V68` uncoded). ICB groups are coarse
(e.g. level-4 "Van tai bien" mixes shipping lines and ports); `industry_code` (4-digit, old ICB) is legacy.

```sql
SELECT industry_l2, count(*) FROM symbol_industry
WHERE exchange IN ('HSX', 'HNX', 'UPCOM') AND NOT is_fund GROUP BY 1 ORDER BY 2 DESC;
```

## Known limitations

- Survivorship: delisted companies that never had a dividend or rights issue are missing.
- `adj_ratio` also reflects events outside the 3 event types (e.g. bonus shares); 9 change points have no matching event.
- 29 delisted candidates returned no quote history at all.
- No intraday, tick or order-book data.
- `fundamental_snapshots` and share counts have no history before the first crawl.
- Data quality report: `uv run fireant validate` -> `data/reports/validation-{date}.md`.
