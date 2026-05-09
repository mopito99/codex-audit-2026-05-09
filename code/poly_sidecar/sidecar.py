"""VelocityQuant — Polymarket Sentiment Sidecar.

Loop: cada 300s
  1. Lee macro_calendar.json para descubrir contratos
  2. Para cada contrato, snapshot de los 4 endpoints REST
  3. Calcula τ_per_contract, τ_macro, τ_crypto, τ_final
  4. Calcula ρ Pearson rolling 4h (si hay datos)
  5. Escribe state atómico a /home/administrator/poly_sidecar/data/tau_state.json
  6. Repite.

El loop NO ejecuta trading. NO toca V3.5. Solo escribe state.
El bot Rust V4-Alpha (cuando entre en SHADOW viernes) leerá ese state.
"""
from __future__ import annotations
import asyncio
import datetime as dt
import json
import logging
import re
import signal
import time
from collections import deque
from pathlib import Path

from poly_client import PolymarketClient
from tau_calc import (
    TauComponents,
    aggregate_tau_per_category,
    compute_pearson_rho,
    compute_tau_final,
    compute_tau_for_contract,
)
from btc_feed import BTCFeed
# 2026-05-08 · Migrated from fmp_client (HTTP 402 desde 2025-08-31) a fmp_compat.
# fmp_compat es drop-in: FRED calendar + BLS actuals (gov APIs, $0 recurring).
from fmp_compat import FMPClient, time_to_next_event, upcoming_events
from investing_client import InvestingClient, load_sigma_from_calendar, SIGMA_FRED
import store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        # r130 Gemma Q1 firma — StreamHandler para systemd journal
        logging.StreamHandler(),
        # archivo histórico data/sidecar.log
        logging.FileHandler("/home/administrator/poly_sidecar/data/sidecar.log"),
    ],
)


# [r152-M1] Redact API keys/tokens from log records (Codex M-02 fix)
# httpx loggea URLs completas con query strings · FRED/BLS keys quedaban
# en disco (sidecar.log + journald). Filter aplica a todos los handlers root.
_REDACT_PATTERN = re.compile(
    r"(api_key|registrationkey|token|secret|password)=[A-Za-z0-9._-]{8,}",
    re.IGNORECASE,
)


class _RedactSecretsFilter(logging.Filter):
    """Redact secrets in log records.

    httpx logs `HTTP Request: %s %s "%s %d %s"` with `request.url` as a
    httpx.URL object (NOT str). Lazy formatting renders URL via str()
    AFTER filter runs · key se filtra plaintext.

    Estrategia: para non-str args, comprobar si su str() contiene un
    secret pattern. Si sí, reemplazar por la versión redactada (string).
    Si no, mantener el objeto original (preserva tipos int/float para %d).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _REDACT_PATTERN.sub(r"\1=<REDACTED>", record.msg)
        if record.args:
            try:
                new_args = []
                for a in record.args:
                    if isinstance(a, str):
                        new_args.append(_REDACT_PATTERN.sub(r"\1=<REDACTED>", a))
                    else:
                        sa = str(a)
                        if _REDACT_PATTERN.search(sa):
                            new_args.append(_REDACT_PATTERN.sub(r"\1=<REDACTED>", sa))
                        else:
                            new_args.append(a)
                record.args = tuple(new_args)
            except Exception:
                pass
        return True


_redact_filter = _RedactSecretsFilter()
for _h in logging.getLogger().handlers:
    _h.addFilter(_redact_filter)
# httpx logger es separado · agregar también
logging.getLogger("httpx").addFilter(_redact_filter)

logger = logging.getLogger("poly_sidecar.main")

CALENDAR_FILE = Path("/home/administrator/poly_sidecar/macro_calendar.json")
RISK_CONFIG_FILE = Path("/home/administrator/poly_sidecar/risk_config.json")
DEFAULT_INTERVAL_S = 300


# [r152-M2] Codex C-01 fix · ventana absoluta T-30min → T+15min
# Firmado Gemma hash GEMMA4-SR-QUANT-B31-M2-FIX-C01-OK-20260509T1215Z
def _next_or_recent_tracked(events, recent_window_s: int = 900):
    """Return tracked event con menor |delta| dentro de ventana T-30min → T+recent_window_s.

    delta > 0  → evento futuro · seconds remaining
    delta < 0  → evento reciente pasado · |delta| = seconds since release
    delta None → ningún evento dentro de ventana

    Args:
        events: lista MacroEvent del FMP cache
        recent_window_s: cuántos segundos post-release seguimos en HIGH (default 900 = 15min)

    Returns:
        (event, delta_secs) o (None, None) si ningún evento en ventana.
    """
    now = dt.datetime.now(dt.timezone.utc)
    candidates = []
    for ev in events:
        if not FMPClient.is_tracked(ev):
            continue
        try:
            ts = dt.datetime.fromisoformat(ev.date.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        delta = (ts - now).total_seconds()
        if -recent_window_s <= delta <= 1800:
            candidates.append((delta, ev))
    if not candidates:
        return None, None
    candidates.sort(key=lambda x: abs(x[0]))
    delta, ev = candidates[0]
    return ev, delta


# ── r144 firma Gemma Q4 — Adaptive polling backoff Polymarket ────────────────
class AdaptivePollingState:
    """
    Exponential backoff con piso 60s y techo 300s para polling Polymarket.
    En caso de 429 → duplica intervalo (max 300s). Tras 5 polls consecutivos OK
    → vuelve a 60s.

    Por qué: 300s fijo es inaceptable (τ stale 5min en macro events). 60s fijo
    arriesga rate-limit. Adaptive es el balance correcto firmado en r144.
    """
    BASE_INTERVAL_S = 60
    MAX_INTERVAL_S = 300
    BACKOFF_FACTOR = 2.0
    SUCCESS_TO_RESET = 5
    MAX_INTERVAL_ALERT_AFTER_S = 1800  # 30 min sostenido en MAX → Telegram

    def __init__(self):
        self.current_interval = self.BASE_INTERVAL_S
        self.consecutive_ok = 0
        self.entered_max_at: float | None = None
        self.alerted_max = False

    def report(self, hit_429: bool, now_ts: float) -> int:
        """Devuelve el siguiente intervalo (segundos) tras reportar éxito o 429."""
        prev_interval = self.current_interval
        if hit_429:
            self.current_interval = min(
                int(self.current_interval * self.BACKOFF_FACTOR),
                self.MAX_INTERVAL_S
            )
            self.consecutive_ok = 0
            if self.current_interval == self.MAX_INTERVAL_S and self.entered_max_at is None:
                self.entered_max_at = now_ts
        else:
            self.consecutive_ok += 1
            if self.consecutive_ok >= self.SUCCESS_TO_RESET:
                if self.current_interval > self.BASE_INTERVAL_S:
                    self.current_interval = self.BASE_INTERVAL_S
                    self.consecutive_ok = 0
                    self.entered_max_at = None
                    self.alerted_max = False

        # Trigger alarma si stuck en MAX > 30min
        if (self.entered_max_at and
            (now_ts - self.entered_max_at) > self.MAX_INTERVAL_ALERT_AFTER_S and
            not self.alerted_max):
            self.alerted_max = True
            return -1  # señal de "alerta requerida"
        return self.current_interval


# Cache mutable para audit_log NORMAL_DEGRADED transitions (firmado Gemma r92)
class _StateAuditCache:
    """Mantiene estado entre ticks para detectar transitions."""
    last_normal_degraded_sf: float | None = None
    last_mode: str | None = None


_state_audit_cache = _StateAuditCache()


def load_risk_config() -> dict:
    """Carga risk_config.json (firmado Gemma r92/r93). Fallback a defaults si missing.

    Spec r93 §2 condition (firma Gemma 2026-05-06): si JSON falla, log CRITICAL
    explícito obligatorio. Sin log explícito el fallback es fallo de auditoría.
    """
    try:
        return json.loads(RISK_CONFIG_FILE.read_text())
    except Exception as e:
        logger.critical(
            "WARNING: risk_config.json corrupted/missing. "
            "Operating on r92 Signed Defaults. "
            f"Reason: {type(e).__name__}: {e}"
        )
        return {
            "normal_degraded": {
                "size_factor_default": 0.70,
                "size_factor_bounds": [0.55, 0.85],
                "thresholds_errors_per_min": {"tier_a_low": 1.0, "tier_b_medium": 5.0, "tier_c_high": 15.0},
                "size_factors_by_tier": {"below_tier_a": 0.85, "tier_a_to_b": 0.70, "tier_b_to_c": 0.60, "above_tier_c": 0.55},
            },
            "stale_hierarchy": {
                "L1_404_per_min_threshold": 1.0,
                "L2_5xx_per_min_threshold": 0.6,
                "L3_timeout_per_min_threshold": 1.0,
                "L4_heartbeat_age_seconds": 600,
            },
        }


def compute_normal_degraded_size_factor(err_404_per_min: float, risk_config: dict) -> float:
    """Dynamic size_factor para NORMAL_DEGRADED (firmado Gemma r92).

    Bounded [0.55, 0.85] default 0.70. Escalado por err/min thresholds [1, 5, 15].
    """
    nd = risk_config.get("normal_degraded", {})
    th = nd.get("thresholds_errors_per_min", {"tier_a_low": 1.0, "tier_b_medium": 5.0, "tier_c_high": 15.0})
    sf = nd.get("size_factors_by_tier", {"below_tier_a": 0.85, "tier_a_to_b": 0.70, "tier_b_to_c": 0.60, "above_tier_c": 0.55})
    if err_404_per_min < th["tier_a_low"]:
        return sf["below_tier_a"]
    if err_404_per_min < th["tier_b_medium"]:
        return sf["tier_a_to_b"]
    if err_404_per_min < th["tier_c_high"]:
        return sf["tier_b_to_c"]
    return sf["above_tier_c"]


def _filter_active_contracts(contracts: list[dict]) -> list[dict]:
    """Filtra contratos cuyo end_date_iso ya pasó.

    Antes (bug 2026-05-05/06): el sidecar consultaba mercados Polymarket
    expirados (ej. 'Bitcoin above ___ on May 5?' tras May 5), generando
    miles de 404s acumulados que disparaban CAUTELA por "endpoints stale"
    sin causa real.
    """
    today_str = dt.datetime.now(dt.timezone.utc).date().isoformat()
    today = dt.date.fromisoformat(today_str)
    active = []
    skipped = []
    for c in contracts:
        end_str = c.get("end_date_iso") or c.get("end_date")
        if end_str:
            try:
                end_d = dt.date.fromisoformat(str(end_str)[:10])
                if end_d < today:
                    skipped.append(f"{c.get('market_id')}={c.get('title','?')[:40]} (ended {end_d})")
                    continue
            except Exception:
                pass  # parse error → mantener (defensive)
        active.append(c)
    if skipped:
        logger.info(f"polymarket: skipping {len(skipped)} expired contracts: {skipped}")
    return active


def load_calendar() -> dict:
    with CALENDAR_FILE.open() as f:
        cal = json.load(f)
    # Refresh σ_FRED from calendar (no-op si no existe fred_calibration)
    n = load_sigma_from_calendar(cal)
    if n > 0:
        logger.debug(f"σ_FRED loaded for {n} categories: {list(SIGMA_FRED.keys())}")
    return cal


# Rolling history per contract — last 288 samples = 24h at 5min cadence
class VolHistoryCache:
    def __init__(self, max_samples: int = 288):
        self._cache: dict[str, deque] = {}
        self._max = max_samples

    def push(self, market_id: str, volume: float | None) -> None:
        if volume is None:
            return
        d = self._cache.setdefault(market_id, deque(maxlen=self._max))
        d.append(volume)

    def get(self, market_id: str) -> list[float]:
        return list(self._cache.get(market_id, ()))


class PriceHistoryCache:
    """Holds last N midpoint values per token_id for rolling Pearson."""
    def __init__(self, max_samples: int = 60):
        # 60 samples × 5min/cycle = 5h ventana — sweet spot 4h±1
        self._cache: dict[str, deque] = {}
        self._max = max_samples

    def push(self, token_id: str, midpoint: float | None) -> None:
        if midpoint is None:
            return
        d = self._cache.setdefault(token_id, deque(maxlen=self._max))
        d.append(midpoint)

    def returns(self, token_id: str) -> list[float]:
        seq = list(self._cache.get(token_id, ()))
        if len(seq) < 2:
            return []
        return [(seq[i] - seq[i - 1]) / seq[i - 1] if seq[i - 1] != 0 else 0.0
                for i in range(1, len(seq))]


class BTCPriceCache:
    """Holds last N BTC spot prices for rolling Pearson against bear contracts."""
    def __init__(self, max_samples: int = 60):
        self._buf: deque = deque(maxlen=max_samples)

    def push(self, price: float | None) -> None:
        if price is None or price <= 0:
            return
        self._buf.append(price)

    def prices(self) -> list[float]:
        return list(self._buf)

    def returns(self) -> list[float]:
        seq = list(self._buf)
        if len(seq) < 2:
            return []
        return [(seq[i] - seq[i - 1]) / seq[i - 1] if seq[i - 1] != 0 else 0.0
                for i in range(1, len(seq))]


async def run_once(
    client: PolymarketClient,
    btc_feed: BTCFeed,
    fmp: FMPClient,
    investing: InvestingClient,
    calendar: dict,
    vol_cache: VolHistoryCache,
    price_cache: PriceHistoryCache,
    btc_cache: BTCPriceCache,
    fmp_last_fetch_ts: list,
    investing_last_fetch_ts: list,
) -> dict:
    formula = calendar["tau_formula"]
    sigmoid_params = calendar["sigmoid_params"]
    weights = formula["weights"]
    cat_weights = formula["category_weights"]

    contracts = calendar["polymarket_contracts_initial_set"]
    macro = _filter_active_contracts(contracts.get("macro", []))
    crypto = _filter_active_contracts(contracts.get("crypto", []))

    # Fetch BTC spot in parallel with Polymarket
    btc_task = asyncio.create_task(btc_feed.get_price())

    # [P3.6.5-v2] FMP polling adaptativo · firmado Gemma r152
    # HIGH_FREQUENCY = 30s · ventana T-30min → T+15min del próximo tracked event
    # LOW_FREQUENCY  = 3600s · fuera de ventana
    # Razón: Codex C-01 fix · captura BLS post-release SLA <120s garantizada
    # hash GEMMA4-SR-QUANT-B31-M2-FIX-C01-OK-20260509T1215Z
    if fmp.configured:
        cached_for_poll = fmp.cached_events()
        next_or_recent_ev, secs_window = (
            _next_or_recent_tracked(cached_for_poll, recent_window_s=900)
            if cached_for_poll else (None, None)
        )
        in_high_window = (
            next_or_recent_ev is not None
            and -900 <= secs_window <= 1800
        )
        poll_interval = 30 if in_high_window else 3600
        if (time.time() - fmp_last_fetch_ts[0]) > poll_interval:
            try:
                # [r152-M2-bis] force_refresh_bls=True durante high window
                # bypass cache TTL · garantiza SLA <120s post-release
                # firmado Gemma · Codex CRITICAL-NEW-02 fix
                await fmp.fetch_calendar(
                    days_ahead=14,
                    days_behind=0,
                    force_refresh_bls=in_high_window,
                )
                fmp_last_fetch_ts[0] = time.time()
                if in_high_window:
                    logger.info(
                        f"[P3.6.5-v2] HIGH_FREQUENCY poll · "
                        f"evt={next_or_recent_ev.event} "
                        f"secs_window={secs_window:.0f}s "
                        f"(neg=post-release · BLS force_refresh=True)"
                    )
            except Exception as e:
                logger.warning(f"FMP fetch error: {e}")

    # Investing.com polling cada 30min (1800s) — captura "actual" tras release
    if (time.time() - investing_last_fetch_ts[0] > 1800):
        try:
            await investing.fetch(days_ahead=1, days_behind=1)
            investing_last_fetch_ts[0] = time.time()
        except Exception as e:
            logger.warning(f"Investing.com fetch error: {e}")

    async def fetch_and_compute(c: dict) -> tuple[dict, TauComponents]:
        snap = await client.snapshot(c["market_id"], c["yes_token_id"])
        vol_cache.push(c["market_id"], snap.volume_24h)
        price_cache.push(c["yes_token_id"], snap.midpoint)
        # Para ρ Pearson también guardamos midpoint del NO_token (apuesta bajista)
        if c.get("no_token_id"):
            no_mid = await client.get_midpoint(c["no_token_id"])
            price_cache.push(c["no_token_id"], no_mid)
        comps = compute_tau_for_contract(
            snap, sigmoid_params, weights,
            vol_history_24h=vol_cache.get(c["market_id"]),
        )
        return c, comps

    macro_results = await asyncio.gather(*(fetch_and_compute(c) for c in macro))
    crypto_results = await asyncio.gather(*(fetch_and_compute(c) for c in crypto))

    macro_taus = [comps for _, comps in macro_results]
    crypto_taus = [comps for _, comps in crypto_results]

    tau_macro = aggregate_tau_per_category(macro_taus)
    tau_crypto = aggregate_tau_per_category(crypto_taus)
    tau_final = compute_tau_final(tau_crypto, tau_macro, cat_weights)

    # BTC price — push to cache
    btc_price, btc_pub_time = await btc_task
    btc_cache.push(btc_price)
    btc_returns = btc_cache.returns()

    # ρ Pearson — para cada contrato cripto monitoreado, correlación BTC vs NO_token (apuesta bajista)
    # Usamos el contrato cripto más líquido (BTC_LONG_TERM o BTC_MONTHLY) como referencia.
    rho_global = None
    rho_per_contract: list[dict] = []
    for c in crypto:
        no_token = c.get("no_token_id")
        if not no_token:
            continue
        no_returns = price_cache.returns(no_token)
        rho = compute_pearson_rho(btc_returns, no_returns)
        rho_per_contract.append({
            "market_id": c.get("market_id"),
            "title": c.get("title"),
            "category": c.get("category"),
            "rho": round(rho, 4) if rho is not None else None,
            "n_paired": min(len(btc_returns), len(no_returns)),
        })
        # ρ_global = ρ del contrato más líquido (mayor vol24h_at_capture_usd)
        if rho is not None and (rho_global is None or
                                c.get("vol24h_at_capture_usd", 0) > 1_000_000):
            rho_global = rho

    per_contract_serialized = []
    for cat, results in [("macro", macro_results), ("crypto", crypto_results)]:
        for c, comps in results:
            per_contract_serialized.append({
                "category_group": cat,
                "category": c.get("category"),
                "market_id": comps.market_id,
                "title": c.get("title"),
                "tau": round(comps.tau, 6),
                "delta_prob": round(comps.delta_prob, 6),
                "vol_zscore": round(comps.vol_zscore, 6),
                "implied_vol": round(comps.implied_vol, 6),
                "norm_delta_prob": round(comps.norm_delta_prob, 6),
                "norm_vol_zscore": round(comps.norm_vol_zscore, 6),
                "norm_implied_vol": round(comps.norm_implied_vol, 6),
                "valid": comps.valid,
                "reason": comps.reason,
            })

    rho_threshold = formula.get("rho_divergence_threshold", -0.7)
    divergence = rho_global is not None and rho_global < rho_threshold

    # ── Modo derivado del estado (Gemma spec V4-Alpha + V4.1 ponderador) ──
    # Defensivo: ρ < −0.7 (divergencia narrativa) — hard override
    # Cautela:   stale, reaction_required (SF), τ_final > 0.7
    # Normal:    todo OK
    # ── Spec r92 stale hierarchy (firmado Gemma 2026-05-06) ─────────────
    # Lee thresholds de risk_config.json (separation of concerns).
    risk_config = load_risk_config()
    sh = risk_config.get("stale_hierarchy", {})
    th_L1 = sh.get("L1_404_per_min_threshold", 1.0)
    th_L2 = sh.get("L2_5xx_per_min_threshold", 0.6)
    th_L3 = sh.get("L3_timeout_per_min_threshold", 1.0)
    window = sh.get("window_seconds", 300.0)

    err_404_per_min = client.errors_per_minute("404", window_seconds=window)
    err_5xx_per_min = client.errors_per_minute("5xx", window_seconds=window)
    err_timeout_per_min = client.errors_per_minute("timeout", window_seconds=window)

    stale_level = "L0"
    stale_reason = ""
    if err_5xx_per_min >= th_L2:
        stale_level = "L2"
        stale_reason = f"5xx errors {err_5xx_per_min:.1f}/min (>={th_L2})"
    elif err_timeout_per_min >= th_L3:
        stale_level = "L3"
        stale_reason = f"timeout errors {err_timeout_per_min:.1f}/min (>={th_L3})"
    elif err_404_per_min >= th_L1:
        stale_level = "L1"
        stale_reason = f"404 errors {err_404_per_min:.1f}/min (markets vencidos, ruido benigno, NO trigger CAUTELA)"

    investing_react = False  # se setea abajo cuando construyamos investing_info

    # Build FMP info
    fmp_events = fmp.cached_events() if fmp.configured else []
    next_evt, sec_to_next = time_to_next_event(fmp_events) if fmp_events else (None, None)
    upcoming_24h = upcoming_events(fmp_events, hours_ahead=24) if fmp_events else []

    fmp_info = {
        "configured": fmp.configured,
        "status": fmp.status,
        "errors": fmp.errors,
        "last_error": fmp.last_error,
        "last_sync_ts": fmp.last_ok if fmp.last_ok > 0 else None,
        "events_in_cache": len(fmp_events),
        "tracked_events_in_cache": sum(1 for e in fmp_events if FMPClient.is_tracked(e)),
        "upcoming_24h": [
            {
                "event": e.event,
                "country": e.country,
                "date": e.date,
                "category": FMPClient.categorize(e),
                "estimate": e.estimate,
                "previous": e.previous,
                "actual": e.actual,
                "impact": e.impact,
            }
            for e in upcoming_24h[:10]
        ],
        "next_event": (
            {
                "event": next_evt.event,
                "country": next_evt.country,
                "date": next_evt.date,
                "category": FMPClient.categorize(next_evt),
                "seconds_to_event": int(sec_to_next),
                "estimate": next_evt.estimate,
                "previous": next_evt.previous,
                "actual": next_evt.actual,
            } if next_evt else None
        ),
    }

    # Investing.com — captura Surprise Factor de eventos publicados hace ≤6h
    investing_info = {
        "status": investing.status,
        "errors": investing.errors,
        "last_error": investing.last_error,
        "events_in_cache": len(investing.cached()),
        "last_sync_ts": investing.last_ok if investing.last_ok > 0 else None,
        "recent_releases_6h": investing.recent_releases(hours_behind=6),
    }
    # Reaction signal: SF más reciente que cruzó umbral 1.0σ
    react_event = next(
        (r for r in investing_info["recent_releases_6h"] if r.get("reaction_threshold_hit")),
        None,
    )
    investing_info["latest_surprise_event"] = react_event
    investing_info["reaction_required"] = react_event is not None
    investing_react = react_event is not None

    # ── Modo final (Spec r91+/r92/r93/r107/r108/r109/r110/r111 firmado Gemma) ─
    # NORMAL_DEGRADED dynamic size_factor [0.55-0.85] thresholds [1,5,15] err/min
    #
    # PRIORITY ORDER (firma r109 §4c):
    #   1. ⚡ kill_switch BTC consensus outlier (HARD OVERRIDE pre-todo)
    #   2. ρ < -0.7 divergencia narrativa → DEFENSIVO
    #   3. SF > 1σ Investing reaction → CAUTELA
    #   4. τ_final > 0.7 → CAUTELA
    #   5. Stale L2/L3 → CAUTELA temporal
    #   6. Stale L1 → NORMAL_DEGRADED dynamic
    #   7. else → NORMAL
    size_factor = 1.0  # default NORMAL
    kill_switch_triggered = False

    # ⚡ STEP 1 — kill_switch BTC consensus check (HARD OVERRIDE firma r107 §2b)
    # Solo verifica si tenemos consensus_result + buffer + macro_event_window
    try:
        from kill_switch import check_btc_kill_switch
        consensus_result = getattr(btc_feed, "last_consensus", None)
        btc_buffer = getattr(btc_feed, "buffer", None)
        if consensus_result and btc_buffer:
            ks_result = check_btc_kill_switch(
                consensus_result=consensus_result,
                btc_buffer=btc_buffer,
                risk_config=risk_config,
                fmp_upcoming=upcoming_24h or [],
            )
            if ks_result.get("triggered"):
                mode = "CRITICAL"
                mode_reason = f"kill_switch BTC: {ks_result['reason']}"
                size_factor = 0.0
                kill_switch_triggered = True
                logger.critical(
                    f"⚡ KILL_SWITCH BTC TRIGGERED: {ks_result['reason']} "
                    f"| btc_move={ks_result['btc_move_pct']:.2f}% "
                    f"| event={ks_result.get('matched_event', {}).get('event', '?')}"
                )
    except Exception as e:
        # Defensive: si el kill_switch logic falla, log + continuar con mode logic estándar
        logger.warning(f"kill_switch check exception (non-fatal): {type(e).__name__}: {e}")

    if kill_switch_triggered:
        # Ya se setteó mode=CRITICAL, skip resto del mode logic
        pass
    elif divergence:
        mode = "DEFENSIVO"
        mode_reason = f"ρ={rho_global:.3f} < {rho_threshold} (divergencia narrativa)"
        size_factor = 0.5
    elif investing_react:
        mode = "CAUTELA"
        cat = react_event.get("category", "?")
        sf = react_event.get("surprise_factor")
        mode_reason = f"SF={sf} en {cat} (|SF|>1σ)"
        size_factor = 0.7
    elif tau_final > 0.7:
        mode = "CAUTELA"
        mode_reason = f"τ_final={tau_final:.3f} > 0.7"
        size_factor = 0.7
    elif stale_level == "L2":
        mode = "CAUTELA"
        mode_reason = f"polymarket L2 stale: {stale_reason}"
        size_factor = 0.7
    elif stale_level == "L3":
        mode = "CAUTELA"
        mode_reason = f"polymarket L3 stale: {stale_reason}"
        size_factor = 0.7
    elif stale_level == "L1":
        # NORMAL_DEGRADED — solo L1, dynamic size_factor escalado por err/min
        # Lee thresholds + factors de risk_config.json (firmado Gemma r92)
        mode = "NORMAL_DEGRADED"
        mode_reason = f"polymarket L1 only: {stale_reason}"
        size_factor = compute_normal_degraded_size_factor(err_404_per_min, risk_config)
        # Audit log obligatorio (firmado Gemma r92): cada cambio de tier
        prev_sf = _state_audit_cache.last_normal_degraded_sf
        if prev_sf is not None and abs(prev_sf - size_factor) > 0.001:
            logger.info(
                f"L1_Degradation_Event: {prev_sf:.2f} -> {size_factor:.2f} "
                f"(err_404_per_min={err_404_per_min:.2f})"
            )
        _state_audit_cache.last_normal_degraded_sf = size_factor
    else:
        mode = "NORMAL"
        mode_reason = "todo OK"
        size_factor = 1.0

    state = {
        "tau_final": round(tau_final, 6),
        "tau_macro": round(tau_macro, 6),
        "tau_crypto": round(tau_crypto, 6),
        "rho": round(rho_global, 4) if rho_global is not None else None,
        "rho_threshold": rho_threshold,
        "rho_divergence_active": divergence,
        "rho_per_contract": rho_per_contract,
        "btc_price_usd": round(btc_price, 2) if btc_price else None,
        "btc_pub_time": btc_pub_time,
        "btc_samples_in_cache": len(btc_cache.prices()),
        "btc_status": btc_feed.status,
        "btc_errors": btc_feed.errors,
        "btc_last_sync_ts": btc_feed.last_ok if btc_feed.last_ok > 0 else None,
        "polymarket_last_sync_ts": time.time(),  # cada cycle Polymarket es sync exitoso
        "fmp": fmp_info,
        "investing": investing_info,
        "mode": mode,
        "mode_reason": mode_reason,
        "heartbeat_ts": time.time(),
        "polling_interval_s": int(formula.get("polling_interval_seconds", DEFAULT_INTERVAL_S)),
        "endpoints_errors": dict(client.errors_by_endpoint),
        "per_contract": per_contract_serialized,
        "calendar_version": calendar.get("version"),
    }
    return state


async def main_loop():
    client = PolymarketClient()
    btc_feed = BTCFeed()
    fmp = FMPClient()
    investing = InvestingClient()
    vol_cache = VolHistoryCache(max_samples=288)
    price_cache = PriceHistoryCache(max_samples=60)
    btc_cache = BTCPriceCache(max_samples=60)
    fmp_last_fetch_ts = [0.0]
    investing_last_fetch_ts = [0.0]

    stop = asyncio.Event()

    def _shutdown(*_):
        logger.info("shutdown signal received")
        stop.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except Exception:
            pass

    # r144 firma Gemma Q4 — adaptive backoff. El interval del calendar TOML
    # ya no se respeta como autoridad: usamos backoff dinámico 60s→max 300s.
    polling_state = AdaptivePollingState()
    interval = polling_state.current_interval

    logger.info(f"sidecar started — adaptive polling base={interval}s max={polling_state.MAX_INTERVAL_S}s (r144 Q4)")
    last_429_ts_seen: float | None = None
    while not stop.is_set():
        cycle_start = time.time()
        try:
            calendar = load_calendar()
            state = await run_once(client, btc_feed, fmp, investing, calendar,
                                    vol_cache, price_cache, btc_cache,
                                    fmp_last_fetch_ts, investing_last_fetch_ts)
            # r144 Q4 — exponer current_polling_interval_s en /api/state.
            state["current_polling_interval_s"] = interval
            state["polling_state_consecutive_ok"] = polling_state.consecutive_ok
            store.write(state)
            # r125 §6 firma Gemma — auto-cleanup path B: real data wins
            try:
                import synthetic_override
                if synthetic_override.clear_on_polling_tick():
                    logger.info("synthetic override cleared (real polling tick succeeded)")
            except Exception as e:
                logger.warning(f"synthetic_override clear failed: {e}")
            logger.info(
                f"τ_final={state['tau_final']} τ_crypto={state['tau_crypto']} "
                f"τ_macro={state['tau_macro']} contracts={len(state['per_contract'])} "
                f"errors={state['endpoints_errors']} polling_s={interval}"
            )
        except Exception as e:
            logger.exception(f"cycle error: {e}")
            try:
                store.write({
                    "tau_final": 0.0,
                    "tau_macro": 0.0,
                    "tau_crypto": 0.0,
                    "rho": None,
                    "heartbeat_ts": time.time(),
                    "last_error": str(e),
                    "endpoints_errors": dict(client.errors_by_endpoint),
                    "per_contract": [],
                    "current_polling_interval_s": interval,
                })
            except Exception:
                pass

        # r144 Q4 — detectar si hubo 429 nuevo en este cycle.
        cycle_429 = (client.last_429_ts is not None
                     and (last_429_ts_seen is None or client.last_429_ts > last_429_ts_seen))
        if cycle_429:
            last_429_ts_seen = client.last_429_ts
        result = polling_state.report(hit_429=cycle_429, now_ts=time.time())
        if result == -1:
            logger.error(
                f"r144 Q4 ALERT: polling_interval stuck at MAX {polling_state.MAX_INTERVAL_S}s "
                f"durante >30min — posible cambio API Polymarket o ban. Investigar."
            )
            # Sigue funcionando con MAX_INTERVAL pero con alerta loggeada.
            interval = polling_state.MAX_INTERVAL_S
        else:
            interval = result

        elapsed = time.time() - cycle_start
        wait = max(0, interval - elapsed)
        try:
            await asyncio.wait_for(stop.wait(), timeout=wait)
        except asyncio.TimeoutError:
            pass

    await client.close()
    await btc_feed.close()
    await fmp.close()
    logger.info("sidecar stopped")


if __name__ == "__main__":
    asyncio.run(main_loop())
