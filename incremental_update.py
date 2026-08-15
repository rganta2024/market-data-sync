import os
import sys
import logging
from datetime import datetime, timedelta, timezone
from typing import List

import pandas as pd
import numpy as np
import psycopg2
from psycopg2.extras import execute_values
import ta

# Fix Windows SSL Certificates
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("Incremental_Sync")

SYMBOLS_FILE = os.path.join(os.path.dirname(__file__), "Fidelity_Symbols.txt")
HEDGE_DATABASE_URL = os.getenv("HEDGE_DATABASE_URL")

def get_db_connection():
    if not HEDGE_DATABASE_URL:
        raise ValueError("HEDGE_DATABASE_URL environment variable is missing.")
    return psycopg2.connect(HEDGE_DATABASE_URL)

def load_symbols() -> List[str]:
    with open(SYMBOLS_FILE, "r", encoding="utf-8") as f:
        symbols = [line.strip().upper() for line in f if line.strip() and not line.startswith("#")]
    return sorted(list(set(symbols)))

def clean_val(v):
    if v is None or pd.isna(v) or np.isnan(v) or np.isinf(v):
        return None
    return v

def run_incremental_sync(lookback_days: int = 400, update_recent_bars: int = 5):
    """
    Pulls recent bars to compute rolling technical indicators accurately,
    then updates the most recent `update_recent_bars` (default 5) in Supabase.
    """
    logger.info("Starting Daily Incremental OHLC & Indicator Sync...")
    symbols = load_symbols()
    conn = get_db_connection()
    data_client = StockHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
    
    start_dt = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    batch_size = 40
    all_ohlc_records = []
    
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
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
                
                # Moving Averages & Price Changes
                group["prev_close"] = group["close"].shift(1)
                group["change_dollar"] = group["close"] - group["prev_close"]
                group["change_pct"] = (group["change_dollar"] / group["prev_close"]) * 100.0

                group["sma_20"] = ta.trend.sma_indicator(group["close"], window=20)
                group["sma_50"] = ta.trend.sma_indicator(group["close"], window=50)
                group["sma_200"] = ta.trend.sma_indicator(group["close"], window=200)
                group["ema_9"] = ta.trend.ema_indicator(group["close"], window=9)
                group["ema_20"] = ta.trend.ema_indicator(group["close"], window=20)
                group["ema_50"] = ta.trend.ema_indicator(group["close"], window=50)
                group["ema_200"] = ta.trend.ema_indicator(group["close"], window=200)

                group["rsi_14"] = ta.momentum.rsi(group["close"], window=14)
                macd = ta.trend.MACD(group["close"])
                group["macd"] = macd.macd()
                group["macd_signal"] = macd.macd_signal()
                group["macd_hist"] = macd.macd_diff()

                stoch = ta.momentum.StochasticOscillator(group["high"], group["low"], group["close"], window=14, smooth_window=3)
                group["stoch_k"] = stoch.stoch()
                group["stoch_d"] = stoch.stoch_signal()
                group["adx_14"] = ta.trend.adx(group["high"], group["low"], group["close"], window=14)

                bb = ta.volatility.BollingerBands(group["close"], window=20, window_dev=2)
                group["bb_upper"] = bb.bollinger_hband()
                group["bb_middle"] = bb.bollinger_mavg()
                group["bb_lower"] = bb.bollinger_lband()
                group["bb_width"] = bb.bollinger_wband()
                group["atr_14"] = ta.volatility.average_true_range(group["high"], group["low"], group["close"], window=14)

                group["vol_sma_20"] = ta.trend.sma_indicator(group["volume"], window=20)
                group["vol_ratio"] = np.where(group["vol_sma_20"] > 0, group["volume"] / group["vol_sma_20"], 1.0)
                group["obv"] = ta.volume.on_balance_volume(group["close"], group["volume"])

                group["high_52w"] = group["high"].rolling(window=252, min_periods=20).max()
                group["low_52w"] = group["low"].rolling(window=252, min_periods=20).min()
                group["pct_from_52w_high"] = np.where(group["high_52w"] > 0, ((group["close"] - group["high_52w"]) / group["high_52w"]) * 100.0, 0.0)
                group["pct_from_52w_low"] = np.where(group["low_52w"] > 0, ((group["close"] - group["low_52w"]) / group["low_52w"]) * 100.0, 0.0)

                # Pick recent rows for incremental upsert
                recent_df = group.tail(update_recent_bars)
                for _, row in recent_df.iterrows():
                    all_ohlc_records.append((
                        sym,
                        row["timestamp"].date(),
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
                        datetime.now(timezone.utc)
                    ))
        except Exception as e:
            logger.error(f"Error updating batch {batch}: {e}")

    if all_ohlc_records:
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
        with conn.cursor() as cur:
            execute_values(cur, upsert_ohlc_sql, all_ohlc_records)
            cur.execute("UPDATE symbol_metadata SET last_synced_at = NOW();")
            conn.commit()
            
        logger.info(f"Incremental sync finished successfully! Upserted {len(all_ohlc_records)} records.")
    
    conn.close()

if __name__ == "__main__":
    run_incremental_sync()
