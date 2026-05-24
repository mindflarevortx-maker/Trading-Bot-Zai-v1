"""
Configuration for Trading Bot Zai v1.
All tunable parameters are centralized here.
"""

import os
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_CACHE_DIR = BASE_DIR / "data_cache"
SESSION_FILE = BASE_DIR / "session.json"
LOG_DIR = BASE_DIR / "logs"

# ─── Quotex Credentials ──────────────────────────────────────────────
QUOTEX_EMAIL = os.getenv("QUOTEX_EMAIL", "")
QUOTEX_PASSWORD = os.getenv("QUOTEX_PASSWORD", "")
QUOTEX_HOST = os.getenv("QUOTEX_HOST", "qxbroker.com")
QUOTEX_LANG = os.getenv("QUOTEX_LANG", "en")

# ─── Account Mode ────────────────────────────────────────────────────
# "PRACTICE" or "REAL"
ACCOUNT_MODE = os.getenv("ACCOUNT_MODE", "PRACTICE")

# ─── Candle / Data Settings ─────────────────────────────────────────
CANDLE_PERIOD = 60                    # 1-minute candles (in seconds)
HISTORY_DAYS = 30                     # 30 days of historical data
HISTORY_SECONDS = HISTORY_DAYS * 86400

# ─── Cache Settings ──────────────────────────────────────────────────
CACHE_DURATION_HOURS = 1              # Cache data for 1 hour
CACHE_DURATION_SECONDS = CACHE_DURATION_HOURS * 3600

# ─── Backtesting Settings ────────────────────────────────────────────
BACKTEST_WINDOW = 500                 # Last N candles for pattern backtesting
MIN_CONFIDENCE_PCT = 95.0             # Minimum confidence % to emit a signal
                                    # (user wants ~100%, we set 95 as practical threshold)

# ─── Signal Generation Settings ──────────────────────────────────────
SIGNAL_LOOKAHEAD_MINUTES = 1          # Predict next 1 minute
SIGNAL_GENERATION_INTERVAL = 60       # Generate signals every 60 seconds

# ─── Scheduler Settings ──────────────────────────────────────────────
CYCLE_INTERVAL_SECONDS = 10           # Check cycle every 10 seconds
FULL_REFRESH_INTERVAL_HOURS = 1       # Full data refresh every 1 hour

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
# These prefixes help categorize assets for filtering
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

# OTC versions of the above
OTC_PAIRS = [f"{p}_otc" for p in FOREX_PAIRS]

# Commodities
COMMODITY_PAIRS = [
    "XAUUSD", "XAGUSD", "XPTUSD", "XPDUSD",
    "XAUUSD_otc", "XAGUSD_otc",
    "UKBRENT", "UKOIL", "USOIL", "NATGASUS",
]

# Crypto
CRYPTO_PAIRS = [
    "BTCUSD", "ETHUSD", "LTCUSD", "XRPUSD", "ADAUSD",
    "BTCUSD_otc", "ETHUSD_otc",
]

# Indices
INDEX_PAIRS = [
    "US100", "US30", "SPX500", "UK100", "DAX30", "CAC40",
    "NIKKEI225", "HSI50", "AUS200",
    "US100_otc", "US30_otc", "SPX500_otc",
]

# All target assets
ALL_TARGET_ASSETS = FOREX_PAIRS + OTC_PAIRS + COMMODITY_PAIRS + CRYPTO_PAIRS + INDEX_PAIRS

# ─── Ensure directories exist ────────────────────────────────────────
DATA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)
