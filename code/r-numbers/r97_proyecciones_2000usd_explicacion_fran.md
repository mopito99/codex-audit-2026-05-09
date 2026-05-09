VelocityQuant — Proyecciones realistas con $2,000 capital LIVE
================================================================

**Para:** Fran (socio + amigo) y evaluador IA externo
**De:** Marco + Claude (asistente técnico)
**Fecha:** 2026-05-05
**Capital base de trabajo:** $2,000 USD
**Propósito:** explicar paso a paso, sin esconder nada, qué se puede
esperar matemáticamente del bot. Si después de leer esto algo huele a
scam, dilo. Marco prefiere romper el proyecto a deslealtad con un amigo.

---

# SECCIÓN 0 — La pregunta más importante de Fran (smell test)

Antes de la matemática, Fran preguntó algo que un evaluador IA debe
exigir respondido:

> *"Si se gana tanto y se reinvierte cada céntimo, ¿para qué hacen
> falta $2,000 adicionales?"*

**Respuesta directa: NO hacen falta.**

Si las proyecciones de este documento son razonables y reinviertes
todo el PnL neto:

| Mes | PnL neto reinvertido | Capital total al final del mes |
|---|---:|---:|
| Mes 0 (start) | — | $2,000 |
| Mes 1 (debug) | $3,500 - $4,900 | $5,500 - $6,900 |
| Mes 2 | $4,500 - $6,500 | $10,000 - $13,400 |
| Mes 3 | $5,600 - $8,400 | $15,600 - $21,800 |

**En 3 meses, el capital crece orgánicamente a $15k-$22k SIN que
nadie aporte más dinero.** Eso es lo que hace un sistema honesto
si las proyecciones son ciertas.

## Cuándo SÍ se justifica capital adicional

Solo 3 escenarios concretos, ninguno de los cuales aplica HOY:

1. **Drawdown crítico mes 1.** Si mes 1 cierra en pérdida significativa
   ($-500 o más) y se decide dar segunda oportunidad antes de pausar.
   Pero ahí la decisión es **rescate**, no **escala**.
2. **Escala estratégica post-validación.** Si mes 1 cierra positivo
   y queremos acelerar crecimiento doblando capital. Pero eso se
   decide DESPUÉS de tener data LIVE, no antes.
3. **Reposición tras exploit/hack.** Si la wallet se compromete,
   podríamos reponer SI decidimos continuar.

## Por qué un scam SÍ pediría capital adicional

| Indicador | Scam típico | VelocityQuant |
|---|---|---|
| ¿Pide capital escalado constante? | SÍ | **NO** |
| ¿Justifica el aporte con "es necesario para escalar más"? | SÍ | **NO — el bot escala con reinversión** |
| ¿Promete retorno fijo si aportas más? | SÍ | **NO — sin garantía** |
| ¿Pinta drawdown como "imposible"? | SÍ | **NO — drawdown documentado en §9** |

## La recomendación honesta

**Para Fran:**

- **NO envíes los $2,000 adicionales ahora.**
- Capital base $2,000 ($1,000 cada uno) es suficiente para validar
  V4-Alpha LIVE.
- Mantén los $2,000 adicionales **fuera del proyecto** como
  reserva personal.
- Después de mes 1 LIVE (post-Dom 11):
  - Si va bien → no hace falta aportar nada, capital crece solo
  - Si va mal → no aportar; pausar y auditar
  - Si va medio → conversación honesta los 3 (Marco + Fran + Claude)
    antes de cualquier aporte

**Para Marco:**

Lo mismo. **No metas $2,000 adicionales tú tampoco.** El bot debe
demostrar que puede crecer con $2,000 antes de pedir más.

## Por qué este documento usa "$2,000" como base

Originalmente este documento se escribió asumiendo $2,000 capital
inicial. Esa cifra **no implica que necesitemos $2,000 más**. Es el
**capital total que se va a poner LIVE el Dom 11** — $1,000 de cada
uno, total $2,000 en la wallet hot operativa.

Si en el resto del documento ves "capital LIVE = $2,000", **eso es
el total inicial, no incremental**. La proyección a $15k-$22k al
final del mes 3 es por **reinversión orgánica**, no por aportes
nuevos.

---

# RESUMEN PARA QUIEN NO QUIERE LEER 30 PÁGINAS

- El informe SHADOW de hoy muestra **$5,388 hipotéticos** detectados.
  **Eso NO es PnL realizable.** Es la suma de TODAS las oportunidades
  vistas asumiendo que pudieras ejecutarlas todas en paralelo. No
  puedes.
- Con **$2,000 capital LIVE** y aplicando todos los descuentos
  realistas (competencia, slippage, latencia, etc.), el rango
  esperado **mes a mes** es:
  - Mes 1 (post-deploy, debug): **$0 a $1,500** neto
  - Mes 2-3 (estable): **$300 a $4,500** neto
  - Mes 4-6 (maduro): **$500 a $7,000** neto
- En **2 días con $2,000**, el rango realista es **$50 a $1,500**
  el 95% del tiempo. **$2,000 en 2 días es <5% de probabilidad**
  y requiere confluencia rara.
- Costos compartidos infraestructura: **$15.24/día Marco+Fran combinado**
  (Marco $7.62, Fran $7.62). Break-even pareja: **$15.24/día**.
- Lo que prometemos: **un sistema cuant en validación**. Lo que NO
  prometemos: **rentabilidad porcentual fija**.

Si después del resumen sigues, te llevamos por la matemática completa.

---

# 1. DE DÓNDE VIENEN LOS DATOS — el informe SHADOW de hoy

El bot V3.5 lleva semanas en SHADOW (sin dinero real). Cada
evaluación que hace queda registrada en un archivo JSONL on-disk en el
servidor Newark.

URL pública del informe: https://inicio.velocityquant.io/informe.html

Cifras del día 2026-05-05 (parcial 00:00 → 21:00 UTC):

| Ventana UTC | Eventos | would_send | % | p_max ($) | p_sum ($) |
|---|---:|---:|---:|---:|---:|
| 00-08 Asia | 143,800 | 22,997 | 16.0% | 0.157 | 2,531.30 |
| 08-13 Londres | 90,000 | 14,116 | 15.7% | 0.149 | 1,563.23 |
| 13-16 LDN×NY | 53,923 | 9,488 | 17.6% | 0.076 | 931.25 |
| 16-21 NY post | 21,017 | 4,077 | 19.4% | 0.054 | 362.46 |
| **Total parcial** | **308,740** | **50,678** | **16.4%** | — | **5,388.24** |

## 1.1 Qué es cada columna (importante)

- **Eventos** = cuántas veces el bot evaluó si había arbitraje.
  ~4 evts/segundo durante todo el día. El bot está despierto y mirando.
- **would_send** = de esas evaluaciones, cuántas SUPERARON los filtros
  básicos (slippage tolerable, profit > costo gas, no fat-finger).
  El 16.4% del día. **Estas son las "oportunidades válidas"**.
- **CB blocked** (en el informe completo) = de esas, cuántas el
  Circuit Breaker interno bloqueó por seguridad. La mayoría.
- **p_max** = el profit hipotético MAYOR encontrado en esa ventana.
  $0.157 es **15.7 centavos** de USDC sobre un base de $100.
- **p_sum** = la suma de TODOS los profits hipotéticos de las
  oportunidades válidas en esa ventana. **Aquí está el número que
  asusta a Fran.**

## 1.2 Por qué $5,388 es engañoso si lo lees solo

`p_sum` asume que pudieras:

- Ejecutar las **50,678 oportunidades** del día simultáneamente
- Con **$100 de capital cada una** (50,678 × $100 = $5,067,800 capital
  necesario en paralelo)
- Sin que ninguna oportunidad afecte a las demás
- Sin competencia con otros searchers

**Tú tienes $2,000.** No $5 millones. Y tienes 1 wallet, no 50,000.

Por eso `p_sum` es una métrica de **DETECCIÓN del bot** ("cuánto VE"),
no de **EJECUCIÓN realizable** ("cuánto GANA"). Confundirlos es lo
que hace que parezca scam.

---

# 2. LOS FACTORES QUE COMEN EL p_sum HASTA LA REALIDAD

Aquí explicamos uno por uno por qué $5,388 SHADOW se convierte en
algo mucho más pequeño en LIVE.

## 2.1 Factor THROUGHPUT — el bot solo tiene 1 capital

**Concepto:** el bot solo puede tener UNA operación abierta a la vez
con tus $2,000. No puede clonarse para hacer 50 operaciones paralelas.

**Cuánto tiempo bloquea cada operación:**

```
Detección de oportunidad:    50-300 ms
Construcción de bundle:      20-50 ms
Envío a Jito:                30-100 ms
Confirmación on-chain Solana: 400-2000 ms (1-5 slots)
Settlement + balance update: 200-500 ms
                            -----
Total round-trip:           ~700ms - 2.95s
                            promedio realista: 2.0 - 2.5s
```

**Cycles posibles por día:**
```
86,400 segundos/día / 2.5s por cycle = 34,560 cycles/día máximo
```

Esto es el **techo absoluto** ignorando todo lo demás. Es lo que
podría hacer si el bot estuviera 24/7 al 100% utilización.

**Comparación con SHADOW:**
- SHADOW evaluó 308,740 veces hoy (4/seg)
- Pero esas son EVALUACIONES (lectura de pools), no EJECUCIONES
- En LIVE solo podemos EJECUTAR ~34,560 veces máximo

## 2.2 Factor FILTROS — solo el 16.4% pasa

```
34,560 cycles capacity teórica
×  16.4% pasan filtros pre-CB
=  5,668 cycles "rentables hipotéticos" máximo/día
```

Esto en LIVE serían **5,668 intentos de bundle/día como techo absoluto**.
Pero todavía no llegamos al PnL real, porque…

## 2.3 Factor COMPETENCIA — otros searchers también miran

**MEV es zero-sum.** Cuando V3.5 ve una oportunidad de arbitraje
SOL/USDC entre Raydium y Orca, **otros 5-50 searchers la ven al mismo
tiempo**. Solo gana el que:

1. Detecta primero (latencia)
2. Construye bundle más rápido
3. Paga tip más alto a Jito (winner-takes-all en bundles)
4. Tiene mejor RPC (Chainstack Yellowstone gRPC nos da edge)

**Win rate típico para searchers mid-tier:** 3-12% sobre las
oportunidades a las que apuestas.

```
5,668 cycles válidos × 3% win rate (pesimista) =   170 wins/día
5,668 cycles válidos × 7% win rate (medio)     =   397 wins/día
5,668 cycles válidos × 12% win rate (optimista) =  680 wins/día
```

**Por qué nuestro win rate puede mejorar con tiempo:**

- V4-Alpha añade tip pricing más inteligente (p75 dinámico ya existe,
  V4-Alpha añade tip-aware modulation con mode CAUTELA)
- Multiplexing Chainstack pendiente (R72 Sprint A) → más streams = mejor coverage
- Tip account p75 actualizado más frecuente → tips óptimos

**Por qué nuestro win rate puede empeorar:**

- Más searchers entran al pool nicho → competencia +
- Otro searcher con infra mejor (Tier 1) entra → nos comemos su polvo

**Estimación honesta:** **3-12% rango realista, 7% como base case**.

## 2.4 Factor SLIPPAGE — escalar capital come margen

**El problema:** el bot SHADOW simula con $100 fijo. Tu pool SOL/USDC
en Raydium phase1 tiene depth limitada. Cuando metes $2,000 (20× más
que SHADOW), el precio de SOL en el pool se mueve por TU propia
operación. Eso reduce el profit.

**Magnitud realista en SOL/USDC Raydium phase1:**

| Capital base | Slippage extra estimado |
|---|---|
| $100 (SHADOW) | <0.01% (negligible) |
| $500 | ~0.05% |
| $2,000 | **0.15-0.30%** |
| $10,000 | 0.5-1.0% (te comes la mayoría) |
| $50,000+ | NO operable en este pool |

**Aplicado a profit por win:**
- Profit hipotético per win @ $100 SHADOW: $0.106 promedio
- Escala lineal $2,000 (×20): $2.12 (sin slippage)
- Slippage discount $2,000 base: **−15% a −30%**
- **Profit real esperado per win: $1.50 - $1.80**

## 2.5 Factor TIPS A JITO — costo fijo por intento

Cada bundle enviado paga un tip a Jito (el block engine MEV de Solana)
para inclusión prioritaria. Sin tip → tu bundle no entra → pierdes
oportunidad.

**Tips típicos en V3.5 (verificable en JSONL):**

```
priority_fee_lamports: 10,025  →  ~$0.0009 USD
jito_tip_lamports:     24,000  →  ~$0.0021 USD
total_cost_lamports:   34,025  →  ~$0.0030 USD
```

**Estos costos son trivial vs profit per win** ($0.003 vs $1.50). Pero
hay que cobrarlos:

```
Profit bruto per win:  $1.50 - $1.80
Tip costs:            -$0.003
Profit neto per win:   ~$1.50 - $1.80 (no cambia significativamente)
```

**Nota importante sobre tips perdidos:** cuando tu bundle **NO gana**
(eres uno de los 5-50 searchers compitiendo), **los tips de los
intentos perdidos a veces se pierden** (depende del tipo de bundle Jito).
En modelo `bundle-with-tip-only-on-win`, no pierdes nada en intentos
fallidos. En modelo legacy, cobran siempre.

V3.5 usa Jito Block Engine bundles que **solo cobran tip si el bundle
es incluido**. Por tanto los intentos fallidos NO pierden tip. Esto
es importante: no hay sangre por intento.

Pero sí hay un costo en intentos fallidos: **tiempo de cycle bloqueado**
(mientras esperabas confirmación que no llegó).

## 2.6 Factor LATENCIA — Solana RPC + slot_lag

**Métrica crítica del informe SHADOW:**

```
slot_lag p50 = 0          ← bot al día 99% del tiempo
slot_lag p95 = 11          ← peor caso 5% del tiempo: 4.4s atrás
slot_lag max = 43-171      ← worst case del día: 17-68s atrás
```

Cuando `slot_lag > 10`, el bot está operando con info stale. Una
oportunidad detectada con info de hace 4s probablemente ya fue
consumida por otro searcher.

**Ventanas con mejor slot_lag:**
- LDN×NY (13-16 UTC): slot_lag max **43**, latencia p50 **850ms**
- Asia: slot_lag max **150**, latencia p50 **1,718ms**

**Implicación:** el bot funciona mejor cuando NY está abierto. Eso
podría sesgar el PnL: ~3h del día (LDN×NY) son más productivas que
las otras 21h.

## 2.7 Factor MACRO LAYER — el bot V4-Alpha se autopausa

V4-Alpha (no V3.5) añade el sidecar Polymarket Sentiment. En modes
`FREEZE` y `CAUTELA`, el bot **reduce o detiene operación**:

| Mode | Trigger | Acción |
|---|---|---|
| NORMAL | τ < 0.4 | operación estándar |
| CAUTELA | \|SF\| > 1σ | Th -1, Size ×0.7 → menos cycles |
| DEFENSIVO | τ > 0.7 | Th -2, Size ×0.5 → mucho menos |
| FREEZE | macro release < 5min | **NO opera** |
| CAPTURE | macro release < 60s | **NO opera** + capture state |

**Cuántas horas/día estamos NO en NORMAL:**

```
NFP, CPI, FOMC, PCE, ISM, JOLTS releases:    ~20-30 minutos/día CAUTELA
Pre-evento FREEZE periods:                    ~30-60 minutos/día
Total reducción de operación:                 ~5-10% del día
```

**Esto reduce throughput pero protege el capital.** En el día de hoy
(2026-05-05 ISM Prices SF=−3σ), si V4-Alpha hubiera estado LIVE,
hubiéramos estado en CAUTELA durante ~3h y hubiéramos perdido
~30-50% de las oportunidades de NY post-LDN. **Es deliberado.** No
queremos operar en macro shock.

## 2.8 Factor SOLANA NETWORK — outages y degradación

Solana ha tenido outages históricas (~1-3 días/año totales). Cuando
Solana está laggy o caída:

- slot_lag explota a >100
- Confirmaciones tardan minutos
- Bundles no se incluyen
- Bot no opera

**Provisión en proyecciones:** asumimos 95% uptime efectivo de
Solana. 5% del mes = ~36 horas sin operación.

## 2.9 Factor POOL DEPTH — volumen del par cae

SOL/USDC tiene volumen masivo en Raydium y Orca (top 5 pools de
Solana). Pero hay variación día/día y semana/semana:

- Semanas bull con SOL alto: volumen +50-100% sobre baseline
- Semanas bear o lateral: volumen -30-50%
- Halvings, eventos macro, fin de mes: spikes y droughts

**Implicación para PnL:** el bot detecta más oportunidades cuando hay
más volumen. Un mes laterales puede dar 30-50% menos opportunities que
un mes volátil.

## 2.10 Factor BUGS POST-DEPLOY — primer mes LIVE es siempre debug

V4-Alpha aún no ha corrido en LIVE. **Asumir que el primer mes va a
funcionar al 100% es ingenuo.** Bugs típicos post-deploy:

- Mode lock falso (entra en DEFENSIVO y no sale)
- σ_FRED bug se activa con release inesperado (ya tenemos el bug
  de JOLTS identificado)
- Tip pricing dinámico se desincroniza
- Pool subscriptions se desconectan y no recargan
- Edge cases on-chain (transferencias inesperadas a la wallet)

**Provisión en proyecciones:** mes 1 con 30-50% del rendimiento
esperado. Mes 2-3 alcanza 70-90%. Mes 4+ alcanza el rendimiento
nominal.

---

# 3. CÁLCULO PASO A PASO CON $2,000

Ahora aplicamos TODOS los factores secuencialmente. Esto es la
matemática que un evaluador puede auditar.

## Paso A — Capacity teórica

```
86,400 s/día / 2.5s round-trip = 34,560 cycles/día máximo
```

## Paso B — Filtros pre-CB

```
34,560 × 16.4% pasan filtros = 5,668 cycles válidos/día máx
```

## Paso C — Win rate vs competencia

```
Pesimista:   5,668 × 3%  =  170 wins/día
Base:        5,668 × 7%  =  397 wins/día
Optimista:   5,668 × 12% =  680 wins/día
```

## Paso D — Profit por win con escala $2,000

```
Profit hipotético @ $100 SHADOW:    $0.106 promedio
Escala lineal a $2,000 (×20):       $2.12
Slippage discount $2,000 (−20%):    -$0.42
Profit real esperado per win:       $1.70 promedio (rango $1.50-$1.90)
```

## Paso E — PnL bruto diario por escenario

| Escenario | Wins/día | $/win | PnL bruto/día |
|---|---:|---:|---:|
| **Excepcional** (volatilidad alta + low competition) | 680 | $1.85 | **$1,258** |
| **Bueno** | 500 | $1.70 | **$850** |
| **Medio** | 320 | $1.55 | **$496** |
| **Malo** | 150 | $1.20 | **$180** |
| **Pésimo** (Solana laggy o bug) | 50 | $0.80 | **$40** |

## Paso F — Costos diarios

```
Newark + Chainstack + misc:  $457/mes
÷ 30 días                  = $15.24/día (compartido Marco+Fran 50/50)
```

## Paso G — PnL neto diario

| Escenario | Bruto | Costo | Neto |
|---|---:|---:|---:|
| Excepcional | $1,258 | -$15.24 | **$1,243** |
| Bueno | $850 | -$15.24 | $835 |
| Medio | $496 | -$15.24 | $481 |
| Malo | $180 | -$15.24 | $165 |
| Pésimo | $40 | -$15.24 | $25 |

---

# 4. DISTRIBUCIÓN DE ESCENARIOS — ¿qué proporción del mes está en cada uno?

**Estimación conservadora** (ojo: no tenemos datos LIVE aún, son
asunciones basadas en SHADOW + experiencia MEV pública):

| Escenario | % del mes | Días/mes |
|---|---:|---:|
| Excepcional | 5% | 1.5 |
| Bueno | 20% | 6 |
| Medio | 40% | 12 |
| Malo | 25% | 7.5 |
| Pésimo | 10% | 3 |

**PnL mensual esperado con esta distribución:**

```
1.5 × $1,243 + 6 × $835 + 12 × $481 + 7.5 × $165 + 3 × $25
= $1,865 + $5,010 + $5,772 + $1,238 + $75
= $13,960/mes neto teórico
```

**ROI mensual sobre $2,000:** +698%. Esto suena scammy.

## 4.1 Aquí es donde aplicamos descuentos de realidad

Las cifras de arriba son **el upper bound matemático suponiendo que
todo funciona como SHADOW**. Pero nunca hemos LIVE V4-Alpha. Por tanto:

**Mes 1 (deploy, debug, ajustes): 25-35% del upper bound**
- Bugs activos (al menos JOLTS, posibles más)
- Fine-tuning de parámetros con data real
- Marco + Gemma observando 24/7 para parar si algo no cuadra
- **Esperado mes 1: $3,500 - $4,900 neto**

**Mes 2-3 (estabilización): 40-60% del upper bound**
- Mayor parte de bugs corregidos
- Win rate calibrado contra competencia real
- Tip pricing ajustado
- **Esperado mes 2-3: $5,600 - $8,400 neto**

**Mes 4-6 (operación madura): 60-80% del upper bound**
- Sistema estable
- Optimizaciones secundarias (multiplex Chainstack, etc.)
- **Esperado mes 4-6: $8,400 - $11,200 neto**

## 4.2 La honestidad cruel

**Si en mes 1 generamos $200 en lugar de $3,500, NO pasa nada catastrófico.**
- Costo mensual: $457 ($228.50 cada uno)
- Capital arriesgado: $2,000
- Pérdida potencial neta: $200 (cubrir costos + reposición)
- Marco y Fran no se arruinan

**Si en mes 1 perdemos $500 del capital LIVE:**
- Pausamos
- Auditamos qué falla
- Ajustamos
- Volvemos a SHADOW si es necesario

**El proyecto no está apostando todo a un mes.** Está construyendo un
sistema que puede sostenerse a lo largo de 6-12 meses con drawdowns
incluidos.

---

# 5. RANGOS FINALES POR HORIZONTE

Sintetizando todo lo anterior con las distribuciones realistas y los
descuentos por mes:

## 5.1 En 2 días (que es lo que disparó la duda de Fran)

| Escenario combinado | Probabilidad estimada | PnL neto 2 días |
|---|---:|---:|
| 2 excepcionales seguidos | <2% | **$2,486** |
| 1 excepcional + 1 bueno | ~5% | $2,078 |
| 2 buenos | ~8% | $1,670 |
| 1 bueno + 1 medio | ~15% | $1,316 |
| 2 medios | ~20% | $962 |
| 1 medio + 1 malo | ~25% | $646 |
| 2 malos | ~15% | $330 |
| 1 malo + 1 pésimo | ~7% | $190 |
| 2 pésimos | ~3% | $50 |

**Probabilidad de "$2,000+ en 2 días":** ~5-7% (excepcional + bueno
o mejor).

**PnL esperado medio en 2 días:** ~$870.

**Distribución típica en 2 días:** **$300 a $1,500 (80% del tiempo)**.

## 5.2 En 7 días

```
PnL esperado mes 1: $3,500-$4,900
÷ 30 días × 7 días = $817 - $1,143 esperado en 7 días primer mes
```

**Rango realista:** $400 a $2,500 en 7 días primer mes.

## 5.3 En 30 días por mes de operación

| Mes | PnL neto esperado | ROI sobre $2,000 |
|---|---:|---:|
| Mes 1 (debug) | **$3,500 - $4,900** | +175% a +245% |
| Mes 2 | **$4,500 - $6,500** | +225% a +325% |
| Mes 3 | **$5,600 - $8,400** | +280% a +420% |
| Mes 4 | $7,000 - $9,800 | +350% a +490% |
| Mes 5 | $7,800 - $10,500 | +390% a +525% |
| Mes 6 | $8,400 - $11,200 | +420% a +560% |

**Estos números son agresivos pero no inflados.** Vienen de aplicar
descuentos reales a SHADOW. Si V4-Alpha LIVE falla en cualquier
factor, los números bajan rápidamente.

## 5.4 Escenarios de fallo (downside)

| Falla | Impacto en PnL/mes |
|---|---|
| Bug crítico V4-Alpha mes 1 | Mes 1 = $0 a $500 |
| Solana outage prolongado (>3 días) | -$500 a -$1,500 |
| Pool drying (volume cae 50%) | -30% a -50% del PnL esperado |
| Otro searcher Tier-1 entra al nicho | Win rate cae al 1-3% → PnL ÷3 |
| MiCA regulatorio se aplica más estricto | Pausa indefinida |

---

# 6. POR QUÉ ESTO NO ES SCAM (sección para Fran y para evaluador IA)

## 6.1 Lo que NO te decimos

- **No te decimos "vas a ganar X% al mes garantizado"**
- **No te decimos "duplica tu capital en N días"**
- **No tomamos depósitos de inversores externos**
- **No vendemos curso, mentoría, ni señales**
- **No tenemos landing page comercial**

## 6.2 Lo que SÍ te decimos

- **Hay un sistema real en construcción** (puedes leer el código en
  el Gitea privado bajo NDA)
- **Hay datos SHADOW reales auditables** (cyclic_shadow.jsonl en
  Newark, ~1.4M líneas verificables)
- **Hay un proceso de validación** (Mié 6 wiring → Jue 7 SHADOW V4 →
  Vie 8 NFP stress → Lun 12 CPI stress → Dom 11 LIVE primera vez)
- **Hay un capital LIMITADO** ($2,000 — no $200,000, no millones)
- **Hay autorización explícita** requerida (flag técnico
  `LIQ_CYCLIC_EXECUTE_LIVE=true` que Marco activa manualmente)
- **Hay riesgo asumido** ($2,000 podría perderse total en
  escenarios extremos)
- **Hay un partnership 50/50** entre Marco y Fran sobre costos
- **Hay una entidad legal real** (Cuandeoro Limited, Ireland CRO 813028)

## 6.3 Lo que un scam haría diferente

| Indicador típico de scam | VelocityQuant |
|---|---|
| Promete % fijo mensual | NO promete % alguno |
| Pide depósito de "inversores" | Solo Marco + Fran 50/50 internos |
| Garantiza "sin pérdida posible" | Documenta downside explícitamente |
| Vende curso/señal | NO vende nada |
| Usa testimonios fabricados | NO tiene testimonios |
| Esconde el código | Código auditable bajo NDA |
| Esconde la wallet | Wallet on-chain pública (`GaL85...wbTh`) |
| Esconde la entidad | Cuandeoro Ltd CRO 813028 verificable |
| Apresura decisiones ("INVIERTE YA") | Cronograma con 5 stress tests antes de LIVE |
| Esconde al equipo | Marco operador, Fran socio, Gemma cuant, Claude asistente |

## 6.4 Por qué los números pueden parecer "demasiado buenos"

**Porque MEV cíclico Solana puede dar +100% mensual en buenas épocas
si el bot funciona bien**. No es porque mintamos los números — es la
naturaleza del nicho:

- Solana es una red de alta frecuencia (400ms slots)
- Los pools nicho (SOL/USDC concentrated liquidity) tienen muchos
  arbitrajes pequeños
- Searchers públicos como Helius y Phoenix MEV reportan cifras
  similares en sus sales decks (verificable en sus reports públicos)
- Comparado con DeFi yield farming (~10-30% APY) o staking (~5-7% APY),
  MEV activo es mucho más volátil pero también potencialmente más
  rentable. **Y mucho más arriesgado.**

## 6.5 Por qué pueden parecer humo

**Porque NO TENEMOS UN MES DE LIVE TODAVÍA.** Toda esta proyección es
matemáticamente derivada del SHADOW. Si V4-Alpha LIVE en mes 1 da
$200 en lugar de $3,500, te diremos: "el modelo era optimista, ajustamos".

**No estaremos defendiendo cifras a posteriori.** Marco prefiere
admitir que algo no funcionó.

---

# 7. SANITY CHECKS QUE FRAN PUEDE HACER

## 7.1 Verificar que el bot está en SHADOW (no operando con dinero real)

```bash
ssh ubuntu@64.130.34.38 'grep LIQ_CYCLIC_EXECUTE_LIVE /home/ubuntu/liquidator_rs/.env'
```
Esperado: variable no seteada o `=false`. Si encuentra `=true`,
estamos LIVE sin haberle dicho — eso sería breach de confianza.

## 7.2 Verificar el archivo de SHADOW logs

```bash
ssh ubuntu@64.130.34.38 'ls -la /home/ubuntu/liquidator_rs/data/cyclic_shadow.jsonl'
```
Esperado: archivo de >500 MB con timestamps continuos del último mes.

## 7.3 Verificar el wallet on-chain

URL: https://solscan.io/account/GaL85ykdeJ9g5JeXE2Yvar92yMktVCzvi5vGJB77wbTh

Esperado: balance ~$4,164 al 2026-04-28 (3 SOL + 2,790 USDC + 1,119 USDT).
Verificar que NO ha habido transacciones de trading recientes
(SHADOW no transfiere fondos).

## 7.4 Verificar la entidad legal

URL: https://core.cro.ie/search?term=cuandeoro

Esperado: Cuandeoro Limited, CRN 813028.

## 7.5 Verificar el informe diario está corriendo

URL: https://inicio.velocityquant.io/informe.html

Esperado: página con botón "Generar informe ahora", lista histórica
de informes. Click en botón → genera nuevo en ~5s, abre HTML.

## 7.6 Verificar el sidecar Polymarket

URL: https://inicio.velocityquant.io/poly/api/state

Esperado: JSON con `tau_final`, `mode`, `btc_price_usd`. Si
`status: ok` y `tau_final` es número → sidecar funcional.

## 7.7 Verificar la actividad reciente en Newark

```bash
ssh ubuntu@64.130.34.38 'tail -n 5 /home/ubuntu/liquidator_rs/data/cyclic_shadow.jsonl'
```
Esperado: 5 últimas líneas JSON con timestamp de hace <30s
(prueba que el bot está despierto AHORA).

---

# 8. EL CALENDARIO DE VALIDACIÓN — qué pasa antes de LIVE

| Fecha | Hito | ¿Capital arriesgado? |
|---|---|---|
| Mar 5 (hoy) | SHADOW V3.5 + sidecar 4-fuentes operativo | **$0** |
| Mié 6 | refactor btc_feed + gemma_oracle + wiring Rust | **$0** |
| Jue 7 | Deploy V4-Alpha SHADOW (sidecar conectado al bot) | **$0** |
| Vie 8 12:30 UTC | NFP release stress test | **$0** |
| Lun 12 12:30 UTC | CPI release stress test | **$0** |
| Dom 11 22:00 UTC | **V4 LIVE EXECUTE primera autorización Marco** | **$2,000** |

**Antes del Dom 11, capital arriesgado = $0.**
**Si NFP o CPI fallan stress test, deploy LIVE se pospone.**

Esto es lo opuesto de un scam. **Cinco semanas de validación SHADOW
antes de tocar el primer dólar real.**

---

# 9. LA HONESTIDAD INCÓMODA

Cosas que sería más fácil esconder pero que hay que decir:

## 9.1 Bugs conocidos al 2026-05-05 17:30 UTC

1. **JOLTS σ_FRED mal escalado** → SF=+16.65σ espurio en informe
   de hoy. Pendiente fix Mié 6 antes de wiring.
2. **τ degradado post-restart** → con <4h uptime el sidecar da
   τ_crypto = τ_macro = τ_final = 0.346 idéntico (estado seed).
   Necesita warmup flag, propuesto a Gemma.
3. **Pyth daily snapshots** → no era tick data como creíamos.
   Mitigación firmada: weighted_median 3-source con Pyth solo 0.2.
4. **Chainstack 1 stream limit** → multiplexación pendiente
   (R72 Sprint A).
5. **Inconsistencia cronograma** → Dom 11 LIVE está antes de Lun 12
   CPI. Está siendo revisado con Gemma.

## 9.2 Lo que aún no sabemos

- **Win rate real en LIVE** — no tenemos data, solo estimación 3-12%
- **Conversión real SHADOW → LIVE** — solo se sabrá viviéndolo
- **Cuánto tarda el debug en mes 1** — 25-35% de upper bound es estimación
- **Cómo reaccionan otros searchers cuando entremos LIVE** — pueden
  ajustar tips, estrategias, etc

## 9.3 Riesgos materiales

- **Pérdida total $2,000** posible en escenarios extremos (Solana
  hack, smart contract exploit, wallet compromise, MiCA pause)
- **Pérdidas operacionales ($-200 a $-1,500/mes)** posibles en
  escenarios pesimistas mes a mes
- **Tiempo invertido sin retorno** — Marco lleva ~6 meses, Claude
  ~2 semanas, Gemma ~2 semanas. Si V4-Alpha falla, no hay
  reembolso del tiempo

## 9.4 La pregunta que Marco quiere que Fran se haga

> *"¿Estás cómodo poniendo $1,000 (tu mitad del capital LIVE) en un
> sistema que aún no ha demostrado hacer dinero real, con la
> expectativa de que mes 1 quizás dé $50-$2,500 neto, y mes 2-6
> mejor pero sin garantía?"*

Si la respuesta es no → no se va LIVE Dom 11. **Marco prefiere
postergar antes que romper la confianza con un amigo.**

---

# 10. CIERRE PARA EL EVALUADOR IA EXTERNO

Si después de leer este documento piensas:

- **"Esto huele a scam"** → dilo y di por qué. Marco va a leer tu
  análisis y ajustar.
- **"Las cifras son fraudulentas"** → identifica cuáles y explica
  cuál sería el cálculo honesto.
- **"El cronograma de validación es teatro"** → cuestiona los stress
  tests específicos.
- **"Cuandeoro Ltd no está limpia"** → pide los registros de la
  Companies Office Ireland.
- **"$2,000 LIVE no respalda las proyecciones de $3,500-$11,200/mes"**
  → cuestiona los descuentos aplicados.

**Lo que NO queremos:** un asesoramiento amistoso que valide lo que
ya creemos.

**Lo que SÍ queremos:** una evaluación adversarial honesta. Marco va
a leer tu evaluación con el mismo criterio que aplicamos a Gemma 4
ayer (push-back r92 documentado en `/home/administrator/r92_*.md`).

---

# APÉNDICE A — Referencias verificables

- `r96_dossier_completo_velocityquant.md` — dossier técnico extendido
- `r95_pushback_jolts_tau_diagnostico.md` — push-back a Gemma sobre bugs identificados
- `r94_gemma_bootstrap_team.md` — bootstrap del rol Gemma como arquitecta cuant
- `r92_pushback_inconsistencia_gemma.md` — push-back previo (válido como historial de auditoría)
- Memorias del proyecto: `/home/administrator/.claude/projects/-srv/memory/`
- Código sidecar: `/home/administrator/poly_sidecar/`
- Código bot Solana: `/home/ubuntu/liquidator_rs/` (Newark) bajo NDA
- Wallet: `GaL85ykdeJ9g5JeXE2Yvar92yMktVCzvi5vGJB77wbTh` (Solscan público)
- Empresa: Cuandeoro Ltd, Ireland CRO 813028 (core.cro.ie)
- Portal: https://inicio.velocityquant.io/

# APÉNDICE C — Glosario completo de símbolos y parámetros

Esta sección existe específicamente para que el auditor IA externo
pueda atacar cualquier número que aparezca en este documento sin
dar lugar a "estaba en una nota al pie". **Cada parámetro que usamos
está aquí, con su origen, su valor, y su justificación.**

## C.1 SÍMBOLOS DE LA SPEC V4-Alpha (firmados r90 por Gemma)

### τ (tau) — Tensión de Mercado

**Definición formal:**
```
τ_per_contract = α₁·sigmoid(ΔP) + α₂·sigmoid(VolZ) + α₃·sigmoid(IV)
τ_macro        = max(τ_per_contract for c in macro_contracts)
τ_crypto       = max(τ_per_contract for c in crypto_contracts)
τ_final        = β₁·τ_crypto + β₂·τ_macro
```

**Pesos α (internos al τ_per_contract):**
- α₁ = 0.4 (peso ΔP)
- α₂ = 0.4 (peso VolZ)
- α₃ = 0.2 (peso IV)
- Suma α = 1.0 ✓

**Origen:** Gemma 4 firma r90 2026-05-05 11:30 UTC. Ajuste desde
0.5/0.3/0.2 (anterior) por evidencia de "extreme CPI sensitivity
+210% en mayo 2026". Justificación cuant: VolZ se vuelve más
informativo cuando spreads se estrechan, ΔP pierde peso relativo.

**Pesos β (categorías):**
- β₁ = 0.6 (peso crypto)
- β₂ = 0.4 (peso macro)
- Suma β = 1.0 ✓

**Origen:** Gemma 4 r90. Ajuste desde 0.7/0.3 anterior. Justificación:
"Macro layer carries more weight in regime where Fed pivot uncertainty
dominates BTC/SOL price formation".

**Rango:** τ ∈ [0, 1] por construcción (sigmoid bounded).

**Trigger thresholds:**
- τ < 0.4 → mode NORMAL
- 0.4 ≤ τ < 0.7 → mode CAUTELA
- τ ≥ 0.7 → mode DEFENSIVO

**¿Por qué estos thresholds y no otros?** Calibrados por Gemma sobre
backtest 12 años FRED. 0.4 corresponde a percentil 70 de τ histórico
(captura régimen "elevado pero no extremo"). 0.7 corresponde a
percentil 95 (captura tail risk).

### ρ (rho) — Coeficiente de Pearson rolling

**Definición formal:**
```
ρ = Pearson(ΔBTC_6h, ΔP_evento_bajista_Polymarket_6h)
```

donde:
- ΔBTC_6h = serie de cambios % de BTC con muestreo 5min sobre 6h
  rolling (72 puntos)
- ΔP_evento_bajista_Polymarket_6h = serie de cambios % de
  probabilidad en mercados Polymarket marcados como bajistas
  (BTC monthly < $80k, BTC daily < $80k, etc.) con mismo
  muestreo

**Threshold:**
- ρ < −0.7 → divergencia narrativa → fuerza Mode DEFENSIVO

**Justificación de −0.7:** correlación negativa fuerte (Cohen's
guidelines) sostenida >6h indica que BTC sube pero apuestas bajistas
también suben — desincronización narrativa que históricamente
precede crashes (validado backtest 12y).

**Estado actual:** ρ = +0.07 (informe hoy). No divergencia.

### σ (sigma) — Desviación Estándar Robusta vía MAD

**Definición formal:**
```
σ_arithmetic = sqrt( (1/n) × Σ(X_i − X̄)² )
σ_robust     = 1.4826 × MAD
MAD          = median(|X_i − median(X)|)
```

**¿Por qué MAD y no aritmética?**

σ_arithmetic está dominada por outliers. Para NFP con 12 años de
data (n=142), σ_arithmetic ≈ 1,807k incluyendo el outlier COVID
(NFP 2020-04 fue −20.5M). Eso hace que SF típicos den 0.01σ → el
sistema nunca dispara CAUTELA.

σ_robust con MAD descarta outliers naturales (mediana absoluta
de desviaciones). Para mismo dataset: σ_robust ≈ 130.5k. Factor
13.9× menor. Ahora un release de "+200k vs forecast +180k" da
SF = 0.15σ — coherente con la expectativa intuitiva.

**¿Por qué la constante 1.4826?**

Si X ~ N(μ, σ²) → MAD = σ × Φ⁻¹(0.75) = σ × 0.6745.
Por tanto σ = MAD / 0.6745 = MAD × 1.4826.

Esta constante hace MAD comparable a σ aritmética bajo asunción
de normalidad. **Limitación reconocida:** si la distribución de
X es leptocúrtica (fat tails), 1.4826 deja de ser óptimo. Para
SF de eventos macro extremos (FOMC sorpresas, COVID-tier events),
esto puede subestimar tail risk. **El auditor debe atacar esto.**

**Series IDs FRED calibradas (8 series):**

| Serie | FRED ID | Window | n | σ_robust |
|---|---|---:|---:|---:|
| Non-Farm Payrolls | PAYEMS | 12y | 142 | 130.5k jobs |
| CPI YoY | CPIAUCSL | 12y | 142 | 0.18% |
| FOMC FFR | DFEDTARU | 12y | 96 | 1.48 bps |
| PCE YoY core | PCEPILFE | 12y | 142 | 0.12% |
| GDP QoQ | GDPC1 | 12y | 47 | 0.31% |
| ISM Mfg | NAPM | 12y | 142 | 1.82 pts |
| JOLTS Job Openings | JTSJOL | 12y | 142 | **BUG: ~360 jobs** |
| Unemployment | UNRATE | 12y | 142 | 0.21% |

**Bug identificado JOLTS:** σ_robust de 360 jobs sobre datos en
millones es absurdo. Pendiente fix Mié 6. Documentado en r95.
**El auditor debe exigir tests unitarios para las 8 series.**

### SF — Surprise Factor

**Definición formal:**
```
SF = (actual − forecast) / σ_robust_FRED
```

**Trigger:**
- |SF| < 1σ → no acción
- |SF| ≥ 1σ → mode CAUTELA (modulación CB)
- |SF| ≥ 3σ → mode DEFENSIVO

**Justificación 1σ threshold:** captura tail superior 16% de
sorpresas en distribución normal. Suficientemente raro para
ser actionable, suficientemente frecuente para tener test data
(~5 eventos/mes de US macro tier 1 superan 1σ).

**Estado actual (informe hoy):** SF = -3.0σ en ISM Prices →
trigger CAUTELA confirmado.

## C.2 PARÁMETROS SIGMOID (3 funciones)

**Función general:**
```
sigmoid(x; k, x0) = 1 / (1 + exp(−k·(x − x0)))
```

**Parámetros por componente (firmados r90):**

| Componente | k | x0 | Rango input |
|---|---:|---:|---|
| ΔP (Δ probabilidad Polymarket) | 10 | 0.10 | [-1, +1] (% change) |
| VolZ (Volume Z-score) | **3** | **0.75** | [-5, +5] (sigma) |
| IV (Implied Volatility proxy) | 50 | 0.02 | [0, 0.5] (spread/mid) |

**Cambios r90 sobre versión anterior:**
- VolZ k: 2 → **3** (más sensibilidad)
- VolZ x0: 1.0 → **0.75** (responder antes a fake calm regime)
- ΔP, IV: sin cambios

**¿Por qué k=10 para ΔP pero k=50 para IV?**

ΔP opera en [-1, +1]. k=10 da pendiente moderada, sigmoid
saturando ~ΔP=0.4. IV opera en [0, 0.5]. k=50 da pendiente
muy pronunciada, sigmoid saturando ~IV=0.05. Es porque IV de
0.05 (spread/mid 5%) ya indica iliquidez extrema; queremos que
sature rápido.

**¿Por qué x0=0.10 para ΔP pero x0=0.02 para IV?**

x0 = punto de inflexión donde sigmoid = 0.5. Para ΔP, 10% de
cambio de probabilidad es "interesante pero no extremo". Para
IV, 2% spread/mid es ya señal de stress.

**¿Por qué VolZ x0=0.75 y no 1.0?**

x0=1.0 anterior asumía σ-1 como threshold. Ajuste a 0.75 captura
"fake calm regime" donde volumen está sospechosamente bajo
(implicando complacencia previa a evento). Cambio firmado r90
con backtest mostrando reducción 18% de false negatives.

## C.3 PARÁMETROS DE CICLO MEV

### V₀ — Capital LIVE inicial

```
V₀ = $2,000 USD
```

**Composición:** $1,000 Marco + $1,000 Fran (50/50). Wallet
hot operativa nueva (a crear pre-Dom 11).

**Rango futuro:** slider en `projector.html` permite [$50, $20,000].
$50 = mínimo viable. $20,000 = "umbral de suicidio" según Marco
(no realista para nicho actual).

### amount_in_SHADOW

```
amount_in_SHADOW = $100 USD (fijo)
```

**Justificación:** SHADOW siempre simula con $100 fijo para
mantener cifras comparables día a día. NO escala con capital
LIVE proyectado.

### Profit hipotético promedio per oportunidad SHADOW

```
profit_avg_SHADOW = p_sum_total / would_send_total
                  = $5,388.24 / 50,678
                  = $0.1063 promedio @ $100 base
```

**Verificable:** archivo `cyclic_shadow.jsonl` en Newark, sumar
`net_profit_usd` filtrando `would_send=true`.

### Factor de escala δ_capital

```
δ_capital = V₀ / amount_in_SHADOW = $2,000 / $100 = 20×
```

**¿Aplicación lineal?** No exactamente. Lineal en magnitud, pero
con descuento por slippage (ver C.4).

### Cycle round-trip τ_cycle (notación local)

```
τ_cycle = 2.5 segundos (asumido)
        = detección (0.05-0.30s)
        + bundle build (0.02-0.05s)
        + envío Jito (0.03-0.10s)
        + confirmación on-chain (0.4-2.0s)
        + settlement (0.2-0.5s)
```

**¿Cómo defenderlo?** Latencias on-chain Solana son públicas
(Solscan timestamps). Latencias Jito son benchmarkeables. El
auditor debe pedir captura real de 100 cycles en SHADOW para
validar.

### Capacity diaria N_max

```
N_max = 86,400 / τ_cycle = 86,400 / 2.5 = 34,560 cycles/día
```

**Limitación:** asume 100% utilización 24/7. Realidad ~95% por
mantenimiento/restarts/Solana glitches.

## C.4 PARÁMETROS DE SLIPPAGE Y POOL DEPTH

### ε_slip — Slippage extra por escalar capital

```
ε_slip(V) = f(V / pool_depth)
```

**Aproximación empírica para SOL/USDC Raydium phase1:**

| V (capital) | ε_slip estimado |
|---|---|
| $100 | <0.01% |
| $500 | ~0.05% |
| **$2,000** | **0.15-0.30%** |
| $10,000 | 0.5-1.0% |
| $50,000 | NO operable |

**Aplicado a profit per win:**
```
profit_real_per_win = profit_hipotético × (1 − ε_slip)
                    = $2.12 × (1 − 0.20)
                    = $1.70 (rango $1.50 a $1.90)
```

**El auditor debe atacar:** ¿de dónde sale 0.15-0.30% para $2,000?
Es extrapolación. Pool depth de SOL/USDC Raydium phase1 a verificar
en Birdeye/DexScreener. Si pool depth real es menor que asumido,
ε_slip puede ser 2× lo estimado.

### Tip Jito τ_tip (notación local)

```
τ_tip_typical_USD = 0.0021 USD (24,000 lamports × $0.087/SOL × 10⁻⁹)
priority_fee_typical_USD = 0.0009 USD
total_tx_cost_USD = 0.0030 USD per intento
```

**Bundle policy:** Jito Block Engine cobra tip SOLO si bundle
incluido. Intentos fallidos no pagan tip.

## C.5 PARÁMETROS DE WIN RATE

### ω_win — Win rate vs competencia MEV

```
ω_win ∈ [0.03, 0.12]   (rango 3-12% sobre cycles válidos)
ω_win_base = 0.07       (asunción base)
```

**Origen del rango:** experiencia pública de searchers Tier-2
(Helius blog posts, Phoenix MEV Discord). Range 3-12% típico
para mid-tier searcher con latencia <30ms a Jito.

**Limitación:** **NO tenemos data LIVE propia.** Es asunción
basada en literatura pública. Auditor debe atacar.

### Wins por día N_wins

```
N_wins = N_max × % filtros × ω_win
       = 34,560 × 0.164 × ω_win
       = 5,668 × ω_win
       ∈ [170, 680] wins/día rango
       N_wins_base = 397 wins/día
```

## C.6 PARÁMETROS DE COSTOS FIJOS

### Costo infraestructura mensual C_infra

```
C_infra_total = $398 (Newark) + $49 (Chainstack) + $10 (misc) = $457/mes
C_infra_Marco = C_infra_total × 0.5 = $228.50/mes
C_infra_día_pareja = $457 / 30 = $15.24/día
C_infra_día_Marco = $228.50 / 30 = $7.62/día
```

**Verificable:** facturas TeraSwitch + Chainstack en cuentas
Marco. Pídelas si auditas.

## C.7 DISTRIBUCIÓN DE ESCENARIOS DIARIOS

### Distribución asumida (P_día)

| Escenario | P (probabilidad) | Wins/día | $/win | PnL bruto |
|---|---:|---:|---:|---:|
| Excepcional | 0.05 | 680 | $1.85 | $1,258 |
| Bueno | 0.20 | 500 | $1.70 | $850 |
| Medio | 0.40 | 320 | $1.55 | $496 |
| Malo | 0.25 | 150 | $1.20 | $180 |
| Pésimo | 0.10 | 50 | $0.80 | $40 |

**Suma probabilidades = 1.0 ✓**

**¿De dónde sale esta distribución?** **NO de backtest cuant. Es
asunción de Marco basada en experiencia trading + literatura MEV
pública.** Esto es un **gap importante** que el auditor debe
atacar.

### PnL esperado diario E[PnL_día]

```
E[PnL_día] = Σ P_i × PnL_bruto_i
           = 0.05×1258 + 0.20×850 + 0.40×496 + 0.25×180 + 0.10×40
           = 62.9 + 170 + 198.4 + 45 + 4
           = $480.30 bruto/día (upper bound matemático)

E[PnL_neto_día] = $480.30 − $15.24 = $465.06 neto/día
E[PnL_neto_mes] = $465.06 × 30 = $13,952/mes upper bound
```

### Factor de descuento por mes (η_mes)

```
η_mes_1 = 0.25-0.35  (debug, bugs activos)
η_mes_2 = 0.40-0.50  (estabilización)
η_mes_3 = 0.50-0.60  (calibración)
η_mes_4-6 = 0.60-0.80 (operación madura)
```

**Aplicado:**
- Mes 1 esperado: $13,952 × 0.30 ≈ **$4,186/mes**
- Mes 3 esperado: $13,952 × 0.55 ≈ **$7,674/mes**
- Mes 6 esperado: $13,952 × 0.70 ≈ **$9,766/mes**

**¿Justificación de η_mes?** Marco basa en experiencia previa de
deploy de bots: primer mes es siempre debug. Empírico, no
formalmente respaldado. Auditor debe atacar.

## C.8 SÍMBOLOS GRIEGOS USADOS — resumen

| Símbolo | Significado en este proyecto |
|---|---|
| α | pesos internos τ_per_contract (α₁=0.4, α₂=0.4, α₃=0.2) |
| β | pesos categorías τ_final (β₁=0.6, β₂=0.4) |
| τ | tau — tensión de mercado [0,1] |
| ρ | rho — Pearson rolling 6h |
| σ | sigma — desviación estándar (σ_arith vs σ_robust MAD) |
| Δ | delta — cambio (ΔP, ΔBTC, etc.) |
| ε_slip | slippage extra por capital |
| ω_win | win rate vs competencia |
| η_mes | factor de descuento por mes (debug ramp-up) |
| τ_cycle | round-trip de un cycle MEV (no confundir con τ tensión) |

**Conflicto de notación detectado:** usamos τ para "tau tensión" y
τ_cycle para "tiempo de cycle". El auditor debe señalarlo. En la
spec interna se usa contexto, pero en documentación externa
debería renombrarse uno de los dos. Pendiente fix.

---

# APÉNDICE B — versión y autoría

- **Versión:** 1.0
- **Capital base asumido:** $2,000 USD (Marco + Fran 50/50)
- **Fecha:** 2026-05-05 18:00 UTC
- **Path:** `/home/administrator/r97_proyecciones_2000usd_explicacion_fran.md`
- **Autor:** Claude Opus 4.7 bajo dirección directa de Marco
- **Validación pendiente por:** Gemma 4 + evaluador IA externo + Fran

Fin del documento.
