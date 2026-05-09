# 03_TIMELINE · Track-record VelocityQuant · 2026-05-09 07:25 UTC

Resumen cronológico de hitos relevantes y r-numbers firmados.
**Solo eventos con impacto operacional**. No incluye chats casuales ni
ediciones menores.

---

## 2026-04 (mes anterior)

- Creación inventario base · 3 actores formalizados (Marco · Gemma · Claude)
- V3.5 Liquidator Newark LIVE · estable
- bot2_prime / bot3_prime running · legacy HFT
- profitlab_quantum LIVE paper running 2 semanas
- QuantumBot PPO `policy stagnation` detectada (160 samples / 16 símbolos = 10/símbolo, never reaches `PPO_CHUNK_MIN_SAMPLES=128`)

---

## 2026-05-03

- `cyclic_shadow.jsonl` empieza generando datos V4-Alpha shadow
- Múltiples cycles USDC↔SOL↔USDC con `would_send=true`, profits ~$0.005-0.04
- Latency rango 19-1576ms · slot_lag 0-2

---

## 2026-05-05

- `macro_calendar.json` migration to MAD-based sigma (kappa-adjusted)
- Backups creados pre-migration

---

## 2026-05-07 · V4-Alpha SHADOW deploy

- Patches V4 aplicados a Newark via `v4_q1q4_patches/`
- `cyclic_dispatch.rs` (26.9 KB) instalado
- `shadow_logger.rs` updated
- Sidecar Polymarket τ activo desde Dallas
- StressPass framework definido (16 checks pre-CPI gate)

---

## 2026-05-08 · NFP gate FAIL · CRITICAL

- Vie 12:30 UTC: NFP USA release esperado
- FMP API returns HTTP 402 (pricing change 2025-08-31)
- Sidecar tenía `fmp.status=stale` ANTES del release · NO lo detecté
- Marco quote: "yo qudo mal con mi socio"
- Migration emergency FMP→FRED+BLS+forecasts.json en 75 min
- `r150-bis-RCA_*.md` post-mortem

---

## 2026-05-08 (continuación)

- `fmp_compat.py` drop-in implementation
- `forecasts.json` consensus values agregados manualmente
- BTC, FRED, BLS clients consolidados
- Disk pressure /sdb2 83% → offload via symlink (NO migration · per Gemma)
  - FLUX.1-schnell 54GB → /sda-disk
  - pip cache 12GB delete
  - journalctl vacuum 1.1GB
  - backups 2.7GB

---

## 2026-05-08 (tarde) · r150 chain inicia

- `r150-tris_followups_q23_q26.md` Gemma → Claude
- Validator 6-gate pipeline implementado (`forecasts_validator.py`)
- SHA-256 sign de forecasts.json (`sign_forecasts.py`)
- `forecasts.signed` generado (hash 96571929e5d3f9dd...)
- `INFORME_CODEX_v2.md` enviado vía codex_dropbox (precedente del bundle actual)
- Auth removida de dashboards públicos `inicio.velocityquant.io/poly/audit/`

---

## 2026-05-08 nightly · r150-pent · BUG-NFP-DIM detected

- Smoke test SFEngine standalone: NFP SF = 0.0002σ vs esperado ~0.24σ
- Causa: `forecasts.json` en miles vs `SIGMA_FRED` en absolutos
- 10^3 mismatch unidades
- Documentado en `r150-pent_*.md`
- Gemma firma "Opción C" (defer fix to 2026-05-15) en `r150-hex_*.md`
- Tests marcados `SKIP_BUG_NFP_DIM=True`

---

## 2026-05-09 04:00-04:18 UTC · r150-sept · P3.6 implementado (PARCIAL)

- MD declara `[SAFETY-DIM]` assert YoY [0,20] aplicado
- MD declara `forecasts_validator` integrado en `forecasts_loader`
- Restart sidecar smoke test
- ⚠️ **POST-MORTEM 9-may 05:30**: el assert NUNCA se aplicó realmente
  (backup pre_assert idéntico al "post-edit") · ver `02_KNOWN_ISSUES.md` §1
- `forecasts_loader` validator integration SÍ se aplicó

---

## 2026-05-09 04:18 UTC · r150-oct · BLS rate-limit Issue #1

- Post-restart fetch BLS devuelve `null` por daily threshold
- 25/día anonymous limit consumido
- Plan: registrar BLS API key (free, 5 min)
- Marco firma · registra key vía web BLS

---

## 2026-05-09 05:23 UTC · r150-novum · BLS API key activada

- BLS API key 33 char · `chmod 600 ~/.config/bls/api_key`
- Sidecar restart · `fmp.status: stale → ok`
- 3× HTTP 200 BLS calls post-restart
- StressPass: 12/16 checks verde · 4 pendientes Mar 12

---

## 2026-05-09 05:30 UTC · DETECCIÓN del [SAFETY-DIM] gap

- Antes de implementar P3.6.5, verifiqué `bls_client.py` actual
- `wc -c` y `diff` revelan: `bak_pre_assert` idéntico al actual
- El edit r150-sept nunca llegó al archivo
- Decisión: reaplicar AHORA junto con P3.6.5 + disclosure honesto

---

## 2026-05-09 05:33 UTC · r150-decim · P3.6.5 + P5.0 implementados

- Aplicado `[SAFETY-DIM]` assert (esta vez verificado con grep + py_compile)
- Aplicado SHA-256 cache TTL agresivo en `bls_client.py`
- Aplicado polling LOW(3600s)/HIGH(30s en T-30min) en `sidecar.py`
- Creado `log_rotator.py` + systemd timer `poly_log_rotator.timer`
- 5/5 smoke tests offline PASS
- Disclosure honesto §1 sobre el bug histórico

---

## 2026-05-09 05:40 UTC · Restart aplicado · soak iniciado

- PIDs old 1426330/1426331 → new 1430862/1430863
- Downtime ~7s
- KPIs verde: mode=NORMAL, fmp.errors=0, RSS estable
- BLS 3× HTTP 200 post-restart
- **Soak count T+12h iniciado** · próximo trigger P3.7 = 17:40 UTC HOY

---

## 2026-05-09 06:00-07:00 UTC · Cierre Q&A Gemma

- 4 rondas de follow-ups técnicos con Gemma 4 31B
- `r150-undecim-bis` · 4 respuestas (criterios soak, P3.7 spec, Tokyo POC, rollback)
- `r150-undecim-tris` · 5 respuestas (caso A vs B, histeresis, Docker, BUG-NFP-DIM mitigation, postpone Tokyo)
- `r150-undecim-quad` · 4 respuestas finales + cierre Q&A por Claude
- Gemma firma "ARCHITECTURE LOCKED" → "MONITORING MODE"
- Próxima comunicación: ping 11:40 UTC con KPIs r150-duodecim-prelim

---

## 2026-05-09 07:00-07:25 UTC · Codex audit bundle generation (en curso)

- Plan aprobado por Marco
- Bundle siendo construido en `/home/administrator/codex_audit_2026-05-09/`
- Acceso al código: rsync sanitizado (sin keypairs/api_keys)
- Áreas de foco: Seguridad · Honestidad claims · Code rot · Viabilidad LIVE Mar 12

---

## Próximos hitos (planificados)

| Fecha UTC | Evento | Status |
|---|---|---|
| 2026-05-09 11:40 | Ping T+6h soak · 12 KPIs PASS/FAIL | PENDING |
| 2026-05-09 17:40 | Fin soak T+12h · veredicto GO/STOP P3.7 | PENDING |
| 2026-05-09 17:40+ | (condicional) P3.7 SFEngine integration | PENDING |
| 2026-05-10 evening | Tokyo POC bring-up (postpone validado por Gemma) | PENDING |
| 2026-05-11 evening | Pre-CPI final verification | PENDING |
| 2026-05-12 12:00 | Pre-flight check sidecar HIGH_FREQUENCY | PENDING |
| 2026-05-12 12:30 | CPI USA release · 16 checks StressPass | CRITICAL |
| 2026-05-12 13:30 | Si StressPass=True → microcapital LIVE $5-10 | TARGET |
| 2026-05-15 | Fix BUG-NFP-DIM (post-CPI) | DEFERRED |

---

## Reflexiones honestas para Codex

1. **El proyecto avanza rápido**. ~3 meses de construcción intensa.
   El ritmo puede haber introducido bugs que la velocidad enmascaró.

2. **El NFP fail Vie 8-may** fue una alerta. Marco perdió credibilidad
   con socio externo. No se debe repetir en CPI.

3. **El [SAFETY-DIM] miss** muestra que MDs firmados ≠ código real.
   Codex: cross-check agresivo recomendado.

4. **Capital LIVE = $0** durante todo el desarrollo. Esto es bueno
   (cero pérdidas). Pero también significa cero validación empírica
   con dinero real.

5. **El target Mar 12 es agresivo** (78h de margen actual). Cualquier
   issue CRITICAL detectado por Codex puede mover el target a M+1
   semana sin perder mucho.

---

**Generador**: Claude Opus 4.7 · timeline construido desde memoria de
conversación + r-numbers + git logs implícitos.
