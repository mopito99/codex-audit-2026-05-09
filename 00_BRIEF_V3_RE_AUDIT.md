# 00_BRIEF_V3 · Codex re-audit · post M1-bis + M2-bis (CRITICAL-NEW-01 + 02 fixed)

**Para**: Codex (OpenAI · agente externo)
**Fecha**: 2026-05-09 · 12:30 UTC
**Asunto**: V3 audit · validate cierre de los 2 críticos NUEVOS que detectaste en V2

---

## §0 · Contexto

V2 audit (commit `c398ba5`): detectaste 2 CRITICAL-NEW:
- **CRITICAL-NEW-01** · `/poly/` catch-all bypass → admin/health/random expuestos
- **CRITICAL-NEW-02** · BLS TTL bypass de M2 fix → cache 3600s mata SLA <120s

Marco + Gemma firmaron M1-bis + M2-bis P0 emergency · ambos implementados + verified.

---

## §1 · Cambios V3 vs V2

### M1-bis · Nginx Deny-by-Default

```nginx
# Specific auth (longest prefix wins)
location /poly/api/    { auth_basic ...; proxy_pass ...; }
location /poly/audit/  { auth_basic ...; proxy_pass ...; }
location /poly/pnl/    { auth_basic ...; proxy_pass ...; }

# Explicit deny ANTES catch-all
location /poly/admin/  { return 404; }
location = /poly/health { return 401; }
location /poly/metrics { return 401; }

# Catch-all con auth_basic
location /poly/ {
    auth_basic "VelocityQuant Restricted";
    auth_basic_user_file /etc/nginx/.htpasswd_vq;
    proxy_pass http://127.0.0.1:8090/;
}
```

Verify (8 curl tests): `/poly/admin/*` → 404, `/poly/health` → 401, catch-all → 401 sin auth · 200 con auth.

### M2-bis · BLS force_refresh

`bls_client.get_latest_actual(category, force_refresh=False)`:
- `force_refresh=True` → bypass cache + aggressive_ttl → llama BLS API HTTP
- Activado por sidecar durante `in_high_window` (T-30→T+15min)
- Quota math: ~390 calls/día evento day vs 500 daily limit · holgura 22%

Tests: 4 nuevos (`test_m2bis_force_refresh.py`) + 11 M2 regression = 15/15 PASS.

Verify empírico: 5×force_refresh=True → 5 BLS HTTP calls (cero cache hits).

### Bundle sanitization (Gemma orden)

- `balance_snapshots.jsonl` ELIMINADO
- `pnl.py` wallets `master/hot200` REDACTED a `<REDACTED-WALLET-PUBKEY>`
- `pnl_snapshot.log`, `api.log`, `sidecar.log` ELIMINADOS
- Refs en MDs y Rust/.env.template REDACTED a `<REDACTED-WALLET-MASTER>` / `<REDACTED-WALLET-HOT200>`

---

## §2 · Mission V3

1. Validar M1-bis cierra **CRITICAL-NEW-01** (ya no hay bypass `/poly/`)
2. Validar M2-bis cierra **CRITICAL-NEW-02** (force_refresh actually fuerza HTTP)
3. Detectar nuevos bugs introducidos por los fixes
4. Update veredicto LIVE Mar 22 (V2 fue 30% si LIVE actual · ¿ahora?)
5. Lista priorizada must-fix antes Mar 22 (M3-M8 status)

---

## §3 · Anexos en bundle (cambios vs V2)

```
code/poly_sidecar/sidecar.py             ← post M2-bis (force_refresh_bls=in_high_window)
code/poly_sidecar/bls_client.py          ← post M2-bis (force_refresh param)
code/poly_sidecar/fmp_compat.py          ← post M2-bis (propaga param)
code/poly_sidecar/Makefile               ← NEW · CI gate (pytest+gitleaks+whitespace)
code/poly_sidecar/tests/test_m2bis_force_refresh.py ← NEW · 4 tests
code/poly_sidecar/tests/test_polling_window.py ← M2 regression (11 tests)
configs/nginx/inicio.velocityquant.io    ← M1-bis Deny-by-Default
code/poly_sidecar/pnl.py                 ← SANITIZED (wallet pubkeys redacted)
code/poly_sidecar/data/balance_snapshots.jsonl ← REMOVED
code/r-numbers/r152_M1bis_M2bis_evidencia.md ← evidence post-fix
code/r-numbers/r152_codex_v2_response_gemma.md ← respuesta tu V2 audit
```

---

**Status target**: Mar 22 13:30 UTC LIVE microcapital · M3-M8 milestones pendientes.
