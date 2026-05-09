# BLS API Key · acción humana necesaria · 5 min

**Status**: BLOQUEANTE para CPI gate Mar 12 (Gemma firmó URGENTE en r150-novum)
**Fecha**: 2026-05-09 04:25 UTC
**Tiempo restante CPI gate**: 79h

---

## §0 · Por qué hace falta

Sin API key, BLS limita 25 requests/día por IP anonymous. Sidecar consume el límite en ~6h de polling continuo. Resultado: cuando llegue CPI Mar 12 12:30 UTC, BLS NO devolverá actual → SF=None → sello SF_reaccion_correcta = FALSE → gate falla → no microcapital LIVE.

Con API key registered (free): **500 requests/día** · más que suficiente para polling sostenido + ventana T-30min agresiva.

---

## §1 · Acción tuya · 5 minutos

### Paso 1 · Registrar (web form)

Abrir: **https://data.bls.gov/registrationEngine/**

Campos requeridos:
- Email (cualquiera tuyo)
- Org name (e.g. "VelocityQuant" o tu nombre)
- Agreement: aceptar terms

Receive en email: **Registration Key** (string ~36 caracteres)

### Paso 2 · Pasarme la key

Dos opciones:
- **A**: pégame la key en chat aquí · yo la guardo
- **B**: tú mismo creas el archivo:
  ```bash
  echo "TU_API_KEY_AQUI" > /home/administrator/.config/bls/api_key
  chmod 600 /home/administrator/.config/bls/api_key
  ```
  (`/home/administrator/.config/bls/` ya existe per `bls_client.py:62`)

---

## §2 · Lo que YO hago en paralelo

Mientras registras, implemento (sin restart sidecar):

### A. Polling LOW/HIGH frequency en sidecar.py
- `LOW_FREQUENCY` = poll cada 3600s (1h) cuando no hay evento próximo
- `HIGH_FREQUENCY` = poll cada 30s cuando `seconds_to_event < 1800` (T-30min)
- Guardrail: si BLS responde con rate-limit error, escala automáticamente cache TTL para ese símbolo

### B. Cache TTL agresivo en bls_client.py
- TTL standard: 5 min
- Si dato idéntico al previo: extender TTL a 1h (no consume request)

### C. Backup pre-edit + tests offline

Procedo y te doy MD r150-novum-update con código listo para restart cuando tú confirmes API key.

---

## §3 · Verificación post-key (cuando me la pases)

```bash
# 1. Save key
echo "<TU_KEY>" > /home/administrator/.config/bls/api_key
chmod 600 /home/administrator/.config/bls/api_key

# 2. Test directo
cd /home/administrator/poly_sidecar
./venv/bin/python3 -c "
from bls_client import BLSClient
cli = BLSClient()
print(cli.get_latest_actual('CPI'))
# Debe retornar dict con yoy_pct_change · NO null
"

# 3. Restart sidecar para que use key
sudo systemctl restart vq-poly-sidecar vq-poly-api

# 4. Verify fmp.status=ok
curl -s http://127.0.0.1:8090/api/state | python3 -c "
import sys,json; d=json.load(sys.stdin)
print(f'fmp.status: {d[\"fmp\"][\"status\"]} (esperado: ok)')
print(f'fmp.errors: {d[\"fmp\"][\"errors\"]}')
"
```

---

## §4 · Si NO quieres registrar API key (alternativa)

Existe fallback alternativo:
- Usar **FRED** como source primario para CPI (FRED tiene la series CPIAUCSL)
- FRED API key ya tenemos cargada (sin rate-limit issues)
- bls_client → fred_fallback en código

Coste extra: 1-2h dev para implementar el fallback. Bloquea P3.7.

**Recomendación honesta**: registrar BLS key (5 min) es 24x más rápido que implementar fallback FRED (2h). Tu decisión.

---

**Status mi parte**: Esperando tu key O tu OK para fallback FRED · meanwhile escribo código polling logic.

**Sello pendiente**: `MARCO-OK-BLS-API-KEY-<HASH-WHEN-RECEIVED>`
