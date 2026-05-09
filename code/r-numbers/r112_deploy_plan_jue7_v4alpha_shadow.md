VelocityQuant — Deploy Plan Jueves 7 — V4-Alpha SHADOW Binary
================================================================

**Para:** Marco (operador) + autoarchivo
**De:** Claude (asistente técnico)
**Fecha:** 2026-05-06 ~10:00 UTC
**Spec-Commit reference:** firmas r93/r107/r108/r109/r110/r111 todas aplicadas
**Estado pre-deploy:** stack 5/5 services UP, burn-in T+1h 38min, ADP timer
                        programmed 12:14:30 UTC, dashboard NFP live.

---

# PRE-CONDICIONES (verificar antes de Jue 7 06:00 UTC)

```
✓ ADP capture ejecutó OK (12:15 UTC hoy)
✓ Burn-in 72h NO interrumpido (>0 events to risk_audit.jsonl)
✓ liquidator_rs V3.5 SHADOW corriendo continuo
✓ V4 Shadow Observer corriendo continuo
✓ Sidecar Polymarket NORMAL
✓ btc_consensus 3-source funcional (Coinbase + Kraken + Pyth)
✓ kill_switch logic en sidecar.py wired
✓ 17/17 tests pytest pass
```

Si CUALQUIERA falla → debug primero, NO deploy V4-Alpha.

---

# CRONOGRAMA JUE 7

## 06:00 UTC — Health check

```bash
# Stack status
ssh ubuntu@64.130.34.38 'systemctl is-active liquidator_rs solana-executor-rs vq-v4-shadow-observer'
sudo systemctl is-active vq-poly-sidecar.service vq-poly-api.service

# Burn-in progress
cat /home/administrator/poly_sidecar/data/burn_in_v4_start.json
# T+0: 2026-05-06T08:22:05Z
# T+24h: 2026-05-07T08:22:05Z (~ahora si Jue 7 08:22)

# Risk audit jsonl health
curl -sk -u gemma:$SECRET https://inicio.velocityquant.io/poly/audit/jsonl_size
```

## 07:00 UTC — Build V4-Alpha Rust binary

Working directory: `/home/ubuntu/liquidator_rs.v4_alpha_prep_no_telegram/`

```bash
ssh ubuntu@64.130.34.38

cd /home/ubuntu/liquidator_rs.v4_alpha_prep_no_telegram

# Verificar componentes V4-Alpha existentes
ls src/macro_state.rs        # ✓ HTTP polling sidecar (firmado r90/r107)
ls src/v4_alpha_gate.rs      # ✓ CB + MacroState wrapper (firmado r93)
ls src/cyclic_dispatch_v4.rs # ✓ Shadow logger paralelo (firmado r92)
ls src/bin/v4_shadow_observer.rs  # ✓ Existing observer

# Cargo build release
nice -n 19 /home/ubuntu/.cargo/bin/cargo build --release --bin liquidator_rs 2>&1 | tail -10

# Verify binary
ls -la target/release/liquidator_rs

# Cargo test ALL
nice -n 19 /home/ubuntu/.cargo/bin/cargo test --release --lib 2>&1 | tail -10
```

**Criterio de éxito:**
- Build OK
- `cargo test --release --lib` 129+ tests pass (incluye macro_state + v4_alpha_gate + cyclic_dispatch_v4)
- Binary size razonable (~100-200 MB)

## 09:00 UTC — Deploy V4-Alpha SHADOW como systemd service separado

**Spec firmada r111 §2:** subset deploy (NOT mirror full traffic). V3.5
SHADOW intacto. V4-Alpha corre paralelo.

```bash
# 1. Backup binary V3.5 actual
ssh ubuntu@64.130.34.38 'cp /home/ubuntu/liquidator_rs/target/release/liquidator_rs \
                         /home/ubuntu/liquidator_rs/target/release/liquidator_rs.bak_pre_v4alpha_$(date -u +%Y%m%dT%H%M%SZ)'

# 2. Copy V4-Alpha binary a directorio separado
ssh ubuntu@64.130.34.38 '
cp /home/ubuntu/liquidator_rs.v4_alpha_prep_no_telegram/target/release/liquidator_rs \
   /home/ubuntu/liquidator_v4_alpha/liquidator_v4_alpha
chmod +x /home/ubuntu/liquidator_v4_alpha/liquidator_v4_alpha
'

# 3. Crear systemd unit separado
sudo tee /etc/systemd/system/liquidator_v4_alpha.service > /dev/null <<'UNIT'
[Unit]
Description=VelocityQuant V4-Alpha SHADOW (subset deploy, firma r111 §2)
After=network-online.target liquidator_rs.service
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/liquidator_v4_alpha
EnvironmentFile=/home/ubuntu/liquidator_v4_alpha/.env
ExecStart=/home/ubuntu/liquidator_v4_alpha/liquidator_v4_alpha
Restart=on-failure
RestartSec=10s
StandardOutput=append:/home/ubuntu/liquidator_v4_alpha/data/v4alpha.log
StandardError=append:/home/ubuntu/liquidator_v4_alpha/data/v4alpha.log
Nice=5
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
UNIT

# 4. Enable + start
sudo systemctl daemon-reload
sudo systemctl enable liquidator_v4_alpha.service
sudo systemctl start liquidator_v4_alpha.service
sleep 8

# 5. Verify status
sudo systemctl status liquidator_v4_alpha.service --no-pager | head -10
```

**Criterio de éxito:**
- Service active (running)
- Logs sin errores críticos
- Yellowstone Stream 3 establecido (firma r111 §2b)
- HTTP poll a sidecar funcionando (cada 10s)
- cyclic_shadow_v4_alpha.jsonl creciendo

## 10:00 UTC — Tests integración 13 escenarios (mock spike)

```bash
# Tests pytest desde Dallas (ya implementados)
cd /home/administrator/poly_sidecar
venv/bin/python3 -m pytest tests/test_kill_switch.py -v

# Esperado: 17/17 PASS (8 base + 5 BS + 4 deps)

# Cargo tests Rust desde Newark
ssh ubuntu@64.130.34.38 '
cd /home/ubuntu/liquidator_rs.v4_alpha_prep_no_telegram
nice -n 19 /home/ubuntu/.cargo/bin/cargo test --release --lib 2>&1 | tail -5
'
```

**Criterio:** All tests PASS. Si falla cualquiera → rollback inmediato.

## 11:00 UTC — Dry-run validation con synthetic spike

Test final pre-NFP: inyectar BTC spike artificial al sidecar Dallas para
verificar que el bot V4-Alpha lo detecta + responde correctamente.

```bash
# Script dry-run (a crear): /home/administrator/poly_sidecar/dry_run_spike.py
# Inyecta secuencia BTC: estable → +3% spike → estable
# Verifica:
#   - kill_switch dispara
#   - mode = CRITICAL
#   - audit log forense per-source
#   - block_new_authorizations = true
#   - Auto-recovery NO se activa (window NFP no llegó aún)
```

## 12:00-21:00 UTC — Monitoring continuo

```bash
# Snapshots T+8/12/16/24h (firmado Gemma r92)
# Estos los genero automáticos:
#   T+8h ~ 16:22 UTC
#   T+12h ~ 20:22 UTC
#   T+24h ~ 08:22 UTC Vie 8 (justo 4h antes NFP)

# Para revisar manualmente cualquier momento:
curl -sk -u gemma:$SECRET https://inicio.velocityquant.io/poly/audit/run/v4_decision_latency | jq
curl -sk -u gemma:$SECRET https://inicio.velocityquant.io/poly/audit/run/btc_consensus_latency_p99 | jq
```

---

# PLAN ROLLBACK (si V4-Alpha falla en cualquier momento)

**Firma r111 §2:** rollback es trivial porque V4-Alpha corre como service
separado. V3.5 SHADOW intacto.

```bash
# Step 1: Stop V4-Alpha
ssh ubuntu@64.130.34.38 'sudo systemctl stop liquidator_v4_alpha.service'

# Step 2: Disable auto-restart
ssh ubuntu@64.130.34.38 'sudo systemctl disable liquidator_v4_alpha.service'

# Step 3: Verify V3.5 SHADOW sigue OK
ssh ubuntu@64.130.34.38 'systemctl is-active liquidator_rs'
# Esperado: active

# Step 4: Verify capital LIVE intacto
ssh ubuntu@64.130.34.38 'systemctl is-active solana-executor-rs'
# Esperado: active (NO afectado)

# Step 5: Logs forenses para post-mortem
ssh ubuntu@64.130.34.38 'sudo journalctl -u liquidator_v4_alpha --since "30 minutes ago" --no-pager > /tmp/v4alpha_crash.log'
scp ubuntu@64.130.34.38:/tmp/v4alpha_crash.log /home/administrator/poly_sidecar/data/

# Step 6: Generar post-mortem report
cat /home/administrator/poly_sidecar/data/v4alpha_crash.log | grep -iE "(error|panic|critical)" | head -20

# Step 7: Avisar a Marco + decidir si reset burn-in (firma r109 §3 decision tree)
```

**Tiempo total rollback: <2 minutos.**

---

# CRITERIOS NFP STRESS TEST (Vie 8 12:30 UTC)

Firma Gemma r91+ + r93 + r109. **PASS = todos los criterios AND:**

```
✓ scan_tick_duration p99 < 8000 ms (umbral HARD)
✓ back_pressure_drops == 0
✓ stream_reconnect_events == 0
✓ slot_lag p95 < 10
✓ V4-Alpha SHADOW no crashea durante el evento
✓ kill_switch dispara coherentemente si BTC se mueve >2.5%
✓ mode transitions correctos (NORMAL → CAUTELA / DEFENSIVO)
✓ audit log forense per-source presente
✓ Coherencia btc_consensus ↔ mode modulation (criterio Gemma)
```

**FAIL → reset burn-in 72h decision tree (firma r109 §3 A/B/C)**

---

# CRITERIOS LIVE EXECUTE (post Lun 12 CPI audit)

```
✓ NFP STRESS TEST 1 PASS (Vie 8)
✓ CPI STRESS TEST 2 PASS (Lun 12)
✓ Audit dashboard verificado por Gemma post-CPI
✓ Burn-in completo 72h (mínimo)
✓ Marco firma autorización explícita
✓ Marco ejecuta: LIQ_CYCLIC_EXECUTE_LIVE=true en .env de Newark
✓ Capital inicial: $300 (firma r97/r100/r107)
✓ Wallet: hot200 (firma r91+)
```

**Earliest realistic LIVE: Mar 13 / Mié 14.**

---

# DASHBOARD NFP — credenciales operativas

```
URL:      https://inicio.velocityquant.io/poly/audit/dashboard.html
User:     gemma
Pass:     WoArv9I8Xnc9LY/Cbpz4U2JQmfpr+PtTefRpSCZ2kZU=

Almacenado en: /home/administrator/.velocityquant_secrets/audit_dashboard_shared_secret.txt

Hardening:
  - HTTPS Let's Encrypt SSL
  - Basic Auth obligatorio (.htpasswd_audit, bcrypt $2y$05$)
  - Rate limit 10 req/min (anti brute-force, firma r111 §5)
  - Whitelist queries (no path traversal)
  - Reverse proxy nginx → 127.0.0.1:8090 FastAPI
```

---

# ARCHIVOS Y PATHS CLAVE

| Path | Propósito | Firmas |
|---|---|---|
| `/home/administrator/poly_sidecar/btc_feed.py` | 3-source consensus | r90/r107/r108/r109 |
| `/home/administrator/poly_sidecar/kill_switch.py` | Logic firmada | r93/r107/r108/r109/r110/r111 |
| `/home/administrator/poly_sidecar/sidecar.py` | Mode logic + HARD OVERRIDE | r92/r93/r107/r108 |
| `/home/administrator/poly_sidecar/risk_config.json` | Spec source of truth | todas |
| `/home/administrator/poly_sidecar/cpi_audit_format.py` | Audit format | r92/r93 |
| `/home/administrator/poly_sidecar/audit_queries/q_*.jq` | 7 queries jq | r110/r111 |
| `/home/administrator/poly_sidecar/tests/test_kill_switch.py` | 17 tests | r108/r110 |
| `/home/administrator/poly_sidecar/.githooks/pre-commit` | Audit trail | r109/r110 |
| `/home/administrator/poly_sidecar/data/risk_audit.jsonl` | Audit log | r92/r93/r110 |
| `/etc/nginx/sites-available/inicio.velocityquant.io` | Dashboard auth | r111 |
| `/etc/nginx/.htpasswd_audit` | Basic Auth credentials | r111 |

---

# CHECKLIST PRE-NFP (Jue 7 noche)

Antes de irte a dormir Jue 7:

```
□ liquidator_v4_alpha.service active (running) sostenido 12h+
□ V4 logs sin CRITICAL errors
□ cyclic_shadow_v4_alpha.jsonl creciendo (~1+ records/s)
□ btc_consensus 3-source healthy (p99 <2.5s)
□ Mode transitions registrados en risk_audit.jsonl
□ Dashboard NFP accesible + responde
□ Pre-commit hook activo en repo
□ Burn-in time >24h sin interrupciones
□ Marco confirma operativa pre-NFP
```

Si cualquier punto falla → debug NOW, NO esperar al NFP.

---

# CIERRE

V4-Alpha SHADOW deploy es **subset paralelo** a V3.5. Riesgo capital LIVE
en V4-Alpha = $0 (es SHADOW). V3.5 SHADOW + solana_executor_rs LIVE
intactos. Rollback trivial (systemctl stop). Burn-in 72h en marcha.
NFP Vie 8 será la primera validación REAL del kill_switch + macro layer
con datos en vivo.

Gemma dejó claro: *"No habrá más intervenciones de mi parte hasta la
revisión del Audit Dashboard post-NFP."*

Marco — confirma cuando estés listo para deploy Jue 7 06:00 UTC.

Path: `/home/administrator/r112_deploy_plan_jue7_v4alpha_shadow.md`
