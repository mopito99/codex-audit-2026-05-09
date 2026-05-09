"""
Token Auto-Rotator — ProfitLab Quantum
=======================================
Connects the killswitch system with the smallcap scanner to automatically
replace dead tokens with fresh candidates via Gemma4.

Called by the Strategic Architect after each calibration cycle.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests
from sqlalchemy import text

from app.db import engine as db_engine

logger = logging.getLogger("TokenRotator")

# ── Paths ──────────────────────────────────────────────────────
_BASE = Path(__file__).resolve().parent.parent
ACTIVE_TOKENS_PATH = _BASE / "active_tokens.json"
KILLED_TOKENS_PATH = _BASE / "data" / "killed_tokens.json"

# ── Config ─────────────────────────────────────────────────────
BINGX_BASE = "https://open-api.bingx.com"
OLLAMA_URL = "http://localhost:11434"
GEMMA_MODEL = "gemma4:latest"
COOLDOWN_DAYS = 7         # Don't re-add killed tokens for 7 days
MAX_TOKENS = 12           # Target token count
MIN_VOLUME_24H = 500_000  # $500K min volume
MAX_PRICE = 5.0           # Smallcap territory

EXCLUDE_ASSETS = {
    # Stablecoins — never trade these
    "USDT", "USDC", "DAI", "TUSD", "BUSD", "FDUSD", "USDD",
}

# Major assets are handled as tier "major" — protected from rotation
MAJOR_ASSETS = {
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "DOT", "LINK", "MATIC",
    "LTC", "BCH", "ETC", "ATOM", "UNI", "AAVE", "MKR", "NEAR", "FIL", "APT",
    "SUI", "INJ", "TIA", "SEI", "TON", "HBAR", "ICP", "VET", "ALGO", "FTM",
}


# ── Killed Tokens Registry ─────────────────────────────────────

def _load_killed() -> dict:
    """Load killed tokens registry."""
    if KILLED_TOKENS_PATH.exists():
        try:
            return json.loads(KILLED_TOKENS_PATH.read_text())
        except Exception:
            pass
    return {}


def _save_killed(data: dict) -> None:
    """Save killed tokens registry."""
    KILLED_TOKENS_PATH.parent.mkdir(parents=True, exist_ok=True)
    KILLED_TOKENS_PATH.write_text(json.dumps(data, indent=2))


def mark_token_killed(symbol: str, reason: str) -> None:
    """Register a token as killed by the killswitch."""
    killed = _load_killed()
    if symbol not in killed:
        killed[symbol] = {
            "killed_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "cooldown_until": (datetime.now(timezone.utc) + timedelta(days=COOLDOWN_DAYS)).isoformat(),
        }
        _save_killed(killed)
        logger.info("🪦 Token %s registered as killed: %s (cooldown %dd)", symbol, reason, COOLDOWN_DAYS)


def get_killed_symbols() -> set[str]:
    """Get symbols currently in cooldown (killed and not yet eligible for re-entry)."""
    killed = _load_killed()
    now = datetime.now(timezone.utc)
    in_cooldown = set()
    for sym, info in killed.items():
        try:
            until = datetime.fromisoformat(info["cooldown_until"])
            if until.tzinfo is None:
                until = until.replace(tzinfo=timezone.utc)
            if now < until:
                in_cooldown.add(sym)
        except Exception:
            in_cooldown.add(sym)  # If unparseable, keep in cooldown
    return in_cooldown


def get_killswitched_active_tokens() -> list[str]:
    """Find meme-tier tokens in active list that have been killed.
    
    Only returns meme-tier tokens — majors are NEVER removed by rotation.
    """
    killed = get_killed_symbols()
    try:
        with open(ACTIVE_TOKENS_PATH) as f:
            data = json.load(f)
        active = data.get("active_tokens", [])
        major_fixed = set(data.get("major_tokens_fixed", []))
        
        if active and isinstance(active[0], dict):
            # Only return killed tokens that are meme tier
            return [t["symbol"] for t in active 
                    if t["symbol"] in killed 
                    and t.get("tier", "meme") == "meme"
                    and t["symbol"] not in major_fixed]
        else:
            active_syms = active
            return [s for s in active_syms if s in killed and s not in major_fixed]
    except Exception:
        return []


# ── BingX Scanner ──────────────────────────────────────────────

def _fetch_candidates() -> list[dict]:
    """Fetch and filter BingX small caps."""
    try:
        # Get contracts
        r = requests.get(f"{BINGX_BASE}/openApi/swap/v2/quote/contracts", timeout=15)
        contracts = r.json().get("data", [])
        contracts = [c for c in contracts if c.get("status") == 1 and "USDT" in c.get("symbol", "")]

        # Get tickers
        r2 = requests.get(f"{BINGX_BASE}/openApi/swap/v2/quote/ticker", timeout=15)
        tickers = {t["symbol"]: t for t in r2.json().get("data", []) if t.get("symbol")}
    except Exception as e:
        logger.error("BingX API error: %s", e)
        return []

    # Load exclusions
    killed_cooldown = get_killed_symbols()
    try:
        with open(ACTIVE_TOKENS_PATH) as f:
            current_active = {t["symbol"] if isinstance(t, dict) else t
                              for t in json.load(f).get("active_tokens", [])}
    except Exception:
        current_active = set()

    candidates = []
    for c in contracts:
        sym = c["symbol"]
        asset = c.get("asset", sym.replace("-USDT", ""))

        if asset in EXCLUDE_ASSETS or asset in MAJOR_ASSETS:
            continue
        if sym in current_active:  # Already active
            continue
        if sym in killed_cooldown:  # In cooldown
            continue

        ticker = tickers.get(sym)
        if not ticker:
            continue

        try:
            price = float(ticker.get("lastPrice", 0))
            vol = float(ticker.get("quoteVolume", 0))
            change = float(ticker.get("priceChangePercent", 0))
        except (TypeError, ValueError):
            continue

        if price <= 0 or price > MAX_PRICE or vol < MIN_VOLUME_24H:
            continue

        candidates.append({
            "symbol": sym, "asset": asset,
            "price": round(price, 8),
            "volume_24h": round(vol, 0),
            "change_pct": round(change, 2),
        })

    candidates.sort(key=lambda x: x["volume_24h"], reverse=True)
    return candidates[:30]  # Top 30 by volume


# ── Gemma4 Selection ───────────────────────────────────────────

_REPLACEMENT_PROMPT = """Eres el Director de Rotación de Tokens de un Hedge Fund Small-Cap (ProfitLab Quantum).

CONTEXTO: Los siguientes tokens han sido ELIMINADOS por mal rendimiento (killswitch):
{killed_list}

Necesito {n_needed} REEMPLAZOS de esta lista de candidatos de BingX:

{table}

CRITERIOS DE SELECCIÓN (en orden de prioridad):
1. Volumen 24h alto (liquidez para perpetual futures con apalancamiento)
2. Narrativa activa (AI, memecoins trending, gaming, DePIN, nuevos launches)
3. Momentum positivo (cambio % positivo indica interés)
4. Evitar tokens que muestren señales de pump-and-dump

Responde SOLO con un JSON válido:
{{"replacements": [{{"symbol": "TOKEN-USDT", "reason": "motivo corto"}}]}}"""


def _ask_gemma4_replacements(killed: list[str], candidates: list[dict], n_needed: int) -> list[str]:
    """Ask Gemma4 to pick replacement tokens."""
    table_lines = ["| Token | Price | Vol 24h | Change |", "|---|---|---|---|"]
    for c in candidates[:20]:
        table_lines.append(f"| {c['symbol']} | ${c['price']} | ${c['volume_24h']:,.0f} | {c['change_pct']:+.1f}% |")

    prompt = _REPLACEMENT_PROMPT.format(
        killed_list=", ".join(killed),
        n_needed=n_needed,
        table="\n".join(table_lines),
    )

    try:
        r = requests.post(f"{OLLAMA_URL}/api/generate", json={
            "model": GEMMA_MODEL, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.2, "num_predict": 1000},
        }, timeout=120)
        text = r.json().get("response", "")

        # Parse JSON
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end])
            replacements = parsed.get("replacements", [])
            valid_syms = {c["symbol"] for c in candidates}
            result = [r["symbol"] for r in replacements if r.get("symbol") in valid_syms]
            if result:
                for r_item in replacements:
                    if r_item.get("symbol") in valid_syms:
                        logger.info("  🔄 Replacement: %s — %s", r_item["symbol"], r_item.get("reason", ""))
                return result[:n_needed]
    except Exception as e:
        logger.error("Gemma4 replacement request failed: %s", e)

    # Fallback: just pick top by volume
    logger.warning("Gemma4 unavailable, using mechanical fallback")
    return [c["symbol"] for c in candidates[:n_needed]]


# ── Equity Reset ───────────────────────────────────────────────

def _reset_token_equity(symbol: str) -> None:
    """Reset paper_equity for a newly added token so it starts fresh."""
    try:
        with db_engine.connect() as conn:
            conn.execute(text("DELETE FROM paper_equity WHERE symbol = :s"), {"s": symbol})
            conn.commit()
        logger.info("  📊 Reset equity for %s", symbol)
    except Exception as e:
        logger.warning("Could not reset equity for %s: %s", symbol, e)


# ── Main Rotation Logic ───────────────────────────────────────

def rotate_dead_tokens() -> dict:
    """
    Main entry point. Called by the Strategic Architect.
    
    Returns: dict with rotation results
    """
    logger.info("=" * 50)
    logger.info("🔄 TOKEN AUTO-ROTATOR — Starting")
    logger.info("=" * 50)

    # 1. Find killed tokens that are still in the active list
    dead_in_active = get_killswitched_active_tokens()

    if not dead_in_active:
        logger.info("✅ No dead tokens in active list — nothing to rotate")
        return {"rotated": False, "dead": [], "added": [], "removed": []}

    logger.info("💀 Dead tokens found in active list: %s", dead_in_active)

    # 2. Fetch candidates from BingX
    candidates = _fetch_candidates()
    if not candidates:
        logger.warning("No candidates found from BingX — skipping rotation")
        return {"rotated": False, "dead": dead_in_active, "added": [], "removed": []}

    logger.info("📋 Found %d candidates from BingX", len(candidates))

    # 3. Ask Gemma4 for replacements
    n_needed = len(dead_in_active)
    new_tokens = _ask_gemma4_replacements(dead_in_active, candidates, n_needed)
    logger.info("🎯 Gemma4 selected %d replacements: %s", len(new_tokens), new_tokens)

    # 4. Update active_tokens.json
    try:
        with open(ACTIVE_TOKENS_PATH) as f:
            data = json.load(f)
    except Exception:
        data = {"active_tokens": [], "candidates": []}

    active = data.get("active_tokens", [])

    # Remove dead tokens (only meme tier)
    major_fixed = set(data.get("major_tokens_fixed", []))
    if active and isinstance(active[0], dict):
        active = [t for t in active if t["symbol"] not in set(dead_in_active) or t["symbol"] in major_fixed]
    else:
        active = [t for t in active if t not in set(dead_in_active) or t in major_fixed]

    # Add new tokens
    max_rank = max((t.get("rank", 0) for t in active if isinstance(t, dict)), default=0)
    for i, sym in enumerate(new_tokens):
        active.append({
            "symbol": sym,
            "leverage": 10.0,   # Memecoins: hard cap 10x
            "trade": True,
            "rank": max_rank + i + 1,
            "tier": "meme",
        })
        # Reset equity for new token
        _reset_token_equity(sym)

    # Re-rank
    for i, t in enumerate(active):
        if isinstance(t, dict):
            t["rank"] = i + 1

    data["active_tokens"] = active
    data["candidates"] = [t["symbol"] if isinstance(t, dict) else t for t in active]
    data["last_update"] = datetime.now(timezone.utc).isoformat()
    data["note"] = f"Auto-rotation: removed {dead_in_active}, added {new_tokens}"

    with open(ACTIVE_TOKENS_PATH, "w") as f:
        json.dump(data, f, indent=4)

    logger.info("✅ active_tokens.json updated: -%d removed, +%d added", len(dead_in_active), len(new_tokens))

    result = {
        "rotated": True,
        "dead": dead_in_active,
        "added": new_tokens,
        "removed": dead_in_active,
    }

    logger.info("🔄 ROTATION COMPLETE: %s", result)
    return result
