"""FRED init — descarga 12y series + calcula σ_surprise por evento.

Spec final Gemma 4 (2026-05-05 ~07:00 UTC, brief r80 auditoria):

| Evento        | FRED Series ID | Cálculo σ        |
|---------------|----------------|-------------------|
| CPI Annual    | CPIAUCSL       | Δ YoY             |
| PCE Core      | PCEPOC         | Δ MoM             |
| NFP           | PAYEMS         | Δ Absoluta        |
| JOLTS         | JTSJOL         | Δ Absoluta        |
| Fed Funds     | FEDFUNDS       | Δ Bps             |
| Unemployment  | UNRATE         | Δ Puntos          |
| GDP Real      | GDPC1          | Δ QoQ             |
| Retail Sales  | RSXFS          | Δ MoM             |
| ISM PMI       | NO disponible  | Usar default V4-Alpha |

Período: 12 años fijos (2014-2026). Captura régimen baja inflación pre-2021
+ régimen alta volatilidad actual.

Output: actualiza /home/administrator/poly_sidecar/macro_calendar.json
con campo `historical_surprise_mu` y `historical_surprise_sigma` por evento.

Uso:
  /home/administrator/poly_sidecar/venv/bin/python fred_init.py
  (requiere FRED_API_KEY env o /home/administrator/.config/fred/api_key)
"""
from __future__ import annotations
import datetime as dt
import json
import math
import os
import statistics
import sys
from pathlib import Path
from typing import Any

import httpx

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
KEY_FILE = Path("/home/administrator/.config/fred/api_key")
CALENDAR = Path("/home/administrator/poly_sidecar/macro_calendar.json")

# Spec Gemma 4 verbatim
FRED_EVENTS: dict[str, dict] = {
    "FOMC": {
        "fred_series_id": "FEDFUNDS",
        "calculation": "delta_bps",          # cambio en puntos básicos
        "frequency": "monthly",
        "description": "Fed Funds Effective Rate",
    },
    "CPI": {
        "fred_series_id": "CPIAUCSL",
        "calculation": "yoy_pct",            # cambio % YoY
        "frequency": "monthly",
        "description": "CPI All Urban Consumers (annual change)",
    },
    "PCE": {
        "fred_series_id": "PCEPILFE",        # Core PCE (Gemma propuso PCEPOC, no existe; PCEPILFE es el oficial)
        "calculation": "mom_pct",
        "frequency": "monthly",
        "description": "PCE Excluding Food and Energy (Core PCE)",
    },
    "NFP": {
        "fred_series_id": "PAYEMS",
        "calculation": "delta_absolute_thousands",  # FRED in thousands → multiplicar ×1000 para σ en jobs absolutos
        "frequency": "monthly",
        "description": "Total Nonfarm Payrolls (delta abs, σ en jobs absolutos)",
    },
    "JOLTS": {
        "fred_series_id": "JTSJOL",
        "calculation": "delta_absolute_thousands",  # FRED in thousands → ×1000
        "frequency": "monthly",
        "description": "Job Openings: Total Nonfarm (σ en jobs absolutos)",
    },
    "GDP": {
        "fred_series_id": "GDPC1",
        "calculation": "qoq_pct",            # cambio % QoQ
        "frequency": "quarterly",
        "description": "Real GDP (QoQ change)",
    },
    "ISM": {
        "fred_series_id": None,              # NO disponible en FRED
        "calculation": "default",
        "fallback_sigma": 1.0,
        "description": "ISM PMI — uses V4-Alpha defaults (1pt index)",
    },
    "JOLTS_QUITS": {
        "fred_series_id": "JTSQUR",
        "calculation": "delta_points",  # JTSQUR es rate %, NO en thousands → mantenemos como puntos
        "frequency": "monthly",
        "description": "JOLTS Quits Rate (%)",
    },
    "UNEMPLOYMENT": {
        "fred_series_id": "UNRATE",
        "calculation": "delta_points",       # cambio en puntos %
        "frequency": "monthly",
        "description": "Unemployment Rate",
    },
    "RETAIL_SALES": {
        "fred_series_id": "RSXFS",
        "calculation": "mom_pct",
        "frequency": "monthly",
        "description": "Retail Sales (Excl Food Services)",
    },
}


def _load_api_key() -> str:
    env = os.environ.get("FRED_API_KEY", "").strip()
    if env:
        return env
    try:
        return KEY_FILE.read_text().strip()
    except FileNotFoundError:
        return ""


def fetch_series(client: httpx.Client, series_id: str, api_key: str,
                 start: str, end: str) -> list[tuple[str, float]]:
    """Fetch FRED series. Returns list of (date, value) ascending."""
    r = client.get(FRED_BASE, params={
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start,
        "observation_end": end,
    }, timeout=20.0)
    r.raise_for_status()
    data = r.json()
    obs = data.get("observations", [])
    out: list[tuple[str, float]] = []
    for o in obs:
        try:
            v = float(o.get("value", "."))
            out.append((o["date"], v))
        except (ValueError, TypeError):
            continue
    return out


def _kappa_kurtosis(excess_kurtosis: float) -> float:
    """Factor de ajuste σ_robust por kurtosis (Gemma r100, 2026-05-05).

    Fórmula firmada Gemma 2026-05-05 post-audit ChatGPT:
      κ(K) = 1.0                     si K ≤ 3   (~normal)
      κ(K) = 1.0 + (K - 3) / 10      si 3 < K ≤ 10
      κ(K) = 1.7 + log(K - 9)        si K > 10  (extrema)

    Notación: K aquí es kurtosis NO-excess (Pearson kurtosis donde
    distribución normal tiene K=3). Excess kurtosis = K_pearson - 3.
    Si recibimos excess_kurtosis (donde 0 = normal), convertimos:
      K_pearson = excess_kurtosis + 3

    Para K=3 (normal): κ=1.0 (sin cambio).
    Para K=9.8 (NFP post-COVID): κ=1.68 (compensa fat tails).
    """
    K_pearson = excess_kurtosis + 3.0
    if K_pearson <= 3:
        return 1.0
    if K_pearson <= 10:
        return 1.0 + (K_pearson - 3.0) / 10.0
    # K > 10: log para suavizar
    return 1.7 + math.log(K_pearson - 9.0)


def compute_changes(values: list[tuple[str, float]], calc: str) -> list[float]:
    """Compute the series of 'changes' per Gemma's calculation method.

    delta_absolute_thousands: FRED da serie en thousands; multiplicamos
    deltas ×1000 para que σ_robust quede en unidades absolutas (jobs).
    Esto evita el bug JOLTS SF=+16.65σ identificado 2026-05-05 (r95).
    """
    if len(values) < 2:
        return []
    nums = [v for _, v in values]
    out: list[float] = []
    if calc == "delta_absolute":
        # Cambio absoluto release-vs-release
        for i in range(1, len(nums)):
            out.append(nums[i] - nums[i - 1])
    elif calc == "delta_absolute_thousands":
        # FRED in thousands → escalar a unidades absolutas para coincidir
        # con parser de Investing.com (que convierte "147K" → 147,000).
        for i in range(1, len(nums)):
            out.append((nums[i] - nums[i - 1]) * 1000.0)
    elif calc == "delta_points":
        # Cambio en puntos (igual numericamente a delta_absolute)
        for i in range(1, len(nums)):
            out.append(nums[i] - nums[i - 1])
    elif calc == "delta_bps":
        # Fed Funds rate is in % → convert to bps
        for i in range(1, len(nums)):
            out.append((nums[i] - nums[i - 1]) * 100.0)  # 1% = 100bps
    elif calc == "mom_pct":
        # Cambio % MoM
        for i in range(1, len(nums)):
            if nums[i - 1] > 0:
                out.append(((nums[i] - nums[i - 1]) / nums[i - 1]) * 100.0)
    elif calc == "qoq_pct":
        # Mismo que mom_pct, semánticamente es QoQ porque la series es trimestral
        for i in range(1, len(nums)):
            if nums[i - 1] > 0:
                out.append(((nums[i] - nums[i - 1]) / nums[i - 1]) * 100.0)
    elif calc == "yoy_pct":
        # Cambio % YoY (12 meses atrás para serie mensual)
        lag = 12
        if len(nums) <= lag:
            return []
        for i in range(lag, len(nums)):
            if nums[i - lag] > 0:
                out.append(((nums[i] - nums[i - lag]) / nums[i - lag]) * 100.0)
    return out


def calibrate_event(category: str, spec: dict, client: httpx.Client,
                    api_key: str, years: int = 12) -> dict[str, Any]:
    """Returns { fred_series_id, mu, sigma, n, calc, period_years }."""
    sid = spec.get("fred_series_id")
    calc = spec.get("calculation", "delta_absolute")
    if not sid:
        # No disponible en FRED — fallback per V4-Alpha
        return {
            "fred_series_id": None,
            "calculation": calc,
            "historical_surprise_mu": None,
            "historical_surprise_sigma": spec.get("fallback_sigma"),
            "n_observations": 0,
            "period_years": years,
            "note": "FRED no expone esta serie — usar default V4-Alpha",
        }

    end = dt.date.today().isoformat()
    start = (dt.date.today() - dt.timedelta(days=365 * years)).isoformat()
    try:
        obs = fetch_series(client, sid, api_key, start, end)
    except Exception as e:
        return {
            "fred_series_id": sid,
            "calculation": calc,
            "error": str(e)[:120],
            "historical_surprise_mu": None,
            "historical_surprise_sigma": None,
            "n_observations": 0,
        }

    changes = compute_changes(obs, calc)
    if not changes:
        return {
            "fred_series_id": sid,
            "calculation": calc,
            "error": "no changes computable",
            "historical_surprise_mu": None,
            "historical_surprise_sigma": None,
            "n_observations": len(obs),
        }

    # Estimadores robustos (Gemma 4 r90 firmado 2026-05-05) ajustados r100 con
    # factor κ(K) por kurtosis (post-audit ChatGPT 2026-05-05, blind spot
    # asunción normalidad).
    # σ_robust = 1.4826 × MAD × κ(K) donde κ depende de excess kurtosis.
    mu_robust = statistics.median(changes)
    abs_devs = [abs(x - mu_robust) for x in changes]
    mad = statistics.median(abs_devs)

    # Excess kurtosis empírica
    n = len(changes)
    mean = sum(changes) / n
    variance = sum((x - mean) ** 2 for x in changes) / n
    std = math.sqrt(variance) if variance > 0 else 0.0
    if std > 0:
        fourth_moment = sum((x - mean) ** 4 for x in changes) / n
        excess_kurtosis = fourth_moment / (std ** 4) - 3.0
    else:
        excess_kurtosis = 0.0

    kappa_factor = _kappa_kurtosis(excess_kurtosis)
    sigma_robust_base = 1.4826 * mad
    sigma_robust = sigma_robust_base * kappa_factor

    # Conservamos σ aritmética para auditoría / simulación Z_old vs Z_new
    mu_arith = statistics.mean(changes)
    sigma_arith = statistics.pstdev(changes)

    return {
        "fred_series_id": sid,
        "calculation": calc,
        "frequency": spec.get("frequency"),
        "description": spec.get("description"),
        "historical_surprise_mu": round(mu_robust, 6),         # robusto = mediana
        "historical_surprise_sigma": round(sigma_robust, 6),   # 1.4826*MAD*κ(K)
        "robust_estimator": "median + 1.4826*MAD*kappa(K)",
        "kurtosis_excess": round(excess_kurtosis, 4),
        "kappa_factor": round(kappa_factor, 4),
        "audit": {
            "mu_arithmetic": round(mu_arith, 6),
            "sigma_arithmetic": round(sigma_arith, 6),
            "mu_median": round(mu_robust, 6),
            "mad": round(mad, 6),
            "sigma_robust_1_4826_mad_only": round(sigma_robust_base, 6),
            "kappa_kurtosis_factor": round(kappa_factor, 4),
            "sigma_robust_kurtosis_adj": round(sigma_robust, 6),
            "robustness_ratio": round(sigma_arith / sigma_robust, 4) if sigma_robust > 0 else None,
        },
        "n_observations": len(obs),
        "n_changes": len(changes),
        "period_years": years,
        "period_start": start,
        "period_end": end,
    }


def main() -> int:
    api_key = _load_api_key()
    if not api_key:
        print(
            "ERROR: missing FRED API key.\n"
            "  Generar gratis en https://fred.stlouisfed.org/docs/api/api_key.html\n"
            "  Guardar en /home/administrator/.config/fred/api_key (chmod 600)\n"
            "  o exportar FRED_API_KEY=...",
            file=sys.stderr,
        )
        return 2

    print(f"FRED init — calibrando σ con 12y series (2014-2026)")
    print(f"API key length: {len(api_key)}")
    print()

    results: dict[str, dict] = {}
    with httpx.Client() as client:
        for category, spec in FRED_EVENTS.items():
            sid = spec.get("fred_series_id")
            print(f"[{category:14}] {sid or 'no FRED series'} ... ", end="", flush=True)
            res = calibrate_event(category, spec, client, api_key, years=12)
            results[category] = res
            if "error" in res:
                print(f"ERROR: {res['error']}")
            elif res.get("historical_surprise_sigma") is not None and res.get("historical_surprise_mu") is not None:
                mu = res["historical_surprise_mu"]
                sigma = res["historical_surprise_sigma"]
                n = res.get("n_changes", res.get("n_observations", 0))
                print(f"μ={mu:+.4f}  σ={sigma:.4f}  (n={n})")
            elif res.get("historical_surprise_sigma") is not None:
                # Fallback (ISM): sigma fijo sin μ
                print(f"σ_fallback={res['historical_surprise_sigma']} (V4-Alpha default)")
            else:
                print(f"sin σ — fallback no aplicado")

    # Merge into macro_calendar.json
    cal = json.loads(CALENDAR.read_text())
    cal.setdefault("fred_calibration", {})
    cal["fred_calibration"]["last_run_utc"] = dt.datetime.utcnow().isoformat() + "Z"
    cal["fred_calibration"]["events"] = results
    CALENDAR.write_text(json.dumps(cal, indent=2, ensure_ascii=False))
    print()
    print(f"✅ macro_calendar.json actualizado con fred_calibration de {len(results)} eventos")
    print(f"   {CALENDAR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
