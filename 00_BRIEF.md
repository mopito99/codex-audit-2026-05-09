# 00_BRIEF · VelocityQuant External Audit · 2026-05-09

**Para**: Codex (OpenAI · agente externo independiente)
**De**: Marco (operador) vía Claude Opus 4.7 (operativo Dallas)
**Bundle**: `codex_audit_2026-05-09.tar.gz`
**Endpoint**: `https://inicio.velocityquant.io/codex/codex_audit_2026-05-09.tar.gz`
**SHA256**: incluido en `SHA256SUMS` dentro del bundle
**Tiempo restante CPI gate**: ~78h (Mar 12 12:30 UTC release · Mar 12 13:30 UTC microcapital LIVE target)

---

## §0 · Mission (lee esto primero)

VelocityQuant lleva ~3 meses de construcción acelerada. El operador
(Marco) ha decidido exponer **capital real** ($5-10 microcapital) por
primera vez el **martes 2026-05-12 13:30 UTC**, condicional a que el
sistema pase 16 checks "StressPass" durante el release del CPI USA a
las 12:30 UTC ese mismo día.

Antes de exponer dinero, Marco quiere una **auditoría externa
independiente y brutalmente honesta**. Ya tiene a Gemma 4 31B (open
source local en A100 Dallas) como auditora interna firmando arquitectura
desde el r93 hasta el r150-undecim-quad. Pero Gemma firma con Marco y
con Claude (yo, el agente operativo que escribe código). **Existe sesgo
de equipo**.

Tu rol: **mirada externa, sin contrato emocional con el proyecto, sin
historial firmado, sin "queremos que esto funcione"**. Buscar
agresivamente lo que está mal.

### Reglas explícitas para tu output

1. **Brutal honesty obligatorio**. Sin diplomacia. Sin "looks good
   overall". Sin recomendar features nuevas. Solo evaluar lo existente.
2. **Cita evidencia**: cada finding con `file:line` + extracto del
   código relevante + impacto cuantificado donde sea posible.
3. **Si no puedes juzgar algo sin más info, dilo explícito** ("requiero
   ver X para evaluar Y"). Marco te hace llegar lo que falte vía Claude.
   No inventes.
4. **Si detectas que algo que Claude firmó como DONE en un MD no está
   realmente implementado en el código, flageaalo sin filtros**. Ese es
   uno de los puntos centrales del audit. Yo (Claude) ya detecté un
   caso en esta misma conversación (`[SAFETY-DIM]` assert) y lo
   reporté en `02_KNOWN_ISSUES.md`. Probablemente hay más.
5. **Sin "convencimiento"**. No hace falta validar el sistema. Si crees
   que NO está listo para LIVE, dilo. Si crees que sí, dilo. Cualquier
   ambigüedad es ruido.

---

## §1 · Contexto VelocityQuant (lo mínimo necesario)

### 1.1 · Tres actores · jerarquía decisional firmada

- **Marco** · operador humano · decisión final · autoridad
- **Gemma 4 31B** · open-source local Apache 2.0 · auditora senior
  (Ollama A100 Dallas) · firma arquitectura
- **Claude (Opus 4.7)** · agente operativo · escribe código
  con OK de Marco/Gemma · NO vota arquitectónicamente

Reference: `code/CLAUDE.md` (instrucciones permanentes para Claude).

### 1.2 · Qué hay en producción

| Componente | Estado | Capital | Track |
|---|---|---|---|
| **V4-Alpha cyclic SHADOW** (Solana Newark) | Running 2 días | $0 (paper) | Target Mar 12 LIVE |
| **V3.5 Liquidator LIVE** (Solana Newark) | Running ~1 mes | hot200 wallet activo | Legacy · diferente bot |
| **Polymarket sidecar τ** (Dallas) | Running · soak P3.6.5 | feeder señal | Hoy 05:40 UTC restart aplicado |
| **QuantumBot PPO** (BingX Dallas) | Paper trading | $0 | Diferente track · NO toca V4 |
| **Bot2 / Bot3 prime** (legacy HFT) | Running | ? | Pre-VelocityQuant · pendiente cleanup |

### 1.3 · El gate Mar 12 (cronograma)

```
Mar 11 23:59 UTC  · Pre-flight final
Mar 12 12:00 UTC  · Pre-CPI window · sidecar P3.6.5 entra HIGH_FREQUENCY (30s polling)
Mar 12 12:30 UTC  · CPI USA release · BLS API tiene <120s ventana para capturar actual
Mar 12 13:30 UTC  · Si 16 checks PASS → microcapital LIVE $5-10
                  · Si fail → rollback, NO LIVE, post-mortem
```

Los 16 checks están listados en `02_KNOWN_ISSUES.md`. **Tú decides si
son suficientes**.

### 1.4 · Track record reciente (lo bueno y lo malo)

**Bueno**:
- V4-Alpha SHADOW deploy Jue 7-may sin panics, RSS estable ~52 MB
- Migration de FMP (HTTP 402) a FRED+BLS+forecasts.json en 75 min Vie 8
- Validator con 6 gates + sign SHA-256 de forecasts.json (P1)
- SF Engine standalone con tests (P3)
- Disk offload sdb2 83→50% sin migración (per Gemma instruction)

**Malo**:
- **NFP gate FAIL** Vie 8-may 12:30 UTC. FMP empezó devolver HTTP 402
  por cambio pricing 2025-08-31. Yo (Claude) NO detecté `fmp.status=stale`
  en sweeps de status previos. Marco dijo: "yo qudo mal con mi socio".
  Ver `02_KNOWN_ISSUES.md` §2.
- **`[SAFETY-DIM]` assert** que el MD r150-sept (8-may 04:12 UTC) reportó
  como "DONE" nunca se aplicó al archivo. Detectado por mí mismo el
  9-may 05:30 UTC. Aplicado realmente en r150-decim. Ver §6 abajo.
- **BUG-NFP-DIM** detectado en SFEngine smoke tests (8-may): NFP SF
  computado en 0.0002σ vs esperado ~0.24σ por mismatch unidades
  (forecasts en miles vs SIGMA absolutos). Diferido fix a 2026-05-15
  per firma Gemma "Opción C".
- 3 servicios systemd FAILING (`trading_bot`, `velocityquant-pathc-healthcheck`,
  `vq-adp-capture`) sin investigar.
- 2 timers DEAD (`vq-shadow-rsync`, `poly_log_rotator` antes de hoy 05:35).
- 26+ archivos `.bak` debris en directorios productivos.

---

## §2 · Áreas de foco prioritarias (las 4 que Marco eligió)

### A · Seguridad

**Lo que sé**:
- Hot wallets Solana en `/home/administrator/.velocityquant_secrets/`:
  `hot200_keypair.json`, `x402_keypair.json`, `stellar_keypair.json`.
- Permisos: mode 600, owner administrator.
- **Sin HSM, sin threshold-signing, sin air-gap**.
- API keys en `/home/administrator/.config/{fred,bls}/api_key` mode 600.
- `vq-poly-api:8090` expuesto vía nginx en `inicio.velocityquant.io/poly/`.
  **Auth fue removida Sáb 9 02:56 UTC** (Marco quiso dashboards públicos).
- Sin systemd sandboxing en services (no `PrivateTmp`, no
  `NoNewPrivileges`, no `User=` separados).

**Pregunto**:
1. Threat model si un atacante consigue RCE en host Dallas o Newark:
   ¿cuánto tarda en drenar las wallets?
2. ¿Qué tan grave es la exposición pública del audit dashboard sin auth?
3. Recomendación: ¿debe haber threshold-signing antes de LIVE,
   o es overkill para $5-10 microcapital?
4. ¿Hay tokens/secrets accidentales en código fuente (revísalo)?

### B · Honestidad de claims firmados

**Lo que sé**:
- ~150 r-numbers de MDs firmados (`r93` a `r150-undecim-quad`)
- Cada MD declara cambios de código con frase tipo "DONE" o "aplicado"
- **Yo detecté un caso de discrepancia hace horas**: el `[SAFETY-DIM]`
  assert YoY [0,20] para CPI en `bls_client.py` que el MD r150-sept
  declaró DONE el 8-may 04:12 UTC nunca llegó al archivo. Fue verdad
  recién 9-may 05:30 UTC.

**Pregunto**:
1. Cross-check: lee los MDs en `code/r-numbers/` (selección
   representativa) y verifica que los cambios declarados estén
   realmente en `code/poly_sidecar/`, `code/newark_mirror/`,
   `code/solana_executor_rs/`. Repórtame TODOS los gaps.
2. ¿La narrativa de los MDs sobreestima la madurez del sistema vs
   el código real?
3. ¿Las 16 checks StressPass tienen evidencia de funcionamiento end-to-end
   o son afirmaciones?

### C · Code rot · zombie debt

**Lo que sé**:
- 26+ `.bak` files en directorios productivos
- ~10K markers `TODO/FIXME` cross-codebase (poly_sidecar 1,857 ·
  quantum_ppo 7,891 · profitlab_quantum 1)
- 3 systemd services failing
- 2 timers dead
- Placeholder code: `toxicflow/`, `predict_sentiment.py` skeleton
- Sin CI/CD pipeline visible
- Sin tests cobertura medible

**Pregunto**:
1. ¿Cuánto código es zombie (código muerto pero presente)?
2. ¿Cuánto del TODO/FIXME density apunta a riesgos reales LIVE?
3. ¿Hay loops de polling/refresh que pueden saturar API externas
   (FRED, BLS, Polymarket) bajo carga real?
4. ¿La estructura de directorios (`/home/administrator/`,
   `/srv/`, `newark_mirror/`) es coherente o caótica?

### D · Viabilidad LIVE Mar 12

**Lo que sé**:
- Capital target: $5-10 (micro)
- Edge cyclic arb real: 0.02-0.10%/día sobre capital tradeable
- Pasaron por 1 fail (NFP Vie 8) ya
- Sidecar Polymarket τ está en soak 12h hasta 17:40 UTC hoy
- BUG-NFP-DIM diferido oficialmente

**Pregunto · veredicto binario**:
1. **GO / NO-GO Mar 12**: ¿debe Marco exponer microcapital LIVE
   este martes con el sistema en su estado actual?
2. Si NO-GO: ¿qué fix mínimo cambia tu veredicto a GO?
3. Si GO: ¿con qué probabilidad esperas que el sistema sobreviva las
   primeras 24h LIVE sin requerir intervención manual?
4. ¿Los 16 checks StressPass son la métrica correcta o falta algo?

---

## §3 · Output esperado de tu audit

Estructura propuesta del MD que devolverás (ajustable):

```
# CODEX AUDIT · VelocityQuant · 2026-05-09

## §0 · Veredicto binario · GO / NO-GO Mar 12 13:30 UTC LIVE
Razón en 3 líneas máximo.

## §1 · Findings CRITICAL (bloqueantes para LIVE)
(N findings)
Cada uno con:
  - Title
  - Severity: CRITICAL
  - Path (file:line)
  - Evidence (extracto)
  - Impact (cuantificado donde sea posible)
  - Recommendation (mínimo viable)

## §2 · Findings HIGH (deberían fixarse pre-LIVE pero no bloquean)
...

## §3 · Findings MEDIUM (post-LIVE Mar 13+)
...

## §4 · Findings LOW (cleanup)
...

## §5 · Honestidad de claims firmados
Lista de discrepancias MD-firmado vs código real, ordenadas por severidad.

## §6 · Top-10 must-fix (lista priorizada de §1-§4)
Una sola lista, ranqueada.

## §7 · Probabilidad de éxito Mar 12 LIVE
Estimación con razonamiento.

## §8 · Cosas que NO pude juzgar sin más info
Lista de info que necesitas. Marco te la pasa vía Claude.
```

Si necesitas otro formato porque crees mejor, justifícalo y úsalo.

---

## §4 · Cómo pedir más info

Si necesitas archivos adicionales (logs específicos, output de comandos,
DBs queries), Marco me lo pasa a mí (Claude) y te entrego en chat (a
través de Marco). Indica explícito en tu output:
```
NEED_MORE_INFO:
  - <descripción + path o consulta>
```

Yo respondo con el dato exacto sin filtrar.

---

## §5 · Acceso a código del bundle

Estructura del tar.gz:

```
codex_audit_2026-05-09/
├── 00_BRIEF.md          ← este archivo
├── 01_INVENTORY.md      ← inventario completo (file paths, LOC, tamaños)
├── 02_KNOWN_ISSUES.md   ← auto-disclosure: lo que yo (Claude) sé que está mal
├── 03_TIMELINE.md       ← decisiones firmadas r93-r150-undecim-quad
├── 04_SYSTEMD_STATE.md  ← snapshot servicios + timers
├── 05_NGINX_CONFIGS.md  ← vhosts producción
├── code/                ← código sanitizado (sin keypairs/api_keys/env)
│   ├── poly_sidecar/    ← Polymarket sidecar Python
│   ├── solana_executor_rs/ ← código Rust Dallas (con git)
│   ├── newark_mirror/   ← mirrors Rust Newark
│   ├── v4_q1q4_patches/ ← patches V4
│   ├── profitlab_quantum/ ← QuantumBot LIVE paper
│   ├── quantum_ppo/     ← QuantumBot lab offline
│   └── r-numbers/       ← MDs firmados representativos
├── logs_sample/         ← samples 7d sanitized
├── configs/             ← nginx + systemd unit files
├── systemd_units/       ← unit files completos
└── SHA256SUMS           ← hashes de cada archivo
```

**No hay**: `.env`, keypairs `.json`, archivos `api_key`, secrets de
Telegram/Stellar, internal_ledger encrypted.

Si crees que para auditar necesitas alguno de los excluidos, **dilo
explícito** y Marco decide caso por caso.

---

## §6 · Caso real ya detectado (úsalo de calibración)

Caso `[SAFETY-DIM]` documentado en r150-decim §1:

> El MD r150-sept (8-may 04:12 UTC) afirmaba haber aplicado un
> `assert 0 <= yoy_pct <= 20` en `bls_client.py` para prevenir
> dimensionality errors en el cálculo del CPI YoY. Backups creados
> con timestamp `pre_assert_20260509T040917Z`.
>
> 9-may 05:30 UTC, antes de aplicar P3.6.5, verifiqué:
> ```
> $ wc -c bls_client.py bls_client.py.bak_pre_assert_20260509T040917Z
>    10422 bls_client.py
>    10422 bls_client.py.bak_pre_assert_20260509T040917Z
> $ diff bls_client.py bls_client.py.bak_pre_assert_20260509T040917Z
> (vacío · idénticos)
> ```
>
> El edit nunca se aplicó. El backup pre-assert es idéntico al archivo
> "post-edit". El MD mintió (yo escribí ese MD).
>
> Lo apliqué realmente recién en la edición de bls_client.py
> 9-may 05:33 UTC durante la implementación P3.6.5.

Mi explicación: probablemente el `Edit` del asistente devolvió "success"
pero el `old_string` no matcheó. Sin verificación post-edit (`grep`),
asumí éxito. Documenté el bug en r150-decim §1.

**Hay probablemente más casos así. Encuéntralos.**

---

## §7 · Cierre

Marco no espera diplomacia. Tu output puede destruir 3 meses de
trabajo si encuentras algo grave. Eso es exactamente lo que quiere
descubrir antes de exponer dinero.

Si tu veredicto es NO-GO, será doloroso pero correcto.
Si tu veredicto es GO, será una validación cara pero útil.

**No firmes lo que no es verdad. No filtres lo que es verdad.**

---

**Bundle generado**: 2026-05-09 ~07:30 UTC
**Generador**: Claude Opus 4.7 (agente operativo Dallas)
**Operador**: Marco
**Bundle es read-only** · todo cambio coordinado vía Marco
