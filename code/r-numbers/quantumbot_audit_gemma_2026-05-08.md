# Auditoría Gemma 4 31B QuantumBot · 2026-05-08 06:00 UTC

**Inferencia**: 84.8s · 2394 tokens · gemma4:31b A100 Dallas

---

Aquí tienes la auditoría técnica solicitada. Sin adornos, Marco. Los datos no mienten y el bot está en estado vegetativo.

## SECCIÓN 1 — Diagnóstico raíz

**Causa raíz: Colapso de Política por Inacción (Policy Stagnation).**

El bot no está "decidiendo" en el sentido humano; está ejecutando un bucle de inferencia sobre una política que nunca ha convergido. La razón técnica es que el agente ha caído en un **mínimo local de "No Hacer Nada"**. 

Dado que el `min_samples=32` nunca se alcanza, el proceso de entrenamiento (`ppo.fit()`) jamás se dispara. El bot está operando con la **política aleatoria inicial** (o una versión obsoleta). En un entorno de alta volatilidad (memecoins), una política aleatoria que no recibe actualizaciones de recompensa tiende a converger hacia la acción más segura para evitar penalizaciones: el "Hold" (no operar). Las 38,247 decisiones son simplemente el bot preguntando cada pocos segundos "¿Hago algo?" y la red neuronal respondiendo "No" basándose en pesos no entrenados.

## SECCIÓN 2 — Mismatch train symbols vs trade symbols

**Veredicto: Bug Fatal.**

Entrenar en BTC/SOL/ADA y operar en BONK/PEPE es un error conceptual grave. 
- **Dinámica de Precio**: BTC tiene una estructura de mercado institucional y tendencial. Las memecoins se mueven por liquidez fragmentada, hype y manipulación de ballenas (estocástica pura).
- **Volatilidad**: El modelo ha aprendido que un movimiento del 2% en BTC es significativo; en una memecoin, un 2% es ruido blanco. El modelo está "ciego" ante la escala de volatilidad de las smallcaps.

**Arreglo**: Sincronización inmediata del universo. El `training_universe` debe ser idéntico al `trading_universe`. No se puede transferir el aprendizaje de un activo de baja volatilidad a uno de volatilidad extrema sin un proceso de *Transfer Learning* muy específico, el cual no está implementado aquí.

## SECCIÓN 3 — Sample insufficiency

**Estado: Training Never Starts.**

Confirmado. Si el código requiere 32 muestras por símbolo para ejecutar un update y solo hay 10, el bot está en un bucle infinito de recolección de datos que nunca llega al entrenamiento.

**¿Por qué se reinicia `ppo_memory`?** 
Probablemente tienes un script de limpieza o un buffer circular que purga la memoria cada $X$ horas o al reiniciar el servicio, borrando las 10 experiencias antes de que lleguen a 32. Estás borrando la evidencia antes de que el bot pueda aprender de ella.

**Sugerencia de fix**: 
1. Reducir `min_samples` a 5 o 8 para forzar actualizaciones frecuentes en entornos de baja frecuencia de trade.
2. Cambiar la lógica de purga de memoria: no borrar hasta que el `ppo_training_log` confirme que el update se realizó con éxito.

## SECCIÓN 4 — Reward function

El reward actual es probablemente lineal (P&L bruto), lo cual es suicida en memecoins debido al *slippage* y los *spreads*. El bot ve una oportunidad, entra, y el spread se come la ganancia instantáneamente, generando un reward negativo que castiga la apertura de posiciones.

**3 cambios concretos para memecoins**:
1. **Slippage-Aware Reward**: Restar un costo fijo de transacción y un porcentaje de slippage estimado al reward de cada trade cerrado.
2. **Volatility-Normalized Reward**: Dividir el P&L por la volatilidad del activo (tipo Ratio de Sharpe) para que el bot no se asuste con los swings violentes.
3. **Time-Decay Penalty**: Aplicar una pequeña penalización negativa por cada vela que la posición permanezca abierta sin profit, forzando al bot a buscar trades rápidos (scalping) en lugar de hacer "bag holding".

## SECCIÓN 5 — Plan de acción 90-min

Para sacar al bot del coma hoy mismo:

1. **Alineación de Universo (Min 0-30)**: Cambiar la configuración de entrenamiento para que use exclusivamente los 16 símbolos de memecoins activos. Eliminar BTC, SOL, etc.
2. **Forzar Entrenamiento (Min 30-60)**: Bajar `min_samples` a 5 y reiniciar el servicio `profitlab_quantum_bot.service` para limpiar el buffer y forzar el primer `fit()` en menos de una hora.
3. **Reset de Pesos (Min 60-90)**: Borrar el modelo actual (que está contaminado con datos de BTC) e iniciar un entrenamiento desde cero (*Cold Start*) con la nueva configuración de símbolos y samples.

## SECCIÓN 6 — Veredicto brutal

**Es recuperable, pero solo si aceptas que el trabajo hecho hasta ahora es basura y empiezas el entrenamiento desde cero con los símbolos correctos.**