"""BTC consensus weighted_median feed — 3-source (Coinbase + Kraken + Pyth).

Spec firmada Gemma r90/r107/r108/r109:
  - Coinbase Advanced Trade  weight 0.5  (primary, REST public)
  - Kraken                   weight 0.3  (secondary, REST public)
  - Pyth Hermes              weight 0.2  (fallback, daily snapshots)
  - Outlier rejection: |source − median| > 0.5% del median
  - Stale: sources_alive < 2 → CAUTELA forced (firma r109 §1b STRICTER)
  - Concurrent fetch via asyncio.gather, timeout 2.0s per source, 2.5s total
  - Buffer rolling in-memory para kill_switch logic (firmado r93/r107)

NO requiere auth en ninguna source (todas public market data).

Endpoints:
  - Coinbase: https://api.coinbase.com/api/v3/brokerage/market/products/BTC-USD/ticker
  - Kraken:   https://api.kraken.com/0/public/Ticker?pair=XBTUSD
  - Pyth:     https://hermes.pyth.network/v2/updates/price/latest

Spec-Commit reference: risk_config.json @ r93/r107/r108/r109 firmas
Signed-by-spec: Gemma r90 + r107 + r108 + r109
"""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger("poly_sidecar.btc_feed")

# Endpoints (sin auth — public market data)
COINBASE_TICKER_URL = "https://api.coinbase.com/api/v3/brokerage/market/products/BTC-USD/ticker"
KRAKEN_TICKER_URL = "https://api.kraken.com/0/public/Ticker?pair=XBTUSD"
PYTH_HERMES_URL = "https://hermes.pyth.network/v2/updates/price/latest"
PYTH_BTC_USD_FEED_ID = "0xe62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43"

# Constants firmadas r90/r107/r108/r109
DEFAULT_WEIGHTS = {"coinbase": 0.5, "kraken": 0.3, "pyth": 0.2}
DEFAULT_OUTLIER_THRESHOLD_PCT = 0.005  # 0.5% del median
DEFAULT_TIMEOUT_PER_SOURCE_S = 2.0     # firmado r109 §1a
DEFAULT_TIMEOUT_TOTAL_S = 2.5          # firmado r109 §1a
DEFAULT_MIN_SOURCES_ALIVE = 2          # firmado r109 §1b STRICTER

# Buffer rolling para kill_switch (firmado r107/r108)
DEFAULT_BUFFER_RETAIN_SECONDS = 600.0  # 10 min de samples
DEFAULT_KILL_SWITCH_WINDOW_SECONDS = 300.0  # 5 min


@dataclass
class SourceResult:
    """Resultado de un source individual."""
    name: str
    price_usd: float | None
    fetch_ms: float
    error: str | None = None

    @property
    def alive(self) -> bool:
        return self.price_usd is not None and self.price_usd > 0


@dataclass
class ConsensusResult:
    """Output del weighted_median consensus."""
    consensus_price: float | None
    sources_contributing: int
    sources_total_attempted: int
    outliers_rejected: list[str]
    is_stale: bool
    stale_reason: str | None
    fetch_total_ms: float
    last_update_ts: float
    weights_used: dict[str, float]
    raw_per_source: dict[str, dict]  # debug info


def weighted_median(values_with_weights: list[tuple[float, float]]) -> float | None:
    """Calcula weighted median.

    Args:
        values_with_weights: [(value, weight), ...] con weights normalizados a sum=1.0

    Returns:
        Weighted median value, o None si lista vacía.
    """
    if not values_with_weights:
        return None
    if len(values_with_weights) == 1:
        return values_with_weights[0][0]

    # Sort by value
    sorted_vw = sorted(values_with_weights, key=lambda x: x[0])
    total_weight = sum(w for _, w in sorted_vw)
    if total_weight <= 0:
        return None

    cumulative = 0.0
    target = total_weight / 2.0
    for v, w in sorted_vw:
        cumulative += w
        if cumulative >= target:
            return v
    return sorted_vw[-1][0]


def reject_outliers(
    sources: dict[str, float],
    threshold_pct: float = DEFAULT_OUTLIER_THRESHOLD_PCT,
) -> tuple[dict[str, float], list[str]]:
    """Rejecta outliers >threshold_pct del median.

    Args:
        sources: {"coinbase": 81000, "kraken": 81100, ...}
        threshold_pct: 0.005 = 0.5%

    Returns:
        (filtered_sources, rejected_names)
    """
    if len(sources) < 2:
        return sources, []

    import statistics as st
    prices = list(sources.values())
    median_price = st.median(prices)

    if median_price <= 0:
        return sources, []

    filtered = {}
    rejected = []
    for name, price in sources.items():
        deviation_pct = abs(price - median_price) / median_price
        if deviation_pct > threshold_pct:
            rejected.append(name)
            logger.info(
                f"outlier rejected: {name} price=${price:.2f} median=${median_price:.2f} "
                f"deviation={deviation_pct:.4%} > threshold={threshold_pct:.4%}"
            )
        else:
            filtered[name] = price

    return filtered, rejected


class BTCBuffer:
    """Buffer rolling de BTC consensus prices con timestamps.

    Spec r107/r108: el kill_switch lee de aquí para detectar moves >X% en window.
    """

    def __init__(self, retain_seconds: float = DEFAULT_BUFFER_RETAIN_SECONDS):
        self.retain_seconds = retain_seconds
        self.samples: list[tuple[float, float]] = []  # [(ts, price), ...]

    def push(self, ts: float, price: float) -> None:
        if price is None or price <= 0:
            return
        self.samples.append((ts, price))
        # Cleanup old samples
        cutoff = ts - self.retain_seconds
        self.samples = [(t, p) for t, p in self.samples if t > cutoff]

    def max_move_pct_in_window(
        self,
        window_seconds: float = DEFAULT_KILL_SWITCH_WINDOW_SECONDS,
    ) -> float | None:
        """Returns max((max_price - min_price) / min_price * 100) en últimos N seconds.

        Returns None si insufficient samples (< 2 in window).
        """
        if len(self.samples) < 2:
            return None
        now = self.samples[-1][0]
        cutoff = now - window_seconds
        in_window = [(t, p) for t, p in self.samples if t >= cutoff]
        if len(in_window) < 2:
            return None
        prices = [p for _, p in in_window]
        max_p = max(prices)
        min_p = min(prices)
        if min_p <= 0:
            return None
        return ((max_p - min_p) / min_p) * 100.0

    def latest_price(self) -> float | None:
        if not self.samples:
            return None
        return self.samples[-1][1]

    def latest_ts(self) -> float | None:
        if not self.samples:
            return None
        return self.samples[-1][0]

    def __len__(self) -> int:
        return len(self.samples)


class BTCFeed:
    """3-source weighted_median consensus client.

    Backward-compatible API (mismo `get_price()` que antes) + new `get_consensus()`.
    """

    def __init__(
        self,
        timeout_per_source: float = DEFAULT_TIMEOUT_PER_SOURCE_S,
        timeout_total: float = DEFAULT_TIMEOUT_TOTAL_S,
        weights: dict[str, float] | None = None,
        outlier_threshold_pct: float = DEFAULT_OUTLIER_THRESHOLD_PCT,
        min_sources_alive: int = DEFAULT_MIN_SOURCES_ALIVE,
        buffer: BTCBuffer | None = None,
    ):
        self.timeout_per_source = timeout_per_source
        self.timeout_total = timeout_total
        self.weights = weights or DEFAULT_WEIGHTS
        self.outlier_threshold_pct = outlier_threshold_pct
        self.min_sources_alive = min_sources_alive
        self.buffer = buffer or BTCBuffer()

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_per_source, connect=2.0, read=timeout_per_source),
            follow_redirects=True,
        )
        self.errors = 0
        self.last_ok = 0.0
        self._last_consensus: ConsensusResult | None = None

    async def close(self) -> None:
        await self._client.aclose()

    async def _fetch_coinbase(self) -> SourceResult:
        t0 = time.time()
        try:
            r = await asyncio.wait_for(
                self._client.get(COINBASE_TICKER_URL),
                timeout=self.timeout_per_source,
            )
            r.raise_for_status()
            data = r.json()
            # Coinbase Advanced Trade returns: {"price": "81234.56", "time": "...", ...}
            price_str = data.get("price")
            if not price_str:
                # Fallback: bids/asks median
                bids = data.get("bids", [])
                asks = data.get("asks", [])
                if bids and asks:
                    bid = float(bids[0].get("price", 0))
                    ask = float(asks[0].get("price", 0))
                    if bid > 0 and ask > 0:
                        price = (bid + ask) / 2.0
                        return SourceResult("coinbase", price, (time.time() - t0) * 1000)
                return SourceResult("coinbase", None, (time.time() - t0) * 1000, "no price field")
            price = float(price_str)
            return SourceResult("coinbase", price, (time.time() - t0) * 1000)
        except asyncio.TimeoutError:
            return SourceResult("coinbase", None, (time.time() - t0) * 1000, "timeout")
        except Exception as e:
            return SourceResult("coinbase", None, (time.time() - t0) * 1000, f"{type(e).__name__}: {str(e)[:100]}")

    async def _fetch_kraken(self) -> SourceResult:
        t0 = time.time()
        try:
            r = await asyncio.wait_for(
                self._client.get(KRAKEN_TICKER_URL),
                timeout=self.timeout_per_source,
            )
            r.raise_for_status()
            data = r.json()
            # Kraken returns: {"result": {"XXBTZUSD": {"c": ["81234.5", "0.05"], ...}}}
            result = data.get("result", {})
            if not result:
                return SourceResult("kraken", None, (time.time() - t0) * 1000, "no result field")
            # Kraken usa "XXBTZUSD" como key normalmente, pero varía
            for pair_key, pair_data in result.items():
                last_trade = pair_data.get("c", [None])
                if last_trade and last_trade[0]:
                    price = float(last_trade[0])
                    if price > 0:
                        return SourceResult("kraken", price, (time.time() - t0) * 1000)
            return SourceResult("kraken", None, (time.time() - t0) * 1000, "no last trade price")
        except asyncio.TimeoutError:
            return SourceResult("kraken", None, (time.time() - t0) * 1000, "timeout")
        except Exception as e:
            return SourceResult("kraken", None, (time.time() - t0) * 1000, f"{type(e).__name__}: {str(e)[:100]}")

    async def _fetch_pyth(self) -> SourceResult:
        t0 = time.time()
        try:
            r = await asyncio.wait_for(
                self._client.get(PYTH_HERMES_URL, params=[("ids[]", PYTH_BTC_USD_FEED_ID)]),
                timeout=self.timeout_per_source,
            )
            r.raise_for_status()
            data = r.json()
            parsed = data.get("parsed", [])
            if not parsed:
                return SourceResult("pyth", None, (time.time() - t0) * 1000, "no parsed array")
            pd = parsed[0].get("price", {})
            raw = int(pd.get("price", 0))
            expo = int(pd.get("expo", 0))
            if raw <= 0:
                return SourceResult("pyth", None, (time.time() - t0) * 1000, "invalid raw price")
            price = raw * (10 ** expo)
            return SourceResult("pyth", price, (time.time() - t0) * 1000)
        except asyncio.TimeoutError:
            return SourceResult("pyth", None, (time.time() - t0) * 1000, "timeout")
        except Exception as e:
            return SourceResult("pyth", None, (time.time() - t0) * 1000, f"{type(e).__name__}: {str(e)[:100]}")

    async def get_consensus(self) -> ConsensusResult:
        """Fetch desde 3 sources EN PARALELO + outlier rejection + weighted_median.

        Spec firmada r90/r107/r109. Push al buffer si OK.
        """
        t0 = time.time()

        # Parallel fetch
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    self._fetch_coinbase(),
                    self._fetch_kraken(),
                    self._fetch_pyth(),
                    return_exceptions=False,
                ),
                timeout=self.timeout_total,
            )
        except asyncio.TimeoutError:
            # Total gather timeout — usar lo que haya respondido (probablemente nada)
            results = []

        fetch_total_ms = (time.time() - t0) * 1000

        # Map results
        source_results: dict[str, SourceResult] = {}
        for r in results:
            if isinstance(r, SourceResult):
                source_results[r.name] = r

        # Si todos los sources timeout, no hay results
        if not source_results:
            self.errors += 1
            return ConsensusResult(
                consensus_price=None,
                sources_contributing=0,
                sources_total_attempted=3,
                outliers_rejected=[],
                is_stale=True,
                stale_reason="all_sources_timeout_or_failed",
                fetch_total_ms=fetch_total_ms,
                last_update_ts=time.time(),
                weights_used=self.weights,
                raw_per_source={},
            )

        # Filter alive sources
        alive_sources = {r.name: r.price_usd for r in source_results.values() if r.alive}
        sources_alive = len(alive_sources)
        sources_total = len(source_results)

        # Stale check (firmado r109 §1b: sources_alive < 2 → stale)
        if sources_alive < self.min_sources_alive:
            self.errors += 1
            stale_reason = f"sources_alive ({sources_alive}) < min_required ({self.min_sources_alive})"
            return ConsensusResult(
                consensus_price=alive_sources.get(next(iter(alive_sources))) if alive_sources else None,
                sources_contributing=sources_alive,
                sources_total_attempted=sources_total,
                outliers_rejected=[],
                is_stale=True,
                stale_reason=stale_reason,
                fetch_total_ms=fetch_total_ms,
                last_update_ts=time.time(),
                weights_used=self.weights,
                raw_per_source={k: vars(v) for k, v in source_results.items()},
            )

        # Outlier rejection
        filtered_sources, rejected = reject_outliers(alive_sources, self.outlier_threshold_pct)

        # Re-check after rejection
        if len(filtered_sources) < self.min_sources_alive:
            self.errors += 1
            return ConsensusResult(
                consensus_price=None,
                sources_contributing=len(filtered_sources),
                sources_total_attempted=sources_total,
                outliers_rejected=rejected,
                is_stale=True,
                stale_reason=f"after_outlier_rejection sources ({len(filtered_sources)}) < min ({self.min_sources_alive})",
                fetch_total_ms=fetch_total_ms,
                last_update_ts=time.time(),
                weights_used=self.weights,
                raw_per_source={k: vars(v) for k, v in source_results.items()},
            )

        # Weighted median
        values_with_weights = [
            (price, self.weights.get(name, 0.0))
            for name, price in filtered_sources.items()
        ]
        # Normalize weights to sum=1.0 (en caso de que alguna source falte)
        total_w = sum(w for _, w in values_with_weights)
        if total_w > 0:
            values_with_weights = [(v, w / total_w) for v, w in values_with_weights]

        consensus_price = weighted_median(values_with_weights)

        if consensus_price is None or consensus_price <= 0:
            self.errors += 1
            return ConsensusResult(
                consensus_price=None,
                sources_contributing=len(filtered_sources),
                sources_total_attempted=sources_total,
                outliers_rejected=rejected,
                is_stale=True,
                stale_reason="weighted_median_returned_none_or_zero",
                fetch_total_ms=fetch_total_ms,
                last_update_ts=time.time(),
                weights_used=self.weights,
                raw_per_source={k: vars(v) for k, v in source_results.items()},
            )

        # Success — push al buffer
        ts = time.time()
        self.buffer.push(ts, consensus_price)
        self.last_ok = ts

        result = ConsensusResult(
            consensus_price=consensus_price,
            sources_contributing=len(filtered_sources),
            sources_total_attempted=sources_total,
            outliers_rejected=rejected,
            is_stale=False,
            stale_reason=None,
            fetch_total_ms=fetch_total_ms,
            last_update_ts=ts,
            weights_used=self.weights,
            raw_per_source={k: vars(v) for k, v in source_results.items()},
        )
        self._last_consensus = result
        return result

    async def get_price(self) -> tuple[float | None, float | None]:
        """Backward-compat API. Returns (consensus_price, last_update_ts).

        Used by sidecar.py polling loop.
        """
        result = await self.get_consensus()
        return result.consensus_price, result.last_update_ts

    @property
    def status(self) -> str:
        if self.last_ok == 0:
            return "uninitialized"
        age = time.time() - self.last_ok
        if age > 600:
            return "stale"
        return "ok"

    @property
    def last_consensus(self) -> ConsensusResult | None:
        return self._last_consensus
