"""Calcula stats por ventana horaria UTC del cyclic_shadow.jsonl + V4 macro.
Se ejecuta en Newark vía SSH con nice/ionice mínimos para no impactar al bot.
Usa grep nativo + lee solo el tail del jsonl (~día actual) para minimizar I/O.

V3 (cyclic_shadow.jsonl): events del bot V3.5 SHADOW.
V4 (cyclic_shadow_v4.jsonl): macro layer observer (mode, τ, ρ, decisions)."""
import json
import sys
import statistics as s
import subprocess
from datetime import datetime, timezone
from collections import Counter

JSONL = "/home/ubuntu/liquidator_rs/data/cyclic_shadow.jsonl"
JSONL_V4 = "/home/ubuntu/liquidator_rs/data/cyclic_shadow_v4.jsonl"

WINDOWS = [
    ("00-08 Asia",         0,  7),
    ("08-13 Londres solo", 8, 12),
    ("13-16 LDN x NY",    13, 15),
    ("16-21 NY post-LDN", 16, 20),
    ("21-24 cierre",      21, 23),
]

# El bot escribe ~5 evts/seg → ~432k evts/día. tail 600k líneas cubre el día
# con margen y limita el read a ~250 MB en lugar de los 600+ MB totales.
TAIL_LINES = 600_000


def fast_filter(date_str: str):
    """Devuelve un iterable de líneas con timestamp del día. Usa tail|grep nativos."""
    cmd = (
        f"tail -n {TAIL_LINES} {JSONL} | "
        f"grep -F '\"timestamp\":\"{date_str}'"
    )
    p = subprocess.Popen(
        ["bash", "-c", cmd],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        bufsize=1
    )
    for line in p.stdout:
        yield line
    p.wait()


def main(date_str: str):
    stats = {label: {
        "label": label, "h_start": sh, "h_end": eh,
        "events": 0, "would_send": 0, "cb_blocked": 0, "depeg_blocked": 0,
        "max_profit_usd": 0.0, "sum_profit_usd": 0.0,
        "latencies_ms": [], "slot_lags": [],
    } for label, sh, eh in WINDOWS}

    try:
        for line in fast_filter(date_str):
            try:
                d = json.loads(line)
            except Exception:
                continue
            ts = d.get("timestamp", "")
            if not ts.startswith(date_str):
                continue
            hh = int(ts[11:13])
            for label, sh, eh in WINDOWS:
                if sh <= hh <= eh:
                    st = stats[label]
                    st["events"] += 1
                    if d.get("would_send"):
                        st["would_send"] += 1
                    if d.get("cb_blocked"):
                        st["cb_blocked"] += 1
                    if d.get("depeg_blocked"):
                        st["depeg_blocked"] += 1
                    p = d.get("net_profit_usd", 0.0) or 0.0
                    if p > st["max_profit_usd"]:
                        st["max_profit_usd"] = p
                    st["sum_profit_usd"] += p
                    st["latencies_ms"].append(d.get("latency_ms", 0) or 0)
                    st["slot_lags"].append(d.get("slot_lag", 0) or 0)
                    break
    except FileNotFoundError:
        print(json.dumps({"error": f"jsonl not found: {JSONL}"}))
        return

    out = []
    for label, sh, eh in WINDOWS:
        st = stats[label]
        if st["events"] == 0:
            out.append({
                "label": label, "h_start": sh, "h_end": eh,
                "events": 0, "would_send": 0, "cb_blocked": 0,
                "would_send_pct": None,
                "max_profit_usd": 0.0, "sum_profit_usd": 0.0,
                "lat_p50_ms": None, "lat_p99_ms": None, "slot_lag_max": None,
            })
            continue
        lat = st["latencies_ms"]
        lag = st["slot_lags"]
        p99_idx = min(int(len(lat) * 0.99), len(lat) - 1)
        out.append({
            "label": label, "h_start": sh, "h_end": eh,
            "events": st["events"],
            "would_send": st["would_send"],
            "cb_blocked": st["cb_blocked"],
            "depeg_blocked": st["depeg_blocked"],
            "would_send_pct": round(100 * st["would_send"] / st["events"], 2),
            "max_profit_usd": round(st["max_profit_usd"], 6),
            "sum_profit_usd": round(st["sum_profit_usd"], 4),
            "lat_p50_ms": int(s.median(lat)),
            "lat_p99_ms": int(sorted(lat)[p99_idx]),
            "slot_lag_max": max(lag),
        })

    # V4 macro stats (si V4 observer está corriendo y el archivo existe)
    v4_stats = compute_v4_stats(date_str)

    print(json.dumps({
        "date_utc": date_str,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "now_hour_utc": datetime.now(timezone.utc).hour,
        "windows": out,
        "v4_macro": v4_stats,
    }))


def compute_v4_stats(date_str: str) -> dict:
    """Stats del cyclic_shadow_v4.jsonl. Devuelve dict con resumen del día.

    Si el archivo no existe (V4 observer no corriendo todavía), devuelve
    {"available": false, "reason": "..."}.
    """
    import os
    if not os.path.exists(JSONL_V4):
        return {"available": False, "reason": f"file not found: {JSONL_V4}"}

    # V4 escribe ~1 line/s = ~86,400 lines/día. tail 100k cubre cómodamente.
    cmd = (
        f"tail -n 100000 {JSONL_V4} | "
        f"grep -F '\"timestamp\":\"{date_str}'"
    )
    p = subprocess.Popen(
        ["bash", "-c", cmd],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        bufsize=1
    )

    n = 0
    mode_counter = Counter()
    block_reason_counter = Counter()
    tau_finals = []
    tau_cryptos = []
    tau_macros = []
    rhos = []
    rho_divergence_count = 0
    is_warmup_count = 0
    is_stale_count = 0
    decision_allowed_count = 0
    v3_v4_disagreement_count = 0
    v3_would_send_count = 0
    sidecar_errors_max = 0
    btc_prices = []

    try:
        for line in p.stdout:
            try:
                d = json.loads(line)
            except Exception:
                continue
            ts = d.get("timestamp", "")
            if not ts.startswith(date_str):
                continue
            n += 1
            mode_counter[d.get("v4_mode", "Unknown")] += 1
            br = d.get("v4_block_reason")
            if br:
                block_reason_counter[br] += 1
            t_final = d.get("v4_tau_final")
            if isinstance(t_final, (int, float)):
                tau_finals.append(t_final)
            t_crypto = d.get("v4_tau_crypto")
            if isinstance(t_crypto, (int, float)):
                tau_cryptos.append(t_crypto)
            t_macro = d.get("v4_tau_macro")
            if isinstance(t_macro, (int, float)):
                tau_macros.append(t_macro)
            rho = d.get("v4_rho")
            if isinstance(rho, (int, float)):
                rhos.append(rho)
            if d.get("v4_rho_divergence_active"):
                rho_divergence_count += 1
            if d.get("v4_is_warmup"):
                is_warmup_count += 1
            if d.get("v4_is_stale"):
                is_stale_count += 1
            if d.get("v4_decision_allowed"):
                decision_allowed_count += 1
            if d.get("v3_v4_disagreement"):
                v3_v4_disagreement_count += 1
            if d.get("v3_would_send"):
                v3_would_send_count += 1
            err = d.get("v4_sidecar_error_count", 0) or 0
            if err > sidecar_errors_max:
                sidecar_errors_max = err
            btc = d.get("v4_btc_price_usd")
            if isinstance(btc, (int, float)) and btc > 0:
                btc_prices.append(btc)
        p.wait()
    except Exception as e:
        return {"available": True, "n_records": n, "error_during_parse": str(e)[:200]}

    if n == 0:
        return {"available": True, "n_records": 0, "reason": "no records for date"}

    def pct(c):
        return round(100 * c / n, 2)

    def percentile(sorted_list, q):
        if not sorted_list:
            return None
        idx = min(int(len(sorted_list) * q), len(sorted_list) - 1)
        return sorted_list[idx]

    tau_finals_sorted = sorted(tau_finals)
    rhos_sorted = sorted(rhos)
    btc_sorted = sorted(btc_prices)

    return {
        "available": True,
        "n_records": n,
        "mode_distribution": dict(mode_counter.most_common()),
        "mode_distribution_pct": {k: pct(v) for k, v in mode_counter.most_common()},
        "block_reasons": dict(block_reason_counter.most_common()),
        "tau_final_p10": round(percentile(tau_finals_sorted, 0.10) or 0, 4) if tau_finals_sorted else None,
        "tau_final_p50": round(percentile(tau_finals_sorted, 0.50) or 0, 4) if tau_finals_sorted else None,
        "tau_final_p90": round(percentile(tau_finals_sorted, 0.90) or 0, 4) if tau_finals_sorted else None,
        "tau_final_max": round(max(tau_finals), 4) if tau_finals else None,
        "tau_crypto_avg": round(s.mean(tau_cryptos), 4) if tau_cryptos else None,
        "tau_macro_avg": round(s.mean(tau_macros), 4) if tau_macros else None,
        "rho_p10": round(percentile(rhos_sorted, 0.10) or 0, 4) if rhos_sorted else None,
        "rho_p50": round(percentile(rhos_sorted, 0.50) or 0, 4) if rhos_sorted else None,
        "rho_p90": round(percentile(rhos_sorted, 0.90) or 0, 4) if rhos_sorted else None,
        "rho_min": round(min(rhos), 4) if rhos else None,
        "rho_divergence_active_count": rho_divergence_count,
        "rho_divergence_pct": pct(rho_divergence_count),
        "is_warmup_pct": pct(is_warmup_count),
        "is_stale_pct": pct(is_stale_count),
        "decision_allowed_pct": pct(decision_allowed_count),
        "v3_v4_disagreement_count": v3_v4_disagreement_count,
        "v3_v4_disagreement_pct": pct(v3_v4_disagreement_count),
        "v3_would_send_total": v3_would_send_count,
        "sidecar_error_count_max": sidecar_errors_max,
        "btc_price_min": round(min(btc_prices), 2) if btc_prices else None,
        "btc_price_max": round(max(btc_prices), 2) if btc_prices else None,
        "btc_price_p50": round(percentile(btc_sorted, 0.50) or 0, 2) if btc_sorted else None,
    }


if __name__ == "__main__":
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    main(date_str)
