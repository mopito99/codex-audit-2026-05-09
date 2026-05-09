#!/usr/bin/env python3
"""log_rotator.py — P5.0 firmado Gemma r150-novum.

Archive logs >30 days old to:
    /sda-disk/archive/<host>/<service>/<YYYY-MM-DD>/

Targets (Dallas host = cuandeoro):
- /home/administrator/poly_sidecar/data/sidecar.log
- /home/administrator/poly_sidecar/data/audit/*.log
- /var/log/syslog* (read-only — skip, owned by root)

Targets (Newark — V4-Alpha cyclic_shadow):
- Out of scope this script (SSH-based separate timer if/when needed)

Strategy: find files >30d mtime, gzip if not already, mv to archive dir.
Idempotent: re-running same day does nothing if files are already moved.

Run via systemd timer (poly_log_rotator.timer) daily 03:30 UTC.

Exit codes:
- 0  success (zero or N files archived)
- 1  archive root not writable
- 2  source dir does not exist
- 3  partial failure (some files archived, some failed)
"""
from __future__ import annotations

import datetime as dt
import gzip
import logging
import shutil
import socket
import sys
from pathlib import Path

ARCHIVE_ROOT = Path("/sda-disk/archive")
HOST = socket.gethostname()
RETENTION_DAYS = 30

# (service_name, source_dir_or_file, file_glob)
TARGETS: list[tuple[str, Path, str]] = [
    ("poly_sidecar", Path("/home/administrator/poly_sidecar/data"), "sidecar.log*"),
    ("poly_sidecar_audit", Path("/home/administrator/poly_sidecar/data/audit"), "*.log"),
    ("poly_sidecar_audit", Path("/home/administrator/poly_sidecar/data/audit"), "*.json"),
]

LOGGER = logging.getLogger("log_rotator")


def archive_file(src: Path, service: str, file_date: dt.date) -> bool:
    """Archive src to /sda-disk/archive/<host>/<service>/<YYYY-MM-DD>/.

    Gzip compresses if not already .gz. Returns True on success.
    """
    dest_dir = ARCHIVE_ROOT / HOST / service / file_date.isoformat()
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        LOGGER.error(f"mkdir {dest_dir} failed: {exc}")
        return False

    if src.suffix == ".gz":
        dest = dest_dir / src.name
    else:
        dest = dest_dir / (src.name + ".gz")

    if dest.exists():
        LOGGER.info(f"already archived: {dest}")
        try:
            src.unlink()
        except OSError:
            pass
        return True

    try:
        if src.suffix == ".gz":
            shutil.move(str(src), str(dest))
        else:
            with src.open("rb") as f_in, gzip.open(dest, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            src.unlink()
        LOGGER.info(f"archived: {src} -> {dest}")
        return True
    except OSError as exc:
        LOGGER.error(f"archive {src} failed: {exc}")
        return False


def rotate(dry_run: bool = False) -> int:
    """Rotate. Return 0 on success, 1/2/3 on errors."""
    if not ARCHIVE_ROOT.exists():
        LOGGER.error(f"archive root missing: {ARCHIVE_ROOT}")
        return 1
    if not ARCHIVE_ROOT.is_dir():
        LOGGER.error(f"archive root not a dir: {ARCHIVE_ROOT}")
        return 1

    cutoff_ts = (dt.datetime.now() - dt.timedelta(days=RETENTION_DAYS)).timestamp()
    archived = 0
    failed = 0

    for service, src_dir, glob in TARGETS:
        if not src_dir.exists():
            LOGGER.debug(f"source dir missing (skipping): {src_dir}")
            continue
        for fp in src_dir.glob(glob):
            try:
                mtime = fp.stat().st_mtime
            except OSError:
                continue
            if mtime >= cutoff_ts:
                continue
            file_date = dt.date.fromtimestamp(mtime)
            if dry_run:
                LOGGER.info(f"[dry-run] would archive {fp} (mtime={file_date})")
                archived += 1
                continue
            ok = archive_file(fp, service, file_date)
            if ok:
                archived += 1
            else:
                failed += 1

    LOGGER.info(f"summary: archived={archived} failed={failed}")
    if failed > 0 and archived > 0:
        return 3
    if failed > 0:
        return 1
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    dry_run = "--dry-run" in sys.argv
    return rotate(dry_run=dry_run)


if __name__ == "__main__":
    sys.exit(main())
