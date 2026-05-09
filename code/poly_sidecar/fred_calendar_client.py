"""FRED Releases Calendar Client.

Reemplaza FMP economic_calendar (HTTP 402 desde 2025-08-31) usando
endpoint /fred/release/dates de FRED API. FRED es gov gratis sin límite
con la api key registrada.

Releases relevantes para nuestros gates:
- 53 → Employment Situation (NFP + Unemployment Rate, BLS)
- 10 → Consumer Price Index (BLS)
- 21 → Personal Income and Outlays (PCE, BEA)
- 326 → FOMC Meeting Minutes / Statement
- 82 → Producer Price Index (PPI, BLS)
- 87 → Retail Trade

API endpoint: https://api.stlouisfed.org/fred/release/dates
  ?release_id=53&api_key=KEY&file_type=json
  &include_release_dates_with_no_data=false
  &realtime_start=2026-01-01&realtime_end=2026-12-31

FRED expone fechas de release pasadas + futuras (las próximas 12-24 meses).
Se complementa con bls_client.py que expone los actual values.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


LOGGER = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred/release/dates"
KEY_FILE = Path("/home/administrator/.config/fred/api_key")

# Release ID mapping → category usado por sigma/SF lookup
# Verified 2026-05-08 vía /fred/releases endpoint (IDs cambiaron en FRED 2026)
RELEASE_TO_CATEGORY: dict[int, str] = {
    50:  "NFP",          # Employment Situation
    10:  "CPI",          # Consumer Price Index
    54:  "PCE",          # Personal Income and Outlays (PCE)
    101: "FOMC",         # FOMC Press Release
    46:  "PPI",          # Producer Price Index
    9:   "RETAIL_SALES", # Advance Monthly Sales for Retail and Food Services
    53:  "GDP",          # Gross Domestic Product
    192: "JOLTS",        # Job Openings and Labor Turnover Survey
}

CATEGORY_TO_RELEASE: dict[str, int] = {v: k for k, v in RELEASE_TO_CATEGORY.items()}

# Release timing convention (UTC) — most BLS releases at 12:30 UTC (8:30 ET)
# FOMC at 18:00 UTC (2pm ET). Customizable.
RELEASE_HOUR_UTC: dict[str, int] = {
    "NFP": 12,        # 8:30 ET
    "CPI": 12,
    "PCE": 12,
    "PPI": 12,
    "RETAIL_SALES": 12,
    "FOMC": 18,       # 2:00 ET
    "GDP": 12,
    "JOLTS": 14,      # 10:00 ET
    "ISM": 14,
}
RELEASE_MINUTE_UTC: dict[str, int] = {
    "NFP": 30,
    "CPI": 30,
    "PCE": 30,
    "PPI": 30,
    "RETAIL_SALES": 30,
    "FOMC": 0,
    "GDP": 30,
    "JOLTS": 0,
    "ISM": 0,
}


@dataclass
class CalendarEvent:
    release_id: int
    category: str
    release_name: str
    date: str            # ISO date "YYYY-MM-DD"
    datetime_utc: str    # ISO datetime with assumed time
    is_future: bool


def _load_api_key() -> str:
    env = os.environ.get("FRED_API_KEY", "").strip()
    if env:
        return env
    if KEY_FILE.exists():
        return KEY_FILE.read_text().strip()
    raise RuntimeError("FRED API key missing")


class FREDCalendarClient:
    """Calendar of upcoming/past macro releases via FRED /release/dates."""

    def __init__(self, api_key: str | None = None, timeout: float = 10.0):
        self.api_key = api_key if api_key is not None else _load_api_key()
        self.timeout = timeout
        self._last_sync_ts: float | None = None
        self._last_error: str = ""
        self._errors: int = 0
        self._cache: dict[int, list[CalendarEvent]] = {}
        self._release_names: dict[int, str] = {}

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @property
    def status(self) -> str:
        if self._last_sync_ts is None:
            return "uninitialized"
        if (time.time() - self._last_sync_ts) > 3600:
            return "stale"
        if self._errors > 5:
            return "degraded"
        return "ok"

    def fetch_release_dates(
        self,
        release_id: int,
        days_back: int = 60,
        days_ahead: int = 90,
    ) -> list[CalendarEvent]:
        """Fetch release dates for a single release_id.

        FRED quirk: realtime_start/end no aplican al endpoint /release/dates
        (HTTP 500). Traemos la última ventana con sort=desc y filtramos
        en cliente.
        """
        today = dt.date.today()
        date_min = today - dt.timedelta(days=days_back)
        date_max = today + dt.timedelta(days=days_ahead)
        # FRED quirk: limit=200 causa HTTP 500 en algunos releases (53,10,87).
        # limit=100 funciona consistentemente. Empíricamente verificado 2026-05-08.
        params = {
            "release_id": release_id,
            "api_key": self.api_key,
            "file_type": "json",
            "include_release_dates_with_no_data": "true",
            "sort_order": "desc",
            "limit": "100",
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(FRED_BASE, params=params)
                resp.raise_for_status()
                data = resp.json()
            release_dates = data.get("release_dates", [])
            category = RELEASE_TO_CATEGORY.get(release_id, f"UNKNOWN_{release_id}")
            release_name = (
                data.get("release_dates", [{}])[0].get("release_name", "")
                if release_dates else ""
            ) or category
            self._release_names[release_id] = release_name

            events = []
            today_str = today.isoformat()
            for row in release_dates:
                date_str = row.get("date")
                if not date_str:
                    continue
                # Filter by window
                if date_str < date_min.isoformat() or date_str > date_max.isoformat():
                    continue
                hour = RELEASE_HOUR_UTC.get(category, 12)
                minute = RELEASE_MINUTE_UTC.get(category, 30)
                dt_utc = f"{date_str}T{hour:02d}:{minute:02d}:00+00:00"
                events.append(CalendarEvent(
                    release_id=release_id,
                    category=category,
                    release_name=release_name,
                    date=date_str,
                    datetime_utc=dt_utc,
                    is_future=date_str > today_str,
                ))
            self._cache[release_id] = events
            self._last_sync_ts = time.time()
            return events
        except (httpx.HTTPError, KeyError) as exc:
            self._errors += 1
            self._last_error = f"FRED calendar error rid={release_id}: {exc}"
            LOGGER.warning(self._last_error)
            return []

    def fetch_all_relevant(self) -> dict[int, list[CalendarEvent]]:
        """Fetch all releases mapped in RELEASE_TO_CATEGORY."""
        for rid in RELEASE_TO_CATEGORY:
            self.fetch_release_dates(rid)
        return dict(self._cache)

    def upcoming_24h(self) -> list[CalendarEvent]:
        """Events in [now, now+24h], merged across releases."""
        now = dt.datetime.now(dt.timezone.utc)
        end = now + dt.timedelta(hours=24)
        result = []
        for events in self._cache.values():
            for ev in events:
                event_dt = dt.datetime.fromisoformat(ev.datetime_utc)
                if now <= event_dt <= end:
                    result.append(ev)
        result.sort(key=lambda e: e.datetime_utc)
        return result

    def next_event_for_category(self, category: str) -> CalendarEvent | None:
        rid = CATEGORY_TO_RELEASE.get(category)
        if rid is None or rid not in self._cache:
            return None
        now = dt.datetime.now(dt.timezone.utc)
        future = [
            ev for ev in self._cache[rid]
            if dt.datetime.fromisoformat(ev.datetime_utc) > now
        ]
        if not future:
            return None
        return min(future, key=lambda e: e.datetime_utc)

    def last_event_for_category(self, category: str) -> CalendarEvent | None:
        rid = CATEGORY_TO_RELEASE.get(category)
        if rid is None or rid not in self._cache:
            return None
        now = dt.datetime.now(dt.timezone.utc)
        past = [
            ev for ev in self._cache[rid]
            if dt.datetime.fromisoformat(ev.datetime_utc) <= now
        ]
        if not past:
            return None
        return max(past, key=lambda e: e.datetime_utc)

    def to_state_dict(self) -> dict[str, Any]:
        upc = self.upcoming_24h()
        upc_serialized = [
            {
                "event": ev.release_name,
                "category": ev.category,
                "date": ev.date,
                "datetime_utc": ev.datetime_utc,
                "release_id": ev.release_id,
            }
            for ev in upc
        ]
        return {
            "configured": self.configured,
            "status": self.status,
            "errors": self._errors,
            "last_error": self._last_error,
            "last_sync_ts": self._last_sync_ts,
            "tracked_release_ids": list(RELEASE_TO_CATEGORY.keys()),
            "events_in_cache": sum(len(v) for v in self._cache.values()),
            "upcoming_24h": upc_serialized,
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cli = FREDCalendarClient()
    print(f"FRED Calendar configured: {cli.configured}")
    cli.fetch_all_relevant()
    state = cli.to_state_dict()
    print(json.dumps({
        k: state[k] for k in ["status", "errors", "events_in_cache", "tracked_release_ids"]
    }, indent=2, default=str))
    print()
    print(f"=== upcoming 24h: {len(state['upcoming_24h'])} events ===")
    for ev in state["upcoming_24h"]:
        print(f"  {ev['datetime_utc']} {ev['category']:14s} {ev['event']}")
    print()
    print(f"=== next NFP ===")
    ne = cli.next_event_for_category("NFP")
    print(json.dumps(ne.__dict__ if ne else None, indent=2, default=str))
    print()
    print(f"=== last NFP ===")
    le = cli.last_event_for_category("NFP")
    print(json.dumps(le.__dict__ if le else None, indent=2, default=str))
