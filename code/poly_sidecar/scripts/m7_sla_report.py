#!/usr/bin/env python3
"""m7_sla_report.py — M7 CPI Dry-run SLA Report Generator (firmado Gemma r152-M3-prelim Q3).

Genera reporte markdown con tabla SLA timeline a partir de journalctl de
vq-poly-sidecar durante una ventana T-30min → T+15min de un evento macro
(ej. CPI 2026-05-12 12:30 UTC).

Uso:
    # Mar 12 dry-run real
    sudo python3 m7_sla_report.py \\
        --event-time 2026-05-12T12:30:00Z \\
        --out /home/administrator/r152_M7_dryrun_sla_report.md

    # Replay histórico
    sudo python3 m7_sla_report.py \\
        --event-time 2026-05-08T12:30:00Z \\
        --window-pre-min 30 --window-post-min 15 \\
        --out /tmp/replay_nfp.md

Output: markdown con 4 secciones:
  §1 Polling state timeline (P3.6.5-v2 log entries + tau ticks)
  §2 BLS API capture timeline (httpx api.bls.gov requests + latency)
  §3 Mode transitions (state changes)
  §4 Hard Gate verification (Pass/Fail criteria)

NOTA: requiere sudo para journalctl access.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────
# Regex parsers
# ─────────────────────────────────────────────────────────────────────────

# journalctl format: "May 09 09:25:41 host python3[PID]: TS [LEVEL] logger: msg"
_RE_JOURNAL_LINE = re.compile(
    r"^(?P<mon>\w+)\s+(?P<day>\d+)\s+(?P<time>\d{2}:\d{2}:\d{2})\s+\S+\s+\S+:\s+"
    r"(?P<iso>\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}:\d{2}),\d+\s+\[(?P<level>\w+)\]\s+"
    r"(?P<logger>[\w.]+):\s+(?P<msg>.*)$"
)

# [P3.6.5-v2] HIGH_FREQUENCY poll · evt=Consumer Price Index · secs_window=-300s (neg=post-release)
_RE_P365_V2 = re.compile(
    r"\[P3\.6\.5-v2\] HIGH_FREQUENCY poll · evt=(?P<evt>[^·]+)\s*·\s*secs_window=(?P<secs>-?\d+)s"
)

# httpx: HTTP Request: GET https://api.bls.gov/publicAPI/v2/timeseries/data ... "HTTP/1.1 200 OK"
# httpx redacts api_key= so URL puede tener <REDACTED>
_RE_BLS_HTTP = re.compile(
    r"httpx: HTTP Request:\s+(?P<method>\w+)\s+(?P<url>https?://[^\s]+)\s+\"HTTP/[\d.]+\s+(?P<code>\d+)"
)

# τ_final=0.345716 τ_crypto=... mode info embedded en log later
_RE_TAU = re.compile(
    r"τ_final=(?P<tau>[\d.]+)\s+τ_crypto=[\d.]+\s+τ_macro=[\d.]+\s+contracts=\d+\s+errors="
)

# r152-M3 BLS period MATCH/MISMATCH log
_RE_M3_PERIOD = re.compile(
    r"\[r152-M3\]\s+(?P<cat>\w+)\s+(?P<date>\d{4}-\d{2}-\d{2}):\s+BLS period\s+(?P<verdict>\w+)\s+"
    r"observed=(?P<obs_y>\d+)/(?P<obs_p>M\d+)\s+expected=(?P<exp_y>\d+)/(?P<exp_p>M\d+)"
)


def _parse_journal_ts(line: str) -> dt.datetime | None:
    m = _RE_JOURNAL_LINE.match(line)
    if not m:
        return None
    return dt.datetime.strptime(m.group("iso"), "%Y-%m-%d %H:%M:%S").replace(
        tzinfo=dt.timezone.utc
    )


def _journal_msg(line: str) -> str | None:
    m = _RE_JOURNAL_LINE.match(line)
    return m.group("msg") if m else None


# ─────────────────────────────────────────────────────────────────────────
# Collectors
# ─────────────────────────────────────────────────────────────────────────


def collect_logs(since_iso: str, until_iso: str, unit: str = "vq-poly-sidecar") -> list[str]:
    """Run journalctl and return stdout lines."""
    cmd = [
        "journalctl",
        "-u",
        unit,
        "--since",
        since_iso,
        "--until",
        until_iso,
        "--no-pager",
        "--output=short-iso",
    ]
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=60
        ).stdout
    except subprocess.TimeoutExpired:
        return []
    return out.splitlines()


def collect_polling_events(lines: list[str]) -> list[dict]:
    """Extract P3.6.5-v2 HIGH_FREQUENCY log entries."""
    rows = []
    for ln in lines:
        msg = _journal_msg(ln)
        if not msg or "[P3.6.5-v2]" not in msg:
            continue
        m = _RE_P365_V2.search(msg)
        if not m:
            continue
        ts = _parse_journal_ts(ln)
        rows.append(
            {
                "ts": ts,
                "evt": m.group("evt").strip(),
                "secs_window": int(m.group("secs")),
            }
        )
    return rows


def collect_bls_api_calls(lines: list[str]) -> list[dict]:
    """Extract httpx api.bls.gov requests with latency tracking.

    Latency: not directly logged · approx using consecutive log timestamps.
    """
    rows = []
    for i, ln in enumerate(lines):
        msg = _journal_msg(ln)
        if not msg or "api.bls.gov" not in msg:
            continue
        m = _RE_BLS_HTTP.search(msg)
        if not m:
            continue
        ts = _parse_journal_ts(ln)
        rows.append(
            {
                "ts": ts,
                "method": m.group("method"),
                "url_redacted": m.group("url")[:80] + "...",
                "http_code": m.group("code"),
            }
        )
    return rows


def collect_tau_ticks(lines: list[str]) -> list[dict]:
    """Extract tau_final ticks for polling rate inference."""
    rows = []
    for ln in lines:
        msg = _journal_msg(ln)
        if not msg:
            continue
        m = _RE_TAU.search(msg)
        if not m:
            continue
        ts = _parse_journal_ts(ln)
        rows.append({"ts": ts, "tau": float(m.group("tau"))})
    return rows


def collect_m3_period_decisions(lines: list[str]) -> list[dict]:
    """Extract [r152-M3] BLS period MATCH/MISMATCH/REJECTED entries (when M3 deployed)."""
    rows = []
    for ln in lines:
        msg = _journal_msg(ln)
        if not msg or "[r152-M3]" not in msg:
            continue
        m = _RE_M3_PERIOD.search(msg)
        if not m:
            continue
        ts = _parse_journal_ts(ln)
        rows.append(
            {
                "ts": ts,
                "category": m.group("cat"),
                "ev_date": m.group("date"),
                "verdict": m.group("verdict"),
                "observed": f"{m.group('obs_y')}/{m.group('obs_p')}",
                "expected": f"{m.group('exp_y')}/{m.group('exp_p')}",
            }
        )
    return rows


# ─────────────────────────────────────────────────────────────────────────
# Renderers
# ─────────────────────────────────────────────────────────────────────────


def _fmt_ts(ts: dt.datetime | None) -> str:
    if ts is None:
        return "—"
    return ts.strftime("%H:%M:%S")


def _delta_to_event(ts: dt.datetime, event_dt: dt.datetime) -> str:
    if ts is None:
        return "—"
    delta = (ts - event_dt).total_seconds()
    sign = "+" if delta >= 0 else "-"
    return f"{sign}{abs(delta):.0f}s"


def render_polling_section(rows: list[dict], event_dt: dt.datetime) -> str:
    if not rows:
        return (
            "## §1 · Polling state timeline\n\n"
            "**⚠️ NO `[P3.6.5-v2]` log entries in window.**\n\n"
            "This is a HARD GATE FAIL: SLA <120s post-release captura no garantizada.\n\n"
        )
    out = ["## §1 · Polling state timeline\n"]
    out.append("| UTC time | Δ to event | evt | secs_window | poll_interval |")
    out.append("|---|---|---|---|---|")
    for r in rows:
        secs = r["secs_window"]
        interval = "30 (HIGH)" if -900 <= secs <= 1800 else "3600 (LOW)"
        out.append(
            f"| {_fmt_ts(r['ts'])} | {_delta_to_event(r['ts'], event_dt)} | "
            f"{r['evt']} | {secs}s | {interval} |"
        )
    return "\n".join(out) + "\n\n"


def render_bls_section(rows: list[dict], event_dt: dt.datetime) -> str:
    if not rows:
        return "## §2 · BLS API capture timeline\n\n**No api.bls.gov calls in window.**\n\n"

    out = ["## §2 · BLS API capture timeline\n"]
    out.append("| UTC time | Δ to event | method | http | url (redacted) |")
    out.append("|---|---|---|---|---|")
    for r in rows:
        out.append(
            f"| {_fmt_ts(r['ts'])} | {_delta_to_event(r['ts'], event_dt)} | "
            f"{r['method']} | {r['http_code']} | `{r['url_redacted']}` |"
        )
    # Hard Gate check: any request within 120s post-release
    post_release_calls = [
        r for r in rows
        if r["ts"] and (r["ts"] - event_dt).total_seconds() > 0
        and (r["ts"] - event_dt).total_seconds() <= 120
    ]
    out.append("")
    if post_release_calls:
        out.append(
            f"✅ **SLA <120s GATE PASS**: {len(post_release_calls)} BLS call(s) "
            f"within 120s post-release."
        )
    else:
        out.append("⛔ **SLA <120s GATE FAIL**: 0 BLS calls within 120s post-release.")
    return "\n".join(out) + "\n\n"


def render_period_section(rows: list[dict]) -> str:
    if not rows:
        return (
            "## §3 · BLS period validation [r152-M3]\n\n"
            "*(M3 deploy pendiente · sin entries `[r152-M3]` esperadas todavía)*\n\n"
        )
    out = ["## §3 · BLS period validation [r152-M3]\n"]
    out.append("| UTC time | category | event | verdict | observed | expected |")
    out.append("|---|---|---|---|---|---|")
    for r in rows:
        verdict_emoji = "✅" if r["verdict"] == "MATCH" else (
            "⛔" if r["verdict"] == "MISMATCH" else "⚠️"
        )
        out.append(
            f"| {_fmt_ts(r['ts'])} | {r['category']} | {r['ev_date']} | "
            f"{verdict_emoji} {r['verdict']} | {r['observed']} | {r['expected']} |"
        )
    return "\n".join(out) + "\n\n"


def render_hard_gate(
    polling_rows: list[dict],
    bls_rows: list[dict],
    period_rows: list[dict],
    event_dt: dt.datetime,
) -> str:
    """Hard Gate verification per firma Gemma r152-M2."""
    out = ["## §4 · Hard Gate verification · M7\n"]

    # Criterion 1: [P3.6.5-v2] HIGH_FREQUENCY log entries with secs_window<0 (post-release)
    post_release_polling = [r for r in polling_rows if r["secs_window"] < 0]
    crit1_pass = len(post_release_polling) >= 1
    out.append(
        f"| {'✅' if crit1_pass else '⛔'} | "
        f"`[P3.6.5-v2]` log con `secs_window<0` post-release | "
        f"Found: {len(post_release_polling)} entries (need ≥1) |"
    )

    # Criterion 2: BLS API HTTP 200 within 120s post-release
    post_release_bls_ok = [
        r for r in bls_rows
        if r["ts"]
        and 0 < (r["ts"] - event_dt).total_seconds() <= 120
        and r["http_code"] == "200"
    ]
    crit2_pass = len(post_release_bls_ok) >= 1
    out.insert(
        1,
        f"| Status | Criterio | Resultado |\n|---|---|---|"
    )
    out.append(
        f"| {'✅' if crit2_pass else '⛔'} | "
        f"BLS api.bls.gov HTTP 200 dentro de 120s post-release | "
        f"Found: {len(post_release_bls_ok)} HTTP 200 (need ≥1) |"
    )

    # Criterion 3: M3 period validation MATCH (if M3 deployed)
    period_match = [r for r in period_rows if r["verdict"] == "MATCH"]
    period_mismatch = [r for r in period_rows if r["verdict"] == "MISMATCH"]
    if period_rows:
        crit3_pass = len(period_match) >= 1 and len(period_mismatch) == 0
        out.append(
            f"| {'✅' if crit3_pass else '⛔'} | "
            f"M3 period validation MATCH expected event | "
            f"MATCH={len(period_match)} MISMATCH={len(period_mismatch)} |"
        )
    else:
        out.append(
            "| 🟡 N/A | M3 period validation | M3 not deployed yet (skipped) |"
        )
        crit3_pass = True  # don't block on M3 if not deployed

    overall = crit1_pass and crit2_pass and crit3_pass
    out.append("")
    out.append(f"### Overall verdict: {'✅ M7 GATE PASS · LIVE Mar 22 GO' if overall else '⛔ M7 GATE FAIL · postpone LIVE'}")
    return "\n".join(out) + "\n\n"


# ─────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event-time", default="2026-05-12T12:30:00Z",
                        help="ISO timestamp del macro event")
    parser.add_argument("--window-pre-min", type=int, default=30)
    parser.add_argument("--window-post-min", type=int, default=15)
    parser.add_argument("--out", default="/home/administrator/r152_M7_dryrun_sla_report.md")
    parser.add_argument("--unit", default="vq-poly-sidecar")
    args = parser.parse_args()

    event_dt = dt.datetime.fromisoformat(
        args.event_time.replace("Z", "+00:00")
    )
    start_dt = event_dt - dt.timedelta(minutes=args.window_pre_min)
    end_dt = event_dt + dt.timedelta(minutes=args.window_post_min)

    print(f"Event time:       {event_dt.isoformat()}", file=sys.stderr)
    print(f"Window:           {start_dt.isoformat()}  →  {end_dt.isoformat()}", file=sys.stderr)
    print(f"Collecting logs from {args.unit}...", file=sys.stderr)

    lines = collect_logs(start_dt.isoformat(), end_dt.isoformat(), unit=args.unit)
    print(f"Collected {len(lines)} log lines", file=sys.stderr)

    polling = collect_polling_events(lines)
    bls = collect_bls_api_calls(lines)
    period = collect_m3_period_decisions(lines)

    print(f"  P3.6.5-v2 entries: {len(polling)}", file=sys.stderr)
    print(f"  BLS API calls:     {len(bls)}", file=sys.stderr)
    print(f"  [r152-M3] entries: {len(period)}", file=sys.stderr)

    # Build markdown
    md = [
        f"# M7 CPI Dry-run SLA Report · {event_dt.strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        f"**Generado por**: `scripts/m7_sla_report.py` (firmado Gemma r152-M3-prelim Q3)",
        f"**Window**: T-{args.window_pre_min}min → T+{args.window_post_min}min",
        f"**Logs collected**: {len(lines)} lines from `{args.unit}` journalctl",
        "",
        render_polling_section(polling, event_dt),
        render_bls_section(bls, event_dt),
        render_period_section(period),
        render_hard_gate(polling, bls, period, event_dt),
        "",
        f"---",
        f"*Generated at {dt.datetime.now(dt.timezone.utc).isoformat()}*",
    ]

    Path(args.out).write_text("\n".join(md))
    print(f"\nReport written to: {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
