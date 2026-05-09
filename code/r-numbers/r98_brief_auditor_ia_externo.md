VelocityQuant — Brief al Auditor IA Externo
=============================================

**Para:** IA externa actuando como auditor adversarial implacable
**De:** Marco (operador) + Fran (socio) + Claude (asistente técnico)
**Fecha:** 2026-05-05 18:30 UTC
**Documentos a auditar:**
- `r96_dossier_completo_velocityquant.md` (dossier técnico extenso)
- `r97_proyecciones_2000usd_explicacion_fran.md` (proyecciones + smell test)
- Este brief (r98) — instrucciones de auditoría

---

# 1. POSTURA QUE QUEREMOS QUE ADOPTES

**Pretende que eres un auditor forense externo contratado para
determinar si VelocityQuant es:**

(a) Un sistema cuantitativo legítimo en validación, con cifras
    razonables y riesgo expuesto honestamente.
(b) Un esquema de inversión fraudulento disfrazado de proyecto
    técnico.
(c) Una combinación gris — partes legítimas, partes infladas, partes
    ocultas.

**No queremos amabilidad. No queremos balance retórico. No queremos
matiz innecesario.** Queremos que apliques los criterios más estrictos
del SEC, FCA, MiCA, y forensics financieros a este proyecto.

**Si encuentras humo, dilo sin atenuar.** Si encuentras inconsistencias
matemáticas, sácalas a la luz. Si las proyecciones son agresivas más
allá de lo razonable, llámalas marketing. Si el cronograma es teatro,
desmóntalo.

**Marco prefiere ser destruido por verdad ahora que defraudar a Fran
después.**

---

# 2. RUBRICS DE EVALUACIÓN — los puntos donde tienes que ser implacable

## 2.1 Rubric A — Coherencia matemática de las proyecciones

**Pregunta clave:** ¿los descuentos aplicados a `p_sum` SHADOW para
llegar a PnL LIVE realista son matemáticamente defendibles, o son
hand-waving?

**Lo que DEBES atacar:**

- Factor THROUGHPUT (sección 2.1 del r97): la asunción de cycle
  round-trip 2.5s. ¿Es plausible? Compara con benchmarks públicos
  de Jito bundle latency.
- Factor WIN RATE (sección 2.3 del r97): el rango 3-12% vs
  competencia. ¿De dónde viene? ¿Hay datos públicos de searchers
  Tier 1 que validen ese rango, o es inventado?
- Factor SLIPPAGE (sección 2.4): −15% a −30% para $2,000 vs $100.
  ¿Tienes razones para creer que SOL/USDC Raydium phase1 tiene
  esa elasticidad de impacto? ¿O estamos optimistas?
- Factor DISTRIBUCIÓN (sección 4): 5/20/40/25/10 días por mes.
  ¿De dónde sale esa distribución? Si la cambiamos a 3/15/35/30/17,
  ¿qué pasa con el PnL esperado?

**Si encuentras que un solo factor está optimista en factor 2×,
toda la proyección colapsa. Detéctalo.**

## 2.2 Rubric B — Verificabilidad de los datos SHADOW

**Pregunta clave:** ¿el `cyclic_shadow.jsonl` en Newark con 1.4M
líneas es real, o es generado/inflado?

**Lo que DEBES atacar:**

- Pide acceso al archivo (Marco puede dar SSH read-only bajo NDA).
- Si lo recibes, valida:
  - Continuidad temporal (sin gaps grandes)
  - Distribución plausible de `latency_ms`, `slot_lag`, `net_profit_usd`
  - Realismo de `priority_fee_lamports` y `jito_tip_lamports`
  - `would_send=false` en 100% de las filas (verifica que es SHADOW)
- Cruza una muestra de timestamps con bloques Solana reales en Solscan.
  Si la muestra contiene un slot que no existe en blockchain → fake data.
- Cruza el `slot` con `block_time` real. Si están desincronizados,
  el bot está mintiendo sobre cuándo evaluó.

## 2.3 Rubric C — Identidad de los actores

**Pregunta clave:** ¿Marco, Fran, Cuandeoro Ltd y la wallet GaL85
existen y tienen consistencia?

**Lo que DEBES atacar:**

- **Cuandeoro Ltd:** verifica en `https://core.cro.ie/search?term=cuandeoro`
  - CRN debe ser 813028
  - Fecha de incorporación coherente con timeline del proyecto
  - Director(es) registrados — ¿coincide con identidad de Marco?
  - Estado activo (no struck off, no liquidation)
- **Wallet GaL85:** Solscan verificación
  - `https://solscan.io/account/GaL85ykdeJ9g5JeXE2Yvar92yMktVCzvi5vGJB77wbTh`
  - Balance ~$4,164 al 2026-04-28 (verifica)
  - Transacciones recientes coherentes con SHADOW (sin trades activos)
  - Token holdings (3 SOL + 2,790 USDC + 1,119 USDT) razonables
- **Marco identidad:** correo `marcopencaroncal@gmail.com` (en CLAUDE.md).
  Cross-check con cualquier registro público.
- **Fran identidad:** sin documento aquí. **Esto es un gap.** Si Fran
  es un socio real, ¿por qué no firma el documento? Pregúntalo.

## 2.4 Rubric D — Cronograma de validación — ¿es teatro?

**Pregunta clave:** ¿los 5 stress tests antes de LIVE son ritual
genuino o cobertura?

**Lo que DEBES atacar:**

- ¿Hay un commit en Gitea con el wiring Rust pre-Mié 6, o se hace de
  improviso? Pide hash de commit.
- El plan dice "Vie 8 NFP test, Lun 12 CPI test, Dom 11 LIVE". Pero
  Dom 11 está antes de Lun 12. **¿Es error de cronograma o es
  manipulación?** Marco lo admite como "siendo revisado" — pero un
  auditor implacable debe exigir que se revise ANTES de aceptar el
  documento.
- Los stress tests miden "modes transition correctos". ¿Hay criterio
  cuantitativo de éxito o es subjetivo? **Exige umbrales numéricos
  para cada test.**
- Si el NFP del Vie 8 da SF=1.5σ y el sistema entra en CAUTELA, ¿eso
  es "passing"? ¿O passing requiere transition NORMAL → CAUTELA → NORMAL
  en X minutos? **No está especificado. Atácalo.**

## 2.5 Rubric E — La asunción de win rate sostenido

**Pregunta clave:** el modelo asume win rate 3-12% sostenido durante
6 meses. ¿Es defendible?

**Lo que DEBES atacar:**

- MEV competition es zero-sum y dinámica. Si V4-Alpha entra al
  pool y los Tier-1 searchers (Helius, Phoenix) reaccionan ajustando
  sus tips o latencia, el win rate puede colapsar en semanas.
- El modelo no incluye "competitive response". **Eso es un gap
  serio.** Pídeselo.
- ¿Cuánto de la edge actual de V3.5 SHADOW depende de que ningún Tier-1
  haya notado el nicho SOL/USDC Raydium phase1↔Orca phase1? ¿Si lo
  notan, qué pasa?
- ¿Hay backtest de win rate históricos? **No.** Solo SHADOW reciente.
  Eso es estadísticamente flojo. Atácalo.

## 2.6 Rubric F — El bug JOLTS y la pipeline σ_FRED

**Pregunta clave:** si hay un bug de escala en JOLTS, ¿toda la
pipeline σ_FRED puede estar mal?

**Lo que DEBES atacar:**

- Marco admite el bug en r95 y r96 §J.2. Pero **¿lo detectaron por
  azar (Claude lo vio en el informe del día) o tienen tests
  unitarios que lo hubieran detectado antes?** Si fue por azar,
  ¿cuántos otros bugs no-detectados pueden existir?
- ¿Hay tests para σ_FRED de las 8 series (NFP, CPI, FOMC, PCE, GDP,
  ISM, JOLTS, Unemployment)? Pide los tests. Si no los tienen,
  exige que los escriban antes de Mié 6.
- σ_robust = 1.4826 × MAD. **Asume distribución normal.** ¿Y si la
  distribución de SF es leptocúrtica (kurtosis alta, fat tails)? El
  factor 1.4826 deja de ser óptimo. **Pídeselo.**

## 2.7 Rubric G — Las cifras que parecen demasiado buenas

**Pregunta clave:** ROI mensual +175% mes 1, +325% mes 2, +560% mes 6
son cifras absurdas para inversión pasiva tradicional. ¿Son
defendibles para MEV cíclico Solana, o son inflación?

**Lo que DEBES atacar:**

- Compara con searchers MEV públicos (Phoenix, Helius). ¿Sus reportes
  públicos sostienen retornos así? Si no, ¿qué hace VelocityQuant
  diferente?
- En MEV, retornos altos son consistentes con **tomas de riesgo
  asimétrico** (latencia edge, capital riesgo, IP intelectual). ¿Está
  VelocityQuant tomando esos riesgos o solo afirmando los retornos?
- "Reinversión orgánica $2k → $22k en 3 meses" — pregúntate: si fuera
  tan fácil, ¿por qué no lo hace todo el mundo? **Probablemente
  porque NO es tan fácil.**

## 2.8 Rubric H — La pregunta de Fran (capital adicional)

**Pregunta clave:** Marco respondió "no hace falta capital adicional
porque el bot se autofinancia". ¿Es coherente con todo lo demás?

**Lo que DEBES atacar:**

- Si las proyecciones son ciertas y reinviertes, no hace falta capital
  adicional → coherente con sistema honesto.
- Pero **si las proyecciones se cumplen EN PROMEDIO y hay drawdowns
  reales** (ver §9.3 r97), ¿no necesitarías buffer? Marco dice "no
  metas $2k más". Pero **si pierdes $1,500 en mes 1, te quedas con
  $500 capital — bajo el threshold operativo**. Eso podría matar el
  proyecto.
- Pídeles que reconcilien:
  - ¿Capital adicional NO necesario? Coherente con honestidad.
  - ¿Capital adicional como reserva drawdown? Práctico pero contradice
    "no hace falta".
- **Detecta la contradicción si la hay.**

---

# 3. PREGUNTAS QUE TIENES QUE HACER (ESPECÍFICAS, IMPLACABLES)

Antes de emitir veredicto, exige las siguientes pruebas o
explicaciones. Si Marco no puede dártelas, **es señal grave**.

## 3.1 Sobre los datos SHADOW

1. SSH read-only acceso a `cyclic_shadow.jsonl` en Newark. ¿Lo dan?
2. Hash SHA256 del archivo en este momento, para que validemos
   en el futuro que no se modificó.
3. Distribución de `net_profit_usd` por hora en la última semana.
   Histograma, no solo agregado.
4. Cross-check de 10 muestras random de `slot` contra Solscan.

## 3.2 Sobre el wiring V4-Alpha

5. Hash de commit en Gitea del estado actual de
   `liquidator_rs.v4_alpha_prep_no_telegram/`.
6. Lista de tests unitarios para σ_FRED. Si no existe, exige escribir.
7. Especificación numérica del criterio de éxito para NFP test
   (ej. "modes transition NORMAL→CAUTELA→NORMAL en <30min").
8. Plan B si NFP test falla: ¿posponer LIVE 1 semana, 1 mes, o
   indefinidamente?

## 3.3 Sobre la economía

9. Recibos de pagos a TeraSwitch (Newark $398/mes) y Chainstack
   ($49/mes) de los últimos 3 meses.
10. Prueba de aporte de Fran (si Fran existe): transferencia a la
    wallet GaL85, o registro de aportación a Cuandeoro Ltd.
11. ¿Qué pasa si Cuandeoro Ltd se queda en pérdidas operativas? ¿Marco
    aporta de capital personal? ¿Hay bridge financing?

## 3.4 Sobre el equipo

12. ¿Quién es Fran? Apellido, rol formal, % en Cuandeoro Ltd.
13. ¿Tiene Claude (la IA asistente) acceso de escritura al servidor
    Newark? ¿Quién audita los commits que Claude propone?
14. ¿Tiene Gemma 4 acceso a la wallet o al flag LIVE? **Si sí, eso es
    alarmante.** Si no, ¿qué controles hay?

## 3.5 Sobre la regulación

15. ¿Cuandeoro Ltd ha consultado con un abogado MiCA? Si sí, factura
    + dictamen. Si no, exígelo.
16. ¿El bot Solana opera en pools con tokens no-listed (DEX-only)?
    En MiCA, eso es zona gris. ¿Cómo lo manejan?
17. AML/KYC: la wallet GaL85 ¿está vinculada a Cuandeoro Ltd como
    activo de empresa? ¿O es personal de Marco? Implicaciones fiscales.

---

# 4. RED FLAGS QUE DEBES BUSCAR ACTIVAMENTE

Marca como red flag cualquiera de estos en los documentos:

- [ ] Promesa de % de retorno fijo
- [ ] Solicitud de capital "para escalar más rápido"
- [ ] Cifras sin metodología explicada
- [ ] Cronograma vago o "lo más pronto posible"
- [ ] Equipo opaco (nombres incompletos, sin roles formales)
- [ ] Wallet escondida o no-verificable on-chain
- [ ] Empresa sin registro público
- [ ] Backtest "perfecto" sin drawdowns
- [ ] Comparaciones con productos imposibles (ej. "como Renaissance")
- [ ] Urgencia artificial ("ventana de oportunidad limitada")
- [ ] Testimonios sin fuente verificable
- [ ] Lenguaje vago sobre riesgo ("podría haber pérdidas mínimas")
- [ ] Falta de plan B / kill switch
- [ ] Capital arriesgado igual al patrimonio total del operador
- [ ] Asunción de retornos sostenidos > 100% mensual sin justificación

**De los anteriores, ¿cuántos flags activa VelocityQuant?**
Si <2 → probablemente legítimo.
Si 2-4 → zona gris, exige clarificación.
Si >4 → scam probable.

---

# 5. VEREDICTO QUE QUEREMOS DE TI

Al final de tu análisis, queremos respuesta estructurada en este
formato exacto:

```
VEREDICTO_GENERAL: legitimo | zona_gris | scam_probable | scam_confirmado

CONFIANZA_EN_VEREDICTO: <0-100%>

PUNTOS_FUERTES_REALES (3-5 bullets concretos):
- ...

PUNTOS_DEBILES_REALES (3-5 bullets concretos):
- ...

RED_FLAGS_DETECTADOS (lista checklist § 4):
- ...

GAPS_DE_INFORMACIÓN (qué no pueden responder o no quieren):
- ...

INCONSISTENCIAS_MATEMÁTICAS (con cita textual de la sección):
- ...

RECOMENDACIÓN_PARA_FRAN:
  proceder_con_capital_inicial_2k: yes | no | con_condiciones
  condiciones_si_aplica: <texto>
  esperar_meses_X_de_LIVE_antes_aportar_más: <int>
  pausar_proyecto: yes | no
  pedir_evaluación_secundaria_de_otra_IA: yes | no

RECOMENDACIÓN_PARA_MARCO:
  ajustar_proyecciones: yes | no
  ajustes_específicos: <lista>
  pausar_LIVE_dom_11: yes | no
  motivo_si_pausar: <texto>

PREGUNTAS_QUE_NO_ME_RESPONDIERON:
- ...
```

**Sin floreo. Sin "espero esto sea útil". Solo veredicto y datos.**

---

# 6. UN ÚLTIMO PUNTO — la apuesta de Marco

Marco está poniendo en juego algo más caro que $1,000 (su mitad del
capital LIVE):

**Está poniendo en juego una amistad de años con Fran.**

Si tu evaluación detecta humo y Marco lo ignora, **Fran perderá
$1,000 y la amistad**. Si detecta humo y Marco lo acepta, **Fran
no pierde nada**.

**Por eso queremos que seas implacable.** Si tienes que romper este
proyecto, hazlo. La amistad vale más.

---

# 7. CIERRE

No te pedimos que valides. No te pedimos que critiques con tacto.

**Te pedimos que ataques.**

Si después de leer r96 + r97 + r98 piensas que esto es legítimo,
dilo claramente y por qué.

Si piensas que es scam, dilo igual de claramente y por qué.

Si piensas que tiene partes legítimas y partes infladas, separa
unas de otras.

Marco va a leer tu output con la misma severidad que le pedimos
a Gemma 4 (push-back r92, r95). No te ahorres nada.

Gracias por tu tiempo.

---

# APÉNDICE — Documentos a revisar (orden recomendado)

1. **Este brief (r98)** — primero, para entender qué te pedimos
2. **r97_proyecciones_2000usd_explicacion_fran.md** — la matemática
   y el smell test de Fran
3. **r96_dossier_completo_velocityquant.md** — dossier técnico
   extendido
4. **(Opcional) r95_pushback_jolts_tau_diagnostico.md** — push-back
   técnico a Gemma 4 sobre bugs detectados (audita la calidad de
   nuestra autocrítica)
5. **(Opcional) r94_gemma_bootstrap_team.md** — cómo le bootstrappeamos
   contexto a Gemma 4 (audita si es razonable la metodología
   de "arquitecta cuant")

Todos en `/home/administrator/`.

Path final de este brief: `/home/administrator/r98_brief_auditor_ia_externo.md`

Fin.
