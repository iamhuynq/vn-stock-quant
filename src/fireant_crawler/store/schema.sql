-- FireAnt research warehouse (DuckDB).
-- Units:
--   quotes_daily prices: thousand VND, raw/unadjusted (unit = 1000); adjusted = raw / adj_ratio
--   quotes_daily values (total_value, foreign values, prop trading): VND
--   volumes/counts: stored as DOUBLE exactly as served (a few historical rows are non-integer)
--   corporate_actions cash_per_share_vnd, issue_price_vnd: VND per share
--   report_marks revenue_bn, profit_bn: billion VND
--   fundamental_snapshots *_vnd: VND (52-week prices are VND, not thousand VND)

CREATE TABLE IF NOT EXISTS symbols (
    symbol          VARCHAR NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL,
    name            VARCHAR,
    exchange        VARCHAR,
    type            VARCHAR,
    is_listing      BOOLEAN,
    industry_code   VARCHAR,
    icb_code        VARCHAR,
    source          VARCHAR,
    PRIMARY KEY (symbol, fetched_at)
);

CREATE TABLE IF NOT EXISTS quotes_daily (
    symbol                      VARCHAR NOT NULL,
    date                        DATE NOT NULL,
    fetched_at                  TIMESTAMPTZ NOT NULL,
    price_open                  DOUBLE,
    price_high                  DOUBLE,
    price_low                   DOUBLE,
    price_close                 DOUBLE,
    price_average               DOUBLE,
    price_basic                 DOUBLE,
    total_volume                DOUBLE,
    deal_volume                 DOUBLE,
    putthrough_volume           DOUBLE,
    total_value                 DOUBLE,
    putthrough_value            DOUBLE,
    buy_foreign_quantity        DOUBLE,
    buy_foreign_value           DOUBLE,
    sell_foreign_quantity       DOUBLE,
    sell_foreign_value          DOUBLE,
    buy_count                   DOUBLE,
    buy_quantity                DOUBLE,
    sell_count                  DOUBLE,
    sell_quantity               DOUBLE,
    adj_ratio                   DOUBLE,
    current_foreign_room        DOUBLE,
    prop_trading_net_deal_value DOUBLE,
    prop_trading_net_pt_value   DOUBLE,
    prop_trading_net_value      DOUBLE,
    unit                        DOUBLE,
    PRIMARY KEY (symbol, date)
);

-- Every adj_ratio segment ever observed. A new corporate action rewrites adj_ratio for all
-- earlier sessions, so each fetch appends its own segments instead of overwriting.
CREATE TABLE IF NOT EXISTS adj_ratio_segments (
    symbol      VARCHAR NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL,
    start_date  DATE NOT NULL,
    end_date    DATE NOT NULL,
    adj_ratio   DOUBLE,
    PRIMARY KEY (symbol, fetched_at, start_date)
);

CREATE TABLE IF NOT EXISTS corporate_actions (
    event_id            INTEGER PRIMARY KEY,
    symbol              VARCHAR NOT NULL,
    company_name        VARCHAR,
    event_type          INTEGER,
    event_type_name     VARCHAR,
    title               VARCHAR,
    ex_date             DATE,
    record_date         DATE,
    payment_date        DATE,
    period_year         INTEGER,
    installment         INTEGER,
    cash_per_share_vnd  DOUBLE,
    ratio_held          DOUBLE,
    ratio_received      DOUBLE,
    issue_price_vnd     DOUBLE,
    title_parsed        BOOLEAN,
    fetched_at          TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS report_marks (
    symbol           VARCHAR NOT NULL,
    mark_id          VARCHAR NOT NULL,
    label            VARCHAR,
    release_date     DATE,
    title            VARCHAR,
    period_type      VARCHAR,
    fiscal_year      INTEGER,
    fiscal_quarter   INTEGER,
    revenue_bn       DOUBLE,
    revenue_yoy_pct  DOUBLE,
    profit_bn        DOUBLE,
    profit_yoy_pct   DOUBLE,
    title_parsed     BOOLEAN,
    fetched_at       TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (symbol, mark_id)
);

CREATE TABLE IF NOT EXISTS fundamental_snapshots (
    symbol                VARCHAR NOT NULL,
    fetched_at            TIMESTAMPTZ NOT NULL,
    company_type          INTEGER,
    shares_outstanding    DOUBLE,
    free_shares           DOUBLE,
    beta                  DOUBLE,
    dividend_vnd          DOUBLE,
    dividend_yield        DOUBLE,
    market_cap_vnd        DOUBLE,
    low_52w_vnd           DOUBLE,
    high_52w_vnd          DOUBLE,
    price_change_1y       DOUBLE,
    avg_volume_10d        DOUBLE,
    avg_volume_3m         DOUBLE,
    pe                    DOUBLE,
    eps_vnd               DOUBLE,
    sales_ttm_vnd         DOUBLE,
    net_profit_ttm_vnd    DOUBLE,
    insider_ownership     DOUBLE,
    institution_ownership DOUBLE,
    foreign_ownership     DOUBLE,
    PRIMARY KEY (symbol, fetched_at)
);

CREATE TABLE IF NOT EXISTS icb_industries (
    industry_code VARCHAR PRIMARY KEY,
    level         INTEGER,
    name          VARCHAR,
    description   VARCHAR,
    fetched_at    TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS crawl_state (
    job         VARCHAR NOT NULL,
    key         VARCHAR NOT NULL,
    chunk       VARCHAR NOT NULL,
    status      VARCHAR NOT NULL,
    attempts    INTEGER NOT NULL,
    last_error  VARCHAR,
    updated_at  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (job, key, chunk)
);

CREATE SEQUENCE IF NOT EXISTS crawl_log_id;
CREATE TABLE IF NOT EXISTS crawl_log (
    id               BIGINT PRIMARY KEY DEFAULT nextval('crawl_log_id'),
    logged_at        TIMESTAMPTZ NOT NULL,
    job              VARCHAR,
    path             VARCHAR,
    status           INTEGER,
    elapsed_seconds  DOUBLE,
    attempts         INTEGER,
    error            VARCHAR
);

-- Latest snapshot per symbol.
CREATE OR REPLACE VIEW symbols_latest AS
SELECT * EXCLUDE (rn) FROM (
    SELECT *, row_number() OVER (PARTITION BY symbol ORDER BY fetched_at DESC) AS rn FROM symbols
) WHERE rn = 1;

-- Back-adjusted prices (cash dividends, stock dividends, rights). Volumes stay raw.
CREATE OR REPLACE VIEW quotes_daily_adjusted AS
SELECT
    symbol, date,
    price_open / adj_ratio  AS adj_open,
    price_high / adj_ratio  AS adj_high,
    price_low / adj_ratio   AS adj_low,
    price_close / adj_ratio AS adj_close,
    price_basic / adj_ratio AS adj_basic,
    total_volume, total_value, adj_ratio
FROM quotes_daily
WHERE adj_ratio IS NOT NULL AND adj_ratio > 0;

-- Last session with trades per symbol; delisted symbols are forward-filled with zero volume after it.
CREATE OR REPLACE VIEW symbol_trading_span AS
SELECT symbol,
       min(date) FILTER (WHERE total_volume > 0) AS first_traded_date,
       max(date) FILTER (WHERE total_volume > 0) AS last_traded_date,
       max(date) AS last_row_date
FROM quotes_daily
GROUP BY symbol;

-- One row per stock-typed symbol with its ICB hierarchy (8-digit icb_code: prefixes of 2/4/6/8 digits
-- are levels 1-4). The API types funds/ETFs as "stock": use is_fund to exclude them from equity research.
-- icb_code '00000000' means unclassified. Classification is current only (no history).
CREATE OR REPLACE VIEW symbol_industry AS
WITH s AS (
    SELECT symbol, name, exchange, NULLIF(icb_code, '00000000') AS icb_code,
           coalesce(name ILIKE 'Quỹ %' OR icb_code IN ('30204000', '30205000'), false) AS is_fund
    FROM symbols_latest WHERE type = 'stock'
)
SELECT s.symbol, s.name, s.exchange, s.is_fund, s.icb_code,
       l1.industry_code AS industry_l1_code, l1.name AS industry_l1,
       l2.industry_code AS industry_l2_code, l2.name AS industry_l2,
       l3.industry_code AS industry_l3_code, l3.name AS industry_l3,
       l4.industry_code AS industry_l4_code, l4.name AS industry_l4
FROM s
LEFT JOIN icb_industries l1 ON l1.industry_code = left(s.icb_code, 2)
LEFT JOIN icb_industries l2 ON l2.industry_code = left(s.icb_code, 4)
LEFT JOIN icb_industries l3 ON l3.industry_code = left(s.icb_code, 6)
LEFT JOIN icb_industries l4 ON l4.industry_code = s.icb_code;
