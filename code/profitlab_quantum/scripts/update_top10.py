#!/usr/bin/env python3
"""
Daily Top-10 Market Cap Updater for QuantumMBO — v2
====================================================
Runs at 04:00 UTC each day.
- Fetches top 30 cryptos by market cap (CoinGecko primary, CoinMarketCap fallback)
- Filters: stablecoins, exchange tokens, wrapped tokens, non-crypto artifacts
- Validates each symbol exists on BingX perpetual swaps
- Top 10 → trade=true, 11-15 → trade=false (train only)
- Updates /srv/profitlab_quantum/active_tokens.json
- Writes reload flag for bot

Cron:  0 4 * * * /srv/profitlab_quantum/venv/bin/python /srv/profitlab_quantum/scripts/update_top10.py >> /var/log/quantum_top10.log 2>&1
"""

import sys
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("top10")

if __name__ == "__main__":
    logger.info("TOP10 updater is disabled manually for Smallcap Animal Protocol.")
    sys.exit(0)

import json
import os
import time
import re
from datetime import datetime, timezone

import requests

# ── Configuration ──────────────────────────────────────────────
ACTIVE_TOKENS_FILE = "/srv/profitlab_quantum/active_tokens.json"
BINGX_CONTRACTS_URL = "https://open-api.bingx.com/openApi/swap/v2/quote/contracts"
COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/markets"
LOG_PREFIX = "[TOP10-UPDATE]"

TOP_N_TRADE = 10   # Top 10 = trade
TOP_N_TOTAL = 15   # Top 15 = trade + train

# ── Exclusion Lists ───────────────────────────────────────────
# Stablecoins (pegged to fiat — no point trading)
STABLECOINS = {
    "USDT", "USDC", "DAI", "FDUSD", "USDD", "TUSD", "BUSD",
    "USDP", "PYUSD", "RLUSD", "USD1", "USDG", "USDE", "EURC",
    "USDS", "FRAX", "LUSD", "GUSD", "SUSD", "CRVUSD", "GHO",
    "ALUSD", "MIM", "DOLA", "USDB", "USDX", "UST", "USTC",
    "CUSD", "OUSD", "HAY",
}

# Exchange tokens (often manipulated, low float, not real market)
EXCHANGE_TOKENS = {
    "LEO", "WBT", "OKB", "GT", "CRO", "KCS", "HT", "FTT",
    "BGB", "MX",
}

# Wrapped / bridged tokens (just follow original, no alpha)
WRAPPED_TOKENS = {
    "WBTC", "WETH", "WBNB", "STETH", "RETH", "CBETH", "WSTETH",
    "TBTC", "RENBTC", "HBTC", "SBTC",
}

# CoinGecko IDs known to be non-crypto artifacts or securitized products
BLOCKLIST_COINGECKO_IDS = {
    "figure-heloc",         # Securitized HELOC, not a crypto
    "canton-network",       # Enterprise DLT, no public trading
    "internet-computer",    # Controversial mcap calculations
    "usd1-wlfi",            # Stablecoin variant
}

# Default leverage per token (conservative)
DEFAULT_LEVERAGE = 1.0
LEVERAGE_OVERRIDES = {
    "SOL-USDT": 3.0,
    "ADA-USDT": 3.0,
}


def log(msg: str):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"{ts} {LOG_PREFIX} {msg}", flush=True)


# ── BingX Validation ──────────────────────────────────────────

def get_bingx_symbols() -> set:
    """Fetch all available perpetual swap symbols from BingX."""
    try:
        resp = requests.get(BINGX_CONTRACTS_URL, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        contracts = data.get("data", [])
        symbols = {c["symbol"] for c in contracts if c.get("status") == 1}
        log(f"BingX has {len(symbols)} perpetual symbols")
        return symbols
    except Exception as e:
        log(f"WARNING: BingX API failed: {e}")
        return set()


# ── Market Cap Data Sources ───────────────────────────────────

def get_top_cryptos_coingecko(limit: int = 30) -> list[dict]:
    """Fetch top cryptos by market cap from CoinGecko (free tier)."""
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": limit,
        "page": 1,
        "sparkline": "false",
    }
    try:
        resp = requests.get(COINGECKO_URL, params=params, timeout=20)
        if resp.status_code == 429:
            log("CoinGecko rate-limited (429)")
            return []
        resp.raise_for_status()
        raw = resp.json()
        if not isinstance(raw, list):
            log(f"CoinGecko unexpected response: {type(raw)}")
            return []
        # Normalize to common format
        result = []
        for c in raw:
            result.append({
                "symbol": c.get("symbol", "").upper(),
                "name": c.get("name", ""),
                "market_cap": c.get("market_cap") or 0,
                "cg_id": c.get("id", ""),
            })
        return result
    except Exception as e:
        log(f"CoinGecko API error: {e}")
        return []


def get_top_cryptos_cmc(limit: int = 30) -> list[dict]:
    """Fallback: Fetch from CoinMarketCap (no API key, scrape-style)."""
    # CoinMarketCap public listings endpoint (no key needed for basic)
    url = "https://api.coinmarketcap.com/data-api/v3/cryptocurrency/listing"
    params = {"start": 1, "limit": limit, "sortBy": "market_cap", "sortType": "desc",
              "convert": "USD", "cryptoType": "all", "audited": "false"}
    try:
        resp = requests.get(url, params=params, timeout=20,
                           headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", {}).get("cryptoCurrencyList", [])
        result = []
        for c in items:
            sym = c.get("symbol", "").upper()
            name = c.get("name", "")
            quotes = c.get("quotes", [{}])
            mcap = 0
            for q in quotes:
                if q.get("name") == "USD":
                    mcap = q.get("marketCap", 0)
                    break
            result.append({
                "symbol": sym,
                "name": name,
                "market_cap": mcap,
                "cg_id": "",
            })
        return result
    except Exception as e:
        log(f"CoinMarketCap API error: {e}")
        return []


def get_top_cryptos(limit: int = 30) -> list[dict]:
    """Get top cryptos, trying CoinGecko first, then CMC fallback."""
    data = get_top_cryptos_coingecko(limit)
    if data:
        log(f"Using CoinGecko data ({len(data)} coins)")
        return data

    log("CoinGecko failed, trying CoinMarketCap fallback...")
    data = get_top_cryptos_cmc(limit)
    if data:
        log(f"Using CoinMarketCap data ({len(data)} coins)")
        return data

    log("ERROR: Both data sources failed!")
    return []


# ── Token Filtering ──────────────────────────────────────────

def is_valid_crypto(coin: dict) -> tuple[bool, str]:
    """
    Check if a coin is a valid tradeable crypto.
    Returns (is_valid, skip_reason).
    """
    sym = coin["symbol"]
    name = coin.get("name", "")
    cg_id = coin.get("cg_id", "")

    # 1. Stablecoin check
    if sym in STABLECOINS:
        return False, "stablecoin"

    # 2. Exchange token check
    if sym in EXCHANGE_TOKENS:
        return False, "exchange-token"

    # 3. Wrapped/bridged token check
    if sym in WRAPPED_TOKENS:
        return False, "wrapped-token"

    # 4. CoinGecko blocklist (known artifacts)
    if cg_id in BLOCKLIST_COINGECKO_IDS:
        return False, f"blocklisted-id({cg_id})"

    # 5. Symbol sanity: real crypto tickers are 2-6 alphanumeric chars
    if not re.match(r'^[A-Z0-9]{2,8}$', sym):
        return False, f"invalid-symbol({sym})"

    # 6. Name sanity: reject securitized products, HELOCs, etc.
    name_lower = name.lower()
    blacklist_words = ["heloc", "securitiz", "bond", "treasury", "mortgage", "real estate"]
    for word in blacklist_words:
        if word in name_lower:
            return False, f"non-crypto-name({name})"

    return True, ""


# ── Build Token List ─────────────────────────────────────────

def build_top15(bingx_symbols: set) -> list[dict]:
    """Build ordered list of top 15 tradeable tokens, validated against BingX."""
    cryptos = get_top_cryptos(limit=40)  # Fetch extra to fill gaps
    if not cryptos:
        return []

    result = []
    skipped = []

    for coin in cryptos:
        sym = coin["symbol"]

        # Apply all filters
        valid, reason = is_valid_crypto(coin)
        if not valid:
            skipped.append((sym, reason))
            continue

        # Check BingX availability
        pair = f"{sym}-USDT"
        if pair not in bingx_symbols:
            skipped.append((sym, "not-on-BingX-perp"))
            continue

        # Valid! Add to list
        rank = len(result) + 1
        trade = rank <= TOP_N_TRADE
        lev = LEVERAGE_OVERRIDES.get(pair, DEFAULT_LEVERAGE)
        mcap = coin.get("market_cap", 0)

        result.append({
            "symbol": pair,
            "leverage": lev,
            "trade": trade,
            "rank": rank,
            "market_cap": mcap,
            "name": coin.get("name", ""),
        })

        if len(result) >= TOP_N_TOTAL:
            break

    # Log skipped tokens
    if skipped:
        log(f"Skipped {len(skipped)} tokens:")
        for sym, reason in skipped:
            log(f"  SKIP {sym:<10} → {reason}")

    return result


# ── File Operations ──────────────────────────────────────────

def load_current_tokens() -> dict:
    """Load current active_tokens.json."""
    if os.path.exists(ACTIVE_TOKENS_FILE):
        with open(ACTIVE_TOKENS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_tokens(tokens_list: list[dict]):
    """Save updated active_tokens.json (atomic write)."""
    output = {
        "active_tokens": [
            {
                "symbol": t["symbol"],
                "leverage": t["leverage"],
                "trade": t["trade"],
                "rank": t["rank"],
            }
            for t in tokens_list
        ],
        "candidates": [t["symbol"] for t in tokens_list],
        "last_update": datetime.now(timezone.utc).isoformat(),
        "note": f"Auto-updated by top10 cron v2. Top {TOP_N_TRADE} trade, rest train only.",
    }

    # Atomic write
    tmp_path = ACTIVE_TOKENS_FILE + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(output, f, indent=4)
    os.replace(tmp_path, ACTIVE_TOKENS_FILE)


def notify_bot():
    """Write reload flag for bot to pick up changes."""
    flag = "/tmp/profitlab_quantum/reload_tokens"
    os.makedirs(os.path.dirname(flag), exist_ok=True)
    with open(flag, "w") as f:
        f.write(datetime.now(timezone.utc).isoformat())
    log("Wrote reload flag")


# ── Main ─────────────────────────────────────────────────────

def main():
    log("=" * 60)
    log("Starting daily top-10 market cap update (v2)")

    # 1. Get BingX available symbols
    bingx_symbols = get_bingx_symbols()
    if not bingx_symbols:
        log("ABORT: Could not fetch BingX symbols. Keeping current config.")
        sys.exit(1)

    # 2. Build top 15 (with all filters)
    new_top = build_top15(bingx_symbols)
    if len(new_top) < TOP_N_TRADE:
        log(f"ABORT: Only found {len(new_top)} valid tokens (need >= {TOP_N_TRADE}). Keeping current config.")
        sys.exit(1)

    # 3. Compare with current
    current = load_current_tokens()
    current_syms = set()
    if "active_tokens" in current:
        current_syms = {t["symbol"] if isinstance(t, dict) else t for t in current["active_tokens"]}

    new_syms = {t["symbol"] for t in new_top}
    added = new_syms - current_syms
    removed = current_syms - new_syms
    trading = [t["symbol"] for t in new_top if t["trade"]]
    training = [t["symbol"] for t in new_top if not t["trade"]]

    log(f"Result — top {TOP_N_TOTAL}:")
    for t in new_top:
        mode = "TRADE" if t["trade"] else "TRAIN"
        mcap_b = t.get("market_cap", 0) / 1e9
        log(f"  #{t['rank']:>2} {t['symbol']:<14} {mode:<6} {t.get('name',''):<20} mcap=${mcap_b:.1f}B  lev={t['leverage']}x")

    if added:
        log(f"NEW tokens: {added}")
    if removed:
        log(f"REMOVED tokens: {removed}")
    if not added and not removed:
        log("No changes in token list")

    # 4. Save
    save_tokens(new_top)
    log(f"Saved {len(new_top)} tokens ({len(trading)} trade, {len(training)} train)")

    # 5. Notify bot
    notify_bot()

    log("Done. Bot will pick up changes on next restart.")
    log("=" * 60)


if __name__ == "__main__":
    main()
