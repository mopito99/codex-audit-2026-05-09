"""Backtest histórico macro — valida spec Gemma V4-Alpha §4.7.

Para cada release de NFP/CPI/FOMC/PCE/JOLTS de los últimos N meses:
  1. Saca fecha del FRED + horario fijo conocido del release
  2. Calcula SF = (actual − previous) / σ_FRED   ← ya calibrado 12y
  3. Descarga BTC velas 5m de Binance ±2h alrededor del evento
  4. Mide move BTC: T-30min / T+5min / T+30min
  5. Compara contra spec Gemma:
       pre-event vol drop 20-40%
       spike T0-T+5 mean 1.2% std 0.8%
       P(>2σ) ≈ 15-20%
       repricing T+5-T+30 mean reversion 30-50%
  6. Output: tabla MD + JSON

Sin auth Binance (klines públicos).
"""
from __future__ import annotations
import datetime as dt
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx

CALENDAR = Path("/home/administrator/poly_sidecar/macro_calendar.json")
OUT_MD = Path("/home/administrator/r83_backtest_macro_24m.md")
OUT_JSON = Path("/home/administrator/poly_sidecar/data/backtest_macro_24m.json")

# Horarios fijos UTC de releases (estándar US BLS / Fed)
EVENT_RELEASE_TIMES = {
    "NFP":   "12:30",   # First Friday of month
    "CPI":   "12:30",   # mid-month
    "PCE":   "12:30",   # last Friday of month
    "JOLTS": "14:00",   # First Tuesday of month
    "FOMC":  "18:00",   # FOMC meeting day
    "GDP":   "12:30",
    "UNEMPLOYMENT": "12:30",
    "RETAIL_SALES": "12:30",
}

COINGECKO_RANGE = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart/range"
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
KEY_FILE = Path("/home/administrator/.config/fred/api_key")


def load_fred_key() -> str:
    return KEY_FILE.read_text().strip()


def fetch_fred_recent(client: httpx.Client, series_id: str, key: str,
                     months: int = 12) -> list[dict]:
    """Returns observations of last N months. Limited to 12m by CoinGecko
    free tier (365 days historical max for klines)."""
    today = dt.date.today()
    # +2 months buffer for FRED YoY calc lag
    start = (today - dt.timedelta(days=(months + 2) * 31)).isoformat()
    r = client.get(FRED_BASE, params={
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
        "observation_start": start,
    }, timeout=20)
    r.raise_for_status()
    obs = []
    for o in r.json().get("observations", []):
        try:
            v = float(o["value"])
            obs.append({"date": o["date"], "value": v})
        except (ValueError, KeyError):
            continue
    return obs


def fetch_btc_klines(client: httpx.Client, ts_center_unix: int,
                     window_min: int = 120) -> list[dict]:
    """BTC prices via CoinGecko market_chart/range.
    For ranges <24h CoinGecko returns ~5min resolution automatically."""
    start = ts_center_unix - window_min * 60
    end = ts_center_unix + window_min * 60
    try:
        r = client.get(COINGECKO_RANGE, params={
            "vs_currency": "usd",
            "from": start,
            "to": end,
        }, timeout=15)
        r.raise_for_status()
        data = r.json()
        out = []
        for ts_ms, price in data.get("prices", []):
            out.append({
                "ts_ms": int(ts_ms),
                "ts_unix": int(ts_ms) // 1000,
                "close": float(price),
                "open": float(price),
                "high": float(price),
                "low": float(price),
                "volume": 0,
            })
        return out
    except Exception as e:
        return []


def compute_move_at_offset(klines: list[dict], ts_center: int,
                           offset_min: int) -> float | None:
    """Returns BTC % change between t=center and t=center+offset_min."""
    if not klines:
        return None
    target_t = ts_center + offset_min * 60
    # find closest kline at center and at target
    def closest(ts):
        return min(klines, key=lambda k: abs(k["ts_unix"] - ts))
    k0 = closest(ts_center)
    k1 = closest(target_t)
    if k0["close"] <= 0:
        return None
    return (k1["close"] - k0["close"]) / k0["close"] * 100.0


def main():
    print("=" * 70)
    print("BACKTEST MACRO 24m — Validación spec Gemma V4-Alpha §4.7")
    print("=" * 70)

    cal = json.loads(CALENDAR.read_text())
    fred_cal = cal.get("fred_calibration", {}).get("events", {})
    sigmas = {cat: info.get("historical_surprise_sigma")
              for cat, info in fred_cal.items()}
    sids = {cat: info.get("fred_series_id")
            for cat, info in fred_cal.items()
            if info.get("fred_series_id")}
    print(f"σ_FRED loaded: {len(sigmas)} categories")
    print(f"Series IDs: {len(sids)}")
    print()

    fred_key = load_fred_key()

    results: dict[str, list] = {}
    summary: dict[str, dict] = {}

    with httpx.Client() as client:
        for cat, sid in sids.items():
            release_time = EVENT_RELEASE_TIMES.get(cat)
            if not release_time:
                print(f"[{cat:15}] no release time defined — skip")
                continue
            print(f"[{cat:15}] {sid} — fetching FRED 24m...", end=" ")
            obs = fetch_fred_recent(client, sid, fred_key, months=24)
            print(f"{len(obs)} releases")
            if len(obs) < 2:
                continue

            sigma = sigmas.get(cat) or 1.0
            cat_results = []
            for i in range(1, len(obs)):
                rel = obs[i]
                prev = obs[i - 1]
                # Build release timestamp (date + fixed UTC time)
                try:
                    ts = dt.datetime.fromisoformat(f"{rel['date']}T{release_time}:00+00:00")
                except Exception:
                    continue
                # Skip futures
                if ts > dt.datetime.now(dt.timezone.utc):
                    continue
                # Skip very recent (Binance might not have full window yet)
                if (dt.datetime.now(dt.timezone.utc) - ts).total_seconds() < 7200:
                    continue

                ts_unix = int(ts.timestamp())
                actual = rel["value"]
                previous = prev["value"]
                # SF cálculo según calculation type del FRED calibration
                calc = fred_cal[cat].get("calculation", "delta_absolute")
                if calc == "delta_absolute" or calc == "delta_points":
                    diff = actual - previous
                elif calc == "delta_bps":
                    diff = (actual - previous) * 100.0
                elif calc == "mom_pct" or calc == "qoq_pct":
                    diff = ((actual - previous) / previous * 100.0) if previous > 0 else 0
                elif calc == "yoy_pct":
                    # YoY needs 12 lag, only on >12 obs
                    if i < 12:
                        continue
                    prev12 = obs[i - 12]["value"]
                    diff = ((actual - prev12) / prev12 * 100.0) if prev12 > 0 else 0
                else:
                    diff = actual - previous

                sf = diff / sigma if sigma > 0 else None

                # BTC klines ±2h
                klines = fetch_btc_klines(client, ts_unix, window_min=120)
                if not klines:
                    print(f"  · {rel['date']} {cat}: no BTC klines, skip")
                    continue
                m_neg30 = compute_move_at_offset(klines, ts_unix, -30)
                m_pos5 = compute_move_at_offset(klines, ts_unix, 5)
                m_pos30 = compute_move_at_offset(klines, ts_unix, 30)

                cat_results.append({
                    "date": rel["date"],
                    "ts_utc": ts.isoformat(),
                    "actual": actual,
                    "previous": previous,
                    "diff": round(diff, 4),
                    "surprise_factor": round(sf, 4) if sf is not None else None,
                    "abs_sf": abs(sf) if sf is not None else None,
                    "btc_move_neg30min_pct": round(m_neg30, 4) if m_neg30 is not None else None,
                    "btc_move_pos5min_pct": round(m_pos5, 4) if m_pos5 is not None else None,
                    "btc_move_pos30min_pct": round(m_pos30, 4) if m_pos30 is not None else None,
                })
                # CoinGecko free tier: 30 calls/min → sleep 2.5s between calls
                time.sleep(2.5)

            if cat_results:
                results[cat] = cat_results
                # summary stats
                pos5_moves = [abs(r["btc_move_pos5min_pct"])
                              for r in cat_results
                              if r["btc_move_pos5min_pct"] is not None]
                if pos5_moves:
                    summary[cat] = {
                        "n_events": len(cat_results),
                        "btc_pos5_mean_abs_pct": round(statistics.mean(pos5_moves), 4),
                        "btc_pos5_std_pct": round(statistics.pstdev(pos5_moves), 4)
                            if len(pos5_moves) > 1 else 0,
                        "events_with_sf_above_1sigma": sum(
                            1 for r in cat_results
                            if r.get("abs_sf") is not None and r["abs_sf"] > 1.0
                        ),
                        "events_with_btc_move_above_2pct": sum(
                            1 for r in cat_results
                            if r.get("btc_move_pos5min_pct") is not None
                               and abs(r["btc_move_pos5min_pct"]) > 2.0
                        ),
                    }

    # Save JSON
    output = {
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "summary_by_category": summary,
        "details_by_category": results,
        "sigma_fred_used": sigmas,
        "spec_gemma_v4alpha_§47": {
            "spike_T0_to_T5_mean_pct": 1.2,
            "spike_T0_to_T5_std_pct": 0.8,
            "p_move_above_2sigma": "15-20%",
        },
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(output, indent=2, default=str))
    print(f"\n📦 JSON detalle guardado: {OUT_JSON}")

    # Build MD report
    md = ["# Backtest Macro 24m — Validación spec Gemma V4-Alpha §4.7\n"]
    md.append(f"_Generado {dt.datetime.now(dt.timezone.utc).isoformat()} UTC_\n")
    md.append("\n## Resumen por categoría\n")
    md.append("| Cat | N events | BTC \\|move\\| @+5min mean | std | events |SF|>1σ | events \\|BTC\\|>2% |")
    md.append("|---|---|---|---|---|---|")
    for cat, s in summary.items():
        md.append(
            f"| {cat} | {s['n_events']} | {s['btc_pos5_mean_abs_pct']:.4f}% | "
            f"{s['btc_pos5_std_pct']:.4f}% | {s['events_with_sf_above_1sigma']} | "
            f"{s['events_with_btc_move_above_2pct']} |"
        )

    md.append("\n## Comparación vs spec Gemma\n")
    md.append("**Spec Gemma V4-Alpha §4.7:** mean 1.2%, std 0.8%, P(>2σ)≈15-20%\n")
    md.append("\n| Cat | Spec mean | Real mean | Diff | Spec P(>2σ) | Real P(>2σ) |")
    md.append("|---|---|---|---|---|---|")
    spec_mean = 1.2
    for cat, s in summary.items():
        real_mean = s['btc_pos5_mean_abs_pct']
        diff = real_mean - spec_mean
        diff_str = f"{diff:+.2f}pp"
        n = s['n_events']
        p_2pct = s['events_with_btc_move_above_2pct'] / n * 100 if n > 0 else 0
        md.append(
            f"| {cat} | 1.2% | {real_mean:.2f}% | {diff_str} | "
            f"15-20% | {p_2pct:.0f}% |"
        )

    md.append("\n## Detalle por categoría (top eventos por |SF|)\n")
    for cat, rows in results.items():
        md.append(f"\n### {cat}  (n={len(rows)})\n")
        rows_sorted = sorted(rows, key=lambda r: (r.get("abs_sf") or 0), reverse=True)[:10]
        md.append("| date | actual | prev | diff | SF | BTC -30min | BTC +5min | BTC +30min |")
        md.append("|---|---|---|---|---|---|---|---|")
        for r in rows_sorted:
            md.append(
                f"| {r['date']} | {r['actual']} | {r['previous']} | "
                f"{r['diff']} | {r['surprise_factor']} | "
                f"{r['btc_move_neg30min_pct']}% | {r['btc_move_pos5min_pct']}% | "
                f"{r['btc_move_pos30min_pct']}% |"
            )

    md.append("\n---\n")
    md.append("## Conclusiones operativas\n")
    md.append("1. **σ_FRED defaults vs reales:** revisar cuántos eventos cruzaron |SF|>1σ.")
    md.append("   Si la frecuencia es <5% → σ_FRED demasiado alto, bot nunca reaccionaría.")
    md.append("   Si la frecuencia es >40% → σ_FRED demasiado bajo, demasiada reactividad.")
    md.append("\n2. **Validación spec Gemma BTC mean 1.2% std 0.8%:** comparar vs columna real.")
    md.append("   Categorías con mean < 0.5% → evento sobre-estimado. >2% → sub-estimado.")
    md.append("\n3. **Cobertura outliers:** NFP σ=1807k incluye COVID-19. Para los 24m post-2023")
    md.append("   probablemente el shock real está mucho más bajo que σ permite reaccionar.")

    OUT_MD.write_text("\n".join(md))
    print(f"📄 Report MD guardado: {OUT_MD}")
    print()
    print("=" * 70)
    print("RESUMEN")
    print("=" * 70)
    for cat, s in summary.items():
        n = s["n_events"]
        sf_hits = s["events_with_sf_above_1sigma"]
        sf_pct = sf_hits / n * 100 if n else 0
        big_btc = s["events_with_btc_move_above_2pct"]
        big_pct = big_btc / n * 100 if n else 0
        print(
            f"  {cat:14} n={n:3}  "
            f"|SF|>1σ: {sf_hits}/{n} ({sf_pct:.0f}%)  "
            f"|BTC|>2%: {big_btc}/{n} ({big_pct:.0f}%)  "
            f"BTC mean={s['btc_pos5_mean_abs_pct']:.2f}%"
        )


if __name__ == "__main__":
    sys.exit(main())
