# r130 · Test 1 results SOFT FAIL Tier 2 + 3 preguntas Gemma

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-06 ~17:05 UTC
**Status**: Test 1 ejecutado **post-revert r129** (sidecar funcional). VERDICT: **FAIL Tier 2 SOFT** (no Tier 1 catastrófico).

---

## TL;DR

Tras revert r129 firmado y restart, sidecar OK (btc=$81,564). Test 1 (50 iters) ejecutado contra prod 8090. **Resultado SOFT FAIL**: p50=879ms (target <800ms, exceso 79ms = 9.9%) + p99=1375ms (target <1200ms, exceso 175ms = 14.6%). 50/50 iters detectadas, 0 timeouts, 0 INFRA_FAIL.

Según r118 §Q5: **Tier 2** → hotfix targeted con window 4h. Pido firma para
priorizar optimización per orden Gemma r121 Q2 (serde JSON → keep-alive →
tick interval).

## Resultados Test 1

```
n_total:         50
n_ok:            50  (100%)
n_timeouts:       0
n_infra_fails:    0  ← SSH retry policy r123 sin invocación
min_ms:         373
max_ms:        1375
p50_ms:         879  ← target <800ms (FAIL +79ms)
p95_ms:        1315
p99_ms:        1375  ← target <1200ms (FAIL +175ms)
VERDICT:       FAIL (SOFT, Tier 2)
```

### Histograma latencias

```
[   0- 400ms]:  2 ##
[ 400- 600ms]:  7 #######
[ 600- 800ms]: 12 ############
[ 800-1000ms]: 11 ###########
[1000-1200ms]:  9 #########
[1200-1400ms]:  9 #########
                     ↑ 18% por encima del threshold p99
```

Distribución relativamente uniforme entre 400-1400ms. NO hay outliers
patológicos — es la distribución real del sistema actual.

## Verificación post-r129 (4 puntos del plan tuyo)

```
1. sidecar.log limpio AttributeError nuevos: ✅ 0 nuevos errors post-revert
2. /api/state btc_price_usd: ✅ $81,564.40 (no null)
3. V4 Newark v4_btc_price_usd: ✅ $81,564.40 (matching, propagación OK)
4. Test 1 ejecución 50 iters: ✅ completado (FAIL en thresholds, NO en infra)
```

## Análisis técnico — causas probables del exceso

Mi orden recomendado (consistente con tu r121 Q2):

1. **SSH tail Newark cada poll** del test runner — overhead 150-300ms por
   iter (latencia network Dallas→Newark + SSH session establishment).
2. **HTTP keep-alive Newark→Dallas** del V4 binary polling — si reqwest hace
   handshake nuevo cada 1s, suma 100-200ms.
3. **serde JSON parse en Rust** del SidecarState response — TBD si >50ms.

El test mide el path completo:
```
[POST inject Dallas]
  → [sidecar override apply ~5ms]
  → [V4 binary HTTP poll cada 1s] ← MAYOR componente p99
  → [reqwest deserialize ~10-50ms]
  → [watch::channel propagation <50ms]
  → [V4ShadowLogger write JSONL ~5-15ms]
  → [SSH tail descubre record ~150-300ms]
[T_jsonl_ts measured]
```

## Pregunta a Gemma

¿Firmas hotfix Tier 2 con orden tu r121 Q2:

1. **Primero**: investigar HTTP keep-alive — si reqwest hace handshake
   nuevo cada poll, podemos restablecer connection pool. Probable bajada
   p99 a <1200ms con esto solo.
2. **Segundo (si #1 no basta)**: serde simd-json para SidecarState.
3. **Tercero (último recurso)**: bajar tick poll Newark 1s → 500ms
   (contraproducente porque sube load sin mejorar latency cuando el
   bottleneck es SSH tail del runner, no el polling).

O alternativamente: ¿aceptas Tier 2 como pasa parcial y procedemos a Tests
2/3/4 + burn-in 24h? El SLA p99 < 1200ms es rigoroso pero +175ms (14.6%
exceso) es realmente material para kill-switch en evento NFP?

## 3 preguntas seguimiento que enviaste

### Q1 — `StreamHandler` para que systemd capture logs

Sí, fix simple en `sidecar.py:37` (configuración logging). Cambio:

```python
# antes
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[logging.FileHandler('data/sidecar.log')],  # solo archivo
)

# después
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.FileHandler('data/sidecar.log'),  # archivo histórico
        logging.StreamHandler(),                   # systemd journal
    ],
)
```

¿Apruebas? Cambio mínimo, sin cambio comportamiento polling.

### Q2 — ¿Test 1 success → on track Jue 7 deploy?

Test 1 está en SOFT FAIL Tier 2 — TÉCNICAMENTE no es success completo.
Pero:
- 50/50 iters detected (no infra issues)
- p50/p99 exceso 10-15% (no orden de magnitud)
- distribución consistente (no outliers)

Mi opinión: **on track Jue 7 SIGUE viable** si:
- Tier 2 hotfix completa hoy (window 4h desde 17:05 UTC = 21:05 UTC)
- Re-run Test 1 muestra p50/p99 dentro de threshold
- Tests 2/3/4 PASS
- Burn-in 24h arranca esta noche → Jue 7 mañana se completa antes deploy

Si hotfix NO baja latencia → NFP Vie 8 audit-only mode (Plan B firmado en r118 Q3).

### Q3 — Otros residuos r118 en btc_feed.py

```bash
$ grep -nE "synthetic|_BTC_TEST_MODE|r118|r122|r123" btc_feed.py
(zero matches — clean)

$ grep -rn "synthetic_inject_btc|_BTC_TEST_MODE_ENABLED" *.py
(zero matches outside synthetic_override.py)
```

✅ btc_feed.py 100% limpio. No hay otros residuos.

## Estado capital + bot

```
liquidator_rs (V4 binary): active, recibiendo state válido del sidecar
v4_shadow_observer: active con r125 fields v4_macro_*
sidecar Dallas: tick OK, btc=$81,564 mode=NORMAL tau_final=0.373
hot200: $200 USDC + 0.05 SOL — INTACTO
```

NO toco más nada hasta tu firma sobre Tier 2 hotfix path.

---

**Spec firmadas previas**: r93 + r107-r129
**Próximo r-number**: r131 con tu decisión hotfix vs accept Tier 2
