"""
sign_forecasts.py · doble-firma SHA256 con confirmación interactiva
Firmado: Gemma 4 31B en r150-bis (Q22 doble-firma) + r150-quad (P1 GO)

Flujo:
    1. Marco edita forecasts.json con valores nuevos
    2. Ejecuta: python3 sign_forecasts.py /path/to/forecasts.json
    3. Script muestra summary de los forecasts y pide confirmación interactiva
    4. Si Marco escribe 'YES', genera forecasts.signed con hash + timestamp + signer
    5. Si NO, aborta sin firmar

forecasts.signed format:
    {
        "hash": "<sha256 hex>",
        "signed_at_utc": "<ISO 8601>",
        "signed_by": "marco",
        "events_summary": [...]
    }

Sidecar load logic comprueba que `compute_hash(forecasts.json) == forecasts.signed.hash`
antes de aceptar el load. Si no coincide → reject + alert.

Ejecución:
    python3 sign_forecasts.py /path/to/forecasts.json
    # Modo non-interactive (CI):
    python3 sign_forecasts.py /path/to/forecasts.json --yes-i-understand
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import forecasts_validator as fv


def compute_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_summary(events: list[dict]) -> str:
    """Human-readable summary for confirmation prompt."""
    lines = ["─" * 60]
    for i, ev in enumerate(events):
        lines.append(f"  Event {i+1} · {ev.get('category')} · {ev.get('release_date')}")
        lines.append(f"    primary_metric: {ev.get('primary_metric_for_sf')}")
        for metric, value in ev.get("forecasts", {}).items():
            primary_marker = " ★" if metric == ev.get("primary_metric_for_sf") else ""
            lines.append(f"    {metric}: {value}{primary_marker}")
        if ev.get("previous"):
            lines.append("    previous:")
            for metric, value in ev["previous"].items():
                lines.append(f"      {metric}: {value}")
        lines.append("")
    lines.append("─" * 60)
    return "\n".join(lines)


def sign(path: Path, *, signer: str = "marco", non_interactive: bool = False) -> int:
    """Generate forecasts.signed alongside forecasts.json.

    Returns exit code:
        0 = signed
        1 = validation FAIL (won't sign invalid file)
        2 = user rejected confirmation
        3 = file not found
    """
    if not path.exists():
        print(f"ERROR: {path} not found")
        return 3

    # Step 1: validate first (won't sign invalid JSON)
    print(f"Validating {path}...")
    try:
        report = fv.validate(path, require_signature=False)
    except fv.ValidationError as e:
        print(f"❌ Validation FAILED (code {e.code}): {e.msg}")
        print("Won't sign invalid file. Fix errors first.")
        return 1

    print(f"✅ Validation PASS · {report['events_count']} events")
    if report["warnings"]:
        print(f"⚠ {len(report['warnings'])} non-fatal warnings:")
        for w in report["warnings"]:
            print(f"  · {w}")

    # Step 2: parse content for summary
    with path.open() as f:
        data = json.load(f)
    events = data.get("events", [])

    # Step 3: show summary
    print()
    print("FORECASTS A FIRMAR:")
    print(render_summary(events))

    # Step 4: confirmation
    new_hash = compute_hash(path)
    print(f"SHA256: {new_hash}")
    print()

    if non_interactive:
        confirm = "YES"
        print("Non-interactive mode: assuming YES")
    else:
        prompt = f"¿Confirmas estos forecasts y los firmas como '{signer}'? (escribir 'YES' literal): "
        try:
            confirm = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            confirm = ""

    if confirm != "YES":
        print(f"❌ Aborted: confirmation '{confirm}' != 'YES'. No signature written.")
        return 2

    # Step 5: write forecasts.signed
    signed_path = path.parent / "forecasts.signed"

    # Backup previous signature if exists (rotación implícita)
    if signed_path.exists():
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = path.parent / f"forecasts.signed.bak.{ts}"
        backup.write_text(signed_path.read_text())
        print(f"Previous signature backed up: {backup.name}")

    signed_data = {
        "hash": new_hash,
        "hash_algorithm": "sha256",
        "signed_at_utc": datetime.now(timezone.utc).isoformat(),
        "signed_by": signer,
        "forecasts_path": str(path),
        "events_count": len(events),
        "events_summary": [
            {
                "category": ev.get("category"),
                "release_date": ev.get("release_date"),
                "primary_metric_for_sf": ev.get("primary_metric_for_sf"),
                "primary_value": ev.get("forecasts", {}).get(ev.get("primary_metric_for_sf")),
            }
            for ev in events
        ],
        "validator_warnings": report["warnings"],
    }

    signed_path.write_text(json.dumps(signed_data, indent=2) + "\n")
    print()
    print(f"✅ FIRMADO · {signed_path}")
    print(f"   hash: {new_hash[:16]}...")
    print(f"   signed_at_utc: {signed_data['signed_at_utc']}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: sign_forecasts.py /path/to/forecasts.json [--signer NAME] [--yes-i-understand]")
        return 1

    path = Path(argv[1])
    signer = "marco"
    if "--signer" in argv:
        idx = argv.index("--signer")
        if idx + 1 < len(argv):
            signer = argv[idx + 1]
    non_interactive = "--yes-i-understand" in argv

    return sign(path, signer=signer, non_interactive=non_interactive)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
