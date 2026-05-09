#!/usr/bin/env bash
# Q27 · restore_last_valid.sh
# Restaura forecasts.json desde el backup más reciente que pase validación.
#
# Trigger:
#   - Cron pre-event (4h antes de cualquier release tracked)
#   - Manual: cuando validator detecta corruption
#   - Sidecar.py al startup si forecasts.json fails JSON syntax check
#
# Permisos:
#   - El script debe correr como user `administrator` (mismo dueño que /home/administrator/poly_sidecar/)
#   - cp con preserve flags para mantener mode 644
#   - Falla loud si permission error (no silent skip)
#
# Lógica:
#   1. Identificar forecasts.bak.*.json en directorio
#   2. Iterar de más reciente a más antiguo
#   3. Para cada candidato: validar JSON syntax + range_check
#   4. Primer candidato que pase → cp como forecasts.json
#   5. Si ninguno pasa → exit 1 + alert
#
# Exit codes:
#   0 = restored OK
#   1 = no valid backup found
#   2 = filesystem/permission error
#   3 = invalid current forecasts.json AND restore failed

set -e
set -o pipefail

DIR="/home/administrator/poly_sidecar"
TARGET="${DIR}/forecasts.json"
SIGNED="${DIR}/forecasts.signed"
LOG="/var/log/forecasts_restore.log"
VALIDATOR="${DIR}/forecasts_validator.py"
PYTHON="${DIR}/venv/bin/python3"

# Functions ────────────────────────────────────────────────────────────
log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*" | tee -a "$LOG" >&2; }

err() { log "ERROR: $*"; exit "${2:-1}"; }

check_permissions() {
    if [ ! -d "$DIR" ]; then err "directory $DIR missing" 2; fi
    if [ ! -w "$DIR" ]; then err "no write permission on $DIR (run as administrator user)" 2; fi
    if [ -f "$TARGET" ] && [ ! -w "$TARGET" ]; then err "no write permission on $TARGET" 2; fi
}

validate_json() {
    local file="$1"
    "$PYTHON" -c "import json; json.load(open('$file'))" 2>/dev/null
}

validate_ranges() {
    local file="$1"
    if [ ! -f "$VALIDATOR" ]; then
        log "WARN: forecasts_validator.py missing — skip range_check (only JSON syntax)"
        return 0
    fi
    "$PYTHON" "$VALIDATOR" --validate "$file" >/dev/null 2>&1
}

# Main ──────────────────────────────────────────────────────────────────
log "=== restore_last_valid.sh starting ==="
check_permissions

# Step 1: List backups newest first
mapfile -t BACKUPS < <(
    find "$DIR" -maxdepth 1 -type f -name "forecasts.bak.*.json" -printf '%T@ %p\n' \
        | sort -rn \
        | awk '{print $2}'
)

if [ "${#BACKUPS[@]}" -eq 0 ]; then
    err "no forecasts.bak.*.json found in $DIR" 1
fi

log "found ${#BACKUPS[@]} backup candidates"

# Step 2-3: Iterate, validate
for BAK in "${BACKUPS[@]}"; do
    log "trying $BAK"

    if ! validate_json "$BAK"; then
        log "  ✗ JSON syntax invalid, skip"
        continue
    fi

    if ! validate_ranges "$BAK"; then
        log "  ✗ range_check failed, skip"
        continue
    fi

    # Step 4: Restore
    log "  ✓ valid · restoring as $TARGET"

    # Backup current (corrupted) forecasts.json before overwriting
    if [ -f "$TARGET" ]; then
        CORRUPT_TS=$(date -u +%Y%m%dT%H%M%SZ)
        cp -p "$TARGET" "${TARGET}.corrupted.${CORRUPT_TS}" 2>>"$LOG" || \
            log "  WARN: could not backup current corrupted target"
    fi

    # Atomic copy
    TMP=$(mktemp "${TARGET}.tmp.XXXXXX")
    cp -p "$BAK" "$TMP" || err "cp $BAK → $TMP failed" 2
    mv -f "$TMP" "$TARGET" || err "mv $TMP → $TARGET failed" 2

    # Re-sign with new hash (forecasts.signed becomes invalid until Marco re-signs)
    NEW_HASH=$(sha256sum "$TARGET" | cut -d' ' -f1)
    cat > "$SIGNED" <<SIGEOF
{
  "hash_sha256": "$NEW_HASH",
  "signed_at_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "signed_by": "AUTO_RESTORE",
  "source_backup": "$(basename "$BAK")",
  "requires_marco_re_sign": true
}
SIGEOF
    log "restored OK · hash=$NEW_HASH · ⚠ requires Marco re-sign before next event"

    # Alert (placeholder — could be email/slack hook)
    log "ALERT: forecasts.json restored from $BAK · Marco must re-sign before live event"

    exit 0
done

# Step 5: All failed
err "all ${#BACKUPS[@]} backup candidates failed validation" 1
