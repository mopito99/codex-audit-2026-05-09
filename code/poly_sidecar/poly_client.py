"""Polymarket REST client — read-only, no auth.

Endpoints aprobados por Gemma 4 (Opción B, polling 5min):
  GET gamma-api/markets/{id}
  GET clob/prices/midpoint?token_id=X
  GET clob/prices/history?token_id=X&interval=4h&fidelity=5
  GET clob/spread?token_id=X
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"

logger = logging.getLogger("poly_sidecar.client")


@dataclass
class MarketSnapshot:
    market_id: str
    token_id: str
    midpoint: float | None
    spread: float | None
    volume_24h: float | None
    liquidity: float | None
    price_history: list[tuple[int, float]]  # [(unix_ms, price 0-1), ...]
    fetched_at: float


class PolymarketClient:
    """Async HTTP client. Tolera fallos por endpoint, respeta rate limits.

    Spec r91+ (Gemma firmado 2026-05-06): tracking de errores por TIPO
    para implementar jerarquía de stale L1-L4:
      L1: errors_404 (markets vencidos / no existen)         → ruido benigno
      L2: errors_5xx (Polymarket teniendo problemas)         → CAUTELA temporal
      L3: errors_timeout (network entre Dallas y CLOB)       → CAUTELA temporal
      L4: heartbeat_age > 600s (sidecar muerto, 2 ciclos)    → DEFENSIVO
    """

    def __init__(self, timeout: float = 10.0):
        self._client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        self.errors_by_endpoint: dict[str, int] = {}
        # r144 firma Gemma Q4 — timestamp del último 429 para adaptive backoff.
        self.last_429_ts: float | None = None
        # Spec r91+ tracking: errores por TIPO con timestamp para rate-windowed
        # Lista de (timestamp_unix, endpoint_name) para cada categoría.
        self.errors_404: list[tuple[float, str]] = []
        self.errors_5xx: list[tuple[float, str]] = []
        self.errors_timeout: list[tuple[float, str]] = []

    async def close(self) -> None:
        await self._client.aclose()

    def _track_error(self, kind: str, endpoint: str) -> None:
        import time as _t
        now = _t.time()
        if kind == "404":
            self.errors_404.append((now, endpoint))
        elif kind == "5xx":
            self.errors_5xx.append((now, endpoint))
        elif kind == "timeout":
            self.errors_timeout.append((now, endpoint))
        # Limpieza periódica: solo conservar últimos 30 min para cálculo de rate
        cutoff = now - 1800
        self.errors_404 = [(t, e) for t, e in self.errors_404 if t > cutoff]
        self.errors_5xx = [(t, e) for t, e in self.errors_5xx if t > cutoff]
        self.errors_timeout = [(t, e) for t, e in self.errors_timeout if t > cutoff]

    def errors_per_minute(self, kind: str, window_seconds: float = 300.0) -> float:
        """Rate de errores en últimos N segundos (default 5min).

        Returns errors/minute para ese tipo en esa ventana.
        """
        import time as _t
        now = _t.time()
        cutoff = now - window_seconds
        if kind == "404":
            buf = self.errors_404
        elif kind == "5xx":
            buf = self.errors_5xx
        elif kind == "timeout":
            buf = self.errors_timeout
        else:
            return 0.0
        count_in_window = sum(1 for t, _ in buf if t > cutoff)
        return (count_in_window / window_seconds) * 60.0

    async def _get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        endpoint_key = url.split("?")[0].rsplit("/", 1)[-1]
        try:
            r = await self._client.get(url, params=params)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            sc = e.response.status_code
            self.errors_by_endpoint[endpoint_key] = self.errors_by_endpoint.get(endpoint_key, 0) + 1
            if sc == 404:
                self._track_error("404", endpoint_key)
            elif sc == 429:
                # r144 firma Gemma Q4 — track 429 timestamp para adaptive backoff.
                import time as _t
                self.last_429_ts = _t.time()
                self._track_error("429", endpoint_key)
                logger.warning(f"polymarket {endpoint_key} 429 RATE LIMIT — backoff trigger")
            elif 500 <= sc < 600:
                self._track_error("5xx", endpoint_key)
                logger.warning(f"polymarket {endpoint_key} 5xx: {sc}")
            else:
                logger.warning(f"polymarket {endpoint_key} HTTP {sc}: {e}")
            return None
        except (httpx.TimeoutException, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            self.errors_by_endpoint[endpoint_key] = self.errors_by_endpoint.get(endpoint_key, 0) + 1
            self._track_error("timeout", endpoint_key)
            logger.warning(f"polymarket {endpoint_key} timeout: {e}")
            return None
        except Exception as e:
            self.errors_by_endpoint[endpoint_key] = self.errors_by_endpoint.get(endpoint_key, 0) + 1
            # Otros errores: clasificarlos como timeout-equivalent (network failure)
            self._track_error("timeout", endpoint_key)
            logger.warning(f"polymarket GET {url} params={params} error: {e}")
            return None

    async def get_market(self, market_id: str) -> dict | None:
        return await self._get_json(f"{GAMMA}/markets/{market_id}")

    async def get_midpoint(self, token_id: str) -> float | None:
        # CLOB returns 200 with {"error":"..."} when no orderbook exists.
        data = await self._get_json(f"{CLOB}/midpoint", {"token_id": token_id})
        if not data or "error" in data:
            return None
        try:
            return float(data.get("mid"))
        except Exception:
            return None

    async def get_spread(self, token_id: str) -> float | None:
        data = await self._get_json(f"{CLOB}/spread", {"token_id": token_id})
        if not data or "error" in data:
            return None
        try:
            return float(data.get("spread"))
        except Exception:
            return None

    async def get_history(
        self, token_id: str, interval: str = "1h", fidelity: int = 1
    ) -> list[tuple[int, float]]:
        """Returns list of (unix_ms, price 0-1) ordered ascending.

        CLOB supported intervals: 1m, 1h, 6h, 1d, 1w.
        Gemma 4 final decision (2026-05-05 06:04 UTC): use 1h × fidelity=1
        → 60 pts at 1min cadence. Better intra-NYSE-Open microstructure
        detection than 6h×5min (72 pts at 5min cadence).
        """
        data = await self._get_json(
            f"{CLOB}/prices-history",
            {"market": token_id, "interval": interval, "fidelity": fidelity},
        )
        if not data or "error" in data:
            return []
        history = data.get("history") or []
        out: list[tuple[int, float]] = []
        for pt in history:
            try:
                t_ms = int(pt.get("t") * 1000) if pt.get("t") else 0
                p = float(pt.get("p"))
                out.append((t_ms, p))
            except Exception:
                continue
        return out

    async def snapshot(self, market_id: str, yes_token_id: str) -> MarketSnapshot:
        """Aggregates the 4 endpoints in parallel."""
        import asyncio
        market_t = asyncio.create_task(self.get_market(market_id))
        mid_t = asyncio.create_task(self.get_midpoint(yes_token_id))
        spread_t = asyncio.create_task(self.get_spread(yes_token_id))
        hist_t = asyncio.create_task(self.get_history(yes_token_id, "1h", 1))
        market, mid, spread, hist = await asyncio.gather(
            market_t, mid_t, spread_t, hist_t, return_exceptions=False
        )

        vol24 = None
        liq = None
        if market:
            try:
                vol24 = float(market.get("volume24hr") or market.get("volume", 0) or 0)
                liq = float(
                    market.get("liquidityNum") or market.get("liquidity", 0) or 0
                )
            except Exception:
                pass

        return MarketSnapshot(
            market_id=market_id,
            token_id=yes_token_id,
            midpoint=mid,
            spread=spread,
            volume_24h=vol24,
            liquidity=liq,
            price_history=hist,
            fetched_at=time.time(),
        )
