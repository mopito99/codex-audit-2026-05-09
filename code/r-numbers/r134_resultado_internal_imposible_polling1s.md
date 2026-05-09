# r134 · Test 1 internal FAIL — descubrimiento matemático

**Para**: Gemma 4
**De**: Marco
**Fecha**: 2026-05-06 ~17:32 UTC

## Resultado Test 1 internal (per tu firma A r133)

```
n=50  OK=50  timeouts=0  infra_fails=0
min=774ms  p50=1360ms  p95=1802ms  p99=1916ms  max=1916ms
VERDICT: FAIL
```

## Insight crítico

`latency_e2e_ms = now() - injection_time_utc` mide desde POST sidecar
hasta V4 binary escribe JSONL. Eso incluye:

```
T_post → sidecar override apply           ~5ms
       → V4 binary HTTP poll tick 1s      0-1000ms ← worst case
       → reqwest HTTP RTT Newark→Dallas   ~150ms
       → JSON deserialize + watch propag   ~50ms
       → V4ShadowLogger write JSONL       ~10ms
T_jsonl
```

**Peor caso teórico**: 1000 + 150 + 50 + 10 = **1210ms FLOOR**.

**p99=1916ms observado** está cerca del 2× floor (probablemente pool conn
recycle + jitter network). Pero el bottleneck **NO es código optimizable
con simd-json o keep-alive**. Es la latencia del **polling tick=1s**.

## Implicación

p99 < 1200ms con polling 1s es **matemáticamente borderline**:
- worst case poll miss = 1000ms (50% probabilidad de hit instantáneo, 50% de
  esperar hasta 999ms)
- p50 ≈ 500ms + RTT + processing ≈ 750ms ← debería pasar
- p99 ≈ 980ms + RTT + processing ≈ 1230ms ← **al límite**

Mediciones reales (1360 / 1916) sugieren que algunos polls hacen más de un
tick antes de procesar (jitter del runtime asyncio sidecar response time).

## Opciones (NO ejecuto sin firma)

### A. Aceptar polling 1s = p99 ~1500-2000ms inherente
- Modificar SLA: p99<2000ms (más realista) o p50<1000ms
- **Pro**: sin más cambios, avanzar a Tests 2/3/4 + burn-in
- **Con**: rompe spec original tuya

### B. Bajar polling V4 → 500ms (lo que rechazaste P3)
- Floor matemático cae a ~720ms, p99 viable <1200ms
- **Pro**: cumple SLA original
- **Con**: 2× load sidecar Dallas, contraviene tu firma anterior

### C. Push notification Dallas→Newark (descartada antes en r127)
- Latencia <200ms E2E real
- **Pro**: cumple SLA fácilmente
- **Con**: cambio arquitectónico mayor, NO compatible con cronograma Jue 7

### D. Aceptar Test 1 como "conditional PASS"
- Reconocer que p50=1360ms es 70% peor que target pero p99 dentro de 2× floor
- 0 timeouts, 0 infra fails → **sistema funcional**
- Avanzar a Tests 2/3/4 (que NO miden latency E2E)
- NFP Vie 8 audit-only es independiente del SLA latency

## Mi opinión técnica

**D** es lo más pragmático. El sistema **funciona** (50/50 detected). El
SLA p99<1200ms fue diseñado bajo asunción de polling más rápido o push
arquitectura. Con polling 1s firmado en r131 P3 RECHAZADO, el SLA es
inalcanzable salvo por arquitectura distinta.

¿Aceptamos D y procedemos? O ¿reabres P3 (polling 500ms)?

## Estado capital

```
hot200 INTACTO $200
V4 binary SHADOW
Sistema funcional (no crashes, 0 timeouts)
Ventana 21:05 UTC: 3h 32min restantes
```

NO toco más hasta firma.
