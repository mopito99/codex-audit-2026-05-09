"""Investing.com economic calendar wrapper via investpy.

Decisión Gemma 4 (2026-05-05): Investing.com captura el valor "Actual"
vs "Forecast" en el momento del release. Calcula Surprise Factor:
   SF = (actual - consensus) / σ_historical
Si |SF| > 1.0σ → bot reacciona; <1.0σ → ignora.

σ historical defaults (Gemma spec V4-Alpha §4-bis.10, FRED override pending):
  FOMC: 1σ = 25 bps
  CPI:  1σ = 0.1% YoY
  NFP:  1σ = 50k jobs
"""
from __future__ import annotations
import datetime as dt
import logging
import time
from dataclasses import dataclass

logger = logging.getLogger("poly_sidecar.investing")

# σ histórico por evento (Gemma V4-Alpha §4-bis.10) — fallback hasta FRED.
# Si fred_init.py se ejecutó, los σ se sobreescriben en runtime con valores
# reales de 12y desde fred_calibration en macro_calendar.json.
SIGMA_DEFAULTS = {
    "FOMC":   0.25,    # 25 bps
    "CPI":    0.10,    # 0.1% YoY
    "NFP":    50.0,    # 50k jobs
    "PCE":    0.10,    # ~0.1%
    "ECB":    0.25,    # ~25 bps
    "GDP":    0.30,    # ~0.3% QoQ
    "ISM":    1.0,     # ~1 pt index
    "JOLTS":  150.0,   # ~150k
    "BoJ_BoE": 0.25,
}

# Sobrescribe en runtime con calibración FRED real (cargada desde calendar).
SIGMA_FRED: dict[str, float] = {}


def load_sigma_from_calendar(macro_calendar: dict) -> int:
    """Read fred_calibration.events from macro_calendar.json and override
    SIGMA_FRED dict. Returns count of σ overridden."""
    SIGMA_FRED.clear()
    fred = macro_calendar.get("fred_calibration", {}).get("events", {})
    n = 0
    for cat, info in fred.items():
        sigma = info.get("historical_surprise_sigma")
        if sigma is not None and sigma > 0:
            SIGMA_FRED[cat] = float(sigma)
            n += 1
    return n


def get_sigma(category: str) -> float | None:
    """Resolution order: FRED calibration > V4-Alpha defaults."""
    if category in SIGMA_FRED:
        return SIGMA_FRED[category]
    return SIGMA_DEFAULTS.get(category)

EVENT_KEYWORDS = {
    "FOMC":   ["fomc", "fed interest rate", "federal funds"],
    "CPI":    ["cpi", "consumer price", "inflation rate", "core inflation"],
    "PCE":    ["pce", "core pce"],
    "NFP":    ["non farm payrolls", "nonfarm payrolls", "non-farm payrolls"],
    "ECB":    ["ecb interest rate", "ecb rate", "ecb press conference"],
    "GDP":    ["gdp"],
    "ISM":    ["ism manufacturing", "ism services", "ism non-manufacturing"],
    "JOLTS":  ["jolts"],
    "BoJ_BoE":["boj interest rate", "boe interest rate"],
}


@dataclass
class InvestingEvent:
    id: str
    date: str            # dd/mm/yyyy
    time: str            # HH:MM or 'All Day'
    zone: str
    currency: str | None
    importance: str      # 'high'|'medium'|'low'
    event: str
    actual: str | None
    forecast: str | None
    previous: str | None
    category: str | None = None


def _categorize(event_name: str) -> str | None:
    name = event_name.lower()
    for cat, kws in EVENT_KEYWORDS.items():
        for kw in kws:
            if kw in name:
                return cat
    return None


def _to_float(x) -> float | None:
    if x is None:
        return None
    s = str(x).strip()
    if not s or s.lower() in ("none", "nan", ""):
        return None
    # Investing.com style: "1.386M", "62.5K", "5.25%", "-61.00B"
    mult = 1.0
    if s.endswith(("K", "k")):
        mult = 1e3; s = s[:-1]
    elif s.endswith(("M", "m")):
        mult = 1e6; s = s[:-1]
    elif s.endswith(("B", "b")):
        mult = 1e9; s = s[:-1]
    elif s.endswith(("T", "t")):
        mult = 1e12; s = s[:-1]
    s = s.replace("%", "").replace(",", "").strip()
    try:
        return float(s) * mult
    except ValueError:
        return None


def fetch_calendar(days_ahead: int = 1, days_behind: int = 0) -> list[InvestingEvent]:
    """Fetch upcoming + recent events. Synchronous call (investpy uses requests)."""
    import investpy
    today = dt.datetime.now(dt.timezone.utc)
    d_from = (today - dt.timedelta(days=days_behind)).strftime("%d/%m/%Y")
    d_to   = (today + dt.timedelta(days=days_ahead)).strftime("%d/%m/%Y")
    try:
        df = investpy.economic_calendar(
            time_zone="GMT",
            from_date=d_from,
            to_date=d_to,
            countries=["united states", "euro zone", "china", "japan", "united kingdom"],
            importances=["high", "medium"],
        )
    except Exception as e:
        logger.warning(f"investpy fetch error: {e}")
        return []

    events = []
    for _, row in df.iterrows():
        try:
            ev = InvestingEvent(
                id=str(row.get("id", "")),
                date=str(row.get("date", "")),
                time=str(row.get("time", "")),
                zone=str(row.get("zone", "")),
                currency=row.get("currency") if row.get("currency") else None,
                importance=str(row.get("importance", "")) or "low",
                event=str(row.get("event", "")),
                actual=str(row.get("actual")) if row.get("actual") and str(row.get("actual")) != "None" else None,
                forecast=str(row.get("forecast")) if row.get("forecast") else None,
                previous=str(row.get("previous")) if row.get("previous") else None,
            )
            ev.category = _categorize(ev.event)
            events.append(ev)
        except Exception:
            continue
    return events


def compute_surprise_factor(event: InvestingEvent) -> tuple[float | None, float | None]:
    """Returns (SF, abs_change). SF = (actual - forecast) / sigma_default.
    If actual or forecast missing, returns (None, None)."""
    if not event.category:
        return None, None
    actual = _to_float(event.actual)
    forecast = _to_float(event.forecast)
    if actual is None or forecast is None:
        return None, None
    diff = actual - forecast
    sigma = get_sigma(event.category)
    if sigma is None or sigma <= 0:
        return None, diff
    return diff / sigma, diff


def recent_releases_with_actual(events: list[InvestingEvent],
                                 hours_behind: int = 6) -> list[dict]:
    """Filter to events within last `hours_behind` whose actual is published."""
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(hours=hours_behind)
    out = []
    for e in events:
        if not e.category:
            continue
        if not e.actual or e.actual.lower() in ("none", "nan", ""):
            continue
        try:
            ts = dt.datetime.strptime(f"{e.date} {e.time}", "%d/%m/%Y %H:%M")
            ts = ts.replace(tzinfo=dt.timezone.utc)
        except Exception:
            continue
        if ts < cutoff or ts > now:
            continue
        sf, diff = compute_surprise_factor(e)
        out.append({
            "id": e.id,
            "event": e.event,
            "category": e.category,
            "country": e.zone,
            "ts_utc": ts.isoformat(),
            "actual": e.actual,
            "forecast": e.forecast,
            "previous": e.previous,
            "importance": e.importance,
            "surprise_factor": round(sf, 4) if sf is not None else None,
            "abs_change": round(diff, 4) if diff is not None else None,
            "abs_sf": abs(sf) if sf is not None else None,
            "reaction_threshold_hit": sf is not None and abs(sf) > 1.0,
        })
    out.sort(key=lambda x: x["ts_utc"], reverse=True)
    return out


class InvestingClient:
    """Manager around the synchronous investpy with state + caching.
    Uses thread executor to avoid blocking asyncio loop."""

    def __init__(self):
        self.last_ok = 0.0
        self.errors = 0
        self.last_error = ""
        self._cache: list[InvestingEvent] = []
        self._cache_ts = 0.0

    @property
    def status(self) -> str:
        if self.last_ok == 0:
            return "uninitialized"
        age = time.time() - self.last_ok
        if age > 7200:
            return "stale"
        return "ok"

    async def fetch(self, days_ahead: int = 1, days_behind: int = 0) -> list[InvestingEvent]:
        import asyncio
        loop = asyncio.get_event_loop()
        try:
            events = await loop.run_in_executor(
                None, fetch_calendar, days_ahead, days_behind
            )
            self._cache = events
            self._cache_ts = time.time()
            self.last_ok = time.time()
            return events
        except Exception as e:
            self.errors += 1
            self.last_error = str(e)[:120]
            return []

    def cached(self) -> list[InvestingEvent]:
        return list(self._cache)

    def recent_releases(self, hours_behind: int = 6) -> list[dict]:
        return recent_releases_with_actual(self._cache, hours_behind=hours_behind)
