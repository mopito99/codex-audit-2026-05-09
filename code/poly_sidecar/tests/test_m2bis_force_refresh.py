"""Tests M2-bis · BLS force_refresh durante macro window.

Firmado Gemma · Codex CRITICAL-NEW-02 fix
"""
from __future__ import annotations
import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _mock_obs(year, period, value, period_name=None):
    """Helper · construye BLSObservation mock."""
    from bls_client import BLSObservation
    return BLSObservation(
        series_id="CUUR0000SA0",
        year=year,
        period=period,
        period_name=period_name or period,
        value=value,
        is_latest=False,
        is_preliminary=False,
    )


def test_force_refresh_bypasses_cache():
    """force_refresh=True debe llamar fetch_series() aunque haya cache válido."""
    from bls_client import BLSClient

    cli = BLSClient()
    fake_obs = [
        _mock_obs(2026, "M03", 330.213, "March"),
        _mock_obs(2026, "M02", 326.785, "February"),
        _mock_obs(2025, "M03", 320.0, "March"),
    ]

    fetch_call_count = [0]
    def mock_fetch_series(self, series_id, **kw):
        fetch_call_count[0] += 1
        self._cache[series_id] = fake_obs
        self._last_sync_ts = time.time()
        return fake_obs

    with patch.object(BLSClient, "fetch_series", mock_fetch_series):
        # Primera llamada · cache miss · 1 fetch
        cli.get_latest_actual("CPI")
        assert fetch_call_count[0] == 1

        # Segunda llamada SIN force · cache hit · NO fetch
        cli.get_latest_actual("CPI")
        assert fetch_call_count[0] == 1, "cache hit esperado · no debe fetch"

        # Tercera llamada CON force_refresh=True · BYPASS cache · fetch
        cli.get_latest_actual("CPI", force_refresh=True)
        assert fetch_call_count[0] == 2, "force_refresh debe forzar fetch"

        # Cuarta llamada SIN force tras force · cache válido · NO fetch
        cli.get_latest_actual("CPI")
        assert fetch_call_count[0] == 2, "cache válido tras force · no debe fetch"


def test_force_refresh_5_calls_5_http():
    """5x force_refresh=True → 5 fetch_series calls (cero cache hits)."""
    from bls_client import BLSClient

    cli = BLSClient()
    fake_obs = [
        _mock_obs(2026, "M03", 330.213, "March"),
        _mock_obs(2026, "M02", 326.785, "February"),
        _mock_obs(2025, "M03", 320.0, "March"),
    ]

    fetch_call_count = [0]
    def mock_fetch_series(self, series_id, **kw):
        fetch_call_count[0] += 1
        self._cache[series_id] = fake_obs
        self._last_sync_ts = time.time()
        return fake_obs

    with patch.object(BLSClient, "fetch_series", mock_fetch_series):
        for _ in range(5):
            cli.get_latest_actual("CPI", force_refresh=True)

    assert fetch_call_count[0] == 5, (
        f"5x force_refresh=True debe = 5 fetch calls · got {fetch_call_count[0]}"
    )


def test_default_low_frequency_caches_correctly():
    """Sin force_refresh · 5 calls = 1 fetch (cache hits)."""
    from bls_client import BLSClient

    cli = BLSClient()
    fake_obs = [
        _mock_obs(2026, "M03", 330.213, "March"),
        _mock_obs(2026, "M02", 326.785, "February"),
        _mock_obs(2025, "M03", 320.0, "March"),
    ]

    fetch_call_count = [0]
    def mock_fetch_series(self, series_id, **kw):
        fetch_call_count[0] += 1
        self._cache[series_id] = fake_obs
        self._last_sync_ts = time.time()
        return fake_obs

    with patch.object(BLSClient, "fetch_series", mock_fetch_series):
        for _ in range(5):
            cli.get_latest_actual("CPI")  # default force_refresh=False

    assert fetch_call_count[0] == 1, (
        f"5x default · 1 fetch (cache hits 4) · got {fetch_call_count[0]}"
    )


def test_force_refresh_returns_data_correctly():
    """force_refresh debe retornar el mismo formato dict que sin force."""
    from bls_client import BLSClient

    cli = BLSClient()
    fake_obs = [
        _mock_obs(2026, "M03", 330.213, "March"),
        _mock_obs(2026, "M02", 326.785, "February"),
        _mock_obs(2025, "M03", 320.0, "March"),
    ]

    def mock_fetch_series(self, series_id, **kw):
        self._cache[series_id] = fake_obs
        self._last_sync_ts = time.time()
        return fake_obs

    with patch.object(BLSClient, "fetch_series", mock_fetch_series):
        normal = cli.get_latest_actual("CPI")
        forced = cli.get_latest_actual("CPI", force_refresh=True)

    assert normal is not None
    assert forced is not None
    # Mismo schema
    for k in ("category", "series_id", "latest_year", "latest_period",
              "latest_value", "actual_for_sf", "yoy_pct_change"):
        assert k in normal, f"normal missing {k}"
        assert k in forced, f"forced missing {k}"
    # Misma data (mock idéntico)
    assert normal["yoy_pct_change"] == forced["yoy_pct_change"]
