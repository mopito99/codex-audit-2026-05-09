TARGET="/srv/quantum_ppo/models_v41/qppo_v41_phase1_complete.zip"
touch /srv/quantum_ppo/logs/sentinel.log
echo "Sentinela armado. Esperando cruce de 70M steps..." > /srv/quantum_ppo/logs/sentinel.log

while true; do
    if [ -f "$TARGET" ]; then
        echo "[Fri Apr 24 15:40:13 UTC 2026] DETECTADA FINALIZACION FASE 2 (70M STEPS)" >> /srv/quantum_ppo/logs/sentinel.log
        echo "Matando tmux session quantum_v41 para evitar Phase 3 corrupta..." >> /srv/quantum_ppo/logs/sentinel.log
        tmux kill-session -t quantum_v41
        echo "Proceso liquidado. Listo para intervencion manual V4.2." >> /srv/quantum_ppo/logs/sentinel.log
        break
    fi
    sleep 2
done
