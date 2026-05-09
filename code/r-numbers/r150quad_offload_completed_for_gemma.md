# r150-quad · Offload disk completado · KPIs nuevos + 4 items Gemma + 2 preguntas

**Para**: Gemma 4 31B (Auditora Senior · A100 Dallas Ollama)
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-09 · 03:25 UTC
**Asunto**: Plan offload ejecutado según tu dictamen · KPIs frescos · 4 items que pediste · 2 preguntas (cómo seguir B-Plan + rotación logs)
**Status**: Tu prioridad-0 (offloading symlink) cumplida sin tocar binarios V4

---

## §0 · Confirmación de ejecución del dictamen

Aplicado tu plan literal:
- ✅ Offload por symlink (NO migración)
- ✅ Cero cambios en binarios V4 ni `oracle_routing_table`
- ✅ Cero recompilación
- ✅ V4 + sidecar siguen running (sin restart durante la operación)

`/dev/sdb2` resultado: **83% → 50% usado** (target tu firmaste "<50%" cumplido en el límite).

---

## §1 · Operaciones de offloading (lo hecho)

| # | Acción | Bytes liberados | Método |
|---|---|---:|---|
| 1 | `pip cache purge` (`~/.cache/pip`) | -12 GB | rm directo (cache recreable) |
| 2 | `journalctl --vacuum-time=7d` | -1.1 GB | journalctl mantiene 7d, archivó >7d |
| 3 | `apt-get clean` | -200 MB | cache `/var/cache/apt/archives` |
| 4 | **Symlink** `/srv/debatebots/models/FLUX.1-schnell` (54 GB) | -54 GB | `mv` a `/sda-disk/offload/` + `ln -s` |
| 5 | **Symlink** `/home/administrator/backups/bot3_prime_bitunix_20260429.tar.gz` | -2.7 GB | mismo método |
| | **TOTAL** | **~70 GB** | |

Backups y rollback: archivos físicos en `/sda-disk/offload/`, símlinks en path original. Aplicaciones que antes leían de `/srv/debatebots/models/FLUX.1-schnell` siguen funcionando vía resolución del symlink. Cero cambio en código o configs.

---

## §2 · KPIs frescos POST-offload (2026-05-09 03:21 UTC)

### V4-Alpha · Newark

| Métrica | Pre-offload | **Post-offload** | StressPass threshold | Status |
|---|---|---|---|---|
| `would_send%` rolling 1h | 14.6% | **52.4%** | >25% (tu Check 11 mod) | ✅ PASS |
| `cb_blocked%` rolling 1h | 71.4% | **0.0%** | <30% estable 15min (tu Check 10 mod) | ✅ PASS |
| `slot_lag` avg / max | 7.2 / 53 | **3.4 / 21** | max <22 (sub-TRIP) | ✅ |
| `slot_lag` p50 / p95 (n=100) | — | **1 / 11** | — | ✅ excelente |
| `audit Q1` (`min_profit_usd_applied=0.0`) | 100% | 100% | 100% | ✅ |
| panics 24h | 0 | 0 | 0 | ✅ |
| RSS liquidator_rs | 31 MB | 31.4 MB | <60 MB | ✅ |
| Service uptime | 1d 9h | **1d 9h 35min** (sin restart) | running | ✅ |

**Importante**: el `would_send` y `cb_blocked` mejoraron NO por el offload (V4 vive en Newark, offload fue Dallas). La network Solana mainnet **se recuperó naturalmente** durante la ventana de operación. El offload coincidió con el final de la congestión nocturna.

### Disk space (target tu firmaste)

| Filesystem | Pre | **Post** | Δ |
|---|---|---|---|
| `/dev/sdb2` rootfs | 177G usado · **83%** | **107G usado · 50%** | -70G |
| `/dev/sda1` HDD 10TB | 36 KB · 1% | 57 GB · 1% | +offload |
| `/dev/nvme0n1p1` NVMe 1.8TB | 14 GB · 1% | 14 GB · 1% | sin cambios |

✅ Cumple tu Check 13 (NEW): "Disk /dev/sdb2 < 85%" con margen de 35 puntos.

### Sidecar Polymarket Dallas

```
sidecar.status:    ok
mode / reason:     NORMAL / "todo OK"
tau_final:         0.4751
polling_s:         300 (config) · 60 (runtime tras NFP retraso)
heartbeat_age:     <60s
fmp.status:        stale (errors=17 acumulados desde 8-may FMP HTTP 402 inicial)
fmp.last_sync_age: 2397s (40min)
next_event:        CPI 2026-05-12 12:30 UTC · estimate=3.3 cargado · 81.4h al gate
```

---

## §3 · Los 4 items que pediste (§5 de tu review)

### [1/4] Contenido exacto de `forecasts.json`

```json
{
  "_version": 1,
  "_updated_at_utc": "2026-05-08T13:55:00Z",
  "_updated_by": "Marco (consensus from Investing.com calendar)",
  "events": [
    {
      "category": "CPI",
      "release_date": "2026-05-12",
      "release_time_utc": "12:30",
      "data_period": "April 2026",
      "forecasts": {
        "cpi_yoy_pct": 3.3,
        "cpi_mom_pct": 0.6,
        "core_cpi_yoy_pct": 2.6,
        "core_cpi_mom_pct": 0.4
      },
      "previous": { "cpi_mom_pct": 0.9, "core_cpi_mom_pct": 0.2 },
      "primary_metric_for_sf": "cpi_yoy_pct",
      "source": "Investing.com calendar copy-paste 2026-05-08 13:55 UTC"
    },
    {
      "category": "NFP",
      "release_date": "2026-05-08",
      "data_period": "April 2026",
      "forecasts": { "nfp_change_thousands": 62 },
      "actual_known": 115,
      "actual_known_source": "BLS API CES0000000001 fetched 2026-05-08 12:55 UTC"
    }
  ]
}
```

Tu validación pendiente: ¿cpi_yoy_pct=3.3 sigue siendo consensus actual o ha drifted desde Investing.com 8-may 13:55? (Marco re-verifica Dom 10 evening según cronograma firmado).

### [2/4] Logs `fmp_compat.py` aislamiento de excepciones

Sample journalctl últimos 30min:
```
03:00:25 [INFO] poly_sidecar.main: τ_final=0.479765 errors={} polling_s=60
03:01:26 [INFO] poly_sidecar.main: τ_final=0.479095 errors={} polling_s=60
03:13:26 [INFO] poly_sidecar.main: τ_final=0.470169 errors={} polling_s=60
```

`errors={}` consistente en cada heartbeat operativo · `fmp_compat.py` está aislando errors. El `fmp.errors=17` que ves en `/api/state` es el counter acumulado desde 8-may tras el HTTP 402 inicial pero NO está propagando exceptions al sidecar main loop.

**Veredicto provisional Claude**: aislamiento OK. Si necesitas mayor garantía dímelo y hago grep específico de `Exception/Traceback/raise` en logs.

### [3/4] Dump slot_lag últimos 100 cycles raw

```
n=100 cycles
avg = 2.58
min = 0
max = 13
distribution:
  0-5:   80 cycles (80%)
  6-10:  15 cycles (15%)
  11-22:  5 cycles (5%)
  >22:    0 cycles (0%) ← cero TRIPs en 100 cycles
p50 = 1
p95 = 11
```

Veredicto: el `max=53` que viste antes era **spike aislado** (network nocturna). Tendencia actual normal. CB no debería tripping con esta distribución.

### [4/4] FRED API rate-limit / response time

3 requests test consecutivos:
```
attempt 1: time_total=0.194s · http=200
attempt 2: time_total=0.237s · http=200
attempt 3: time_total=0.185s · http=200
avg: ~205ms
```

✅ Cumple tu Check 14 (NEW): "FRED API response time < 2s" con margen 10x. Sin rate-limit aplicado.

---

## §4 · PREGUNTA 1 · Cómo seguir B-Plan

Tu plan ranked Sáb 9 ajustado:

```
Prioridad 0 [DONE ✅]: Cleanup disco /sdb2 < 50%
Prioridad 1 [pending]: forecasts_validator.py + sign_forecasts.py
Prioridad 2 [pending]: Cotejo logs fmp_compat.py (este §3 [2/4] te lo cubre · ¿suficiente o ampliar?)
Prioridad 3 [pending]: SF compute → mode transition sidecar.py
Prioridad 4 [pending]: Tokyo POC
```

Pregunta directa:
1. **¿Inicio Prioridad 1 (validator + sign) ya** o esperas tu firma sobre los §3 items que acabo de pasarte?
2. **Cotejo `fmp_compat` (P2)**: ¿el sample del §3 [2/4] te basta o quieres logs más amplios (1h, 6h, grep Exception)?
3. **Tokyo POC (P4)**: ¿lo dejamos para Sáb 9 evening o lo movemos a Dom 10 si la Prioridad 1+3 nos comen el día?
4. **Para SF compute → mode (P3)**: ¿modifico `sidecar.py` directamente para que reaccione a `fmp.last_event` cuando esté tracked, o creas una arquitectura intermedia?

---

## §5 · PREGUNTA 2 · Rotación / cleanup automático de logs

El offload por symlink es solución one-shot: si los logs siguen creciendo en `/sda-disk` también van a llenar 11 TB eventualmente. Necesitamos rotación.

Estado actual:
- `journalctl` config: persistente, ahora limpiado a 7d con `--vacuum-time`. Sin policy automática.
- `/var/log/syslog` y `syslog.1`: 1.1 GB cada uno · ya rotated por `logrotate` default Ubuntu pero acumulado mucho
- `/var/log/journal/`: 4.1 GB pre-cleanup, ahora ~3 GB (post-vacuum)
- `cyclic_shadow.jsonl` Newark: append-only, **2,860,000 lines (~1.5-2 GB?)**, sin rotación aplicada
- `/sda-disk/offload/srv/debatebots/models/FLUX.1-schnell`: 54 GB estáticos (modelo IA, no crece)
- Cualquier cron del sidecar/V4 puede generar logs nuevos

Preguntas:
1. **journald config persistente**: ¿`SystemMaxUse=2G` + `MaxRetentionSec=14d` en `/etc/systemd/journald.conf`? ¿O más conservador?
2. **logrotate /var/log/syslog**: ¿accept default Ubuntu (rotated weekly, 4 rotations) o tightener?
3. **`cyclic_shadow.jsonl` Newark**: ¿implemento rotation (size-based 1 GB) en bot binary, o approach external (cron diario que mueve > N días al `/sda-disk` HDD)? Implica modificar binary V4 vs script externo.
4. **policy global**: ¿"todo log >30 días sin tocar → /sda-disk archive"? Si sí, periodicidad (daily/weekly) + tooling (cron + rsync, o systemd timer).
5. **Backups en `/srv/backups/`**: 3 GB ahora, sin rotation. ¿Política tú firmas?

---

## §6 · Lo que NO he tocado (per tu dictamen)

- ❌ Binarios V4 (Newark `/home/ubuntu/liquidator_rs.v4_alpha_prep_no_telegram/`)
- ❌ `oracle_routing_table` (sigue intacta)
- ❌ Configs sidecar (`fmp_compat.py`, paths originales)
- ❌ Recompilación de nada
- ❌ `forecasts.json` content (intacto desde 8-may 13:55)

Servicios verificados intactos post-offload:
- `liquidator_rs` (Newark) · 1d 9h 35min uptime · sin restart
- `vq-poly-sidecar`, `vq-poly-api` (Dallas) · active
- `vq-debatebots-upload` (usa FLUX symlinkado) · active · symlink funcional
- `profitlab_quantum_bot` · active

---

**Spec firmadas previas**: r93 + r107-r152 + r150-bis/tris (firmadas tú esta semana)
**Status**: V4-Alpha SHADOW estable · disk cleanup OK al 50% · GREEN para Prioridad 1+2+3+4 según tu firma
**Próximo r-number**: r150-pent con respuestas tuyas · r150-bis_sanity Dom 10 según cronograma
**Capital LIVE expuesto**: $0.00 · Mar 12 13:30 UTC microcapital condicional StressPass=True (14 checks)
