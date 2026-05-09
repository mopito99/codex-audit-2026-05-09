# r129 · Root cause sidecar stuck — bug de indentación en btc_feed.py

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-06 ~17:00 UTC
**Tipo**: Diagnóstico py-spy + revert request
**Severity**: Bloqueante Test 1 — capital intacto

---

## TL;DR (3 líneas)

`py-spy dump` revela que el sidecar **NO está stuck**, está en `select(timeout=299.222)` esperando próximo polling tick (5min normales). El primer tick **falló silenciosamente** con `AttributeError: 'BTCFeed' object has no attribute 'status'` causado por código mío en r118 §Q2 mal indentado que rompió la clase BTCFeed. Solicito firma para revertir mi código residual.

## Evidencia 1 — py-spy stack trace

```
Thread 732118 (idle): "MainThread"
    select (selectors.py:468)
        timeout: 299.222            ← deliberate sleep, NO stuck
    _run_once (asyncio/base_events.py:1949)
        timeout: 299.2210049063433
        when: 1221837.1313637113    ← scheduled wake-up
    run_forever
    run_until_complete
    run
    <module> (sidecar.py:595)
        asyncio.run(main_loop())
```

Tu hipótesis (synchronous block sin timeout) era correcta sintomáticamente
pero el bloqueo NO está en HTTP — está en el `asyncio.sleep(300)` del polling
loop tras un primer tick fallido.

## Evidencia 2 — log file (no journalctl)

```
/home/administrator/poly_sidecar/data/sidecar.log:
[16:54:49,430] [ERROR] poly_sidecar.main: cycle error:
'BTCFeed' object has no attribute 'status'
Traceback (most recent call last):
  File "/home/administrator/poly_sidecar/sidecar.py", line 549
    state = await run_once(client, btc_feed, fmp, investing, calendar, ...)
  File "/home/administrator/poly_sidecar/sidecar.py", line 496
    "btc_status": btc_feed.status,
                  ^^^^^^^^^^^^^^^
AttributeError: 'BTCFeed' object has no attribute 'status'
```

Por qué no apareció en `journalctl`: el sidecar usa `logging.basicConfig`
con FileHandler a `data/sidecar.log`, no stderr → systemd no captura.

## Evidencia 3 — Diagnóstico estructural btc_feed.py

```
Línea 446-466 (dentro de clase BTCFeed):
    async def get_price(self) -> tuple[float | None, float | None]:
        ...

Línea 469-505 (module-level — POR ERROR fuera de clase):
# r122/r123 firma Gemma — synthetic test override (LIQ_SIDECAR_TEST_MODE=1)
import os as _os
_BTC_TEST_MODE_ENABLED: bool = _os.environ.get("LIQ_SIDECAR_TEST_MODE") == "1"
...
def synthetic_inject_btc(price, duration_s):
    ...
def synthetic_status():
    ...

Línea 506-515 (debían estar EN BTCFeed, ahora module-level por el corte):
    @property                ← cuatro espacios indent pero parser
    def status(self) -> str: ya cerró la clase en 469
        ...
    @property
    def last_consensus(self):
        ...
```

El bloque que metí en r118 §Q2 (sin newline + sin re-indentar el resto)
**cortó la clase BTCFeed prematuramente**. Python parser cerró la clase en
línea 469 cuando vio `import os as _os` sin indent, dejando las properties
`status` y `last_consensus` huérfanas. NO da error de sintaxis (los `@property`
sin contexto se permiten module-level pero no se asocian a la clase).

## Causa específica

Mi edit r118 §Q2 (que después de tu sign-off r125 fue reemplazado por
`synthetic_override.py`) dejó **CÓDIGO MUERTO RESIDUAL** en `btc_feed.py`.
Olvidé revertirlo cuando implementé r125.

Este código residual:
- NO está firmado por ti (era r118 §Q2 que descartamos)
- Rompe la clase `BTCFeed` (status property no accesible)
- Causa AttributeError en cada polling tick → tick siempre falla → state
  vacío → next sleep 300s → repeat

## Solicitud de firma

**Pido autorización para REMOVER el bloque residual r118 §Q2**:

```python
# DELETE de líneas 469-505 inclusive (lo de r118 §Q2 no firmado):
# r122/r123 firma Gemma — synthetic test override
import os as _os
_BTC_TEST_MODE_ENABLED: bool = _os.environ.get("LIQ_SIDECAR_TEST_MODE") == "1"
_btc_test_override: dict = {"enabled": False, "price": None, "expires_at": 0}
def synthetic_inject_btc(price, duration_s) -> dict:
    ...
def synthetic_status() -> dict:
    ...
```

Y **REVERTIR** `get_price()` al original (sin la rama `_BTC_TEST_MODE_ENABLED`):

```python
async def get_price(self) -> tuple[float | None, float | None]:
    """Backward-compat API. Returns (consensus_price, last_update_ts).
    Used by sidecar.py polling loop.
    """
    result = await self.get_consensus()
    return result.consensus_price, result.last_update_ts
```

**Tras revert**:
- Clase BTCFeed recupera su forma original
- `status` property accesible
- Polling tick completa sin error
- `btc_price_usd` se popula en /api/state
- V4 binary Newark recibe data válida
- Test 1 ejecutable

**Aclaración**: el reemplazo r125 de este approach (`synthetic_override.py`)
NO toca btc_feed.py. La inyección synthetic se aplica EN `_state_payload()`
en health_api.py via `synthetic_override.maybe_apply()`. Por tanto remover
el código residual NO afecta la mecánica de Test 1.

## Riesgo de ejecutar revert

| Factor | Riesgo |
|---|---|
| Capital | 0 (sigue SHADOW, hot200 intacto) |
| Code firmado por ti | 0 (revert es de código mío no firmado) |
| Mecánica Test 1 | 0 (synthetic_override.py independiente) |
| Polling tick | recupera comportamiento original |
| Buffer downtime | ~10s (restart sidecar tras edit) |

## Plan post-firma

1. Edit btc_feed.py: remove bloque residual + revert get_price()
2. Restart vq-poly-sidecar.service
3. Esperar primer tick (~30s — el bug era en RUN, no en HTTP)
4. Verify `/api/state` devuelve `btc_price_usd` numérico
5. Verify V4 Newark JSONL muestra `v4_btc_price_usd > 0`
6. Run Test 1 (50 iters) → r130 con resultados

## NO te pido

- Cambios de design synthetic_override (r125 sigue firmado correcto)
- Reset de spec acumulada
- Decisión LIVE — sigue prohibido

## Pregunta

¿Firmas la remoción del bloque residual r118 §Q2 + revert get_price()
original? (mi recomendación: SÍ — es revert literal de código no firmado).

---

**Spec firmadas previas**: r93 + r107-r128
**Estado**: Bloqueado — esperando firma revert
**Próximo r-number**: r130 con Test 1 results post-revert
