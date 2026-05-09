#!/usr/bin/env python3
"""
backfill_ppo.py — Historical PPO Experience Backfill for New Tokens
===================================================================
Downloads 30 days of 5m + 1h klines from BingX, runs them through the
QuantumEngine feature pipeline, and accumulates PPO experiences in the
ppo_memory table so new tokens start with a training base comparable
to existing ones (~500+ experiences).

Usage:
    cd /srv/profitlab_quantum
    python3 /srv/backfill_ppo.py [--days 30] [--tokens BCH-USDT,LINK-USDT,...]

The script does NOT open positions; it only populates the PPO memory.
"""

import sys, os, time, argparse, logging, asyncio
import requests
import numpy as np
import pandas as pd

# Ensure project root is in path
PROJECT_ROOT = "/srv/profitlab_quantum"
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from app.engine import QuantumEngine
from app.config import DATABASE_URL, INITIAL_CAPITAL, TOKENS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [BACKFILL] %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("Backfill")

# ─── BingX Historical Klines ─────────────────────────────────────
BINGX_BASE = "https://open-api.bingx.com"
KLINE_URL = f"{BINGX_BASE}/openApi/swap/v3/quote/klines"
MAX_PER_REQUEST = 1440          # BingX max per call
RATE_LIMIT_SLEEP = 0.35         # seconds between API calls


def fetch_klines_chunk(symbol: str, interval: str, start_ms: int, end_ms: int) -> list[dict]:
    """Fetch up to 1440 klines from BingX between start_ms and end_ms."""
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": MAX_PER_REQUEST,
    }
    try:
        resp = requests.get(KLINE_URL, params=params, timeout=30)
        data = resp.json()
        if data.get("code") != 0:
            logger.warning(f"BingX error for {symbol} ({interval}): {data}")
            return []
        return data.get("data", [])
    except Exception as e:
        logger.error(f"HTTP error fetching klines: {e}")
        return []


def fetch_all_klines(symbol: str, interval: str, days: int) -> pd.DataFrame:
    """
    Download `days` worth of historical klines by paginating with startTime/endTime.
    Returns a DataFrame sorted ascending by time.
    """
    interval_ms = {"5m": 5 * 60_000, "1h": 60 * 60_000}[interval]
    candles_per_day = (24 * 60 * 60_000) // interval_ms
    total_candles_needed = candles_per_day * days
    
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (days * 24 * 60 * 60 * 1000)
    
    all_klines = []
    cursor = start_ms
    
    while cursor < now_ms and len(all_klines) < total_candles_needed + 500:
        chunk_end = min(cursor + MAX_PER_REQUEST * interval_ms, now_ms)
        klines = fetch_klines_chunk(symbol, interval, cursor, chunk_end)
        
        if not klines:
            logger.warning(f"  No klines returned for {symbol} at cursor {cursor}, advancing...")
            cursor = chunk_end
            time.sleep(RATE_LIMIT_SLEEP)
            continue
        
        all_klines.extend(klines)
        
        # BingX returns reverse-chronological; find the oldest timestamp
        timestamps = [int(k.get("time", 0)) for k in klines]
        oldest = min(timestamps)
        newest = max(timestamps)
        
        # Advance cursor past the newest candle we got
        cursor = newest + interval_ms
        
        logger.info(
            f"  {symbol} {interval}: fetched {len(klines)} candles "
            f"({pd.Timestamp(oldest, unit='ms', tz='UTC').strftime('%m/%d %H:%M')} → "
            f"{pd.Timestamp(newest, unit='ms', tz='UTC').strftime('%m/%d %H:%M')}), "
            f"total={len(all_klines)}"
        )
        time.sleep(RATE_LIMIT_SLEEP)
    
    if not all_klines:
        return pd.DataFrame()
    
    # Build DataFrame and deduplicate
    df = pd.DataFrame(all_klines)
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    
    if "time" in df.columns:
        df["timestamp"] = pd.to_numeric(df["time"], errors="coerce")
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.set_index("datetime")
    
    df = df.dropna().drop_duplicates(subset=["time"]).sort_values("time")
    logger.info(f"  {symbol} {interval}: total unique candles = {len(df)}")
    return df


# ─── Backfill Engine ─────────────────────────────────────────────

def run_backfill_for_token(symbol: str, days: int):
    """
    Download historical data and simulate PPO step-by-step for one token.
    
    We slide a window of 220 5m candles (same as live bot) across historical data
    and call engine.step() for each new candle. The engine computes features,
    PPO decides action, reward is calculated from price change, and the
    experience is stored via agent.remember() → ppo_memory table.
    """
    logger.info(f"{'='*60}")
    logger.info(f"BACKFILL START: {symbol} ({days} days)")
    logger.info(f"{'='*60}")
    
    # 1. Download klines
    logger.info(f"Downloading 5m klines...")
    df_5m = fetch_all_klines(symbol, "5m", days)
    if df_5m.empty or len(df_5m) < 250:
        logger.error(f"Not enough 5m data for {symbol}: {len(df_5m)} candles")
        return 0
    
    logger.info(f"Downloading 1h klines...")
    df_1h = fetch_all_klines(symbol, "1h", days)
    
    # 2. Create engine (separate from live bot — its own agent weights)
    capital_per_token = INITIAL_CAPITAL / max(len(TOKENS), 1)
    engine = QuantumEngine(initial_capital=capital_per_token, symbol=symbol)
    
    # 3. Slide through history
    WINDOW_5M = 220     # Same as live bot
    WINDOW_1H = 300     # Same as live bot (used in main.py)
    STEP_EVERY = 1      # Every 5m candle
    
    total_5m = len(df_5m)
    experiences_before = _count_experiences(symbol)
    logger.info(f"Experiences before backfill: {experiences_before}")
    logger.info(f"Sliding through {total_5m} candles (window={WINDOW_5M})...")
    
    steps_done = 0
    for i in range(WINDOW_5M, total_5m, STEP_EVERY):
        window = df_5m.iloc[i - WINDOW_5M : i]
        
        # Find matching 1h window (candles up to current 5m timestamp)
        htf_window = None
        if df_1h is not None and not df_1h.empty:
            current_ts = int(window["time"].iloc[-1])
            htf_mask = df_1h["time"].astype(int) <= current_ts
            htf_slice = df_1h[htf_mask].tail(WINDOW_1H)
            if len(htf_slice) >= 13:
                htf_window = htf_slice
        
        try:
            engine.step(
                market_data=window,
                htf_data=htf_window,
                symbol=symbol,
                microstructure=None,
            )
            steps_done += 1
        except Exception as e:
            if steps_done == 0:
                logger.error(f"First step failed for {symbol}: {e}")
                import traceback
                traceback.print_exc()
            # Log sparingly after first
            if steps_done % 500 == 0:
                logger.warning(f"Step error at i={i}: {e}")
            continue
        
        # Progress log every 500 steps
        if steps_done % 500 == 0:
            pct = (i / total_5m) * 100
            logger.info(f"  {symbol}: step {steps_done} ({pct:.1f}%)")
    
    experiences_after = _count_experiences(symbol)
    new_experiences = experiences_after - experiences_before
    
    logger.info(f"BACKFILL DONE: {symbol}")
    logger.info(f"  Steps executed: {steps_done}")
    logger.info(f"  New PPO experiences: {new_experiences}")
    logger.info(f"  Total PPO experiences: {experiences_after}")
    
    return new_experiences


def _count_experiences(symbol: str) -> int:
    """Count PPO experiences in DB for a symbol."""
    try:
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM ppo_memory WHERE symbol = %s", (symbol,))
        count = cur.fetchone()[0]
        conn.close()
        return count
    except Exception:
        return 0


# ─── Main ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Backfill PPO experiences for new tokens")
    parser.add_argument("--days", type=int, default=30, help="Days of history to backfill (default: 30)")
    parser.add_argument(
        "--tokens",
        type=str,
        default="BCH-USDT,LINK-USDT,HYPE-USDT,XLM-USDT,LTC-USDT",
        help="Comma-separated list of tokens to backfill",
    )
    args = parser.parse_args()
    
    tokens = [t.strip() for t in args.tokens.split(",") if t.strip()]
    
    logger.info(f"Backfill PPO Experiences")
    logger.info(f"  Tokens: {tokens}")
    logger.info(f"  Days:   {args.days}")
    logger.info(f"  DB:     {DATABASE_URL[:40]}...")
    
    results = {}
    for token in tokens:
        try:
            new_exp = run_backfill_for_token(token, args.days)
            results[token] = new_exp
        except Exception as e:
            logger.error(f"FAILED backfill for {token}: {e}")
            import traceback
            traceback.print_exc()
            results[token] = -1
    
    # Summary
    logger.info(f"\n{'='*60}")
    logger.info(f"BACKFILL SUMMARY")
    logger.info(f"{'='*60}")
    for token, count in results.items():
        status = f"{count:,} new experiences" if count >= 0 else "FAILED"
        logger.info(f"  {token:20s} → {status}")
    
    total = sum(v for v in results.values() if v > 0)
    logger.info(f"  {'TOTAL':20s} → {total:,} new experiences")


if __name__ == "__main__":
    main()
