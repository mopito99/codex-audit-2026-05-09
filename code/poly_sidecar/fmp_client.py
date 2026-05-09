"""FMP (Financial Modeling Prep) economic_calendar client.

Decisión Gemma 4 (2026-05-05): polling cada 1h al endpoint
/api/v3/economic_calendar para obtener calendario de eventos macro
(FOMC, CPI, NFP, ECB, PCE, GDP, ISM, etc.) con consensus + previous + actual
cuando publicado.

Auth: ?apikey=<KEY>  (env var FMP_API_KEY)
Free tier: 250 req/día (más que suficiente, polling 1h = 24 req/día).
"""
from __future__ import annotations
import datetime as dt
import logging
import os
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger("poly_sidecar.fmp")

FMP_BASE = "https://financialmodelingprep.com/stable"
ENDPOINT = f"{FMP_BASE}/economic-calendar"
KEY_FILE = "/home/administrator/.config/fmp/api_key"


def _load_api_key() -> str:
    # Prefer env var, fallback to chmod-600 file (consistent with Gemini bridge).
    env_key = os.environ.get("FMP_API_KEY", "").strip()
    if env_key:
        return env_key
    try:
        with open(KEY_FILE) as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""
    except Exception:
        return ""


@dataclass
class MacroEvent:
    event: str
    country: str
    date: str           # ISO datetime
    actual: float | None
    previous: float | None
    estimate: float | None
    change: float | None
    change_pct: float | None
    impact: str | None  # "Low" | "Medium" | "High"


# Mapping de keywords → categoría VelocityQuant (event_multipliers)
EVENT_KEYWORDS = {
    "FOMC": ["FOMC", "Fed Interest Rate", "Federal Funds Rate"],
    "CPI": ["CPI", "Consumer Price Index", "Inflation Rate"],
    "PCE": ["PCE", "Core PCE", "Personal Consumption Expenditures"],
    "NFP": ["Non Farm Payrolls", "Nonfarm Payrolls", "Employment"],
    "ECB": ["ECB Interest Rate", "ECB Press Conference", "ECB Rate"],
    "GDP": ["GDP", "Gross Domestic Product"],
    "ISM": ["ISM Manufacturing", "ISM Services", "ISM Non-Manufacturing"],
    "JOLTS": ["JOLTS"],
    "BoJ_BoE": ["BoJ Interest Rate", "BoE Interest Rate"],
}

# Países que nos interesan principalmente
TRACKED_COUNTRIES = {"US", "EU", "GB", "JP", "CN"}


class FMPClient:
    def __init__(self, api_key: str | None = None, timeout: float = 12.0):
        self.api_key = api_key if api_key is not None else _load_api_key()
        self._client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        self.last_ok = 0.0
        self.errors = 0
        self.last_error = ""
        self._cache: list[MacroEvent] = []
        self._cache_ts = 0.0

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @property
    def status(self) -> str:
        if not self.configured:
            return "no_api_key"
        if self.last_ok == 0:
            return "uninitialized"
        age = time.time() - self.last_ok
        if age > 7200:   # >2h sin actualizar
            return "stale"
        return "ok"

    async def fetch_calendar(
        self, days_ahead: int = 7, days_behind: int = 0
    ) -> list[MacroEvent]:
        """Fetch economic calendar in window [today-days_behind, today+days_ahead]."""
        if not self.configured:
            return []
        now = dt.datetime.utcnow().date()
        d_from = (now - dt.timedelta(days=days_behind)).isoformat()
        d_to = (now + dt.timedelta(days=days_ahead)).isoformat()
        try:
            r = await self._client.get(
                ENDPOINT,
                params={"from": d_from, "to": d_to, "apikey": self.api_key},
            )
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and "Error Message" in data:
                self.errors += 1
                self.last_error = data["Error Message"][:120]
                return []
            events = []
            for e in data:
                try:
                    events.append(MacroEvent(
                        event=str(e.get("event", "")),
                        country=str(e.get("country", "")),
                        date=str(e.get("date", "")),
                        actual=_to_float(e.get("actual")),
                        previous=_to_float(e.get("previous")),
                        estimate=_to_float(e.get("estimate")),
                        change=_to_float(e.get("change")),
                        change_pct=_to_float(e.get("changePercentage")),
                        impact=str(e.get("impact", "")) or None,
                    ))
                except Exception:
                    continue
            self._cache = events
            self._cache_ts = time.time()
            self.last_ok = time.time()
            return events
        except httpx.HTTPStatusError as e:
            self.errors += 1
            self.last_error = f"HTTP {e.response.status_code}"
            try:
                body = e.response.json()
                self.last_error = str(body.get("Error Message", self.last_error))[:120]
            except Exception:
                pass
            return []
        except Exception as e:
            self.errors += 1
            self.last_error = str(e)[:120]
            return []

    def cached_events(self) -> list[MacroEvent]:
        return list(self._cache)

    @staticmethod
    def categorize(event: MacroEvent) -> str | None:
        """Match event title against EVENT_KEYWORDS → VelocityQuant category."""
        title = event.event.lower()
        for cat, keywords in EVENT_KEYWORDS.items():
            for kw in keywords:
                if kw.lower() in title:
                    return cat
        return None

    @staticmethod
    def is_tracked(event: MacroEvent) -> bool:
        if event.country not in TRACKED_COUNTRIES:
            return False
        if not FMPClient.categorize(event):
            return False
        return True


def _to_float(x) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def upcoming_events(events: list[MacroEvent], hours_ahead: int = 24) -> list[MacroEvent]:
    """Filter to events within the next `hours_ahead` and tracked categories."""
    now = dt.datetime.utcnow()
    horizon = now + dt.timedelta(hours=hours_ahead)
    out = []
    for e in events:
        if not FMPClient.is_tracked(e):
            continue
        try:
            ts = dt.datetime.fromisoformat(e.date.replace("Z", "+00:00"))
            if ts.tzinfo:
                ts = ts.replace(tzinfo=None)
            if now <= ts <= horizon:
                out.append(e)
        except Exception:
            continue
    return out


def time_to_next_event(events: list[MacroEvent]) -> tuple[MacroEvent | None, float | None]:
    """Returns (next_event, seconds_until) for closest tracked upcoming event."""
    upcoming = upcoming_events(events, hours_ahead=24 * 14)
    if not upcoming:
        return None, None
    now = dt.datetime.utcnow()
    best = None
    best_dt = None
    for e in upcoming:
        try:
            ts = dt.datetime.fromisoformat(e.date.replace("Z", "+00:00"))
            if ts.tzinfo:
                ts = ts.replace(tzinfo=None)
            sec = (ts - now).total_seconds()
            if sec >= 0 and (best_dt is None or sec < best_dt):
                best, best_dt = e, sec
        except Exception:
            continue
    return best, best_dt
