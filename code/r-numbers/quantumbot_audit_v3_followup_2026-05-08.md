# Audit Gemma 4 31B v3 (followup CPPI hipótesis) · 2026-05-08

**Inferencia**: 84.7s · 2355 tokens

---

## §1 Diagnóstico refinado

El diagnóstico cambia radicalmente a **H6 (CPPI Floor Breach / Cushion Exhaustion)**. 

Se descarta H5 (Execution Block) y H3 (Zombie) porque la data de `paper_trades` confirma actividad hasta hace 48 horas y los `decision_logs` muestran que el bot sigue procesando señales y calculando riesgos (está "vivo" y "decidiendo").

**Evidencia específica:**
*   **Proximidad Crítica:** El `portfolio_value` de HBAR ($45.98) está a solo **$0.98** del `cppi_floor` (45.0).
*   **Divergencia de Tamaño:** La existencia de un `safe_size` ($7-17 USD) frente a un `notional_usd` de $0.0 es la prueba irrefutable de que el motor de riesgo está aplicando un **filtro restrictivo posterior** al cálculo de volatilidad. 
*   **Estado de Cuenta:** El drawdown reportado (~8.10% en HBAR) ha erosionado el "cushion" (colchón) hasta un punto donde el multiplicador CPPI ya no puede generar una posición válida.

## §2 Por qué notional=0

El `safe_size` es el resultado de la función de *volatility targeting* (Línea 1048 de `engine.py`), que mira la volatilidad del activo y el capital total. Sin embargo, el `notional_usd` final es el resultado de la intersección entre el `safe_size` y el **CPPI Cap**.

**Mecanismo de fallo (Pseudocódigo basado en engine.py L1011-1048):**
1.  `cushion = portfolio_value (45.98) - floor_value (45.0) = 0.98`
2.  `cap = multiplier (ej. 3.0) * max(0.0, 0.98) = 2.94 USD`
3.  `final_notional = min(safe_size (15.0), cap (2.94))`
4.  **El Punto de Quiebre:** Si en el momento exacto del tick el `portfolio_value` cae a $\le 45.0$, el `max(0.0, cushion)` se vuelve **0.0**.
5.  Cualquier `safe_size` multiplicado o limitado por un `cap` de 0 resulta en `notional_usd = 0.0`.

El bot no está "roto", está **protegiendo el capital** según la regla estricta de CPPI: si el valor cae al suelo (floor), la exposición debe ser cero para evitar que la cuenta baje de ese límite.

## §3 Acción correctiva ranked

1.  **Ajuste de Parámetros de Riesgo (Inmediato):** Reducir el `cppi_floor` (ej. de 45.0 a 40.0) o incrementar el balance de la cuenta para restaurar el `cushion`. Esto reactivará la apertura de trades instantáneamente.
2.  **Implementación de Alerta de "Cushion Low":** Modificar `engine.py` para que cuando `cushion < (safe_size * 0.1)`, el bot emita un log crítico: `CRITICAL: CPPI Cushion exhausted, notional zeroed`.
3.  **Revisión de `risk/cppi.py`:** Verificar si existe un "minimum notional" que esté forzando el redondeo a 0 cuando el `cap` es muy pequeño (ej. si el cap es $2.94 pero el exchange requiere mínimo $5.00).

## §4 Veredicto

STOP first fix: Reducir `cppi_floor` o inyectar capital para restaurar el cushion.