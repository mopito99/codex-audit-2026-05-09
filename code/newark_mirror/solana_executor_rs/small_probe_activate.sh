#!/bin/bash
ENV=/home/ubuntu/solana_executor_rs/.env
LOG=/home/ubuntu/solana_executor_rs/data/small_probe_cron.log
BUNDLES=/home/ubuntu/solana_executor_rs/data/bundles.jsonl

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] === ACTIVANDO SMALL PROBE LIVE ===" | tee -a $LOG

# Comprobar wallet key
if ! grep -q 'WALLET_PRIVATE_KEY=.' "$ENV"; then
    echo "[ERROR] WALLET_PRIVATE_KEY no configurada — abortando" | tee -a $LOG; exit 1
fi

# Obtener precio SOL en vivo
SOL_PRICE=$(python3 -c "
import urllib.request, json
try:
    r = urllib.request.urlopen('https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT', timeout=3)
    print(int(float(json.loads(r.read())['price'])))
except: print(83)" 2>/dev/null)
[ -z "$SOL_PRICE" ] && SOL_PRICE=83
sed -i "s/^SOL_PRICE_USD=.*/SOL_PRICE_USD=$SOL_PRICE/" "$ENV"
echo "[$(date -u)] SOL_PRICE_USD=$SOL_PRICE" | tee -a $LOG

# Bundles previos (para que el watcher cuente solo los de esta sesión)
BUNDLES_INICIO=$(grep -c '"bundle_id"' "$BUNDLES" 2>/dev/null || echo 0)
echo "[$(date -u)] bundles pre-sesión: $BUNDLES_INICIO" | tee -a $LOG

# Activar LIVE
sed -i 's/^PAPER_MODE=.*/PAPER_MODE=false/' "$ENV"
sed -i 's/^SMALL_PROBE_MODE=.*/SMALL_PROBE_MODE=true/' "$ENV"

sudo systemctl restart solana-executor-rs
sleep 4
STATUS=$(sudo systemctl is-active solana-executor-rs)
echo "[$(date -u)] servicio=$STATUS PAPER_MODE=false SMALL_PROBE_MODE=true probe=\$100 tip=0.03SOL_fijo" | tee -a $LOG

# Lanzar watcher en background
nohup bash /home/ubuntu/solana_executor_rs/small_probe_watcher.sh >> $LOG 2>&1 &
echo "[$(date -u)] watcher PID=$!" | tee -a $LOG
