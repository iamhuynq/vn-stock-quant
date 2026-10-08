# Plan: Fundamental factors (direction B, beyond the doc roadmap)

<!-- type: feature -->
<!-- status: STOPPED 2026-10-08 after step 0 (decision of the user); see 'Outcome' -->

## Why

Every signal tested so far failed **because of trading costs**: short horizons, high turnover, 0.4% per
round trip. Fundamental factors (value, quality, growth, size) change slowly. Portfolios rebalance monthly
or quarterly, so costs are a small fraction of any effect. They are also the best-documented family of
cross-sectional effects in emerging markets, and the doc's data list (section 2) does not cover them.

## What exists already (no new requests needed)

- `report_marks` (label F): release dates of quarterly and annual financial reports with revenue and profit
  **as released**. There are 64,488 quarterly marks for 1,330 symbols, the bulk from 2006 onward, and
  1,100+ symbols a year since 2017. The reporting lag after the quarter end has a median of 30 days and a
  95th percentile of 30-35 days.
- `fundamental_snapshots`: weekly snapshots of current values only (no history).

## Candidate endpoints (FireAnt swagger, GET)

| Endpoint | Returns | Use |
|----------|---------|-----|
| `/symbols/all-financial-data?type=Q&count=N` | `financialValues` per symbol and quarter for **all** symbols | Bulk history in few requests, if `count` allows it |
| `/symbols/{symbol}/financial-data?type=Q&count=N` | The same for one symbol | Delisted symbols; fallback |
| `/symbols/{symbol}/full-financial-reports?type=1..4&year&quarter` | Full statements line by line | Only if the summary fields are not enough |

## Risks to check before building anything (step 0)

1. **Restated numbers (look-ahead).** The API probably returns the **latest** figures, which may have
   been restated after the first release. A factor computed on restated data uses information not known
   at the time. Check: compare API quarterly revenue and profit with `report_marks` (as released) for the
   same quarters, and measure how often and how much they differ.
2. **Survivorship.** Does `all-financial-data` include delisted companies? If not, they come from the
   per-symbol endpoint (the backtest universe already includes delisted stocks).
3. **Depth and units.** How many quarters are available, the field names (EPS, equity, shares outstanding,
   assets, debt...), units (VND vs billion), and the bank / insurer / broker layouts (`companyType`).

## Steps

0. **Probe (needs your OK: the token is used for about 10 GET requests, whitelist extended by 2 GET
   paths).**
   - Requests: `all-financial-data` type=Q with count=1, then a larger count; `financial-data` for FPT,
     VCB, HPG, SSI and one delisted stock.
   - Output: `data/reports/fundamental-probe-*.md` with fields, depth, units, restatement rate and delisted
     coverage.
   - Then decide, with you, whether to continue.
1. **Crawl job `financials`**: backfill, plus quarterly refresh in the weekly update. Raw store, then
   warehouse table `financial_values (symbol, year, quarter, field, value, fetched_at)`; re-runnable,
   GET-only, rate-limited like every other job.
2. **Point-in-time availability**:
   - a quarter's figures become usable from the session **after** its `report_marks` release date;
   - without a mark, from the quarter end + 45 days (conservative), flagged;
   - growth uses the as-released revenue and profit of `report_marks` where possible (no restatement
     risk).
3. **Monthly factor table** in research.duckdb, as of each month end:
   - value: E/P (TTM), B/P, S/P;
   - quality: ROE, ROA, gross margin, leverage;
   - growth: revenue and profit YoY as released;
   - size: market cap (price x shares).
   Banks and financials are kept separately where a ratio does not apply.
4. **Tests (logged, few)**:
   - per factor, the top quintile (by month, within the liquid universe) minus the universe, next 20
     sessions from the next open, monthly, Newey-West, turnover and net-of-cost reported;
   - about 10 factors, so 10 logged tests;
   - discovery on research (<= 2023);
   - a candidate goes to a **pre-registered** validation run (2024-2025, a new family), then to forward
     tracking.
5. **UI**: fundamentals on the Symbol page (as available on each date) and a factor page (quintile
   returns over time).

## Rollback

- Additive.
- Remove the job and its tables and revert the whitelist (2 lines).
- Raw files stay, as for every other job.
- Runs are invalidated, never deleted.

## Decision needed now

Approve **step 0 only** (about 10 GET requests with your token, read-only, whitelist +2 GET paths). Steps 1-5
are planned in detail after the probe shows what the data allows.

## Outcome (2026-10-08): stopped after step 0

The probe ran: 20 GET requests, about 10 more than approved because of an accidental re-run, which was
reported. Report: `data/reports/fundamental-probe-2026-10-08.md`; raw responses kept in
`data/raw/probe_financials/`.

Findings:
- `financial-data` has rich data: about 419 fields, quarterly from 2008-2009, delisted companies included.
- It is unreliable: 16 of 20 requests returned HTTP 404 at random, and `all-financial-data` never
  answered.
- The values could not be shown to be as first published (possible restatements).

Decision: direction B is stopped. The two whitelist paths and the `probe-financials` command were removed,
so the crawler is back to its previous scope. The probe report and raw files are kept for reference if the
direction is revisited.
