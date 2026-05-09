"""
forecasts_validator.py · validación de forecasts.json antes de carga al sidecar
Firmado: Gemma 4 31B en r150-bis (Q19 ranges) + r150-quad (P1 GO)

Ejecución:
    python3 forecasts_validator.py /path/to/forecasts.json

Returns exit code:
    0 = válido, todos los gates pass
    1 = JSON syntax error
    2 = schema violation (missing required fields)
    3 = range violation
    4 = signature mismatch (hash != forecasts.signed)
    5 = type error (e.g. string in pct field)
"""

from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path
from typing import Any


# Per Gemma r150-bis Q19 · 10 metric ranges (basados en histórico US macro 1947-2026)
RANGE_LIMITS_BY_METRIC: dict[str, tuple[float, float]] = {
    "cpi_yoy_pct":           (-3.0, 15.0),    # historical max 14.6% (1980), min -2.1% (2009)
    "cpi_mom_pct":           (-2.0,  5.0),    # extreme MoM bounds
    "core_cpi_yoy_pct":      ( 0.0, 13.0),    # core never went negative
    "core_cpi_mom_pct":      (-1.0,  3.0),
    "nfp_change_thousands":  (-2000.0, 2000.0),  # +/- 2M jobs
    "unemployment_rate_pct": ( 2.5, 25.0),
    "pce_yoy_pct":           (-3.0, 15.0),
    "fomc_funds_target_pct": ( 0.0, 25.0),    # 1981 max ~20%
    "ppi_yoy_pct":           (-12.0, 25.0),   # PPI más volátil
    "retail_sales_mom_pct":  (-25.0, 25.0),   # COVID lockdown extreme
}

# Required schema fields per event entry
REQUIRED_EVENT_FIELDS = {"category", "release_date", "primary_metric_for_sf", "forecasts"}


class ValidationError(Exception):
    """Raised when validation fails. Contains exit code + message."""
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code
        self.msg = msg


def gate_json_syntax(path: Path) -> dict[str, Any]:
    """Gate 0: JSON parses without exception."""
    try:
        with path.open() as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValidationError(1, f"JSON syntax error: {e}")
    except FileNotFoundError:
        raise ValidationError(1, f"file not found: {path}")


def gate_schema(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Gate 1: top-level has 'events' array of dicts with required fields."""
    if not isinstance(data, dict):
        raise ValidationError(2, "top-level must be dict")
    events = data.get("events")
    if not isinstance(events, list):
        raise ValidationError(2, "missing or invalid 'events' (must be list)")
    if not events:
        raise ValidationError(2, "'events' list is empty")
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            raise ValidationError(2, f"event[{i}] is not a dict")
        missing = REQUIRED_EVENT_FIELDS - set(ev.keys())
        if missing:
            raise ValidationError(2, f"event[{i}] missing fields: {missing}")
        if not isinstance(ev["forecasts"], dict):
            raise ValidationError(2, f"event[{i}].forecasts must be dict")
    return events


def gate_types(events: list[dict[str, Any]]) -> None:
    """Gate 2: forecast values must be numeric (int or float)."""
    for i, ev in enumerate(events):
        for metric, value in ev["forecasts"].items():
            if value is None:
                continue
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValidationError(
                    5,
                    f"event[{i}].forecasts.{metric} = {value!r} (type {type(value).__name__}) — must be numeric"
                )


def gate_range(events: list[dict[str, Any]]) -> list[str]:
    """Gate 3: each metric value within historical range. Returns list of warnings (out-of-range)."""
    violations = []
    for i, ev in enumerate(events):
        for metric, value in ev["forecasts"].items():
            if value is None:
                continue
            limits = RANGE_LIMITS_BY_METRIC.get(metric)
            if limits is None:
                # Unknown metric · don't fail, just warn
                violations.append(f"event[{i}].forecasts.{metric}: unknown metric (no range defined)")
                continue
            lo, hi = limits
            if not (lo <= value <= hi):
                raise ValidationError(
                    3,
                    f"event[{i}].forecasts.{metric} = {value} out of historical range [{lo}, {hi}]"
                )
    return violations


def gate_not_default_zero(events: list[dict[str, Any]]) -> list[str]:
    """Gate 4 (Gemma): metrics ending in 'pct' should not be 0.0 (uninitialized default suspicious)."""
    warnings = []
    for i, ev in enumerate(events):
        for metric, value in ev["forecasts"].items():
            if value == 0.0 and "pct" in metric:
                warnings.append(
                    f"event[{i}].forecasts.{metric} = 0.0 (suspicious for pct-type metric · verify intentional)"
                )
    return warnings


def gate_decimal_precision(events: list[dict[str, Any]]) -> list[str]:
    """Gate 5: limit decimal precision to 4 places (typo detection)."""
    warnings = []
    for i, ev in enumerate(events):
        for metric, value in ev["forecasts"].items():
            if value is None or not isinstance(value, (int, float)):
                continue
            s = f"{value}"
            if "." in s:
                decimals = len(s.split(".")[-1])
                if decimals > 4:
                    warnings.append(
                        f"event[{i}].forecasts.{metric} = {value} ({decimals} decimals · verify intentional)"
                    )
    return warnings


def compute_hash(path: Path) -> str:
    """SHA256 hash of file content for signature comparison."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gate_signature_match(path: Path) -> bool | None:
    """Gate 6: file hash matches forecasts.signed (if exists). Returns None if no .signed."""
    signed_path = path.parent / "forecasts.signed"
    if not signed_path.exists():
        return None
    try:
        signed_data = json.loads(signed_path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValidationError(4, f"forecasts.signed corrupted")
    expected_hash = signed_data.get("hash")
    actual_hash = compute_hash(path)
    if expected_hash != actual_hash:
        raise ValidationError(
            4,
            f"hash mismatch · expected {expected_hash[:16]}... · actual {actual_hash[:16]}..."
        )
    return True


def validate(path: Path, *, require_signature: bool = False) -> dict[str, Any]:
    """Full validation pipeline. Returns report dict.

    Args:
        path: forecasts.json path
        require_signature: if True, missing forecasts.signed = ValidationError code 4

    Raises ValidationError on first FAIL.
    Returns report on success (may include non-fatal warnings).
    """
    report: dict[str, Any] = {
        "path": str(path),
        "hash": None,
        "events_count": 0,
        "warnings": [],
        "signed": None,
    }

    # Gate 0
    data = gate_json_syntax(path)

    # Gate 1
    events = gate_schema(data)
    report["events_count"] = len(events)

    # Gate 2
    gate_types(events)

    # Gate 3
    report["warnings"].extend(gate_range(events))

    # Gate 4
    report["warnings"].extend(gate_not_default_zero(events))

    # Gate 5
    report["warnings"].extend(gate_decimal_precision(events))

    # Gate 6
    sig_result = gate_signature_match(path)
    report["signed"] = sig_result
    if sig_result is None and require_signature:
        raise ValidationError(4, "no forecasts.signed found and require_signature=True")

    report["hash"] = compute_hash(path)
    report["status"] = "PASS"
    return report


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: forecasts_validator.py /path/to/forecasts.json [--require-signature]")
        return 2
    path = Path(argv[1])
    require_sig = "--require-signature" in argv

    try:
        report = validate(path, require_signature=require_sig)
        print(json.dumps(report, indent=2))
        if report["warnings"]:
            print(f"\n⚠ {len(report['warnings'])} non-fatal warnings (file accepted)")
        else:
            print("\n✅ All gates PASS")
        return 0
    except ValidationError as e:
        print(json.dumps({"status": "FAIL", "code": e.code, "error": e.msg}, indent=2))
        return e.code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
