import os
import sys
import re
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

import pandas as pd
import numpy as np
import psycopg2
from psycopg2.extras import execute_values

# Fix Windows SSL Certificates if needed
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

sys.path.append(r"C:\Users\ganta\OneDrive\ClaudeCode\Fidelity\Fidelity_reoccuring_orders\leveraged_tranche_engine")
try:
    from config import ALPACA_API_KEY, ALPACA_SECRET_KEY
except ImportError:
    ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
    ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")

from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionChainRequest, OptionBarsRequest
from alpaca.data.timeframe import TimeFrame

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("Options_Pipeline")

HEDGE_DATABASE_URL = os.getenv("HEDGE_DATABASE_URL")

# Default popular underlyings for options tracking
TARGET_UNDERLYINGS = ["QQQ", "SPY", "SPXL", "TQQQ", "IWM", "DIA", "SOXL", "NVDA", "TSLA", "AAPL"]

def get_db_connection():
    if not HEDGE_DATABASE_URL:
        raise ValueError("HEDGE_DATABASE_URL environment variable is missing.")
    return psycopg2.connect(HEDGE_DATABASE_URL)

def parse_occ_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    m = re.match(r"^([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d{8})$", symbol)
    if not m:
        return None
    root, yy, mm, dd, opt_type, strike_raw = m.groups()
    exp_date = datetime.strptime(f"20{yy}-{mm}-{dd}", "%Y-%m-%d").date()
    strike = float(strike_raw) / 1000.0
    return {
        "underlying": root,
        "expiration_date": exp_date,
        "contract_type": "CALL" if opt_type == "C" else "PUT",
        "strike_price": strike
    }

def clean_val(v):
    if v is None or pd.isna(v) or np.isnan(v) or np.isinf(v):
        return None
    return v

def sync_options_for_underlyings(underlyings: List[str] = TARGET_UNDERLYINGS, days_back: int = 60, max_contracts_per_underlying: int = 150):
    conn = get_db_connection()
    opt_client = OptionHistoricalDataClient(ALPACA_API_KEY, ALPACA_SECRET_KEY)
    
    logger.info(f"Starting Options OHLC & Greeks sync for underlyings: {underlyings}")
    
    total_contracts_metadata = []
    all_option_ohlc_records = []
    
    # Also fetch latest underlying stock prices from Supabase for moneyness calculation
    underlying_prices = {}
    with conn.cursor() as cur:
        cur.execute("SELECT symbol, close FROM v_stock_latest_snapshot WHERE symbol = ANY(%s);", (underlyings,))
        for sym, cl in cur.fetchall():
            underlying_prices[sym] = float(cl) if cl else None

    for u in underlyings:
        logger.info(f"Fetching Option Chain for {u}...")
        try:
            chain = opt_client.get_option_chain(OptionChainRequest(underlying_symbol=u))
            if not chain:
                logger.warning(f"No option chain returned for {u}")
                continue
                
            u_price = underlying_prices.get(u)
            
            # Select liquid/active contracts
            # Filter: contracts expiring within 180 days, with recent trades/quotes
            valid_contracts = []
            today_date = datetime.now(timezone.utc).date()
            
            for sym, snap in chain.items():
                parsed = parse_occ_symbol(sym)
                if not parsed:
                    continue
                    
                dte = (parsed["expiration_date"] - today_date).days
                if dte < 0 or dte > 180:
                    continue
                
                # Check if it has a recent trade or active bid/ask quote
                has_trade = bool(snap.latest_trade and snap.latest_trade.price > 0.01)
                has_quote = bool(snap.latest_quote and (snap.latest_quote.bid_price > 0.05 or snap.latest_quote.ask_price > 0.05))
                
                # Prefer contracts within reasonable distance to strike
                strike = parsed["strike_price"]
                near_money = True
                if u_price:
                    pct_diff = abs(strike - u_price) / u_price
                    near_money = pct_diff <= 0.35  # within 35% of underlying price
                
                if (has_trade or has_quote) and near_money:
                    valid_contracts.append((sym, snap, parsed, dte))

            # Limit to most active contracts to keep requests efficient
            valid_contracts = valid_contracts[:max_contracts_per_underlying]
            logger.info(f"{u}: Selected {len(valid_contracts)} active contracts for OHLC bar pulling.")
            
            if not valid_contracts:
                continue

            # 1. Prepare Metadata records
            for sym, snap, parsed, dte in valid_contracts:
                total_contracts_metadata.append((
                    sym,
                    parsed["underlying"],
                    parsed["contract_type"],
                    parsed["strike_price"],
                    parsed["expiration_date"],
                    "AMERICAN",
                    datetime.now(timezone.utc),
                    datetime.now(timezone.utc)
                ))

            # 2. Fetch Historical Option Bars in batches
            contract_symbols = [v[0] for v in valid_contracts]
            snap_map = {v[0]: (v[1], v[2], v[3]) for v in valid_contracts}
            
            batch_size = 30
            for i in range(0, len(contract_symbols), batch_size):
                batch_syms = contract_symbols[i : i + batch_size]
                try:
                    bars_req = OptionBarsRequest(
                        symbol_or_symbols=batch_syms,
                        timeframe=TimeFrame.Day,
                        start=datetime.now(timezone.utc) - timedelta(days=days_back)
                    )
                    bars = opt_client.get_option_bars(bars_req)
                    if not bars.data:
                        continue
                    
                    b_df = bars.df.reset_index()
                    if b_df.empty:
                        continue

                    for _, row in b_df.iterrows():
                        opt_sym = row["symbol"]
                        bar_date = row["timestamp"].date()
                        snap, parsed, dte = snap_map[opt_sym]
                        
                        bid = float(snap.latest_quote.bid_price) if snap.latest_quote and snap.latest_quote.bid_price is not None else None
                        ask = float(snap.latest_quote.ask_price) if snap.latest_quote and snap.latest_quote.ask_price is not None else None
                        mid = (bid + ask) / 2.0 if bid is not None and ask is not None else None
                        
                        iv = float(snap.implied_volatility) if snap.implied_volatility is not None else None
                        delta = float(snap.greeks.delta) if snap.greeks and snap.greeks.delta is not None else None
                        gamma = float(snap.greeks.gamma) if snap.greeks and snap.greeks.gamma is not None else None
                        theta = float(snap.greeks.theta) if snap.greeks and snap.greeks.theta is not None else None
                        vega = float(snap.greeks.vega) if snap.greeks and snap.greeks.vega is not None else None
                        rho = float(snap.greeks.rho) if snap.greeks and snap.greeks.rho is not None else None
                        
                        moneyness = None
                        if u_price and parsed["strike_price"]:
                            moneyness = ((parsed["strike_price"] - u_price) / u_price) * 100.0

                        all_option_ohlc_records.append((
                            opt_sym,
                            bar_date,
                            parsed["underlying"],
                            parsed["contract_type"],
                            parsed["strike_price"],
                            parsed["expiration_date"],
                            dte,
                            float(row["open"]),
                            float(row["high"]),
                            float(row["low"]),
                            float(row["close"]),
                            int(row["volume"]),
                            int(row["trade_count"]) if pd.notna(row.get("trade_count")) else None,
                            float(row["vwap"]) if pd.notna(row.get("vwap")) else None,
                            clean_val(bid),
                            clean_val(ask),
                            clean_val(mid),
                            clean_val(iv),
                            clean_val(delta),
                            clean_val(gamma),
                            clean_val(theta),
                            clean_val(vega),
                            clean_val(rho),
                            clean_val(u_price),
                            clean_val(moneyness),
                            datetime.now(timezone.utc)
                        ))
                except Exception as b_err:
                    logger.error(f"Error fetching bars for batch {batch_syms[:3]}: {b_err}")

        except Exception as e:
            logger.error(f"Error processing options for {u}: {e}")

    # 3. Bulk Upsert into option_contracts_metadata
    if total_contracts_metadata:
        logger.info(f"Upserting {len(total_contracts_metadata)} contracts into option_contracts_metadata...")
        upsert_meta_sql = """
        INSERT INTO option_contracts_metadata (
            option_symbol, underlying_symbol, contract_type, strike_price, expiration_date, style, created_at, updated_at
        ) VALUES %s
        ON CONFLICT (option_symbol) DO UPDATE SET
            underlying_symbol = EXCLUDED.underlying_symbol,
            contract_type = EXCLUDED.contract_type,
            strike_price = EXCLUDED.strike_price,
            expiration_date = EXCLUDED.expiration_date,
            style = EXCLUDED.style,
            updated_at = NOW();
        """
        with conn.cursor() as cur:
            execute_values(cur, upsert_meta_sql, total_contracts_metadata)
            conn.commit()

    # 4. Bulk Upsert into option_ohlc_daily
    if all_option_ohlc_records:
        logger.info(f"Upserting {len(all_option_ohlc_records)} option OHLC records into option_ohlc_daily...")
        upsert_ohlc_sql = """
        INSERT INTO option_ohlc_daily (
            option_symbol, date, underlying_symbol, contract_type, strike_price, expiration_date, days_to_exp,
            open, high, low, close, volume, trade_count, vwap,
            bid, ask, mid_price, implied_volatility, delta, gamma, theta, vega, rho,
            underlying_close, moneyness_pct, updated_at
        ) VALUES %s
        ON CONFLICT (option_symbol, date) DO UPDATE SET
            underlying_symbol = EXCLUDED.underlying_symbol,
            contract_type = EXCLUDED.contract_type,
            strike_price = EXCLUDED.strike_price,
            expiration_date = EXCLUDED.expiration_date,
            days_to_exp = EXCLUDED.days_to_exp,
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            trade_count = EXCLUDED.trade_count,
            vwap = EXCLUDED.vwap,
            bid = EXCLUDED.bid,
            ask = EXCLUDED.ask,
            mid_price = EXCLUDED.mid_price,
            implied_volatility = EXCLUDED.implied_volatility,
            delta = EXCLUDED.delta,
            gamma = EXCLUDED.gamma,
            theta = EXCLUDED.theta,
            vega = EXCLUDED.vega,
            rho = EXCLUDED.rho,
            underlying_close = EXCLUDED.underlying_close,
            moneyness_pct = EXCLUDED.moneyness_pct,
            updated_at = NOW();
        """
        with conn.cursor() as cur:
            chunk_size = 2000
            for j in range(0, len(all_option_ohlc_records), chunk_size):
                chunk = all_option_ohlc_records[j : j + chunk_size]
                execute_values(cur, upsert_ohlc_sql, chunk)
                conn.commit()

    # 5. Summary
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM option_contracts_metadata;")
        cnt_meta = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*), MIN(date), MAX(date) FROM option_ohlc_daily;")
        cnt_ohlc, min_d, max_d = cur.fetchone()
        
        cur.execute("""
            SELECT underlying_symbol, COUNT(DISTINCT option_symbol), COUNT(*) 
            FROM option_ohlc_daily 
            GROUP BY underlying_symbol 
            ORDER BY COUNT(*) DESC;
        """)
        underlying_counts = cur.fetchall()

    print("\n" + "="*85)
    print("SUPABASE OPTIONS OHLC & GREEKS INGESTION SUMMARY")
    print("="*85)
    print(f"Total Option Contracts in Metadata: {cnt_meta}")
    print(f"Total Option Daily OHLC Rows:       {cnt_ohlc}")
    print(f"Date Range:                         {min_d} -> {max_d}")
    print("\nOptions Coverage by Underlying:")
    for u, u_contracts, u_rows in underlying_counts:
        print(f" - {u:<7}: {u_contracts} contracts | {u_rows} daily OHLC rows")

    print("="*85 + "\n")
    conn.close()

if __name__ == "__main__":
    sync_options_for_underlyings()
