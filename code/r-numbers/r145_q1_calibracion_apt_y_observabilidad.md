# r145 · Q1 mal calibrado en producción + apt-upgrade rompió burn-in + observabilidad SSH

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-07 07:30 UTC
**Asunto**: 3 hallazgos críticos post-r144 que requieren tu firma
**Estado burn-in**: T+13h44min de 24h (corrupto, ver §1)

---

## TL;DR — 3 hechos

1. **Q1 floor `LIQ_MIN_PROFIT_USD_SHADOW=0.10` está activo en producción desde 06:32 UTC** (no se aplicó a las 17:46 UTC como acordamos). Resultado: `would_send=0.0%` últimos 75min porque el 100% de los profits SHADOW están **debajo de $0.10**. La calibración Q1 que firmaste estaba mal.
2. **El deploy temprano NO fue humano**: lo causó `apt-daily-upgrade.service` (Ubuntu unattended-upgrades) que reinició liquidator_rs cuando actualizó libs del sistema. Esto es un **riesgo recurrente diario** para cualquier burn-in 24h.
3. **El "loop" de 1.7 SSH/sec a Newark que detecté no es amenaza externa**: es nuestra propia observabilidad de Dallas (5 timers + scripts). Funciona, pero ineficiente sin SSH ControlMaster.

---

## §1 — Q1 mal calibrado: realidad vs spec

### Lo que firmamos en r144

> "SHADOW: Mantener $0.10 (para medir el universo de oportunidades)."
> "LIVE: Implementar un hard-floor de $1.00."

### Lo que muestra la data REAL del sistema (5000 cycles SHADOW)

```
Distribución net_profit_usd últimos 1000 cycles:
  min       = $0.000085
  p25       = $0.0119
  p50       = $0.0157
  p75       = $0.0245
  p95       = $0.0356
  max       = $0.058
  positivos = 100%

Cycles con profit >= $0.10: 0 / 1000 (0.0%)
```

**El profit SHADOW típico está en milicéntimos**, no en céntimos. El floor $0.10 que propuse y firmaste es **6× el max observado**, no "filtro de ruido". Es una guillotina total.

### Implicación

`would_send=0.0%` rolling 60min post-Q1 deployment (vs **50.4% pre-r140 / pre-Q1**). Burn-in con métrica corrupta. CB calibration r140 (cb_blocked 19.5%, sub-15%) sigue **válida** porque opera sobre slot_lag, independiente del profit floor.

### 3 opciones (necesito tu firma)

| Opción | Acción | Resultado |
|---|---|---|
| (a) | `LIQ_MIN_PROFIT_USD_SHADOW=0.0` (sin floor SHADOW) | would_send vuelve a ~50%, burn-in válido, LIVE floor=$1.00 firmado intacto |
| (b) | `LIQ_MIN_PROFIT_USD_SHADOW=0.005` (filtra el 5% peor según distribución observada) | would_send ~45%, mantiene idea "filtro ruido" calibrado con data |
| (c) | Revertir binary al backup `liquidator_rs.bak_pre_q1q4_20260507T062733Z` hasta firma corregida | would_send vuelve a 50%, pero pierde Q1 arquitectura entera; tendríamos que reaplicar Q1 a las 17:46 |

**Mi voto**: (a). Floor SHADOW = 0 = comportamiento pre-Q1 exacto = burn-in íntegro = Q1 architecture preservada. Si quieres filtro real lo recalibramos post-LIVE con data realizada.

---

## §2 — apt-daily-upgrade reinició liquidator_rs sin previo aviso

### Cronología 06:32 UTC

```
06:32:17  apt.systemd.daily[315125]: unattended-upgrade running
06:32:21  systemd[1]: Stopping liquidator_rs.service
06:32:21  systemd[1]: Stopping vq-v4-shadow-observer.service
06:32:21  systemd[1]: Started liquidator_rs.service (PID 315327)
06:32:23  apt-daily-upgrade.service: Finished
```

### Cómo

Ubuntu `apt-daily-upgrade.timer` corre a las 06:13 UTC (con jitter). `unattended-upgrades` actualizó paquetes del sistema (probablemente libssl/libc/systemd). El paquete `needrestart` detectó que liquidator_rs usaba libs actualizadas y disparó `systemctl restart liquidator_rs.service` automáticamente. Sin prompt, sin notificación.

### Evidencia auditable

```
$ sudo journalctl -u apt-daily-upgrade.service --since '2026-05-07 06:30 UTC' | tail -5
$ sudo journalctl -u liquidator_rs --since '2026-05-07 06:32:00 UTC' --until '06:32:30 UTC'
# Ambos muestran la cadena timer → upgrade → restart
```

NO hubo `sudo systemctl restart` de mi sesión ni de Marco. El último restart manual fue 04:41:48 UTC (aplicación de r140 calibration).

### Riesgo recurrente

Cualquier día apt-daily-upgrade puede romper burn-in. Pasa típicamente entre 06:00-08:00 UTC con jitter aleatorio.

### Mitigación propuesta

```bash
# Pausar unattended-upgrades hasta post-LIVE Lun 12 12:30 UTC
sudo systemctl disable --now apt-daily-upgrade.timer
sudo systemctl disable --now apt-daily.timer
# Re-habilitar manualmente Mar 13 después de validar primer LIVE
```

Alternativa más quirúrgica: dejar timers pero excluir liquidator_rs de needrestart:
```
echo '$nrconf{override_rc}->{q(/usr/local/bin/liquidator_rs|liquidator_rs.service)} = 0;' \
  | sudo tee /etc/needrestart/conf.d/liquidator_rs.conf
```

¿Qué prefieres? **Mi voto**: pausar timers hasta Mar 13 (más simple, reversible, garantiza cero sorpresas durante NFP Vie 8 + CPI Lun 12).

---

## §3 — El "loop" 1.7 SSH/sec a Newark = nuestra propia observabilidad

Detecté que la IP `69.197.143.90` martillaba Newark con 23 SSH/min sostenido (1400/h pico). Verifiqué reverse-DNS: **es Dallas mismo (cuandeoro)**. Ridículo de mi parte no haberlo visto antes.

### Inventario de quién genera el tráfico (TU infra, no externa)

| Timer | Frecuencia | SSH/run | Función |
|---|---|---|---|
| `velocityquant-shadow-collector.timer` | 15s | ~10 | telemetry collector V4 |
| `vq-burnin-sample.timer` | 60s | 6 | KPI snapshot burn-in |
| `vq-shadow-rsync.timer` | 60s | 1 | mirror cyclic_shadow.jsonl |
| `sync-newark.timer` | 30min | 5 | dashboard stats |
| `hftbots-evaluator.timer` | 30s | 0 SSH | (eval local, no toca Newark) |
| `vq-pnl-snapshot.timer` | 5min | varios | snapshots dashboard PnL |

Total: **~30-50 SSH/min teórico, ~23 SSH/min observado**. Todo deliberado.

### Costo real

- ~33,000 conexiones SSH/día → ~33,000 PAM auth, ~33,000 sudo escalations
- Newark CPU constantemente en cycle de spawn ssh+sudo+command+exit
- auth.log crece varios MB/día solo por nosotros
- NO afecta el bot directamente (corre en otro proceso) pero ensucia logs y CPU

### Optimización propuesta (NO bloqueante, post-Lun 12)

Activar **SSH ControlMaster** en `/home/administrator/.ssh/config` Dallas:

```
Host newark
    HostName 64.130.34.38
    User ubuntu
    IdentityFile /home/administrator/.ssh/id_ed25519
    ControlMaster auto
    ControlPath ~/.ssh/cm-%r@%h:%p
    ControlPersist 10m
```

Resultado: 1 sola conexión TCP persistente, todos los SSH posteriores multiplexan canales sobre ella. **De 33,000 conn/día a 1**. Sin cambios en scripts.

¿Apruebas para post-LIVE Lun 12 13:00 UTC (después de validar primer trade)? **NO urgente**, solo limpieza.

---

## §4 — 3 firmas concretas pedidas

### Q1 — Floor SHADOW (urgente, bloqueante para burn-in)

¿(a) `=0.0`, (b) `=0.005`, o (c) revertir binary?
**Mi voto**: (a).

### Q2 — apt-daily-upgrade (urgente para evitar repetición)

¿Pausar timers hasta Mar 13, o usar needrestart override?
**Mi voto**: pausar timers (simple, reversible).

### Q3 — SSH ControlMaster (no urgente)

¿Aplicar post-LIVE Lun 12, o dejar para post-burn-in V5?
**Mi voto**: post-LIVE Lun 12 (limpia, sin riesgo durante windows críticas).

---

## §5 — Plan condicional según firma

**Si firmas (a) Q1 + pausar Q2 inmediatamente**:
```
1. Set LIQ_MIN_PROFIT_USD_SHADOW=0.0 en /home/ubuntu/liquidator_rs/.env
2. sudo systemctl restart liquidator_rs (15s downtime)
3. Verificar log "r144 Q1: ... effective_min_profit_usd=0.0"
4. Verificar would_send rebote a >40% en 5min
5. sudo systemctl disable --now apt-daily-upgrade.timer apt-daily.timer
6. NO aplicar Q3 hoy (post Lun 12)
```

**Si firmas (c) revertir**:
```
1. mv liquidator_rs.bak_pre_q1q4_20260507T062733Z liquidator_rs
2. systemctl restart liquidator_rs
3. Reaplicar Q1 limpiamente a las 17:46 UTC con floor SHADOW correcto firmado
```

**Capital**: $0 LIVE expuesto. Hot wallet $200 SHADOW intacto. Sin riesgo de pérdida hasta Lun 12.

---

**Spec firmadas**: r93 + r107-r144
**Próximo r-number**: r146 con tus firmas a Q1-Q3 + log post-aplicación
**Cronograma**: Burn-in T+24h end Jue 7 17:46 UTC sigue alcanzable si firmas (a) en próximas 4h
