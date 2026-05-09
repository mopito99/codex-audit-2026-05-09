"""Migración del macro_calendar.json existente para aplicar:
1. Fix unit mismatch JOLTS/NFP (×1000 a σ para series in-thousands).
2. Factor κ(K) por kurtosis (Gemma r100 firmado post-audit ChatGPT).

Sin re-descargar FRED (no requiere API key). Lee σ_arithmetic + MAD
del audit existente, calcula kurtosis empíricamente impossible (no
tenemos changes brutos), por lo que aplicamos kurtosis ESTIMADA
desde el ratio σ_arith/σ_robust:
  - Si ratio ≈ 1 → distribución cercana a normal → K_excess ≈ 0
  - Si ratio > 5 → fat tails → K_excess alto

Estimación robustez_ratio → kurtosis aproximada:
  ratio < 1.5  → K_excess ~ 0     (cuasi-normal)
  ratio < 3    → K_excess ~ 1.5   (moderada)
  ratio < 7    → K_excess ~ 4     (leptocúrtica)
  ratio ≥ 7    → K_excess ~ 7     (extrema, NFP COVID)

Esta es heurística MIENTRAS no tengamos FRED API. Mañana Mié 6 con
FRED key se re-corre fred_init.py para obtener K real.
"""
from __future__ import annotations
import json
import math
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

CALENDAR = Path("/home/administrator/poly_sidecar/macro_calendar.json")
BACKUP_DIR = Path("/home/administrator/poly_sidecar")

# Series que vienen "in thousands" de FRED → necesitan ×1000 escalado
SERIES_IN_THOUSANDS = {"NFP", "JOLTS"}


def estimate_kurtosis_from_robustness(robustness_ratio: float | None) -> float:
    """Heurística: ratio σ_arith/σ_robust → excess kurtosis aproximada.

    Justificación: σ_arith infla con outliers. Si ratio alto, hay cola
    pesada → kurtosis alta. Si ratio ≈ 1, distribución casi normal.
    Validación cruzada con NFP audit: ratio=13.86 → estimación K~7.
    """
    if robustness_ratio is None or robustness_ratio <= 0:
        return 0.0
    r = float(robustness_ratio)
    # Calibrado contra Gemma table r100: NFP ratio=13.86 → K_excess=6.8 → κ=1.68
    if r < 1.5:
        return 0.0
    if r < 3.0:
        return 0.5    # ej. CPI ratio=1.81 → K~0.5 → κ~1.05 (cercano a normal)
    if r < 7.0:
        return 1.5    # ej. ISM, GDP ~ratio 5 → κ~1.15
    if r < 12.0:
        return 4.0    # ej. UNRATE ratio=6.3 → κ~1.40
    return 6.8        # ratio extremo (NFP table Gemma: K_excess=6.8 → κ=1.68)


def kappa_kurtosis(excess_kurtosis: float) -> float:
    """Mismo que fred_init._kappa_kurtosis. Local para evitar dependencia."""
    K_pearson = excess_kurtosis + 3.0
    if K_pearson <= 3:
        return 1.0
    if K_pearson <= 10:
        return 1.0 + (K_pearson - 3.0) / 10.0
    return 1.7 + math.log(K_pearson - 9.0)


def migrate():
    if not CALENDAR.exists():
        print(f"ERROR: {CALENDAR} no existe", file=sys.stderr)
        sys.exit(1)

    # Backup
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = BACKUP_DIR / f"macro_calendar.json.bak_pre_kurtosis_migration_{ts}"
    shutil.copy(CALENDAR, backup)
    print(f"✓ Backup: {backup}")

    data = json.loads(CALENDAR.read_text())
    fred = data.setdefault("fred_calibration", {})
    events = fred.setdefault("events", {})

    print()
    print(f"{'Serie':<14} {'σ_old':>14} {'×1000?':>7} {'ratio':>7} {'K_est':>7} {'κ':>7} {'σ_new':>14}")
    print("-" * 80)

    for cat, info in events.items():
        sigma_old = info.get("historical_surprise_sigma")
        if sigma_old is None or sigma_old <= 0:
            print(f"{cat:<14} (skipped, no σ)")
            continue

        # Step 1: aplicar ×1000 si está in-thousands
        scale_x1000 = cat in SERIES_IN_THOUSANDS
        sigma_after_unit_fix = sigma_old * (1000.0 if scale_x1000 else 1.0)

        # También aplicar al MAD audit
        audit = info.setdefault("audit", {})
        if scale_x1000:
            for k in ("mad", "sigma_robust_1_4826_mad", "sigma_arithmetic", "mu_arithmetic"):
                if k in audit and isinstance(audit[k], (int, float)):
                    audit[k] = audit[k] * 1000.0
            mu = info.get("historical_surprise_mu")
            if isinstance(mu, (int, float)):
                info["historical_surprise_mu"] = mu * 1000.0

        # Step 2: estimar kurtosis desde robustness_ratio
        ratio = audit.get("robustness_ratio")
        K_est = estimate_kurtosis_from_robustness(ratio)
        kappa = kappa_kurtosis(K_est)

        # Step 3: aplicar κ
        sigma_new = sigma_after_unit_fix * kappa

        # Update audit con nuevos campos
        audit["sigma_robust_1_4826_mad_only"] = round(sigma_after_unit_fix, 6)
        audit["kappa_kurtosis_factor"] = round(kappa, 4)
        audit["sigma_robust_kurtosis_adj"] = round(sigma_new, 6)
        audit["unit_fix_x1000_applied"] = scale_x1000
        audit["kurtosis_excess_estimated_from_ratio"] = round(K_est, 4)
        audit["kurtosis_estimation_method"] = "heuristic_from_robustness_ratio_pending_fred_recompute"

        # Update top-level σ
        info["historical_surprise_sigma"] = round(sigma_new, 6)
        info["robust_estimator"] = "median + 1.4826*MAD*kappa(K) [migrated from MAD-only]"
        info["kurtosis_excess"] = round(K_est, 4)
        info["kappa_factor"] = round(kappa, 4)
        info["migration_notes"] = (
            f"Migrated 2026-05-05: unit_fix_x1000={scale_x1000}, "
            f"K estimated heuristically (pending FRED recompute Wed 6)"
        )

        x1000_marker = "YES" if scale_x1000 else "no"
        print(f"{cat:<14} {sigma_old:>14.4f} {x1000_marker:>7} "
              f"{ratio if ratio else 0:>7.2f} {K_est:>7.2f} {kappa:>7.4f} "
              f"{sigma_new:>14.4f}")

    # Bump version + tag de migración (version puede ser string o número)
    cur_version = data.get("version", "1.0")
    if isinstance(cur_version, str):
        data["version"] = f"{cur_version}+kurtosis_migration_2026-05-05"
    else:
        data["version"] = float(cur_version) + 0.01
    data.setdefault("migration_log", []).append({
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "type": "sigma_fred_kurtosis_unit_fix",
        "applied_to_series": list(events.keys()),
        "in_thousands_fixed": list(SERIES_IN_THOUSANDS),
        "kappa_formula": "1.0 + (K_pearson-3)/10 for 3<K<=10, log for K>10",
        "notes": "Pending FRED API recompute to replace heuristic K estimation",
    })

    # Atomic write
    tmp = CALENDAR.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    tmp.replace(CALENDAR)

    print()
    print(f"✓ Migración aplicada a {CALENDAR}")
    print(f"  Version: {data.get('version')}")
    print(f"  Backup en: {backup}")


if __name__ == "__main__":
    migrate()
