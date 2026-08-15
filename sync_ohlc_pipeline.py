import os
import sys
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

import pandas as pd
import numpy as np
import psycopg2
from psycopg2.extras import execute_values
import ta

# Fix Windows SSL Certificates if needed
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

# Ensure leveraged_tranche_engine config can be imported for credentials
sys.path.append(r"C:\Users\ganta\OneDrive\ClaudeCode\Fidelity\Fidelity_reoccuring_orders\leveraged_tranche_engine")
try:
    from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, ALPACA_PAPER
except ImportError:
    ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
    ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
    ALPACA_PAPER = True

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass, AssetStatus

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("OHLC_Pipeline")

SYMBOLS_FILE = os.path.join(os.path.dirname(__file__), "Fidelity_Symbols.txt")
HEDGE_DATABASE_URL = os.getenv("HEDGE_DATABASE_URL")

def get_db_connection():
    if not HEDGE_DATABASE_URL:
        raise ValueError("HEDGE_DATABASE_URL environment variable is missing.")
    return psycopg2.connect(HEDGE_DATABASE_URL)

def load_symbols() -> List[str]:
    if not os.path.exists(SYMBOLS_FILE):
        raise FileNotFoundError(f"Symbols file not found: {SYMBOLS_FILE}")
    with open(SYMBOLS_FILE, "r", encoding="utf-8") as f:
        symbols = [line.strip().upper() for line in f if line.strip() and not line.startswith("#")]
    logger.info(f"Loaded {len(symbols)} symbols from {SYMBOLS_FILE}")
    return sorted(list(set(symbols)))

def classify_symbol(symbol: str, name: str) -> Dict[str, Any]:
    name_upper = (name or "").upper()
    sym_upper = symbol.upper()
    
    # Specific known tickers map
    SECTOR_MAP = {
        # Mega-cap Tech & AI / Software
        "AAPL": ("Tech & AI", "Common Stock"),
        "MSFT": ("Tech & AI", "Common Stock"),
        "NVDA": ("Semiconductors", "Common Stock"),
        "AVGO": ("Semiconductors", "Common Stock"),
        "AMD": ("Semiconductors", "Common Stock"),
        "QCOM": ("Semiconductors", "Common Stock"),
        "INTC": ("Semiconductors", "Common Stock"),
        "TXN": ("Semiconductors", "Common Stock"),
        "AMAT": ("Semiconductors", "Common Stock"),
        "MU": ("Semiconductors", "Common Stock"),
        "SMH": ("Semiconductors", "ETF"),
        "AMZN": ("Consumer Discretionary", "Common Stock"),
        "GOOGL": ("Communication Services", "Common Stock"),
        "GOOG": ("Communication Services", "Common Stock"),
        "META": ("Communication Services", "Common Stock"),
        "NFLX": ("Communication Services", "Common Stock"),
        "DIS": ("Communication Services", "Common Stock"),
        "TSLA": ("Automotive & Clean Energy", "Common Stock"),
        "UBER": ("Tech & Mobility", "Common Stock"),
        "PLTR": ("Tech & AI", "Common Stock"),
        "ORCL": ("Tech & AI", "Common Stock"),
        "CRM": ("Tech & AI", "Common Stock"),
        "ADBE": ("Tech & AI", "Common Stock"),
        "CSCO": ("Tech & AI", "Common Stock"),
        "IBM": ("Tech & AI", "Common Stock"),
        "NOW": ("Tech & AI", "Common Stock"),
        # Financials
        "JPM": ("Financials", "Common Stock"),
        "BAC": ("Financials", "Common Stock"),
        "V": ("Financials", "Common Stock"),
        "MA": ("Financials", "Common Stock"),
        "BRK.B": ("Financials", "Common Stock"),
        "BRK.A": ("Financials", "Common Stock"),
        "XLF": ("Financials", "ETF"),
        # Healthcare & Pharma
        "LLY": ("Healthcare & Pharma", "Common Stock"),
        "UNH": ("Healthcare & Pharma", "Common Stock"),
        "JNJ": ("Healthcare & Pharma", "Common Stock"),
        "ABBV": ("Healthcare & Pharma", "Common Stock"),
        "MRK": ("Healthcare & Pharma", "Common Stock"),
        "XLV": ("Healthcare & Pharma", "ETF"),
        # Consumer Staples / Retail / Discretionary
        "COST": ("Consumer Staples", "Common Stock"),
        "WMT": ("Consumer Staples", "Common Stock"),
        "PG": ("Consumer Staples", "Common Stock"),
        "KO": ("Consumer Staples", "Common Stock"),
        "PEP": ("Consumer Staples", "Common Stock"),
        "HD": ("Consumer Discretionary", "Common Stock"),
        "XLY": ("Consumer Discretionary", "ETF"),
        "XLP": ("Consumer Staples", "ETF"),
        # Energy & Industrials
        "XOM": ("Energy", "Common Stock"),
        "CVX": ("Energy", "Common Stock"),
        "XLE": ("Energy", "ETF"),
        "CAT": ("Industrials", "Common Stock"),
        "GE": ("Industrials", "Common Stock"),
        "XLI": ("Industrials", "ETF"),
        "XLB": ("Materials", "ETF"),
        "XLU": ("Utilities", "ETF"),
        "XLC": ("Communication Services", "ETF"),
        "VNQ": ("Real Estate", "ETF"),
        # Broad Market & Fixed Income
        "SPY": ("Broad Market Index", "ETF"),
        "QQQ": ("Broad Market Index", "ETF"),
        "IWM": ("Broad Market Index", "ETF"),
        "DIA": ("Broad Market Index", "ETF"),
        "VOO": ("Broad Market Index", "ETF"),
        "TLT": ("Treasuries & Bonds", "ETF"),
        "HYG": ("Corporate Bonds", "ETF"),
        "LQD": ("Corporate Bonds", "ETF"),
        "AGG": ("Aggregate Bonds", "ETF"),
        "EEM": ("International & Emerging", "ETF"),
        "VWO": ("International & Emerging", "ETF"),
    }

    if sym_upper in SECTOR_MAP:
        theme, asset_type = SECTOR_MAP[sym_upper]
        return {
            "theme": theme,
            "asset_type": asset_type,
            "is_leveraged": False,
            "is_inverse": False,
            "leverage_factor": 1.0
        }

    # Check leverage multiplier
    leverage_factor = 1.0
    is_leveraged = False
    is_inverse = False
    
    if any(k in name_upper for k in ["3X", "3.0X", "TRIPLE"]):
        leverage_factor = 3.0
        is_leveraged = True
    elif any(k in name_upper for k in ["2X", "2.0X", "DOUBLE", "ULTRAPRO", "ULTRA"]):
        leverage_factor = 2.0
        is_leveraged = True
    elif any(k in name_upper for k in ["1.5X", "1.75X"]):
        leverage_factor = 1.5
        is_leveraged = True
    elif any(k in name_upper for k in ["SHORT", "BEAR", "INVERSE", "-1X", "-2X", "-3X", "ULTRASHORT"]):
        is_inverse = True
        
    if any(k in name_upper for k in ["SHORT", "BEAR", "INVERSE", "-1X", "-2X", "-3X", "ULTRASHORT"]):
        is_inverse = True
        if is_leveraged:
            leverage_factor = -abs(leverage_factor)
        else:
            leverage_factor = -1.0

    # Sector & Theme Classification
    theme = "Other / Multi-Asset"
    if any(k in name_upper for k in ["BITCOIN", "CRYPTO", "ETHER", "ETHEREUM", "COIN", "BTC", "ETH"]) or sym_upper in ["IBIT", "BITO", "BITU", "BITX", "ETHA", "ETHT", "CONI", "CONL", "HIVE"]:
        theme = "Crypto & Digital Assets"
    elif any(k in name_upper for k in ["SEMICONDUCTOR", "CHIPS", "SOX", "NVIDIA", "NVDA"]) or sym_upper in ["SOXL", "SOXQ", "NVDX", "NVDD", "SMCX", "SMCZ"]:
        theme = "Semiconductors"
    elif any(k in name_upper for k in ["AI ", "ARTIFICIAL INTELLIGENCE", "TECH", "TECHNOLOGY", "ROBOTIC", "SOFTWARE", "CLOUD", "BIG DATA"]) or sym_upper in ["AIQ", "AIBU", "IGV", "TECL", "FNGU", "FNGD", "BULZ"]:
        theme = "Tech & AI"
    elif any(k in name_upper for k in ["S&P 500", "NASDAQ", "DOW", "RUSSELL", "TOTAL STOCK", "ALL-WORLD", "EQUAL WEIGHT"]) or sym_upper in ["TQQQ", "SQQQ", "SPXL", "SPYI", "SPYU", "QLD", "UDOW", "DDM", "TNA", "RSP", "VTI", "VT", "VEU", "VTV", "URSP"]:
        theme = "Broad Market Index"
    elif any(k in name_upper for k in ["GOLD", "SILVER", "OIL", "ENERGY", "GAS", "URANIUM", "MINERS"]) or sym_upper in ["GLD", "SLV", "GUSH", "NRGU", "OILU", "GDXU", "GDXD", "URNJ"]:
        theme = "Commodities & Energy"
    elif any(k in name_upper for k in ["CHINA", "ASIA", "INDIA", "KOREA", "EUROPE", "EMERGING", "INTERNATIONAL"]) or sym_upper in ["AIA", "CQQQ", "FXI", "YINN", "INDL", "KORU", "EURL", "IXUS", "VXUS", "SCHF", "FLIN", "EDC", "AVEM"]:
        theme = "International & Emerging"
    elif any(k in name_upper for k in ["FINANCIAL", "BANK", "HEALTH", "BIOTECH", "AEROSPACE", "HOUSING", "HOMEBUILDER", "DEFENSE", "UTILITIES"]) or sym_upper in ["FAS", "DPST", "LABU", "XBI", "CURE", "DFEN", "NAIL", "DUSL"]:
        theme = "Sector & Thematic"
    elif "ETF" not in name_upper and "TRUST" not in name_upper and "SHARES" not in name_upper:
        theme = "Single Stock Equities"

    asset_type = "Common Stock"
    if "ETF" in name_upper or "TRUST" in name_upper or "SHARES" in name_upper or "FUND" in name_upper or "INDEX" in name_upper:
        if is_inverse and is_leveraged:
            asset_type = "Leveraged Inverse ETF"
        elif is_inverse:
            asset_type = "Inverse ETF"
        elif is_leveraged:
            asset_type = "Leveraged ETF"
        else:
            asset_type = "ETF"

    return {
        "theme": theme,
        "asset_type": asset_type,
        "is_leveraged": is_leveraged,
        "is_inverse": is_inverse,
        "leverage_factor": leverage_factor
    }

def sync_symbol_metadata(symbols: List[str], tc: TradingClient, conn) -> Dict[str, Any]:
    logger.info("Fetching asset metadata from Alpaca...")
    alpaca_assets = tc.get_all_assets(GetAssetsRequest(asset_class=AssetClass.US_EQUITY, status=AssetStatus.ACTIVE))
    asset_map = {a.symbol: a for a in alpaca_assets}
    
    records = []
    for sym in symbols:
        asset = asset_map.get(sym)
        if asset:
            name = asset.name or sym
            exchange = str(asset.exchange).replace("AssetExchange.", "")
            asset_class = str(asset.asset_class).replace("AssetClass.", "")
            status = str(asset.status).replace("AssetStatus.", "")
            tradable = asset.tradable
            marginable = asset.marginable
            fractionable = asset.fractionable
            shortable = asset.shortable
            easy_to_borrow = asset.easy_to_borrow
        else:
            name = sym
            exchange = "UNKNOWN"
            asset_class = "US_EQUITY"
            status = "ACTIVE"
            tradable = True
            marginable = True
            fractionable = True
            shortable = True
            easy_to_borrow = True

        clf = classify_symbol(sym, name)
        records.append((
            sym,
            name,
            exchange,
            asset_class,
            clf["asset_type"],
            clf["theme"],
            status,
            tradable,
            marginable,
            fractionable,
            shortable,
            easy_to_borrow,
            clf["is_leveraged"],
            clf["is_inverse"],
            clf["leverage_factor"],
            datetime.now(timezone.utc)
        ))

    upsert_sql = """
    INSERT INTO symbol_metadata (
        symbol, name, exchange, asset_class, asset_type, theme, status,
        tradable, marginable, fractionable, shortable, easy_to_borrow,
        is_leveraged, is_inverse, leverage_factor, last_synced_at
    ) VALUES %s
    ON CONFLICT (symbol) DO UPDATE SET
        name = EXCLUDED.name,
        exchange = EXCLUDED.exchange,
        asset_class = EXCLUDED.asset_class,
        asset_type = EXCLUDED.asset_type,
        theme = EXCLUDED.theme,
        status = EXCLUDED.status,
        tradable = EXCLUDED.tradable,
        marginable = EXCLUDED.marginable,
        fractionable = EXCLUDED.fractionable,
        shortable = EXCLUDED.shortable,
        easy_to_borrow = EXCLUDED.easy_to_borrow,
        is_leveraged = EXCLUDED.is_leveraged,
        is_inverse = EXCLUDED.is_inverse,
        leverage_factor = EXCLUDED.leverage_factor,
        last_synced_at = EXCLUDED.last_synced_at;
    """

    with conn.cursor() as cur:
        execute_values(cur, upsert_sql, records)
        conn.commit()
    logger.info(f"Upserted metadata for {len(records)} symbols into symbol_metadata table.")
    return asset_map

def compute_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    
    # 1. Price Changes
    df["prev_close"] = df["close"].shift(1)
    df["change_dollar"] = df["close"] - df["prev_close"]
    df["change_pct"] = (df["change_dollar"] / df["prev_close"]) * 100.0

    # 2. Moving Averages
    df["sma_20"] = ta.trend.sma_indicator(df["close"], window=20)
    df["sma_50"] = ta.trend.sma_indicator(df["close"], window=50)
    df["sma_200"] = ta.trend.sma_indicator(df["close"], window=200)
    
    df["ema_9"] = ta.trend.ema_indicator(df["close"], window=9)
    df["ema_20"] = ta.trend.ema_indicator(df["close"], window=20)
    df["ema_50"] = ta.trend.ema_indicator(df["close"], window=50)
    df["ema_200"] = ta.trend.ema_indicator(df["close"], window=200)

    # 3. Momentum & Oscillators
    df["rsi_14"] = ta.momentum.rsi(df["close"], window=14)
    
    macd = ta.trend.MACD(df["close"])
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_hist"] = macd.macd_diff()

    stoch = ta.momentum.StochasticOscillator(df["high"], df["low"], df["close"], window=14, smooth_window=3)
    df["stoch_k"] = stoch.stoch()
    df["stoch_d"] = stoch.stoch_signal()

    df["adx_14"] = ta.trend.adx(df["high"], df["low"], df["close"], window=14)

    # 4. Volatility & Bands
    bb = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    df["bb_upper"] = bb.bollinger_hband()
    df["bb_middle"] = bb.bollinger_mavg()
    df["bb_lower"] = bb.bollinger_lband()
    df["bb_width"] = bb.bollinger_wband()

    df["atr_14"] = ta.volatility.average_true_range(df["high"], df["low"], df["close"], window=14)

    # 5. Volume Analysis
    df["vol_sma_20"] = ta.trend.sma_indicator(df["volume"], window=20)
    df["vol_ratio"] = np.where(df["vol_sma_20"] > 0, df["volume"] / df["vol_sma_20"], 1.0)
    df["obv"] = ta.volume.on_balance_volume(df["close"], df["volume"])

    # 6. 52-Week High & Low (252 trading days rolling window)
    df["high_52w"] = df["high"].rolling(window=252, min_periods=20).max()
    df["low_52w"] = df["low"].rolling(window=252, min_periods=20).min()
    df["pct_from_52w_high"] = np.where(df["high_52w"] > 0, ((df["close"] - df["high_52w"]) / df["high_52w"]) * 100.0, 0.0)
    df["pct_from_52w_low"] = np.where(df["low_52w"] > 0, ((df["close"] - df["low_52w"]) / df["low_52w"]) * 100.0, 0.0)

    return df

def clean_val(v):
    if v is None or pd.isna(v) or np.isnan(v) or np.isinf(v):
        return None
    return v

def sync_all_stock_bars(symbols: List[str], data_client: StockHistoricalDataClient, conn, days_back: int = 400, keep_days: int = 150):
    logger.info(f"Fetching historical daily bars for {len(symbols)} symbols ({days_back} days lookback)...")
    
    start_dt = datetime.now(timezone.utc) - timedelta(days=days_back)
    batch_size = 30
    all_ohlc_records = []
    
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        logger.info(f"Downloading batch {i//batch_size + 1}/{(len(symbols) + batch_size - 1)//batch_size}: {batch[:4]}... ({len(batch)} symbols)")
        
        try:
            req = StockBarsRequest(
                symbol_or_symbols=batch,
                timeframe=TimeFrame.Day,
                start=start_dt
            )
            bars = data_client.get_stock_bars(req)
            if not bars.data:
                continue
                
            raw_df = bars.df.reset_index()
            if raw_df.empty:
                continue

            for sym, group in raw_df.groupby("symbol"):
                group = group.sort_values("timestamp").reset_index(drop=True)
                if len(group) < 5:
                    continue
                    
                processed_df = compute_technical_indicators(group)
                
                # Keep the desired period (e.g. 150 trading days to cover 120-day timeframe)
                recent_df = processed_df.tail(keep_days)
                
                for _, row in recent_df.iterrows():
                    bar_date = row["timestamp"].date()
                    all_ohlc_records.append((
                        sym,
                        bar_date,
                        float(row["open"]),
                        float(row["high"]),
                        float(row["low"]),
                        float(row["close"]),
                        int(row["volume"]),
                        int(row["trade_count"]) if pd.notna(row.get("trade_count")) else None,
                        float(row["vwap"]) if pd.notna(row.get("vwap")) else None,
                        clean_val(row.get("change_dollar")),
                        clean_val(row.get("change_pct")),
                        clean_val(row.get("sma_20")),
                        clean_val(row.get("sma_50")),
                        clean_val(row.get("sma_200")),
                        clean_val(row.get("ema_9")),
                        clean_val(row.get("ema_20")),
                        clean_val(row.get("ema_50")),
                        clean_val(row.get("ema_200")),
                        clean_val(row.get("rsi_14")),
                        clean_val(row.get("macd")),
                        clean_val(row.get("macd_signal")),
                        clean_val(row.get("macd_hist")),
                        clean_val(row.get("stoch_k")),
                        clean_val(row.get("stoch_d")),
                        clean_val(row.get("adx_14")),
                        clean_val(row.get("bb_upper")),
                        clean_val(row.get("bb_middle")),
                        clean_val(row.get("bb_lower")),
                        clean_val(row.get("bb_width")),
                        clean_val(row.get("atr_14")),
                        int(row["vol_sma_20"]) if pd.notna(row.get("vol_sma_20")) else None,
                        clean_val(row.get("vol_ratio")),
                        int(row["obv"]) if pd.notna(row.get("obv")) else None,
                        clean_val(row.get("high_52w")),
                        clean_val(row.get("low_52w")),
                        clean_val(row.get("pct_from_52w_high")),
                        clean_val(row.get("pct_from_52w_low")),
                    ))

        except Exception as e:
            logger.error(f"Error fetching batch {batch}: {e}")

    logger.info(f"Total processed OHLC rows ready for database: {len(all_ohlc_records)}")
    
    if not all_ohlc_records:
        logger.warning("No records to insert.")
        return

    upsert_ohlc_sql = """
    INSERT INTO stock_ohlc_daily (
        symbol, date, open, high, low, close, volume, trade_count, vwap,
        change_dollar, change_pct, sma_20, sma_50, sma_200, ema_9, ema_20, ema_50, ema_200,
        rsi_14, macd, macd_signal, macd_hist, stoch_k, stoch_d, adx_14,
        bb_upper, bb_middle, bb_lower, bb_width, atr_14,
        vol_sma_20, vol_ratio, obv, high_52w, low_52w, pct_from_52w_high, pct_from_52w_low,
        updated_at
    ) VALUES %s
    ON CONFLICT (symbol, date) DO UPDATE SET
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low = EXCLUDED.low,
        close = EXCLUDED.close,
        volume = EXCLUDED.volume,
        trade_count = EXCLUDED.trade_count,
        vwap = EXCLUDED.vwap,
        change_dollar = EXCLUDED.change_dollar,
        change_pct = EXCLUDED.change_pct,
        sma_20 = EXCLUDED.sma_20,
        sma_50 = EXCLUDED.sma_50,
        sma_200 = EXCLUDED.sma_200,
        ema_9 = EXCLUDED.ema_9,
        ema_20 = EXCLUDED.ema_20,
        ema_50 = EXCLUDED.ema_50,
        ema_200 = EXCLUDED.ema_200,
        rsi_14 = EXCLUDED.rsi_14,
        macd = EXCLUDED.macd,
        macd_signal = EXCLUDED.macd_signal,
        macd_hist = EXCLUDED.macd_hist,
        stoch_k = EXCLUDED.stoch_k,
        stoch_d = EXCLUDED.stoch_d,
        adx_14 = EXCLUDED.adx_14,
        bb_upper = EXCLUDED.bb_upper,
        bb_middle = EXCLUDED.bb_middle,
        bb_lower = EXCLUDED.bb_lower,
        bb_width = EXCLUDED.bb_width,
        atr_14 = EXCLUDED.atr_14,
        vol_sma_20 = EXCLUDED.vol_sma_20,
        vol_ratio = EXCLUDED.vol_ratio,
        obv = EXCLUDED.obv,
        high_52w = EXCLUDED.high_52w,
        low_52w = EXCLUDED.low_52w,
        pct_from_52w_high = EXCLUDED.pct_from_52w_high,
        pct_from_52w_low = EXCLUDED.pct_from_52w_low,
        updated_at = NOW();
    """

    db_records = [r + (datetime.now(timezone.utc),) for r in all_ohlc_records]
    
    logger.info("Executing bulk upsert into Supabase stock_ohlc_daily...")
    with conn.cursor() as cur:
        db_chunk_size = 2000
        for j in range(0, len(db_records), db_chunk_size):
            chunk = db_records[j : j + db_chunk_size]
            execute_values(cur, upsert_ohlc_sql, chunk)
            conn.commit()
            logger.info(f"Inserted/updated {min(j + db_chunk_size, len(db_records))}/{len(db_records)} rows...")

    logger.info("Database OHLC synchronization complete!")

def print_summary(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM symbol_metadata;")
        sym_count = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM stock_ohlc_daily;")
        ohlc_count, min_date, max_date = cur.fetchone()

        cur.execute("""
            SELECT theme, COUNT(*) 
            FROM symbol_metadata 
            GROUP BY theme 
            ORDER BY COUNT(*) DESC;
        """)
        theme_counts = cur.fetchall()

        cur.execute("""
            SELECT symbol, name, latest_date, close, change_pct, rsi_14, sma_50, sma_200 
            FROM v_stock_latest_snapshot 
            WHERE symbol IN ('SPY', 'QQQ', 'IWM', 'DIA', 'AAPL', 'MSFT', 'NVDA', 'TSLA', 'TQQQ', 'SOXL', 'TLT')
            ORDER BY symbol;
        """)
        sample_snapshots = cur.fetchall()

    print("\n" + "="*85)
    print("SUPABASE OHLC & TECHNICAL ANALYSIS INGESTION SUMMARY (EXPANDED UNIVERSE)")
    print("="*85)
    print(f"Total Symbols in Metadata: {sym_count}")
    print(f"Total Daily OHLC Rows:    {ohlc_count}")
    print(f"Date Range Stored:        {min_date} -> {max_date}")
    print("\nAsset Breakdown by Theme:")
    for theme, cnt in theme_counts:
        print(f" - {theme:<30}: {cnt} symbols")

    print("\nSample Snapshot (Top Benchmarks & Mega-Caps):")
    print(f"{'Symbol':<7} {'Latest Date':<12} {'Close':<9} {'Day %':<8} {'RSI(14)':<9} {'SMA(50)':<9} {'SMA(200)':<9} {'Name'}")
    print("-" * 85)
    for row in sample_snapshots:
        sym, name, dt, close, chg, rsi, s50, s200 = row
        print(f"{sym:<7} {str(dt):<12} ${float(close):<8.2f} {f'{float(chg):+.2f}%':<8} {f'{float(rsi):.1f}' if rsi else 'N/A':<9} {f'${float(s50):.2f}' if s50 else 'N/A':<9} {f'${float(s200):.2f}' if s200 else 'N/A':<9} {name[:25]}")
    print("="*85 + "\n")

def main():
    logger.info("Starting Full Supabase OHLC & Technical Analysis Ingestion...")
    symbols = load_symbols()
    conn = get_db_connection()
    
    tc = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=ALPACA_PAPER)
    data_client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
    
    sync_symbol_metadata(symbols, tc, conn)
    sync_all_stock_bars(symbols, data_client, conn, days_back=400, keep_days=150)
    print_summary(conn)
    conn.close()

if __name__ == "__main__":
    main()
