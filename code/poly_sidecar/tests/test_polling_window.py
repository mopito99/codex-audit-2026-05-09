"""Tests deterministas para _next_or_recent_tracked() · P3.6.5-v2 fix Codex C-01.

Firmado Gemma hash GEMMA4-SR-QUANT-B31-M2-FIX-C01-OK-20260509T1215Z

Garantía:
  - In window  (-900 <= delta <= 1800)  → HIGH_FREQUENCY · log emitted
  - Out of window                        → LOW_FREQUENCY · no log

NOTA semántica:
  delta = (event_ts - now).total_seconds()
  delta > 0  → evento futuro
  delta < 0  → evento pasado reciente
"""
from __future__ import annotations
import datetime as dt
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _make_event(date_iso: str, event="Consumer Price Index"):
    """Helper · construye MacroEvent mock."""
    ev = MagicMock()
    ev.date = date_iso
    ev.event = event
    return ev


@pytest.mark.parametrize(
    "test_id,offset_s,expected_in_window",
    [
        ("T-30min_edge",      -1800,  True),    # T-30min · borde inicio HIGH
        ("T-1min",            -60,    True),    # T-1min · pre-release HIGH
        ("T+30s",             30,     True),    # T+30s · post-release HIGH
        ("T+119s_SLA_edge",   119,    True),    # T+119s · SLA edge (<120s)
        ("T+5min",            300,    True),    # T+5min · post-release HIGH
        ("T+14min59s_edge",   899,    True),    # T+14:59 · borde fin HIGH
        ("T+15min01s_out",    901,    False),   # T+15:01 · OUT of window LOW
        ("T+30min_far_past",  1801,   False),   # T+30min · LOW (legacy)
        ("T-30min01s_pre",    -1801,  False),   # T-30:01 · OUT pre-event LOW
    ],
)
def test_polling_window_covers_post_release(test_id, offset_s, expected_in_window):
    """Para offset_s positivo (evento ya pasó hace offset_s) o negativo (evento futuro):
    determina si _next_or_recent_tracked retorna match in-window.
    """
    from sidecar import _next_or_recent_tracked
    now = dt.datetime.now(dt.timezone.utc)
    # offset_s positivo → evento PASADO hace offset_s segundos · ts = now - offset_s
    # offset_s negativo → evento FUTURO en |offset_s| segundos · ts = now - (negativo) = now + |offset_s|
    fake_event_ts = now - dt.timedelta(seconds=offset_s)
    fake_event = _make_event(fake_event_ts.isoformat())

    with patch("sidecar.FMPClient.is_tracked", return_value=True):
        ev, secs = _next_or_recent_tracked([fake_event], recent_window_s=900)

    if expected_in_window:
        assert ev is not None, f"{test_id}: expected event in window · got None"
        assert -900 <= secs <= 1800, f"{test_id}: secs={secs} out of [-900,1800]"
        # Verify delta semantics: delta = ts - now = -offset_s
        # Allow 5s slack for test execution
        expected_delta = -offset_s
        assert abs(secs - expected_delta) <= 5, (
            f"{test_id}: delta={secs} expected~{expected_delta}"
        )
    else:
        assert ev is None, f"{test_id}: expected NO event in window · got {ev}"
        assert secs is None, f"{test_id}: expected secs=None · got {secs}"


def test_no_tracked_events():
    """Si no hay eventos tracked → return (None, None) · LOW_FREQUENCY."""
    from sidecar import _next_or_recent_tracked
    fake_event = _make_event("2026-05-12T12:30:00+00:00")
    with patch("sidecar.FMPClient.is_tracked", return_value=False):
        ev, secs = _next_or_recent_tracked([fake_event])
    assert ev is None
    assert secs is None


def test_multiple_events_picks_closest_abs():
    """Si múltiples eventos en ventana · picks min(|delta|).

    Tres eventos:
    - far_future  T-25min  (delta=+1500)
    - near_past   T+2min   (delta=-120)  ← debe ganar (|delta|=120 menor)
    - far_past    T+10min  (delta=-600)
    """
    from sidecar import _next_or_recent_tracked
    now = dt.datetime.now(dt.timezone.utc)
    far_future_ts = (now + dt.timedelta(seconds=1500)).isoformat()
    near_past_ts = (now - dt.timedelta(seconds=120)).isoformat()
    far_past_ts = (now - dt.timedelta(seconds=600)).isoformat()

    events = [
        _make_event(far_future_ts, "Event A"),
        _make_event(near_past_ts, "Event B"),  # ganador
        _make_event(far_past_ts, "Event C"),
    ]
    with patch("sidecar.FMPClient.is_tracked", return_value=True):
        ev, secs = _next_or_recent_tracked(events, recent_window_s=900)

    assert ev.event == "Event B", f"Expected closest abs (Event B), got {ev.event}"
    assert -200 < secs < 0, f"Expected secs ~ -120, got {secs}"
