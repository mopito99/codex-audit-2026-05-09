# Código del advisor (sin integrar aún)
Guardado 2026-04-29. Para integrar DESPUÉS de validar que el bot básico aterriza bundles.

Pendientes:
- clmm_tick_traversal.rs — motor de traversal exacto
- tickarray_loader.rs — carga TickArrays de Orca/Raydium (NO usa Pubkey::from_str import)
- slippage_predictor.rs — predictor para long-tail
- sandwich_risk.rs — score probabilístico
- whale_detector.rs — necesita fix de filtrado por pool

Orden de integración cuando se valide el bot principal:
1. Slippage predictor (proteger long-tail)
2. TickArray loader + traversal (precision long-tail)
3. Sandwich filter (long-tail specifically)
4. Whale detector (anticipación)

NO integrar todo a la vez. Una pieza, validar, siguiente.
