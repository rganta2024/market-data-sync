-- ==============================================================================
-- SCHEMA DEFINITION: Stock Metadata, Daily OHLCV & Options Data
-- Location: C:\Users\ganta\OneDrive\ClaudeCode\Fidelity\OHLC_Data_Supabase\schema.sql
-- ==============================================================================

-- 1. Stock Symbol Metadata Table
CREATE TABLE IF NOT EXISTS symbol_metadata (
    symbol VARCHAR(16) PRIMARY KEY,
    name TEXT NOT NULL,
    exchange VARCHAR(32),
    asset_class VARCHAR(32) DEFAULT 'US_EQUITY',
    asset_type VARCHAR(32) DEFAULT 'ETF',          -- 'ETF', 'Leveraged ETF', 'Inverse ETF', 'Common Stock', etc.
    theme VARCHAR(64),                             -- 'Tech & AI', 'Crypto', 'Broad Market Index', 'Semiconductors', etc.
    status VARCHAR(16) DEFAULT 'ACTIVE',
    tradable BOOLEAN DEFAULT TRUE,
    marginable BOOLEAN DEFAULT TRUE,
    fractionable BOOLEAN DEFAULT TRUE,
    shortable BOOLEAN DEFAULT TRUE,
    easy_to_borrow BOOLEAN DEFAULT TRUE,
    is_leveraged BOOLEAN DEFAULT FALSE,
    is_inverse BOOLEAN DEFAULT FALSE,
    leverage_factor NUMERIC(4, 2) DEFAULT 1.0,     -- e.g. 2.0, 3.0, -1.0, -2.0, -3.0
    last_synced_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Daily Stock OHLCV & Comprehensive Technical Indicators Table
CREATE TABLE IF NOT EXISTS stock_ohlc_daily (
    symbol VARCHAR(16) NOT NULL REFERENCES symbol_metadata(symbol) ON DELETE CASCADE,
    date DATE NOT NULL,
    
    -- Price & Volume
    open NUMERIC(14, 4) NOT NULL,
    high NUMERIC(14, 4) NOT NULL,
    low NUMERIC(14, 4) NOT NULL,
    close NUMERIC(14, 4) NOT NULL,
    volume BIGINT NOT NULL,
    trade_count BIGINT,
    vwap NUMERIC(14, 4),
    
    -- Price Changes
    change_dollar NUMERIC(14, 4),
    change_pct NUMERIC(10, 4),
    
    -- Moving Averages (Trend)
    sma_20 NUMERIC(14, 4),
    sma_50 NUMERIC(14, 4),
    sma_200 NUMERIC(14, 4),
    ema_9 NUMERIC(14, 4),
    ema_20 NUMERIC(14, 4),
    ema_50 NUMERIC(14, 4),
    ema_200 NUMERIC(14, 4),
    
    -- Momentum & Oscillators
    rsi_14 NUMERIC(10, 4),
    macd NUMERIC(14, 4),
    macd_signal NUMERIC(14, 4),
    macd_hist NUMERIC(14, 4),
    stoch_k NUMERIC(10, 4),
    stoch_d NUMERIC(10, 4),
    adx_14 NUMERIC(10, 4),
    
    -- Volatility & Bands
    bb_upper NUMERIC(14, 4),
    bb_middle NUMERIC(14, 4),
    bb_lower NUMERIC(14, 4),
    bb_width NUMERIC(10, 4),
    atr_14 NUMERIC(14, 4),
    
    -- Volume Analysis
    vol_sma_20 BIGINT,
    vol_ratio NUMERIC(10, 4),
    obv BIGINT,
    
    -- 52-Week High/Low Analytics
    high_52w NUMERIC(14, 4),
    low_52w NUMERIC(14, 4),
    pct_from_52w_high NUMERIC(10, 4),
    pct_from_52w_low NUMERIC(10, 4),
    
    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    PRIMARY KEY (symbol, date)
);

-- Performance Indexes for Stock OHLC
CREATE INDEX IF NOT EXISTS idx_stock_ohlc_symbol_date ON stock_ohlc_daily (symbol, date DESC);
CREATE INDEX IF NOT EXISTS idx_stock_ohlc_date ON stock_ohlc_daily (date DESC);
CREATE INDEX IF NOT EXISTS idx_stock_ohlc_rsi ON stock_ohlc_daily (rsi_14) WHERE rsi_14 IS NOT NULL;

-- 3. Options Contracts Metadata Table
CREATE TABLE IF NOT EXISTS option_contracts_metadata (
    option_symbol VARCHAR(32) PRIMARY KEY,
    underlying_symbol VARCHAR(16) NOT NULL,
    contract_type VARCHAR(8) NOT NULL,             -- 'CALL' or 'PUT'
    strike_price NUMERIC(12, 4) NOT NULL,
    expiration_date DATE NOT NULL,
    style VARCHAR(16) DEFAULT 'AMERICAN',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. Daily Options OHLCV & Greeks Table
CREATE TABLE IF NOT EXISTS option_ohlc_daily (
    option_symbol VARCHAR(32) NOT NULL,
    date DATE NOT NULL,
    underlying_symbol VARCHAR(16) NOT NULL,
    contract_type VARCHAR(8) NOT NULL,             -- 'CALL' or 'PUT'
    strike_price NUMERIC(12, 4) NOT NULL,
    expiration_date DATE NOT NULL,
    days_to_exp INTEGER,
    
    -- OHLCV
    open NUMERIC(12, 4) NOT NULL,
    high NUMERIC(12, 4) NOT NULL,
    low NUMERIC(12, 4) NOT NULL,
    close NUMERIC(12, 4) NOT NULL,
    volume BIGINT NOT NULL,
    trade_count BIGINT,
    vwap NUMERIC(12, 4),
    
    -- Quotes & Pricing
    bid NUMERIC(12, 4),
    ask NUMERIC(12, 4),
    mid_price NUMERIC(12, 4),
    
    -- Greeks & Implied Volatility
    implied_volatility NUMERIC(10, 4),
    delta NUMERIC(10, 4),
    gamma NUMERIC(10, 4),
    theta NUMERIC(10, 4),
    vega NUMERIC(10, 4),
    rho NUMERIC(10, 4),
    
    -- Moneyness Analytics
    underlying_close NUMERIC(12, 4),
    moneyness_pct NUMERIC(10, 4),                  -- ((Strike - Underlying) / Underlying) * 100
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    PRIMARY KEY (option_symbol, date)
);

-- Performance Indexes for Options OHLC
CREATE INDEX IF NOT EXISTS idx_opt_ohlc_underlying_date ON option_ohlc_daily (underlying_symbol, date DESC);
CREATE INDEX IF NOT EXISTS idx_opt_ohlc_exp_strike ON option_ohlc_daily (underlying_symbol, expiration_date, strike_price);
CREATE INDEX IF NOT EXISTS idx_opt_ohlc_date ON option_ohlc_daily (date DESC);

-- 5. Views
-- Stock Latest Snapshot View
CREATE OR REPLACE VIEW v_stock_latest_snapshot AS
WITH ranked_ohlc AS (
    SELECT 
        o.*,
        ROW_NUMBER() OVER(PARTITION BY o.symbol ORDER BY o.date DESC) AS rn
    FROM stock_ohlc_daily o
)
SELECT 
    m.symbol,
    m.name,
    m.exchange,
    m.asset_type,
    m.theme,
    m.is_leveraged,
    m.is_inverse,
    m.leverage_factor,
    r.date AS latest_date,
    r.open,
    r.high,
    r.low,
    r.close,
    r.volume,
    r.vwap,
    r.change_dollar,
    r.change_pct,
    r.sma_20,
    r.sma_50,
    r.sma_200,
    r.ema_9,
    r.ema_20,
    r.ema_50,
    r.ema_200,
    r.rsi_14,
    r.macd,
    r.macd_signal,
    r.macd_hist,
    r.stoch_k,
    r.stoch_d,
    r.adx_14,
    r.bb_upper,
    r.bb_middle,
    r.bb_lower,
    r.bb_width,
    r.atr_14,
    r.vol_sma_20,
    r.vol_ratio,
    r.high_52w,
    r.low_52w,
    r.pct_from_52w_high,
    r.pct_from_52w_low
FROM symbol_metadata m
LEFT JOIN ranked_ohlc r ON m.symbol = r.symbol AND r.rn = 1
ORDER BY m.symbol ASC;

-- Options Latest Snapshot View
CREATE OR REPLACE VIEW v_option_latest_chain AS
WITH ranked_opt AS (
    SELECT 
        o.*,
        ROW_NUMBER() OVER(PARTITION BY o.option_symbol ORDER BY o.date DESC) AS rn
    FROM option_ohlc_daily o
)
SELECT 
    option_symbol,
    underlying_symbol,
    date AS latest_date,
    contract_type,
    strike_price,
    expiration_date,
    days_to_exp,
    open,
    high,
    low,
    close,
    volume,
    trade_count,
    vwap,
    bid,
    ask,
    mid_price,
    implied_volatility,
    delta,
    gamma,
    theta,
    vega,
    rho,
    underlying_close,
    moneyness_pct
FROM ranked_opt
WHERE rn = 1
ORDER BY underlying_symbol ASC, expiration_date ASC, strike_price ASC;
