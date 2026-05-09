"""BLS (Bureau of Labor Statistics) API client.

Reemplaza FMP (HTTP 402 desde 2025-08-31) como fuente de actuals para
eventos macro NFP, CPI, PCE, Unemployment Rate.

API gratis sin key (25 calls/day). Con key registrada (gratis): 500 calls/day.

Series IDs relevantes:
- CES0000000001 → Total Nonfarm Payrolls (NFP, level in thousands)
- LNS14000000   → Unemployment Rate (U-3, percent)
- CUUR0000SA0   → CPI All Urban Consumers (level, NSA)
- CUUR0000SA0L1E → CPI Core (excluding food/energy, level)

NFP "actual" se computa: PAYEMS_M(this) - PAYEMS_M(prev) en miles.
CPI "actual" típicamente reporta como % YoY o MoM, computar diff vs previous.

Sin auth para 25 calls/día es suficiente para nuestro polling cada 5min en
ventana T-15min → T+30min de cada release (~9 calls por evento).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


LOGGER = logging.getLogger(__name__)

BLS_BASE = "https://api.bls.gov/publicAPI/v2/timeseries/data"
KEY_FILE = Path("/home/administrator/.config/bls/api_key")

# Categorías mapeadas a series_id
SERIES_BY_CATEGORY: dict[str, str] = {
    "NFP":           "CES0000000001",   # Total Nonfarm, all employees, thousands
    "UNEMPLOYMENT":  "LNS14000000",      # Unemployment Rate, percent
    "CPI":           "CUUR0000SA0",      # CPI-U, NSA, index 1982-84=100
    "CPI_CORE":      "CUUR0000SA0L1E",   # CPI Core (exc food/energy)
    # PCE viene de BEA, no BLS — añadir bea_client.py si necesario
}


@dataclass
class BLSObservation:
    series_id: str
    year: int
    period: str       # "M01"-"M12" mensual, "Q01"-"Q04" trimestral
    period_name: str  # "January", "Q1" etc
    value: float
    is_latest: bool
    is_preliminary: bool


def _load_api_key() -> str | None:
    env = os.environ.get("BLS_API_KEY", "").strip()
    if env:
        return env
    if KEY_FILE.exists():
        return KEY_FILE.read_text().strip() or None
    return None


def parse_period_to_month(period: str) -> int | None:
    """M01..M12 → 1..12. Returns None for non-monthly."""
    if period and period.startswith("M") and len(period) == 3:
        try:
            m = int(period[1:])
            if 1 <= m <= 12:
                return m
        except ValueError:
            pass
    return None


class BLSClient:
    """Lightweight BLS REST client with sync polling."""

    def __init__(self, api_key: str | None = None, timeout: float = 12.0):
        self.api_key = api_key if api_key is not None else _load_api_key()
        self.timeout = timeout
        self._last_sync_ts: float | None = None
        self._last_error: str = ""
        self._errors: int = 0
        self._cache: dict[str, list[BLSObservation]] = {}
        # [P3.6.5] Cache TTL agresivo · SHA-256 sobre tuple parsed data
        # Si hash igual al previo → extender TTL a 3600s · evita consumir API
        self._prev_data_hash: dict[str, str] = {}
        self._cat_last_fetch_ts: dict[str, float] = {}
        self._cat_aggressive_ttl: dict[str, bool] = {}

    # ────────────────────────────────────────────────────────────────────

    @property
    def configured(self) -> bool:
        return True  # works without API key (25/day limit)

    @property
    def status(self) -> str:
        if self._last_sync_ts is None:
            return "uninitialized"
        if (time.time() - self._last_sync_ts) > 1800:
            return "stale"
        if self._errors > 5:
            return "degraded"
        return "ok"

    @property
    def errors(self) -> int:
        return self._errors

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def last_sync_ts(self) -> float | None:
        return self._last_sync_ts

    # ────────────────────────────────────────────────────────────────────

    def fetch_series(
        self,
        series_id: str,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> list[BLSObservation]:
        """Fetch series observations. Returns list sorted descending (latest first)."""
        params: dict[str, Any] = {"seriesid": [series_id]}
        if start_year:
            params["startyear"] = str(start_year)
        if end_year:
            params["endyear"] = str(end_year)
        if self.api_key:
            params["registrationkey"] = self.api_key

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(BLS_BASE, json=params)
                resp.raise_for_status()
                data = resp.json()

            if data.get("status") != "REQUEST_SUCCEEDED":
                msg = data.get("message", ["unknown"])[0] if data.get("message") else "unknown"
                self._errors += 1
                self._last_error = f"BLS status={data.get('status')} message={msg}"
                LOGGER.warning(self._last_error)
                return []

            series_list = data.get("Results", {}).get("series", [])
            if not series_list:
                return []
            raw = series_list[0].get("data", [])
            obs = []
            for row in raw:
                try:
                    is_prelim = any(
                        f.get("code") == "P" for f in row.get("footnotes", [])
                    )
                    is_latest = row.get("latest") == "true"
                    obs.append(BLSObservation(
                        series_id=series_id,
                        year=int(row["year"]),
                        period=row["period"],
                        period_name=row["periodName"],
                        value=float(row["value"]),
                        is_latest=is_latest,
                        is_preliminary=is_prelim,
                    ))
                except (KeyError, ValueError, TypeError) as exc:
                    LOGGER.debug(f"BLS row skip: {exc}")
                    continue

            self._last_sync_ts = time.time()
            self._cache[series_id] = obs
            return obs

        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            self._errors += 1
            self._last_error = f"BLS HTTP error: {exc}"
            LOGGER.warning(self._last_error)
            return []

    # ────────────────────────────────────────────────────────────────────

    def get_latest_actual(
        self,
        category: str,
        force_refresh: bool = False,
    ) -> dict[str, Any] | None:
        """Compute "actual surprise input" for a category.

        For NFP: returns dict with `month_change_thousands` (current - previous).
        For CPI: returns dict with `mom_pct_change` and `yoy_pct_change`.
        For UNEMPLOYMENT: returns level percent.

        Args:
            category: NFP/CPI/CPI_CORE/UNEMPLOYMENT.
            force_refresh: si True bypassa cache + aggressive_ttl · forza HTTP call BLS.
                Activado por sidecar durante macro window T-30→T+15min para garantizar
                SLA <120s post-release (Codex CRITICAL-NEW-02 fix · firmado Gemma r152-M2-bis).

        Returns None si data insufficient o category unknown.
        """
        series_id = SERIES_BY_CATEGORY.get(category)
        if not series_id:
            return None

        # [r152-M2-bis] BLS TTL bypass durante macro window
        # firmado Gemma · Codex CRITICAL-NEW-02 fix
        if force_refresh:
            cached = self.fetch_series(series_id)
            if not cached:
                return None
            self._cat_last_fetch_ts[category] = time.time()
            LOGGER.info(
                f"[r152-M2-bis] {category} force_refresh=True · BLS HTTP call forced "
                f"(macro window) · cache + aggressive_ttl bypassed"
            )
        else:
            # [P3.6.5] Cache TTL adaptativo (LOW frequency · fuera de macro window)
            # - default TTL: 300s (5min)
            # - aggressive TTL: 3600s (1h) si hash datos parseados igual al previo
            ttl = 3600 if self._cat_aggressive_ttl.get(category, False) else 300
            last_fetch = self._cat_last_fetch_ts.get(category, 0.0)
            cached = self._cache.get(series_id)
            if not cached or (time.time() - last_fetch) > ttl:
                cached = self.fetch_series(series_id)
                if not cached:
                    return None
                self._cat_last_fetch_ts[category] = time.time()

        cur_year = max(o.year for o in cached)
        # Sort descending by (year, month)
        sorted_obs = sorted(
            [o for o in cached if parse_period_to_month(o.period)],
            key=lambda o: (o.year, parse_period_to_month(o.period) or 0),
            reverse=True,
        )
        if len(sorted_obs) < 2:
            return None

        latest = sorted_obs[0]
        previous = sorted_obs[1]

        result: dict[str, Any] = {
            "category": category,
            "series_id": series_id,
            "latest_year": latest.year,
            "latest_period": latest.period,
            "latest_period_name": latest.period_name,
            "latest_value": latest.value,
            "latest_is_preliminary": latest.is_preliminary,
            "previous_value": previous.value,
            "fetched_at": time.time(),
        }

        if category == "NFP":
            # Change in thousands of jobs
            result["month_change_thousands"] = round(latest.value - previous.value, 1)
            result["actual_for_sf"] = result["month_change_thousands"]
        elif category == "CPI" or category == "CPI_CORE":
            mom = (latest.value - previous.value) / previous.value * 100
            result["mom_pct_change"] = round(mom, 4)
            # YoY needs 13 obs back
            year_back_target = (latest.year - 1, parse_period_to_month(latest.period))
            yoy_obs = next(
                (o for o in sorted_obs
                 if o.year == year_back_target[0]
                 and parse_period_to_month(o.period) == year_back_target[1]),
                None,
            )
            if yoy_obs:
                yoy_pct_raw = (latest.value - yoy_obs.value) / yoy_obs.value * 100
                # [SAFETY-DIM] Hard-assert firmado Gemma S-C-CLOSE-R150-HEX-20260509
                # Range histórico CPI YoY: -2.1% (2009) a 14.6% (1980)
                # Range conservador [0, 20] excluye deflation periods · ampliable
                # a [-3, 20] si entramos en periodo deflacionario futuro.
                assert 0 <= yoy_pct_raw <= 20, (
                    f"Dimensionality Error: CPI YoY {yoy_pct_raw} outside "
                    f"realistic bounds [0, 20]. Series={series_id} "
                    f"latest={latest.value} yoy_obs={yoy_obs.value}"
                )
                result["yoy_pct_change"] = round(yoy_pct_raw, 4)
            result["actual_for_sf"] = result.get("yoy_pct_change", result["mom_pct_change"])
        elif category == "UNEMPLOYMENT":
            result["actual_for_sf"] = latest.value
            result["pp_change"] = round(latest.value - previous.value, 2)

        # [P3.6.5] SHA-256 hash sobre tuple parsed data
        # Si hash igual al previo → próximo poll usa TTL agresivo 3600s
        # Tuple: (series_id, year, period, value, prev_value) · estable vs raw JSON
        hash_tuple = (
            series_id,
            latest.year,
            latest.period,
            latest.value,
            previous.value,
        )
        cur_hash = hashlib.sha256(
            json.dumps(hash_tuple, sort_keys=True).encode()
        ).hexdigest()
        prev_hash = self._prev_data_hash.get(category)
        if prev_hash == cur_hash:
            self._cat_aggressive_ttl[category] = True
        else:
            self._cat_aggressive_ttl[category] = False
            self._prev_data_hash[category] = cur_hash

        return result

    # ────────────────────────────────────────────────────────────────────

    def to_state_dict(self) -> dict[str, Any]:
        """Return snapshot for /api/state.fmp-like exposure."""
        return {
            "configured": self.configured,
            "status": self.status,
            "errors": self.errors,
            "last_error": self.last_error,
            "last_sync_ts": self.last_sync_ts,
            "categories_supported": list(SERIES_BY_CATEGORY.keys()),
        }


if __name__ == "__main__":
    # CLI smoke test
    logging.basicConfig(level=logging.INFO)
    cli = BLSClient()
    print(f"BLS configured: {cli.configured}")
    for cat in ["NFP", "UNEMPLOYMENT", "CPI"]:
        print(f"\n=== {cat} ===")
        result = cli.get_latest_actual(cat)
        print(json.dumps(result, indent=2, default=str))
    print(f"\nstate: {cli.to_state_dict()}")
