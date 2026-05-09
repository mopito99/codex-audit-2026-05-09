VelocityQuant — ¿Adelantar V4-Alpha SHADOW desde HOY?
=======================================================

Para: Gemma 4
De: Marco
Fecha: 2026-05-05 ~07:00 UTC
Asunto: Decisión operativa. V3.5 estable + sidecar 4-fuentes operativo +
        tu aprobación firmada. ¿Por qué no arrancar V4-Alpha SHADOW
        AHORA en lugar del viernes 8?

---

## Estado actual (verificable en vivo)

### V3.5 SHADOW Newark
- Uptime desde 02:43:05 UTC (4h aplicando tu parche threshold 5→8)
- Lag oscila 2-7 sin trippear ni una vez
- Memoria 9-10MB plana, 0 panics, 0 errores fondo
- Es la baseline más limpia que hemos tenido nunca

### Sidecar 4 fuentes (`https://inicio.velocityquant.io/poly/api/state`)
- Polymarket: 8 contratos (4 macro + 4 cripto), τ calculándose
- BTC/Pyth: $80,899 spot, samples acumulando para ρ Pearson
- FMP: 1017 events / 42 tracked, NEXT JOLTs+ISM hoy 14:00 UTC
- Investing.com: 53 events cached, ready para capturar `actual`
- **FRED: 10 series calibradas con 12y, σ reales reemplazaron defaults**

### Tu auditoría firmada (07:30 UTC hace 30min)
> "Implementación Aprobada. El sistema pasa de ser un 'indicador de
> sentimiento' a un 'sistema de gestión de riesgo macro'. Procede con
> el despliegue de V4-Alpha SHADOW para el viernes."

---

## La pregunta operativa de Marco

V4-Alpha SHADOW es **modo simulación sin dinero real** (`LIQ_CYCLIC_EXECUTE_LIVE=false`).
Iguales restricciones de capital que V3.5 SHADOW. **No hay riesgo de pérdida.**

Pero el spec dice "viernes 13:00 UTC". Marco pregunta: **si todo está listo y
estable, ¿qué nos hace esperar 3 días?**

### Pros de adelantar a HOY (Marco)

1. **Hoy 14:00 UTC: JOLTs + ISM (HIGH impact)** — primera oportunidad de
   ver el pipeline end-to-end con evento macro real:
   - Investing.com captura `actual` ~30min después
   - Calcula SF con σ_FRED real (no defaults)
   - Si |SF| > 1σ → MODE=CAUTELA en atomic store
   - V4-Alpha Rust en SHADOW lee el state y simula la decisión
   - Comparator V3.5 vs V4-Alpha sobre el mismo evento

2. **Vie 8 12:30 UTC: NFP** — si arrancamos hoy, llegaría al NFP con
   3 días de calibración real, no el día del deploy.

3. **Lun 12 12:30 UTC: CPI** — bot probado contra dos eventos macro
   antes del LIVE EXECUTE Dom 11.

4. **Más tiempo de comparator** = más confianza al activar LIVE.

### Pros de mantener viernes (tu spec original)

1. **V4-Alpha Rust requiere modificación** para leer `tau_state.json`
   y aplicar `Th_adj`/`Size_adj`/`mode` del sidecar. Eso es trabajo de
   miércoles según roadmap (no está hecho hoy).

2. **Code Freeze + audit** del binario V4-Alpha sin la integración τ
   ya estaba terminado. Re-tocar requiere re-audit.

3. **Comparator científicamente puro:** V3.5 (baseline sin τ) vs V4-Alpha
   (con τ desde día 1) — separación clara de qué cambió.

4. **Tu spec dice viernes.** Saltarse el timeline puede meter bugs no
   detectados.

---

## Pregunta concreta para ti

**Opción A — Mantener spec original (viernes 8 13:00 UTC)**
- Mi/Mié implemento modificación V4-Alpha Rust para leer atomic τ
- Jue brief consolidado + tu GO formal
- Vie 13:00 UTC deploy SHADOW
- Eventos cubiertos: NFP vie + CPI lun

**Opción B — Adelantar a HOY (martes 5)**
- Implemento modificación Rust EN LAS PRÓXIMAS 4-5h
- Backup defensivo + audit interno
- Deploy V4-Alpha SHADOW ~12:00 UTC HOY (antes de JOLTs+ISM 14:00)
- Eventos cubiertos: JOLTs+ISM hoy + NFP vie + CPI lun (3 vs 2)

**Opción C — Mid-week intermedio (miércoles)**
- Mié mañana implemento Rust + audit + deploy SHADOW
- Eventos cubiertos: NFP vie + CPI lun (igual que A pero con 1 día más
  de calibración)

¿Cuál es técnicamente más sólida desde tu óptica de riesgo cuantitativo?

### Sub-pregunta: ¿qué riesgos ves en B?

Marco entiende que adelantar tiene un riesgo de implementación apurada.
Pero también ve que:
- V3.5 sigue corriendo intacto (no se toca)
- V4-Alpha es un binario distinto en `liquidator_rs.v4_alpha_prep_no_telegram/`
- Si V4-Alpha SHADOW falla → solo logs perdidos, V3.5 sigue
- Sidecar es proceso aparte → si falla, V4-Alpha cae a τ=0+Cautela auto

¿Hay algún riesgo cuantitativo que no estamos viendo?

---

## Si dices "Opción B procede"

Necesito de ti **antes de programar**:

1. **Plan exacto del wiring Rust V4-Alpha → atomic store:**
   - ¿Lectura sincrona en cada slot del dispatch loop, o async background?
   - ¿Cache local en Rust con TTL 30s, o re-leer state.json cada slot?
   - ¿Qué hace si `mode_reason` cambia entre dos slots — log de transición?

2. **Cómo modula τ encima de tu macro_layer existente:**
   - Tu spec V4-Alpha §4.5 dice "Capture mode threshold = 10" cuando macro
     activo. Si τ_final = 0.5 → `Th_adj = max(2, 10 − 3) = 7`. ¿Correcto?
   - ¿Size_macro × (1−τ) o Size_after_macro × (1−τ)? Confirma orden de
     aplicación.

3. **Audit checklist de 5min antes del SHADOW** que tú apruebes para
   validar que V4-Alpha lee bien el atomic store y no corrompe el dispatch.

---

Marco mira. Tu llamada técnica define el resto del día.
