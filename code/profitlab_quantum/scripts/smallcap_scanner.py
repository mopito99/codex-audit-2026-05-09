#!/usr/bin/env python3
"""
Gemma4 Small Cap Scanner — ProfitLab Quantum
=============================================
Scans BingX Swap contracts, filters by volume/price, asks Gemma4 (Ollama)
to rank by narrative strength, and updates active_tokens.json.

Usage:
    python3 scripts/smallcap_scanner.py              # Full scan + Gemma4 analysis
    python3 scripts/smallcap_scanner.py --dry-run     # Show results without writing
    python3 scripts/smallcap_scanner.py --mechanical   # Skip Gemma4, mechanical only
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── Config ──────────────────────────────────────────────────────
BINGX_BASE = "https://open-api.bingx.com"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
GEMMA_MODEL = os.getenv("GEMMA_MODEL", "gemma4:latest")

ACTIVE_TOKENS_PATH = Path(__file__).resolve().parent.parent / "active_tokens.json"
SCANNER_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "scanner_log.json"
BOT_SERVICE = "profitlab_quantum_bot.service"

# Filter params
MIN_VOLUME_24H_USD = 500_000   # Minimum 24h volume
MAX_PRICE_USD = 5.0            # Smallcap territory
MAX_TOKENS = 16                # How many tokens to trade
MAX_NEW_PER_ROTATION = 5       # Don't change more than 5 at once
MIN_KEEP = 7                   # Keep at least 7 tokens between rotations

# Exclusions (not smallcaps)
EXCLUDE_ASSETS = {
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "DOT", "LINK", "MATIC",
    "LTC", "BCH", "ETC", "ATOM", "UNI", "AAVE", "MKR", "NEAR", "FIL", "APT",
    "SUI", "INJ", "TIA", "SEI", "TON", "HBAR", "ICP", "VET", "ALGO", "FTM",
    # Stablecoins
    "USDT", "USDC", "DAI", "TUSD", "BUSD", "FDUSD", "USDD",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger("Scanner")


# ── Phase 1: Mechanical Filter ─────────────────────────────────

def fetch_contracts() -> list[dict]:
    """Fetch all BingX swap contracts."""
    url = f"{BINGX_BASE}/openApi/swap/v2/quote/contracts"
    r = requests.get(url, timeout=15)
    data = r.json()
    if data.get("code") != 0:
        log.error("BingX contracts API error: %s", data)
        return []
    return [c for c in data["data"] if c.get("status") == 1 and "USDT" in c.get("symbol", "")]


def fetch_tickers() -> dict[str, dict]:
    """Fetch 24h tickers for all symbols."""
    url = f"{BINGX_BASE}/openApi/swap/v2/quote/ticker"
    r = requests.get(url, timeout=15)
    data = r.json()
    if data.get("code") != 0:
        log.error("BingX ticker API error: %s", data)
        return {}
    tickers = {}
    for t in data.get("data", []):
        sym = t.get("symbol", "")
        if sym:
            tickers[sym] = t
    return tickers


def mechanical_filter(contracts: list[dict], tickers: dict[str, dict]) -> list[dict]:
    """Apply volume, price, and exclusion filters. Returns ranked candidates."""
    candidates = []
    for c in contracts:
        sym = c["symbol"]
        asset = c.get("asset", sym.replace("-USDT", ""))

        # Skip non-smallcaps
        if asset in EXCLUDE_ASSETS:
            continue

        ticker = tickers.get(sym)
        if not ticker:
            continue

        try:
            last_price = float(ticker.get("lastPrice", 0))
            volume_24h = float(ticker.get("quoteVolume", 0))  # USDT volume
            change_pct = float(ticker.get("priceChangePercent", 0))
        except (TypeError, ValueError):
            continue

        # Hard filters
        if last_price <= 0 or last_price > MAX_PRICE_USD:
            continue
        if volume_24h < MIN_VOLUME_24H_USD:
            continue

        candidates.append({
            "symbol": sym,
            "asset": asset,
            "price": round(last_price, 8),
            "volume_24h": round(volume_24h, 0),
            "change_pct": round(change_pct, 2),
        })

    # Sort by volume descending (most liquid first)
    candidates.sort(key=lambda x: x["volume_24h"], reverse=True)
    return candidates


# ── Phase 2: Gemma4 Analysis ───────────────────────────────────

GEMMA_PROMPT = """Eres un analista crypto profesional especializado en small caps de alto momentum para trading con apalancamiento en perpetual futures.

Analiza estos {n} tokens candidatos de BingX Swap con sus métricas 24h:

{table}

Tu tarea:
1. Clasifica cada token en una de estas categorías:
   - 🔥 HOT: narrativa fuerte actual, momentum positivo, volumen alto → OPERAR
   - ⚡ WATCH: tiene potencial pero necesita confirmación → POSIBLE
   - 💀 DEAD: memecoin muerta, sin volumen, sin narrativa → EVITAR

2. Selecciona los TOP {max} tokens para trading activo, priorizando:
   - Volumen 24h alto (liquidez para entrar/salir)
   - Momentum positivo (cambio % positivo)
   - Narrativa viva (AI, memecoins trending, gaming, DePIN, nuevos launches)
   - Evita tokens que solo subieron por un pump and dump

3. Responde SOLO con un JSON válido, sin texto adicional, con este formato exacto:
{{
  "analysis": "Resumen breve del mercado smallcap actual",
  "top_tokens": [
    {{"symbol": "TOKEN-USDT", "rank": 1, "category": "HOT", "reason": "motivo corto"}},
    ...
  ]
}}"""


def build_table(candidates: list[dict]) -> str:
    """Build a markdown table for Gemma4."""
    lines = ["| Token | Price | Vol 24h (USDT) | Change % |", "|---|---|---|---|"]
    for c in candidates[:60]:  # Cap at 60 to fit context
        lines.append(f"| {c['symbol']} | ${c['price']} | ${c['volume_24h']:,.0f} | {c['change_pct']:+.1f}% |")
    return "\n".join(lines)


def _parse_gemma_response(response_text: str) -> list[dict] | None:
    """Try multiple strategies to extract token list from Gemma4 response."""
    import re as _re

    # Strategy 1: Full JSON parse
    try:
        json_start = response_text.find("{")
        json_end = response_text.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            parsed = json.loads(response_text[json_start:json_end])
            top = parsed.get("top_tokens", [])
            if top:
                log.info("Gemma4 analysis: %s", parsed.get("analysis", "N/A"))
                return top
    except json.JSONDecodeError:
        pass

    # Strategy 2: Find the top_tokens array specifically
    try:
        match = _re.search(r'"top_tokens"\s*:\s*\[([^\]]+(?:\{[^}]*\}[^\]]*)*)\]', response_text, _re.DOTALL)
        if match:
            array_text = "[" + match.group(1) + "]"
            array_text = _re.sub(r',\s*\]', ']', array_text)
            array_text = _re.sub(r',\s*\}', '}', array_text)
            return json.loads(array_text)
    except (json.JSONDecodeError, AttributeError):
        pass

    # Strategy 3: Extract individual token objects via regex
    try:
        pattern = r'\{\s*"symbol"\s*:\s*"([^"]+)"\s*,\s*"rank"\s*:\s*(\d+)\s*,\s*"category"\s*:\s*"([^"]+)"\s*,\s*"reason"\s*:\s*"([^"]*)"'
        matches = _re.findall(pattern, response_text)
        if matches:
            tokens = [{"symbol": m[0], "rank": int(m[1]), "category": m[2], "reason": m[3]} for m in matches]
            tokens.sort(key=lambda x: x["rank"])
            return tokens
    except Exception:
        pass

    log.warning("All JSON parsing strategies failed")
    return None


def ask_gemma4(candidates: list[dict], retry: int = 1) -> list[dict] | None:
    """Send candidates to Gemma4 via Ollama for narrative ranking."""
    table = build_table(candidates)
    prompt = GEMMA_PROMPT.format(n=len(candidates[:60]), table=table, max=MAX_TOKENS)

    for attempt in range(retry + 1):
        log.info("Gemma4 attempt %d/%d (%s)...", attempt + 1, retry + 1, GEMMA_MODEL)
        try:
            r = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": GEMMA_MODEL, "prompt": prompt, "stream": False,
                      "options": {"temperature": 0.2, "num_predict": 3000}},
                timeout=180,
            )
            data = r.json()
            response_text = data.get("response", "")
        except Exception as e:
            log.error("Ollama request failed: %s", e)
            continue

        result = _parse_gemma_response(response_text)
        if result and len(result) >= 5:
            log.info("Gemma4 returned %d ranked tokens", len(result))
            return result

        log.warning("Gemma4 response insufficient (got %d tokens), retrying...", len(result or []))

    return None


# ── Phase 3: Rotation ──────────────────────────────────────────

def load_current_tokens() -> list[str]:
    """Load current active tokens."""
    try:
        with open(ACTIVE_TOKENS_PATH) as f:
            data = json.load(f)
            tokens = data.get("active_tokens", [])
            if tokens and isinstance(tokens[0], dict):
                return [t["symbol"] for t in tokens]
            return tokens
    except Exception:
        return []


def check_open_positions() -> set[str]:
    """Check which tokens have open positions (cannot be rotated out)."""
    try:
        import psycopg2
        conn = psycopg2.connect("postgresql://postgres:4366037.Cabeza@localhost/profitlab_quantum_db")
        cur = conn.cursor()
        cur.execute("SELECT symbol FROM paper_positions WHERE side IS NOT NULL")
        positions = {row[0] for row in cur.fetchall()}
        conn.close()
        return positions
    except Exception as e:
        log.warning("Could not check positions: %s", e)
        return set()


def compute_rotation(current: list[str], new_ranked: list[str]) -> list[str]:
    """Compute rotation respecting protection rules."""
    open_positions = check_open_positions()
    current_set = set(current)
    new_set = set(new_ranked[:MAX_TOKENS])

    # Tokens that MUST stay (have open positions)
    must_keep = current_set & open_positions
    log.info("Tokens with open positions (must keep): %s", must_keep or "none")

    # Tokens to potentially remove
    removable = current_set - must_keep
    # Tokens to potentially add
    to_add = new_set - current_set

    # Limit changes
    actual_remove = removable - new_set
    if len(actual_remove) > MAX_NEW_PER_ROTATION:
        # Only remove the lowest-ranked ones
        actual_remove = set(list(actual_remove)[:MAX_NEW_PER_ROTATION])

    actual_add = list(to_add)[:MAX_NEW_PER_ROTATION]

    # Build final list: keep current - removed + added
    final = [t for t in current if t not in actual_remove]
    for t in actual_add:
        if len(final) < MAX_TOKENS:
            final.append(t)

    # Ensure minimum continuity
    if len(set(final) & current_set) < MIN_KEEP:
        log.warning("Too many changes, keeping more current tokens for stability")
        final = current[:MIN_KEEP] + [t for t in final if t not in current[:MIN_KEEP]]
        final = final[:MAX_TOKENS]

    changes = {
        "added": [t for t in final if t not in current_set],
        "removed": [t for t in current if t not in set(final)],
        "kept": [t for t in final if t in current_set],
    }
    log.info("Rotation: +%d added, -%d removed, %d kept",
             len(changes["added"]), len(changes["removed"]), len(changes["kept"]))

    return final


def write_tokens(tokens: list[str], analysis: str = "") -> None:
    """Write new active_tokens.json."""
    data = {
        "active_tokens": [
            {"symbol": sym, "leverage": 20.0, "trade": True, "rank": i + 1}
            for i, sym in enumerate(tokens)
        ],
        "candidates": tokens,
        "last_update": datetime.now(timezone.utc).isoformat(),
        "note": f"Gemma4 Scanner rotation. {analysis}",
    }
    with open(ACTIVE_TOKENS_PATH, "w") as f:
        json.dump(data, f, indent=4)
    log.info("Written %d tokens to %s", len(tokens), ACTIVE_TOKENS_PATH)


def log_rotation(current: list[str], final: list[str], analysis: str) -> None:
    """Append rotation event to scanner log."""
    SCANNER_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "previous": current,
        "new": final,
        "added": [t for t in final if t not in set(current)],
        "removed": [t for t in current if t not in set(final)],
        "analysis": analysis,
    }
    # Append to log
    logs = []
    if SCANNER_LOG_PATH.exists():
        try:
            logs = json.loads(SCANNER_LOG_PATH.read_text())
        except Exception:
            logs = []
    logs.append(entry)
    # Keep last 52 entries (1 year of weekly scans)
    logs = logs[-52:]
    SCANNER_LOG_PATH.write_text(json.dumps(logs, indent=2))


def restart_bot() -> None:
    """Restart the quantum bot service."""
    log.info("Restarting %s...", BOT_SERVICE)
    try:
        subprocess.run(["systemctl", "restart", BOT_SERVICE], check=True, timeout=30)
        log.info("Bot restarted successfully")
    except Exception as e:
        log.error("Failed to restart bot: %s", e)


# ── Main ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Gemma4 Small Cap Scanner")
    parser.add_argument("--dry-run", action="store_true", help="Show results without writing")
    parser.add_argument("--mechanical", action="store_true", help="Skip Gemma4, use mechanical ranking only")
    parser.add_argument("--force", action="store_true", help="Force rotation even if few changes")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("GEMMA4 SMALL CAP SCANNER — ProfitLab Quantum")
    log.info("=" * 60)

    # Phase 1: Mechanical filter
    log.info("Phase 1: Fetching BingX contracts...")
    contracts = fetch_contracts()
    log.info("Found %d active USDT swap contracts", len(contracts))

    tickers = fetch_tickers()
    log.info("Fetched %d tickers", len(tickers))

    candidates = mechanical_filter(contracts, tickers)
    log.info("Phase 1 result: %d candidates pass mechanical filter", len(candidates))

    if not candidates:
        log.error("No candidates found! Check BingX API.")
        sys.exit(1)

    # Show top candidates
    print(f"\n{'='*70}")
    print(f"{'Token':<18} {'Price':>10} {'Vol 24h':>15} {'Change':>8}")
    print(f"{'='*70}")
    for c in candidates[:30]:
        print(f"{c['symbol']:<18} ${c['price']:>9} ${c['volume_24h']:>13,.0f} {c['change_pct']:>+7.1f}%")
    print(f"{'='*70}\n")

    # Phase 2: Gemma4 analysis
    analysis = ""
    if args.mechanical:
        # Just use top by volume
        ranked_symbols = [c["symbol"] for c in candidates[:MAX_TOKENS]]
        analysis = "Mechanical ranking (volume only)"
        log.info("Skipping Gemma4 — using mechanical ranking")
    else:
        gemma_result = ask_gemma4(candidates)
        if gemma_result:
            # Use Gemma4's ranking, but validate symbols exist in candidates
            valid_symbols = {c["symbol"] for c in candidates}
            ranked_symbols = []
            for t in gemma_result:
                sym = t.get("symbol", "")
                if sym in valid_symbols:
                    ranked_symbols.append(sym)
                    cat = t.get("category", "?")
                    reason = t.get("reason", "")
                    print(f"  {cat} #{len(ranked_symbols):>2} {sym:<18} — {reason}")

            # Fill remaining slots with mechanical ranking
            for c in candidates:
                if c["symbol"] not in set(ranked_symbols) and len(ranked_symbols) < MAX_TOKENS:
                    ranked_symbols.append(c["symbol"])

            analysis = "Gemma4 narrative + volume ranking"
        else:
            log.warning("Gemma4 failed, falling back to mechanical ranking")
            ranked_symbols = [c["symbol"] for c in candidates[:MAX_TOKENS]]
            analysis = "Mechanical fallback (Gemma4 unavailable)"

    log.info("Final ranking: %s", ranked_symbols[:MAX_TOKENS])

    # Phase 3: Rotation
    current = load_current_tokens()
    final = compute_rotation(current, ranked_symbols)

    added = [t for t in final if t not in set(current)]
    removed = [t for t in current if t not in set(final)]

    if not added and not removed:
        log.info("No changes needed — current lineup is optimal")
        if not args.force:
            return

    print(f"\n{'='*50}")
    print(f"ROTATION SUMMARY")
    print(f"{'='*50}")
    print(f"  Added:   {added or 'none'}")
    print(f"  Removed: {removed or 'none'}")
    print(f"  Final:   {final}")
    print(f"{'='*50}\n")

    if args.dry_run:
        log.info("DRY RUN — no changes written")
        return

    # Write and restart
    write_tokens(final, analysis)
    log_rotation(current, final, analysis)
    restart_bot()

    log.info("Scanner complete ✅")


if __name__ == "__main__":
    main()
