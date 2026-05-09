"""r125 firma Gemma — Synthetic injection layer (Opción B).

Provee módulo de estado para inject sintético del macro state durante stress
tests. Cumple los 4 condicionantes técnicos firmados:

  1. Atomicidad del lock: threading.Lock SOLO para writes, reads sin lock.
  2. Trazabilidad: injection_id + injection_time_utc propagated downstream.
  3. Auto-cleanup: TTL expiry on read + polling-tick-wins on real data fresh.
  4. Validación warmup: API expone synthetic_status() para pre-test check.

Activación: requiere LIQ_SIDECAR_TEST_MODE=1 al startup del sidecar.
"""
from __future__ import annotations
import os
import threading
import time
import uuid
from typing import Any

# Gate: solo activable si env var setteada al startup
TEST_MODE_ENABLED: bool = os.environ.get("LIQ_SIDECAR_TEST_MODE") == "1"

# Estado del override (None = no active). Module-global, write-locked.
_override: dict | None = None
_lock = threading.Lock()


def is_test_mode() -> bool:
    """True si LIQ_SIDECAR_TEST_MODE=1 al startup."""
    return TEST_MODE_ENABLED


def inject(payload: dict) -> dict:
    """Atomic write of synthetic override (condición #1). Solo bajo lock.

    Validates payload + computes expires_at + sets state. Returns the response
    payload (incluyendo injection_time_utc para trazabilidad #2).
    """
    if not TEST_MODE_ENABLED:
        raise RuntimeError("LIQ_SIDECAR_TEST_MODE!=1 — injection disabled")

    # Validation
    iid = payload.get("injection_id")
    if not iid or len(str(iid)) > 64:
        raise ValueError("injection_id required (≤64 chars)")
    btc = payload.get("btc_price_usd")
    if not isinstance(btc, (int, float)) or btc <= 0:
        raise ValueError("btc_price_usd must be positive number")
    mode = payload.get("mode", "")
    valid_modes = {"NORMAL", "CAUTELA", "DEFENSIVO", "FREEZE", "CAPTURE", "CRITICAL"}
    if mode not in valid_modes:
        raise ValueError(f"mode must be in {valid_modes}, got {mode!r}")
    ttl = payload.get("ttl_seconds", 30)
    if not isinstance(ttl, int) or ttl < 1 or ttl > 120:
        raise ValueError("ttl_seconds must be int 1..120")

    now = time.time()
    expires_at = now + float(ttl)
    injection_time_utc = time.strftime(
        "%Y-%m-%dT%H:%M:%S", time.gmtime(now)
    ) + f".{int((now % 1) * 1_000_000):06d}Z"

    new_override = {
        "injection_id": iid,
        "injection_time_utc": injection_time_utc,
        "injection_time_unix": now,
        "expires_at": expires_at,
        "is_synthetic": True,
        "btc_price_usd": float(btc),
        "tau_final": float(payload.get("tau_final", 0.85)),
        "tau_macro": float(payload.get("tau_macro", 0.85)),
        "tau_crypto": float(payload.get("tau_crypto", 0.50)),
        "rho": payload.get("rho"),
        "rho_divergence_active": bool(payload.get("rho_divergence_active", False)),
        "mode": mode,
        "mode_reason": payload.get("mode_reason", "synthetic_test"),
    }

    # Atomic write only — read path is lock-free
    with _lock:
        global _override
        _override = new_override

    return {
        "ok": True,
        "injection_id": iid,
        "injection_time_utc": injection_time_utc,
        "expires_at_utc": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(expires_at)
        ),
        "is_synthetic": True,
        "ttl_seconds": ttl,
    }


def maybe_apply(state_dict: dict) -> dict:
    """Lock-free read path (condición #1). Returns state with override
    applied if active and not expired (condición #3 path A).

    Mutates NOTHING — returns new dict if override applied, else original ref.
    """
    o = _override  # atomic read of the reference
    if o is None:
        return state_dict
    now = time.time()
    if now > o.get("expires_at", 0):
        # Expired — let the polling loop clean it (path B). Return real state.
        return state_dict
    # Apply override to a NEW dict (do not mutate state_dict)
    out = dict(state_dict)
    out.update({
        "btc_price_usd": o["btc_price_usd"],
        "tau_final": o["tau_final"],
        "tau_macro": o["tau_macro"],
        "tau_crypto": o["tau_crypto"],
        "rho": o["rho"],
        "rho_divergence_active": o["rho_divergence_active"],
        "mode": o["mode"],
        "mode_reason": o["mode_reason"],
        "is_synthetic": True,
        "injection_id": o["injection_id"],
        "injection_time_utc": o["injection_time_utc"],
    })
    return out


def clear_on_polling_tick() -> bool:
    """Auto-cleanup path B (condición #3): real data wins.

    Llamado por sidecar.py main loop después de cada polling tick exitoso.
    Si hay override active, lo limpia (la realidad sobreescribe simulación).
    Returns True si limpió algo, False si no había override.
    """
    with _lock:
        global _override
        if _override is not None:
            _override = None
            return True
        return False


def status() -> dict:
    """Estado actual del override. Para validación de warmup (#4) y debug."""
    o = _override
    if o is None:
        return {
            "test_mode_enabled": TEST_MODE_ENABLED,
            "override_active": False,
        }
    now = time.time()
    expired = now > o.get("expires_at", 0)
    return {
        "test_mode_enabled": TEST_MODE_ENABLED,
        "override_active": not expired,
        "expired": expired,
        "injection_id": o.get("injection_id"),
        "injection_time_utc": o.get("injection_time_utc"),
        "expires_at_unix": o.get("expires_at"),
        "seconds_until_expiry": max(0, o.get("expires_at", 0) - now),
        "mode": o.get("mode"),
        "btc_price_usd": o.get("btc_price_usd"),
    }
