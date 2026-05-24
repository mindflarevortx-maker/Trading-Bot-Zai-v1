"""
Configuration for Trading Bot Zai v1.2.
All tunable parameters are centralized here.
"""

import os
from pathlib import Path
from datetime import timezone, timedelta

# ─── Paths ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_CACHE_DIR = BASE_DIR / "data_cache"
SESSION_FILE = BASE_DIR / "session.json"
LOG_DIR = BASE_DIR / "logs"

# ─── Quotex Credentials ──────────────────────────────────────────────
QUOTEX_EMAIL = os.getenv("QUOTEX_EMAIL", "")
QUOTEX_PASSWORD = os.getenv("QUOTEX_PASSWORD", "")
QUOTEX_HOST = os.getenv("QUOTEX_HOST", "market-qx.trade")
QUOTEX_LANG = os.getenv("QUOTEX_LANG", "en")

# ─── Account Mode ────────────────────────────────────────────────────
# "PRACTICE" or "REAL"
ACCOUNT_MODE = os.getenv("ACCOUNT_MODE", "PRACTICE")

# ─── Candle / Data Settings ─────────────────────────────────────────
CANDLE_PERIOD = 60                    # 1-minute candles (in seconds)
HISTORY_DAYS = 30                     # 30 days of historical data
HISTORY_SECONDS = HISTORY_DAYS * 86400

# ─── Cache Settings ──────────────────────────────────────────────────
# Cache is PERSISTENT — data never expires once fetched.
# On hourly refresh, only the gap between cached and live data is fetched.
CACHE_DURATION_HOURS = 0              # 0 = never expire (persistent)
CACHE_DURATION_SECONDS = 0            # 0 = never expire

# ─── Backtesting Settings ────────────────────────────────────────────
BACKTEST_WINDOW = 500                 # Last N candles for pattern backtesting
MIN_CONFIDENCE_PCT = 95.0             # Minimum confidence % to emit a signal

# ─── Signal Generation Settings ──────────────────────────────────────
SIGNAL_LOOKAHEAD_MINUTES = 60         # Generate signals for next 60 minutes
SIGNAL_GENERATION_INTERVAL = 60       # Generate signals every 60 seconds
SIGNAL_FORECAST_HOURS = 1             # Forecast window in hours

# ─── Martingale Settings ─────────────────────────────────────────────
MARTINGALE_STEPS = 1                  # Number of martingale steps (1 = double once)
MARTINGALE_MULTIPLIER = 2.0           # Multiply bet by this on loss
MARTINGALE_BASE_AMOUNT = 1            # Base trade amount (for display)

# ─── Timezone ─────────────────────────────────────────────────────────
# User's timezone for signal display (UTC+5:00 = Asia/Karachi)
TIMEZONE_OFFSET_HOURS = int(os.getenv("TIMEZONE_OFFSET_HOURS", "5"))
TIMEZONE_OFFSET_MINUTES = int(os.getenv("TIMEZONE_OFFSET_MINUTES", "0"))
USER_TZ = timezone(timedelta(
    hours=TIMEZONE_OFFSET_HOURS,
    minutes=TIMEZONE_OFFSET_MINUTES,
))

# ─── Scheduler Settings ──────────────────────────────────────────────
CYCLE_INTERVAL_SECONDS = 10           # Check cycle every 10 seconds
FULL_REFRESH_INTERVAL_HOURS = 1       # Full data refresh every 1 hour

# ─── Data Fetching ───────────────────────────────────────────────────
FETCH_MAX_CONCURRENT = 3              # Parallel asset fetches
FETCH_RETRIES = 3                     # Retry attempts per asset
FETCH_BATCH_TIMEOUT = 30              # Seconds per batch request timeout
FETCH_MAX_WORKERS = 3                 # Workers for historical candle fetching

# ─── Flask Settings ──────────────────────────────────────────────────
FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() == "true"

# ─── Logging ─────────────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

# ─── Proxy (optional) ───────────────────────────────────────────────
PROXY_HTTP = os.getenv("PROXY_HTTP", "")
PROXY_HTTPS = os.getenv("PROXY_HTTPS", "")

# ─── Asset Categories ────────────────────────────────────────────────
FOREX_PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "USDCAD",
    "EURGBP", "EURJPY", "GBPJPY", "CHFJPY", "AUDJPY", "NZDJPY", "CADJPY",
    "EURCHF", "EURCAD", "EURAUD", "EURNZD", "GBPAUD", "GBPNZD", "GBPCAD",
    "GBPCHF", "AUDCAD", "AUDCHF", "AUDNZD", "NZDCAD", "NZDCHF", "CADCHF",
    "USDSGD", "USDHKD", "USDSEK", "USDNOK", "USDDKK", "USDZAR", "USDMXN",
    "USDTRY", "USDPLN", "USDCZK", "USDHUF", "USDTHB", "USDCNH", "USDINR",
    "USDPKR", "USDBDT", "USDRUB", "USDBRL", "USDCOP", "USDARS", "USDCLP",
    "USDVND", "USDPHP", "USDMYR", "USDIDR", "USDKRW", "USDTWD", "USDEGP",
]

OTC_PAIRS = [f"{p}_otc" for p in FOREX_PAIRS]

COMMODITY_PAIRS = [
    "XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD",
    "XAUUSD_otc", "XAGUSD_otc",
    "UKBRENT", "UKOIL", "USOIL", "NATGASUS",
]

CRYPTO_PAIRS = [
    "BTCUSD", "ETHUSD", "LTCUSD", "XRPUSD", "ADAUSD",
    "BTCUSD_otc", "ETHUSD_otc",
]

INDEX_PAIRS = [
    "US100", "US30", "SPX500", "UK100", "DAX30", "CAC40",
    "NIKKEI225", "HSI50", "AUS200",
    "US100_otc", "US30_otc", "SPX500_otc",
]

ALL_TARGET_ASSETS = FOREX_PAIRS + OTC_PAIRS + COMMODITY_PAIRS + CRYPTO_PAIRS + INDEX_PAIRS

# ─── Ensure directories exist ────────────────────────────────────────
DATA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
