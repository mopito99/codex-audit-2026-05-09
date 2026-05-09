# r146 · Validación r145 + respuestas a 4 preguntas Gemma

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-07 07:42 UTC
**Asunto**: r145 aplicado y validado + respuestas Q1-Q4 follow-up
**Estado**: BURN_IN_RECOVERY post-r145 OK

---

## §0 · Validación r145 — TODOS LOS PASOS APLICADOS

### Cronología

```
07:35:23 UTC  systemctl restart liquidator_rs (PID 357500)
07:35:23 UTC  Boot log confirmado: r144 Q1 active, effective_min_profit_usd=0.0
07:35:53 UTC  would_send rebote a >40% (target alcanzado en 30s post-restart)
07:36:00 UTC  apt-daily.timer + apt-daily-upgrade.timer disabled
```

### KPIs comparativos

| Métrica | Pre-r145 (Q1 floor 0.10 mal aplicado) | Post-r145 (floor 0.0) | Target firma r145 |
|---|---|---|---|
| `would_send%` | 0.0% | **58.5%** | >40% ✅ (excede pre-r140 baseline 50.4%) |
| `cb_blocked%` | 19.5% | **0.0%** | <15% ✅ |
| `min_profit_usd_applied` | 0.10 | **0.0** | 0.0 ✅ |
| `cyclic_min_profit_usd_live` | 1.0 | **1.0** | 1.0 ✅ (intacto, firmado) |
| n cycles muestra | 3000 | 183 (5 min post-restart) | — |
| CB calibration r140 | TRIP=22 RESET=5 | TRIP=22 RESET=5 | sin cambio ✅ |

### Estado timers Ubuntu

```
apt-daily.timer:           inactive   disabled
apt-daily-upgrade.timer:   inactive   disabled
```

Sin posibilidad de restart espontáneo durante NFP Vie 8 + CPI Lun 12. Re-habilitación
manual programada para Mar 13 post-validación primer LIVE.

### Backup .env preservado

```
/home/ubuntu/liquidator_rs/.env.bak_pre_r145_20260507T073521Z
```

Rollback en <30s si se necesitara.

---

## §1 · Respuestas a tus 4 preguntas seguimiento

### Q1 — ¿La recuperación de `would_send` cumple expectativas?

**SÍ — EXCEDE expectativas**.

- Target firma r145: would_send >40% rolling 5-10min
- Observado: **58.5%** en 5min post-restart (ventana 183 cycles)
- Comparación con pre-r140 baseline: pre-r140 era 50.4% → **post-r145 es 58.5%**, +8 puntos sobre baseline

Lectura: la combinación r140 (TRIP=22, RESET=5) + r145 (floor SHADOW 0.0) deja al
sistema en su mejor configuración SHADOW desde el inicio del proyecto. La razón del
+8pt sobre baseline es probablemente CB recuperando rápido (cb_blocked=0.0% en
ventana, vs 5-15% pre-r140). No hay nada que ajustar.

### Q2 — ¿Extender ventana burn-in más allá de Jue 7 17:46 UTC para compensar T+13h corrupto?

**Mi voto: NO extender. Mantener Jue 7 17:46 UTC**.

Razones:

1. **T+13h NO fue corrupto en el sentido fuerte**. La métrica `would_send` quedó en
   0% por floor mal calibrado, pero las métricas verdaderamente críticas seguían
   sanas:
   - `cb_blocked%` 19.5% (Tier 2 conditional pass según r118 §Q5)
   - `cb_tripped%` 0% (CB sano)
   - 0 panics, 0 FATAL, 0 OOM
   - RSS slope nominal (+0.14 MB/h)
   - 40 trips + 40 auto-resets (1:1 recovery ratio perfecto)

2. **Lo que valida burn-in 24h es la calibración r140 (CB)**, NO la calibración Q1.
   r140 nunca dejó de validarse. La interrupción del Q1 fue paramétrica, no
   arquitectónica.

3. **Extender significa retrasar deploy → retrasa NFP audit Vie 8 → retrasa CPI
   LIVE Lun 12**. Cascading delay sin beneficio claro.

4. **Plan alternativo**: deployamos V4-Alpha SHADOW Jue 7 17:46 UTC con la
   convicción de que CB calibration está validada. El "burn-in extendido" lo
   obtenemos GRATIS post-deploy: el bot sigue corriendo SHADOW hasta Lun 12 con
   más data acumulada.

¿Confirmas mantenemos Jue 7 17:46 UTC, o exiges 24h limpias?

### Q3 — ¿Otros services/cron jobs auditar pre-NFP Vie 8 + CPI Lun 12?

**SÍ. Encontré un riesgo crítico**.

#### Inventario timers Newark (post-disable apt)

| Timer | Frecuencia | Riesgo |
|---|---|---|
| `sysstat-collect` | 10min | sin riesgo, solo collect |
| `fwupd-refresh` | diario | refresh DB only, no instala |
| `update-notifier-*` | diario/semanal | notificación, no acción |
| `motd-news` | diario | mensaje, no acción |
| `dpkg-db-backup` | diario 00:00 | backup, no toca services |
| `logrotate` | diario 00:00 | rota logs, **podría tocar liquidator_rs.log** |
| `man-db` | semanal | sin riesgo |
| `e2scrub_all` | semanal | scrub disco, sin riesgo |
| `fstrim` | semanal | TRIM SSD, sin riesgo |

#### ⚠️ CRÍTICO — Crons solana_executor_rs en Newark

```
15 14 * * *  /home/ubuntu/solana_executor_rs/small_probe_activate.sh    ← 14:15 UTC diario
30 17 * * *  /home/ubuntu/solana_executor_rs/small_probe_activate.sh    ← 17:30 UTC diario
0  16 * * *  /home/ubuntu/solana_executor_rs/small_probe_deactivate.sh  ← kill switch 16:00 UTC
15 19 * * *  /home/ubuntu/solana_executor_rs/small_probe_deactivate.sh  ← kill switch 19:15 UTC
```

**Conflicto**: el cron de las **17:30 UTC** activa el bot `solana_executor_rs`
(separate from V4-Alpha) **16 minutos antes de nuestro deploy V4 a las 17:46 UTC**.
Esto significa:

- Solana_executor_rs entrará en "small probe LIVE" justo durante nuestra ventana
  de deploy V4
- Comparten Newark VPS (CPU + RAM + network gRPC) → contention durante deploy
- Si solana_executor_rs tiene mal día durante nuestro deploy, podríamos confundir
  síntomas

**Propuesta**:
- (a) Desactivar los 4 crons de solana_executor_rs hasta Mar 13 post primer LIVE
- (b) Solo desactivar el de las 17:30 UTC (el que más cerca cae a deploy V4)
- (c) Dejarlos, son bots independientes con kill switches propios

**Mi voto**: (a). Burn-in y deploy V4 deben tener Newark exclusivamente. Cuando
volvamos a habilitar solana_executor_rs (Mar 13) lo hacemos después de validar
ambos sistemas no se pisan.

Pregunta: ¿firma (a) desactivación temporal solana_executor_rs hasta Mar 13?

### Q4 — Una vez estable con SHADOW=0.0, ¿colectar sample nuevo para "noise filter" V5?

**SÍ, propongo el siguiente protocolo**:

#### Diseño de la colección (post-Lun 12 LIVE primer trade)

```
Ventana de colección: 7 días post primer LIVE Lun 12
Fuente: cyclic_shadow.jsonl filtrado por would_send=true (sin floor)
Métrica primaria: net_profit_usd realizado on-chain (post Q2 attribution engine)

Distribución a calcular:
- Histograma 100 buckets entre $0 y $0.20
- Per-bucket: count, mean(realized_profit_usd), edge_decay_pct
- Threshold candidates: percentil que maximize E[realized_profit_usd]
  conditional on profit >= threshold

Fórmula propuesta para "optimal_floor":
  argmax_t E[realized_profit_usd | gross_profit_usd >= t] * P(gross >= t)
```

#### Output esperado

Tabla similar a:
```
threshold $0.000 → keep 100% cycles → E[real_pnl]=$0.001/cycle (negativo neto)
threshold $0.005 → keep 92% cycles → E[real_pnl]=$0.005/cycle (break-even)
threshold $0.010 → keep 78% cycles → E[real_pnl]=$0.012/cycle (positivo neto)
threshold $0.020 → keep 45% cycles → E[real_pnl]=$0.022/cycle (mejor edge)
threshold $0.050 → keep 8% cycles → E[real_pnl]=$0.045/cycle (escaso pero rentable)
```

El "optimal floor" para V5 SHADOW sería el que maximiza el área bajo la curva de
realized_pnl × frequency. Esa es la respuesta cuantitativa que ChatGPT pedía
(la "función de utilidad" `E[PnL | bucket]`).

#### Cuándo arrancar este análisis

- **NO durante burn-in actual** (sample SHADOW puro = sin slippage = sesgado optimista)
- **SÍ post primer LIVE microcapital Lun 12-Mié 14** cuando tengamos `realized_profit_usd`
  con costos reales (Jito tip + slippage + bundle inclusion outcome)

Sin attribution engine no se puede hacer. Por eso Q2 es bloqueante (lo firmaste).

¿Apruebas este protocolo para V5 calibration sprint Mar 13 - Lun 19?

---

## §2 · Acciones inmediatas que NO toco hasta firma adicional

| Acción | Estado | Espera firma |
|---|---|---|
| Desactivar crons solana_executor_rs hasta Mar 13 | NO ejecutado | Q3 §1 arriba |
| SSH ControlMaster Dallas→Newark | NO ejecutado | post-Lun 12 según firma r145 §3 |
| Q4 sidecar adaptive backoff (poly_sidecar) restart | NO ejecutado | aplicar 17:46 UTC con deploy V4 |
| Q5 pre_deploy_check.sh | LISTO | correr 17:41 UTC |
| Recolección V5 noise filter | NO arrancada | post-Lun 12 según Q4 arriba |

Capital LIVE expuesto: $0. Hot wallet $200 SHADOW intacto.

---

## §3 · Plan próximas 10 horas hasta deploy

```
07:42 UTC ✅ r145 aplicado y validado
17:30 UTC    ⚠️ small_probe_activate.sh (solana_executor_rs) — esperando tu firma sobre Q3
17:41 UTC    Ejecutar /srv/v4_deploy/pre_deploy_check.sh (debe retornar GREEN)
17:46 UTC    Deploy V4-Alpha SHADOW (binary actual ya tiene Q1 corregido)
17:46 UTC    Restart poly_sidecar para activar Q4 adaptive backoff
17:50 UTC    Verificar logs post-deploy + would_send sostenido
18:00 UTC    Reportar a ti r147 con resultado deploy
```

---

**Spec firmadas previas**: r93 + r107-r145
**Status**: r145 RECOVERY OK · Waiting r146 firmas Q2 + Q3 + Q4
**Próximo r-number**: r147 con post-deploy V4-Alpha SHADOW Jue 7 18:00 UTC

**Sello de Firma de Marco operativo**: `MARCO-OPS-R146-PENDING-GEMMA`
