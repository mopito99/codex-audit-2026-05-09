"""FMP-compatible drop-in replacement using FRED calendar + BLS actuals.

Provides identical interface to `fmp_client.FMPClient` so `sidecar.py`
keeps working without changes. Internally uses gov APIs (FRED + BLS) which
are gratis y sin tier-locks (FMP HTTP 402 desde 2025-08-31).

Usage in sidecar.py:
    # from fmp_client import FMPClient, time_to_next_event, upcoming_events
    from fmp_compat import FMPClient, time_to_next_event, upcoming_events

Same async API:
    fmp = FMPClient()
    await fmp.fetch_calendar(days_ahead=14, days_behind=0)
    events = fmp.cached_events()  # list[MacroEvent]
    fmp.configured / fmp.status / fmp.errors / fmp.last_error / fmp.last_ok
    FMPClient.categorize(event) / FMPClient.is_tracked(event)
    await fmp.close()
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any

from fred_calendar_client import (
    FREDCalendarClient,
    CATEGORY_TO_RELEASE,
    RELEASE_TO_CATEGORY,
    RELEASE_HOUR_UTC,
    RELEASE_MINUTE_UTC,
)
from bls_client import BLSClient
from forecasts_loader import get_forecast_for_event, get_active_forecast


LOGGER = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
# MacroEvent — same shape as fmp_client.MacroEvent for drop-in compat
# ────────────────────────────────────────────────────────────────────

@dataclass
class MacroEvent:
    event: str
    country: str
    date: str           # ISO datetime "YYYY-MM-DDTHH:MM:SS+00:00"
    actual: float | None
    previous: float | None
    estimate: float | None
    change: float | None
    change_pct: float | None
    impact: str | None  # "Low" | "Medium" | "High"


# Same EVENT_KEYWORDS / TRACKED_COUNTRIES as fmp_client
EVENT_KEYWORDS = {
    "FOMC": ["FOMC", "Fed Interest Rate", "Federal Funds Rate", "FOMC Press Release"],
    "CPI": ["CPI", "Consumer Price Index", "Inflation Rate"],
    "PCE": ["PCE", "Core PCE", "Personal Consumption Expenditures", "Personal Income and Outlays"],
    "NFP": ["Non Farm Payrolls", "Nonfarm Payrolls", "Employment Situation"],
    "GDP": ["GDP", "Gross Domestic Product"],
    "ISM": ["ISM Manufacturing", "ISM Services", "ISM Non-Manufacturing"],
    "JOLTS": ["JOLTS", "Job Openings"],
    "PPI": ["PPI", "Producer Price"],
    "RETAIL_SALES": ["Retail", "Advance Monthly Sales"],
}
TRACKED_COUNTRIES = {"US"}  # FRED es US-only para nuestros fines

# Friendly category → display name (for event field)
CATEGORY_DISPLAY: dict[str, str] = {
    "NFP": "Non Farm Payrolls",
    "CPI": "Consumer Price Index",
    "PCE": "Personal Income and Outlays",
    "FOMC": "FOMC Press Release",
    "PPI": "Producer Price Index",
    "RETAIL_SALES": "Retail Sales",
    "GDP": "Gross Domestic Product",
    "JOLTS": "JOLTS",
}


def _impact_for(category: str) -> str:
    return {
        "NFP": "High",
        "CPI": "High",
        "PCE": "Medium",
        "FOMC": "High",
        "PPI": "Medium",
        "RETAIL_SALES": "Medium",
        "GDP": "Medium",
        "JOLTS": "Low",
    }.get(category, "Low")


# ────────────────────────────────────────────────────────────────────
# FMPClient drop-in compat
# ────────────────────────────────────────────────────────────────────

class FMPClient:
    """FRED+BLS-backed replacement for FMPClient with identical interface."""

    def __init__(self, api_key: str | None = None, timeout: float = 12.0):
        self.api_key = api_key  # ignored, kept for compat
        self.timeout = timeout
        self._fred_cal = FREDCalendarClient(timeout=timeout)
        self._bls = BLSClient(timeout=timeout)
        self.last_ok = 0.0
        self.errors = 0
        self.last_error = ""
        self._cache: list[MacroEvent] = []
        self._cache_ts = 0.0

    # ---- Status properties ----
    @property
    def configured(self) -> bool:
        return self._fred_cal.configured

    @property
    def status(self) -> str:
        s_fred = self._fred_cal.status
        s_bls = self._bls.status
        if s_fred == "ok" and s_bls == "ok":
            return "ok"
        if s_fred == "stale" or s_bls == "stale":
            return "stale"
        if s_fred == "uninitialized" or s_bls == "uninitialized":
            return "uninitialized"
        return "degraded"

    # ---- Async fetch ----
    async def fetch_calendar(
        self,
        days_ahead: int = 14,
        days_behind: int = 7,
    ) -> list[MacroEvent]:
        """Sync code wrapped in async to match FMP signature."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._sync_fetch, days_ahead, days_behind)
        return list(self._cache)

    def _sync_fetch(self, days_ahead: int, days_behind: int) -> None:
        """Pull FRED calendar + BLS actuals, populate cache as MacroEvent list."""
        try:
            for rid in RELEASE_TO_CATEGORY:
                self._fred_cal.fetch_release_dates(
                    rid, days_back=days_behind, days_ahead=days_ahead,
                )
            self.errors = self._fred_cal._errors
            self.last_error = self._fred_cal._last_error
        except Exception as exc:
            self.errors += 1
            self.last_error = f"FRED fetch error: {exc}"
            LOGGER.warning(self.last_error)

        # Refresh BLS actuals for relevant categories
        bls_actuals: dict[str, dict[str, Any] | None] = {}
        for cat in ("NFP", "CPI", "PCE", "UNEMPLOYMENT"):
            try:
                bls_actuals[cat] = self._bls.get_latest_actual(cat)
            except Exception as exc:
                LOGGER.debug(f"BLS get_latest_actual {cat}: {exc}")
                bls_actuals[cat] = None

        # Build MacroEvent list
        events: list[MacroEvent] = []
        for rid, cat_events in self._fred_cal._cache.items():
            category = RELEASE_TO_CATEGORY.get(rid)
            if not category:
                continue
            actual_data = bls_actuals.get(category)
            for ev in cat_events:
                actual = None
                previous = None
                if actual_data and not ev.is_future:
                    # Match by month: only attach actual to the event whose
                    # release happened within last 60 days
                    today_iso = dt.date.today().isoformat()
                    delta_days = (
                        dt.date.today() - dt.date.fromisoformat(ev.date)
                    ).days
                    if 0 <= delta_days <= 60:
                        actual = actual_data.get("actual_for_sf")
                        previous = actual_data.get("previous_value")

                # Estimate (forecast/consensus) from forecasts.json (manual)
                # while investing_client scraping gets fixed.
                forecast_entry = get_forecast_for_event(category, ev.date)
                estimate = None
                if forecast_entry:
                    primary = forecast_entry.get("primary_metric_for_sf")
                    if primary:
                        estimate = forecast_entry.get("forecasts", {}).get(primary)
                    # Override actual if forecasts.json knows it (NFP backfill case)
                    if actual is None and forecast_entry.get("actual_known") is not None:
                        actual = forecast_entry.get("actual_known")
                    # Override previous from forecasts.json if more reliable
                    fc_prev = forecast_entry.get("previous", {})
                    if previous is None and fc_prev:
                        # Use the first available previous value
                        previous = next(iter(fc_prev.values()), None)

                # Compute change/change_pct from actual+estimate
                change = None
                change_pct = None
                if actual is not None and estimate is not None:
                    change = round(actual - estimate, 4)
                    if estimate != 0:
                        change_pct = round((actual - estimate) / abs(estimate) * 100, 4)

                events.append(MacroEvent(
                    event=CATEGORY_DISPLAY.get(category, ev.release_name),
                    country="US",
                    date=ev.datetime_utc,
                    actual=actual,
                    previous=previous,
                    estimate=estimate,
                    change=change,
                    change_pct=change_pct,
                    impact=_impact_for(category),
                ))

        self._cache = events
        self._cache_ts = self._fred_cal._last_sync_ts or 0.0
        self.last_ok = self._cache_ts

    def cached_events(self) -> list[MacroEvent]:
        return list(self._cache)

    @staticmethod
    def categorize(event: MacroEvent) -> str | None:
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

    async def close(self) -> None:
        # No async client to close (httpx Client used synchronously)
        return None

    # ---- Extra: BLS actual lookup (for sidecar SF compute) ----
    def get_actual_for_category(self, category: str) -> dict[str, Any] | None:
        return self._bls.get_latest_actual(category)


def time_to_next_event(
    events: list[MacroEvent],
) -> tuple[MacroEvent | None, float | None]:
    """Return (next_event, seconds_to_event) or (None, None)."""
    now = dt.datetime.now(dt.timezone.utc)
    future = []
    for ev in events:
        if not FMPClient.is_tracked(ev):
            continue
        try:
            ts = dt.datetime.fromisoformat(ev.date.replace("Z", "+00:00"))
            if ts > now:
                future.append((ts, ev))
        except (ValueError, AttributeError):
            continue
    if not future:
        return None, None
    future.sort(key=lambda x: x[0])
    next_ts, next_ev = future[0]
    return next_ev, (next_ts - now).total_seconds()


def upcoming_events(events: list[MacroEvent], hours_ahead: int = 24) -> list[MacroEvent]:
    now = dt.datetime.now(dt.timezone.utc)
    horizon = now + dt.timedelta(hours=hours_ahead)
    out = []
    for ev in events:
        if not FMPClient.is_tracked(ev):
            continue
        try:
            ts = dt.datetime.fromisoformat(ev.date.replace("Z", "+00:00"))
            if now <= ts <= horizon:
                out.append(ev)
        except (ValueError, AttributeError):
            continue
    return out


if __name__ == "__main__":
    import json, logging
    logging.basicConfig(level=logging.INFO)

    cli = FMPClient()
    print(f"configured={cli.configured} status={cli.status}")
    asyncio.run(cli.fetch_calendar(days_ahead=14, days_behind=14))
    print(f"events={len(cli.cached_events())} status={cli.status} errors={cli.errors}")

    print("\n=== upcoming 14d (tracked only) ===")
    for ev in cli.cached_events():
        if not FMPClient.is_tracked(ev):
            continue
        if ev.date < dt.datetime.now(dt.timezone.utc).isoformat():
            continue
        print(f"  {ev.date} {FMPClient.categorize(ev):14s} {ev.event} actual={ev.actual} prev={ev.previous}")

    print("\n=== latest tracked past events with BLS actual ===")
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    past = sorted(
        [e for e in cli.cached_events() if FMPClient.is_tracked(e) and e.date < now_iso],
        key=lambda e: e.date, reverse=True,
    )
    for ev in past[:8]:
        print(f"  {ev.date} {FMPClient.categorize(ev):14s} actual={ev.actual} prev={ev.previous}")

    print("\n=== BLS direct lookups ===")
    for cat in ("NFP", "CPI", "UNEMPLOYMENT"):
        d = cli.get_actual_for_category(cat)
        if d:
            print(f"  {cat}: actual_for_sf={d.get('actual_for_sf')} period={d.get('latest_period_name')} {d.get('latest_year')}")
