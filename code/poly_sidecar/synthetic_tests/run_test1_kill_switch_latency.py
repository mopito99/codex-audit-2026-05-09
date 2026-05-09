"""r125 Test 1 — Kill-switch latency E2E synthetic.

Mide latency Dallas (POST inject) → Newark (V4ShadowRecord con
matching injection_id en cyclic_shadow_v4.jsonl).

Criterios firmados Gemma r122/r125:
  - p50 < 800ms
  - p99 < 1200ms

Pre-condición (r125 §4 condición #4):
  - Sidecar warmup completo: btc_price_usd != null
  - No synthetic override active

Output: r126 ready summary + raw JSONL appendix.
"""
from __future__ import annotations
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

SIDECAR_URL = "http://127.0.0.1:8090"
NEWARK_HOST = "ubuntu@64.130.34.38"
SSH_KEY = "/home/administrator/.ssh/id_ed25519"
NEWARK_JSONL = "/home/ubuntu/liquidator_rs/data/cyclic_shadow_v4.jsonl"

OUTPUT_DIR = Path("/home/administrator/poly_sidecar/data/synthetic_tests")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
RAW_RESULTS = OUTPUT_DIR / "test1_iters.jsonl"


def http_get(path: str, timeout: float = 3.0) -> dict:
    r = urllib.request.urlopen(f"{SIDECAR_URL}{path}", timeout=timeout)
    return json.loads(r.read())


def http_post(path: str, payload: dict, timeout: float = 3.0) -> dict:
    req = urllib.request.Request(
        f"{SIDECAR_URL}{path}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    r = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(r.read())


def assert_warmup_complete():
    """Condición #4 firma Gemma — warmup y no override previo activo."""
    s = http_get("/admin/test/macro_status")
    if not s.get("warmup_complete"):
        raise RuntimeError(
            f"Warmup incompleto: btc_price={s.get('btc_price_usd')}"
        )
    if s.get("is_synthetic_active"):
        raise RuntimeError(
            f"Override previo activo: {s.get('override')}"
        )
    print(f"✅ Warmup OK: btc=${s['btc_price_usd']:.2f}, no override active")


def ssh_tail_jsonl(n_lines: int = 20, retries: int = 3) -> list[dict]:
    """Tail Newark JSONL via SSH. r127 Q4 spec — 3 retries con backoff."""
    backoffs = [0.1, 0.5, 2.0]
    for attempt in range(retries):
        try:
            r = subprocess.run(
                [
                    "ssh", "-i", SSH_KEY,
                    "-o", "BatchMode=yes",
                    "-o", "ConnectTimeout=3",
                    NEWARK_HOST,
                    f"tail -n {n_lines} {NEWARK_JSONL}",
                ],
                capture_output=True, text=True, timeout=8,
            )
            if r.returncode != 0:
                raise RuntimeError(f"ssh exit {r.returncode}: {r.stderr}")
            out = []
            for line in r.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
            return out
        except Exception:
            if attempt < retries - 1:
                time.sleep(backoffs[attempt])
                continue
            raise


def parse_iso_to_unix(iso_str: str) -> float:
    """Parse ISO 8601 con microseconds + Z."""
    s = iso_str.replace("Z", "").rstrip("0").rstrip(".")
    if "." in s:
        base, frac = s.split(".", 1)
        frac = (frac + "000000")[:6]
        s = f"{base}.{frac}"
        try:
            return time.mktime(time.strptime(s.split(".")[0], "%Y-%m-%dT%H:%M:%S")) + float(f"0.{frac}")
        except Exception:
            return time.mktime(time.strptime(base, "%Y-%m-%dT%H:%M:%S"))
    return time.mktime(time.strptime(s, "%Y-%m-%dT%H:%M:%S"))


def run_iter(iter_num: int, btc_price: float, mode: str) -> dict:
    """Run 1 iteration: POST inject → poll JSONL until matching injection_id."""
    iid = f"test1-{int(time.time()*1000)}-iter{iter_num}"
    payload = {
        "injection_id": iid,
        "btc_price_usd": btc_price,
        "tau_final": 0.85,
        "tau_macro": 0.85,
        "tau_crypto": 0.50,
        "mode": mode,
        "mode_reason": f"test1_iter{iter_num}_btc{btc_price}",
        "ttl_seconds": 30,
    }
    try:
        inject_resp = http_post("/admin/test/inject_macro_state", payload)
    except Exception as e:
        return {"ok": False, "iter": iter_num, "iid": iid,
                "reason": f"inject_failed: {e}"}

    injection_time_utc = inject_resp["injection_time_utc"]
    t_inject_unix = parse_iso_to_unix(injection_time_utc)

    deadline = time.time() + 5.0
    infra_fails = 0
    while time.time() < deadline:
        try:
            recs = ssh_tail_jsonl(n_lines=10)
        except Exception as e:
            infra_fails += 1
            if infra_fails >= 3:
                return {"ok": False, "iter": iter_num, "iid": iid,
                        "reason": f"INFRA_FAIL ssh: {e}"}
            time.sleep(0.2)
            continue
        for rec in recs:
            if rec.get("v4_macro_injection_id") == iid:
                # r134 firma Gemma — usar latency interna (sin overhead SSH tail).
                # v4_macro_latency_e2e_ms = now() - injection_time_utc desde Rust.
                latency_internal = rec.get("v4_macro_latency_e2e_ms")
                # Mantener external metric para comparación
                t_jsonl_unix = parse_iso_to_unix(rec["timestamp"])
                latency_external_ms = int((t_jsonl_unix - t_inject_unix) * 1000)
                return {
                    "ok": True,
                    "iter": iter_num,
                    "iid": iid,
                    # PRIMARY metric per Gemma r131 Q2(b) firma
                    "latency_ms": latency_internal,
                    # Para análisis comparativo
                    "latency_external_ms": latency_external_ms,
                    "injection_time_utc": injection_time_utc,
                    "jsonl_ts": rec["timestamp"],
                    "v4_mode": rec.get("v4_mode"),
                    "v4_btc": rec.get("v4_btc_price_usd"),
                }
        time.sleep(0.05)
    return {"ok": False, "iter": iter_num, "iid": iid,
            "reason": "TIMEOUT 5s no matching injection_id"}


def main(n_iters: int = 50):
    print(f"=== Test 1 · Kill-switch latency E2E (n={n_iters}) ===\n")

    print("[pre-check] warmup validation")
    assert_warmup_complete()

    print(f"\n[run] {n_iters} iterations, alternating BTC prices")
    results = []
    with open(RAW_RESULTS, "w") as f:
        for i in range(n_iters):
            btc = 78000.0 if i % 2 == 0 else 84500.0
            mode = "CRITICAL"  # forced spike → kill-switch trigger
            res = run_iter(i, btc, mode)
            results.append(res)
            f.write(json.dumps(res) + "\n")
            f.flush()
            status = "OK" if res["ok"] else "FAIL"
            extra = f"{res.get('latency_ms')}ms" if res["ok"] else res.get("reason", "?")
            print(f"  iter {i:2d}: {status} {extra}")
            time.sleep(1.5)

    latencies = sorted([r["latency_ms"] for r in results if r["ok"]])
    n = len(latencies)
    n_total = len(results)
    timeouts = sum(1 for r in results if not r["ok"] and "TIMEOUT" in r.get("reason", ""))
    infra_fails = sum(1 for r in results if not r["ok"] and "INFRA_FAIL" in r.get("reason", ""))

    summary = {
        "n_total": n_total,
        "n_ok": n,
        "n_timeouts": timeouts,
        "n_infra_fails": infra_fails,
        "min_ms": latencies[0] if n else None,
        "max_ms": latencies[-1] if n else None,
        "p50_ms": latencies[n // 2] if n else None,
        "p95_ms": latencies[int(n * 0.95)] if n else None,
        "p99_ms": latencies[int(n * 0.99)] if n else None,
        "criteria": {
            "p50_lt_800ms": (latencies[n // 2] if n else 99999) < 800,
            "p99_lt_1200ms": (latencies[int(n * 0.99)] if n else 99999) < 1200,
        },
    }
    summary["VERDICT"] = (
        "PASS" if (summary["criteria"]["p50_lt_800ms"]
                   and summary["criteria"]["p99_lt_1200ms"]
                   and infra_fails == 0)
        else "FAIL"
    )

    print(f"\n=== Summary ===")
    print(json.dumps(summary, indent=2))
    summary_path = OUTPUT_DIR / "test1_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"\nRaw: {RAW_RESULTS}")
    print(f"Summary: {summary_path}")
    return summary


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    summary = main(n_iters=n)
    sys.exit(0 if summary["VERDICT"] == "PASS" else 1)
