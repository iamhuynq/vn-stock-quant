# Plan: "Market watch" dashboard page

<!-- type: feature -->
<!-- status: built 2026-10-08 -->

Goal: one page in the local UI answering "what should I avoid today, and which stocks move together?"
with the latest data. It replaces the manual queries of 2026-10-08. Read-only, like every UI page. It uses
existing tables only (`daily_events`, `event_study_stats`, `cross.duckdb` snapshots); no new research and
no logged tests.

## Layout

```
+----------------------------------------------------------------------------------+
| Market watch - data 2026-10-07 (latest final session 2026-10-08: run pipeline!)  |
| Regime: Bear | VNINDEX 1,753.39 (+0.9% 5 sessions)                               |
+----------------------------------------------------------------------------------+
| AVOID (validated signal)          | WARNINGS TODAY (event study, not validated)  |
| none today / list + last 5 days   | symbol | flags | events          | industry  |
|                                   | KOS    | 3     | sell, breakdown, drop     |
|                                   | PNJ    | 2     | drop, breakdown ...       |
+----------------------------------------------------------------------------------+
| MY WATCHLIST  [FTS, BSI, CTS, PNJ, MWG ...]                                      |
|  - flags today for each symbol                                                   |
|  - correlation matrix (120 sessions) + "these behave like one position" groups   |
+----------------------------------------------------------------------------------+
| MOVES TOGETHER                                                                   |
|  top correlated pairs (120 sessions) | clusters (3-14 stocks) | industry heatmap |
+----------------------------------------------------------------------------------+
| INDUSTRY STRENGTH (descriptive: momentum failed validation)                      |
+----------------------------------------------------------------------------------+
```

## Sections

1. **Header.**
   - Data date and market regime.
   - VNINDEX change over the last 5 sessions.
   - A staleness warning when the data is behind the latest final session, with a link to Run tasks.
2. **Avoid (validated).** Today's `drop3_volume2_sellers` events and the last 5 sessions. The validation
   result is shown verbatim.
3. **Warnings today.** Downside catalog events (BREAKDOWN, ORDER_IMBALANCE_SPIKE_SELL, PRICE_DROP,
   DIVERGENCE_DOWN_FOREIGN_BUY, FOREIGN_SELL_SPIKE).
   - One row per symbol, sorted by the number of flags.
   - Each row shows the industry and liquidity, plus the event study's historical mean and win rate (10
     sessions).
   - Labelled clearly: "historical averages, not validated, not advice".
4. **Watchlist.**
   - You enter your symbols.
   - The page shows each symbol's flags today, the correlation matrix (120 sessions, latest snapshot) and
     the groups with correlation >= 0.6, highlighted as "about one position" (concentration risk).
5. **Moves together.**
   - The top correlated pairs (120 sessions), with industry.
   - The small clusters of 3-14 stocks.
   - The industry correlation heatmap.
   - All at the latest snapshot.
6. **Industry strength.** Industry excess return over 5 and 21 sessions, labelled "descriptive (industry
   momentum failed validation on 2026-10-08)".

## Decisions (defaults)

| Topic | Default | Why |
|-------|---------|-----|
| Data period | **Latest data** (2024 onward included), with a banner: "for monitoring; do not build hypotheses from this page" | Monitoring needs current relations. The research pages keep their 2023 cap |
| Watchlist storage | A small JSON file `data/ui/watchlist.json` | Survives restarts. Not a database, so the read-only rule for databases holds |
| Liquidity filter | Warnings only for stocks with 20-session average traded value > 1bn VND (toggle to show all) | Same universe as research; avoids noise from illiquid names |
| Refresh | Like the other pages: cached reads, a "pipeline running" banner, refresh after a task | Existing behaviour |

## Tests

- The page renders on synthetic data and on real data, with no exception and database files unchanged.
- The watchlist is saved and reloaded, and invalid symbols are ignored.
- The warnings table equals a direct query of `daily_events`.
- The staleness banner appears when the data date is older than the latest final session.
- The full suite stays green.

## Open question

Persist the watchlist to `data/ui/watchlist.json` (default), or keep it only for the browser session?

## Result (2026-10-08)

- `src/stock_ui/pages/watch.py`: the default page of the UI. Helpers live in `watch_data.py` (queries,
  warnings table, union-find groups) and `watchlist.py` (JSON file `data/ui/watchlist.json`, atomic
  write).
- New Run tasks button "Build cross-stock data" (`quant cross build`), so the correlation snapshot can
  be refreshed. It is not part of the daily pipeline.
- 234 tests pass (5 new):
  - parsing and storage;
  - groups;
  - the warnings table;
  - the page renders read-only;
  - the staleness banner;
  - saving the watchlist through the form.
- On real data (2026-10-07), the page renders with no error and leaves the database files unchanged:
  - the avoid list is empty;
  - 33 liquid stocks carry downside flags, led by PNJ and KOS with 3 each;
  - the top pairs and clusters come from the 2026-10-02 snapshot.
