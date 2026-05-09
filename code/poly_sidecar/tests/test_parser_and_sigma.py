"""Tests unitarios para parser Investing.com + σ_FRED post-migración kurtosis.

Cubre los 2 bugs identificados 2026-05-05 (r95, r100):
1. Bug JOLTS SF=+16.65σ por unit mismatch (parser ×1e6 vs σ in thousands)
2. Asunción normalidad σ_robust=1.4826*MAD que sub-estima fat tails

Run: cd /home/administrator/poly_sidecar && venv/bin/python3 -m pytest tests/ -v
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

# Path hack para imports relativos
sys.path.insert(0, str(Path(__file__).parent.parent))

from investing_client import _to_float, compute_surprise_factor, InvestingEvent, load_sigma_from_calendar, get_sigma
from fred_init import _kappa_kurtosis, compute_changes


# ===== Parser tests =====

@pytest.mark.parametrize("input_str,expected", [
    ("147K", 147_000),
    ("147k", 147_000),
    ("6.866M", 6_866_000),
    ("6.860M", 6_860_000),
    ("1.5B", 1_500_000_000),
    ("3.5%", 3.5),  # % retains numeric value, not /100
    ("48.0", 48.0),
    ("4.2", 4.2),
    ("-61.00B", -61_000_000_000),
    ("1,234", 1234),
    (None, None),
    ("", None),
    ("None", None),
    ("nan", None),
])
def test_to_float_parser(input_str, expected):
    """Parser maneja sufijos K/M/B/T y casos edge."""
    if expected is None:
        assert _to_float(input_str) is None
    else:
        result = _to_float(input_str)
        assert result == pytest.approx(expected), f"input='{input_str}' got {result}, expected {expected}"


# ===== JOLTS bug regression test =====

def test_jolts_bug_no_longer_explodes_to_16_sigma():
    """Replay del evento JOLTS de 2026-05-05 que dió SF=+16.65σ por bug.

    Pre-fix: σ_JOLTS=360 (en thousands implícito) → SF = 6000/360 = 16.65σ
    Post-fix: σ_JOLTS=360,272 (jobs absolutos) → SF = 6000/360,272 ≈ 0.017σ
    """
    # Cargar σ desde macro_calendar.json post-migración
    cal = json.loads(Path("/home/administrator/poly_sidecar/macro_calendar.json").read_text())
    n_loaded = load_sigma_from_calendar(cal)
    assert n_loaded > 0, "No σ loaded from calendar"

    sigma_jolts = get_sigma("JOLTS")
    assert sigma_jolts is not None, "σ_JOLTS not found"

    # Verificar que está en jobs absolutos (no thousands)
    assert sigma_jolts > 100_000, (
        f"σ_JOLTS={sigma_jolts} parece estar en thousands aún. "
        f"Esperado: σ en jobs absolutos (>100k para JOLTS post-migración)."
    )

    # Replay del evento real
    event = InvestingEvent(
        id="546282_test", date="05/05/2026", time="14:00", zone="US",
        currency="USD", importance="high",
        event="JOLTS Job Openings  (Mar)",
        actual="6.866M", forecast="6.860M", previous="6.860M",
        category="JOLTS",
    )
    sf, diff = compute_surprise_factor(event)
    assert sf is not None
    assert abs(sf) < 0.5, (
        f"JOLTS SF={sf:.4f} sigue siendo absurdo (debería ser ~0.017 post-fix)"
    )


def test_nfp_realistic_surprise_factor():
    """NFP típico: actual 147k vs forecast 200k → SF debe ser razonable."""
    cal = json.loads(Path("/home/administrator/poly_sidecar/macro_calendar.json").read_text())
    load_sigma_from_calendar(cal)
    sigma_nfp = get_sigma("NFP")
    assert sigma_nfp is not None
    assert sigma_nfp > 100_000, f"σ_NFP={sigma_nfp} debe estar en jobs absolutos"

    event = InvestingEvent(
        id="nfp_test", date="01/05/2026", time="12:30", zone="US",
        currency="USD", importance="high",
        event="Non-Farm Payrolls", actual="147K", forecast="200K", previous="180K",
        category="NFP",
    )
    sf, diff = compute_surprise_factor(event)
    assert sf is not None
    # Δ = -53k, σ ~219k → SF ~ -0.24σ
    assert -1.0 < sf < 0.0, f"NFP SF={sf:.4f} fuera de rango razonable [-1, 0]"


def test_ism_event_today_replay_consistency():
    """ISM Prices del evento de hoy: actual 70.7 vs forecast 73.7.

    Pre y post migración deberían dar SF similar (ISM no está en
    in-thousands, factor κ aplicable).
    """
    cal = json.loads(Path("/home/administrator/poly_sidecar/macro_calendar.json").read_text())
    load_sigma_from_calendar(cal)
    sigma_ism = get_sigma("ISM")
    assert sigma_ism == pytest.approx(1.0, abs=0.5), (
        f"σ_ISM={sigma_ism} esperado cercano a 1.0 (default)"
    )

    event = InvestingEvent(
        id="ism_test", date="05/05/2026", time="14:00", zone="US",
        currency="USD", importance="high",
        event="ISM Non-Manufacturing Prices  (Apr)",
        actual="70.7", forecast="73.7", previous="70.7",
        category="ISM",
    )
    sf, diff = compute_surprise_factor(event)
    assert sf is not None
    # SF ≈ -3.0 (que vimos hoy)
    assert -3.5 < sf < -2.5, f"ISM SF={sf:.4f} no coincide con -3σ esperado"


# ===== κ(K) function tests =====

@pytest.mark.parametrize("excess_K,expected_kappa", [
    (-1.0, 1.0),    # platikurtósica → no escalar
    (0.0, 1.0),     # K_pearson=3 (normal) → 1.0
    (0.5, 1.05),    # K_pearson=3.5
    (1.2, 1.12),    # K_pearson=4.2 (ISM)
    (3.5, 1.35),    # K_pearson=6.5 (CPI)
    (4.2, 1.42),    # K_pearson=7.2 (FOMC)
    (6.8, 1.68),    # K_pearson=9.8 (NFP table Gemma)
])
def test_kappa_matches_gemma_table_r100(excess_K, expected_kappa):
    """Verifica que κ(K) coincide con la tabla firmada por Gemma r100."""
    actual = _kappa_kurtosis(excess_K)
    assert actual == pytest.approx(expected_kappa, abs=0.001), (
        f"κ({excess_K}) = {actual}, esperado {expected_kappa}"
    )


# ===== compute_changes con delta_absolute_thousands =====

def test_compute_changes_delta_absolute_thousands_scales_x1000():
    """Verifica que series in-thousands escalan correctamente."""
    # NFP típico FRED en thousands
    values = [
        ("2024-01", 158_000.0),
        ("2024-02", 158_200.0),
        ("2024-03", 158_147.0),
    ]
    deltas = compute_changes(values, "delta_absolute_thousands")
    # +200 thousand = +200,000 jobs absolutos
    # -53 thousand = -53,000 jobs absolutos
    assert deltas == [200_000.0, -53_000.0], (
        f"deltas {deltas} no coinciden con escalado ×1000 esperado"
    )


def test_compute_changes_delta_absolute_no_scale():
    """Verifica que delta_absolute (sin _thousands) NO escala."""
    values = [("2024-01", 100.0), ("2024-02", 105.0)]
    deltas = compute_changes(values, "delta_absolute")
    assert deltas == [5.0]


# ===== σ por categoría — sanity check ranges =====

def test_sigma_jolts_in_absolute_jobs_units():
    """σ_JOLTS debe estar en jobs absolutos, no thousands."""
    cal = json.loads(Path("/home/administrator/poly_sidecar/macro_calendar.json").read_text())
    load_sigma_from_calendar(cal)
    sigma = get_sigma("JOLTS")
    # Sanity: JOLTS deltas mensuales típicos son ±300-500k jobs.
    # σ_robust en thousands sería ~300-400. En jobs absolutos: 300,000-500,000.
    assert 100_000 < sigma < 1_000_000, (
        f"σ_JOLTS={sigma} fuera de rango razonable en jobs absolutos"
    )


def test_sigma_nfp_in_absolute_jobs_units():
    """σ_NFP debe estar en jobs absolutos, no thousands."""
    cal = json.loads(Path("/home/administrator/poly_sidecar/macro_calendar.json").read_text())
    load_sigma_from_calendar(cal)
    sigma = get_sigma("NFP")
    assert 100_000 < sigma < 1_000_000, (
        f"σ_NFP={sigma} fuera de rango razonable en jobs absolutos"
    )


def test_all_calibrated_series_have_sigma():
    """Las 8 series principales tienen σ > 0."""
    cal = json.loads(Path("/home/administrator/poly_sidecar/macro_calendar.json").read_text())
    load_sigma_from_calendar(cal)
    expected = ["FOMC", "CPI", "NFP", "PCE", "GDP", "JOLTS", "ISM", "UNEMPLOYMENT"]
    for cat in expected:
        sigma = get_sigma(cat)
        assert sigma is not None and sigma > 0, f"{cat} sin σ válida"
