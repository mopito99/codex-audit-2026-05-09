#!/usr/bin/env python3
"""
Gemma4 Strategy Engine — ProfitLab Quantum
===========================================
Offline engine that runs every 4-6h using GPU:
1. Downloads 72h klines (5m, 15m) for all active tokens
2. Computes technical features (RSI, MACD, OB, FVG, volume, squeeze)
3. Runs combinatorial backtest of indicator combos x SL/TP levels
4. Sends top results to Gemma4 for narrative analysis + rule selection
5. Generates playbook.json for the real-time bot
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests

# ── Paths ───────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
ACTIVE_TOKENS_PATH = BASE_DIR / "active_tokens.json"
PLAYBOOK_PATH = BASE_DIR / "data" / "playbook.json"
STRATEGY_LOG = BASE_DIR / "data" / "strategy_log.json"
BINGX_BASE = "https://open-api.bingx.com"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
GEMMA_MODEL = os.getenv("GEMMA_MODEL", "gemma4:latest")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("StrategyEngine")


# ═════════════════════════════════════════════════════════════════
# PHASE 1: DATA COLLECTION
# ═════════════════════════════════════════════════════════════════

def load_tokens() -> list[str]:
    with open(ACTIVE_TOKENS_PATH) as f:
        data = json.load(f)
        tokens = data.get("active_tokens", [])
        if tokens and isinstance(tokens[0], dict):
            return [t["symbol"] for t in tokens]
        return tokens


def fetch_klines(symbol: str, interval: str, limit: int = 1000) -> pd.DataFrame | None:
    """Fetch klines from BingX REST API."""
    url = f"{BINGX_BASE}/openApi/swap/v3/quote/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        r = requests.get(url, params=params, timeout=15)
        data = r.json()
        if data.get("code") != 0 or not data.get("data"):
            return None
        df = pd.DataFrame(data["data"])
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "time" in df.columns:
            df["timestamp"] = pd.to_numeric(df["time"], errors="coerce")
            df = df.sort_values("timestamp").reset_index(drop=True)
        return df.dropna(subset=["close"])
    except Exception as e:
        log.warning("Klines error %s %s: %s", symbol, interval, e)
        return None


def collect_data(tokens: list[str]) -> dict[str, dict[str, pd.DataFrame]]:
    """Collect klines for all tokens across timeframes."""
    data: dict[str, dict[str, pd.DataFrame]] = {}
    timeframes = {"5m": 864, "15m": 288}  # 72h

    total = len(tokens) * len(timeframes)
    done = 0
    for sym in tokens:
        data[sym] = {}
        for tf, limit in timeframes.items():
            df = fetch_klines(sym, tf, limit)
            done += 1
            if df is not None and len(df) > 50:
                data[sym][tf] = df
                log.info("[%d/%d] %s %s: %d candles", done, total, sym, tf, len(df))
            else:
                log.warning("[%d/%d] %s %s: FAILED", done, total, sym, tf)
            time.sleep(0.15)
    return data


# ═════════════════════════════════════════════════════════════════
# PHASE 2: FEATURE COMPUTATION
# ═════════════════════════════════════════════════════════════════

def compute_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute trading features for each candle."""
    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    volume = df["volume"].astype(float)
    n = len(close)
    feat = df.copy()

    # RSI 14
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-10)
    feat["rsi"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    feat["macd"] = ema12 - ema26
    feat["macd_signal"] = feat["macd"].ewm(span=9).mean()
    feat["macd_cross_up"] = ((feat["macd"] > feat["macd_signal"]) &
                              (feat["macd"].shift(1) <= feat["macd_signal"].shift(1)))
    feat["macd_cross_down"] = ((feat["macd"] < feat["macd_signal"]) &
                                (feat["macd"].shift(1) >= feat["macd_signal"].shift(1)))

    # EMAs
    feat["ema9"] = close.ewm(span=9).mean()
    feat["ema21"] = close.ewm(span=21).mean()
    feat["ema_dist"] = (close - feat["ema9"]) / (close + 1e-10)

    # ATR 14
    tr = pd.concat([high - low, (high - close.shift(1)).abs(),
                     (low - close.shift(1)).abs()], axis=1).max(axis=1)
    feat["atr"] = tr.rolling(14).mean()
    feat["atr_pct"] = feat["atr"] / (close + 1e-10)

    # Volume ratio
    vol_sma = volume.rolling(20).mean()
    feat["vol_ratio"] = volume / (vol_sma + 1e-10)

    # Bollinger Bands
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    feat["bb_upper"] = bb_mid + 2 * bb_std
    feat["bb_lower"] = bb_mid - 2 * bb_std
    feat["bb_position"] = (close - feat["bb_lower"]) / (feat["bb_upper"] - feat["bb_lower"] + 1e-10)

    # Squeeze
    if n >= 20:
        ema20 = close.ewm(span=20).mean()
        atr20 = tr.rolling(20).mean()
        kc_upper = ema20 + 1.5 * atr20
        kc_lower = ema20 - 1.5 * atr20
        feat["squeeze"] = ((feat["bb_lower"] > kc_lower) &
                            (feat["bb_upper"] < kc_upper)).astype(float)
    else:
        feat["squeeze"] = 0.0

    # ADX
    if n >= 15:
        plus_dm = high.diff().clip(lower=0)
        minus_dm = (-low.diff()).clip(lower=0)
        plus_di = 100 * (plus_dm.rolling(14).mean() / (feat["atr"] + 1e-10))
        minus_di = 100 * (minus_dm.rolling(14).mean() / (feat["atr"] + 1e-10))
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)) * 100
        feat["adx"] = dx.rolling(14).mean()
    else:
        feat["adx"] = 0.0

    # HTF trend
    feat["htf_trend"] = feat["ema21"].pct_change(5)

    # Swing detection
    feat["swing_low"] = (low <= low.rolling(5, center=True).min()).astype(float)
    feat["swing_high"] = (high >= high.rolling(5, center=True).max()).astype(float)

    # FVG
    if n >= 3:
        feat["fvg_bull"] = (low > high.shift(2)).astype(float)
        feat["fvg_bear"] = (high < low.shift(2)).astype(float)
    else:
        feat["fvg_bull"] = 0.0
        feat["fvg_bear"] = 0.0

    # ── Time-based features ──────────────────────────────────────
    if "timestamp" in feat.columns:
        ts = pd.to_datetime(feat["timestamp"], unit="ms", utc=True, errors="coerce")
        feat["hour_utc"] = ts.dt.hour.astype(float)
    else:
        feat["hour_utc"] = 12.0  # neutral default

    # Liquidity score: 1.0 during London+US overlap, 0.3 during dead hours
    def _liq(h):
        if 13 <= h <= 16: return 1.0    # London + US overlap = max liquidity
        if 7 <= h <= 12: return 0.8     # London only
        if 17 <= h <= 21: return 0.7    # US only
        if 22 <= h or h <= 1: return 0.4  # Asia early
        return 0.3                       # Dead hours (2-6 UTC)
    feat["liquidity"] = feat["hour_utc"].apply(_liq)

    return feat.dropna().reset_index(drop=True)


# ═════════════════════════════════════════════════════════════════
# PHASE 3: COMBINATORIAL BACKTEST
# ═════════════════════════════════════════════════════════════════

LONG_CONDITIONS = [
    ("rsi_oversold",   "rsi",            "<", 42),
    ("rsi_deep_os",    "rsi",            "<", 35),
    ("macd_cross_up",  "macd_cross_up",  "==", True),
    ("ema_below",      "ema_dist",       "<", -0.003),
    ("vol_spike",      "vol_ratio",      ">", 1.3),
    ("vol_big_spike",  "vol_ratio",      ">", 2.0),
    ("bb_low",         "bb_position",    "<", 0.3),
    ("squeeze_fire",   "squeeze",        ">", 0.5),
    ("htf_up",         "htf_trend",      ">", 0.002),
    ("adx_trending",   "adx",            ">", 20),
    ("swing_low",      "swing_low",      ">", 0.5),
    ("fvg_bull",       "fvg_bull",       ">", 0.5),
    # Time-based conditions
    ("high_liq",       "liquidity",      ">", 0.7),   # Only during London/US
    ("any_liq",        "liquidity",      ">", 0.3),   # Exclude dead hours
]

SHORT_CONDITIONS = [
    ("rsi_overbought", "rsi",            ">", 58),
    ("rsi_deep_ob",    "rsi",            ">", 65),
    ("macd_cross_dn",  "macd_cross_down","==", True),
    ("ema_above",      "ema_dist",       ">", 0.003),
    ("vol_spike",      "vol_ratio",      ">", 1.3),
    ("vol_big_spike",  "vol_ratio",      ">", 2.0),
    ("bb_high",        "bb_position",    ">", 0.7),
    ("squeeze_fire",   "squeeze",        ">", 0.5),
    ("htf_down",       "htf_trend",      "<", -0.002),
    ("adx_trending",   "adx",            ">", 20),
    ("swing_high",     "swing_high",     ">", 0.5),
    ("fvg_bear",       "fvg_bear",       ">", 0.5),
    # Time-based conditions
    ("high_liq",       "liquidity",      ">", 0.7),   # Only during London/US
    ("any_liq",        "liquidity",      ">", 0.3),   # Exclude dead hours
]

SL_LEVELS = [0.010, 0.015, 0.020, 0.025]
TP_LEVELS = [0.010, 0.015, 0.020, 0.030, 0.040]


def eval_condition(df: pd.DataFrame, col: str, op: str, val: Any) -> pd.Series:
    s = df[col]
    if op == "<":  return s < val
    if op == ">":  return s > val
    if op == "==": return s == val
    if op == "<=": return s <= val
    if op == ">=": return s >= val
    return pd.Series(False, index=df.index)


def backtest_rule(df: pd.DataFrame, entry_mask: pd.Series, direction: str,
                  sl_pct: float, tp_pct: float) -> dict[str, Any]:
    """Backtest a rule. Returns performance stats."""
    entries = df.index[entry_mask].tolist()
    if not entries:
        return {"trades": 0}

    wins, losses, pnls = 0, 0, []

    for idx in entries:
        entry_price = float(df.loc[idx, "close"])
        if entry_price <= 0:
            continue

        if direction == "LONG":
            sl = entry_price * (1 - sl_pct)
            tp = entry_price * (1 + tp_pct)
        else:
            sl = entry_price * (1 + sl_pct)
            tp = entry_price * (1 - tp_pct)

        pnl = 0.0
        max_candles = min(len(df) - idx - 1, 60)
        hit = False
        for j in range(1, max_candles + 1):
            ni = idx + j
            if ni >= len(df):
                break
            h = float(df.loc[ni, "high"])
            l = float(df.loc[ni, "low"])

            if direction == "LONG":
                if l <= sl:
                    pnl = -sl_pct; losses += 1; hit = True; break
                if h >= tp:
                    pnl = tp_pct; wins += 1; hit = True; break
            else:
                if h >= sl:
                    pnl = -sl_pct; losses += 1; hit = True; break
                if l <= tp:
                    pnl = tp_pct; wins += 1; hit = True; break

        if not hit:
            exit_price = float(df.loc[min(idx + max_candles, len(df) - 1), "close"])
            if direction == "LONG":
                pnl = (exit_price - entry_price) / entry_price
            else:
                pnl = (entry_price - exit_price) / entry_price
            if pnl > 0: wins += 1
            else: losses += 1

        pnls.append(pnl)

    total = wins + losses
    if total == 0:
        return {"trades": 0}

    avg_pnl = float(np.mean(pnls))
    std_pnl = float(np.std(pnls)) if len(pnls) > 1 else 0.01
    # Floor std at 0.5% to prevent Sharpe explosion when all trades win
    std_pnl = max(std_pnl, 0.005)
    sharpe = (avg_pnl / std_pnl) * (252 ** 0.5)
    # Cap Sharpe at reasonable bounds
    sharpe = max(min(sharpe, 10.0), -10.0)

    return {
        "trades": total, "wins": wins, "losses": losses,
        "win_rate": round(wins / total * 100, 1),
        "avg_pnl": round(avg_pnl * 100, 3),
        "total_pnl": round(sum(pnls) * 100, 2),
        "sharpe": round(sharpe, 2),
    }


def run_backtest(all_data: dict[str, dict[str, pd.DataFrame]]) -> list[dict[str, Any]]:
    """Run combinatorial backtest across all tokens and timeframes.
    
    Optimized: pre-computes per-condition masks using numpy arrays,
    then combines them via bitwise AND for each combo. This avoids
    redundant pandas Series operations and cuts runtime ~5-8x.
    """
    from itertools import combinations

    long_combos = []
    for r in range(2, 4):
        long_combos.extend(list(combinations(range(len(LONG_CONDITIONS)), r)))

    short_combos = []
    for r in range(2, 4):
        short_combos.extend(list(combinations(range(len(SHORT_CONDITIONS)), r)))

    log.info("Testing %d LONG combos + %d SHORT combos", len(long_combos), len(short_combos))

    # Pre-compute features for all dataframes
    featured_data: dict[str, dict[str, pd.DataFrame]] = {}
    for sym, tfs in all_data.items():
        featured_data[sym] = {}
        for tf, df in tfs.items():
            feat = compute_features(df)
            if len(feat) >= 50:
                featured_data[sym][tf] = feat

    # ── KEY OPTIMIZATION: Pre-compute ALL condition masks as numpy arrays ──
    # Structure: precomp[sym][tf] = {"LONG": [np.array, ...], "SHORT": [...]}
    precomp: dict[str, dict[str, dict[str, list[np.ndarray]]]] = {}
    for sym, tfs in featured_data.items():
        precomp[sym] = {}
        for tf, feat in tfs.items():
            long_masks = []
            for name, col, op, val in LONG_CONDITIONS:
                if col in feat.columns:
                    long_masks.append(eval_condition(feat, col, op, val).values)
                else:
                    long_masks.append(np.zeros(len(feat), dtype=bool))
            short_masks = []
            for name, col, op, val in SHORT_CONDITIONS:
                if col in feat.columns:
                    short_masks.append(eval_condition(feat, col, op, val).values)
                else:
                    short_masks.append(np.zeros(len(feat), dtype=bool))
            precomp[sym][tf] = {"LONG": long_masks, "SHORT": short_masks}

    # Filter SL/TP combos once
    sl_tp_pairs = [(sl, tp) for sl in SL_LEVELS for tp in TP_LEVELS if tp >= sl * 1.2]

    results = []
    conditions_map = {"LONG": (long_combos, LONG_CONDITIONS), "SHORT": (short_combos, SHORT_CONDITIONS)}

    for direction in ["LONG", "SHORT"]:
        combos, cond_list = conditions_map[direction]
        for combo_indices in combos:
            combo_name = " + ".join([cond_list[i][0] for i in combo_indices])
            best_result = None
            best_sharpe = -999

            for sym, tfs in featured_data.items():
                for tf, feat in tfs.items():
                    masks = precomp[sym][tf][direction]
                    # Combine pre-computed numpy masks with AND
                    combined = masks[combo_indices[0]].copy()
                    skip = False
                    for idx in combo_indices[1:]:
                        combined &= masks[idx]
                        if combined.sum() < 3:
                            skip = True
                            break
                    if skip or combined.sum() < 3:
                        continue

                    mask_series = pd.Series(combined, index=feat.index)
                    for sl, tp in sl_tp_pairs:
                        r = backtest_rule(feat, mask_series, direction, sl, tp)
                        if (r["trades"] >= 5 and r["win_rate"] >= 45
                                and r["sharpe"] > 0.3 and r["sharpe"] > best_sharpe):
                            best_sharpe = r["sharpe"]
                            best_result = {
                                "direction": direction,
                                "combo": combo_name,
                                "conditions": [{"name": cond_list[i][0], "col": cond_list[i][1],
                                                "op": cond_list[i][2], "val": cond_list[i][3]}
                                               for i in combo_indices],
                                "sl_pct": sl, "tp_pct": tp, **r,
                            }

            if best_result:
                results.append(best_result)

    results.sort(key=lambda x: x.get("sharpe", 0), reverse=True)
    log.info("Backtest complete: %d viable rules found", len(results))
    return results[:50]


# ═════════════════════════════════════════════════════════════════
# PHASE 4: GEMMA4 ANALYSIS
# ═════════════════════════════════════════════════════════════════

GEMMA_PROMPT = """Eres un quant senior que diseña estrategias para smallcaps en perpetual futures con 20x leverage.

Resultados de backtest (72h, 16 smallcaps BingX):

{table}

IMPORTANTE: Los datos incluyen condiciones de liquidez (high_liq = London+US overlap, any_liq = no dead hours).
Las smallcaps tienen liquidez limitada fuera de horarios principales.

Selecciona las TOP 10-14 reglas más robustas. Criterios:
- Win rate >= 50% (20x leverage no tolera muchas pérdidas)
- Sharpe >= 0.5
- BALANCE: mínimo 4 LONG + 4 SHORT para cubrir ambas direcciones
- Diversificar condiciones (no repetir mismas)
- Preferir R:R favorable (TP >= 1.5x SL)
- Incluir reglas con filtro de liquidez cuando mejore el WR
- Reglas con condiciones de hora son MUY valiosas para evitar trampas en horas muertas

AUDITORIA: Analiza también:
1. ¿Hay sesiones horarias donde todas las reglas fallan?
2. ¿Las reglas SHORT funcionan mejor en ciertos horarios?
3. ¿El volumen spike es más confiable con alta liquidez?

Responde SOLO con JSON:
{{
  "market_regime": "descripcion del regimen actual",
  "analysis": "resumen detallado 3-5 lineas incluyendo hallazgos de sesiones",
  "session_insights": "hallazgos sobre horarios y liquidez",
  "rules": [
    {{
      "id": "R001",
      "direction": "LONG",
      "conditions": [{{"col": "rsi", "op": "<", "val": 35}}, {{"col": "vol_ratio", "op": ">", "val": 1.5}}],
      "sl_pct": 0.018,
      "tp1_pct": 0.012,
      "tp2_pct": 0.025,
      "confidence": 0.7,
      "reason": "explicacion incluyendo horario si aplica"
    }}
  ]
}}"""


def ask_gemma_strategy(results: list[dict]) -> dict | None:
    import re
    lines = ["| # | Dir | Conditions | Trades | Win% | Avg PnL | Sharpe | SL | TP |",
             "|---|-----|-----------|--------|------|---------|--------|----|----|"]
    for i, r in enumerate(results[:40], 1):
        lines.append(f"| {i} | {r['direction']} | {r['combo']} | "
                     f"{r['trades']} | {r['win_rate']}% | {r['avg_pnl']}% | "
                     f"{r['sharpe']} | {r['sl_pct']*100}% | {r['tp_pct']*100}% |")
    table = "\n".join(lines)
    prompt = GEMMA_PROMPT.format(table=table)

    log.info("Sending %d results to Gemma4...", min(len(results), 40))
    for attempt in range(2):
        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": GEMMA_MODEL, "prompt": prompt, "stream": False,
                      "options": {"temperature": 0.2, "num_predict": 3000}},
                timeout=180)
            text = resp.json().get("response", "")
        except Exception as e:
            log.error("Ollama error: %s", e)
            continue

        # Parse
        try:
            js = text[text.find("{"):text.rfind("}")+1]
            parsed = json.loads(js)
            if parsed.get("rules") and len(parsed["rules"]) >= 3:
                log.info("Gemma4: %s", parsed.get("analysis", ""))
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass

        # Regex fallback
        matches = re.findall(r'\{[^{}]*"id"\s*:\s*"R\d+"[^{}]*\}', text)
        if matches:
            rules = []
            for m in matches:
                try: rules.append(json.loads(m))
                except Exception: pass
            if len(rules) >= 3:
                return {"rules": rules, "market_regime": "regex_parse",
                        "analysis": "Parsed via regex fallback"}
        log.warning("Gemma4 attempt %d failed", attempt + 1)
    return None


def mechanical_playbook(results: list[dict]) -> dict:
    """Generate balanced playbook: at least 3 LONG + 3 SHORT rules."""
    rules, seen = [], set()
    long_count, short_count = 0, 0
    min_per_dir = 3
    max_rules = 14
    
    # First pass: best rules regardless of direction
    for r in results:
        if r["combo"] in seen:
            continue
        if len(rules) >= max_rules:
            break
        seen.add(r["combo"])
        d = r["direction"]
        if d == "LONG" and long_count >= max_rules - min_per_dir:
            continue  # Reserve slots for SHORT
        if d == "SHORT" and short_count >= max_rules - min_per_dir:
            continue  # Reserve slots for LONG
        rules.append({
            "id": f"R{len(rules)+1:03d}",
            "direction": d,
            "conditions": r["conditions"],
            "sl_pct": r["sl_pct"],
            "tp1_pct": round(r["tp_pct"] * 0.5, 4),
            "tp2_pct": r["tp_pct"],
            "confidence": min(0.9, r["sharpe"] / 2),
            "backtest_winrate": r["win_rate"],
            "backtest_trades": r["trades"],
            "backtest_sharpe": r["sharpe"],
            "reason": f"{r['combo']} | WR={r['win_rate']}% Sharpe={r['sharpe']}",
        })
        if d == "LONG": long_count += 1
        else: short_count += 1
    
    # Second pass: fill missing direction
    for d_needed, count in [("SHORT", short_count), ("LONG", long_count)]:
        if count < min_per_dir:
            for r in results:
                if r["direction"] != d_needed or r["combo"] in seen:
                    continue
                seen.add(r["combo"])
                rules.append({
                    "id": f"R{len(rules)+1:03d}",
                    "direction": d_needed,
                    "conditions": r["conditions"],
                    "sl_pct": r["sl_pct"],
                    "tp1_pct": round(r["tp_pct"] * 0.5, 4),
                    "tp2_pct": r["tp_pct"],
                    "confidence": min(0.9, r["sharpe"] / 2),
                    "backtest_winrate": r["win_rate"],
                    "backtest_trades": r["trades"],
                    "backtest_sharpe": r["sharpe"],
                    "reason": f"{r['combo']} | WR={r['win_rate']}% Sharpe={r['sharpe']}",
                })
                count += 1
                if count >= min_per_dir:
                    break
    
    return {
        "market_regime": "mechanical",
        "analysis": f"Balanced playbook: {sum(1 for r in rules if r['direction']=='LONG')}L + {sum(1 for r in rules if r['direction']=='SHORT')}S (72h backtest)",
        "rules": rules,
    }


# ═════════════════════════════════════════════════════════════════
# PHASE 5: OUTPUT
# ═════════════════════════════════════════════════════════════════

def write_playbook(playbook: dict) -> None:
    PLAYBOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
    playbook["generated_at"] = datetime.now(timezone.utc).isoformat()
    playbook["version"] = int(time.time())
    with open(PLAYBOOK_PATH, "w") as f:
        json.dump(playbook, f, indent=2)
    log.info("Playbook: %s (%d rules)", PLAYBOOK_PATH, len(playbook.get("rules", [])))


def log_run(playbook: dict) -> None:
    STRATEGY_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rules": len(playbook.get("rules", [])),
        "regime": playbook.get("market_regime", ""),
    }
    logs = []
    if STRATEGY_LOG.exists():
        try: logs = json.loads(STRATEGY_LOG.read_text())
        except Exception: pass
    logs.append(entry)
    STRATEGY_LOG.write_text(json.dumps(logs[-200:], indent=2))


def main():
    parser = argparse.ArgumentParser(description="Gemma4 Strategy Engine")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-gemma", action="store_true")
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("GEMMA4 STRATEGY ENGINE")
    log.info("=" * 60)

    tokens = load_tokens()
    log.info("Phase 1: Collecting data for %d tokens...", len(tokens))
    all_data = collect_data(tokens)
    total_candles = sum(len(df) for tfs in all_data.values() for df in tfs.values())
    log.info("Total candles: %d", total_candles)

    log.info("Phase 3: Combinatorial backtest...")
    t0 = time.time()
    results = run_backtest(all_data)
    log.info("Backtest: %.1fs", time.time() - t0)

    if not results:
        log.error("No viable rules! Market too choppy.")
        pb = {"rules": [], "market_regime": "no_signal",
              "analysis": "No viable setups in 72h"}
        if not args.dry_run:
            write_playbook(pb)
        return

    print(f"\n{'='*90}")
    print(f"{'#':>3} {'Dir':<6} {'Conditions':<35} {'Tr':>4} {'WR%':>5} {'PnL%':>6} {'Shrp':>5} {'SL':>5} {'TP':>5}")
    print(f"{'='*90}")
    for i, r in enumerate(results[:20], 1):
        print(f"{i:>3} {r['direction']:<6} {r['combo']:<35} {r['trades']:>4} "
              f"{r['win_rate']:>5}% {r['avg_pnl']:>5}% {r['sharpe']:>5} "
              f"{r['sl_pct']*100:>4}% {r['tp_pct']*100:>4}%")
    print(f"{'='*90}\n")

    if args.skip_gemma:
        playbook = mechanical_playbook(results)
    else:
        gemma = ask_gemma_strategy(results)
        playbook = gemma if gemma and gemma.get("rules") else mechanical_playbook(results)

    print(f"\n{'='*60}")
    print("PLAYBOOK:")
    print(f"{'='*60}")
    for r in playbook.get("rules", []):
        rid = r.get("id", "?")
        d = r.get("direction", "?")
        reason = r.get("reason", "")[:55]
        sl = r.get("sl_pct", 0) * 100
        tp2 = r.get("tp2_pct", r.get("tp_pct", 0)) * 100
        print(f"  {rid} {d:<6} SL={sl:.1f}%  TP={tp2:.1f}%  | {reason}")
    print(f"{'='*60}\n")

    if args.dry_run:
        log.info("DRY RUN — not written")
        return

    write_playbook(playbook)
    log_run(playbook)
    
    # ── Phase 5: Auto-calibrate guards from trade history ────
    log.info("Phase 5: Auto-calibrating guards from trade history...")
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from sqlalchemy import create_engine
        from app.auto_calibrator import calibrate
        from app.config import DATABASE_URL
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            cal = calibrate(conn)
        log.info(f"Calibrated: SHORT_thresh={cal.get('short_btc_threshold')} "
                 f"TP0={cal.get('tp0_close_pct')} TP1={cal.get('tp1_close_pct')} "
                 f"L_WR={cal.get('long_wr')}% S_WR={cal.get('short_wr')}%")
    except Exception as e:
        log.warning(f"Auto-calibration failed: {e}")
    
    log.info("Strategy engine complete")


if __name__ == "__main__":
    main()
