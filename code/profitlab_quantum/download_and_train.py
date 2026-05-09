#!/usr/bin/env python3
"""
Download historical OHLCV via CCXT (Binance) and pre-train PPO offline.
Gives the Quantum bot a "head start" instead of waiting 9+ days.

Usage:
    /srv/profitlab_quantum/venv/bin/python download_and_train.py
"""
import os, sys, time, logging

os.chdir("/srv/profitlab_quantum")
sys.path.insert(0, "/srv/profitlab_quantum")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dl_train")

import ccxt
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone, timedelta

# ── Config ─────────────────────────────────────────────────────
SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "XRP/USDT", "BNB/USDT", "SOL/USDT",
    "ADA/USDT", "DOGE/USDT", "AVAX/USDT", "TRX/USDT", "LINK/USDT",
    "DOT/USDT", "TON/USDT", "SUI/USDT", "SHIB/USDT", "XLM/USDT",
    "HBAR/USDT", "BCH/USDT", "LTC/USDT", "UNI/USDT", "NEAR/USDT",
]

TIMEFRAME = "5m"
MONTHS_BACK = 3          # 3 months → ~26K candles/token
DATA_DIR = Path("/srv/profitlab_quantum/data/historical")
BATCH_SIZE = 1000        # Binance max per request


def download_ohlcv(symbol: str) -> pd.DataFrame:
    """Download historical OHLCV from Binance via CCXT."""
    exchange = ccxt.bingx({"enableRateLimit": True})

    bot_symbol = symbol.replace("/", "-")
    parquet_path = DATA_DIR / f"{bot_symbol.replace('-', '_')}_5m_6m.parquet"

    if parquet_path.exists():
        age_h = (time.time() - parquet_path.stat().st_mtime) / 3600
        if age_h < 24:
            logger.info(f"  ✓ {symbol}: cached ({age_h:.0f}h old)")
            return pd.read_parquet(parquet_path)

    since = int((datetime.now(timezone.utc) - timedelta(days=MONTHS_BACK * 30)).timestamp() * 1000)
    all_candles = []

    logger.info(f"  ↓ {symbol}: downloading {MONTHS_BACK}mo of {TIMEFRAME}...")

    while True:
        try:
            candles = exchange.fetch_ohlcv(symbol, TIMEFRAME, since=since, limit=BATCH_SIZE)
        except Exception as e:
            logger.warning(f"  ⚠ {symbol}: {e}, retry 5s...")
            time.sleep(5)
            if "does not have market symbol" in str(e):
                logger.error(f"  ✗ {symbol}: Not on BingX, skipping")
                return pd.DataFrame()
            continue

        if not candles:
            break

        all_candles.extend(candles)
        since = candles[-1][0] + 1

        if len(candles) < BATCH_SIZE:
            break

        time.sleep(exchange.rateLimit / 1000)

    if not all_candles:
        logger.error(f"  ✗ {symbol}: No data")
        return pd.DataFrame()

    df = pd.DataFrame(all_candles, columns=["time", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(parquet_path, index=False)

    logger.info(f"  ✓ {symbol}: {len(df)} candles → {parquet_path.name}")
    return df


def train_all():
    """Run offline_train per symbol."""
    from offline_train import train_symbol

    results = {}
    for sym_ccxt in SYMBOLS:
        bot_sym = sym_ccxt.replace("/", "-")
        try:
            t0 = time.time()
            ok = train_symbol(bot_sym)
            dt = time.time() - t0
            results[bot_sym] = f"OK ({dt:.1f}s)" if ok else "SKIPPED"
        except Exception as e:
            logger.error(f"FAILED {bot_sym}: {e}")
            import traceback; traceback.print_exc()
            results[bot_sym] = f"FAILED: {e}"

    return results


def main():
    import torch
    gpu = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"

    logger.info("=" * 60)
    logger.info("CCXT DOWNLOAD + OFFLINE PPO TRAINING")
    logger.info(f"GPU: {gpu}")
    logger.info(f"Tokens: {len(SYMBOLS)} | TF: {TIMEFRAME} | History: {MONTHS_BACK}mo")
    logger.info("=" * 60)

    start = time.time()

    # Phase 1: Download
    logger.info("\n📥 PHASE 1: Downloading historical data...")
    for sym in SYMBOLS:
        try:
            download_ohlcv(sym)
        except Exception as e:
            logger.error(f"Download failed {sym}: {e}")

    n_files = len(list(DATA_DIR.glob("*.parquet")))
    logger.info(f"📦 {n_files} parquet files ready\n")

    # Phase 2: Train
    logger.info("🧠 PHASE 2: Offline PPO training...")
    results = train_all()

    elapsed = time.time() - start
    logger.info(f"\n{'=' * 60}")
    logger.info(f"COMPLETE — {elapsed / 60:.1f} min")
    logger.info(f"{'=' * 60}")
    for sym, status in results.items():
        icon = "✅" if "OK" in status else "⏭️" if "SKIP" in status else "❌"
        logger.info(f"  {icon} {sym}: {status}")


if __name__ == "__main__":
    main()
