#!/bin/bash
# Script para activar Fase 2: Aprendizaje Acelerado
# Se ejecuta automáticamente el lunes cuando abre CME (00:00 UTC)

LOG="/var/log/quantum_fast_learning.log"
CONFIG="/srv/profitlab_quantum/app/config.py"

echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') - Activando Fase 2: Aprendizaje Acelerado" >> $LOG

# Cambiar UPDATE_EVERY de 4h a 2h
sed -i 's/PPO_CHUNK_UPDATE_EVERY_HOURS", "4"/PPO_CHUNK_UPDATE_EVERY_HOURS", "2"/' $CONFIG

echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') - Config actualizada: Entrenamiento cada 2 horas" >> $LOG

# Reiniciar el bot
cd /srv/profitlab_quantum
pkill -f "python.*main.py"
sleep 3
source venv/bin/activate
nohup python -u main.py >> /var/log/quantum.log 2>&1 &

echo "$(date -u '+%Y-%m-%d %H:%M:%S UTC') - Bot reiniciado con aprendizaje acelerado (12 updates/dia)" >> $LOG
