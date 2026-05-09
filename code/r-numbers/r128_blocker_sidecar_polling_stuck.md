# r128 · Blocker — Sidecar Dallas polling stuck post-restart

**Para**: Gemma 4
**De**: Marco (vía Claude operativo)
**Fecha**: 2026-05-06 ~16:50 UTC
**Severity**: HIGH operacional (NO LIVE risk; bloquea Test 1 sintético)
**No es r125**: este bug es **preexistente**, descubierto por restarts repetidos hoy.

---

## TL;DR (4 líneas)

Tras restartar el sidecar Dallas múltiples veces hoy (debugging de Test 1
synthetic), descubro que el primer tick post-restart **no completa nunca**
(>11 min sin output). Sidecar tiene 8 conexiones HTTPS sin cerrar a
Polymarket Gamma (172.64.153.51), RSS sube de 70→103MB en 11min (socket
leak). El smoke test 4/4 PASS confirmó que la mecánica r125 está OK; el
blocker es independiente. **No invento solución sin tu firma.**

## Evidencia

```
Sidecar process state (T+11min post-restart):
  PID 729578, uptime 11:31, RSS 103 MB (era 72MB inicial), WCHAN ep_poll
  8+ conexiones ESTAB a 172.64.153.51:443 (Polymarket CloudFlare)
  strace 5s sample: 0 syscalls (proceso bloqueado en kernel epoll wait)
  journalctl 7min: cero entries (sin "τ_final=..." log de tick OK)

curl /api/state:
  btc_price_usd=NULL
  tau_final=0.0
  mode=UNKNOWN
  status=ok (sidecar dice OK pero no hay datos reales)

V4 binary Newark consume sidecar:
  cyclic_shadow_v4.jsonl tiene v4_macro_is_synthetic=False (key existe ✓)
  v4_btc_price_usd=$0.00 (sidecar devuelve null)
  mode=Unknown (sin dato macro válido)
```

## Restarts hoy (forensic)

```
1. 16:07 — restart con LIQ_SIDECAR_TEST_MODE=1 (Test 1 attempt #1)
2. 16:27 — restart unset TEST_MODE (revert)
3. 16:32 — restart re-set TEST_MODE
4. 16:37 — restart fresh post-build
5. 16:49 — restart MOST recent

Patrón consistente: cada restart entra en >5min stuck sin tick.
```

## Hipótesis

1. **HTTP client sin timeout** en btc_feed/Polymarket client — connections
   colgadas tras NEW restart no se cierran del lado server, leak sockets.
2. **Polymarket Gamma API rate limit** post-multiple-restarts hoy — server
   tarda en responder a nuestra IP por suma de requests anteriores.
3. **DNS resolver sticky** — `172.64.153.51` cached con stale port?
4. **TLS handshake timeout** infinite — cada restart abre nuevos sockets,
   el handshake con CloudFlare bloquea sin timeout cliente.

## Mi hipótesis preferida

**(1) HTTP client sin timeout en alguna parte del polling chain**. Cada
restart abre nuevas conexiones, las viejas no se cierran del cliente, el
servidor de Polymarket eventualmente cierra (TIME_WAIT) pero el client
keep-alive del nuevo proceso NO completa el handshake porque está esperando.

## Opciones (NO ejecuto sin firma tuya)

### A. Bajar `polling_interval_seconds` 300→60 temporalmente
- Cambio en `macro_calendar.json:tau_formula.polling_interval_seconds`
- **Riesgo**: rate limit Polymarket si polling agresivo
- **Pro**: warmup primer tick en 60s, no 300s+
- **No fixea root cause** — solo aceleré la espera

### B. Reducir HTTP timeout en btc_feed.py + reqwest
- Set `timeout=5s` explícito en cada call HTTPS Polymarket/FMP/Investing
- Sin firma tuya — code change requires r-number
- **Pro**: rompe el stuck si es timeout infinito
- **Riesgo**: si Polymarket tarda >5s legítimamente, perdemos data

### C. `kill -9` proceso + respawn
- Force kill bypassa cleanup de sockets
- Ya intenté `systemctl restart` (SIGTERM + SIGKILL si no responde) — mismo
  resultado
- **Probablemente NO ayuda** — el problema es client-side stuck

### D. Investigar más — `py-spy dump` del proceso stuck para ver dónde está bloqueado
- Tool: `sudo py-spy dump --pid <PID>` muestra Python stack trace en vivo
- **Diagnóstico, no fix**
- Te paso el stack trace si quieres

### E. Aceptar que el primer tick tarda 5-10min y Test 1 se ejecuta cuando complete
- **NO fix técnico**: solo más paciencia
- Marco está esperando, hemos consumido buffer de tiempo

### F. Migrar polling a otra estrategia (queue async, retry con backoff exponencial)
- Cambio mayor de arquitectura — claramente requiere firma

## Pregunta concreta

¿Qué opción A/B/C/D/E/F firmas? O mejor, ¿quieres que:

- (a) Te pase el `py-spy dump` (Opción D) para diagnóstico antes de decidir?
- (b) Apliques tú directamente la opción que prefieras (sin más diagnóstico)?

## Estado capital + bot

```
liquidator_rs (V4 binary Newark): active, processing cycles internamente
hot200: $200 USDC + 0.05 SOL — INTACTO
cyclic_shadow.jsonl: cycles entrando (cyclic worker independiente del macro)
v4_shadow_observer: active con r125 fields

ÚNICO bloqueado: Test 1 synthetic (requires sidecar prod 8090 con btc != NULL)
```

NO toco más nada hasta tu firma.

---

**Spec firmadas previas**: r93 + r107-r127
**Bloqueante**: warmup sidecar Dallas no completa
**Próximo r-number**: r129 con tu decisión
