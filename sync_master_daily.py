import os
import sys
import logging
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("Master_Sync")

from incremental_update import run_incremental_sync as sync_stocks
from sync_options_data import sync_options_for_underlyings as sync_options

def main():
    start_time = datetime.now(timezone.utc)
    logger.info("=================================================================")
    logger.info("STARTING MASTER DAILY MARKET DATA SYNC (STOCKS + OPTIONS)")
    logger.info("=================================================================")
    
    # 1. Sync Stock OHLC & Technical Analysis Indicators (223 symbols)
    try:
        logger.info("Step 1/2: Syncing Stock OHLC & Technical Indicators...")
        sync_stocks(lookback_days=400, update_recent_bars=5)
    except Exception as e:
        logger.error(f"Stock sync failed: {e}")

    # 2. Sync Options OHLC, Greeks & Implied Volatility
    try:
        logger.info("Step 2/2: Syncing Options OHLC & Greeks for Core Underlyings...")
        sync_options(
            underlyings=["QQQ", "SPY", "SPXL", "TQQQ", "IWM", "DIA", "SOXL", "NVDA", "TSLA", "AAPL"],
            days_back=30,
            max_contracts_per_underlying=100
        )
    except Exception as e:
        logger.error(f"Options sync failed: {e}")

    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    logger.info("=================================================================")
    logger.info(f"MASTER DAILY SYNC COMPLETED IN {elapsed:.2f} SECONDS")
    logger.info("=================================================================")

if __name__ == "__main__":
    main()
