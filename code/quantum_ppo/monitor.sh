#!/bin/bash
# =========================================================
#  QUANTUM PPO — Monitor de Entrenamiento en Vivo
#  Uso: bash /srv/quantum_ppo/monitor.sh
# =========================================================

LOG="/srv/quantum_ppo/train_v2.log"
TOTAL=10000000

# Colores
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

clear
echo -e "${BOLD}${CYAN}"
echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║         QUANTUM PPO — Monitor de Entrenamiento       ║"
echo "  ║         SOL/USDT · 5m · Futuros x5 · A100 GPU       ║"
echo "  ╚══════════════════════════════════════════════════════╝"
echo -e "${RESET}"

# Verificar si el proceso está vivo
PID=$(pgrep -f "python3 /srv/quantum_ppo/train.py")
if [ -z "$PID" ]; then
    echo -e "${RED}  ⚠️  Proceso de entrenamiento NO está corriendo.${RESET}"
else
    echo -e "${GREEN}  ✅ Proceso ACTIVO — PID: $PID${RESET}"
fi

# Extraer métricas del log (formato tabla: | key | value |)
EP_REW=$(grep "ep_rew_mean" "$LOG" | tail -1 | awk -F'|' '{gsub(/ /,"",$3); print $3}')
EP_LEN=$(grep "ep_len_mean" "$LOG" | tail -1 | awk -F'|' '{gsub(/ /,"",$3); print $3}')
FPS=$(grep "   fps " "$LOG" | tail -1 | awk -F'|' '{gsub(/ /,"",$3); print $3}')
STEPS=$(grep "total_timesteps" "$LOG" | tail -1 | awk -F'|' '{gsub(/ /,"",$3); print $3}' | tr -d ',')
ELAPSED=$(grep "time_elapsed" "$LOG" | tail -1 | awk -F'|' '{gsub(/ /,"",$3); print $3}')
ENTROPY=$(grep "entropy_loss" "$LOG" | tail -1 | awk -F'|' '{gsub(/ /,"",$3); print $3}')
VAL_LOSS=$(grep "value_loss" "$LOG" | tail -1 | awk -F'|' '{gsub(/ /,"",$3); print $3}')
EXP_VAR=$(grep "explained_variance" "$LOG" | tail -1 | awk -F'|' '{gsub(/ /,"",$3); print $3}')

# Calcular progreso
if [ -n "$STEPS" ] && [ "$STEPS" -gt 0 ] 2>/dev/null; then
    PROGRESO=$(echo "scale=1; $STEPS * 100 / $TOTAL" | bc)
    RESTANTE_S=$(echo "scale=0; ($TOTAL - $STEPS) / $FPS" | bc 2>/dev/null)
    RESTANTE_M=$(echo "scale=0; $RESTANTE_S / 60" | bc 2>/dev/null)
    ELAPSED_M=$(echo "scale=0; $ELAPSED / 60" | bc 2>/dev/null)
    
    # Barra de progreso
    FILLED=$(echo "scale=0; $PROGRESO / 2" | bc)
    BAR=$(printf '█%.0s' $(seq 1 $FILLED))$(printf '░%.0s' $(seq 1 $((50-FILLED))))
else
    PROGRESO="0.0"; RESTANTE_M="N/A"; ELAPSED_M="0"; BAR=$(printf '░%.0s' $(seq 1 50))
fi

echo ""
echo -e "  ${BOLD}📈 PROGRESO TOTAL${RESET}"
echo -e "  [${CYAN}${BAR}${RESET}] ${BOLD}${PROGRESO}%${RESET}"
echo -e "  Pasos: ${YELLOW}${STEPS}${RESET} / ${TOTAL}"
echo -e "  ⏱  Transcurrido: ${ELAPSED_M} min  |  Restante estimado: ${YELLOW}~${RESTANTE_M} min${RESET}  |  FPS: ${FPS}"

echo ""
echo -e "  ${BOLD}🧠 SALUD DEL CEREBRO (Señales Vitales)${RESET}"
echo -e "  ┌─────────────────────────────────────────────────┐"

# Estado de ep_rew_mean
if (( $(echo "$EP_REW > 0" | bc -l 2>/dev/null) )); then
    BADGE="${GREEN}🟢 GANANDO${RESET}"
elif (( $(echo "$EP_REW > -30" | bc -l 2>/dev/null) )); then
    BADGE="${YELLOW}🟡 APRENDIENDO${RESET}"
else
    BADGE="${RED}🔴 BEBÉ (Normal al inicio)${RESET}"
fi
echo -e "  │  Recompensa Promedio  : ${BOLD}${EP_REW}${RESET}  ← ${BADGE}"
echo -e "  │  Duración de vida     : ${EP_LEN} velas (~$(echo "scale=0; ${EP_LEN:-0} * 5 / 60" | bc) horas de mercado)"
echo -e "  │  Entropía (Curiosidad): ${ENTROPY}  ← ${YELLOW}(ideal: -0.5 a -1.5)${RESET}"
echo -e "  │  Var. Explicada       : ${EXP_VAR}  ← ${YELLOW}(meta: cerca de 1.0)${RESET}"
echo -e "  │  Value Loss           : ${VAL_LOSS}  ← ${YELLOW}(debe bajar con el tiempo)${RESET}"
echo -e "  └─────────────────────────────────────────────────┘"

echo ""
echo -e "  ${BOLD}📦 MODELOS GUARDADOS (Checkpoints)${RESET}"
ls /srv/quantum_ppo/models/ 2>/dev/null | head -10 | while read f; do
    echo -e "  ✦ $f"
done

echo ""
echo -e "  ${BOLD}📝 Últimas 3 líneas del Log:${RESET}"
tail -5 "$LOG" | grep -v "^$" | tail -3 | while read line; do
    echo -e "  ${CYAN}│${RESET} $line"
done

echo ""
echo -e "  ${YELLOW}Actualiza con:  bash /srv/quantum_ppo/monitor.sh${RESET}"
echo ""
