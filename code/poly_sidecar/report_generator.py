"""Generador del informe diario VelocityQuant.

Recolecta:
- Stats por ventana UTC del bot V3.5 SHADOW en Newark (vía SSH)
- Estado actual del sidecar Polymarket (local /api/state)
- Eventos macro próximos (FMP) y reacciones recientes (Investing SF)

Genera 3 archivos en reports/<id>/ :
- report.json  → datos crudos auditables
- report.html  → render visual oscuro
- report.md    → copy-paste a Gemma 4

Uso:
    python3 report_generator.py            # genera ahora
    python3 report_generator.py --date 2026-05-05

Salida en stdout: report_id (carpeta) o JSON con status si falla.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import urllib.request

REPORTS_DIR = Path("/home/administrator/poly_sidecar/reports")
SIDECAR_URL = "http://127.0.0.1:8090/api/state"
NEWARK_HOST = "ubuntu@64.130.34.38"
SSH_KEY = "/home/administrator/.ssh/id_ed25519"
WINDOW_SCRIPT_LOCAL = Path("/home/administrator/poly_sidecar/report_window_stats.py")
WINDOW_SCRIPT_REMOTE = "/tmp/vq_report_window_stats.py"


def fetch_sidecar_state() -> dict:
    try:
        with urllib.request.urlopen(SIDECAR_URL, timeout=10) as r:
            return json.load(r)
    except Exception as e:
        return {"_error": f"sidecar fetch failed: {e}"}


def fetch_newark_window_stats(date_str: str) -> dict:
    if not WINDOW_SCRIPT_LOCAL.exists():
        return {"_error": f"window script missing: {WINDOW_SCRIPT_LOCAL}"}

    scp = subprocess.run(
        ["scp", "-i", SSH_KEY, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
         str(WINDOW_SCRIPT_LOCAL), f"{NEWARK_HOST}:{WINDOW_SCRIPT_REMOTE}"],
        capture_output=True, text=True, timeout=30,
    )
    if scp.returncode != 0:
        return {"_error": f"scp failed: {scp.stderr}"}

    # nice -n 19 + ionice -c 3 (idle) → prioridad mínima de CPU/IO para no
    # interferir con el bot Rust corriendo en el mismo host.
    remote_cmd = (
        f"nice -n 19 ionice -c 3 -n 7 "
        f"python3 {WINDOW_SCRIPT_REMOTE} {date_str}"
    )
    run = subprocess.run(
        ["ssh", "-i", SSH_KEY, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
         NEWARK_HOST, remote_cmd],
        capture_output=True, text=True, timeout=120,
    )
    if run.returncode != 0:
        return {"_error": f"ssh exec failed: {run.stderr[:500]}", "stdout": run.stdout[:500]}
    try:
        return json.loads(run.stdout)
    except Exception as e:
        return {"_error": f"json parse failed: {e}", "raw": run.stdout[:500]}


def derive_macro_section(state: dict) -> dict:
    """Resume eventos macro: trigger SF, próximos 24h, reacciones recientes."""
    inv = state.get("investing", {}) or {}
    fmp = state.get("fmp", {}) or {}
    out = {
        "mode": state.get("mode"),
        "mode_reason": state.get("mode_reason"),
        "tau_final": state.get("tau_final"),
        "tau_crypto": state.get("tau_crypto"),
        "tau_macro": state.get("tau_macro"),
        "rho": state.get("rho"),
        "rho_threshold": state.get("rho_threshold"),
        "rho_divergence_active": state.get("rho_divergence_active"),
        "btc_price_usd": state.get("btc_price_usd"),
        "fmp_upcoming_24h": fmp.get("upcoming_24h", [])[:10],
        "investing_recent_6h": inv.get("recent_releases_6h", [])[:10],
        "investing_latest_surprise": inv.get("latest_surprise_event"),
        "investing_reaction_required": inv.get("reaction_required"),
    }
    return out


def assemble_report(date_str: str) -> dict:
    sidecar = fetch_sidecar_state()
    newark = fetch_newark_window_stats(date_str)
    macro = derive_macro_section(sidecar) if "_error" not in sidecar else {"_error": sidecar.get("_error")}

    return {
        "report_id": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ"),
        "date_utc": date_str,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "newark_v35_shadow": newark,
        "sidecar_now": macro,
        "sidecar_full_state": sidecar,
    }


# ---------- Render helpers ----------

def fmt_int(n):
    if n is None:
        return "—"
    return f"{n:,}"


def fmt_float(x, dec=4, signed=False):
    if x is None:
        return "—"
    try:
        v = float(x)
    except Exception:
        return str(x)
    s = f"{v:.{dec}f}"
    if signed and v >= 0:
        s = "+" + s
    return s


def render_md(report: dict) -> str:
    rid = report["report_id"]
    date = report["date_utc"]
    gen = report["generated_at_utc"]
    nw = report.get("newark_v35_shadow", {})
    sc = report.get("sidecar_now", {})

    lines = []
    lines.append(f"# Informe operativo VelocityQuant — {date}")
    lines.append("")
    lines.append(f"**Report ID:** `{rid}`  ")
    lines.append(f"**Generado:** {gen}  ")
    lines.append(f"**Hora UTC actual:** {nw.get('now_hour_utc', '—')}h")
    lines.append("")
    lines.append("---")
    lines.append("")

    # 1. Sidecar state
    lines.append("## 1. Sidecar Polymarket — estado actual")
    lines.append("")
    if "_error" in sc:
        lines.append(f"⚠️ Error: `{sc['_error']}`")
    else:
        lines.append(f"- **Mode:** `{sc.get('mode')}` ({sc.get('mode_reason') or 'sin razón'})")
        lines.append(f"- **τ_final:** {fmt_float(sc.get('tau_final'), 3)}")
        lines.append(f"- **τ_crypto:** {fmt_float(sc.get('tau_crypto'), 3)}  |  **τ_macro:** {fmt_float(sc.get('tau_macro'), 3)}")
        lines.append(f"- **ρ:** {fmt_float(sc.get('rho'), 3)}  (umbral {fmt_float(sc.get('rho_threshold'), 2)}, divergencia: {'SÍ' if sc.get('rho_divergence_active') else 'no'})")
        lines.append(f"- **BTC spot:** ${fmt_int(int(sc.get('btc_price_usd') or 0))}")
    lines.append("")

    # 2. Macro events
    lines.append("## 2. Macro events")
    lines.append("")
    surprise = sc.get("investing_latest_surprise") if isinstance(sc, dict) else None
    if surprise:
        lines.append(f"### ⚠️ Última sorpresa (|SF| > 1σ)")
        lines.append("")
        lines.append(f"- **{surprise.get('event')}** ({surprise.get('country')})")
        lines.append(f"  - actual: `{surprise.get('actual')}`  |  forecast: `{surprise.get('forecast')}`  |  prev: `{surprise.get('previous')}`")
        lines.append(f"  - **SF: {surprise.get('surprise_factor')}σ**  ({surprise.get('ts_utc')})")
        lines.append(f"  - reaction_threshold_hit: {surprise.get('reaction_threshold_hit')}")
        lines.append("")

    upcoming = sc.get("fmp_upcoming_24h", []) if isinstance(sc, dict) else []
    if upcoming:
        lines.append("### Próximos 24h (FMP)")
        lines.append("")
        lines.append("| Hora UTC | Evento | Categoría | Prev | Forecast |")
        lines.append("|---|---|---|---|---|")
        for e in upcoming:
            lines.append(f"| {e.get('date','—')} | {e.get('event','—')} | {e.get('category','—')} | {e.get('previous','—')} | {e.get('estimate','—')} |")
        lines.append("")

    recent = sc.get("investing_recent_6h", []) if isinstance(sc, dict) else []
    if recent:
        lines.append("### Reacciones últimas 6h (Investing)")
        lines.append("")
        lines.append("| TS UTC | Evento | Cat | Actual | Fcst | SF |")
        lines.append("|---|---|---|---|---|---|")
        for e in recent:
            sf = e.get('surprise_factor')
            sf_s = f"{sf:.2f}σ" if isinstance(sf, (int, float)) else str(sf)
            lines.append(f"| {e.get('ts_utc','—')} | {e.get('event','—')[:40]} | {e.get('category','—')} | {e.get('actual','—')} | {e.get('forecast','—')} | {sf_s} |")
        lines.append("")

    # 3. Newark V3.5 SHADOW windows
    lines.append("## 3. V3.5 SHADOW Newark — actividad por ventana UTC")
    lines.append("")
    if "_error" in nw:
        lines.append(f"⚠️ Error: `{nw['_error']}`")
    else:
        lines.append("| Ventana UTC | Eventos | would_send | %  | CB blocked | p_max ($) | p_sum ($) | lat p50 (ms) | lat p99 (ms) | slot_lag max |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for w in nw.get("windows", []):
            ws_pct = w.get("would_send_pct")
            ws_pct_s = f"{ws_pct:.1f}%" if isinstance(ws_pct, (int, float)) else "—"
            lines.append(
                f"| {w['label']} | {fmt_int(w.get('events'))} | {fmt_int(w.get('would_send'))} | {ws_pct_s} | "
                f"{fmt_int(w.get('cb_blocked'))} | {fmt_float(w.get('max_profit_usd'), 4)} | "
                f"{fmt_float(w.get('sum_profit_usd'), 2)} | {fmt_int(w.get('lat_p50_ms'))} | "
                f"{fmt_int(w.get('lat_p99_ms'))} | {fmt_int(w.get('slot_lag_max'))} |"
            )
        lines.append("")

    # 4. V4-Alpha Macro Layer (si observer está corriendo)
    v4 = nw.get("v4_macro") if isinstance(nw, dict) else None
    if v4 and v4.get("available"):
        lines.append("## 4. V4-Alpha Macro Layer — observer paralelo")
        lines.append("")
        n = v4.get("n_records", 0)
        if n == 0:
            lines.append(f"⚠️ {v4.get('reason', 'sin records')}")
        else:
            lines.append(f"**Records observados hoy:** {fmt_int(n)} (V4 observer Newark, ~1 record/s)")
            lines.append("")

            # Mode distribution
            lines.append("### 4.1 Distribución de modes")
            lines.append("")
            lines.append("| Mode | Records | % |")
            lines.append("|---|---:|---:|")
            mode_dist = v4.get("mode_distribution", {})
            mode_pct = v4.get("mode_distribution_pct", {})
            for mode, count in mode_dist.items():
                pct = mode_pct.get(mode, 0)
                lines.append(f"| {mode} | {fmt_int(count)} | {pct:.1f}% |")
            lines.append("")

            # Block reasons (si hubo)
            br = v4.get("block_reasons", {})
            if br:
                lines.append("### 4.2 Razones de bloqueo V4")
                lines.append("")
                lines.append("| Razón | Records |")
                lines.append("|---|---:|")
                for reason, count in br.items():
                    lines.append(f"| `{reason}` | {fmt_int(count)} |")
                lines.append("")

            # τ y ρ stats
            lines.append("### 4.3 τ (tensión) y ρ (Pearson) percentiles")
            lines.append("")
            lines.append("| Métrica | p10 | p50 | p90 | extremo |")
            lines.append("|---|---:|---:|---:|---:|")
            lines.append(f"| τ_final | {fmt_float(v4.get('tau_final_p10'), 3)} | {fmt_float(v4.get('tau_final_p50'), 3)} | {fmt_float(v4.get('tau_final_p90'), 3)} | max {fmt_float(v4.get('tau_final_max'), 3)} |")
            lines.append(f"| τ_crypto avg | — | {fmt_float(v4.get('tau_crypto_avg'), 3)} | — | — |")
            lines.append(f"| τ_macro avg | — | {fmt_float(v4.get('tau_macro_avg'), 3)} | — | — |")
            rho_p50 = v4.get('rho_p50')
            if rho_p50 is not None:
                lines.append(f"| ρ | {fmt_float(v4.get('rho_p10'), 3)} | {fmt_float(v4.get('rho_p50'), 3)} | {fmt_float(v4.get('rho_p90'), 3)} | min {fmt_float(v4.get('rho_min'), 3)} |")
            else:
                lines.append("| ρ | — | — | — | (insuficiente data pareada) |")
            lines.append("")

            # Disagreements V3 vs V4
            lines.append("### 4.4 V3 vs V4 — ¿hubieran decidido distinto?")
            lines.append("")
            v3_ws = v4.get("v3_would_send_total", 0)
            disag = v4.get("v3_v4_disagreement_count", 0)
            disag_pct = v4.get("v3_v4_disagreement_pct", 0)
            lines.append(f"- V3 `would_send=true` total: {fmt_int(v3_ws)}")
            lines.append(f"- V3-V4 disagreement (V3 sí, V4 no): **{fmt_int(disag)}** ({disag_pct:.2f}% del total)")
            lines.append(f"- Decision_allowed por V4: {v4.get('decision_allowed_pct', 0):.1f}%")
            lines.append(f"- ρ divergencia activa: {v4.get('rho_divergence_pct', 0):.2f}%")
            lines.append("")

            # Health
            lines.append("### 4.5 Health del macro layer")
            lines.append("")
            lines.append(f"- is_warmup pct: {v4.get('is_warmup_pct', 0):.1f}% (warmup threshold 4h)")
            lines.append(f"- is_stale pct: {v4.get('is_stale_pct', 0):.1f}%")
            lines.append(f"- sidecar_error_count_max: {v4.get('sidecar_error_count_max', 0)}")
            btc_min = v4.get('btc_price_min')
            btc_max = v4.get('btc_price_max')
            if btc_min and btc_max:
                lines.append(f"- BTC range observado: ${btc_min:,.2f} — ${btc_max:,.2f} (median ${v4.get('btc_price_p50', 0):,.2f})")
            lines.append("")
    else:
        lines.append("## 4. V4-Alpha Macro Layer")
        lines.append("")
        if v4:
            lines.append(f"⚠️ V4 observer no disponible: {v4.get('reason', 'unknown')}")
        else:
            lines.append("⚠️ V4 observer no instrumentado todavía (deploy pendiente)")
        lines.append("")

    # 5. Lectura ejecutiva (template para Gemma)
    lines.append("## 5. Lectura para Gemma 4")
    lines.append("")
    lines.append("Marco copiará este MD a Gemma 4 web para análisis cuantitativo y posibles ajustes de spec.")
    lines.append("")
    lines.append("**Preguntas sugeridas a Gemma:**")
    lines.append("")
    lines.append("1. ¿La ventana LDN×NY confirma o desmiente el supuesto de mejor ejecución durante solape?")
    lines.append("2. ¿El SF detectado del Investing justifica la transición a CAUTELA según los thresholds?")
    lines.append("3. ¿Hay desalineación entre τ_crypto, τ_macro y los eventos próximos que sugiera ajuste de pesos?")
    lines.append("4. ¿El % would_send post-evento macro es consistente con el modelo de retracción de liquidez?")
    if v4 and v4.get("available") and v4.get("n_records", 0) > 0:
        lines.append("5. **V4-Alpha:** ¿La distribución de modes observada (§4.1) es coherente con tu spec r90?")
        lines.append("6. **V4-Alpha:** ¿Algún disagreement V3↔V4 (§4.4) sugiere ajuste de thresholds?")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"_Informe generado por VelocityQuant report_generator v1.1 — `{rid}`_")
    lines.append("")
    return "\n".join(lines)


def render_html(report: dict, md_text: str) -> str:
    rid = report["report_id"]
    date = report["date_utc"]
    gen = report["generated_at_utc"]
    nw = report.get("newark_v35_shadow", {})
    sc = report.get("sidecar_now", {})

    # Side note: HTML structurally — cards + tables, dark theme
    surprise = sc.get("investing_latest_surprise") if isinstance(sc, dict) else None
    upcoming = sc.get("fmp_upcoming_24h", []) if isinstance(sc, dict) else []
    recent = sc.get("investing_recent_6h", []) if isinstance(sc, dict) else []
    windows = nw.get("windows", []) if "_error" not in nw else []

    def tau_color(t):
        if t is None: return "#8b949e"
        if t > 0.7: return "#f85149"
        if t > 0.4: return "#d29922"
        return "#3fb950"

    surprise_html = ""
    if surprise:
        surprise_html = f"""
        <div class="alert">
          <strong>⚠️ Última sorpresa SF={surprise.get('surprise_factor')}σ</strong><br>
          <b>{surprise.get('event')}</b> ({surprise.get('country')}) — {surprise.get('ts_utc')}<br>
          actual=<code>{surprise.get('actual')}</code> · forecast=<code>{surprise.get('forecast')}</code> · prev=<code>{surprise.get('previous')}</code>
        </div>
        """

    upcoming_rows = "\n".join([
        f"<tr><td>{e.get('date','—')}</td><td>{e.get('event','—')}</td>"
        f"<td><span class='cat'>{e.get('category','—')}</span></td>"
        f"<td>{e.get('previous','—')}</td><td>{e.get('estimate','—')}</td></tr>"
        for e in upcoming
    ]) or "<tr><td colspan='5' class='muted'>sin eventos próximos en 24h</td></tr>"

    recent_rows = "\n".join([
        f"<tr><td>{e.get('ts_utc','—')[11:19]}</td><td>{(e.get('event','—') or '')[:50]}</td>"
        f"<td><span class='cat'>{e.get('category','—')}</span></td>"
        f"<td>{e.get('actual','—')}</td><td>{e.get('forecast','—')}</td>"
        f"<td class='{'pos' if (e.get('surprise_factor') or 0) >= 0 else 'neg'}'>{e.get('surprise_factor','—')}σ</td></tr>"
        for e in recent
    ]) or "<tr><td colspan='6' class='muted'>sin reacciones en últimas 6h</td></tr>"

    # V4 macro section build (rows for mode + tau/rho)
    v4 = nw.get("v4_macro") if isinstance(nw, dict) else None
    v4_section_html = ""
    if v4 and v4.get("available") and v4.get("n_records", 0) > 0:
        n = v4["n_records"]
        mode_dist = v4.get("mode_distribution", {})
        mode_pct = v4.get("mode_distribution_pct", {})
        mode_rows = "\n".join(
            f"<tr><td>{m}</td><td>{count:,}</td><td>{mode_pct.get(m,0):.1f}%</td></tr>"
            for m, count in mode_dist.items()
        ) or "<tr><td colspan='3' class='muted'>sin records</td></tr>"

        block_html = ""
        block_reasons = v4.get("block_reasons", {})
        if block_reasons:
            block_rows = "\n".join(
                f"<tr><td><code>{r}</code></td><td>{count:,}</td></tr>"
                for r, count in block_reasons.items()
            )
            block_html = f"<h3 style='font-size:.95rem'>Razones de bloqueo</h3><table><thead><tr><th>Razón</th><th>Records</th></tr></thead><tbody>{block_rows}</tbody></table>"

        rho_p50 = v4.get('rho_p50')
        rho_row = (
            f"<tr><td>ρ Pearson</td><td>{fmt_float(v4.get('rho_p10'), 3)}</td>"
            f"<td>{fmt_float(v4.get('rho_p50'), 3)}</td>"
            f"<td>{fmt_float(v4.get('rho_p90'), 3)}</td>"
            f"<td>min {fmt_float(v4.get('rho_min'), 3)}</td></tr>"
        ) if rho_p50 is not None else (
            "<tr><td>ρ Pearson</td><td colspan='4' class='muted'>insuficiente data pareada</td></tr>"
        )

        disag = v4.get("v3_v4_disagreement_count", 0)
        disag_pct = v4.get("v3_v4_disagreement_pct", 0)
        disag_class = "neg" if disag > 0 else "pos"

        btc_min = v4.get('btc_price_min')
        btc_max = v4.get('btc_price_max')
        btc_row = (
            f"BTC range observado: <code>${btc_min:,.2f}</code> — <code>${btc_max:,.2f}</code>"
            if btc_min and btc_max else "BTC range: n/a"
        )

        v4_section_html = f"""
<h2>4. V4-Alpha Macro Layer — observer paralelo</h2>
<div class="muted" style="margin-bottom:10px;">
  Records observados hoy: <b>{n:,}</b> · cyclic_shadow_v4.jsonl · ~1 record/s · spec r90/r100
</div>

<h3 style="font-size:.95rem">Distribución de modes</h3>
<table><thead><tr><th>Mode</th><th>Records</th><th>%</th></tr></thead><tbody>
{mode_rows}
</tbody></table>

{block_html}

<h3 style="font-size:.95rem">τ y ρ percentiles</h3>
<table><thead><tr><th>Métrica</th><th>p10</th><th>p50</th><th>p90</th><th>extremo</th></tr></thead><tbody>
<tr><td>τ_final</td><td>{fmt_float(v4.get('tau_final_p10'), 3)}</td>
    <td>{fmt_float(v4.get('tau_final_p50'), 3)}</td>
    <td>{fmt_float(v4.get('tau_final_p90'), 3)}</td>
    <td>max {fmt_float(v4.get('tau_final_max'), 3)}</td></tr>
<tr><td>τ_crypto avg</td><td>—</td><td>{fmt_float(v4.get('tau_crypto_avg'), 3)}</td><td>—</td><td>—</td></tr>
<tr><td>τ_macro avg</td><td>—</td><td>{fmt_float(v4.get('tau_macro_avg'), 3)}</td><td>—</td><td>—</td></tr>
{rho_row}
</tbody></table>

<h3 style="font-size:.95rem">V3 vs V4 — disagreements + health</h3>
<div class="grid">
  <div class="card"><h3>V3 would_send total</h3><div class="big">{v4.get('v3_would_send_total', 0):,}</div></div>
  <div class="card"><h3>V3↔V4 disagreement</h3>
    <div class="big {disag_class}">{disag:,}</div>
    <div class="muted">{disag_pct:.2f}% del total</div>
  </div>
  <div class="card"><h3>V4 decision_allowed</h3><div class="big">{v4.get('decision_allowed_pct', 0):.1f}%</div></div>
  <div class="card"><h3>ρ divergencia activa</h3><div class="big">{v4.get('rho_divergence_pct', 0):.2f}%</div></div>
  <div class="card"><h3>is_warmup</h3><div class="big">{v4.get('is_warmup_pct', 0):.1f}%</div></div>
  <div class="card"><h3>is_stale</h3><div class="big">{v4.get('is_stale_pct', 0):.1f}%</div></div>
</div>
<div class="muted" style="margin-top:8px">
  {btc_row} · sidecar_error_count_max: {v4.get('sidecar_error_count_max', 0)}
</div>
"""
    else:
        reason = v4.get("reason", "no instrumentado") if v4 else "no instrumentado"
        v4_section_html = f"""
<h2>4. V4-Alpha Macro Layer</h2>
<div class="muted">⚠️ V4 observer no disponible: {reason}</div>
"""

    win_rows = ""
    for w in windows:
        ws_pct = w.get("would_send_pct")
        ws_pct_s = f"{ws_pct:.1f}%" if isinstance(ws_pct, (int, float)) else "—"
        highlight = "highlight" if "LDN x NY" in w["label"] else ""
        win_rows += f"""
        <tr class="{highlight}">
          <td><b>{w['label']}</b></td>
          <td>{fmt_int(w.get('events'))}</td>
          <td>{fmt_int(w.get('would_send'))}</td>
          <td>{ws_pct_s}</td>
          <td>{fmt_int(w.get('cb_blocked'))}</td>
          <td>${fmt_float(w.get('max_profit_usd'), 4)}</td>
          <td>${fmt_float(w.get('sum_profit_usd'), 2)}</td>
          <td>{fmt_int(w.get('lat_p50_ms'))}</td>
          <td>{fmt_int(w.get('lat_p99_ms'))}</td>
          <td>{fmt_int(w.get('slot_lag_max'))}</td>
        </tr>
        """
    if not win_rows:
        err = nw.get("_error") if isinstance(nw, dict) else "no data"
        win_rows = f"<tr><td colspan='10' class='muted'>error: {err}</td></tr>"

    tau_final_str = fmt_float(sc.get('tau_final'), 3) if isinstance(sc, dict) else "—"
    tau_c_color = tau_color(sc.get('tau_final') if isinstance(sc, dict) else None)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Informe VelocityQuant — {date}</title>
<style>
  body {{ background:#0d1117; color:#c9d1d9; font-family:-apple-system,sans-serif;
         margin:0; padding:24px; line-height:1.5; }}
  h1, h2, h3 {{ color:#fff; margin-top:1.5em; }}
  h1 {{ font-size:1.4rem; margin-top:0; }}
  h2 {{ font-size:1.1rem; border-bottom:1px solid #30363d; padding-bottom:6px; }}
  .muted {{ color:#8b949e; font-size:.85rem; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:14px; margin:14px 0; }}
  .card {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:14px; }}
  .card h3 {{ margin:0 0 6px 0; font-size:.7rem; text-transform:uppercase; color:#8b949e; letter-spacing:.5px; }}
  .big {{ font-size:1.6rem; font-weight:600; font-variant-numeric:tabular-nums; }}
  table {{ width:100%; border-collapse:collapse; background:#161b22; border:1px solid #30363d;
           border-radius:8px; overflow:hidden; margin:12px 0; }}
  th, td {{ padding:7px 10px; text-align:left; font-size:.83rem; border-bottom:1px solid #30363d;
            font-variant-numeric:tabular-nums; }}
  th {{ background:#1f2630; color:#8b949e; font-weight:500; text-transform:uppercase;
        font-size:.68rem; letter-spacing:.5px; }}
  tr:last-child td {{ border-bottom:none; }}
  tr.highlight td {{ background:rgba(88,166,255,0.08); }}
  .cat {{ font-size:.68rem; padding:1px 6px; background:#1f2630; border-radius:3px; color:#8b949e; }}
  .alert {{ background:rgba(248,81,73,0.12); border:1px solid #f85149; border-radius:6px;
            padding:12px; margin:12px 0; }}
  .pos {{ color:#3fb950; }}
  .neg {{ color:#f85149; }}
  code {{ background:#0d1117; padding:1px 5px; border-radius:3px; font-size:.85rem; }}
  .footer {{ margin-top:30px; color:#8b949e; font-size:.75rem; border-top:1px solid #30363d;
             padding-top:12px; }}
  .sub {{ color:#8b949e; font-size:.85rem; margin-bottom:14px; }}
  .links a {{ color:#58a6ff; text-decoration:none; margin-right:14px; }}
  .links a:hover {{ text-decoration:underline; }}
</style>
</head>
<body>

<h1>Informe operativo VelocityQuant — {date}</h1>
<div class="sub">
  Report ID: <code>{rid}</code> · Generado: {gen}
  <div class="links" style="margin-top:6px;">
    <a href="report.md" download>📄 descargar .md (para Gemma)</a>
    <a href="report.json" download>🗂 descargar .json</a>
    <a href="../">← volver al índice</a>
  </div>
</div>

<h2>1. Sidecar Polymarket — ahora</h2>
<div class="grid">
  <div class="card"><h3>τ_final</h3>
    <div class="big" style="color:{tau_c_color}">{tau_final_str}</div></div>
  <div class="card"><h3>τ_crypto</h3>
    <div class="big">{fmt_float(sc.get('tau_crypto') if isinstance(sc, dict) else None, 3)}</div></div>
  <div class="card"><h3>τ_macro</h3>
    <div class="big">{fmt_float(sc.get('tau_macro') if isinstance(sc, dict) else None, 3)}</div></div>
  <div class="card"><h3>ρ Polymarket↔BTC</h3>
    <div class="big">{fmt_float(sc.get('rho') if isinstance(sc, dict) else None, 3)}</div></div>
  <div class="card"><h3>Mode</h3>
    <div class="big" style="font-size:1.2rem">{sc.get('mode') if isinstance(sc, dict) else '—'}</div>
    <div class="muted">{(sc.get('mode_reason') if isinstance(sc, dict) else '') or ''}</div></div>
  <div class="card"><h3>BTC spot</h3>
    <div class="big">${fmt_int(int(sc.get('btc_price_usd') or 0)) if isinstance(sc, dict) else '—'}</div></div>
</div>

<h2>2. Macro events</h2>
{surprise_html}
<h3 style="font-size:.95rem">Próximos 24h (FMP)</h3>
<table><thead><tr>
  <th>Hora UTC</th><th>Evento</th><th>Cat</th><th>Prev</th><th>Forecast</th>
</tr></thead><tbody>{upcoming_rows}</tbody></table>

<h3 style="font-size:.95rem">Reacciones últimas 6h (Investing)</h3>
<table><thead><tr>
  <th>UTC</th><th>Evento</th><th>Cat</th><th>Actual</th><th>Fcst</th><th>SF</th>
</tr></thead><tbody>{recent_rows}</tbody></table>

<h2>3. V3.5 SHADOW Newark — actividad por ventana UTC</h2>
<table><thead><tr>
  <th>Ventana</th><th>Evts</th><th>w_send</th><th>%</th><th>CB blk</th>
  <th>p_max</th><th>p_sum</th><th>lat p50</th><th>lat p99</th><th>slag</th>
</tr></thead><tbody>{win_rows}</tbody></table>
<div class="muted">would_send=true son oportunidades que pasan filtros pre-CB. CB blocked = circuit breaker interno V3.5.
La fila <span style="color:#58a6ff">resaltada</span> es el solape Londres × Wall Street.</div>

{v4_section_html}

<div class="footer">
VelocityQuant report_generator v1.1 · {rid}<br>
Datos: Newark V3.5 SHADOW <code>cyclic_shadow.jsonl</code> + V4-Alpha observer <code>cyclic_shadow_v4.jsonl</code> · sidecar Polymarket+FMP+Investing+Pyth en Dallas.<br>
Este informe NO se borra. Histórico en <code>/poly/reports/</code>.
</div>

</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None, help="YYYY-MM-DD UTC, default=today UTC")
    args = parser.parse_args()

    date_str = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    report = assemble_report(date_str)
    rid = report["report_id"]
    folder = REPORTS_DIR / rid
    folder.mkdir(parents=True, exist_ok=False)

    md = render_md(report)
    html = render_html(report, md)

    (folder / "report.json").write_text(json.dumps(report, indent=2, default=str))
    (folder / "report.md").write_text(md)
    (folder / "report.html").write_text(html)

    print(json.dumps({
        "status": "ok",
        "report_id": rid,
        "folder": str(folder),
        "files": ["report.json", "report.md", "report.html"],
    }))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}))
        sys.exit(1)
