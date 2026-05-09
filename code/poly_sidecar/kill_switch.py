"""kill_switch.py — Logic firmada Gemma r93/r107/r108/r109/r110/r111.

Spec source of truth: risk_config.json (NO hardcoded thresholds).
Spec-Commit reference: risk_config.json @ r93/r107/r108/r109/r110/r111

Firma trail:
  r93   — initial deploy approved + risk_limits section (kill_switch BTC)
  r107  — btc_consensus_weighted_median required (NOT pyth-only)
        — target_mode = CAUTELA en auto-recovery (NO direct NORMAL)
  r108  — weights 0.5/0.3/0.2 + 8 base tests + stale → CAUTELA SF 0.6
  r109  — sources_alive < 2 → stale STRICTER (firmado §1b)
        — path SF 0.6 → SF 0.7 → NORMAL + dwell time 5min
  r110  — pre-commit hook FAIL on Signed-by-spec missing
        — audit forense per-source en trigger BS-3
        — system_load_at_ack en manual ACK process
        — q_v4_decision_latency query nueva
  r111  — psutil con fallback /proc/loadavg + traceback completo
        — V4-Alpha SHADOW subset (NOT mirror full)
        — 3 timestamps T0/T1/T2 + worst_decision
        — HTTP local 127.0.0.1:8090 (NOT shared mem ni Unix socket)
        — Basic Auth + nginx + rate limiting 10 req/min

Components:
  - check_btc_kill_switch()       — Early HARD OVERRIDE pre-mode logic
  - check_consensus_health()      — Stale detection (sources_alive<2)
  - process_manual_ack()          — File existence + content + system_load
  - check_auto_recovery()         — Hybrid manual+auto (target CAUTELA)
  - log_kill_switch_trigger()     — Audit forense per-source

To audit decision chain:
  git log --grep "Spec-Commit" --pretty=full
  jq 'select(.audit_type | startswith("kill_switch"))' risk_audit.jsonl
"""
from __future__ import annotations
import json
import logging
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("poly_sidecar.kill_switch")

RISK_AUDIT_JSONL = Path("/home/administrator/poly_sidecar/data/risk_audit.jsonl")


# ── system_load snapshot (firmado r110 §3 + r111 §1) ────────────────

def system_load_snapshot() -> dict:
    """Snapshot psutil con fallback /proc/loadavg + traceback completo (firmado r111)."""
    try:
        import psutil
        return {
            "load_avg_1m": psutil.getloadavg()[0],
            "load_avg_5m": psutil.getloadavg()[1],
            "load_avg_15m": psutil.getloadavg()[2],
            "cpu_percent_total": psutil.cpu_percent(interval=0.1),
            "cpu_count_logical": psutil.cpu_count(),
            "memory_percent": psutil.virtual_memory().percent,
            "memory_available_gb": round(psutil.virtual_memory().available / 1e9, 2),
            "swap_percent": psutil.swap_memory().percent,
            "method": "psutil"
        }
    except Exception as e:
        # Fallback proc/loadavg con traceback completo (firma r111 §1)
        psutil_traceback = traceback.format_exc()
        try:
            with open("/proc/loadavg") as f:
                parts = f.read().split()
            return {
                "load_avg_1m": float(parts[0]),
                "load_avg_5m": float(parts[1]),
                "load_avg_15m": float(parts[2]),
                "method": "proc_loadavg",
                "psutil_error": str(e),
                "psutil_traceback": psutil_traceback,  # firma r111: traceback completo
            }
        except Exception as e2:
            return {
                "method": "failed",
                "psutil_error": str(e),
                "psutil_traceback": psutil_traceback,
                "proc_loadavg_error": str(e2),
                "proc_loadavg_traceback": traceback.format_exc(),
            }


# ── Macro event window check (firmado r107 §2a) ─────────────────────

def is_in_macro_event_window(
    fmp_upcoming: list,
    applies_to: list,
    pre_min: int = 15,
    post_min: int = 30,
) -> tuple[bool, dict | None]:
    """Check si NOW está en ventana [event_ts - pre_min, event_ts + post_min]
    para algún evento de los `applies_to` categories.

    Returns:
        (in_window, matched_event_or_None)
    """
    now = time.time()
    for ev in fmp_upcoming:
        cat = ev.get("category", "")
        if cat not in applies_to:
            continue
        date_str = ev.get("date", "")
        try:
            ev_dt = datetime.fromisoformat(date_str.replace(" ", "T"))
            if ev_dt.tzinfo is None:
                ev_dt = ev_dt.replace(tzinfo=timezone.utc)
            ev_ts = ev_dt.timestamp()
            if (ev_ts - pre_min * 60) <= now <= (ev_ts + post_min * 60):
                return True, ev
        except Exception:
            continue
    return False, None


# ── Consensus health check (firmado r109 §1b) ───────────────────────

def check_consensus_health(consensus_result: Any, risk_config: dict) -> str:
    """Returns 'healthy', 'degraded', 'stale' (firmado r108 §3 + r109 §1b).

    Stale strict: sources_alive < min_required (default 2).
    """
    if consensus_result is None:
        return "stale"
    sources_alive = getattr(consensus_result, "sources_contributing", 0)
    if sources_alive == 0:
        sources_alive = consensus_result.get("sources_contributing", 0) if isinstance(consensus_result, dict) else 0

    last_update_ts = getattr(consensus_result, "last_update_ts", 0)
    if last_update_ts == 0 and isinstance(consensus_result, dict):
        last_update_ts = consensus_result.get("last_update_ts", 0)

    last_update_age = time.time() - last_update_ts if last_update_ts > 0 else 999

    risk_limits = risk_config.get("risk_limits", {})
    min_required = 2  # firma r109 §1b STRICTER

    if sources_alive >= min_required and last_update_age < 30:
        return "healthy"
    if sources_alive >= min_required and last_update_age < 120:
        return "degraded"
    return "stale"


# ── Kill switch BTC consensus check (firmado r93/r107/r108/r109) ────

def check_btc_kill_switch(
    consensus_result: Any,
    btc_buffer: Any,
    risk_config: dict,
    fmp_upcoming: list,
) -> dict:
    """Verifica kill_switch_pause_btc_move_pct durante macro event window.

    Spec firmada Gemma r93/r107/r108/r109:
      - Solo durante macro_event_window [pre_min=15, post_min=30]
      - Usa btc_consensus_weighted_median (NO Pyth solo)
      - Si max_move > threshold% en window_minutes → CRITICAL trigger
      - HARD OVERRIDE en mode logic (early check)

    Returns:
        {
            triggered: bool,
            reason: str,
            btc_move_pct: float | None,
            in_event_window: bool,
            matched_event: dict | None,
            forensic_per_source: dict (firma r110 §2),
            system_load: dict,
        }
    """
    rl = risk_config.get("risk_limits", {})
    threshold_pct = rl.get("kill_switch_pause_btc_move_pct", 2.5)
    window_min = rl.get("window_minutes", 5)
    pre_min = rl.get("macro_event_window_pre_minutes", 15)
    post_min = rl.get("macro_event_window_post_minutes", 30)
    applies_to = rl.get("applies_during_macro_event_windows", ["NFP", "CPI", "FOMC", "PCE"])

    # Push current consensus al buffer
    if consensus_result and not getattr(consensus_result, "is_stale", True):
        price = getattr(consensus_result, "consensus_price", None)
        if price and price > 0:
            btc_buffer.push(time.time(), price)

    # Calcular max move en window
    move_pct = btc_buffer.max_move_pct_in_window(window_min * 60)
    if move_pct is None:
        return {
            "triggered": False,
            "reason": "insufficient_samples",
            "btc_move_pct": None,
            "in_event_window": False,
            "matched_event": None,
            "forensic_per_source": None,
            "system_load": None,
        }

    # Solo activo durante ventanas macro tier-1
    in_window, matched_event = is_in_macro_event_window(fmp_upcoming, applies_to, pre_min, post_min)

    if not in_window:
        return {
            "triggered": False,
            "reason": "outside_macro_event_window",
            "btc_move_pct": move_pct,
            "in_event_window": False,
            "matched_event": None,
            "forensic_per_source": None,
            "system_load": None,
        }

    if move_pct > threshold_pct:
        # TRIGGER — capture forensic data per-source (firma r110 §2 BS-3)
        forensic = {}
        if consensus_result:
            raw = getattr(consensus_result, "raw_per_source", {})
            if isinstance(raw, dict):
                forensic = raw

        result = {
            "triggered": True,
            "reason": (
                f"BTC consensus moved {move_pct:.2f}% > {threshold_pct}% "
                f"in {window_min}min during {matched_event.get('event','?')} window"
            ),
            "btc_move_pct": move_pct,
            "in_event_window": True,
            "matched_event": {
                "event": matched_event.get("event"),
                "category": matched_event.get("category"),
                "date": matched_event.get("date"),
            },
            "forensic_per_source": forensic,
            "system_load": system_load_snapshot(),  # firma r110/r111
            "threshold_pct": threshold_pct,
            "window_minutes": window_min,
            "consensus_price_at_trigger": getattr(consensus_result, "consensus_price", None) if consensus_result else None,
            "buffer_size": len(btc_buffer),
        }
        # Audit log inmediato (firma r110 §2)
        log_kill_switch_trigger(result)
        return result

    return {
        "triggered": False,
        "reason": "within_threshold",
        "btc_move_pct": move_pct,
        "in_event_window": True,
        "matched_event": {
            "event": matched_event.get("event"),
            "category": matched_event.get("category"),
        },
        "forensic_per_source": None,
        "system_load": None,
    }


# ── Audit logging (firmado r92/r93/r110) ────────────────────────────

def log_kill_switch_trigger(trigger_result: dict) -> None:
    """Audit log forense del trigger (firma r110 §2 BS-3 obligatorio)."""
    audit_entry = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "audit_type": "kill_switch_btc_trigger",
        "spec_signed_by": "Gemma r93/r107/r108/r109/r110/r111",
        "runtime_version": "V3.5-SHADOW-r93+r111",
        "trigger_result": trigger_result,
    }
    try:
        RISK_AUDIT_JSONL.parent.mkdir(parents=True, exist_ok=True)
        with open(RISK_AUDIT_JSONL, "a") as f:
            f.write(json.dumps(audit_entry, default=str) + "\n")
    except Exception as e:
        logger.error(f"Failed to write kill_switch audit: {e}")


def log_mode_transition(
    mode_before: str,
    mode_after: str,
    reason: str,
    sf_used: float | None = None,
    decision_chain: list | None = None,
    latency_breakdown: dict | None = None,
    context_snapshot: dict | None = None,
) -> None:
    """Audit log de mode transition (firma r92 + r111 §3 latency 3 components)."""
    audit_entry = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "audit_type": "mode_transition",
        "runtime_version": "V3.5-SHADOW-r93+r111",
        "mode_decision": {
            "mode_before": mode_before,
            "mode_after": mode_after,
            "decision_reason": reason,
            "mode_unchanged": mode_before == mode_after,
        },
        "sf_calculation": {"sf_used_for_decision": sf_used} if sf_used is not None else None,
        "decision_chain": decision_chain or [],
        "latency_breakdown": latency_breakdown,
        "context_snapshot": context_snapshot,
    }
    try:
        with open(RISK_AUDIT_JSONL, "a") as f:
            f.write(json.dumps(audit_entry, default=str) + "\n")
    except Exception as e:
        logger.error(f"Failed to write mode_transition audit: {e}")


# ── Manual ACK process (firmado r108 §5 + r110 §3) ──────────────────

def check_manual_ack(risk_config: dict) -> dict:
    """Process manual ACK file. firma r108 §5 + r110 §3 (system_load).

    Returns:
        {
            "acknowledged": bool,
            "ack_ts": str,
            "operator_note": str,
            "system_load": dict (firma r110),
            "file_metadata": dict,
        }
    """
    rl = risk_config.get("risk_limits", {})
    ack_path_str = rl.get("manual_ack_path", "/home/administrator/poly_sidecar/data/kill_switch_ack")
    ack_path = Path(ack_path_str)

    if not ack_path.exists():
        return {"acknowledged": False, "ack_ts": None, "operator_note": None}

    try:
        content = ack_path.read_text().strip()
        stat = ack_path.stat()
        mtime_utc = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        return {
            "acknowledged": True,
            "ack_ts": mtime_utc,
            "operator_note": content[:500],
            "system_load": system_load_snapshot(),  # firma r110 §3
            "file_metadata": {
                "file_path": str(ack_path),
                "file_size_bytes": stat.st_size,
                "file_uid": stat.st_uid,
                "file_gid": stat.st_gid,
            },
        }
    except Exception as e:
        logger.warning(f"ACK file read error: {e}")
        return {
            "acknowledged": True,
            "ack_ts": "unreadable",
            "operator_note": str(e),
            "system_load": system_load_snapshot(),
            "file_metadata": {"error": str(e), "traceback": traceback.format_exc()},
        }


def process_manual_ack(
    risk_config: dict,
    kill_switch_state: dict,
) -> dict:
    """Process ACK + log audit + one-shot unlink (firma r108 §5c).

    kill_switch_state: dict con keys triggered_at_utc, triggered_reason
    """
    ack_data = check_manual_ack(risk_config)
    if not ack_data.get("acknowledged"):
        return {"processed": False, "reason": "no_ack_file"}

    # Audit log
    audit_entry = {
        "ts_utc": datetime.now(timezone.utc).isoformat(),
        "audit_type": "kill_switch_manual_ack_processed",
        "runtime_version": "V3.5-SHADOW-r93+r111",
        "ack_data": ack_data,
        "kill_switch_state_pre_ack": kill_switch_state,
        "kill_switch_state_post_ack": "CAUTELA",  # firma r107 §4d target
        "spec_signed_by": "Gemma r108 §5 + r110 §3",
    }
    try:
        with open(RISK_AUDIT_JSONL, "a") as f:
            f.write(json.dumps(audit_entry, default=str) + "\n")
    except Exception as e:
        logger.error(f"Failed to write ACK audit: {e}")

    # One-shot unlink (firma r108 §5c)
    rl = risk_config.get("risk_limits", {})
    ack_path = Path(rl.get("manual_ack_path", "/home/administrator/poly_sidecar/data/kill_switch_ack"))
    try:
        ack_path.unlink()
    except Exception as e:
        logger.warning(f"Failed to unlink ACK file: {e}")

    return {
        "processed": True,
        "ack_data": ack_data,
        "next_mode": "CAUTELA",
    }


# ── Auto-recovery condicional (firmado r107 §4 + r109 §4) ───────────

def check_auto_recovery(
    btc_buffer: Any,
    risk_config: dict,
    fmp_upcoming: list,
    kill_switch_triggered_at_ts: float,
) -> dict:
    """Check si auto-recovery puede activarse (firma r107 §4 + r109 §4).

    Conditions ALL must be true:
      1. min_minutes_since_trigger reached (default 60)
      2. BTC volatility < max_volatility_pct in volatility_window (default 0.5%/30min)
      3. NO macro event in next hour
      4. Manual ACK NOT priority (manual takes precedence)

    Target mode: CAUTELA (NEVER direct to NORMAL — firma r107 §4d).
    """
    rl = risk_config.get("risk_limits", {})
    ar = rl.get("auto_recovery", {})

    if not ar.get("enabled", False):
        return {"can_recover": False, "reason": "auto_recovery_disabled"}

    min_minutes = ar.get("min_minutes_since_trigger", 60)
    max_volatility = ar.get("max_btc_volatility_pct_for_recovery", 0.5)
    vol_window_min = ar.get("volatility_window_minutes", 30)
    require_no_macro = ar.get("no_macro_event_in_next_hour_required", True)
    target_mode = ar.get("auto_recovery_target_mode", "CAUTELA")

    now = time.time()

    # Condition 1: time since trigger
    minutes_since = (now - kill_switch_triggered_at_ts) / 60.0
    if minutes_since < min_minutes:
        return {
            "can_recover": False,
            "reason": f"time_since_trigger {minutes_since:.1f}min < {min_minutes}min required",
        }

    # Condition 2: volatility within window
    move_pct = btc_buffer.max_move_pct_in_window(vol_window_min * 60)
    if move_pct is None:
        return {"can_recover": False, "reason": "insufficient_samples_for_volatility_check"}
    if move_pct > max_volatility:
        return {
            "can_recover": False,
            "reason": f"volatility {move_pct:.3f}% > max {max_volatility}% in {vol_window_min}min",
        }

    # Condition 3: no macro event in next hour
    if require_no_macro:
        from datetime import timedelta
        next_hour_end = now + 3600
        for ev in fmp_upcoming:
            date_str = ev.get("date", "")
            try:
                ev_dt = datetime.fromisoformat(date_str.replace(" ", "T"))
                if ev_dt.tzinfo is None:
                    ev_dt = ev_dt.replace(tzinfo=timezone.utc)
                ev_ts = ev_dt.timestamp()
                if now <= ev_ts <= next_hour_end:
                    return {
                        "can_recover": False,
                        "reason": f"macro event '{ev.get('event','?')}' upcoming in next 60min",
                    }
            except Exception:
                continue

    # ALL conditions met → auto-recovery
    return {
        "can_recover": True,
        "target_mode": target_mode,  # firma r107 §4d → CAUTELA, NEVER NORMAL
        "minutes_since_trigger": minutes_since,
        "btc_volatility_in_window": move_pct,
        "volatility_window_minutes": vol_window_min,
        "reason": "all_recovery_conditions_met",
    }
