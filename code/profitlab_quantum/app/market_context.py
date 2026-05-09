# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportUnknownParameterType=false
# pyright: reportUnknownLambdaType=false, reportReturnType=false
"""Market Context Module for V13 Smart.

Detects market hours, holidays, and adjusts trading behavior.

Also supports optional "event risk" windows around high-impact events (e.g.
major speeches) to reduce position sizing for a configurable time before/after.
"""
from __future__ import annotations

import os
import pandas as pd
from datetime import datetime, timezone
from typing import Any, Dict, Tuple, Optional
from dataclasses import dataclass

# Database URL for loading calendar from PostgreSQL
from app.config import DATABASE_URL


def _parse_impact_to_stars(impact: str) -> int:
    if not impact:
        return 0
    s = str(impact).strip().lower()
    if s in ("high", "3", "★★★", "star3"):
        return 3
    if s in ("medium", "2", "★★", "star2"):
        return 2
    if s in ("low", "1", "★", "star1"):
        return 1
    # holidays are handled separately
    return 0


def _infer_event_stars(event_name: str) -> int:
    if not event_name:
        return 0
    e = str(event_name).lower()
    # Treat major macro events and high-profile speeches as 3-star risk.
    if any(k in e for k in [
        "fomc", "cpi", "nfp", "powell", "fed chair", "rate decision",
        "interest rate", "press conference", "speech", "trump",
    ]):
        return 3
    return 0


@dataclass
class MarketStatus:
    """Status of all markets"""
    is_cme_weekend: bool = False
    is_us_holiday: bool = False
    is_asia_holiday: bool = False
    is_europe_holiday: bool = False
    markets_open: int = 0  # Count of open markets (0-5)
    active_session: str = "off"  # asia, europe, us, overlap, off
    liquidity_score: float = 0.0  # 0-1, higher = better liquidity
    trading_mode: str = "full"  # full, conservative, minimal, pause
    position_size_multiplier: float = 1.0  # Reduces position size

    # Optional event-risk overlay
    event_risk_active: bool = False
    event_risk_stars: int = 0
    event_risk_event: str = ""
    event_risk_minutes_to: float = 0.0  # negative = minutes since start
    event_risk_timestamp: int = 0  # Unix timestamp of the event


# Country name constants (used in MARKETS, HOLIDAYS_2026, and holiday checks)
_COUNTRY_US = "United States"
_COUNTRY_UK = "United Kingdom"
_COUNTRY_HK = "Hong Kong"


# Market schedules (all times in UTC)
MARKETS = {
    "tokyo": {
        "tz_offset": 9,
        "open_local": 9.0,
        "close_local": 15.0,
        "open_utc": 0.0,
        "close_utc": 6.0,
        "days": [0, 1, 2, 3, 4],
        "country": "Japan"
    },
    "hong_kong": {
        "tz_offset": 8,
        "open_local": 9.5,
        "close_local": 16.0,
        "open_utc": 1.5,
        "close_utc": 8.0,
        "days": [0, 1, 2, 3, 4],
        "country": _COUNTRY_HK
    },
    "shanghai": {
        "tz_offset": 8,
        "open_local": 9.5,
        "close_local": 15.0,
        "open_utc": 1.5,
        "close_utc": 7.0,
        "days": [0, 1, 2, 3, 4],
        "country": "China"
    },
    "singapore": {
        "tz_offset": 8,
        "open_local": 9.0,
        "close_local": 17.0,
        "open_utc": 1.0,
        "close_utc": 9.0,
        "days": [0, 1, 2, 3, 4],
        "country": "Singapore"
    },
    "london": {
        "tz_offset": 0,
        "open_local": 8.0,
        "close_local": 16.5,
        "open_utc": 8.0,
        "close_utc": 16.5,
        "days": [0, 1, 2, 3, 4],
        "country": _COUNTRY_UK
    },
    "frankfurt": {
        "tz_offset": 1,
        "open_local": 9.0,
        "close_local": 17.5,
        "open_utc": 8.0,
        "close_utc": 16.5,
        "days": [0, 1, 2, 3, 4],
        "country": "Germany"
    },
    "nyse": {
        "tz_offset": -5,
        "open_local": 9.5,
        "close_local": 16.0,
        "open_utc": 14.5,
        "close_utc": 21.0,
        "days": [0, 1, 2, 3, 4],
        "country": _COUNTRY_US
    },
    "cme": {
        "tz_offset": -6,
        "open_local": 17.0,
        "close_local": 16.0,
        "open_utc": 23.0,
        "close_utc": 22.0,
        "days": "special",
        "country": _COUNTRY_US
    }
}


# 2026 Holiday Schedule (UTC Close Times or 'closed')
HOLIDAYS_2026 = {
    "2026-01-01": {"all": "closed"},
    "2026-01-19": {"nyse": "closed", "cme": 18.0}, # MLK (12:00 CT = 18:00 UTC)
    "2026-02-16": {"nyse": "closed", "cme": 18.0}, # Presidents (12:00 CT = 18:00 UTC)
    "2026-04-03": {"london": "closed", "nyse": "closed", "cme": 14.25}, # Good Friday (08:15 CT = 14:15 UTC)
    "2026-04-06": {"london": "closed"}, # Easter Monday
    "2026-05-04": {"london": "closed"}, # Early May Bank
    "2026-05-25": {"london": "closed", "nyse": "closed", "cme": 18.0}, # Spring Bank / Memorial
    "2026-06-19": {"nyse": "closed", "cme": 18.0}, # Juneteenth
    "2026-07-03": {"nyse": "closed", "cme": 18.0}, # Independence Day
    "2026-08-31": {"london": "closed"}, # Summer Bank
    "2026-09-07": {"nyse": "closed", "cme": 18.0}, # Labor Day
    "2026-11-26": {"nyse": "closed", "cme": 18.0}, # Thanksgiving
    "2026-11-27": {"nyse": 18.0, "cme": 18.25}, # Black Friday (13:00 ET=18:00 UTC, 12:15 CT=18:15 UTC)
    "2026-12-24": {"london": 12.5, "nyse": 18.0, "cme": 18.25}, # Xmas Eve
    "2026-12-25": {"all": "closed"},
    "2026-12-28": {"london": "closed"}, # Boxing Day Sub
    "2026-12-31": {"london": 12.5}, # New Year's Eve
}

class MarketContextManager:
    """Manages market context and holidays for V13 Smart"""
    
    def __init__(self, calendar_path: Optional[str] = None):
        self.holidays: Dict[str, set[str]] = {}  # country -> set of date strings
        self.events: list[dict[str, Any]] = []  # [{timestamp:int, impact:str, event:str, stars:int}]
        self._calendar_path: Optional[str] = calendar_path
        self._calendar_mtime: Optional[float] = None
        self._last_db_load: Optional[float] = None
        # Try PostgreSQL first, fall back to CSV
        self._load_from_database()
        if not self.events and calendar_path:
            self._load_calendar(calendar_path)
    
    def _load_from_database(self):
        """Load holidays and events from PostgreSQL market_calendar table."""
        try:
            import psycopg2  # type: ignore[import-untyped]
            from urllib.parse import urlparse
            
            parsed = urlparse(DATABASE_URL)
            conn = psycopg2.connect(
                host=parsed.hostname,
                port=parsed.port or 5432,
                user=parsed.username,
                password=parsed.password,
                dbname=parsed.path[1:]
            )
            cur = conn.cursor()
            
            # Load events from market_calendar
            cur.execute("""
                SELECT event_date, event_time, event_name, country, impact, stars
                FROM market_calendar
                WHERE event_date >= CURRENT_DATE - INTERVAL '7 days'
                ORDER BY event_date, event_time
            """)
            
            self.holidays = {}
            self.events = []
            
            for row in cur.fetchall():
                event_date, event_time, event_name, country, impact, stars = row
                
                # Combine date and time to timestamp
                if event_time:
                    dt = datetime.combine(event_date, event_time)
                else:
                    dt = datetime.combine(event_date, datetime.min.time())
                dt = dt.replace(tzinfo=timezone.utc)
                ts = int(dt.timestamp())
                
                # Add to holidays dict
                if str(impact).lower() == 'holiday':
                    date_str = event_date.strftime("%Y-%m-%d")
                    if country not in self.holidays:
                        self.holidays[country] = set()
                    self.holidays[country].add(date_str)
                
                # Add to events list
                self.events.append({
                    'timestamp': ts,
                    'impact': str(impact),
                    'event': f"{event_name} - {country}",
                    'stars': int(stars) if stars else 1,
                })
            
            cur.close()
            conn.close()
            self._last_db_load = datetime.now(timezone.utc).timestamp()
            
            print(f"[MarketContext] Loaded {len(self.events)} events from PostgreSQL, "
                  f"{sum(len(v) for v in self.holidays.values())} holidays")
            
        except Exception as e:
            print(f"[MarketContext] Could not load from database: {e}")
    
    def _maybe_reload_database(self):
        """Reload from database every 6 hours."""
        if self._last_db_load is None:
            self._load_from_database()
            return
        
        now = datetime.now(timezone.utc).timestamp()
        if now - self._last_db_load > 6 * 3600:  # 6 hours
            self._load_from_database()
    
    # Countries to match in CSV event names
    _HOLIDAY_COUNTRIES = [
        _COUNTRY_US, _COUNTRY_UK, "Germany", "Japan", "China",
        _COUNTRY_HK, "Singapore", "South Korea", "Spain", "India",
    ]

    def _extract_holidays_from_csv(self, df: pd.DataFrame) -> None:
        """Extract holidays from CSV dataframe into self.holidays."""
        holidays_df = (
            df[df['impact'] == 'holiday']
            if 'impact' in df.columns
            else df[df['event'].str.contains('holiday', case=False, na=False)]
        )
        for _, row in holidays_df.iterrows():
            ts = row.get('timestamp', 0)
            event = row.get('event', '')
            country = next((c for c in self._HOLIDAY_COUNTRIES if c in event), None)
            if country and ts > 0:
                dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                self.holidays.setdefault(country, set()).add(dt.strftime("%Y-%m-%d"))

    def _extract_events_from_csv(self, df: pd.DataFrame) -> None:
        """Extract high-impact events from CSV dataframe into self.events."""
        self.events = []
        if 'timestamp' not in df.columns or 'event' not in df.columns:
            return
        has_impact = 'impact' in df.columns
        for _, row in df.iterrows():
            ev = self._parse_event_row(row, has_impact)
            if ev:
                self.events.append(ev)

    @staticmethod
    def _parse_event_row(row: Any, has_impact: bool) -> Optional[dict[str, Any]]:
        """Parse a single CSV row into an event dict, or return None."""
        ts = row.get('timestamp', 0)
        if ts is None:
            return None
        try:
            ts_i = int(float(ts))
        except (ValueError, TypeError):
            return None
        if ts_i <= 0:
            return None
        ev_name = row.get('event', '')
        impact = row.get('impact', '') if has_impact else ''
        stars = max(_parse_impact_to_stars(impact), _infer_event_stars(ev_name))
        if str(impact).strip().lower() == 'holiday' and stars == 0:
            stars = 1
        if stars <= 0:
            return None
        return {'timestamp': ts_i, 'impact': str(impact), 'event': str(ev_name), 'stars': int(stars)}

    def _load_calendar(self, calendar_path: Optional[str]):
        """Load holidays and high-impact events from calendar CSV."""
        if not calendar_path or not os.path.exists(calendar_path):
            return
        try:
            df = pd.read_csv(calendar_path)
            try:
                self._calendar_mtime = os.path.getmtime(calendar_path)
            except OSError:
                self._calendar_mtime = None
            self._extract_holidays_from_csv(df)
            self._extract_events_from_csv(df)
            print(
                f"[MarketContext] Loaded {sum(len(v) for v in self.holidays.values())} holidays "
                f"for {len(self.holidays)} countries; events={len(self.events)}"
            )
        except Exception as e:
            print(f"[MarketContext] Error loading holidays: {e}")

    def _maybe_reload_calendar(self):
        """Reload calendar from database or CSV if needed."""
        # Try database reload first (every 6 hours)
        self._maybe_reload_database()
        
        # Fall back to CSV reload if no database events
        if self.events:
            return
            
        p = self._calendar_path
        if not p or not os.path.exists(p):
            return
        try:
            mtime = os.path.getmtime(p)
        except Exception:
            return
        if self._calendar_mtime is None or mtime > self._calendar_mtime:
            self.holidays = {}
            self.events = []
            self._load_calendar(p)

    def get_next_event(self, dt: datetime) -> Optional[Dict[str, Any]]:
        """Find the next upcoming event (future only)."""
        if not self.events:
            return None
        
        now_ts = dt.timestamp()
        # Filter for future events
        future_events = [e for e in self.events if float(e.get('timestamp', 0)) > now_ts]
        if not future_events:
            return None
            
        # Sort by time
        future_events.sort(key=lambda x: float(x.get('timestamp', 0)))
        
        # Return the nearest one
        return future_events[0]

    def _find_best_active_event(self, now_ts: float, pre_min: float, post_min: float) -> Optional[dict[str, Any]]:
        """Find the highest-priority event within the active risk window."""
        best = None
        for ev in self.events:
            ts = float(ev.get('timestamp', 0))
            if ts <= 0:
                continue
            delta_min = (ts - now_ts) / 60.0
            if not ((-post_min) <= delta_min <= pre_min):
                continue
            ev_stars = int(ev.get('stars', 0))
            if best is None or ev_stars > int(best.get('stars', 0)):
                best = ev
            elif ev_stars == int(best.get('stars', 0)):
                if abs(ts - now_ts) < abs(float(best.get('timestamp', 0)) - now_ts):
                    best = ev
        return best

    @staticmethod
    def _star_to_multiplier(stars: int, mult_3: float, mult_2: float, mult_1: float) -> float:
        """Map star rating to position size multiplier."""
        if stars >= 3:
            return mult_3
        if stars == 2:
            return mult_2
        return mult_1

    def _event_summary(self, ev: dict[str, Any], now_ts: float) -> Tuple[int, str, float]:
        """Extract (stars, name, minutes_to) from an event dict."""
        return (
            int(ev.get('stars', 0)),
            str(ev.get('event', '')),
            (float(ev.get('timestamp', 0)) - now_ts) / 60.0,
        )

    def get_event_risk(self, dt: datetime) -> Tuple[bool, int, str, float, float]:
        """Return (active, stars, event_name, minutes_to_event, size_multiplier)."""
        _NO_RISK = (False, 0, "", 0.0, 1.0)

        mode = os.getenv("EVENT_RISK_MODE_V13", "off").strip().lower()
        if mode in ("0", "off", "false", "no") or not self.events:
            return _NO_RISK

        pre_min = float(os.getenv("EVENT_RISK_PRE_MIN_V13", "30"))
        post_min = float(os.getenv("EVENT_RISK_POST_MIN_V13", "60"))
        mult_3 = float(os.getenv("EVENT_RISK_MULT_3STAR_V13", "0.3"))
        mult_2 = float(os.getenv("EVENT_RISK_MULT_2STAR_V13", "0.6"))
        mult_1 = float(os.getenv("EVENT_RISK_MULT_1STAR_V13", "0.8"))

        now_ts = dt.timestamp()
        best = self._find_best_active_event(now_ts, pre_min, post_min)

        if not best:
            # Show next upcoming event for display only (not active)
            future = [e for e in self.events if float(e.get('timestamp', 0)) > now_ts]
            if not future:
                return _NO_RISK
            future.sort(key=lambda x: float(x.get('timestamp', 0)))
            stars, name, minutes_to = self._event_summary(future[0], now_ts)
            return (False, stars, name, minutes_to, 1.0)

        stars, name, minutes_to = self._event_summary(best, now_ts)

        # If user wants only 3-star fundamentals
        if mode in ("3", "3star", "three", "three_star") and stars < 3:
            return _NO_RISK

        mult = self._star_to_multiplier(stars, mult_3, mult_2, mult_1)
        return (True, stars, name, minutes_to, float(mult))
    
    def is_holiday(self, country: str, dt: datetime) -> bool:
        """Check if date is a holiday for country"""
        # Hardcoded major global holidays
        if dt.month == 12 and dt.day == 25:
            return True
        if dt.month == 1 and dt.day == 1:
            return True
            
        date_str = dt.strftime("%Y-%m-%d")
        return date_str in self.holidays.get(country, set())
    
    def is_cme_weekend(self, dt: datetime) -> bool:
        """
        CME Futures weekend:
        - Closes: Friday 4:00 PM CT (22:00 UTC)
        - Opens: Sunday 5:00 PM CT (23:00 UTC)
        """
        dow = dt.weekday()
        hour = dt.hour + dt.minute / 60.0
        
        # Saturday all day
        if dow == 5:
            return True
        
        # Friday after 22:00 UTC
        if dow == 4 and hour >= 22.0:
            return True
        
        # Sunday before 23:00 UTC
        if dow == 6 and hour < 23.0:
            return True

        # Special: Xmas Eve (Dec 24) closes at 18:00 UTC
        if dt.month == 12 and dt.day == 24 and hour >= 18.0:
            return True
            
        # Special: Xmas Day (Dec 25) closed all day
        if dt.month == 12 and dt.day == 25:
            return True
        
        return False
    
    @staticmethod
    def _check_holiday_2026(market_name: str, date_str: str, hour: float) -> Optional[bool]:
        """Check 2026 holiday exception. Returns False=closed, None=no exception (continue check)."""
        if date_str not in HOLIDAYS_2026:
            return None
        rule = HOLIDAYS_2026[date_str]
        if "all" in rule and rule["all"] == "closed":
            return False
        if market_name in rule:
            val = rule[market_name]
            if val == "closed":
                return False
            if isinstance(val, (int, float)) and hour >= val:
                return False
        return None

    _XMAS_EVE_CLOSE = {"nyse": 18.0, "london": 12.5, "frankfurt": 13.0}

    def is_market_open(self, market_name: str, dt: datetime) -> bool:
        """Check if a specific market is currently open"""
        market = MARKETS.get(market_name)
        if not market:
            return False
        
        dow = dt.weekday()
        hour = dt.hour + dt.minute / 60.0
        date_str = dt.strftime("%Y-%m-%d")
        
        # Check 2026 Exceptions
        holiday_check = self._check_holiday_2026(market_name, date_str, hour)
        if holiday_check is not None:
            return holiday_check

        # Check CME special case
        if market_name == "cme":
            if self.is_cme_weekend(dt):
                return False
            return not (22.0 <= hour < 23.0)  # daily maintenance 22-23 UTC
        
        # Check if weekday
        if dow not in market["days"]:
            return False

        is_xmas_eve = (dt.month == 12 and dt.day == 24)
        
        # Check if holiday (skip for Xmas Eve – partial trading day)
        country = market.get("country", "")
        if self.is_holiday(country, dt) and not is_xmas_eve:
            return False
        
        # Check hours (adjust close for Xmas Eve)
        open_h = market["open_utc"]
        close_h: float = float(self._XMAS_EVE_CLOSE.get(market_name, market["close_utc"]) if is_xmas_eve else market["close_utc"] or 0)  # type: ignore[arg-type]
        
        return open_h <= hour < close_h  # type: ignore[operator]
    
    @staticmethod
    def _determine_session(asia_open: int, europe_open: int, us_open: int) -> str:
        """Determine the active trading session from open market counts."""
        if us_open > 0 and europe_open > 0:
            return "us_europe_overlap"
        if us_open > 0:
            return "us"
        if europe_open > 0 and asia_open > 0:
            return "europe_asia_overlap"
        if europe_open > 0:
            return "europe"
        if asia_open > 0:
            return "asia"
        return "off"

    _SESSION_BASE_LIQUIDITY = {
        "us_europe_overlap": 1.0,
        "us": 0.8,
        "europe_asia_overlap": 0.8,
        "europe": 0.6,
        "asia": 0.6,
    }

    @classmethod
    def _compute_liquidity(cls, status: MarketStatus) -> float:
        """Compute liquidity score (0-1) based on session and holidays."""
        score = cls._SESSION_BASE_LIQUIDITY.get(status.active_session, 0.0)
        if score < 0.01:
            score = 0.4 if status.markets_open > 0 else 0.2
        if status.is_us_holiday:
            score *= 0.5
        if status.is_europe_holiday:
            score *= 0.7
        if status.is_asia_holiday:
            score *= 0.8
        if status.is_cme_weekend:
            score = 0.1
        return score

    @staticmethod
    def _determine_trading_mode(status: MarketStatus) -> Tuple[str, float]:
        """Determine trading mode and position size multiplier."""
        if status.is_cme_weekend:
            return "weekend", 0.3
        if status.is_us_holiday and status.is_europe_holiday:
            return "pause", 0.0
        # US-holiday-only and low-liquidity both result in conservative/0.5
        if not status.is_us_holiday and status.liquidity_score >= 0.6:
            return "full", 1.0
        if not status.is_us_holiday and status.liquidity_score >= 0.4:
            return "normal", 0.8
        return "conservative", 0.5

    def get_status(self, dt: Optional[datetime] = None) -> MarketStatus:
        """Get comprehensive market status"""
        if dt is None:
            dt = datetime.now(timezone.utc)

        # If calendar CSV changes, reload holidays/events
        self._maybe_reload_calendar()
        
        status = MarketStatus()
        
        # Check CME weekend
        status.is_cme_weekend = self.is_cme_weekend(dt)
        
        # Check holidays
        date_str = dt.strftime("%Y-%m-%d")
        status.is_us_holiday = date_str in self.holidays.get(_COUNTRY_US, set())
        status.is_asia_holiday = any(
            date_str in self.holidays.get(c, set()) 
            for c in ["Japan", "China", _COUNTRY_HK, "Singapore", "South Korea"]
        )
        status.is_europe_holiday = any(
            date_str in self.holidays.get(c, set())
            for c in [_COUNTRY_UK, "Germany", "Spain"]
        )
        
        # Count open markets
        asia_markets = ["tokyo", "hong_kong", "shanghai", "singapore"]
        europe_markets = ["london", "frankfurt"]
        us_markets = ["nyse", "cme"]
        
        asia_open = sum(1 for m in asia_markets if self.is_market_open(m, dt))
        europe_open = sum(1 for m in europe_markets if self.is_market_open(m, dt))
        us_open = sum(1 for m in us_markets if self.is_market_open(m, dt))
        
        status.markets_open = asia_open + europe_open + us_open
        status.active_session = self._determine_session(asia_open, europe_open, us_open)
        status.liquidity_score = self._compute_liquidity(status)
        status.trading_mode, status.position_size_multiplier = self._determine_trading_mode(status)

        # Optional event-risk overlay (3-star fundamentals / high-impact events)
        try:
            active, stars, ev_name, minutes_to, mult = self.get_event_risk(dt)
            if active:
                status.event_risk_active = True
                status.event_risk_stars = int(stars)
                status.event_risk_event = str(ev_name)[:200]
                status.event_risk_minutes_to = float(minutes_to)
                status.position_size_multiplier = min(status.position_size_multiplier, float(mult))
                if status.trading_mode != "pause":
                    status.trading_mode = f"{status.trading_mode}+event"
            else:
                next_ev = self.get_next_event(dt)
                if next_ev:
                    status.event_risk_active = False
                    status.event_risk_stars = int(next_ev['stars'])
                    status.event_risk_event = str(next_ev['event'])[:200]
                    status.event_risk_minutes_to = (float(next_ev['timestamp']) - dt.timestamp()) / 60.0
                    status.event_risk_timestamp = int(next_ev['timestamp'])
        except Exception:
            pass
        
        return status
    
    def get_smart_features(self, ts: int) -> Tuple[float, float, float, float, float]:
        """
        Get smart features for the model based on market context
        Returns: (liquidity_score, is_weekend, is_holiday, markets_open_norm, session_id)
        """
        if ts <= 0:
            return (0.5, 0.0, 0.0, 0.5, 0.0)
        
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        status = self.get_status(dt)
        
        # Normalize markets_open (0-8 markets possible)
        markets_open_norm = status.markets_open / 8.0
        
        # Session ID (0-5)
        session_map = {
            "off": 0.0,
            "asia": 0.2,
            "europe": 0.4,
            "europe_asia_overlap": 0.5,
            "us": 0.7,
            "us_europe_overlap": 1.0
        }
        session_id = session_map.get(status.active_session, 0.0)
        
        # Binary flags
        is_weekend = 1.0 if status.is_cme_weekend else 0.0
        is_holiday = 1.0 if (status.is_us_holiday or status.is_europe_holiday) else 0.0
        
        return (
            status.liquidity_score,
            is_weekend,
            is_holiday,
            markets_open_norm,
            session_id
        )


# Singleton instance
_market_context: Optional[MarketContextManager] = None

def get_market_context(calendar_path: Optional[str] = None) -> MarketContextManager:
    """Get or create market context manager"""
    global _market_context
    if _market_context is None:
        _market_context = MarketContextManager(calendar_path)
    return _market_context
