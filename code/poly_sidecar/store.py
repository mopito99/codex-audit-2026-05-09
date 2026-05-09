"""Atomic store backend — file-based for now (Redis pluggable when installed).

Atomic write semantics: write to .tmp then os.rename (atomic on POSIX).
Readers always see a consistent snapshot or the previous one.

Schema written to /home/administrator/poly_sidecar/data/tau_state.json:
  {
    "tau_final": 0.42,
    "tau_macro": 0.31,
    "tau_crypto": 0.48,
    "rho": -0.55,
    "heartbeat_ts": 1715000000.0,
    "polling_interval_s": 300,
    "last_error": null,
    "endpoints_health": {
      "markets": {"errors": 0, "last_ok": 1715...},
      "midpoint": {...}, "spread": {...}, "history": {...}
    },
    "per_contract": [
      {"market_id":"...", "category":"FOMC", "tau": 0.5, "delta_prob": 0.1,
       "vol_zscore": 1.2, "implied_vol": 0.03, "valid": true}
    ]
  }
"""
from __future__ import annotations
import json
import os
import time
from pathlib import Path
from typing import Any

DATA_DIR = Path("/home/administrator/poly_sidecar/data")
STATE_FILE = DATA_DIR / "tau_state.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def write(state: dict[str, Any]) -> None:
    """Atomic write — temp + rename."""
    state.setdefault("heartbeat_ts", time.time())
    tmp = STATE_FILE.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump(state, f, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.rename(tmp, STATE_FILE)


def read() -> dict[str, Any] | None:
    """Returns last state or None if missing/corrupt."""
    if not STATE_FILE.exists():
        return None
    try:
        with STATE_FILE.open() as f:
            return json.load(f)
    except Exception:
        return None


def heartbeat_age_seconds() -> float | None:
    s = read()
    if not s:
        return None
    ts = s.get("heartbeat_ts")
    if ts is None:
        return None
    return time.time() - float(ts)


def is_stale(max_age_seconds: int = 600) -> bool:
    """True if heartbeat older than max_age_seconds (default 10min per Gemma)."""
    age = heartbeat_age_seconds()
    return age is None or age > max_age_seconds
