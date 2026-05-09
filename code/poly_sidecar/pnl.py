"""PNL module — wallet balances on-chain (Solana RPC) + SHADOW summaries.

Endpoints expuestos (vía health_api.py):
  GET /pnl/balance              → balances actuales master + hot200
  GET /pnl/snapshots?h=24       → series snapshots últimas h horas
  GET /pnl/shadow_summary?h=24  → SHADOW would-profit en cyclic_shadow JSONLs

Datos:
  /poly_sidecar/data/balance_snapshots.jsonl  ← cron cada 5min
  /home/ubuntu/liquidator_rs/data/cyclic_shadow.jsonl     (rsync desde Newark)
  /home/ubuntu/liquidator_rs/data/cyclic_shadow_v4.jsonl  (rsync desde Newark)
"""
from __future__ import annotations
import json
import time
import urllib.request
from pathlib import Path
from typing import Any

DATA_DIR = Path("/home/administrator/poly_sidecar/data")
SNAPSHOTS_FILE = DATA_DIR / "balance_snapshots.jsonl"
SHADOW_MIRROR_DIR = DATA_DIR / "shadow_mirror"  # rsync target Newark→Dallas
SHADOW_CACHE_FILE = DATA_DIR / "shadow_summary_cache.json"  # cache 5min

RPC_URLS = [
    "https://api.mainnet-beta.solana.com",
]
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"

WALLETS = [
    {"label": "master", "pubkey": "<REDACTED-WALLET-PUBKEY>"},
    {"label": "hot200", "pubkey": "<REDACTED-WALLET-PUBKEY>"},
]


def _rpc(method: str, params: list, timeout: float = 6.0, retries: int = 2) -> dict:
    """Try each RPC in RPC_URLS in turn; on 429 advance to next; minimal backoff."""
    req = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    data = json.dumps(req).encode()
    last_exc: Exception | None = None
    for url in RPC_URLS:
        for attempt in range(retries):
            try:
                r = urllib.request.Request(
                    url, data=data, headers={"Content-Type": "application/json"}
                )
                with urllib.request.urlopen(r, timeout=timeout) as resp:
                    return json.loads(resp.read())
            except urllib.error.HTTPError as e:
                last_exc = e
                if e.code == 429:
                    break  # advance to next URL immediately
                if attempt < retries - 1:
                    time.sleep(0.5)
                    continue
                break
            except Exception as e:
                last_exc = e
                if attempt < retries - 1:
                    time.sleep(0.5)
                    continue
                break
    raise last_exc if last_exc else RuntimeError("all RPCs failed")


def _sol_usd_price() -> float | None:
    try:
        r = urllib.request.urlopen(
            "https://api.coinbase.com/v2/prices/SOL-USD/spot", timeout=4
        )
        return float(json.loads(r.read())["data"]["amount"])
    except Exception:
        return None


def wallet_balance(pubkey: str, sol_usd: float | None) -> dict[str, Any]:
    sol_lamports = _rpc("getBalance", [pubkey]).get("result", {}).get("value", 0)
    sol_amount = sol_lamports / 1e9
    tokens = _rpc(
        "getTokenAccountsByOwner",
        [pubkey, {"programId": TOKEN_PROGRAM}, {"encoding": "jsonParsed"}],
    )
    usdc = 0.0
    usdt = 0.0
    other = []
    for acc in tokens.get("result", {}).get("value", []):
        info = acc["account"]["data"]["parsed"]["info"]
        mint = info["mint"]
        amt = float(info["tokenAmount"]["uiAmount"] or 0)
        if amt <= 0:
            continue
        if mint == USDC_MINT:
            usdc = amt
        elif mint == USDT_MINT:
            usdt = amt
        else:
            other.append({"mint": mint, "amount": amt})
    sol_usd_value = sol_amount * sol_usd if sol_usd else None
    total_usd = (sol_usd_value or 0) + usdc + usdt
    return {
        "pubkey": pubkey,
        "sol": round(sol_amount, 6),
        "sol_usd": round(sol_usd_value, 2) if sol_usd_value is not None else None,
        "usdc": round(usdc, 4),
        "usdt": round(usdt, 4),
        "other_tokens": other,
        "total_usd": round(total_usd, 2),
    }


def _last_good_snapshot() -> dict | None:
    """Lee el último snapshot completo (sin errors) del JSONL — cross-process cache."""
    if not SNAPSHOTS_FILE.exists():
        return None
    try:
        # Leer el archivo completo (es pequeño, una línea por 5 min) y devolver el último válido
        with open(SNAPSHOTS_FILE) as f:
            lines = f.readlines()
        for line in reversed(lines):
            try:
                rec = json.loads(line)
                if rec.get("wallets") and all(not w.get("error") for w in rec["wallets"]):
                    return rec
            except Exception:
                continue
    except Exception:
        return None
    return None


def all_balances(cache_ttl_s: int = 90) -> dict[str, Any]:
    """Live RPC read con cache file-based + serve-stale on 429.

    Cache via balance_snapshots.jsonl (escrito por systemd timer cada 5min).
    Si el último snapshot válido es < cache_ttl_s, sirve cached.
    Si fetch fresh falla, sirve last good del JSONL marcado como stale.
    """
    now = time.time()
    last_good = _last_good_snapshot()
    if last_good:
        try:
            cached_age = now - time.mktime(time.strptime(last_good["ts_utc"], "%Y-%m-%dT%H:%M:%SZ"))
        except Exception:
            cached_age = 99999
        if cached_age < cache_ttl_s:
            out = dict(last_good)
            out["served_from_cache"] = True
            out["cache_age_s"] = round(cached_age, 1)
            return out

    # Cache stale o ausente — intentar fresh fetch
    sol_usd = _sol_usd_price()
    out = {
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "sol_usd_price": sol_usd,
        "wallets": [],
        "totals": {"sol": 0.0, "usdc": 0.0, "usdt": 0.0, "total_usd": 0.0},
        "served_from_cache": False,
    }
    n_errors = 0
    for i, w in enumerate(WALLETS):
        if i > 0:
            time.sleep(1.5)
        try:
            b = wallet_balance(w["pubkey"], sol_usd)
            b["label"] = w["label"]
            out["wallets"].append(b)
            out["totals"]["sol"] += b["sol"]
            out["totals"]["usdc"] += b["usdc"]
            out["totals"]["usdt"] += b["usdt"]
            out["totals"]["total_usd"] += b["total_usd"]
        except Exception as e:
            out["wallets"].append({"label": w["label"], "pubkey": w["pubkey"], "error": str(e)})
            n_errors += 1
    for k in ("sol", "usdc", "usdt", "total_usd"):
        out["totals"][k] = round(out["totals"][k], 4 if k != "total_usd" else 2)

    # Si el fresh tuvo errores y existe last_good, servir stale (mejor que $0)
    if n_errors > 0 and last_good:
        try:
            cached_age = now - time.mktime(time.strptime(last_good["ts_utc"], "%Y-%m-%dT%H:%M:%SZ"))
        except Exception:
            cached_age = 99999
        stale = dict(last_good)
        stale["served_from_cache"] = True
        stale["cache_age_s"] = round(cached_age, 1)
        stale["stale_reason"] = f"fresh fetch had {n_errors} RPC errors, serving last good"
        return stale

    return out


def take_snapshot() -> dict[str, Any]:
    """Llamado desde systemd timer cada 5 min."""
    snap = all_balances()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(SNAPSHOTS_FILE, "a") as f:
        f.write(json.dumps(snap, separators=(",", ":")) + "\n")
    return snap


def read_snapshots(hours: int = 24) -> list[dict]:
    if not SNAPSHOTS_FILE.exists():
        return []
    cutoff = time.time() - hours * 3600
    out = []
    with open(SNAPSHOTS_FILE) as f:
        for line in f:
            try:
                rec = json.loads(line)
                ts = time.mktime(time.strptime(rec["ts_utc"], "%Y-%m-%dT%H:%M:%SZ"))
                if ts >= cutoff:
                    out.append(rec)
            except Exception:
                continue
    return out


def shadow_summary(hours: int = 24) -> dict[str, Any]:
    """Lee cyclic_shadow{,_v4}.jsonl mirrored y agrega would-profit.

    Devuelve métricas para 2 windows simultáneamente:
    - 24h móvil sliding (cutoff = now - 24h)
    - "today" desde 00:00 UTC del día actual (firma Marco r137)
    """
    cutoff_ms = (time.time() - hours * 3600) * 1000
    # r137 — además de 24h sliding, añadimos counter "today" desde UTC midnight
    now_t = time.gmtime()
    midnight_utc_unix = time.mktime((
        now_t.tm_year, now_t.tm_mon, now_t.tm_mday, 0, 0, 0, 0, 0, 0
    )) - time.timezone
    today_cutoff_ms = midnight_utc_unix * 1000
    v3_path = SHADOW_MIRROR_DIR / "cyclic_shadow.jsonl"
    v4_path = SHADOW_MIRROR_DIR / "cyclic_shadow_v4.jsonl"

    def parse_iso_ms(s: str) -> float:
        # "2026-05-06T11:10:37.922677458Z" → epoch ms (truncated nanoseconds)
        s = s.replace("Z", "").rstrip("0")
        if "." in s:
            base, frac = s.split(".", 1)
            frac = (frac + "000000")[:6]
            s = f"{base}.{frac}"
        return time.mktime(time.strptime(s.split(".")[0], "%Y-%m-%dT%H:%M:%S")) * 1000

    def scan_v3(path: Path) -> dict:
        if not path.exists():
            return {"present": False, "n_cycles": 0, "total_profit_usd": 0.0,
                    "today": {"n_cycles": 0, "total_profit_usd": 0.0}}
        n = 0
        sum_profit_base = 0
        wins = 0
        losses = 0
        last_ts = None
        # r137 — counters separados para "today" (desde UTC midnight)
        n_today = 0
        sum_profit_today = 0
        wins_today = 0
        # USDC has 6 decimals → divide net_profit_base_units by 1e6 = USD
        with open(path, errors="ignore") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    ts = rec.get("timestamp", "")
                    if not ts:
                        continue
                    ts_ms = parse_iso_ms(ts)
                    profit = rec.get("net_profit_base_units", 0)
                    # 24h sliding window
                    if ts_ms >= cutoff_ms:
                        sum_profit_base += profit
                        n += 1
                        if profit > 0:
                            wins += 1
                        else:
                            losses += 1
                        last_ts = ts
                    # r137 — today window (since UTC midnight)
                    if ts_ms >= today_cutoff_ms:
                        n_today += 1
                        sum_profit_today += profit
                        if profit > 0:
                            wins_today += 1
                except Exception:
                    continue
        # Hours elapsed today (para rate)
        hours_today = (time.time() - midnight_utc_unix) / 3600.0
        return {
            "present": True,
            "n_cycles": n,
            "wins": wins,
            "losses": losses,
            "win_rate_pct": round(100 * wins / n, 2) if n else 0.0,
            "total_profit_usd": round(sum_profit_base / 1e6, 4),
            "avg_profit_per_cycle_usd": round(sum_profit_base / 1e6 / n, 6) if n else 0.0,
            "last_ts": last_ts,
            "today": {
                "n_cycles": n_today,
                "wins": wins_today,
                "total_profit_usd": round(sum_profit_today / 1e6, 4),
                "win_rate_pct": round(100 * wins_today / n_today, 2) if n_today else 0.0,
                "hours_elapsed": round(hours_today, 2),
                "rate_usd_per_hour": round((sum_profit_today / 1e6) / hours_today, 4) if hours_today > 0.01 else 0.0,
                "midnight_utc": time.strftime("%Y-%m-%dT00:00:00Z", now_t),
            },
        }

    def scan_v4(path: Path) -> dict:
        if not path.exists():
            return {"present": False, "n_ticks": 0}
        n = 0
        modes_count: dict[str, int] = {}
        v3_v4_disagree = 0
        v4_block_count = 0
        with open(path, errors="ignore") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    ts = rec.get("timestamp", "")
                    if not ts:
                        continue
                    ts_ms = parse_iso_ms(ts)
                    if ts_ms < cutoff_ms:
                        continue
                    n += 1
                    mode = rec.get("v4_mode", "?")
                    modes_count[mode] = modes_count.get(mode, 0) + 1
                    if rec.get("v3_v4_disagreement"):
                        v3_v4_disagree += 1
                    if not rec.get("v4_decision_allowed", True):
                        v4_block_count += 1
                except Exception:
                    continue
        return {
            "present": True,
            "n_ticks": n,
            "modes_count": modes_count,
            "v3_v4_disagreement_count": v3_v4_disagree,
            "v4_block_count": v4_block_count,
        }

    return {
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "period_hours": hours,
        "v3_cyclic_shadow": scan_v3(v3_path),
        "v4_observer": scan_v4(v4_path),
    }


def shadow_cache_refresh(hours: int = 24) -> dict:
    """Calcula shadow_summary y escribe a cache JSON para serving rápido."""
    summary = shadow_summary(hours=hours)
    summary["cached_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SHADOW_CACHE_FILE.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(summary, f, separators=(",", ":"))
    tmp.replace(SHADOW_CACHE_FILE)
    return summary


# ── Bot status (flags reales del .env Newark) ──

_bot_status_cache: dict[str, Any] = {"data": None, "ts": 0}

def bot_status_cached(ttl_s: int = 60) -> dict:
    now = time.time()
    if _bot_status_cache["data"] and (now - _bot_status_cache["ts"]) < ttl_s:
        return _bot_status_cache["data"]
    result = bot_status_fresh()
    _bot_status_cache["data"] = result
    _bot_status_cache["ts"] = now
    return result


def bot_status_fresh() -> dict:
    """SSH a Newark + grep flags del .env (sin imprimir contenido)."""
    import subprocess
    try:
        # Ejecuta grep en Newark, devuelve solo las líneas que matchean (puede contener sólo la flag, no demás secrets)
        cmd = (
            "ssh -i /home/administrator/.ssh/id_ed25519 -o BatchMode=yes -o ConnectTimeout=4 "
            "ubuntu@64.130.34.38 "
            "'grep -E \"^LIQ_CYCLIC_EXECUTE_LIVE=|^LIQ_KAMINO_DISABLE=\" /home/ubuntu/liquidator_rs/.env'"
        )
        out = subprocess.check_output(cmd, shell=True, timeout=8, stderr=subprocess.DEVNULL).decode().strip()
        flags = {}
        for line in out.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                flags[k.strip()] = v.strip()
        cyclic_live = flags.get("LIQ_CYCLIC_EXECUTE_LIVE", "").lower() == "true"
        kamino_off = flags.get("LIQ_KAMINO_DISABLE", "").lower() == "true"
        return {
            "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": True,
            "cyclic_live": cyclic_live,
            "kamino_disabled": kamino_off,
            "raw_flags": flags,
        }
    except Exception as e:
        return {
            "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "ok": False,
            "error": str(e),
        }


def shadow_cache_read() -> dict:
    """Lee cache instantáneo. Si no existe devuelve placeholder."""
    if not SHADOW_CACHE_FILE.exists():
        return {
            "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "cached_at": None,
            "v3_cyclic_shadow": {"present": False, "n_cycles": 0, "total_profit_usd": 0.0, "note": "cache aún no generado"},
            "v4_observer": {"present": False, "n_ticks": 0, "note": "cache aún no generado"},
        }
    try:
        with open(SHADOW_CACHE_FILE) as f:
            return json.load(f)
    except Exception as e:
        return {"error": f"cache read failed: {e}"}


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "balance"
    if cmd == "balance":
        print(json.dumps(all_balances(), indent=2))
    elif cmd == "snapshot":
        snap = take_snapshot()
        print(f"snapshot taken: total_usd=${snap['totals']['total_usd']}")
    elif cmd == "shadow":
        print(json.dumps(shadow_summary(int(sys.argv[2]) if len(sys.argv) > 2 else 24), indent=2))
    elif cmd == "shadow_cache":
        s = shadow_cache_refresh(int(sys.argv[2]) if len(sys.argv) > 2 else 24)
        v3 = s.get("v3_cyclic_shadow", {})
        print(f"shadow cache refreshed: cycles={v3.get('n_cycles', 0)} total_profit_usd=${v3.get('total_profit_usd', 0)}")
    else:
        print(f"unknown cmd: {cmd}")
        sys.exit(1)
