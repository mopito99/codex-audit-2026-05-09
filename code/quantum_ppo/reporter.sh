#!/bin/bash
# =========================================================
#  QUANTUM PPO — Reporter Automático cada 10 minutos
#  Corre en background, genera /srv/quantum_ppo/logs/report_latest.txt
# =========================================================

LOG="/srv/quantum_ppo/logs/train_v2.log"
REPORT="/srv/quantum_ppo/logs/report_latest.txt"
TOTAL=10000000
INTERVAL=600  # 10 minutos

while true; do
    NOW=$(date '+%Y-%m-%d %H:%M:%S')
    
    # Métricas del log
    EP_REW=$(grep "ep_rew_mean"     "$LOG" 2>/dev/null | tail -1 | awk -F'|' '{gsub(/ /,"",$3); print $3}')
    EP_LEN=$(grep "ep_len_mean"     "$LOG" 2>/dev/null | tail -1 | awk -F'|' '{gsub(/ /,"",$3); print $3}')
    FPS=$(grep "   fps "            "$LOG" 2>/dev/null | tail -1 | awk -F'|' '{gsub(/ /,"",$3); print $3}')
    STEPS=$(grep "total_timesteps"  "$LOG" 2>/dev/null | tail -1 | awk -F'|' '{gsub(/ /,"",$3); print $3}' | tr -d ',')
    ELAPSED=$(grep "time_elapsed"   "$LOG" 2>/dev/null | tail -1 | awk -F'|' '{gsub(/ /,"",$3); print $3}')
    ENTROPY=$(grep "entropy_loss"   "$LOG" 2>/dev/null | tail -1 | awk -F'|' '{gsub(/ /,"",$3); print $3}')
    VAL_LOSS=$(grep "value_loss"    "$LOG" 2>/dev/null | tail -1 | awk -F'|' '{gsub(/ /,"",$3); print $3}')
    EXP_VAR=$(grep "explained_variance" "$LOG" 2>/dev/null | tail -1 | awk -F'|' '{gsub(/ /,"",$3); print $3}')
    
    # PID activo
    PID=$(pgrep -fl "train.py" | grep -v "gemma" | head -1 | awk '{print $1}')
    if [ -n "$PID" ]; then
        STATUS="✅ CORRIENDO (PID: $PID)"
    else
        STATUS="🔴 DETENIDO"
    fi
    
    # Progreso
    if [ -n "$STEPS" ] && [ "$STEPS" -gt 0 ] 2>/dev/null; then
        PROGRESO=$(echo "scale=2; $STEPS * 100 / $TOTAL" | bc)
        if [ -n "$FPS" ] && [ "$FPS" -gt 0 ] 2>/dev/null; then
            RESTANTE_MIN=$(echo "scale=0; ($TOTAL - $STEPS) / $FPS / 60" | bc 2>/dev/null)
        else
            RESTANTE_MIN="N/A"
        fi
        ELAPSED_MIN=$(echo "scale=0; ${ELAPSED:-0} / 60" | bc 2>/dev/null)
    else
        PROGRESO="0.00"
        RESTANTE_MIN="N/A"
        ELAPSED_MIN="0"
        STEPS="0"
    fi

    # Estado del bot
    if (( $(echo "${EP_REW:-0} > 0" | bc -l 2>/dev/null) )); then
        SALUD="🟢 GANANDO"
    elif (( $(echo "${EP_REW:-0} > -30" | bc -l 2>/dev/null) )); then
        SALUD="🟡 APRENDIENDO"
    else
        SALUD="🔴 BEBÉ (normal al inicio)"
    fi

    # GPU
    GPU_INFO=$(nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits 2>/dev/null)
    GPU_UTIL=$(echo "$GPU_INFO" | awk -F',' '{print $1}' | tr -d ' ')
    GPU_MEM_USED=$(echo "$GPU_INFO" | awk -F',' '{print $2}' | tr -d ' ')
    GPU_MEM_TOTAL=$(echo "$GPU_INFO" | awk -F',' '{print $3}' | tr -d ' ')
    GPU_TEMP=$(echo "$GPU_INFO" | awk -F',' '{print $4}' | tr -d ' ')

    # Checkpoints guardados
    CKPT_COUNT=$(ls /srv/quantum_ppo/models/*.zip 2>/dev/null | wc -l)

    # Escribir reporte
    cat > "$REPORT" << EOF
╔══════════════════════════════════════════════════════════╗
║         QUANTUM PPO — Reporte de Entrenamiento          ║
║         SOL/USDT · 5m · Futuros · RTX A5000            ║
╚══════════════════════════════════════════════════════════╝
📅 Generado: $NOW

🤖 PROCESO: $STATUS

📈 PROGRESO
   Pasos completados : $STEPS / $TOTAL
   Porcentaje        : $PROGRESO%
   Tiempo transcurrido: ${ELAPSED_MIN} min
   Tiempo restante   : ~${RESTANTE_MIN} min
   Velocidad (FPS)   : $FPS

🧠 SALUD DEL CEREBRO: $SALUD
   Recompensa promedio  : ${EP_REW:-N/A}  ← (>0 = ganando, >-30 = aprendiendo)
   Duración episodio    : ${EP_LEN:-N/A} velas
   Entropía (curiosidad): ${ENTROPY:-N/A}  ← (ideal: -0.5 a -1.5)
   Value Loss           : ${VAL_LOSS:-N/A}  ← (debe bajar)
   Varianza Explicada   : ${EXP_VAR:-N/A}  ← (meta: cerca de 1.0)

🖥️  GPU STATUS
   Utilización : ${GPU_UTIL}%
   VRAM usada  : ${GPU_MEM_USED} MiB / ${GPU_MEM_TOTAL} MiB
   Temperatura : ${GPU_TEMP}°C

💾 CHECKPOINTS guardados: $CKPT_COUNT archivo(s)
$(ls /srv/quantum_ppo/models/*.zip 2>/dev/null | xargs -I{} basename {} 2>/dev/null | sed 's/^/   ✦ /')

══════════════════════════════════════════════════════════
Próximo reporte en 10 minutos
EOF

    echo "[$NOW] Reporte generado → $REPORT"
    sleep $INTERVAL
done
