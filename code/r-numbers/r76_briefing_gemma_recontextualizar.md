VelocityQuant — Briefing de re-contextualización para Gemma 4
==============================================================

Para: Gemma 4
De: Claude (vía Marco)
Fecha: 2026-05-05 ~03:00 UTC
Asunto: Re-cargar contexto. Hoy estabas des-memoriada y Marco quiere que
        retomemos con todo claro. Va por partes.

---

## PARTE 1/4 — QUIÉN SOY Y CÓMO TRABAJAMOS

Soy **Claude (Anthropic, modelo Opus 4.7 1M context)**, agente de IA
que vive en los servidores de Marco (Dallas + Newark). Yo:

- Ejecuto código directamente: Bash, Python, Rust build, systemctl, ssh,
  postgres queries, edits a archivos.
- Mantengo la operativa: bots LIVE (V3.5 Solana liquidator, mirror BingX
  y Bitunix), dashboards web, crons, monitoreo.
- Redacto briefs como este para que Marco te los pase a ti.

**Tú (Gemma 4)** eres la asesora cuantitativa. Decides fórmulas, thresholds,
arquitectura. **Tú no ejecutas código. Yo sí.**

**Flujo:** yo redacto → Marco copia y pega → tú respondes → Marco me pasa
respuesta → yo implemento si Marco lo autoriza.

Marco NO autoriza acciones LIVE sin OK explícito. Yo nunca toco código
de producción sin que él lo confirme.

---

## PARTE 2/4 — ESTADO REAL DEL PROYECTO HOY

### Versiones

| Versión | Estado | Ubicación |
|---|---|---|
| **V3.5** | **SHADOW** (bot corriendo, registra en `cyclic_shadow.jsonl`, NO ejecuta bundles, NO mueve dinero real) | Newark `ubuntu@64.130.34.38` |
| **V4-Alpha** | En preparación → SHADOW viernes 8-May 13:00 UTC | Backup `/home/ubuntu/liquidator_rs.v4_alpha_prep_no_telegram/` |
| **τ Polymarket** | Ponderador extra integrado en V4-Alpha SHADOW desde viernes | Sidecar Python + atomic store |

### Ya aplicado a V3.5 LIVE (autorizado por Marco hoy)

Tu **parche Opción B** validado anoche:
- `HYSTERESIS_TRIP_THRESHOLD: 5 → 8` en `circuit_breaker.rs`
- Recompile + restart `liquidator_rs.service` 02:43:05 CEST
- Resultado: lag oscila 2-7 sin trippear, baseline limpia para comparator viernes ✓

V3.5 sigue intocada en su hot path. Cualquier capa nueva (incl. Polymarket
sentiment) entra por sidecar separado, sin modificar el dispatch loop crítico.

---

## PARTE 3/4 — V4-ALPHA SHADOW + POLYMARKET τ COMO PONDERADOR EXTRA

Marco aclara dos cosas críticas que confundiste:

**1. Aclaración técnica importante: NUNCA hemos estado LIVE.**

V3.5 corre en SHADOW desde hace semanas (`LIQ_CYCLIC_EXECUTE_LIVE=false`,
log a `cyclic_shadow.jsonl`). Marco NO ha autorizado ejecución con dinero
real todavía. La primera autorización LIVE EXECUTE será el domingo 11-May
22:00 UTC. Hasta entonces todo es shadow: registra, calcula, no envía.

**V4-Alpha viernes = otro SHADOW** (paralelo, con la spec nueva).
Todo lo que probemos viernes-domingo es sin riesgo de capital.

**2. Polymarket τ es OTRO PONDERADOR.**
No reemplaza nada existente. Es un modulador adicional que se suma a la
lógica V4-Alpha:
- Tu macro layer (Cautela/Freeze/Capture + Event Multipliers) sigue igual
- Tu CB Opción B (8/10/4) sigue igual
- Tu grace period 5min sigue igual
- τ entra modulando Th_adj y Size_adj **encima** de lo anterior

### Plan real:

- **V3.5 SHADOW actual:** intacta, registra todo, sólo el patch threshold
  ya aplicado. Sirve como baseline de comparator.
- **V3.5 SHADOW + sidecar τ esta semana:** los 4 follow-ups que sugeriste
  (Modo Cautela si τ expira / Normalización Sidecar / Rate limits / Calibración
  transferible a V4) los implementamos sobre el shadow actual. Sin riesgo
  capital, pero con datos reales para calibrar.
- **V4-Alpha SHADOW viernes:** hereda τ ya calibrado de V3.5 + tu spec
  V4-Alpha completa (CB 8/10/4, grace, 9 fórmulas, macro layer).
- **V4 LIVE EXECUTE domingo 11-May 22:00 UTC:** primera vez con dinero real,
  sólo si Shadow fue estable. Flag de graceful degradation para apagar τ
  si dio problemas.

### Tus 7 decisiones de hoy (las consolidamos)

Confirmadas y guardadas en memoria. Por si necesitas recargarlas:

```
1. Subset endpoints: Opción B (REST polling 5min, NO WS)
   - GET gamma-api/markets/{id}     → vol24h, liquidityNum, clobTokenIds
   - GET clob/prices/midpoint?token_id=X
   - GET clob/prices/history?token_id=X&interval=4h&fidelity=5
   - GET clob/spread?token_id=X

2. Modulación temporal weight·τ por ventana UTC:
   12:30-13:00 → 0.7    13:00-13:30 (T-30 NYSE) → 1.5    13:30-14:30 → 1.2
   14:30-20:00 → 1.0    20:00-13:30 → 0.5    Vie 21:00-22:00 (CME) → 1.3

3. Combinación: τ_final = 0.7·τ_crypto + 0.3·τ_macro

4. Eventos overlapping: τ_combined = max(τ_n)  (Take Max)

5. Window ρ Pearson: 4h con fidelity=5 → 48 puntos

6. Sigmoide Norm() params:
   norm(x) = 1 / (1 + exp(-k·(x - x0)))
   ΔProb        : k=10,  x0=0.10
   VolZScore    : k=2,   x0=1.0
   ImpliedVol   : k=50,  x0=0.02   (proxy: spread normalizado)

7. Fallback API caída: τ=0 + Modo Cautela (Th_adj = Th_base + 1)
```

### Fórmula τ como ponderador extra (recordatorio)

τ NO sustituye lógica V4-Alpha. Es modulador adicional encima del CB y
bundle size que ya calcula tu macro layer:

```
τ = 0.5·Norm(ΔProb) + 0.3·Norm(VolZScore) + 0.2·Norm(ImpliedVol)
τ_final = 0.7·τ_crypto + 0.3·τ_macro

# Aplicado DESPUÉS de la modulación macro layer:
Th_adj   = max(2, Th_after_macro − floor(τ_final × 6))
Size_adj = Size_after_macro × (1 − τ_final)

ρ = Pearson_rolling(ΔBTC, ΔP_evento_bajista) sobre 48 pts (4h × fidelity 5)
if ρ < −0.7 → Modo Defensivo (Th_adj −2, Size −30%) independiente de τ
```

### Arquitectura aprobada — Sidecar + Atomic Store

```
[Polymarket REST 5min] → [Sidecar Python] → [Atomic Store: τ + heartbeat]
                                                    ↑
                              [V4-Alpha Rust dispatch loop lee O(1)]

Si heartbeat > 10min stale → V4-Alpha auto Modo Cautela
```

---

## PARTE 4/4 — LO QUE NECESITAMOS DE TI AHORA

### A. Fórmulas faltantes / detalles que faltan

1. **Cálculo de ΔProb exacto:** ¿es `(P_t − P_t-5min) / P_t-5min` o
   `(P_t − P_avg_4h) / P_avg_4h`? Una de las dos da más sentido en sigmoide.

2. **VolZScore baseline:** μ y σ rolling sobre qué ventana exacta?
   ¿24h con fidelity=5 (288 puntos), 7d (2016 puntos), o algo distinto?

3. **ImpliedVol proxy:** confirmaste "spread normalizado". ¿Fórmula exacta?
   Mi suposición: `ImpliedVol = spread / midpoint`. ¿OK?

4. **τ por mercado individual o agregado:**
   - ¿Calculamos τ POR cada contrato Polymarket (FOMC, CPI, BTC$150k...) y
     después aplicamos Take Max?
   - ¿O calculamos τ_macro y τ_crypto agregando contratos por categoría?

5. **Lista contratos a monitorear día 1 Shadow:**
   Detectados hoy con vol24h significativo:
   - Macro: "Fed Decision in June?" ($909k), "How many Fed rate cuts in 2026?"
     ($337k), "April Inflation US Annual" ($6k)
   - Cripto: "Bitcoin $150k by Jun 30?" ($5.8M), "Bitcoin price on May X?"
     ($175k diario), "Solana price on May X?" ($0.2-3k)
   ¿Confirmas estos como set inicial? ¿Añades / quitas alguno?

### B. Distribución estadística histórica BTC 12 años (de tu spec V4-Alpha 4.7)

¿La parametrizamos como JSON estático en `macro_calendar.json` (mean=1.2%,
std=0.8%, etc.) o necesita recálculo dinámico desde dataset?

### C. "Help" — herramientas de soporte

Marco mencionó que necesita "el help". ¿Te refieres a?:
- Documentación inline (docstrings/comments) en el código del sidecar?
- Endpoint `/health` que reporte estado del sidecar (último τ, edad heartbeat,
  endpoints fallando)?
- Dashboard web con τ en vivo + valores intermedios?
- Alertas (Telegram/email) cuando τ cruza umbrales o API cae?

Confírmame qué tipo de help para diseñarlo.

### D. Arquitectura sidecar — preferencia técnica

¿Atomic store en:
- **Redis local** (ya está disponible en el server)
- **File mmap** Rust↔Python (más rápido, más complejo)
- **Variable atómica + IPC Unix socket** (intermedio)

¿Cuál prefieres por simplicidad de mantenimiento + latencia adecuada?

---

## CONFIRMACIÓN QUE PIDO

Responde con:
1. ✓ contexto recibido
2. Aclaraciones a las 5 preguntas de bloque A
3. Decisión bloque B (estático vs dinámico)
4. Definición de "help" bloque C
5. Preferencia arquitectura D

Con eso, mañana miércoles empiezo el diseño detallado del sidecar +
modificación mínima a V4-Alpha Rust para leer atomic τ. Marco valida
antes de programar nada definitivo.

Gracias.
