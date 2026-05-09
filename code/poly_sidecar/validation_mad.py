"""Validation simulation Z_old vs Z_new MAD — Entregable 4 firmado Gemma.

Para los últimos N releases macro, comparar:
  Z_old = (actual − previous) / σ_arithmetic
  Z_new = (actual − previous) / σ_robust_MAD

Cruzar con BTC reaction observada en T+5min usando CoinGecko (free tier
365d max). Si:
  - BTC reaction > 1% AND Z_old < trigger AND Z_new > trigger → "FIXED"
  - Z_new dispara en eventos flat → "OVER-SENSITIVE"

Output: r87_validation_mad_report.md con tabla auditable por Gemma.
"""
from __future__ import annotations
import datetime as dt
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

CALENDAR = Path("/home/administrator/poly_sidecar/macro_calendar.json")
OUT_MD = Path("/home/administrator/r87_validation_mad_report.md")
OUT_JSON = Path("/home/administrator/poly_sidecar/data/validation_mad.json")

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
FRED_KEY_FILE = Path("/home/administrator/.config/fred/api_key")
PYTH_HISTORIC = "https://hermes.pyth.network/v2/updates/price/{ts}"
BTC_FEED_ID = "0xe62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43"

EVENT_RELEASE_TIMES = {
    "NFP":   "12:30",
    "CPI":   "12:30",
    "PCE":   "12:30",
    "JOLTS": "14:00",
    "FOMC":  "18:00",
    "GDP":   "12:30",
    "UNEMPLOYMENT": "12:30",
    "RETAIL_SALES": "12:30",
}


def load_fred_key() -> str:
    return FRED_KEY_FILE.read_text().strip()


def fetch_fred_recent(client: httpx.Client, sid: str, key: str,
                     months: int = 6) -> list[dict]:
    today = dt.date.today()
    start = (today - dt.timedelta(days=months * 31)).isoformat()
    r = client.get(FRED_BASE, params={
        "series_id": sid,
        "api_key": key,
        "file_type": "json",
        "observation_start": start,
    }, timeout=20)
    r.raise_for_status()
    obs = []
    for o in r.json().get("observations", []):
        try:
            obs.append({"date": o["date"], "value": float(o["value"])})
        except (ValueError, KeyError):
            continue
    return obs


def compute_z(diff: float, sigma: float) -> float | None:
    if sigma is None or sigma <= 0:
        return None
    return diff / sigma


def fetch_btc_pyth(client: httpx.Client, ts_unix: int) -> float | None:
    """BTC/USD spot price at exact timestamp via Pyth Hermes historic.
    No auth, no rate limits typical. Returns None on error."""
    try:
        url = PYTH_HISTORIC.format(ts=ts_unix)
        r = client.get(url, params={
            "ids[]": BTC_FEED_ID,
            "parsed": "true",
            "encoding": "hex",
        }, timeout=15)
        r.raise_for_status()
        parsed = r.json().get("parsed", [])
        if not parsed:
            return None
        pd = parsed[0].get("price", {})
        raw = int(pd.get("price", 0))
        expo = int(pd.get("expo", 0))
        if raw <= 0:
            return None
        return raw * (10 ** expo)
    except Exception as e:
        print(f"  Pyth fetch ts={ts_unix} error: {e}")
        return None


def fetch_btc_around(client: httpx.Client, ts_unix: int,
                     window_min: int = 60) -> tuple[float | None, float | None]:
    """Returns (price_at_t0, price_at_t+5min) via Pyth Hermes historic."""
    p0 = fetch_btc_pyth(client, ts_unix)
    p5 = fetch_btc_pyth(client, ts_unix + 300)
    return p0, p5


def main():
    print("=" * 70)
    print("VALIDATION MAD — últimos releases macro")
    print("=" * 70)

    cal = json.loads(CALENDAR.read_text())
    fred_cal = cal.get("fred_calibration", {}).get("events", {})
    triggers = cal.get("trigger_sf_per_event", {})

    # Tomar los últimos 3-5 releases más recientes y RELEVANTES
    # (NFP April, CPI March/April, JOLTS March/April, etc.)
    target_categories = ["NFP", "CPI", "JOLTS", "PCE", "UNEMPLOYMENT", "RETAIL_SALES"]
    fred_key = load_fred_key()

    rows = []
    with httpx.Client() as client:
        for cat in target_categories:
            if cat not in fred_cal:
                continue
            info = fred_cal[cat]
            sid = info.get("fred_series_id")
            if not sid:
                continue
            audit = info.get("audit", {})
            sigma_arith = audit.get("sigma_arithmetic")
            sigma_robust = info.get("historical_surprise_sigma")
            trigger = triggers.get(cat, triggers.get("default", 1.0))
            calc = info.get("calculation", "delta_absolute")

            print(f"[{cat:14}] sid={sid} σ_arith={sigma_arith} σ_robust={sigma_robust} trigger={trigger}σ")

            obs = fetch_fred_recent(client, sid, fred_key, months=6)
            if len(obs) < 2:
                continue

            # Pick últimos 2 events (con histórico para cómputo)
            for i in range(max(1, len(obs) - 2), len(obs)):
                rel = obs[i]
                prev = obs[i - 1]
                # Compute diff per calc method
                if calc == "delta_absolute" or calc == "delta_points":
                    diff = rel["value"] - prev["value"]
                elif calc == "delta_bps":
                    diff = (rel["value"] - prev["value"]) * 100
                elif calc == "mom_pct" or calc == "qoq_pct":
                    diff = ((rel["value"] - prev["value"]) / prev["value"] * 100) if prev["value"] > 0 else 0
                elif calc == "yoy_pct":
                    if i < 12:
                        continue
                    p12 = obs[i - 12]["value"]
                    diff = ((rel["value"] - p12) / p12 * 100) if p12 > 0 else 0
                else:
                    diff = rel["value"] - prev["value"]

                z_old = compute_z(diff, sigma_arith)
                z_new = compute_z(diff, sigma_robust)

                # Construct timestamp for BTC fetch
                rel_time = EVENT_RELEASE_TIMES.get(cat, "12:30")
                try:
                    ts = dt.datetime.fromisoformat(f"{rel['date']}T{rel_time}:00+00:00")
                except Exception:
                    continue
                if ts > dt.datetime.now(dt.timezone.utc):
                    continue
                # Pyth Hermes historic — sin límite de 365d
                ts_unix = int(ts.timestamp())
                p0, p5 = fetch_btc_around(client, ts_unix, window_min=10)
                if p0 and p5 and p0 > 0:
                    btc_move_pct = (p5 - p0) / p0 * 100
                else:
                    btc_move_pct = None

                # Status logic
                hit_old = abs(z_old or 0) >= trigger
                hit_new = abs(z_new or 0) >= trigger
                btc_significant = btc_move_pct is not None and abs(btc_move_pct) > 1.0

                if btc_significant and not hit_old and hit_new:
                    status = "✓ FIXED (MAD recovered sensitivity)"
                elif not btc_significant and hit_new and not hit_old:
                    status = "⚠ OVER-SENSITIVE (MAD triggers in flat)"
                elif hit_new and hit_old:
                    status = "✓ Both triggered"
                elif not hit_new and not hit_old:
                    status = "○ Neither triggered (consistent)"
                else:
                    status = "? Mixed"

                rows.append({
                    "category": cat,
                    "date": rel["date"],
                    "actual": rel["value"],
                    "previous": prev["value"],
                    "diff": round(diff, 4),
                    "z_old": round(z_old, 4) if z_old is not None else None,
                    "z_new": round(z_new, 4) if z_new is not None else None,
                    "trigger_sf": trigger,
                    "z_old_hit": hit_old,
                    "z_new_hit": hit_new,
                    "btc_t0_price": round(p0, 2) if p0 else None,
                    "btc_t5_price": round(p5, 2) if p5 else None,
                    "btc_move_pct_t5": round(btc_move_pct, 4) if btc_move_pct is not None else None,
                    "status": status,
                })
                time.sleep(0.5)  # Pyth Hermes — más permisivo

    # Save JSON
    output = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "method": "Z_old (σ arithmetic) vs Z_new (σ MAD 1.4826) vs BTC T+5min reaction",
        "rows": rows,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(output, indent=2, default=str))
    print(f"\n📦 JSON: {OUT_JSON}")

    # MD report
    md = ["# Validation MAD — últimos releases macro\n"]
    md.append(f"_Generado {dt.datetime.now(dt.timezone.utc).isoformat()} UTC_\n")
    md.append("\n## Comparativa Z_old (σ aritmética) vs Z_new (σ MAD)\n")
    md.append("Para cada release reciente con BTC observable (CoinGecko 365d max), se calcula:\n")
    md.append("- Z_old = ΔActual / σ_arithmetic (envenenado por outliers)")
    md.append("- Z_new = ΔActual / (1.4826 × MAD) (robusto)")
    md.append("- BTC move T+5min: cambio % real BTC tras release")
    md.append("\n**Criterio FIXED:** BTC reaction > 1% AND Z_old < trigger AND Z_new > trigger")
    md.append("**Criterio OVER-SENSITIVE:** Z_new dispara en mercado plano (BTC < 1%)\n")
    md.append("\n| Categoría | Fecha | ΔActual | Z_old | Z_new | trigger | BTC T+5 | Status |")
    md.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        z_old_str = f"{r['z_old']:.3f}" if r['z_old'] is not None else "—"
        z_new_str = f"{r['z_new']:.3f}" if r['z_new'] is not None else "—"
        btc = f"{r['btc_move_pct_t5']:+.3f}%" if r['btc_move_pct_t5'] is not None else "n/a"
        md.append(f"| {r['category']} | {r['date']} | {r['diff']} | {z_old_str} | "
                 f"{z_new_str} | {r['trigger_sf']}σ | {btc} | {r['status']} |")

    md.append("\n## Resumen agregado\n")
    fixed = sum(1 for r in rows if "FIXED" in r["status"])
    over = sum(1 for r in rows if "OVER-SENSITIVE" in r["status"])
    consistent = sum(1 for r in rows if "Neither triggered" in r["status"] or "Both triggered" in r["status"])
    md.append(f"- ✓ FIXED (MAD recovered sensitivity): {fixed}")
    md.append(f"- ⚠ OVER-SENSITIVE: {over}")
    md.append(f"- ○ Consistent (both/neither): {consistent}")
    md.append(f"- Total events analizados: {len(rows)}\n")

    md.append("\n## Pregunta a Gemma\n")
    md.append("¿Z_new behavior nos da green light para empezar el wiring Rust mañana miércoles?")
    md.append("Si over-sensitivity en flat markets aparece → ¿ajustar 1.4826 o subir trigger_sf?\n")

    OUT_MD.write_text("\n".join(md))
    print(f"📄 MD report: {OUT_MD}")
    print()
    print("=" * 70)
    print("RESUMEN")
    print("=" * 70)
    for r in rows:
        z_old_str = f"{r['z_old']:.2f}" if r['z_old'] is not None else "—"
        z_new_str = f"{r['z_new']:.2f}" if r['z_new'] is not None else "—"
        btc = f"{r['btc_move_pct_t5']:+.2f}%" if r['btc_move_pct_t5'] is not None else "n/a"
        print(f"  [{r['category']:12}] {r['date']} ΔA={r['diff']:>8} Z_old={z_old_str:>6} "
              f"Z_new={z_new_str:>6} trig={r['trigger_sf']}σ BTC={btc:>8} | {r['status']}")


if __name__ == "__main__":
    sys.exit(main())
