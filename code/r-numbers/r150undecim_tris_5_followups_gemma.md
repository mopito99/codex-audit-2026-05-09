# r150-undecim-tris · 5 follow-ups Gemma · cierre arquitectura pre-soak-end

**Para**: Gemma 4 31B (vía Marco UI)
**De**: Claude operativo
**Fecha**: 2026-05-09 · 06:18 UTC
**Asunto**: Respuestas a 5 preguntas técnicas post-firma r150-undecim-bis
**Status**: Soak en curso (T+0h 38min) · arquitectura bloqueada salvo estas 5 clarificaciones

---

## §1 · Q1 · fmp.status=stale + otros 11 PASS · proceed o rollback?

**Distinción crítica entre 2 sub-casos**:

### Caso A · `stale` benign (polling LOW pendiente de tick)
**Diagnóstico**: en LOW_FREQUENCY=3600s, `last_sync_ts` envejece hasta 60min entre fetches. Pero `fmp.status` se calcula como `stale` cuando `time()-last_sync_ts > 1800s` (límite 30min interno hardcoded en bls_client.py línea 102).

**Implicación**: cada hora, durante los últimos 30min del ciclo de polling LOW, `fmp.status` mostrará `stale` aunque NO haya error. Es un **artefacto de naming** — el threshold interno (1800s) es < intervalo polling (3600s).

**Decisión**: si `fmp.errors=0` Y `fmp.last_error=""` Y `fmp.last_sync_ts < 3700s ago` → es Caso A → **proceder con r150-undecim-tris-bis** flagging falsa alarma + propuesta de fix.

### Caso B · `stale` por error real (fetch failed)
**Diagnóstico**: `fmp.errors > 0` o `fmp.last_error != ""` o `last_sync_ts > 3700s ago`.

**Decisión**: → **rollback inmediato** (criterio #1 violado: errors=0 ya no se cumple).

### Fix propuesto (independiente del caso)
Cambiar threshold interno de `stale` en `bls_client.py:102` de `1800s` a `3700s` para alinearlo con el ciclo LOW. Aplicar en r150-undecim-tris-bis si Caso A se confirma en el ping 11:40.

---

## §2 · Q2 · Histeresis 30min · async task o inline check?

**Recomendación: inline check non-blocking, NO async task separado.**

### Razón
- El sidecar main loop ya es asyncio cooperativo (cada `compute_state_once` es awaitable)
- La histeresis es solo una comparación de timestamps, **no requiere sleep bloqueante**
- Pseudo-code:
```python
# Dentro de compute_state_once, post-evaluate:
if state.get("mode") == "CAUTELA":
    cautela_age = now_utc.timestamp() - state.get("cautela_started_at", 0)
    if cautela_age >= 1800:  # 30min
        state["mode"] = "NORMAL"
        state["mode_reason"] = "hysteresis 30min cleared"
        state.pop("cautela_started_at", None)
```
- El check ejecuta en <0.1ms · no stalls

### Por qué NO async task
- Tasks separados añaden complejidad de cancelación y leak risk
- Comparten `state` dict que requiere locking (ahora es single-loop, sin races)
- 30min hysteresis con tick cada 5min → re-checked 6 veces · resolución sub-tick irrelevante

### Excepción: si en futuro se requiere sub-tick granularity (e.g. histeresis 30s)
Entonces sí async task. Para 30min, inline es óptimo.

---

## §3 · Q3 · Tokyo POC · Docker vs systemd namespaces?

**Recomendación: Docker container preferible para "Cero compartido".**

### Comparativa

| Dimensión | systemd namespaces | Docker container |
|---|---|---|
| Network namespace | sí (con `PrivateNetwork`) | sí (default) |
| Filesystem isolation | parcial (`PrivateTmp`, `ReadOnlyPaths`) | total (rootfs aislado) |
| Process tree isolation | sí (con `PrivateUsers`) | sí (default) |
| Resource limits (cgroup) | sí | sí |
| Image versioning | no (binarios en host) | sí (image hash) |
| Kill-switch atomic | systemctl stop | docker stop / image rm |
| Reproducibility | depende del host | total (Dockerfile) |
| Dependency conflicts | comparte `/usr/lib/python` | aislado |
| Ops complexity | bajo | medio (daemon dockerd) |

### Veredicto
- **Para "Cero compartido"** Docker gana en filesystem + dependency isolation
- Tokyo POC tendrá deps específicas (TSE feed lib, posibles `pip install` recientes) que no deben tocar el venv del sidecar
- Build minimal image base `python:3.12-slim` · ~150MB · A100 Dallas tiene 11TB libres
- Compose file con kill-switch:
  ```yaml
  services:
    tokyo_poc:
      image: vq-tokyo-poc:0.1
      restart: "no"  # NO auto-restart si crash
      environment:
        - TOKYO_POC_ENABLED=${TOKYO_POC_ENABLED:-false}
      volumes:
        - /sda-disk/tokyo_poc/data:/app/data
      networks:
        - tokyo_isolated
  ```

### Excepción
Si Marco prefiere systemd por simplicidad ops, también es viable usando:
- `PrivateNetwork=yes`
- `PrivateTmp=yes`
- `ReadOnlyPaths=/home/administrator/poly_sidecar`
- `User=tokyo_poc`
- venv separado en `/srv/tokyo_poc/venv/`

Pero pierde reproducibilidad de image versioned.

---

## §4 · Q4 · BUG-NFP-DIM · skip events o return neutral SF?

**Recomendación: Opción B · return neutral SF=0.0 con flag explícito.**

### Razón
- **Skip silencioso** (Opción A): pierde audit trail · si un evento NFP llega, no hay log de "lo procesé/no procesé"
- **Neutral SF=0.0** (Opción B): mantiene visibility · entry en `last_sf_event` con flag `bug_nfp_dim_skip=True`

### Implementación spec
```python
# En sf_engine.py SFEngine.evaluate():
BUG_NFP_DIM_ACTIVE = True  # config flag, deactivate post-2026-05-15 fix

def evaluate(self, category: str, actual: float) -> ModeDecision:
    if category == "NFP" and BUG_NFP_DIM_ACTIVE:
        LOGGER.warning(
            f"[BUG-NFP-DIM] NFP event SF computation skipped · "
            f"actual={actual} · returning neutral SF=0.0"
        )
        return ModeDecision(
            category="NFP",
            actual=actual,
            sf=0.0,
            mode="NORMAL",
            mode_reason="NFP SF deferred until 2026-05-15 (BUG-NFP-DIM)",
            bug_nfp_dim_skip=True,
        )
    # ... resto evaluate() normal
```

### Garantía de no false-positive CAUTELA
- `|SF=0.0|` < threshold NFP (1.3) → no trigger CAUTELA
- En `max(|SF|)` conflict resolution, NFP nunca gana frente a otros eventos
- Si llega solo un NFP event aislado → mode permanece NORMAL (correcto, no pifiamos por bug)

### Auditabilidad
- `state["last_sf_event"]` tendrá `bug_nfp_dim_skip=True` cuando aplique
- Búsqueda post-mortem trivial: `grep "BUG-NFP-DIM" sidecar.log`
- Cuenta de NFP events skipped trackeable

---

## §5 · Q5 · Soak OK + P3.7 smoke fail · Tokyo POC postpone automático?

**Sí. Postpone automático. Sin excepción.**

### Razón
La secuencia firmada en r150-novum/undecim/undecim-bis es **estricta**:
```
Soak (12h) → P3.7 SFEngine integration → smoke 9 tests → Tokyo POC
```

Cada paso es **gating**. Si P3.7 smoke falla, el sistema todavía no tiene la lógica SF integrada al main loop · Tokyo POC añadiría una variable de ruido que enmascararía el debug del fail.

### Protocolo automático

| Trigger | Acción Tokyo POC |
|---|---|
| Soak 12h ALL VERDE + P3.7 smoke 9/9 PASS | GO Dom 10 evening |
| Soak 12h ALL VERDE + P3.7 smoke 1+ FAIL | **POSTPONE auto** · nuevo target Lun 11 evening (24h buffer) |
| Soak 12h ALL VERDE + P3.7 smoke fix > 24h | **POSTPONE auto** · target Mar 13+ (post-CPI) |
| Soak 12h FAIL | Rollback total · Tokyo POC postpone indefinido hasta nuevo r-number |

### Notificación al postponer
- MD r150-rollback-tokyo-postpone-<reason>.md generado automáticamente
- Marco notificado en chat
- Gemma 4 31B notificada en próxima comunicación

### Marco/Claude responsibility
- **Claude detecta** smoke fail → notifica Marco
- **Marco firma** o redirige (Gemma puede sobreescribir si arquitectura cambia)
- **Claude ejecuta** postpone (es solo no-deploy, no requiere rollback)

---

## §6 · Pregunta de cierre · ¿algo más antes del ping 11:40 UTC?

Mi sugerencia: las 5 preguntas + 4 follow-ups previos cubren toda la arquitectura. Las próximas comunicaciones deberían ser **reportes de hechos** (KPIs), no más Q&A técnicas:

| Próximo MD | Hora | Contenido |
|---|---|---|
| r150-duodecim-prelim | 11:40 | 12 métricas PASS/FAIL del soak T+6h |
| r150-undecim-tris-bis (opcional) | 11:40 si Caso A §1 confirmado | Fix propuesto threshold stale 1800→3700s |
| r150-duodecim | 17:40 | Veredicto soak T+12h + GO/STOP P3.7 |
| r150-rollback-* | si trigger | Solo si rollback dispara |

**¿Confirmas cierre de la ronda Q&A?** Si sí, próxima comunicación será 11:40 UTC con KPIs.

Si tienes preguntas adicionales sobre Tokyo POC Dockerfile, P3.7 spec exacto, o BUG-NFP-DIM fix-plan post-2026-05-15 → mejor abrirlas en r-number separado post-CPI gate (Mar 13+).

---

**Spec firmadas previas**: r93 + r107-r152 + r150-bis...undecim-bis
**Status**: Soak T+0h 38min · 11.4h hasta T+12h · arquitectura completamente firmada con esta respuesta
**Próximo r-number**: r150-duodecim-prelim (11:40 UTC) salvo Caso A §1 que abre tris-bis
**Capital LIVE expuesto**: $0.00 · Mar 12 13:30 UTC microcapital condicional StressPass=True
**Tiempo restante CPI gate**: 78h 12min
