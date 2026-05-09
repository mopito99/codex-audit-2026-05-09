VelocityQuant — Brief consolidado pre-deploy V4-Alpha SHADOW (miércoles)
=========================================================================

Para: Gemma 4
De: Marco
Fecha: 2026-05-05 ~09:00 UTC
Asunto: 4 puntos antes del deploy mañana. Tu llamada cuantitativa define
        cómo programa Claude el wiring Rust + el comparator del viernes
        + los GO criteria del domingo.

---

# CONTEXTO RÁPIDO

- Tú aprobaste Opción C (deploy V4-Alpha SHADOW miércoles) hace 30min
- σ_FRED ya calibrados con 12y: FOMC=17.10bps, CPI=2.12% YoY, PCE=0.15%
  MoM, NFP=1807k, JOLTS=383, GDP=1.69% QoQ, UNEMP=0.94pp, RETAIL=2.33%
- Sidecar 4 fuentes operativo (Polymarket+BTC/Pyth+FMP+Investing.com)
- HOY 14:00 UTC: JOLTs+ISM (HIGH impact) — primer evento que pillará
  el sidecar (V3.5 SHADOW), aún sin V4-Alpha conectado

---

# 1. BACKTEST HISTÓRICO MACRO — usa tu acceso analítico

Antes de cablear V4-Alpha mañana, necesitamos verificar empíricamente
que tu spec V4-Alpha §4.7 sigue válida con la realidad reciente.

Tú tienes acceso analítico desde 2014+ y series macro completas FRED.

**Para los principales releases macro de los últimos 12 años (NFP, CPI,
FOMC, PCE), genera el resumen estadístico de:**

1. Movimiento BTC en ventanas T-30min, T+5min, T+30min post-release
2. Frecuencia P(|move|>2σ) real → comparar con tu spec "15-20%"
3. Mean reversion T+5 a T+30 real → comparar con tu spec "30-50%"
4. Decomposición por categoría (¿NFP > CPI? ¿FOMC > NFP? ¿régimen
   post-2021 vs pre-2021?)

**Devuelve:**
- Tabla con n eventos, mean |move|, std, P(>2σ), mean reversion
- ¿La spec V4-Alpha §4.7 sub-estima, sobre-estima, o está en línea?
- Si discrepa → números actualizados para `btc_response_profile` en
  `macro_calendar.json`

---

# 2. REFINAMIENTO σ_FRED — pregunta crítica

Tras calibrar con 12 años:
- **σ_NFP = 1807k** (ENORME, incluye COVID-19: -22M jobs Apr 2020 + recuperación)
- σ_FOMC = 17 bps (vs default 25)
- σ_CPI = 2.12% YoY (vs default 0.1% → mucho menos reactivo)

**Problema:** sin filtrar outliers, σ_NFP es tan grande que el bot
**nunca reaccionará a un NFP normal de ±200k surprise**.

¿Cuál es tu recomendación cuantitativa:
- (a) Mantener σ con outliers (régimen real incluye eventos extremos)
- (b) Winsorize 3σ trimming
- (c) Excluir explícitamente período Mar-Sep 2020 (COVID shock)
- (d) Usar MAD (Median Absolute Deviation) en lugar de σ — robusto a outliers
- (e) Otra técnica que prefieras

Marco aplicará lo que decidas en `fred_init.py` antes del deploy.

---

# 3. ESTRUCTURA EXACTA DEL TEST "GRACEFUL DEGRADATION"

Tu spec dice: si state.json corrupto o vacío → MODE=CAUTELA τ=0.
Marco propone 5 tests pre-SHADOW. ¿Confirmas o añades?

### Test 1 — state.json vacío
1. `mv state.json state.json.bak`
2. `touch state.json` (file vacío)
3. Verificar log Rust: `[MACRO_FALLBACK] empty → MODE=CAUTELA τ=0`
4. Dispatch loop sigue corriendo sin crashear
5. Restaurar y verificar polling 10s recupera

### Test 2 — JSON corrupto
1. `echo "{ corrupt json [" > state.json`
2. Esperar 15s
3. Verificar log `[MACRO_FALLBACK] parse error → MODE=CAUTELA τ=0`

### Test 3 — Campos faltantes
1. Escribir `{"heartbeat_ts": 1000000}` (sin tau_final, sin mode)
2. Verificar fallback a τ=0 + MODE=CAUTELA

### Test 4 — Heartbeat stale (>10min)
1. State válido pero heartbeat_ts 15min en el pasado
2. Verificar log `heartbeat stale → MODE=CAUTELA τ=0`

### Test 5 — File lock concurrencia
1. Mientras Rust lee, Sidecar Python re-escribe (atomic rename)
2. Rust nunca debe leer JSON parcial

¿Suficientes? ¿Añades alguno (ej. permisos rotos, disk full, etc.)?

---

# 4. KPIs COMPARATOR V3.5 vs V4-Alpha (criterio de éxito)

Tras viernes (NFP) y lunes (CPI), comparator V3.5 SHADOW vs V4-Alpha
SHADOW. ¿Qué KPIs específicos priorizar para determinar si la modulación
τ está realmente mejorando, o solo añadiendo ruido?

### Marco sugiere primarios

1. Quote acceptance rate alrededor de eventos macro (V4 debería reducir
   trades en T-30min y aumentar en T+20min)
2. Drawdown máximo durante NFP/CPI (V4 debería evitar spikes pérdida)
3. Hit rate post-evento T+5..T+30 (V4 en Capture mode debería capturar
   mejor las ineficiencias del re-pricing)

### Secundarios

4. Tiempo total en MODE=CAUTELA/DEFENSIVO vs eventos efectivamente impactantes
5. Falsos positivos (τ activó CAUTELA pero evento fue benigno)
6. Falsos negativos (bot operó normal y evento fue volátil)
7. Slippage promedio en bundles macro windows

### Métricas de descarte

- τ_final >40% del tiempo en CAUTELA sin reactividad real → ruido
- Correlación τ vs volatilidad real BTC < 0.3 → señal débil

**¿Confirmas este set?**

**¿Cuál es el threshold cuantitativo de "mejora suficiente para LIVE"?**
Ejemplo: V4 drawdown ≤ 70% de V3.5, hit rate ≥ V3.5 + 5%.

---

# 5. GO CRITERIA EXACTOS LIVE EXECUTE Dom 11 22:00 UTC

Si miércoles deploy + jueves estabilización van perfectos, ¿qué criterios
específicos tienen que cumplirse para activar `LIQ_CYCLIC_EXECUTE_LIVE=true`?
Necesito un semáforo cuantitativo, no subjetivo.

### Marco propone

**Hard gates** (cualquiera falla → NO LIVE):
- [ ] V4-Alpha SHADOW corrió ≥48h sin un solo crash
- [ ] 0 panics en `journalctl -u v4alpha`
- [ ] Memoria estable (no leak detectable en muestras de 8h)
- [ ] Sidecar 4 fuentes uptime ≥95% últimas 48h
- [ ] τ_final OSCILA (no plano permanente, no errático)
- [ ] NFP del viernes: V4-Alpha respondió como esperado
- [ ] CPI del lunes: V4-Alpha respondió como esperado

**Soft gates** (señal de cuidado pero no bloqueante):
- [ ] Comparator V4 ≥ V3.5 en hit rate post-macro
- [ ] Comparator V4 drawdown ≤ V3.5
- [ ] Sin ruido excesivo en transiciones de modo (≤10/día)

**Hard cancel** (Marco cancela LIVE):
- ¿Qué señal específica te haría decir "NO procede domingo"?
  - τ medio > 0.6 último día? (sentimiento extremo persistente)
  - Eventos macro con SF > 3σ los días previos?
  - Polymarket APIs caídas >2h en 48h?

**¿Cuáles GO/NO-GO criteria firmas tú?**

---

# DIRECTRICES TÉCNICAS YA CERRADAS (no necesitan respuesta)

Lo siguiente ya está validado por ti en briefings previos, lo listo
para que tengas el contexto completo:

```
Wiring Rust:
  - Async background thread (NO bloquea dispatch)
  - AtomicPtr o Arc<RwLock<MacroState>>
  - Polling state.json cada 10s
  - Log [MACRO_TRANSITION] Old:... → New:... | Reason:...

Modulación τ — orden de aplicación:
  1. Calcular Size_after_macro (binario macro layer Cautela/Freeze/Capture)
  2. Size_final = Size_after_macro × (1 − τ)   ← τ es freno final
  3. Th_adj = max(2, Th_base − Offset(τ))      ← τ es modulador

Audit checklist 5min pre-SHADOW:
  - Graceful Degradation
  - Parse Latency
  - Bounds Check τ ∈ [0,1]
  - Log Echo del mode_reason
  - Memory Leak 10min

Calendario:
  Mié 6 mañana: implement + audit
  Mié 6 tarde:  deploy V4-Alpha SHADOW
  Jue 7:        estabilización
  Vie 8 12:30:  NFP test
  Lun 12 12:30: CPI test
  Dom 11 22:00: LIVE EXECUTE (target)
```

---

# RESUMEN — lo que pido en orden de prioridad

1. **Backtest histórico macro** (§1) — ¿spec V4-Alpha §4.7 sigue válida?
2. **Refinamiento σ_FRED** (§2) — a/b/c/d/e o propuesta tuya
3. **Tests Graceful Degradation** (§3) — confirma 5 + añade
4. **KPIs comparator** (§4) — confirma sets + threshold mejora
5. **GO criteria LIVE** (§5) — hard/soft/cancel con números

Tu llamada en estos 5 puntos define todo el sprint hasta el domingo.
Marco se basa 100% en lo que decidas.

Gracias.
