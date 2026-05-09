VelocityQuant — Análisis técnico BTC: TODO sale de ti
=========================================================

Para: Gemma 4
De: Marco
Fecha: 2026-05-05
Asunto: Prueba de autonomía cuantitativa. Análisis BTC multi-timeframe.
        Tú haces TODO — datos, niveles, narrativa y HTML final.

---

# QUÉ QUIERO

Un análisis técnico **completo** de BTC en 5 timeframes:

- **15m** — micro-estructura intra-día
- **1h** — TIMEFRAME PRIMARY (donde das soportes/resistencias/TP1/TP2/SL1)
- **4h** — swing intra-day
- **D** (Daily) — tendencia diaria
- **W** (Weekly) — macro

Y como entregable: **un único archivo HTML autocontenido** que pueda
guardar en `/home/administrator/btc_analysis.html` y abrir en el
navegador. Quiero ver:

1. Un gráfico interactivo de BTC del **sitio gratis y movible de Google**
   que ya conoces (tú decides el embed/widget exacto, lo importante es
   que sea de Google y se pueda hacer zoom + cambiar timeframe)
2. Análisis matemático tuyo justo debajo del gráfico
3. Soportes y resistencias destacados como niveles concretos en USD
4. Trade plan 1h: Entry, TP1, TP2, SL1 con razón técnica de cada nivel
5. Tendencia macro / intermedia / micro con justificación

---

# EL PUNTO DE LA PRUEBA

Marco quiere ver hasta dónde llegas tú **sola** sin que Claude meta nada:

- Datos OHLCV → tú los proporcionas / sugieres fuente
- Cálculos (RSI, ATR, swing highs/lows, MAs, niveles) → tú
- Soportes y resistencias → tú con USD concretos
- Razonamiento del setup → tú narrativa
- Embed gráfico Google → tú decides cuál
- HTML completo → tú lo escribes (Marco lo guarda y abre)

Claude **no mete nada**. Solo te pasa este brief y luego pega tu output
en un archivo. Es una prueba de **autonomía cuantitativa total**.

---

# FORMATO DE TU RESPUESTA

Devuelve **un único bloque de código HTML completo** (`<!doctype html>`
hasta `</html>`) que incluya:

- `<head>` con título, meta viewport, estilos CSS dark theme
- El embed del gráfico Google que tú elijas
- Sección de análisis técnico narrativo (HTML directo, sin JSON)
- Las 6 secciones obligatorias:

  1. **Lectura macro (W + D)** — tendencia macro, niveles psicológicos clave,
     régimen actual (acumulación / distribución / mark-up / mark-down)
  2. **Estructura intermedia (4h)** — patrón actual (HH/HL alcista, LH/LL
     bajista, rango), soportes/resistencias en 4h
  3. **Trade plan 1h** (PRIMARY) con:
     - Soporte 1, 2, 3 (USD concretos)
     - Resistencia 1, 2, 3 (USD concretos)
     - Entry sugerido (sesgo long/short justificado)
     - TP1 (target conservador) — precio + R/R
     - TP2 (target extendido) — precio + R/R
     - SL1 (stop loss) — precio + razón técnica
  4. **Confirmación 15m** — cómo el 15m confirma o desmiente el setup,
     trigger de entrada exacto
  5. **Risk management** — probabilidad subjetiva de éxito, tamaño de
     posición sugerido (% capital), invalidación del análisis
  6. **Lectura final 3 líneas** — resumen ejecutivo: qué hago hoy

---

**Constraints:**

- Todo en un solo archivo HTML autocontenido
- Sin dependencias locales — solo CDNs/embeds remotos del gráfico Google
- Sin JSON estructurado — narrativa Markdown convertida a HTML directo
- Tono matemático directo. Sin floritura ni "lean and lethal".
- Justifica cada nivel con la data de los timeframes
- Los precios deben estar en rangos plausibles del régimen BTC mayo 2026

---

# QUÉ HACE MARCO CON TU OUTPUT

1. Copia el HTML completo a `/home/administrator/btc_analysis.html`
2. Abre en navegador
3. Si funciona → la prueba sale ✅
4. Si no funciona (gráfico no carga, niveles vacíos, etc.) → debug

Es una prueba de capacidad. Fírmalo cuantitativamente.

Gracias.
