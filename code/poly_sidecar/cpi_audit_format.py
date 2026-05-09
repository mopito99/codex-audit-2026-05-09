"""CPI Audit Report — formato firmado Gemma r92 (2026-05-06).

Genera el JSON audit report post-CPI Lun 12 que se usa para autorizar
LIVE EXECUTE. 8 secciones + 8 criterios HARD pass. β_observed es SOFT
(warning, no bloquea LIVE). source_provider añadido per firma r92.

Schema:
  - event_metadata (incluye source_provider)
  - sf_calculation (naive + adjusted con revision, max() decision)
  - mode_transitions_during_event
  - p99_audit_window (criterios HARD)
  - btc_response_validation (β SOFT)
  - macro_layer_health_during_event
  - burn_in_total_hours_completed
  - verdict (8 criterios AND para LIVE auth)

Use:
  python3 cpi_audit_format.py --event CPI --release-ts 2026-05-12T12:30:00Z

Output:
  - JSON: /home/administrator/poly_sidecar/data/audit_CPI_<ts>.json
  - MD : /home/administrator/poly_sidecar/data/audit_CPI_<ts>.md (human-readable)
"""
from __future__ import annotations
import argparse
import json
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Spec firmada Gemma r91+/r92 — constants ───────────────────────────
P99_HARD_THRESHOLD_MS = 8000           # criterio HARD pass (firmado r91+)
P99_TARGET_MS = 5000                   # objetivo final (firmado r91+)
SLOT_LAG_P95_MAX = 10                  # criterio HARD pass
BACK_PRESSURE_DROPS_MAX = 0            # criterio HARD pass
STREAM_RECONNECTS_MAX = 0              # criterio HARD pass
BURN_IN_MIN_HOURS = 72                 # criterio HARD pass

# σ_robust FRED kurtosis-adjusted (post-fix r100/r92)
SIGMA_FRED = {
    "CPI": 0.243,        # CPI YoY % (κ-adjusted)
    "NFP": 219188,       # NFP jobs absolutos (κ-adjusted)
    "FOMC": 2.10,        # FOMC FFR bps (κ-adjusted)
    "PCE": 0.142,        # PCE YoY % (κ-adjusted)
    "GDP": 0.326,        # GDP QoQ %
    "ISM": 1.12,         # ISM points
    "JOLTS": 360272,     # JOLTS jobs absolutos (post unit-fix)
    "UNEMPLOYMENT": 0.21,
}

# β response BTC per σ (firmado r91+)
BETA_PER_EVENT = {
    "CPI": 0.43,        # %  per σ
    "NFP": 0.32,
    "ADP": 0.18,        # ADP_proxy = NFP × 0.5 (firmado r91+)
    "FOMC": 0.55,
    "PCE": 0.28,
    "ISM": 0.15,
}

BETA_REVISION_PROPAGATION = 0.5  # firmado r91+ default
ANOMALY_REVISION_PCT = 0.5       # firmado r92 — 50% del actual


@dataclass
class EventMetadata:
    """Sección 1 del audit. source_provider añadido per firma r92."""
    event: str                       # "CPI", "NFP", "ADP", etc.
    actual: float | int | None
    forecast: float | int | None
    previous_original: float | int | None
    previous_revised: float | int | None
    revision_delta: float | int | None
    source_provider: str             # "FMP" | "Bloomberg" | "Investing" — firma r92
    release_ts_utc: str
    received_by_sidecar_ts_utc: str | None = None
    lag_release_to_received_seconds: float | None = None


@dataclass
class SFCalculation:
    """Sección 2 — SF naive + adjusted con revision, max() decision."""
    sigma_robust_FRED: float
    sigma_robust_source: str
    beta_revision_propagation: float
    revision_delta: float | int
    revision_significant: bool
    forecast_adjusted: float
    sf_naive: float
    sf_adjusted: float
    sf_used_for_decision: float        # max(|naive|, |adjusted|)
    sf_used_source: str                # "max(|sf_naive|, |sf_adjusted|)"
    absolute_sf_value: float


@dataclass
class ModeTransition:
    ts_utc: str
    mode_from: str
    mode_to: str
    reason: str
    size_factor_after: float


@dataclass
class P99AuditWindow:
    """Sección 4 — criterios HARD para LIVE pass."""
    window_start_utc: str
    window_end_utc: str
    scan_tick_duration_p99_ms: int
    scan_tick_duration_p95_ms: int
    scan_tick_duration_p50_ms: int
    back_pressure_drops_count: int
    stream_reconnect_events: int
    slot_lag_p95: int
    n_samples: int
    verdict_per_criteria: dict[str, bool]


@dataclass
class BTCResponseValidation:
    """Sección 5 — β observed vs expected. SOFT warning per firma r92."""
    expected_beta_per_sigma: float
    actual_btc_move_5min_pct: float | None
    actual_btc_move_30min_pct: float | None
    actual_btc_move_60min_pct: float | None
    beta_observed: float | None
    beta_expected: float
    match_within_tolerance: bool | None
    tolerance_pct: float = 30.0       # ±30% tolerance default
    severity: str = "SOFT_WARNING"    # firmado r92 (no bloquea LIVE)


@dataclass
class MacroLayerHealth:
    """Sección 6 — health del macro layer durante el evento."""
    tau_final_at_release: float
    tau_final_max_during_window: float
    rho_at_release: float | None
    rho_min_during_window: float | None
    stale_level_during_event: str    # "L0", "L1", "L2", "L3", "L4"
    v3_v4_disagreement_count: int
    v4_decision_allowed_pct: float
    runtime_version: str = "V3.5-SHADOW-r93"  # firma r93 — añadido para evitar confusiones histórico


@dataclass
class CPIAuditReport:
    """Estructura completa del audit report. 8 secciones."""
    audit_id: str
    audit_type: str
    spec_version: str

    event_metadata: EventMetadata
    sf_calculation: SFCalculation
    mode_transitions_during_event: list[ModeTransition]
    p99_audit_window: P99AuditWindow
    btc_response_validation: BTCResponseValidation
    macro_layer_health_during_event: MacroLayerHealth
    burn_in_total_hours_completed: float
    burn_in_includes_NFP_stress: bool
    burn_in_includes_CPI_stress: bool

    # Defaults al final (firma r93 + dataclass requirement)
    runtime_version: str = "V3.5-SHADOW-r93"  # firma r93 — runtime tracker
    verdict: dict[str, Any] = field(default_factory=dict)


def parse_value(s: str | None) -> float | None:
    """Parser unificado. Maneja 'M', 'K', 'B', '%', etc."""
    if s is None or str(s).lower() in ("none", "nan", ""):
        return None
    s = str(s).strip().replace(",", "")
    mult = 1.0
    if s.endswith(("K", "k")): mult = 1e3; s = s[:-1]
    elif s.endswith(("M", "m")): mult = 1e6; s = s[:-1]
    elif s.endswith(("B", "b")): mult = 1e9; s = s[:-1]
    s = s.replace("%", "")
    try:
        return float(s) * mult
    except ValueError:
        return None


def calculate_sf(
    actual: float,
    forecast: float,
    previous_original: float,
    previous_revised: float | None,
    sigma_robust: float,
    event_category: str,
) -> SFCalculation:
    """Calcula SF naive + adjusted con revision propagation.

    Spec r91+ firmado:
      - β_revision = 0.5
      - SF_used = max(|naive|, |adjusted|)
      - anomaly threshold: revision > 50% del actual → flag manual
    """
    # Revision delta
    revision_delta = 0
    if previous_revised is not None:
        revision_delta = previous_revised - previous_original

    # Anomaly check (firmado r92)
    revision_significant = abs(revision_delta) > ANOMALY_REVISION_PCT * abs(actual) if actual else False

    # Forecast adjusted con propagation β=0.5
    forecast_adjusted = forecast + (revision_delta * BETA_REVISION_PROPAGATION)

    # SF naive (sin revision)
    sf_naive = (actual - forecast) / sigma_robust if sigma_robust > 0 else 0

    # SF adjusted (con revision propagation)
    sf_adjusted = (actual - forecast_adjusted) / sigma_robust if sigma_robust > 0 else 0

    # Decision: max(|naive|, |adjusted|) — conservador
    sf_naive_abs = abs(sf_naive)
    sf_adjusted_abs = abs(sf_adjusted)
    sf_used = sf_naive if sf_naive_abs >= sf_adjusted_abs else sf_adjusted

    return SFCalculation(
        sigma_robust_FRED=sigma_robust,
        sigma_robust_source=f"macro_calendar.json fred_calibration kappa-adjusted ({event_category})",
        beta_revision_propagation=BETA_REVISION_PROPAGATION,
        revision_delta=revision_delta,
        revision_significant=revision_significant,
        forecast_adjusted=round(forecast_adjusted, 6),
        sf_naive=round(sf_naive, 4),
        sf_adjusted=round(sf_adjusted, 4),
        sf_used_for_decision=round(sf_used, 4),
        sf_used_source="max(|sf_naive|, |sf_adjusted|)",
        absolute_sf_value=round(max(sf_naive_abs, sf_adjusted_abs), 4),
    )


def evaluate_p99_criteria(audit: P99AuditWindow) -> dict[str, bool]:
    """Aplica los criterios HARD firmados r91+/r92."""
    return {
        "p99_under_8000ms": audit.scan_tick_duration_p99_ms < P99_HARD_THRESHOLD_MS,
        "back_pressure_drops_zero": audit.back_pressure_drops_count <= BACK_PRESSURE_DROPS_MAX,
        "no_reconnects": audit.stream_reconnect_events <= STREAM_RECONNECTS_MAX,
        "slot_lag_p95_under_10": audit.slot_lag_p95 < SLOT_LAG_P95_MAX,
        "sufficient_samples": audit.n_samples >= 100_000,
    }


def evaluate_verdict(report: CPIAuditReport) -> dict[str, Any]:
    """Aplica los 8 criterios HARD para autorización LIVE.

    Firmado Gemma r92:
      ALL criteria must pass:
        1. p99 < 8000ms
        2. back_pressure_drops == 0
        3. stream_reconnects == 0
        4. slot_lag_p95 < 10
        5. NFP audit del Vie 8 ya passed
        6. macro stale_level NOT IN [L2, L3, L4]
        7. burn_in >= 72h
        8. SF calculation completed without error
      β_observed match: SOFT (warning only)
    """
    p99_pass = all(report.p99_audit_window.verdict_per_criteria.values())
    burn_in_pass = report.burn_in_total_hours_completed >= BURN_IN_MIN_HOURS
    nfp_pass = report.burn_in_includes_NFP_stress
    cpi_pass = report.burn_in_includes_CPI_stress
    stale_pass = report.macro_layer_health_during_event.stale_level_during_event not in ("L2", "L3", "L4")
    sf_calc_ok = report.sf_calculation.sf_used_for_decision is not None

    criteria_failed = []
    if not p99_pass: criteria_failed.append("p99_audit_window.criteria")
    if not burn_in_pass: criteria_failed.append(f"burn_in_hours ({report.burn_in_total_hours_completed:.1f} < 72)")
    if not nfp_pass: criteria_failed.append("NFP_stress_test_not_passed")
    if not cpi_pass: criteria_failed.append("CPI_stress_test_not_passed")
    if not stale_pass: criteria_failed.append(f"stale_level={report.macro_layer_health_during_event.stale_level_during_event}")
    if not sf_calc_ok: criteria_failed.append("sf_calculation_failed")

    all_pass = len(criteria_failed) == 0

    # β_observed SOFT warning
    soft_warnings = []
    btc = report.btc_response_validation
    if btc.match_within_tolerance is False:
        soft_warnings.append(
            f"β_observed={btc.beta_observed} vs β_expected={btc.beta_expected} "
            f"outside ±{btc.tolerance_pct}% tolerance (SOFT, no bloquea LIVE)"
        )

    return {
        "all_criteria_pass": all_pass,
        "criteria_failed": criteria_failed,
        "soft_warnings": soft_warnings,
        "authorize_LIVE": all_pass,
        "next_action": (
            "LIVE_AUTHORIZED" if all_pass else
            ("RESET_BURN_IN" if not burn_in_pass else "DEFER_LIVE_FIX_FAILED_CRITERIA")
        ),
        "if_LIVE_authorized": {
            "earliest_LIVE_date_utc": "2026-05-13T22:00:00Z",
            "capital_initial_usd": 300,
            "wallet": "hot200 (firmado Gemma r91+)",
            "kill_switches_active": "see risk_config.json",
        } if all_pass else None,
    }


def serialize_report(report: CPIAuditReport, output_dir: Path) -> tuple[Path, Path]:
    """Genera JSON + MD del audit report."""
    output_dir.mkdir(parents=True, exist_ok=True)
    audit_ts = report.audit_id.replace(":", "-").replace("T", "_")
    json_path = output_dir / f"audit_{report.event_metadata.event}_{audit_ts}.json"
    md_path = output_dir / f"audit_{report.event_metadata.event}_{audit_ts}.md"

    # JSON
    json_path.write_text(json.dumps(asdict(report), indent=2, default=str))

    # MD human-readable
    md = render_md(report)
    md_path.write_text(md)

    return json_path, md_path


def render_md(r: CPIAuditReport) -> str:
    """MD legible para Marco / Gemma copy-paste."""
    v = r.verdict
    e = r.event_metadata
    sf = r.sf_calculation
    p99 = r.p99_audit_window
    btc = r.btc_response_validation
    macro = r.macro_layer_health_during_event

    lines = [
        f"# AUDIT REPORT — {e.event} — {r.audit_id}",
        "",
        f"**Spec version:** {r.spec_version}",
        f"**Verdict:** {'✅ LIVE_AUTHORIZED' if v.get('authorize_LIVE') else '⛔ ' + v.get('next_action', 'DEFER')}",
        "",
        "## 1. Event Metadata",
        "",
        f"- Event: **{e.event}**",
        f"- Actual: `{e.actual}`",
        f"- Forecast: `{e.forecast}`",
        f"- Previous original: `{e.previous_original}`",
        f"- Previous revised: `{e.previous_revised}` (delta: {e.revision_delta})",
        f"- Source provider: **{e.source_provider}**",
        f"- Release ts UTC: {e.release_ts_utc}",
        f"- Lag release→sidecar: {e.lag_release_to_received_seconds}s",
        "",
        "## 2. SF Calculation",
        "",
        f"- σ_robust FRED: `{sf.sigma_robust_FRED}`",
        f"- β revision propagation: `{sf.beta_revision_propagation}`",
        f"- Revision delta: `{sf.revision_delta}` (significant: {sf.revision_significant})",
        f"- Forecast adjusted: `{sf.forecast_adjusted}`",
        f"- **SF naive: `{sf.sf_naive}σ`**",
        f"- **SF adjusted: `{sf.sf_adjusted}σ`**",
        f"- **SF USED (max): `{sf.sf_used_for_decision}σ`**",
        "",
        "## 3. Mode Transitions",
        "",
        "| ts UTC | from | to | reason | size_factor |",
        "|---|---|---|---|---:|",
    ]
    for t in r.mode_transitions_during_event:
        lines.append(f"| {t.ts_utc[11:19]} | {t.mode_from} | {t.mode_to} | {t.reason} | {t.size_factor_after} |")

    lines += [
        "",
        "## 4. p99 Audit Window (HARD criteria)",
        "",
        f"- Window: {p99.window_start_utc[11:19]} → {p99.window_end_utc[11:19]}",
        f"- N samples: {p99.n_samples:,}",
        f"- scan_tick_duration p99: **{p99.scan_tick_duration_p99_ms:,} ms** (threshold <{P99_HARD_THRESHOLD_MS:,})",
        f"- scan_tick_duration p95: {p99.scan_tick_duration_p95_ms:,} ms",
        f"- scan_tick_duration p50: {p99.scan_tick_duration_p50_ms:,} ms",
        f"- back_pressure_drops: **{p99.back_pressure_drops_count}** (threshold ≤{BACK_PRESSURE_DROPS_MAX})",
        f"- stream_reconnects: **{p99.stream_reconnect_events}** (threshold ≤{STREAM_RECONNECTS_MAX})",
        f"- slot_lag p95: **{p99.slot_lag_p95}** (threshold <{SLOT_LAG_P95_MAX})",
        "",
        "**Per-criteria verdict:**",
        "",
    ]
    for k, ok in p99.verdict_per_criteria.items():
        lines.append(f"- {k}: {'✅ PASS' if ok else '❌ FAIL'}")

    lines += [
        "",
        "## 5. BTC Response Validation (SOFT warning, no bloquea LIVE)",
        "",
        f"- β expected per σ: `{btc.beta_expected}%`",
        f"- BTC move T+5min: `{btc.actual_btc_move_5min_pct}%`",
        f"- BTC move T+30min: `{btc.actual_btc_move_30min_pct}%`",
        f"- BTC move T+60min: `{btc.actual_btc_move_60min_pct}%`",
        f"- β observed: `{btc.beta_observed}`",
        f"- Match within ±{btc.tolerance_pct}%: {btc.match_within_tolerance}",
        f"- Severity: **{btc.severity}**",
        "",
        "## 6. Macro Layer Health",
        "",
        f"- τ_final at release: `{macro.tau_final_at_release}`",
        f"- τ_final max in window: `{macro.tau_final_max_during_window}`",
        f"- ρ at release: `{macro.rho_at_release}`",
        f"- ρ min in window: `{macro.rho_min_during_window}`",
        f"- Stale level: **{macro.stale_level_during_event}**",
        f"- V3↔V4 disagreement count: {macro.v3_v4_disagreement_count}",
        f"- V4 decision_allowed pct: {macro.v4_decision_allowed_pct}%",
        "",
        "## 7. Burn-in",
        "",
        f"- Hours completed: **{r.burn_in_total_hours_completed:.1f}h** (min {BURN_IN_MIN_HOURS}h)",
        f"- NFP stress test included: {'✅' if r.burn_in_includes_NFP_stress else '❌'}",
        f"- CPI stress test included: {'✅' if r.burn_in_includes_CPI_stress else '❌'}",
        "",
        "## 8. Verdict",
        "",
        f"- **All criteria pass:** {v.get('all_criteria_pass')}",
        f"- **Authorize LIVE:** {v.get('authorize_LIVE')}",
        f"- **Next action:** {v.get('next_action')}",
    ]

    if v.get("criteria_failed"):
        lines.append("")
        lines.append("**Criteria failed:**")
        for cf in v["criteria_failed"]:
            lines.append(f"  - ❌ {cf}")

    if v.get("soft_warnings"):
        lines.append("")
        lines.append("**Soft warnings:**")
        for sw in v["soft_warnings"]:
            lines.append(f"  - ⚠️ {sw}")

    if v.get("if_LIVE_authorized"):
        live = v["if_LIVE_authorized"]
        lines.extend([
            "",
            "**LIVE authorization details:**",
            f"  - Earliest LIVE date: {live.get('earliest_LIVE_date_utc')}",
            f"  - Capital initial: ${live.get('capital_initial_usd')}",
            f"  - Wallet: {live.get('wallet')}",
        ])

    return "\n".join(lines)


def build_audit_report(
    event: str,
    actual: float,
    forecast: float,
    previous_original: float,
    previous_revised: float | None,
    source_provider: str,
    release_ts_utc: str,
    received_ts_utc: str | None,
    p99_window_data: dict,
    mode_transitions: list[dict],
    btc_response_data: dict,
    macro_health_data: dict,
    burn_in_hours: float,
    nfp_passed: bool,
    cpi_passed: bool,
) -> CPIAuditReport:
    """Constructor del audit report. Validates + computes verdict."""
    sigma = SIGMA_FRED.get(event, 1.0)
    sf = calculate_sf(actual, forecast, previous_original, previous_revised, sigma, event)

    e_meta = EventMetadata(
        event=event,
        actual=actual,
        forecast=forecast,
        previous_original=previous_original,
        previous_revised=previous_revised,
        revision_delta=sf.revision_delta,
        source_provider=source_provider,
        release_ts_utc=release_ts_utc,
        received_by_sidecar_ts_utc=received_ts_utc,
        lag_release_to_received_seconds=(
            (datetime.fromisoformat(received_ts_utc.replace("Z","+00:00")) -
             datetime.fromisoformat(release_ts_utc.replace("Z","+00:00"))).total_seconds()
            if received_ts_utc else None
        ),
    )

    p99 = P99AuditWindow(**p99_window_data)
    p99.verdict_per_criteria = evaluate_p99_criteria(p99)

    btc_resp = BTCResponseValidation(**btc_response_data)
    if btc_resp.beta_observed is not None and btc_resp.beta_expected != 0:
        delta_pct = abs(btc_resp.beta_observed - btc_resp.beta_expected) / abs(btc_resp.beta_expected) * 100
        btc_resp.match_within_tolerance = delta_pct <= btc_resp.tolerance_pct

    macro = MacroLayerHealth(**macro_health_data)
    transitions = [ModeTransition(**t) for t in mode_transitions]

    audit_id = f"{event}_{release_ts_utc.replace(':','-').replace('T','_')}"
    report = CPIAuditReport(
        audit_id=audit_id,
        audit_type=f"{event}_stress_test_audit",
        spec_version="r92_2026-05-06",
        event_metadata=e_meta,
        sf_calculation=sf,
        mode_transitions_during_event=transitions,
        p99_audit_window=p99,
        btc_response_validation=btc_resp,
        macro_layer_health_during_event=macro,
        burn_in_total_hours_completed=burn_in_hours,
        burn_in_includes_NFP_stress=nfp_passed,
        burn_in_includes_CPI_stress=cpi_passed,
    )
    report.verdict = evaluate_verdict(report)
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--demo", action="store_true", help="Generar report demo con valores fake")
    args = p.parse_args()

    if args.demo:
        # Demo: ADP de hoy con valores plausibles
        report = build_audit_report(
            event="ADP",
            actual=130000,
            forecast=99000,
            previous_original=62000,
            previous_revised=65000,
            source_provider="FMP",
            release_ts_utc="2026-05-06T12:15:00Z",
            received_ts_utc="2026-05-06T12:15:02.987Z",
            p99_window_data={
                "window_start_utc": "2026-05-06T11:15:00Z",
                "window_end_utc": "2026-05-06T13:15:00Z",
                "scan_tick_duration_p99_ms": 4500,
                "scan_tick_duration_p95_ms": 3200,
                "scan_tick_duration_p50_ms": 1100,
                "back_pressure_drops_count": 0,
                "stream_reconnect_events": 0,
                "slot_lag_p95": 6,
                "n_samples": 36000,
                "verdict_per_criteria": {},
            },
            mode_transitions=[],
            btc_response_data={
                "expected_beta_per_sigma": 0.18,
                "actual_btc_move_5min_pct": 0.05,
                "actual_btc_move_30min_pct": 0.12,
                "actual_btc_move_60min_pct": 0.08,
                "beta_observed": 0.21,
                "beta_expected": 0.18,
                "match_within_tolerance": None,
            },
            macro_health_data={
                "tau_final_at_release": 0.604,
                "tau_final_max_during_window": 0.715,
                "rho_at_release": 0.024,
                "rho_min_during_window": -0.041,
                "stale_level_during_event": "L0",
                "v3_v4_disagreement_count": 0,
                "v4_decision_allowed_pct": 100.0,
            },
            burn_in_hours=4.5,  # ADP no es stress oficial — solo time
            nfp_passed=False,
            cpi_passed=False,
        )

        out_dir = Path("/home/administrator/poly_sidecar/data")
        json_path, md_path = serialize_report(report, out_dir)
        print(f"✓ JSON: {json_path}")
        print(f"✓ MD:   {md_path}")
        print()
        print("=== VERDICT SUMMARY ===")
        v = report.verdict
        print(f"all_criteria_pass: {v.get('all_criteria_pass')}")
        print(f"authorize_LIVE: {v.get('authorize_LIVE')}")
        print(f"next_action: {v.get('next_action')}")
        if v.get("criteria_failed"):
            print(f"criteria_failed: {v['criteria_failed']}")
    else:
        print("Use --demo for sample run. For real audit, import build_audit_report().")


if __name__ == "__main__":
    main()
