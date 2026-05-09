"""τ calculation per Gemma 4 spec V4.1 (validated 2026-05-05).

Pipeline:
  τ_per_contract = 0.5·sigmoid(ΔProb) + 0.3·sigmoid(VolZScore) + 0.2·sigmoid(ImpliedVol)
  τ_macro  = max(τ_per_contract for c in macro)
  τ_crypto = max(τ_per_contract for c in crypto)
  τ_final  = 0.7·τ_crypto + 0.3·τ_macro

Where:
  ΔProb       = (P_t − P_avg_4h) / P_avg_4h
  VolZScore   = (V_now − μ_24h) / σ_24h    (μ,σ rolling 24h fidelity 5min)
  ImpliedVol  = spread / midpoint
"""
from __future__ import annotations
import math
import statistics
from dataclasses import dataclass
from typing import Iterable

from poly_client import MarketSnapshot


def sigmoid(x: float, k: float, x0: float) -> float:
    """norm(x) = 1 / (1 + exp(-k·(x − x0)))   bounded [0,1]."""
    try:
        return 1.0 / (1.0 + math.exp(-k * (x - x0)))
    except OverflowError:
        return 0.0 if (x - x0) < 0 else 1.0


@dataclass
class TauComponents:
    market_id: str
    delta_prob: float
    vol_zscore: float
    implied_vol: float
    norm_delta_prob: float
    norm_vol_zscore: float
    norm_implied_vol: float
    tau: float
    valid: bool
    reason: str | None = None


def compute_delta_prob(snap: MarketSnapshot) -> float | None:
    """ΔProb = (P_now − P_avg_4h) / P_avg_4h"""
    if snap.midpoint is None or snap.midpoint <= 0:
        return None
    if not snap.price_history:
        return None
    prices = [p for _, p in snap.price_history if p > 0]
    if len(prices) < 5:
        return None
    avg_4h = statistics.mean(prices)
    if avg_4h <= 0:
        return None
    return (snap.midpoint - avg_4h) / avg_4h


def compute_vol_zscore(
    snap: MarketSnapshot, vol_history_24h: list[float] | None
) -> float | None:
    """Z-score of current 24h volume vs rolling baseline.

    Polymarket REST does not give a clean 5min volume series — Gamma only
    exposes volume24hr (rolling current). For an MVP we use the running set
    of last-N samples held in memory by the sidecar and compute z-score
    over that. If <30 samples, return None (insufficient).
    """
    if snap.volume_24h is None or vol_history_24h is None:
        return None
    if len(vol_history_24h) < 30:
        return None
    try:
        mu = statistics.mean(vol_history_24h)
        sigma = statistics.pstdev(vol_history_24h)
        if sigma <= 0:
            return 0.0
        return (snap.volume_24h - mu) / sigma
    except Exception:
        return None


def compute_implied_vol(snap: MarketSnapshot) -> float | None:
    """ImpliedVol proxy = spread / midpoint."""
    if snap.spread is None or snap.midpoint is None or snap.midpoint <= 0:
        return None
    return abs(snap.spread) / snap.midpoint


def compute_tau_for_contract(
    snap: MarketSnapshot,
    sigmoid_params: dict,
    weights: dict,
    vol_history_24h: list[float] | None = None,
) -> TauComponents:
    """Returns full τ breakdown for one contract."""
    dp = compute_delta_prob(snap)
    vz = compute_vol_zscore(snap, vol_history_24h)
    iv = compute_implied_vol(snap)

    if dp is None and vz is None and iv is None:
        return TauComponents(
            market_id=snap.market_id,
            delta_prob=0.0,
            vol_zscore=0.0,
            implied_vol=0.0,
            norm_delta_prob=0.0,
            norm_vol_zscore=0.0,
            norm_implied_vol=0.0,
            tau=0.0,
            valid=False,
            reason="no_data_at_all",
        )

    dp = dp if dp is not None else 0.0
    vz = vz if vz is not None else 0.0
    iv = iv if iv is not None else 0.0

    sp_dp = sigmoid_params["delta_prob"]
    sp_vz = sigmoid_params["vol_zscore"]
    sp_iv = sigmoid_params["implied_vol"]

    n_dp = sigmoid(dp, sp_dp["k"], sp_dp["x0"])
    n_vz = sigmoid(vz, sp_vz["k"], sp_vz["x0"])
    n_iv = sigmoid(iv, sp_iv["k"], sp_iv["x0"])

    tau = (
        weights["delta_prob"] * n_dp
        + weights["vol_zscore"] * n_vz
        + weights["implied_vol"] * n_iv
    )
    return TauComponents(
        market_id=snap.market_id,
        delta_prob=dp,
        vol_zscore=vz,
        implied_vol=iv,
        norm_delta_prob=n_dp,
        norm_vol_zscore=n_vz,
        norm_implied_vol=n_iv,
        tau=tau,
        valid=True,
    )


def aggregate_tau_per_category(taus: Iterable[TauComponents]) -> float:
    """τ_category = max(τ_per_contract for valid contracts)."""
    valid = [t.tau for t in taus if t.valid]
    return max(valid) if valid else 0.0


def compute_tau_final(tau_crypto: float, tau_macro: float, category_weights: dict) -> float:
    """τ_final = 0.7·τ_crypto + 0.3·τ_macro (per Gemma)."""
    return (
        category_weights["crypto"] * tau_crypto
        + category_weights["macro"] * tau_macro
    )


def compute_pearson_rho(
    btc_returns: list[float], poly_bear_prob_returns: list[float]
) -> float | None:
    """Pearson correlation rolling. Returns None if <30 paired points."""
    n = min(len(btc_returns), len(poly_bear_prob_returns))
    if n < 30:
        return None
    x = btc_returns[-n:]
    y = poly_bear_prob_returns[-n:]
    try:
        mx = statistics.mean(x)
        my = statistics.mean(y)
        sx = statistics.pstdev(x)
        sy = statistics.pstdev(y)
        if sx <= 0 or sy <= 0:
            return None
        cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y)) / n
        return cov / (sx * sy)
    except Exception:
        return None
