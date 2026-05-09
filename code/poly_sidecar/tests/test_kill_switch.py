"""Tests integración kill_switch — 13 escenarios firmados Gemma r108+r110.

8 base tests (r108):
  T1 — Spike alcista durante NFP window
  T2 — Crash bajista durante NFP window
  T3 — Spike falso single-source (consensus filtra)
  T4 — Spike fuera de ventana (NO trigger)
  T5 — Edge timing T-15min exact
  T6 — Insufficient samples
  T7 — Volatility no-monotónica (max-min en window)
  T8 — Auto-recovery condicional

5 black swan tests (r110):
  BS1 — COVID-flash crash sostenido
  BS2 — Whipsaw 30 segundos
  BS3 — Coordinated source collusion (forensic log)
  BS4 — Solana outage stale (Pyth fail, Coinbase+Kraken survive)
  BS5 — Black Wednesday drift sostenido

Run:
  cd /home/administrator/poly_sidecar
  venv/bin/python3 -m pytest tests/test_kill_switch.py -v
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from btc_feed import BTCBuffer, weighted_median, reject_outliers
from kill_switch import (
    check_btc_kill_switch,
    is_in_macro_event_window,
    check_consensus_health,
    check_manual_ack,
    check_auto_recovery,
    system_load_snapshot,
)


# ───────────────────────────────────────────────────────────────────
# FIXTURES & HELPERS
# ───────────────────────────────────────────────────────────────────

@pytest.fixture
def risk_config():
    """Lee risk_config.json real (firmado r93/r107/r108/r109/r110/r111)."""
    return json.loads(Path("/home/administrator/poly_sidecar/risk_config.json").read_text())


@pytest.fixture
def btc_buffer():
    """Buffer rolling fresh."""
    return BTCBuffer(retain_seconds=600.0)


@pytest.fixture
def fmp_nfp_now():
    """FMP upcoming events: NFP 'ahora' (en window)."""
    now_dt = time.gmtime()
    # Mock event 5 min en el futuro (dentro de la ventana pre-15min)
    ev_ts = time.time() + 5 * 60
    ev_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ev_ts))
    return [{
        "event": "Non-Farm Payrolls (NFP)",
        "category": "NFP",
        "date": ev_iso,
    }]


@pytest.fixture
def fmp_nfp_far_future():
    """FMP upcoming events: NFP en 5 horas (fuera de window)."""
    ev_ts = time.time() + 5 * 3600
    ev_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ev_ts))
    return [{
        "event": "Non-Farm Payrolls (NFP)",
        "category": "NFP",
        "date": ev_iso,
    }]


def make_consensus(price: float, sources_alive: int = 3, raw_per_source: dict | None = None):
    """Mock ConsensusResult-like object."""
    obj = MagicMock()
    obj.consensus_price = price
    obj.sources_contributing = sources_alive
    obj.is_stale = sources_alive < 2
    obj.last_update_ts = time.time()
    obj.raw_per_source = raw_per_source or {}
    return obj


# ───────────────────────────────────────────────────────────────────
# 8 BASE TESTS (firma r108)
# ───────────────────────────────────────────────────────────────────

class TestBase:
    """8 base tests del r108."""

    def test_T1_spike_alcista_durante_NFP(self, btc_buffer, risk_config, fmp_nfp_now):
        """T1: Spike +3% durante NFP window dispara CRITICAL."""
        # Pre-NFP: BTC stable a $81k
        now = time.time()
        for offset in range(-300, -60, 30):
            btc_buffer.push(now + offset, 81000.0)
        # Spike: $83.5k (+3.09%)
        btc_buffer.push(now, 83500.0)

        consensus = make_consensus(83500.0)
        result = check_btc_kill_switch(consensus, btc_buffer, risk_config, fmp_nfp_now)

        assert result["triggered"] == True, f"Spike +3% should trigger. Got: {result}"
        threshold = risk_config["risk_limits"]["kill_switch_pause_btc_move_pct"]
        assert result["btc_move_pct"] > threshold
        assert result["in_event_window"] == True
        assert result["matched_event"]["category"] == "NFP"

    def test_T2_crash_bajista_durante_NFP(self, btc_buffer, risk_config, fmp_nfp_now):
        """T2: Crash -3% dispara igualmente (move_pct es absoluto)."""
        now = time.time()
        for offset in range(-300, -60, 30):
            btc_buffer.push(now + offset, 81000.0)
        # Crash: $78.5k (-3.09%)
        btc_buffer.push(now, 78500.0)

        consensus = make_consensus(78500.0)
        result = check_btc_kill_switch(consensus, btc_buffer, risk_config, fmp_nfp_now)
        assert result["triggered"] == True
        assert result["btc_move_pct"] > 2.5

    def test_T3_spike_falso_single_source_consensus_filtra(self, btc_buffer, risk_config, fmp_nfp_now):
        """T3: Single-source diverge → outlier rejection lo descarta.

        Verifica que weighted_median + outlier rejection es resilient a
        single-source manipulation. Test directo de btc_feed lógica.
        """
        # Sources: 2 estables + 1 manipulada
        sources = {
            "coinbase": 81000.0,
            "kraken": 81100.0,
            "pyth": 85000.0,  # outlier 4.94%
        }
        filtered, rejected = reject_outliers(sources, threshold_pct=0.005)
        assert "pyth" in rejected
        assert len(filtered) == 2
        # weighted_median sobre filtered con weights re-normalizados
        weights = {"coinbase": 0.5, "kraken": 0.3}
        total_w = sum(weights.values())
        vw = [(filtered[k], weights[k] / total_w) for k in filtered]
        median = weighted_median(vw)
        assert 81000 <= median <= 81100  # No infectado por Pyth

    def test_T4_spike_fuera_de_ventana_NO_trigger(self, btc_buffer, risk_config, fmp_nfp_far_future):
        """T4: Spike +3% fuera de macro window → NO trigger."""
        now = time.time()
        for offset in range(-300, -60, 30):
            btc_buffer.push(now + offset, 81000.0)
        btc_buffer.push(now, 83500.0)

        consensus = make_consensus(83500.0)
        result = check_btc_kill_switch(consensus, btc_buffer, risk_config, fmp_nfp_far_future)
        assert result["triggered"] == False
        assert result["reason"] == "outside_macro_event_window"
        assert result["btc_move_pct"] > 2.5  # move existe pero no aplica

    def test_T5_edge_timing_T_minus_15min(self, btc_buffer, risk_config):
        """T5: Window armada exactly T-15min. T-14min59s YES, T-15min01s NO."""
        # Event en T+15min exacto (al borde)
        ev_ts = time.time() + 15 * 60
        ev_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ev_ts))
        events_in_edge = [{"event": "NFP", "category": "NFP", "date": ev_iso}]
        in_window, _ = is_in_macro_event_window(events_in_edge, ["NFP"], pre_min=15, post_min=30)
        assert in_window == True  # exactly at edge → in

        # Event en T+15min01s (fuera)
        ev_ts2 = time.time() + 15 * 60 + 5
        ev_iso2 = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(ev_ts2))
        events_outside = [{"event": "NFP", "category": "NFP", "date": ev_iso2}]
        in_window2, _ = is_in_macro_event_window(events_outside, ["NFP"], pre_min=15, post_min=30)
        assert in_window2 == False

    def test_T6_insufficient_samples(self, btc_buffer, risk_config, fmp_nfp_now):
        """T6: Buffer con 0 samples → returns None / no trigger."""
        # Buffer vacío
        consensus = make_consensus(81000.0)
        result = check_btc_kill_switch(consensus, btc_buffer, risk_config, fmp_nfp_now)
        # consensus push agrega 1 sample → aún insuficiente para max_move_pct (necesita >=2)
        # Después del primer push, max_move_pct con 1 sample = None
        assert result["triggered"] == False
        assert result["reason"] in ("insufficient_samples", "within_threshold")

    def test_T7_volatility_no_monotonica_max_minus_min(self, btc_buffer, risk_config, fmp_nfp_now):
        """T7: max-min en window detecta whipsaw incluso si vuelve a baseline."""
        now = time.time()
        # Sequence: 81 → 82.5 (+1.85%) → 80 (-3.0% from peak) → 81 (recovery)
        btc_buffer.push(now - 60, 81000.0)
        btc_buffer.push(now - 45, 82500.0)
        btc_buffer.push(now - 30, 80000.0)  # max-min = 82500-80000 = 3.125% del min
        btc_buffer.push(now - 15, 81000.0)  # vuelve baseline pero max_move ya capturado

        consensus = make_consensus(81000.0)
        result = check_btc_kill_switch(consensus, btc_buffer, risk_config, fmp_nfp_now)
        assert result["triggered"] == True
        assert result["btc_move_pct"] > 3.0  # max-min, no last-vs-first

    def test_T8_auto_recovery_condicional_target_CAUTELA(self, btc_buffer, risk_config, fmp_nfp_far_future):
        """T8: Auto-recovery target = CAUTELA (no NORMAL — firma r107 §4d)."""
        # Buffer con BTC estable últimos 30min (volatility <0.5%)
        now = time.time()
        for offset in range(-1800, 0, 30):  # 30min de samples
            btc_buffer.push(now + offset, 81000.0 + (offset % 100) * 0.5)  # ±0.05% jitter

        # kill_switch triggered hace 65 min
        triggered_at = now - 65 * 60

        recovery = check_auto_recovery(btc_buffer, risk_config, fmp_nfp_far_future, triggered_at)

        if recovery["can_recover"]:
            assert recovery["target_mode"] == "CAUTELA", "firma r107 §4d → CAUTELA, NEVER NORMAL"
            assert recovery["minutes_since_trigger"] >= 60


# ───────────────────────────────────────────────────────────────────
# 5 BLACK SWAN TESTS (firma r110)
# ───────────────────────────────────────────────────────────────────

class TestBlackSwan:
    """5 black swan tests del r110."""

    def test_BS1_COVID_flash_crash_sostenido(self, btc_buffer, risk_config, fmp_nfp_now):
        """BS1: Flash crash sostenido tipo COVID-March-2020 (-16% en 2min)."""
        now = time.time()
        # Pre-event: stable
        for offset in range(-300, -60, 30):
            btc_buffer.push(now + offset, 81000.0)
        # Crash secuencia
        btc_buffer.push(now - 60, 81000.0)
        btc_buffer.push(now - 30, 77500.0)  # -4.32%
        btc_buffer.push(now, 73800.0)         # -9.05% from peak
        btc_buffer.push(now + 30, 70200.0)    # acumulado

        consensus = make_consensus(73800.0)
        result = check_btc_kill_switch(consensus, btc_buffer, risk_config, fmp_nfp_now)
        assert result["triggered"] == True
        assert result["btc_move_pct"] > 4.0  # well above 2.5%

    def test_BS2_whipsaw_30_seconds(self, btc_buffer, risk_config, fmp_nfp_now):
        """BS2: Whipsaw violent 30s. 81 → 84.5 → 80.2 → 81."""
        now = time.time()
        btc_buffer.push(now - 30, 81000.0)
        btc_buffer.push(now - 25, 84500.0)
        btc_buffer.push(now - 20, 80200.0)
        btc_buffer.push(now - 15, 81000.0)
        btc_buffer.push(now, 81200.0)

        consensus = make_consensus(81200.0)
        result = check_btc_kill_switch(consensus, btc_buffer, risk_config, fmp_nfp_now)
        # max range: ($84500 - $80200) / $80200 = 5.36%
        assert result["triggered"] == True
        assert result["btc_move_pct"] > 5.0

    def test_BS3_coordinated_source_collusion_forensic_log(self, btc_buffer, risk_config, fmp_nfp_now):
        """BS3: 2 sources colluden alta + 1 baja. Outlier rejection da preferencia
        a los 2 colluded.

        Verifica que system es SAFE (dispara) pero registra forensic per-source.
        """
        now = time.time()
        for offset in range(-300, -60, 30):
            btc_buffer.push(now + offset, 81000.0)

        # Colluded: $85k (real es $81k)
        raw_per_source = {
            "coinbase": {"name": "coinbase", "price_usd": 81000, "fetch_ms": 100},
            "kraken": {"name": "kraken", "price_usd": 85000, "fetch_ms": 110},
            "pyth": {"name": "pyth", "price_usd": 85000, "fetch_ms": 90},
        }
        consensus = make_consensus(85000.0, sources_alive=2, raw_per_source=raw_per_source)
        btc_buffer.push(now, 85000.0)

        result = check_btc_kill_switch(consensus, btc_buffer, risk_config, fmp_nfp_now)
        assert result["triggered"] == True
        # Forensic log incluye per-source prices (firma r110 §2)
        assert result["forensic_per_source"] is not None
        assert "kraken" in result["forensic_per_source"]
        assert "system_load" in result and result["system_load"]["method"] == "psutil"

    def test_BS4_solana_outage_stale_consensus_continues(self, btc_buffer, risk_config, fmp_nfp_now):
        """BS4: Pyth muere (Solana outage). Coinbase+Kraken survive con 2/3."""
        now = time.time()
        for offset in range(-300, -60, 30):
            btc_buffer.push(now + offset, 81000.0)
        # 2 sources alive, Pyth dead
        consensus = make_consensus(83500.0, sources_alive=2)  # Coinbase+Kraken weighted
        btc_buffer.push(now, 83500.0)  # +3% real macro reaction

        result = check_btc_kill_switch(consensus, btc_buffer, risk_config, fmp_nfp_now)
        assert result["triggered"] == True  # 2 sources es suficiente, move detectado

    def test_BS5_black_wednesday_drift_sostenido(self, btc_buffer, risk_config, fmp_nfp_now):
        """BS5: Drift sostenido sin spike puntual (Black Wednesday)."""
        now = time.time()
        # Drift gradual -3.7% en 6 minutos
        # Solo los últimos 5 min cuentan en max_move window
        prices = [
            (now - 360, 81000),
            (now - 300, 80400),  # entry of 5min window
            (now - 240, 79800),
            (now - 180, 79200),
            (now - 120, 78600),
            (now - 60, 78000),
            (now, 77400),
        ]
        for ts, p in prices:
            btc_buffer.push(ts, p)

        consensus = make_consensus(77400.0)
        result = check_btc_kill_switch(consensus, btc_buffer, risk_config, fmp_nfp_now)
        # En 5min window: max=80400, min=77400 → 3.88% drift
        assert result["triggered"] == True
        assert result["btc_move_pct"] > 3.0


# ───────────────────────────────────────────────────────────────────
# Sanity tests adicionales (no son los 13, son verificación deps)
# ───────────────────────────────────────────────────────────────────

class TestDependencies:
    def test_psutil_available(self):
        load = system_load_snapshot()
        assert load["method"] == "psutil"

    def test_consensus_health_stale_when_sources_below_min(self):
        """firma r109 §1b: sources_alive < 2 → stale."""
        consensus_1source = make_consensus(81000.0, sources_alive=1)
        risk_config = {"risk_limits": {}}
        health = check_consensus_health(consensus_1source, risk_config)
        assert health == "stale"

    def test_consensus_health_healthy_when_recent_and_2plus_sources(self):
        consensus_3sources = make_consensus(81000.0, sources_alive=3)
        risk_config = {"risk_limits": {}}
        health = check_consensus_health(consensus_3sources, risk_config)
        assert health == "healthy"

    def test_manual_ack_no_file_returns_unack(self):
        config = {"risk_limits": {"manual_ack_path": "/tmp/nonexistent_xxx_ack"}}
        result = check_manual_ack(config)
        assert result["acknowledged"] == False
