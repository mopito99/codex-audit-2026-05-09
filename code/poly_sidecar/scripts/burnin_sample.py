#!/usr/bin/env python3
"""r136 firma Gemma — Burn-in 24h monitoring sampling cada 60s.

Captura cada 60s:
  1. /cb/status del V4 binary (Newark :9091 vía SSH)
  2. RSS/VSZ/CPU% del proceso liquidator_rs (Newark)
  3. Lectura ligera del último cycle de cyclic_shadow.jsonl (Dallas mirror)

Output JSONL: /home/administrator/poly_sidecar/data/burnin_samples.jsonl
"""
from __future__ import annotations
import json
import subprocess
import time
from pathlib import Path

OUT = Path("/home/administrator/poly_sidecar/data/burnin_samples.jsonl")
MIRROR = Path("/home/administrator/poly_sidecar/data/shadow_mirror/cyclic_shadow.jsonl")
SSH_KEY = "/home/administrator/.ssh/id_ed25519"
SSH_HOST = "ubuntu@64.130.34.38"

V4_BINARY_PATH = "/home/ubuntu/liquidator_rs.v4_alpha_prep_no_telegram/target/release/liquidator_rs"


def ssh_run(cmd: str, timeout: float = 5.0) -> str:
    try:
        r = subprocess.run(
            ["ssh", "-i", SSH_KEY, "-o", "BatchMode=yes",
             "-o", "ConnectTimeout=4", SSH_HOST, cmd],
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def get_cb_status() -> dict:
    out = ssh_run("curl -sf -m 2 http://127.0.0.1:9091/cb/status")
    try:
        return json.loads(out) if out else {}
    except Exception:
        return {}


def get_proc_stats() -> dict:
    out = ssh_run(
        f"PID=$(pgrep -f '{V4_BINARY_PATH}$' | head -1); "
        "if [ -n \"$PID\" ]; then ps -o rss=,vsz=,pcpu=,etimes= -p $PID; fi"
    )
    if not out:
        return {"rss_kb": 0, "vsz_kb": 0, "cpu_pct": 0.0, "uptime_s": 0}
    parts = out.split()
    return {
        "rss_kb": int(parts[0]) if len(parts) > 0 else 0,
        "vsz_kb": int(parts[1]) if len(parts) > 1 else 0,
        "cpu_pct": float(parts[2]) if len(parts) > 2 else 0.0,
        "uptime_s": int(parts[3]) if len(parts) > 3 else 0,
    }


def get_last_cycle() -> dict:
    if not MIRROR.exists():
        return {}
    try:
        with open(MIRROR, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 8192))
            chunk = f.read().decode(errors="ignore")
        last_line = chunk.rstrip().split("\n")[-1]
        d = json.loads(last_line)
        return {
            "ts": d.get("timestamp"),
            "cb_blocked": d.get("cb_blocked"),
            "would_send": d.get("would_send"),
            "slot_lag": d.get("slot_lag"),
        }
    except Exception:
        return {}


def main():
    now = time.time()
    sample = {
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "ts_unix": int(now),
        "proc": get_proc_stats(),
        "cb": get_cb_status(),
        "last_cycle": get_last_cycle(),
    }
    with open(OUT, "a") as f:
        f.write(json.dumps(sample, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
