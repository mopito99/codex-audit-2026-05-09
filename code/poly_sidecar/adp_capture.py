"""ADP capture script — 12:15 UTC release auto-capture.

Spec firmada Gemma r91+/r92/r93:
  - β_ADP_proxy = 0.18% per σ (50% del NFP β=0.32%)
  - σ_robust_NFP = 219,188 jobs (post-fix kurtosis)
  - SF_used = max(|sf_naive|, |sf_adjusted|) con β_revision=0.5
  - ADP cuenta como TIME burn-in, NO como STRESS test (firma r93 §5)
  - EXCEPCIÓN: si |SF| > 3σ outlier → re-clasifica como STRESS automatic

Captura:
  - actual + forecast + previous_revised desde Investing/FMP
  - BTC T+5/T+30/T+60min (post-decision capture window firmado r93 §3)
  - mode transitions sidecar
  - τ, ρ, mode_reason snapshots
  - audit format completo via cpi_audit_format.build_audit_report()

Uso:
  cron-style: ejecutar a las 12:14:30 UTC (30s antes del release)
  o on-demand: python3 adp_capture.py --execute-now
"""
from __future__ import annotations
import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import urllib.request

sys.path.insert(0, "/home/administrator/poly_sidecar")
from cpi_audit_format import build_audit_report, serialize_report, parse_value

ADP_RELEASE_TS = "2026-05-06T12:15:00Z"
SIDECAR_URL = "http://127.0.0.1:8090/api/state"
OUTPUT_DIR = Path("/home/administrator/poly_sidecar/data")


def _normalize_jobs(v: float | None) -> float | None:
    """Normaliza valores de empleo a JOBS ABSOLUTOS (no thousands).

    σ_robust_NFP en macro_calendar.json está en jobs absolutos (219,188).
    Algunos providers (FMP, Investing sin sufijo) reportan en thousands
    ("99.0" = 99,000 jobs). Sufijos K/M ya se manejan en parse_value(),
    pero números desnudos como "99.0" o "130" necesitan normalización.

    Heurística: si v < 10000 (probablemente thousands), multiplicar ×1000.
    Si v >= 10000, ya está en jobs absolutos.
    """
    if v is None:
        return None
    if 0 < v < 10000:
        return v * 1000.0
    return v


def fetch_sidecar_state() -> dict:
    """Read current sidecar state."""
    try:
        with urllib.request.urlopen(SIDECAR_URL, timeout=10) as r:
            return json.load(r)
    except Exception as e:
        return {"error": f"sidecar fetch failed: {e}"}


def find_adp_in_sidecar(state: dict) -> dict | None:
    """Buscar evento ADP recién publicado en investing.recent_releases_6h."""
    inv = state.get("investing", {})
    recent = inv.get("recent_releases_6h", [])
    for ev in recent:
        event_name = (ev.get("event") or "").upper()
        if "ADP" in event_name and ev.get("actual"):
            return ev
    return None


def find_adp_in_fmp_upcoming(state: dict) -> dict | None:
    """Buscar ADP en FMP upcoming (pre-release) para verificar forecast."""
    fmp = state.get("fmp", {})
    upcoming = fmp.get("upcoming_24h", [])
    for ev in upcoming:
        event_name = (ev.get("event") or "").upper()
        if "ADP" in event_name:
            return ev
    return None


async def capture_btc_at_offset(offset_minutes: int) -> dict:
    """Espera offset_minutes y captura BTC del sidecar."""
    await asyncio.sleep(offset_minutes * 60)
    state = fetch_sidecar_state()
    return {
        "offset_minutes": offset_minutes,
        "btc_price_usd": state.get("btc_price_usd"),
        "tau_final": state.get("tau_final"),
        "mode": state.get("mode"),
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
    }


async def post_event_capture_loop(
    btc_at_release: float,
    capture_offsets: list[int],
) -> list[dict]:
    """Spawn paralelo de captures a T+5/30/60min."""
    tasks = [capture_btc_at_offset(off) for off in capture_offsets]
    results = await asyncio.gather(*tasks)

    # Calcular % move
    for r in results:
        btc = r.get("btc_price_usd")
        if btc and btc_at_release:
            r["btc_move_pct"] = ((btc - btc_at_release) / btc_at_release) * 100
        else:
            r["btc_move_pct"] = None
    return results


def execute_capture_now() -> Path:
    """Ejecuta el capture inmediato (sin sleep). Para testing o si llegamos tarde."""
    print(f"[{datetime.now(timezone.utc).isoformat()}] ADP capture starting...")

    # Step 1: leer estado pre-release
    pre_state = fetch_sidecar_state()
    btc_pre_release = pre_state.get("btc_price_usd", 0)
    tau_pre = pre_state.get("tau_final", 0)
    mode_pre = pre_state.get("mode", "?")

    # Step 2: buscar ADP event en investing
    adp_event = find_adp_in_sidecar(pre_state)
    fmp_upcoming = find_adp_in_fmp_upcoming(pre_state)

    if adp_event:
        # ADP ya released — usar valores de Investing
        actual_str = str(adp_event.get("actual"))
        forecast_str = str(adp_event.get("forecast"))
        actual = parse_value(actual_str)
        forecast = parse_value(forecast_str)
        previous_str = str(adp_event.get("previous", ""))
        previous_original = parse_value(previous_str)
        # Normalización jobs (firma r93): si valor parece "thousands" (<10000),
        # multiplicar ×1000 para alinear con σ_robust en jobs absolutos.
        actual = _normalize_jobs(actual)
        forecast = _normalize_jobs(forecast)
        previous_original = _normalize_jobs(previous_original)
        source = "Investing.com"
        ts_received = adp_event.get("ts_utc", datetime.now(timezone.utc).isoformat())
        print(f"  ADP found in sidecar: actual={actual_str}→{actual}, forecast={forecast_str}→{forecast}")
    elif fmp_upcoming:
        # ADP aún no released — solo tenemos forecast
        forecast = parse_value(str(fmp_upcoming.get("estimate")))
        actual = None
        previous_original = parse_value(str(fmp_upcoming.get("previous")))
        forecast = _normalize_jobs(forecast)
        previous_original = _normalize_jobs(previous_original)
        source = "FMP upcoming (release pending)"
        ts_received = None
        print(f"  ADP upcoming: forecast={forecast}, previous={previous_original} (NOT YET RELEASED)")
    else:
        print("  ADP NOT FOUND in sidecar. Aborting capture.")
        return None

    if actual is None:
        print(f"  Cannot generate audit yet — actual not published. Will retry.")
        # Save partial state for later analysis
        partial = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "status": "ADP_NOT_RELEASED_YET",
            "forecast": forecast,
            "previous_original": previous_original,
            "btc_at_check": btc_pre_release,
            "tau_at_check": tau_pre,
            "mode_at_check": mode_pre,
        }
        path = OUTPUT_DIR / f"adp_partial_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        path.write_text(json.dumps(partial, indent=2))
        print(f"  Partial state saved: {path}")
        return path

    # Step 3: ADP released — build full audit report
    # NOTA: post_decision_observations se llenan después del sleep
    btc_response_initial = {
        "expected_beta_per_sigma": 0.18,  # firmado r91+ ADP_proxy
        "actual_btc_move_5min_pct": None,   # filled later
        "actual_btc_move_30min_pct": None,
        "actual_btc_move_60min_pct": None,
        "beta_observed": None,
        "beta_expected": 0.18,
        "match_within_tolerance": None,
    }

    macro_health = {
        "tau_final_at_release": tau_pre,
        "tau_final_max_during_window": tau_pre,  # se actualizará si llega más alto
        "rho_at_release": pre_state.get("rho"),
        "rho_min_during_window": pre_state.get("rho"),
        "stale_level_during_event": "L0" if not pre_state.get("endpoints_errors") else "L1+",
        "v3_v4_disagreement_count": 0,  # V3.5 stopped, no disagreement medible
        "v4_decision_allowed_pct": 100.0,
    }

    # Build audit
    report = build_audit_report(
        event="ADP",
        actual=actual,
        forecast=forecast or 99000,
        previous_original=previous_original or 62000,
        previous_revised=None,  # Si Investing tuviera revision, llenarlo aquí
        source_provider=source,
        release_ts_utc=ADP_RELEASE_TS,
        received_ts_utc=ts_received,
        p99_window_data={
            "window_start_utc": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "window_end_utc": datetime.now(timezone.utc).isoformat(),
            "scan_tick_duration_p99_ms": 0,  # V3.5 SHADOW stopped
            "scan_tick_duration_p95_ms": 0,
            "scan_tick_duration_p50_ms": 0,
            "back_pressure_drops_count": 0,
            "stream_reconnect_events": 0,
            "slot_lag_p95": 0,
            "n_samples": 0,
            "verdict_per_criteria": {},
        },
        mode_transitions=[],  # V3.5 stopped, no transitions to log here
        btc_response_data=btc_response_initial,
        macro_health_data=macro_health,
        burn_in_hours=0.0,  # V3.5 stopped → 0 burn-in oficial
        nfp_passed=False,
        cpi_passed=False,
    )

    # Determinar si SF outlier (firma r93 §5: |SF|>3σ → re-clasifica STRESS)
    abs_sf = abs(report.sf_calculation.sf_used_for_decision)
    if abs_sf > 3.0:
        print(f"  ⚠️ SF={report.sf_calculation.sf_used_for_decision:.4f} > 3σ → OUTLIER")
        print(f"     Per firma Gemma r93 §5: re-clasificar como STRESS test (no solo TIME)")

    # Save initial report
    json_path, md_path = serialize_report(report, OUTPUT_DIR)
    print(f"  ✓ Initial audit JSON: {json_path}")
    print(f"  ✓ Initial audit MD:   {md_path}")
    print(f"  SF naive: {report.sf_calculation.sf_naive:.4f}")
    print(f"  SF adjusted: {report.sf_calculation.sf_adjusted:.4f}")
    print(f"  SF used: {report.sf_calculation.sf_used_for_decision:.4f}")
    return json_path


async def execute_with_post_capture():
    """Full execution: capture + post-event T+5/30/60min observations."""
    initial_path = execute_capture_now()
    if initial_path is None:
        print("Capture aborted — no actual data yet.")
        return

    # Capture BTC pre-release for delta calculation
    pre_state = fetch_sidecar_state()
    btc_at_release = pre_state.get("btc_price_usd")

    print(f"\n[{datetime.now(timezone.utc).isoformat()}] Starting post-event capture loop")
    print(f"  BTC at release: ${btc_at_release:,.2f}")
    print(f"  Will capture at T+5min, T+30min, T+60min")

    # Background capture
    captures = await post_event_capture_loop(btc_at_release, [5, 30, 60])

    # Update audit JSON with post-decision observations
    if initial_path and initial_path.exists():
        report_data = json.loads(initial_path.read_text())
        btc_obs = {
            f"actual_btc_move_{c['offset_minutes']}min_pct": round(c["btc_move_pct"], 4) if c["btc_move_pct"] is not None else None
            for c in captures
        }
        # Init key if not present (e.g. partial state save before NFP/CPI)
        report_data.setdefault("btc_response_validation", {}).update(btc_obs)

        # Calcular β_observed (5min como proxy más cercano al evento)
        sf_used = report_data["sf_calculation"]["sf_used_for_decision"]
        btc_5min = btc_obs.get("actual_btc_move_5min_pct")
        if sf_used and abs(sf_used) > 0.001 and btc_5min is not None:
            beta_obs = btc_5min / sf_used
            report_data["btc_response_validation"]["beta_observed"] = round(beta_obs, 4)

            # Tolerance check (firmado r92 SOFT warning)
            beta_exp = 0.18
            tolerance_pct = 30.0
            if beta_exp != 0:
                delta_pct = abs(beta_obs - beta_exp) / abs(beta_exp) * 100
                report_data["btc_response_validation"]["match_within_tolerance"] = delta_pct <= tolerance_pct

        # Append captures detail
        report_data["post_event_captures"] = captures

        initial_path.write_text(json.dumps(report_data, indent=2))
        print(f"  ✓ Updated audit with post-event observations: {initial_path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--execute-now", action="store_true", help="Capture immediately (no scheduling)")
    p.add_argument("--with-post-capture", action="store_true", help="Include T+5/30/60 BTC observations (long-running)")
    p.add_argument("--check-only", action="store_true", help="Just check sidecar state for ADP, no capture")
    args = p.parse_args()

    if args.check_only:
        state = fetch_sidecar_state()
        adp = find_adp_in_sidecar(state)
        upcoming = find_adp_in_fmp_upcoming(state)
        print("=== Pre-release check ===")
        print(f"  Sidecar mode: {state.get('mode')}")
        print(f"  BTC: ${state.get('btc_price_usd', 0):,.2f}")
        print(f"  ADP in investing.recent_6h: {bool(adp)}")
        if adp:
            print(f"    actual: {adp.get('actual')}, forecast: {adp.get('forecast')}, SF: {adp.get('surprise_factor')}")
        print(f"  ADP in fmp.upcoming_24h: {bool(upcoming)}")
        if upcoming:
            print(f"    forecast: {upcoming.get('estimate')}, prev: {upcoming.get('previous')}")
        return

    if args.with_post_capture:
        asyncio.run(execute_with_post_capture())
    elif args.execute_now:
        execute_capture_now()
    else:
        print("Use --check-only or --execute-now or --with-post-capture")


if __name__ == "__main__":
    main()
