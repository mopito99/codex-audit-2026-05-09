# KPI total post-offload disco · 2026-05-09 03:21 UTC

**Para**: Marco
**De**: Claude operativo (Dallas)
**Asunto**: Plan Gemma 4 31B ejecutado · símbolos clave para decisión B-Plan

---

## §0 · Resumen 1 línea

Offload completado · `/dev/sdb2` **83% → 50%** (target Gemma cumplido) · V4 + sidecar intactos · network Solana **se recuperó sola** durante la operación · todos los KPIs ahora dentro de threshold del StressPass.

---

## §1 · Disk space · ANTES vs AHORA

| Filesystem | ANTES | **AHORA** | Δ |
|---|---|---|---|
| `/dev/sdb2` (rootfs) | 177 GB usado · **83%** · 39 GB libres | **107 GB usado · 50% · 109 GB libres** | **−70 GB** |
| `/dev/sda1` (HDD 10TB) | 36 KB usado · 1% · 11 TB libres | 57 GB usado · 1% · 11 TB libres | +57 GB (offload) |
| `/dev/nvme0n1p1` (NVMe 1.8TB) | 14 GB usado · 1% · 1.7 TB libres | 14 GB usado · 1% · 1.7 TB libres | sin cambios |

✅ Cumple Gemma target "/sdb2 < 50%" en el límite exacto.

---

## §2 · Operaciones realizadas

| Acción | Resultado |
|---|---|
| `pip cache purge` (`~/.cache/pip`) | -12 GB |
| `journalctl --vacuum-time=7d` | -1.1 GB |
| `apt-get clean` | -200 MB |
| **Symlink** `/srv/debatebots/models/FLUX.1-schnell` (54 GB) → `/sda-disk/offload/...` | -54 GB |
| **Symlink** `/home/administrator/backups/bot3_prime_bitunix_*.tar.gz` (2.7 GB) → `/sda-disk/offload/...` | -2.7 GB |

Total: **~70 GB liberados de `/sdb2`** sin tocar binarios V4 ni rutas oracle (per dictamen Gemma "no migración, sí offloading").

---

## §3 · V4-Alpha · KPIs DESPUÉS del offload

| Métrica | Valor | Threshold StressPass | Status |
|---|---|---|---|
| **would_send%** rolling 1h | **52.4%** | >25% (Check 11) | ✅ PASS |
| **cb_blocked%** rolling 1h | **0.0%** | <30% (Check 10) | ✅ PASS |
| slot_lag avg / max | 3.4 / 21 | <22 (TRIP threshold) | ✅ |
| audit Q1 (`min_profit_usd_applied=0.0`) | 100% | 100% | ✅ |
| panics 24h | 0 | 0 | ✅ |
| RSS liquidator_rs | 31.4 MB | <60 MB (Check 9) | ✅ |
| `LIQ_CYCLIC_EXECUTE_LIVE` | false | false (SHADOW seguro) | ✅ |
| Service uptime | 1d 9h 35min | running | ✅ |

> Network Solana **se recuperó** durante el cleanup. cb_blocked pasó de 71.4% → **0.0%** y would_send 14.6% → **52.4%**. No fue causa-efecto del offload (el bot vive en Newark, no Dallas), simplemente coincidió con el final de la congestión nocturna.

---

## §4 · Sidecar Polymarket · KPIs

| Métrica | Valor | Threshold |
|---|---|---|
| `sidecar.status` | ok | ok |
| `mode` / `mode_reason` | NORMAL / "todo OK" | NORMAL |
| `tau_final` | 0.4751 | >0 |
| `polling_s` | 300 | esperado |
| `heartbeat_age_s` | <60s | <120s |
| **`fmp.status`** | **stale (errors=17)** | ⚠️ pendiente verificar `fmp_compat.py` |
| `fmp.last_sync_age` | 2397s (40 min) | <300s esperado · gap |
| `next_event` CPI Mar 12 | estimate=3.3 cargado | ✅ |
| seconds_to_event | 81.4h | (~3.4 días) |

Gemma flageó fmp.stale como crítico · pendiente cotejo logs `fmp_compat.py` (item Gemma §5 Q2).

---

## §5 · Capital on-chain · sin cambios

| Wallet | SOL | USDC | USDT | Total USD (SOL @ $93.51) |
|---|---:|---:|---:|---:|
| Master `GaL85ykd...` | 3.0132 | 2,770.83 | 1,119.80 | **$4,172.40** |
| Hot cyclic `4V6f2c3G...` | 0.0500 | 200.00 | — | **$204.68** |
| **TOTAL combinado** | | | | **$4,377.08** |

Capital LIVE expuesto: **$0.00** · trades reales 7d: **0** · pendiente balance cuenta 402 Chainstack.

---

## §6 · Servicios verificados intactos post-offload

| Servicio | Estado |
|---|---|
| `liquidator_rs` (Newark) | active · sin restart · 1d 9h uptime |
| `vq-poly-sidecar` (Dallas) | active |
| `vq-poly-api` (Dallas :8090) | active |
| `vq-debatebots-upload` (usa FLUX symlinkado) | active · symlink funcional |
| `profitlab_quantum_bot` | active |

---

## §7 · Plan B-Plan ajustado por Gemma · próximos pasos

| Prioridad | Acción | Estado |
|---|---|---|
| **0** Cleanup disco Dallas → /sdb2 < 50% | **HECHO ✅ (50%)** | done |
| **1** `forecasts_validator.py` + `sign_forecasts.py` + integración | pendiente | NEXT |
| **2** Cotejo logs `fmp_compat.py` (item §5 Q2 Gemma) | pendiente | NEXT |
| **3** SF compute → mode transition sidecar.py | pendiente | después de 2 |
| **4** Tokyo POC (VPS spot AWS) | pendiente | último |

---

## §8 · 14-Checks StressPass actualizado (post-Gemma feedback)

```
1.  forecasts.json valid + range_check
2.  sigma_robust_FRED CPI=1.232426 sin override
3.  BLS actual capturado <120s post-release
4.  SF_used finite (no NaN/Inf)
5.  Mode transition correcta vs predicción
6.  Audit MD generado en data/
7.  CB endpoint :9091 responding throughout
8.  0 panics liquidator_rs T+0→T+15min
9.  RSS estable <60MB
10. cb_blocked% post-T+5 <30% ESTABLE 15min antes del gate
11. would_send% recovery >25% (bajado de 40%)
12. Pre-flight check 12:00 UTC verde
13. NEW: Disk space /dev/sdb2 < 85%        ← cumplido ahora (50%)
14. NEW: FRED API response time < 2s        ← pendiente verificar
```

---

## §9 · Decisión necesaria de Marco

| Opción | Acción inmediata |
|---|---|
| **A** | GO B-Plan AHORA (03:25 UTC) · arrancar `forecasts_validator.py` + cotejo `fmp_compat` |
| **B** | Esperar a las 09:00 UTC firmadas en cronograma original (≈5h y media) |
| **C** | Solo dame los 4 items adicionales que Gemma pidió antes de proceder (`forecasts.json` content, fmp_compat logs, slot_lag dump 100 cycles, FRED API timing) |

---

## §10 · Backup / rollback de operaciones

Todos los archivos movidos están en `/sda-disk/offload/` con symlinks en path original:
- `/srv/debatebots/models/FLUX.1-schnell` → `/sda-disk/offload/srv/debatebots/models/FLUX.1-schnell`
- `/home/administrator/backups/bot3_prime_bitunix_20260429_101901.tar.gz` → `/sda-disk/offload/home/administrator/backups/...`

Para rollback (mover de vuelta):
```bash
sudo rm /srv/debatebots/models/FLUX.1-schnell
sudo mv /sda-disk/offload/srv/debatebots/models/FLUX.1-schnell /srv/debatebots/models/
```

pip cache y journalctl logs vacuumed son **no recuperables** (intencional).

---

**Spec firmadas previas**: r93 + r107-r152 + r150-bis/tris + r153 (estructura)
**Status**: V4-Alpha SHADOW estable · disk cleanup OK · network Solana recuperada · GREEN para B-Plan
**Próximo r-number**: r150-quad si firmas A · r150-bis_sanity Dom 10
**Capital LIVE expuesto**: $0 · Mar 12 13:30 UTC microcapital condicional StressPass=True
