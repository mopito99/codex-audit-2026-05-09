#!/bin/bash
# Desactiva Small Probe: vuelve a PAPER_MODE
ENV=/home/ubuntu/solana_executor_rs/.env
LOG=/home/ubuntu/solana_executor_rs/data/small_probe_cron.log

REASON=${1:-"timeout"}
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] === DESACTIVANDO SMALL PROBE (motivo: $REASON) ===" >> $LOG

sed -i 's/^PAPER_MODE=.*/PAPER_MODE=true/' "$ENV"
sed -i 's/^SMALL_PROBE_MODE=.*/SMALL_PROBE_MODE=false/' "$ENV"

sudo systemctl restart solana-executor-rs
sleep 3
STATUS=$(sudo systemctl is-active solana-executor-rs)
echo "[$(date -u)] servicio: $STATUS | vuelto a PAPER_MODE=true" >> $LOG

# Resumen de la sesión
BUNDLES=/home/ubuntu/solana_executor_rs/data/bundles.jsonl
SENT=$(grep -c '"bundle_id"' "$BUNDLES" 2>/dev/null || echo 0)
LANDED=$(grep -c '"landed"' "$BUNDLES" 2>/dev/null || echo 0)
LR=$(python3 -c "s=$SENT; l=$LANDED; print(f'{l/s*100:.1f}%' if s>0 else 'N/A')" 2>/dev/null)
echo "[$(date -u)] RESUMEN: sent=$SENT landed=$LANDED LR=$LR" >> $LOG
