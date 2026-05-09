#!/usr/bin/env python3
"""
VelocityQuant — HyperLiquid Shadow Daemon
Paper mode · monitorea cross-exchange spreads + funding rates
NO ejecuta órdenes reales.
"""
import json
import os
import sys
import time
import signal
from datetime import datetime, timezone
from pathlib import Path
import urllib.request
import urllib.error

# ===== Config =====
HL_API = "https://api.hyperliquid.xyz/info"
# Binance bloquea US East Coast (HTTP 451). Usamos Bybit como benchmark cross-exchange.
BYBIT_API = "https://api.bybit.com/v5"
DATA_DIR = Path("/home/ubuntu/hyperliquid/data")
LOG_PATH = DATA_DIR / "hyperliquid_shadow.jsonl"
SNAPSHOT_PATH = DATA_DIR / "snapshot.json"
T0_PATH = DATA_DIR / "t0.txt"
SCAN_INTERVAL_SEC = 5

# Pares a vigilar (cross-exchange entre HL y Binance)
WATCH = ["BTC", "ETH", "SOL", "DOGE", "XRP", "AVAX", "LINK", "SUI", "ONDO", "AAVE"]

# Thresholds para "would_send" virtual (paper mode)
MIN_SPREAD_BPS = 3.0       # spread mínimo entre HL y Binance para opp
MIN_FUNDING_DIFF_BPS = 1.0 # diferencia funding rate mínima (vs cero) para basis trade
PROBE_SIZE_USD = 1000.0     # probe size simulado por trade

# ===== HTTP helper =====
def http_post(url, payload, timeout=10):
    req = urllib.request.Request(url, method="POST",
                                  data=json.dumps(payload).encode(),
                                  headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

def http_get(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())

# ===== Market data =====
def fetch_hyperliquid():
    """Fetch HyperLiquid meta + asset contexts (mark price, funding, OI, volume)"""
    meta = http_post(HL_API, {"type":"metaAndAssetCtxs"})
    universe = meta[0]["universe"]
    ctxs = meta[1]
    out = {}
    for i, asset in enumerate(universe):
        name = asset["name"]
        ctx = ctxs[i]
        if ctx.get("markPx") is None:
            continue
        out[name] = {
            "mark":     float(ctx["markPx"]),
            "mid":      float(ctx.get("midPx") or ctx["markPx"]),
            "oracle":   float(ctx.get("oraclePx") or ctx["markPx"]),
            "funding":  float(ctx.get("funding", 0)),
            "oi_coins": float(ctx.get("openInterest", 0)),
            "vol24h":   float(ctx.get("dayNtlVlm", 0)),
        }
    return out

def fetch_bybit_perps(symbols):
    """Fetch Bybit linear (USDT) perp prices + funding. US-friendly, no HTTP 451."""
    out = {}
    try:
        data = http_get(f"{BYBIT_API}/market/tickers?category=linear")
        if data.get("retCode") != 0:
            print(f"bybit retCode={data.get('retCode')}", file=sys.stderr)
            return out
        ticker_map = {t["symbol"]: t for t in data["result"]["list"]}
        for sym in symbols:
            bsym = f"{sym}USDT"
            if bsym in ticker_map:
                t = ticker_map[bsym]
                # Bybit funding rate is per 8h, expressed as decimal (e.g. 0.0001 = 0.01%)
                out[sym] = {
                    "mark":       float(t["lastPrice"]),
                    "funding_8h": float(t.get("fundingRate", 0)),
                    "vol24h":     float(t.get("turnover24h", 0)),
                }
    except Exception as e:
        print(f"bybit fetch err: {e}", file=sys.stderr)
    return out

# ===== Opportunity detection =====
def detect_opportunities(hl_data, bybit_data, ts):
    """Identifica oportunidades de cross-exchange basis arb + funding rate basis"""
    opps = []
    for sym in WATCH:
        if sym not in hl_data or sym not in bybit_data:
            continue
        hl = hl_data[sym]
        bb = bybit_data[sym]

        # 1. Cross-exchange basis: HL mark vs Bybit mark
        mid = (hl["mark"] + bb["mark"]) / 2
        spread_abs = abs(hl["mark"] - bb["mark"])
        spread_bps = (spread_abs / mid) * 10000 if mid > 0 else 0

        # 2. Funding rate differential (both normalized to 8h % for comparison)
        hl_funding_8h = hl["funding"] * 8 * 100  # HL hourly → 8h %
        bb_funding_8h = bb["funding_8h"] * 100   # Bybit already 8h, decimal → %
        funding_diff = hl_funding_8h - bb_funding_8h
        funding_diff_bps = abs(funding_diff) * 100  # % → bps

        # 3. Basis trade signal: when HL price diverges from Bybit
        if hl["mark"] > bb["mark"]:
            basis_direction = "SHORT_HL_LONG_BB"  # HL caro → short HL, long Bybit
        else:
            basis_direction = "LONG_HL_SHORT_BB"

        # Theoretical PnL estimate
        # For cross-basis: probe × spread_bps / 10000
        gross_basis = PROBE_SIZE_USD * spread_bps / 10000
        # For funding arb (annualized): probe × funding_8h × 3 × 365 / 100
        annualized_funding_pct = abs(hl_funding_8h) * 3 * 365  # rough

        would_capture_basis = spread_bps >= MIN_SPREAD_BPS
        would_capture_funding = funding_diff_bps >= MIN_FUNDING_DIFF_BPS

        opps.append({
            "ticker":           sym,
            "hl_mark":          hl["mark"],
            "bb_mark":          bb["mark"],
            "mid":              mid,
            "spread_abs":       spread_abs,
            "spread_bps":       round(spread_bps, 3),
            "hl_funding_8h_pct": round(hl_funding_8h, 5),
            "bb_funding_8h_pct": round(bb_funding_8h, 5),
            "funding_diff_bps": round(funding_diff_bps, 2),
            "basis_direction":  basis_direction,
            "annualized_funding_est_pct": round(annualized_funding_pct, 2),
            "gross_basis_usd":  round(gross_basis, 4),
            "hl_oi_usd":        round(hl["oi_coins"] * hl["mark"], 0),
            "hl_vol24h_usd":    round(hl["vol24h"], 0),
            "would_capture_basis":   would_capture_basis,
            "would_capture_funding": would_capture_funding,
        })
    return opps

# ===== Logging =====
def write_record(record):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(record) + "\n")

def write_snapshot(snapshot):
    with open(SNAPSHOT_PATH, "w") as f:
        json.dump(snapshot, f, indent=2)

# ===== Main loop =====
def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not T0_PATH.exists():
        T0_PATH.write_text(f"T0={datetime.now(timezone.utc).isoformat()}\n")

    print(f"VelocityQuant HL Shadow · T0={T0_PATH.read_text().strip()}")
    print(f"Watching: {', '.join(WATCH)}")
    print(f"Scan interval: {SCAN_INTERVAL_SEC}s")
    print(f"Probe size simulated: ${PROBE_SIZE_USD:,.0f}")
    print(f"Min spread for would_capture: {MIN_SPREAD_BPS} bps")
    print(f"Log: {LOG_PATH}")
    print()

    iteration = 0
    while True:
        iteration += 1
        ts = datetime.now(timezone.utc).isoformat()
        t_start = time.time()
        try:
            hl = fetch_hyperliquid()
            bb = fetch_bybit_perps(WATCH)
            opps = detect_opportunities(hl, bb, ts)

            # Aggregate stats this scan
            n_opps_basis = sum(1 for o in opps if o["would_capture_basis"])
            n_opps_funding = sum(1 for o in opps if o["would_capture_funding"])
            max_spread = max((o["spread_bps"] for o in opps), default=0)

            # Per-ticker JSONL records
            for o in opps:
                rec = {"timestamp": ts, "iteration": iteration, **o}
                write_record(rec)

            # Latest snapshot for dashboard
            snapshot = {
                "timestamp": ts,
                "iteration": iteration,
                "scan_duration_ms": round((time.time() - t_start) * 1000, 1),
                "n_tickers": len(opps),
                "n_opps_basis": n_opps_basis,
                "n_opps_funding": n_opps_funding,
                "max_spread_bps": max_spread,
                "probe_size_usd": PROBE_SIZE_USD,
                "min_spread_threshold_bps": MIN_SPREAD_BPS,
                "tickers": opps,
            }
            write_snapshot(snapshot)

            print(f"[{ts}] iter={iteration} tickers={len(opps)} "
                  f"opps_basis={n_opps_basis} opps_fund={n_opps_funding} "
                  f"max_spread={max_spread:.2f}bps "
                  f"scan={snapshot['scan_duration_ms']:.0f}ms")

        except Exception as e:
            print(f"[{ts}] ERROR: {e}", file=sys.stderr)

        # Sleep until next scan
        elapsed = time.time() - t_start
        if elapsed < SCAN_INTERVAL_SEC:
            time.sleep(SCAN_INTERVAL_SEC - elapsed)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, lambda s,f: (print("\nshutdown"), sys.exit(0)))
    main()
