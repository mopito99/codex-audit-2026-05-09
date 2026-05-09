import os

# Database Configuration
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "4366037.Cabeza")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_NAME = "profitlab_quantum_db" # Separate database

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}/{DB_NAME}"

# Trading Configuration
# List of tokens to trade (USDT pairs)
# Dynamic loading from active_tokens.json
import json
ACTIVE_TOKENS_FILE = os.path.join(os.path.dirname(__file__), "../active_tokens.json")

def load_active_tokens():
    """Load ALL tokens (trading + training). Engine runs for all."""
    defaults = ["BTC-USDT"] # Default to BTC only for safety
    if os.path.exists(ACTIVE_TOKENS_FILE):
        try:
            with open(ACTIVE_TOKENS_FILE, "r") as f:
                data = json.load(f)
                tokens = data.get("active_tokens", defaults)
                # Handle both list of strings and list of objects
                if tokens and isinstance(tokens[0], dict):
                    return [t["symbol"] for t in tokens]
                return tokens
        except Exception as e:
            print(f"Error loading active_tokens.json: {e}")
            return defaults
    return defaults

def load_trading_tokens():
    """Load only tokens with trade=true. Only these open paper positions."""
    defaults = ["BTC-USDT"]
    if os.path.exists(ACTIVE_TOKENS_FILE):
        try:
            with open(ACTIVE_TOKENS_FILE, "r") as f:
                data = json.load(f)
                tokens = data.get("active_tokens", defaults)
                if tokens and isinstance(tokens[0], dict):
                    return [t["symbol"] for t in tokens if t.get("trade", True)]
                return tokens
        except Exception as e:
            print(f"Error loading active_tokens.json: {e}")
            return defaults
    return defaults

def get_token_tier(symbol: str) -> str:
    """Get the tier ('major' or 'meme') for a given symbol."""
    if os.path.exists(ACTIVE_TOKENS_FILE):
        try:
            with open(ACTIVE_TOKENS_FILE, "r") as f:
                data = json.load(f)
                # Check fixed majors list first (fast path)
                if symbol in data.get("major_tokens_fixed", []):
                    return "major"
                for t in data.get("active_tokens", []):
                    if isinstance(t, dict) and t.get("symbol") == symbol:
                        return t.get("tier", "meme")
        except Exception:
            pass
    # Fallback: classify by well-known majors
    major_assets = {"BTC", "ETH", "SOL", "BNB", "XRP", "AVAX", "SUI", "LINK", "ADA",
                    "DOT", "ATOM", "NEAR", "APT", "INJ", "TON", "HBAR", "ICP"}
    asset = symbol.replace("-USDT", "").replace("USDT", "")
    return "major" if asset in major_assets else "meme"

def load_token_leverage(symbol):
    """Legacy function - now returns league-based leverage."""
    # El leverage ahora es dinámico por liga, esta función se mantiene por compatibilidad
    return get_league_leverage()

def get_league_leverage():
    """
    Leverage DINÁMICO basado en liga (Gemma4-designed).
    
    La liga se calcula de los últimos 50 trades reales:
    - Bronce (WR<40%): 5x — protege cuenta en mal racha
    - Plata (WR 40-55%): 10x — conservador
    - Oro (WR 55-65%): 15x — probado
    - Diamante (WR>65%): 20x — alto rendimiento
    - Leyenda (WR>70%, Sharpe>1.5): 25x — elite
    """
    try:
        from sqlalchemy import create_engine
        from app.league import compute_league
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            league = compute_league(conn)
        return float(league["max_leverage"])
    except Exception:
        return 20.0  # Fallback

# Cache para no consultar DB en cada tick
_league_leverage_cache = {"value": 20.0, "league": "Plata", "updated_at": 0}

def get_cached_league_leverage():
    """Versión con cache (actualiza cada 60 segundos)."""
    import time
    now = time.time()
    
    if now - _league_leverage_cache["updated_at"] > 60:
        try:
            from sqlalchemy import create_engine
            from app.league import compute_league
            engine = create_engine(DATABASE_URL)
            with engine.connect() as conn:
                league = compute_league(conn)
            _league_leverage_cache["value"] = float(league["max_leverage"])
            _league_leverage_cache["league"] = league["league"]
            _league_leverage_cache["updated_at"] = now
        except Exception:
            pass
    
    return _league_leverage_cache["value"]

TOKENS = load_active_tokens()           # ALL tokens: engines train on all
TRADING_TOKENS = load_trading_tokens()  # Only trade=true: open positions

# ═══════════════════════════════════════════════════════════════
# TIER CONFIGURATION — Dual Strategy (Blue Chips vs Memecoins)
# ═══════════════════════════════════════════════════════════════
# Gemma4-designed: different risk profiles per asset class.

TIER_CONFIG = {
    "major": {
        "label": "🟡 Blue Chips",
        "max_leverage": 25.0,          # Liga-based, up to 25x
        "use_league_leverage": True,   # Dynamic by win rate
        "slippage_bps": 3.0,           # Deep books
        "spread_max_bps": 10.0,        # Tight spreads required
        "killswitch_loss": -15.0,      # More tolerant ($)
        "killswitch_consec": 5,        # More tolerance on streaks
        "min_volume_24h": 10_000_000,  # $10M min
        "session_filter": False,       # Trade 24/7 (enough liquidity)
        "vol_ratio_min": 1.0,          # Lower volume gate
        "rotatable": False,            # Fixed list, no auto-rotation
    },
    "meme": {
        "label": "🐸 Memecoins",
        "max_leverage": 10.0,          # Hard cap 10x regardless of liga
        "use_league_leverage": False,  # Fixed cap
        "slippage_bps": 15.0,          # Thin books
        "spread_max_bps": 30.0,        # More tolerance for illiquidity
        "killswitch_loss": -8.0,       # Strict ($)
        "killswitch_consec": 3,        # Quick kill on bad streaks
        "min_volume_24h": 500_000,     # $500K min
        "session_filter": True,        # Only London+US overlap
        "vol_ratio_min": 1.5,          # Volume confirmation required
        "rotatable": True,             # Auto-rotation by Gemma4
    },
}

def get_tier_config(symbol: str) -> dict:
    """Get the full tier config for a token."""
    tier = get_token_tier(symbol)
    return TIER_CONFIG.get(tier, TIER_CONFIG["meme"])

def get_tier_slippage(symbol: str) -> float:
    """Get slippage in bps for a token based on its tier."""
    return get_tier_config(symbol)["slippage_bps"]

def get_tier_leverage(symbol: str) -> float:
    """Get max leverage for a token based on its tier."""
    cfg = get_tier_config(symbol)
    if cfg["use_league_leverage"]:
        league_lev = get_cached_league_leverage()
        return min(league_lev, cfg["max_leverage"])
    return cfg["max_leverage"]


def reload_tokens() -> tuple[list[str], list[str]]:
    """Reload token lists from active_tokens.json without restarting the bot.
    
    Returns: (all_tokens, trading_tokens)
    """
    global TOKENS, TRADING_TOKENS
    TOKENS = load_active_tokens()
    TRADING_TOKENS = load_trading_tokens()
    return TOKENS, TRADING_TOKENS

# Timeframe for analysis
TIMEFRAME = "5m"  # 5 minutes as base timeframe for SMC (institutional execution layer)

# Datafeed Configuration
# - "1": use BingX WebSocket (low-latency) to detect new candles; falls back to REST polling on WS failure
# - "0": use REST polling only
USE_WS_FEED = os.getenv("USE_WS_FEED", "1").strip() == "1"

# Agent selection
# - "ppo_transformer": PPO with TransformerEncoder backbone (default)
# - "decision_transformer": offline DT policy (no on-policy learning in live loop)
AGENT_TYPE = os.getenv("AGENT_TYPE", "ppo_transformer").strip().lower()

# Decision Transformer config (only used when AGENT_TYPE=decision_transformer)
DT_CONTEXT_LEN = int(os.getenv("DT_CONTEXT_LEN", "32").strip())
DT_TARGET_RTG = float(os.getenv("DT_TARGET_RTG", "0.05").strip())

# Model weights (runtime loading)
# If the file exists, the runtime will load it on startup.
PPO_WEIGHTS_PATH = os.getenv("PPO_WEIGHTS_PATH", "/srv/profitlab_quantum/artifacts/ppo/ppo.pt").strip()
DT_WEIGHTS_PATH = os.getenv("DT_WEIGHTS_PATH", "/srv/profitlab_quantum/artifacts/dt/dt.pt").strip()
DT_META_PATH = os.getenv("DT_META_PATH", "/srv/profitlab_quantum/artifacts/dt/dt_meta.json").strip()

# PPO runtime layout / learning mode
# - Per-symbol weights avoids cross-symbol contamination.
# - Chunked learning updates the PPO policy on a schedule using a rolling time window.
PPO_PER_SYMBOL = os.getenv("PPO_PER_SYMBOL", "1").strip() == "1"
PPO_WEIGHTS_DIR = os.getenv(
    "PPO_WEIGHTS_DIR",
    "/srv/profitlab_quantum/artifacts/ppo/by_symbol",
).strip()

# PPO learning mode:
# - "online": update as soon as >=32 transitions are collected (legacy behavior)
# - "chunked": keep a rolling buffer (default 48h) and update every 12h
# OPTIMIZADO 22/04/2026: Entrenar 2x/día (noche) para reducir carga GPU
PPO_LEARNING_MODE = os.getenv("PPO_LEARNING_MODE", "chunked").strip().lower()
PPO_CHUNK_WINDOW_HOURS = float(os.getenv("PPO_CHUNK_WINDOW_HOURS", "36").strip())  # 36h rolling window
PPO_CHUNK_UPDATE_EVERY_HOURS = float(os.getenv("PPO_CHUNK_UPDATE_EVERY_HOURS", "2").strip())  # 2x/day (saves GPU)
PPO_CHUNK_MIN_SAMPLES = int(os.getenv("PPO_CHUNK_MIN_SAMPLES", "128").strip())  # Reduced from 64 for faster learning
PPO_CHUNK_MAX_SAMPLES = int(os.getenv("PPO_CHUNK_MAX_SAMPLES", "2048").strip())  # Reduced to focus on recent data

# Execution costs (paper realism)
# NOTE: BingX publishes fee schedules; default here is a conservative VIP0-style 0.10%.
# Override via env for your actual account tier / product (spot vs perpetual futures).
BINGX_API_KEY = os.getenv("BINGX_API_KEY", "").strip()
BINGX_SECRET_KEY = os.getenv("BINGX_SECRET_KEY", "").strip()

BINGX_FEE_MAKER = float(os.getenv("BINGX_FEE_MAKER", "0.001").strip())
BINGX_FEE_TAKER = float(os.getenv("BINGX_FEE_TAKER", "0.001").strip())

# Slippage model (basis points). Applied to paper fills.
# FIX 2026-03-02: 7.5 bps was unrealistically high for liquid crypto pairs.
# BingX perpetual futures on BTC/ETH/SOL typically see 1-3 bps slippage.
# [DUAL TIER v3] Slippage is now DYNAMIC per token tier.
# This global fallback is only used if tier lookup fails.
BINGX_SLIPPAGE_BPS = float(os.getenv("BINGX_SLIPPAGE_BPS", "10.0").strip())

# Microstructure / orderbook
USE_ORDERBOOK = os.getenv("USE_ORDERBOOK", "1").strip() == "1"
ORDERBOOK_LIMIT = int(os.getenv("ORDERBOOK_LIMIT", "20").strip())

# Risk Configuration
INITIAL_CAPITAL = 1000.0
