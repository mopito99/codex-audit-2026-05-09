"""Backtest τ retroactivo usando solo Polymarket history — sin BTC ni FRED deps.

Para cada contrato del set inicial:
  1. Descarga clob/prices-history con interval=1w fidelity=5 → ~2016 pts (7d × 24h × 60min / 5)
  2. Para cada punto t, computa τ_per_contract retroactivo:
       ΔProb_t  = (P_t − mean(P_{t-48..t})) / mean(P_{t-48..t})    # 4h baseline
       sigmoid(ΔProb, k=10, x0=0.10) → norm_dp
       (sin VolZScore: serie no incluye volume rolling)
       (sin ImpliedVol: serie no incluye spread por punto)
       τ_proxy = 0.5·norm_dp   (puro ΔProb, sin VolZ ni IV)
  3. Identifica spikes (τ_proxy > umbral)
  4. Reporta tabla: cuándo τ saltó, magnitud, contrato

Output: r84_backtest_polymarket_7d.md + json
"""
from __future__ import annotations
import datetime as dt
import json
import math
import statistics
import sys
import time
from pathlib import Path

import httpx

CALENDAR = Path("/home/administrator/poly_sidecar/macro_calendar.json")
OUT_MD = Path("/home/administrator/r84_backtest_polymarket_7d.md")
OUT_JSON = Path("/home/administrator/poly_sidecar/data/backtest_polymarket_7d.json")

CLOB = "https://clob.polymarket.com"


def sigmoid(x: float, k: float, x0: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-k * (x - x0)))
    except OverflowError:
        return 0.0 if (x - x0) < 0 else 1.0


def fetch_history(client: httpx.Client, token_id: str,
                  interval: str = "1w", fidelity: int = 5) -> list[tuple[int, float]]:
    """Returns [(unix_ms, price 0-1), ...] ascending."""
    try:
        r = client.get(f"{CLOB}/prices-history",
                      params={"market": token_id, "interval": interval,
                              "fidelity": fidelity}, timeout=15)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            return []
        out = []
        for pt in data.get("history", []):
            try:
                t_ms = int(pt["t"] * 1000)
                p = float(pt["p"])
                if 0 < p < 1:
                    out.append((t_ms, p))
            except (KeyError, ValueError, TypeError):
                continue
        return out
    except Exception as e:
        print(f"  ERROR fetch {token_id[:20]}: {e}")
        return []


def compute_delta_prob(prices: list[float], idx: int, lookback: int = 48) -> float | None:
    """ΔProb_t = (P_t − mean(P_{t-lookback..t})) / mean(P_{t-lookback..t})"""
    if idx < lookback:
        return None
    window = prices[max(0, idx - lookback):idx]
    if not window:
        return None
    mean_w = statistics.mean(window)
    if mean_w <= 0:
        return None
    return (prices[idx] - mean_w) / mean_w


def main():
    print("=" * 70)
    print("BACKTEST τ retroactivo — Polymarket prices-history 7d")
    print("=" * 70)

    cal = json.loads(CALENDAR.read_text())
    sigmoid_params = cal["sigmoid_params"]
    weights = cal["tau_formula"]["weights"]

    contracts = cal["polymarket_contracts_initial_set"]
    all_contracts = []
    for cat in ("macro", "crypto"):
        for c in contracts.get(cat, []):
            c2 = dict(c); c2["_category_group"] = cat
            all_contracts.append(c2)

    print(f"Contracts to backtest: {len(all_contracts)}")
    print()

    results: list[dict] = []
    summary_per_contract: list[dict] = []

    with httpx.Client() as client:
        for c in all_contracts:
            title = c.get("title", "")[:55]
            cat_group = c["_category_group"]
            cat = c.get("category", "?")
            tk = c["yes_token_id"]
            print(f"[{cat_group:6}] {cat:18} | {title}")
            print(f"  fetching history (interval=1w fidelity=5)...", end=" ")
            history = fetch_history(client, tk, "1w", 5)
            print(f"{len(history)} pts")
            time.sleep(0.5)
            if len(history) < 60:
                print(f"  insufficient data, skip")
                continue

            timestamps = [t for t, _ in history]
            prices = [p for _, p in history]

            # Compute τ_proxy per timestamp (only ΔProb component, since
            # spread/volume not in this series)
            tau_series = []
            dp_series = []
            for i in range(len(prices)):
                dp = compute_delta_prob(prices, i, lookback=48)
                if dp is None:
                    tau_series.append(None)
                    dp_series.append(None)
                    continue
                norm_dp = sigmoid(dp, sigmoid_params["delta_prob"]["k"],
                                  sigmoid_params["delta_prob"]["x0"])
                # τ_proxy si solo ΔProb existiera (peso 0.5)
                # → para representar mejor el dynamic range, dividimos por 0.5 (peso) → escala 0-1
                tau_series.append(round(norm_dp, 4))
                dp_series.append(round(dp, 4))

            valid_dp = [x for x in dp_series if x is not None]
            valid_tau = [x for x in tau_series if x is not None]
            if not valid_tau:
                continue

            spikes = sum(1 for t in valid_tau if t > 0.7)
            mid_to_high = sum(1 for t in valid_tau if 0.4 <= t <= 0.7)
            calm = sum(1 for t in valid_tau if t < 0.4)

            # Top 5 momentos donde τ_proxy más alto
            indexed = [(i, t) for i, t in enumerate(tau_series) if t is not None]
            indexed.sort(key=lambda x: x[1], reverse=True)
            top5 = []
            for idx, tau_val in indexed[:5]:
                top5.append({
                    "timestamp_utc": dt.datetime.fromtimestamp(
                        timestamps[idx]/1000, dt.timezone.utc).isoformat(),
                    "tau_proxy": tau_val,
                    "delta_prob": dp_series[idx],
                    "price_at_t": round(prices[idx], 4),
                })

            print(f"  τ_proxy distribution (n={len(valid_tau)}): "
                  f"spike >0.7: {spikes} ({spikes*100//len(valid_tau)}%), "
                  f"mid 0.4-0.7: {mid_to_high} ({mid_to_high*100//len(valid_tau)}%), "
                  f"calm <0.4: {calm} ({calm*100//len(valid_tau)}%)")
            print(f"  ΔProb stats: min={min(valid_dp):+.4f} max={max(valid_dp):+.4f} "
                  f"mean={statistics.mean(valid_dp):+.4f} std={statistics.pstdev(valid_dp):.4f}")
            print(f"  τ_proxy max = {max(valid_tau)}  ({top5[0]['timestamp_utc'][:16]} UTC)")
            print()

            summary_per_contract.append({
                "category_group": cat_group,
                "category": cat,
                "title": title,
                "market_id": c["market_id"],
                "n_samples": len(valid_tau),
                "tau_proxy_min": round(min(valid_tau), 4),
                "tau_proxy_max": round(max(valid_tau), 4),
                "tau_proxy_mean": round(statistics.mean(valid_tau), 4),
                "tau_proxy_std": round(statistics.pstdev(valid_tau), 4),
                "spikes_above_07_pct": round(spikes / len(valid_tau) * 100, 1),
                "mid_04_07_pct": round(mid_to_high / len(valid_tau) * 100, 1),
                "calm_below_04_pct": round(calm / len(valid_tau) * 100, 1),
                "delta_prob_min": round(min(valid_dp), 4),
                "delta_prob_max": round(max(valid_dp), 4),
                "delta_prob_std": round(statistics.pstdev(valid_dp), 4),
                "top5_spikes": top5,
            })

    # Save JSON
    output = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "method": "Polymarket prices-history 1w fidelity=5min, ΔProb sigmoid only",
        "sigmoid_params": sigmoid_params,
        "summary_per_contract": summary_per_contract,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(output, indent=2, default=str))
    print(f"\n📦 JSON detalle: {OUT_JSON}")

    # MD report
    md = ["# Backtest τ retroactivo — Polymarket history 7d\n"]
    md.append(f"_Generado {dt.datetime.now(dt.timezone.utc).isoformat()} UTC_\n")
    md.append("\n## Método\n")
    md.append("- Endpoint: `clob.polymarket.com/prices-history?interval=1w&fidelity=5`")
    md.append("- Series: ~2016 puntos por contrato (7 días × 24h × 12 pts/h)")
    md.append("- ΔProb_t = (P_t − mean(P_{t-48..t})) / mean(P_{t-48..t})  (baseline 4h)")
    md.append("- norm(ΔProb) = sigmoid(k=10, x0=0.10)")
    md.append("- τ_proxy = norm(ΔProb)  (sin VolZ ni IV — series no los expone)")
    md.append("\n## Resumen distribución τ por contrato\n")
    md.append("| Cat | Tipo | Mercado | N | τ min | τ max | τ media | τ std | %>0.7 (spike) | %0.4-0.7 (mid) | %<0.4 (calm) |")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for s in summary_per_contract:
        md.append(f"| {s['category_group']} | {s['category']} | {s['title']} | "
                 f"{s['n_samples']} | {s['tau_proxy_min']} | {s['tau_proxy_max']} | "
                 f"{s['tau_proxy_mean']} | {s['tau_proxy_std']} | "
                 f"{s['spikes_above_07_pct']}% | {s['mid_04_07_pct']}% | "
                 f"{s['calm_below_04_pct']}% |")

    md.append("\n## ΔProb stats (cambio relativo vs media 4h)\n")
    md.append("| Cat | Tipo | Mercado | ΔP min | ΔP max | ΔP std |")
    md.append("|---|---|---|---|---|---|")
    for s in summary_per_contract:
        md.append(f"| {s['category_group']} | {s['category']} | {s['title']} | "
                 f"{s['delta_prob_min']} | {s['delta_prob_max']} | {s['delta_prob_std']} |")

    md.append("\n## Top spikes por contrato (5 momentos τ más alto)\n")
    for s in summary_per_contract:
        md.append(f"\n### {s['category_group']} / {s['category']} — {s['title']}\n")
        md.append("| Timestamp UTC | τ_proxy | ΔProb | Price |")
        md.append("|---|---|---|---|")
        for spike in s["top5_spikes"]:
            md.append(f"| {spike['timestamp_utc'][:16]} | {spike['tau_proxy']} | "
                     f"{spike['delta_prob']} | {spike['price_at_t']} |")

    md.append("\n## Conclusiones\n")
    md.append("1. **Distribución τ saludable**: %spike <30% y %calm >50% indica que la fórmula")
    md.append("   no está sobre-reactiva. Si %spike > 50% → sigmoid params demasiado sensibles.")
    md.append("\n2. **ΔProb std**: si <0.02 → mercado plano (sigmoide rara vez activa).")
    md.append("   Si >0.20 → mercado volátil, sigmoide saturada.")
    md.append("\n3. **Top spikes timestamp**: cruzar con calendario macro publicado para ver")
    md.append("   si los picos de τ coinciden con releases NFP/CPI/FOMC. Si coincide → señal real.")
    md.append("   Si no coincide → ruido (puede ser whale trades en Polymarket sin macro driver).")

    OUT_MD.write_text("\n".join(md))
    print(f"📄 Report MD: {OUT_MD}")
    print()
    print("=" * 70)
    print("RESUMEN AGREGADO")
    print("=" * 70)
    for s in summary_per_contract:
        print(f"  [{s['category_group']:6}] {s['category']:18} | "
              f"τ μ={s['tau_proxy_mean']:.3f} σ={s['tau_proxy_std']:.3f} | "
              f"spike={s['spikes_above_07_pct']:5.1f}% calm={s['calm_below_04_pct']:5.1f}% | "
              f"{s['title'][:40]}")


if __name__ == "__main__":
    sys.exit(main())
