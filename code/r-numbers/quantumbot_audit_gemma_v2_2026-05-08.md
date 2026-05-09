# Audit Gemma 4 31B · QuantumBot · 2026-05-08 (v2)

**Inferencia**: 132.6s · 3854 tokens · gemma4:31b A100 Dallas
**Source prompt**: /home/administrator/quantumbot_audit_prompt_v2.txt
**Source DB evidence**: /home/administrator/quantumbot_db_evidence_2026-05-08.json

---

## §1 Diagnóstico raíz

La causa raíz es una **combinación letal de H5 (Execution Block) y H3 (Training Deadlock)**. El bot se encuentra en un estado de "Zombi Operacional".

1.  **H5 (Causa de 0 Trades):** Existe una desconexión total entre la capa de decisión (`agent.act()`) y la capa de ejecución. El hecho de que haya **32,256 decisiones** pero **0 trades** en 7 días es la prueba irrefutable. El agente está emitiendo acciones (Long/Short/Hold), pero un *Risk Gate* o un error en el puente de ejecución en `engine.py` (probablemente entre la línea 1353 y la llamada al API de BingX) está descartando las órdenes antes de que lleguen al exchange.
2.  **H3 (Causa del Congelamiento):** El bot no ha entrenado desde el 22 de abril, pero el servicio arrancó el 23 de abril. Esto indica que `maybe_train()` (línea 417) no está disparando. Si el bot ha tomado 32k decisiones, ha superado con creces el `PPO_CHUNK_MIN_SAMPLES` (128). Por lo tanto, el problema no es la falta de datos, sino que el trigger temporal (`elapsed > PPO_CHUNK_UPDATE_EVERY_HOURS`) está roto o el timestamp de entrenamiento no se está reseteando/persistiendo correctamente tras el restart del servicio.

**Evidencia:** 
- `ppo_training_log`: Último update 2026-04-22.
- `service status`: Start 2026-04-23.
- `decisions_7d` (32k) $\gg$ `trades_7d` (0).

## §2 Validación universe Top 15 train / Top 5 trade

**Coherente, pero insuficiente.** 
Reducir el universo de trading a los 5 activos con mayor liquidez y menor ruido (BTC/ETH/BNB/SOL/XRP) es una decisión correcta para aumentar la densidad de señales y reducir la varianza del gradiente. Sin embargo, **esta optimización es irrelevante si el puente de ejecución está roto**. No sirve de nada optimizar el universo si el bot sigue siendo incapaz de enviar una orden al exchange.

## §3 Min_samples · valor sugerido

El problema **no es el valor de `min_samples`**, sino el trigger de `maybe_train()`. 
Con 32,000 decisiones en 7 días, el bot tiene muestras de sobra para entrenar cada 2 horas. 

**Sugerencia:** Mantener en **128**. 
Bajarlo a 32 o 64 solo aumentaría el riesgo de overfitting en chunks pequeños sin solucionar el hecho de que el proceso de entrenamiento no se está ejecutando. El foco debe estar en el *scheduler* del entrenamiento, no en el umbral de muestras.

## §4 Reward function

**Mal calibrada para el estado actual.**
El componente `Base: realized_r * 200.0` es el motor principal del aprendizaje. Al haber 0 trades cerrados, este componente es **0 constante**. 

El bot solo está recibiendo "migajas" de reward (patience bonus, HTF alignment, momentum). Esto crea un **colapso de política**: el agente aprende que la única forma de no recibir penalizaciones es hacer "HOLD" o emitir señales que el Risk Gate bloquea, ya que no hay feedback positivo real (PnL) que incentive la apertura de posiciones. 

**Cambio sugerido:** Implementar un *Unrealized PnL Reward* (mark-to-market) para que el bot aprenda la dirección del precio aunque la orden no se cierre, evitando que la señal de reward sea plana.

## §5 HITL-RL conectar pathology_taxonomy_v1

**Después del fix raíz.**
Conectar la taxonomía de patologías ahora sería añadir complejidad a un sistema que no puede ejecutar una orden básica. El riesgo es introducir ruido en el reward antes de saber si el bot es capaz de operar. 
**Riesgo:** Si se conecta ahora, podrías estar entrenando al bot para "evitar patologías" en un entorno donde el problema es un bug de software (puente de ejecución), no una patología de mercado.

## §6 Plan Fase 2 ranked

1.  **Fix Execution Bridge (Prioridad Crítica):** Auditar `engine.py` para identificar por qué las decisiones del agente no se convierten en órdenes en BingX (revisar Risk Gates y logs de error de API).
2.  **Fix Training Trigger:** Corregir la lógica de `maybe_train()` para asegurar que el ciclo de re-entrenamiento se active inmediatamente después de un restart del servicio.
3.  **Reset & Warm-up:** Limpiar los `.pt` congelados y ejecutar un entrenamiento intensivo con los datos de las últimas 36h antes de volver a modo live.
4.  **Universe Narrowing:** Implementar la restricción Top 5 Trade / Top 15 Train.
5.  **Reward Re-calibration:** Añadir el componente de *Unrealized PnL* para romper el estancamiento de la política.

## §7 Riesgos

1.  **Overfitting en Top 5:** Al reducir el universo, el bot puede especializarse demasiado en 5 activos y perder capacidad de generalización. 
    *   *Mitigación:* Mantener el entrenamiento en 15 activos para preservar la diversidad de patrones.
2.  **Explosión de Gradiente post-congelamiento:** Al re-activar el entrenamiento tras 16 días de inactividad con datos nuevos, el primer update podría ser violento.
    *   *Mitigación:* Usar un learning rate reducido ($\text{LR} \times 0.1$) para el primer chunk de entrenamiento.
3.  **API Rate Limiting:** El aumento de frecuencia de entrenamiento y el foco en pocos activos puede disparar el polling de Klines.
    *   *Mitigación:* Implementar un cache de datos compartido para los 5 activos principales.

## §8 Veredicto binario

**STOP first fix Execution Bridge & Training Trigger.**