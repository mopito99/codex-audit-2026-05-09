VelocityQuant — Avance sidecar Polymarket τ
============================================

Fecha: 2026-05-05 ~03:00 CEST
Por: Claude (auto mode)

---

## ✅ TODO completado en esta sesión

### Sidecar Polymarket
- 8 archivos en `/home/administrator/poly_sidecar/` con todas las fórmulas validadas por Gemma 4 (anoche)
- Test end-to-end con 8 contratos LIVE de Polymarket exitoso
- venv Python 3.12 con httpx + fastapi + uvicorn instalados

### CORRIENDO AHORA mismo (background del runtime)
- **Sidecar loop** cada 300s leyendo Polymarket → calculando τ → escribiendo `data/tau_state.json`
- **FastAPI dashboard** en `http://127.0.0.1:8090/`

### Dashboard web con ayuda (lo que pediste)
- Tarjetas grandes: τ_final / τ_crypto / τ_macro / ρ con tooltips explicando cada uno
- Tabla por contrato: Cat | Tipo | Mercado | τ | ΔProb | VolZ | IV | σ(ΔP) | σ(VZ) | σ(IV) | OK
- Headers de columna con tooltips explicando cada fórmula al hover
- Caja inferior con todas las fórmulas en formato monospace
- Auto-refresh cada 30s
- Colores: τ verde (<0.4), amarillo (0.4-0.7), rojo (>0.7) | ΔProb verde si positivo, rojo si negativo
- Footer con errores por endpoint + último error + timestamp

### Cron Tokio Close programado
- Job ID `63bd08a2` (session-only)
- Dispara **05:57 UTC = 07:57 CEST** (3min antes del cierre)
- Acción: `tokio_close_report.py` → lee state → construye brief → envía a Gemma vía bridge → guarda respuesta en MD
- Tras Gemma, verifico V3.5 + dashboards y te dejo resumen ejecutivo

### Cálculos verificados con datos reales
```
τ_final = 0.3632   τ_macro = 0.3468   τ_crypto = 0.3702
8 contratos evaluados, todos valid=true

[macro ] τ=0.347 | Fed Decision in June?
[macro ] τ=0.301 | Fed rate cut by June 2026 meeting?
[macro ] τ=0.341 | April Inflation US - Annual
[macro ] τ=0.258 | How high will inflation get in 2026?
[crypto] τ=0.367 | What price will Bitcoin hit in May?
[crypto] τ=0.226 | Bitcoin above ___ on May 5?
[crypto] τ=0.370 | What price will Solana hit in May?
[crypto] τ=0.226 | Solana above ___ on May 5?
```

---

## ⬜ Cómo VER el dashboard

El dashboard está en `http://127.0.0.1:8090/` del server Dallas. Tres opciones:

**Opción A — SSH tunnel (sin tocar nada):**
```bash
ssh -L 8090:127.0.0.1:8090 administrator@<dallas-ip>
# después en tu navegador local: http://localhost:8090
```

**Opción B — Exponer vía nginx (requiere tu OK):**
- Crear `poly.mbottoken.com` → nginx proxy 127.0.0.1:8090 + Certbot SSL
- O añadir path en dominio existente: `https://plsbitunix.mbottoken.com/poly` → 127.0.0.1:8090
- Ambas requieren modificar `/etc/nginx/sites-enabled/`

**Opción C — Integrar al unified dashboard que ya tienes**
- Si tu unified dashboard tiene módulos, añadir uno nuevo "Polymarket τ"
- Embed iframe o fetch directo a /api/state

¿Cuál prefieres? Si dices "B con poly.mbottoken.com" lo monto en 5min con tu OK.

---

## ⬜ Pendiente Rust (NO tocado todavía)

Modificación V4-Alpha (no V3.5 LIVE) para leer `tau_state.json`:

```rust
// En el dispatch loop, cada cycle leer:
fn read_tau_state() -> Option<TauState> {
    let raw = std::fs::read_to_string("/home/ubuntu/poly_sidecar/data/tau_state.json").ok()?;
    let state: TauState = serde_json::from_str(&raw).ok()?;
    let age = SystemTime::now().duration_since(UNIX_EPOCH).ok()?
                  .as_secs_f64() - state.heartbeat_ts;
    if age > 600.0 { return None; }  // stale → fallback Modo Cautela
    Some(state)
}

// Modular threshold y size:
let tau = state.tau_final;
let th_adj = max(2, th_after_macro - (tau * 6.0).floor() as u8);
let size_adj = size_after_macro * (1.0 - tau);
```

Lo metemos miércoles junto con cyclic_dispatch.rs + macro_layer.rs.
**Sólo en el backup V4-Alpha, NO en V3.5 LIVE.**

---

## ⏰ Próximos eventos auto

| Hora UTC | Hora CEST | Evento |
|---|---|---|
| 05:53 | 07:53 | Reloj original Tokio close (job `32d8b05b`) — verifico V3.5 |
| 05:57 | 07:57 | **Reporte auto a Gemma** (job `63bd08a2`) — envío τ + recibo respuesta |
| 06:00 | 08:00 | Tokio close ventana — sidecar sigue corriendo |
| 13:30 | 15:30 | NYSE Open — sidecar tendrá ~10h de histórico VolZScore acumulado |

---

## Decisiones que necesito de ti

1. **Exponer dashboard:** A (SSH tunnel) / B (nginx subdomain) / C (unified) — tu preferencia
2. **Sidecar persistente:** ahora corre en background del runtime de esta sesión. Si quieres que sobreviva a desconexiones de mi proceso, autorizar systemd unit (preparado en README, requiere sudo)
3. **Redis:** el file-store funciona bien. ¿Instalamos Redis Newark de todos modos para limpieza, o lo dejamos así?
4. **Mañana miércoles:** ¿OK con que arranque diseño Rust V4-Alpha (en backup, no LIVE) para integrar lectura de τ?

Yo respondo lo que decidas. Buena reunión Irlanda.
