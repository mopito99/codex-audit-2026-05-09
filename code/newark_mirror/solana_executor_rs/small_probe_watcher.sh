#!/bin/bash
MAX_BUNDLES=20
MAX_MINUTES=90
BUNDLES=/home/ubuntu/solana_executor_rs/data/bundles.jsonl
LOG=/home/ubuntu/solana_executor_rs/data/small_probe_cron.log
DEACTIVATE=/home/ubuntu/solana_executor_rs/small_probe_deactivate.sh
ENV=/home/ubuntu/solana_executor_rs/.env

# Snapshot al inicio de sesión (clave: bundleId en camelCase)
INICIO_SENT=$(grep -c '"bundleId"' "$BUNDLES" 2>/dev/null || echo 0)
INICIO_LANDED=$(grep -c '"landed"' "$BUNDLES" 2>/dev/null || echo 0)
echo "[$(date -u)] watcher iniciado — baseline: sent=$INICIO_SENT landed=$INICIO_LANDED" >> $LOG

DEADLINE=$(( $(date +%s) + MAX_MINUTES * 60 ))

while true; do
    NOW=$(date +%s)
    if [ $NOW -ge $DEADLINE ]; then
        echo "[$(date -u)] TIMEOUT ${MAX_MINUTES}min" >> $LOG
        bash "$DEACTIVATE" "timeout_${MAX_MINUTES}min"
        exit 0
    fi

    TOTAL_SENT=$(grep -c '"bundleId"' "$BUNDLES" 2>/dev/null || echo 0)
    TOTAL_LANDED=$(grep -c '"landed"' "$BUNDLES" 2>/dev/null || echo 0)
    SESSION_SENT=$(( TOTAL_SENT - INICIO_SENT ))
    SESSION_LANDED=$(( TOTAL_LANDED - INICIO_LANDED ))

    if [ $SESSION_SENT -gt 0 ]; then
        echo "[$(date -u)] sesión: sent=$SESSION_SENT landed=$SESSION_LANDED" >> $LOG
    fi

    if [ $SESSION_SENT -ge $MAX_BUNDLES ]; then
        LR_PCT=$(python3 -c "s=$SESSION_SENT; l=$SESSION_LANDED; print(f'{l/s*100:.1f}' if s>0 else '0')" 2>/dev/null || echo 0)
        echo "[$(date -u)] === 20 BUNDLES — sent=$SESSION_SENT landed=$SESSION_LANDED LR=${LR_PCT}% ===" >> $LOG

        if [ "$SESSION_LANDED" -ge 6 ]; then
            echo "[$(date -u)] LR≥30% ✅ — ESCALANDO a full probe \$3000" >> $LOG
            sed -i 's/^SMALL_PROBE_MODE=.*/SMALL_PROBE_MODE=false/' "$ENV"
            sudo systemctl restart solana-executor-rs
            echo "[$(date -u)] LIVE \$3000 activado. Watcher termina." >> $LOG
        else
            echo "[$(date -u)] LR<30% (${LR_PCT}%) ❌ — volviendo a PAPER para diagnóstico" >> $LOG
            bash "$DEACTIVATE" "lr_bajo_${LR_PCT}pct"
        fi
        exit 0
    fi

    sleep 30
done
