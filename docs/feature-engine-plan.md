# Plan: Feature Engine (Phase 2 of the Quant Research System)

<!-- type: feature -->
<!-- status: built 2026-10-04 (awaiting user review at step 7); approved with all recommended options (value-based volume, MA50/MA200 regime, count-based volume_imbalance, both target conventions) -->

Source of requirements: `quant_research_chung_khoan_viet_nam.md` sections 2-4, 12, 13, 21.4, 27.
Input: `data/warehouse.duckdb` (Phase 1, read-only). Storage engine: DuckDB (decided 2026-10-03;
PostgreSQL deferred to the API/dashboard phase).

## Goal

Turn raw daily data into a clean research panel, ~30 meaningful features and forward-looking targets
for every stock and session, with no look-ahead bias, so Phase 3 (pattern discovery) can ask
"after state X, what happens over T+1..T+10?".

## Scope

In scope:
- Clean daily panel (adjusted prices, filters, flags)
- Market table (VNINDEX returns, regime)
- Features from the document: return, volume, volatility, price position, supply/demand, foreign flow,
  market regime; plus liquidity and data-quality flags needed to use them safely
- Targets from the document (section 4), in a separate table from features
- Build metadata (version, data date, code hash), Parquet export, feature dictionary

Out of scope (later phases): pattern discovery, events, cross-stock statistics, backtest, ML,
industry-relative features, full financial-statement features.

## Architecture

```
warehouse.duckdb (ATTACH READ_ONLY)
        |
        v  quant build   (pure SQL in DuckDB, full rebuild, ~seconds-minutes)
research.duckdb
  daily_panel     cleaned stock-session rows, adjusted prices
  market_daily    VNINDEX returns, MA50/MA200, regime
  stock_features  features at date t, using data <= t only        (doc 21.4)
  stock_targets   outcomes after t, using data > t only
  feature_builds  build_id, feature_set_version, data_as_of, code_hash, row counts
  feature_target  view joining features + targets for research
        |
        v  quant export
data/parquet/research/*.parquet
```

- New package `src/quant_research/` in the same project, CLI `uv run quant <command>`.
- `research.duckdb` is fully derived: it can always be deleted and rebuilt. The warehouse is attached
  read-only, so Phase 2 can never modify Phase 1 data.
- Features and targets live in **separate tables** so a feature can never accidentally read a target.
- Every rebuild recomputes everything (5.5M rows): simpler and safer than incremental logic, and
  required anyway because `adj_ratio` is rewritten retroactively after every corporate action.

## 1. Daily panel (`daily_panel`)

Rows: `quotes_daily` joined with `symbol_industry`, keeping
- stocks only: `NOT is_fund`, not an index
- `date <= last_traded_date` (drops the zero-volume filler after delisting)
- `date >= first_traded_date`

Columns (adjusted = raw / adj_ratio):

| Column | Definition |
|--------|------------|
| `adj_open/high/low/close` | back-adjusted prices; used for every return/ratio |
| `close_raw`, `basic_raw` | raw prices; used only for absolute thresholds (e.g. price > 5,000 VND) |
| `deal_volume`, `deal_value` | matched only: `deal_value = total_value - putthrough_value` (VND) |
| `vwap_deal` | `deal_value / (deal_volume * unit)` (raw, thousand VND); exact, unlike rounded `price_average` |
| `is_traded` | `deal_volume > 0` |
| `session_index` | per-symbol session counter since `first_traded_date` (to drop the IPO period) |
| `exchange_now`, industry columns | current exchange and ICB (no history available) |
| `limit_up`, `limit_down` | close at the daily limit, approximate: band by **current** exchange (HOSE 7%, HNX 10%, UPCOM 15%) and `basic_raw`, rounded to tick |
| `bad_source_date` | `2025-07-16` (volume corruption found in Phase 1) |

## 2. Market table (`market_daily`)

From VNINDEX: `mkt_ret_1d/3d/5d/10d/20d`, `mkt_ma50`, `mkt_ma200`, `mkt_vol_20`, and

| Column | Definition |
|--------|------------|
| `trend_regime` | doc section 12: `above_ma200` / `below_ma200` |
| `market_regime` | **Bull** = close > MA200 and MA50 > MA200; **Bear** = close < MA200 and MA50 < MA200; else **Sideway** |
| `vol_regime` | `high` if `mkt_vol_20` > its trailing 250-session median, else `low` |

All computed with trailing windows only.

## 3. Features (`stock_features`, one row per symbol and date t, data <= t)

| Group (doc) | Feature | Definition |
|-------------|---------|------------|
| Return (3.1) | `return_1d/3d/5d/10d/20d` | `adj_close_t / adj_close_{t-n} - 1` |
| | `excess_return_5d/20d` | stock return minus VNINDEX return over the same window |
| Volume (3.2) | `volume_ratio_5/20` | `deal_value_t / mean(deal_value_{t-n..t-1})` (baseline excludes today) |
| | `volume_change` | `deal_value_t / deal_value_{t-1} - 1` |
| | `volume_zscore_20` | z-score of `ln(1 + deal_value_t)` vs the previous 20 sessions |
| Volatility (3.3) | `volatility_5/20` | stdev of `return_1d` over the window (incl. t) |
| | `atr_14_pct` | 14-session mean true range (adjusted) / `adj_close_t` |
| | `high_low_range` | `(high - low) / close` |
| | `gap` | `adj_open_t / adj_close_{t-1} - 1` |
| Price position (3.4, 3.5) | `close_position` | `(close - low) / (high - low)`, null when high = low |
| | `close_vs_avg_price` | `(close_raw - vwap_deal) / vwap_deal` |
| Supply/demand (2.2) | `order_imbalance` | `(buy_qty - sell_qty) / (buy_qty + sell_qty)` (order placements) |
| | `volume_imbalance` | `(buy_count - sell_count) / (buy_count + sell_count)` (order counts; see open question 3) |
| | `buy_pressure`, `sell_pressure` | `buy_qty / deal_volume`, `sell_qty / deal_volume` |
| | `buy_sell_ratio` | `buy_qty / sell_qty` |
| Foreign (2.3, 13) | `foreign_net_volume`, `foreign_net_value` | buy - sell (shares, VND) |
| | `foreign_net_3d/5d/20d` | rolling sum of `foreign_net_value` |
| | `foreign_net_ratio_20` | `foreign_net_20d / sum(deal_value, 20d)` (size-normalised) |
| | `foreign_intensity` | `(foreign_buy_value + foreign_sell_value) / total_value` |
| Regime (12) | `market_regime`, `trend_regime`, `vol_regime` | from `market_daily` at t |
| Liquidity | `adv_value_20` | mean `deal_value` over 20 sessions (VND), for universe filters |
| Quality flags | `is_traded`, `limit_up`, `limit_down`, `bad_source_date`, `session_index` | from the panel |

Rules:
- Windows count **sessions of that symbol**, not calendar days.
- A window feature is null until enough history exists (no partial windows).
- Volume features use **matched value (VND), not shares**, because share volume jumps after stock
  dividends/splits while value does not (see open question 1).
- Order-flow features are null where the source has no order statistics (before ~2007, some gaps).
- Ratios with a zero denominator are null, never infinite.

## 4. Targets (`stock_targets`, one row per symbol and date t, data > t)

Two conventions, both kept:

| Target | Definition | Use |
|--------|------------|-----|
| `fwd_ret_close_1d/3d/5d/10d` | doc section 4: `adj_close_{t+h} / adj_close_t - 1` | statistics, comparable to the doc |
| `fwd_ret_exec_3d/5d/10d/20d` | `adj_close_{t+h} / adj_open_{t+1} - 1`: enter at next open, exit at close | tradable; respects T+2 settlement (no exit before t+3) |
| `fwd_excess_exec_5d/10d/20d` | exec return minus VNINDEX over the same span | removes market moves |
| `fwd_max_return_5d` | `max(adj_high_{t+1..t+5}) / adj_open_{t+1} - 1` | doc section 4 |
| `fwd_max_drawdown_5d` | `min(adj_low_{t+1..t+5}) / adj_open_{t+1} - 1` | doc section 4 |
| `y_up3_5d` | `fwd_ret_close_5d > 0.03` | doc section 4 classification target |
| `entry_blocked` | session t+1 opens at the limit-up price (cannot buy) | tradability |
| `target_complete` | all h future sessions exist and none is filler | filter |

## 5. Research periods (doc section 18)

`research` <= 2023-12-31, `validation` 2024-2025, `holdout` 2026+. Each row carries `period` by date t.
Rows whose target window crosses into the next period are flagged `crosses_period` (purge them when
testing). Phase 2 only labels periods; enforcing the holdout rule belongs to Phase 3.

## 6. Leakage safeguards (doc section 27.1)

1. Features and targets are separate tables, built by separate SQL files.
2. Feature SQL uses only `ROWS BETWEEN n PRECEDING AND CURRENT ROW` (or `1 PRECEDING` for baselines);
   target SQL uses only `FOLLOWING`. A test greps the SQL to enforce this.
3. **Perturbation test**: change every row after date d in a test panel; all features on or before d
   must be identical, all targets on or before d must change accordingly.
4. Back-adjusted prices are used only in ratios (scale-invariant); absolute price thresholds use raw prices.
5. Report release dates are not used in Phase 2.

## 7. Implementation steps

1. Package skeleton `quant_research` (config, CLI `quant`, research DB with read-only ATTACH).
2. `daily_panel.sql` + `market_daily.sql`; tests on fixtures (VOS ex-date: `return_1d` on 2026-10-01
   must be about -0.85%, not -7.9%; FLC filler rows excluded; ETF excluded).
3. `features.sql`; hand-computed unit tests on a small synthetic panel for every feature.
4. `targets.sql`; hand-computed tests; perturbation leakage test.
5. `feature_builds` metadata, `quant build [--dry-run]`, `quant status`, `quant export`.
6. Full build on real data; sanity report (null rates per feature per year, distributions, spot checks
   on VOS/HPG/FPT); `docs/feature-dictionary.md`.
7. **Checkpoint: review the sanity report with the user.**

## Success criteria

- [ ] `quant build` completes on the full warehouse; warehouse file hash unchanged afterwards
- [ ] Every feature and target has a hand-computed unit test
- [ ] Perturbation test proves no feature uses data after t
- [ ] VOS 2026-10-01 `return_1d` reflects the dividend adjustment
- [ ] No infinite values; null rates per feature explained in the sanity report
- [ ] ETFs and delisting filler rows absent from the panel
- [ ] `feature_builds` records version, data date and code hash; Parquet export readable from pandas

## Testing

- All: `uv run pytest`
- Single file: `uv run pytest tests/research/test_features.py`
- Single test: `uv run pytest tests/research/test_features.py::test_volume_ratio_excludes_today`
- Integration: full build on the real warehouse (no mocks)

## Rollback

Phase 2 writes only to `data/research.duckdb` and `data/parquet/research/`, both derived.
- Bad build: `rm data/research.duckdb && uv run quant build`.
- The warehouse is attached `READ_ONLY`; a test asserts its hash is unchanged after a build.

## Open questions (need user decision)

1. **Volume features on matched value (VND) instead of share volume** (split/stock-dividend safe).
   Recommended. Alternative: share volume adjusted by stock-dividend ratios from `corporate_actions`.
2. **Market regime**: Bull/Bear/Sideway via MA50 vs MA200 (recommended) or the doc's simpler
   above/below MA200 only. Both columns are produced either way; the question is which one Phase 3 uses
   by default.
3. **`volume_imbalance`** is listed in the doc without a formula. Proposed: imbalance of order
   **counts**, complementing `order_imbalance` on quantities. Confirm or give your definition.
4. **Targets**: keep both the doc's close-to-close targets and the executable next-open targets
   (recommended), or only one convention.

## Result (2026-10-04)

Built on the full warehouse in ~14 s: `daily_panel` / `stock_features` / `stock_targets` 5,209,888 rows,
`market_daily` 6,370 rows; `research.duckdb` 1.8 GB; warehouse file hash unchanged; 100 tests pass.
Every feature and target is checked against an independent pure-Python reference on a synthetic
warehouse with planted traps (ex-date, ETF, delisting filler, zero prices, ceiling, price jump), plus a
perturbation test for look-ahead. Sanity report: `data/reports/feature-sanity-2026-10-04.md`.
Feature reference: `docs/feature-dictionary.md`.

Spot checks: VOS 2026-10-01 `return_1d` = -0.85% (dividend-adjusted); VOS 2026-07-30 `limit_up` = true;
ETFs and FLC filler excluded; 0 infinite values.

Bugs found by the reference/sanity checks and fixed:
- DuckDB `greatest()` ignores NULLs: true range on the first session and `log_value` for missing values
  were non-NULL. Both guarded explicitly.
- 1,498 source rows with zero prices produced infinities; dropped from the panel and added to
  `fireant validate` (`nonpositive_prices`).
- 16 rows with negative matched value (put-through > total, mostly 2025-07-16): set to NULL.
- Rebuilding in place grew the file to 3.6 GB; builds now write a fresh file and atomically replace it
  (a failed build keeps the previous file; build history is carried over).

Additions beyond the original plan (data-quality flags): `price_jump` (adjusted one-day move > 40%,
737 rows), `fwd_has_price_jump_20d`, `foreign_inconsistent` (3,584 rows). A band-based jump test was
tried and rejected: without exchange history it flagged ~16,000 legitimate moves of stocks that
traded on UPCOM before moving to HOSE/HNX.

Open limitation: exchange history is unknown, so limit flags are approximate.

