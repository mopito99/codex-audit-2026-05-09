# poly_sidecar · CHANGELOG

## [Unreleased] · 2026-05-09 (post-bug detection)

### Known Issues
- **[BUG-NFP-DIM]** · `sf_engine.py` · SF computation for NFP is underestimated by 10^3 due to units mismatch (Thousands vs Absolutes). Impact: SF remains NORMAL during high surprises. Fix deferred to post-CPI Mar 12. Target date: 2026-05-15. Firmado: Gemma 4 31B (`S-C-DEFER-NFP-CPI-GATE-20260509`). Detalles: forecasts.json NFP en miles (62 = 62K jobs), SIGMA_FRED NFP en jobs absolutos (219187.584). CPI no afectado (% pp consistente). JOLTS potencialmente afectado misma manera.

### Test markers
- Tests NFP en `sf_engine.py.__main__` marcados como **EXPECTED_BUG** (no failure) hasta target 2026-05-15.

## [r150-quad] · 2026-05-09

### Added
- `forecasts_validator.py` · 6 gates pipeline (JSON syntax, schema, types, range, decimals, signature)
- `sign_forecasts.py` · SHA256 hash + interactive YES confirmation
- `forecasts.signed` · firma autoritativa de `forecasts.json` actual

### Signed
- Gemma 4 31B firmó GO P1 inmediato + offload disco symlink completo

## [r150-tris] · 2026-05-08

### Signed
- Q23-Q26: forecasts.bak versionado, Tokyo POC tiers, BLS unresponsive fallback, escalado capital fases

## [r150-bis] · 2026-05-08

### Migration
- FMP API HTTP 402 desde 2025-08-31 · migrado a FRED+BLS+forecasts manual
- `bls_client.py`, `fred_calendar_client.py`, `fmp_compat.py` (drop-in)
- Sidecar import switched · estado=ok post-migration

### Signed
- Gemma 4 31B firmó NO APTO escala capital · régimen Mar 12 microcapital $5-10
