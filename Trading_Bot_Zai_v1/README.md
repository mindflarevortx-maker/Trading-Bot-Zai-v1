# 🤖 Trading Bot Zai v1

**Quotex Signal Generator — 1-Minute Binary Options**

A professional-grade trading signal bot that analyzes 30 days of 1-minute historical candle data across 100+ asset pairs (Forex, OTC, Crypto, Commodities, Indices) using a multi-layer confluence strategy with backtesting validation.

---

## 📋 Table of Contents

- [Features](#features)
- [How It Works](#how-it-works)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Bot](#running-the-bot)
- [Understanding the Signals](#understanding-the-signals)
- [Strategy Details](#strategy-details)
- [Project Structure](#project-structure)
- [API Endpoints](#api-endpoints)
- [Troubleshooting](#troubleshooting)
- [Disclaimer](#disclaimer)

---

## ✨ Features

- **100+ Asset Pairs** — Covers all major/minor Forex pairs, OTC pairs, commodities (Gold, Silver, Oil), crypto (BTC, ETH), and stock indices
- **30-Day Historical Analysis** — Analyzes 43,200+ one-minute candles per asset for deep pattern recognition
- **7-Layer Confluence Strategy** — Trend, Momentum, MACD, Bollinger, Stochastic, Candlestick Patterns, Ichimoku Cloud
- **Walk-Forward Backtesting** — Every signal is validated against historical data before being emitted
- **95%+ Confidence Threshold** — Signals are only generated when backtesting confirms high accuracy
- **1-Hour Caching System** — Data is cached and incrementally merged each hour to avoid redundant API calls
- **Continuous Operation** — Runs 24/7 with automatic hourly refresh cycles
- **Real-Time Web Dashboard** — Flask-powered dashboard with 🟢 UP / 🔴 DOWN signal display
- **Candlestick Pattern Recognition** — Detects engulfing, hammer, shooting star, morning/evening star, doji patterns
- **Auto-Reconnection** — Handles connection drops gracefully

---

## 🔄 How It Works

```
┌─────────────────────────────────────────────────────────────┐
│                    STARTUP                                    │
│  1. Connect to Quotex (email + password auth)               │
│  2. Discover 100+ available asset pairs                      │
│  3. Fetch 30 days of 1-min candle data for each asset       │
│  4. Cache all data locally                                   │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│              SIGNAL GENERATION CYCLE                         │
│                                                              │
│  1. Load cached 30-day historical data                      │
│  2. Compute all 7 technical indicator layers                 │
│  3. Run confluence strategy (need 6/7 layers to agree)      │
│  4. Run walk-forward backtesting on historical data          │
│  5. Calculate final confidence = 40% strategy + 60% backtest│
│  6. If confidence >= 95% → emit 🟢 UP or 🔴 DOWN signal    │
│  7. Display signals on dashboard                             │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────┐
│              HOURLY REFRESH (Repeat)                         │
│                                                              │
│  1. Fetch the most recent 1 hour of candle data             │
│  2. Merge new data with cached data (fill gaps)             │
│  3. Trim to 30-day window                                   │
│  4. Re-run backtesting on updated data                      │
│  5. Generate new signals for next hour                      │
│  6. Repeat until stopped                                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 📦 Prerequisites

- **Python 3.9+**
- **Quotex account** (email + password) — Use a DEMO/PRACTICE account for testing
- **Internet connection** — Stable connection for WebSocket + HTTP API calls
- **pip** — Python package manager

---

## 🛠️ Installation

### Step 1: Extract the ZIP

```bash
unzip Trading_Bot_Zai_v1.zip
cd Trading_Bot_Zai_v1
```

### Step 2: Create a virtual environment (recommended)

```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# OR
venv\Scripts\activate     # Windows
```

### Step 3: Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Install pyquotex (Quotex API library)

```bash
pip install pyquotex
```

If `pyquotex` is not available on PyPI, install from the source repo:

```bash
pip install git+https://github.com/cleitonleonel/pyquotex.git
```

### Step 5: Configure your credentials

```bash
cp .env.example .env
```

Edit `.env` and add your Quotex credentials:

```env
QUOTEX_EMAIL=your_email@example.com
QUOTEX_PASSWORD=your_password
ACCOUNT_MODE=PRACTICE
```

> ⚠️ **IMPORTANT**: Always start with `ACCOUNT_MODE=PRACTICE` (demo account) to test the bot without risking real money.

---

## ⚙️ Configuration

All configuration is in `.env` or `bot/config.py`.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `QUOTEX_EMAIL` | *required* | Your Quotex account email |
| `QUOTEX_PASSWORD` | *required* | Your Quotex account password |
| `ACCOUNT_MODE` | `PRACTICE` | `PRACTICE` (demo) or `REAL` (live) |
| `QUOTEX_HOST` | `qxbroker.com` | Quotex server host |
| `QUOTEX_LANG` | `en` | Language for the web interface |
| `FLASK_HOST` | `0.0.0.0` | Flask dashboard host |
| `FLASK_PORT` | `5000` | Flask dashboard port |
| `PROXY_HTTP` | *empty* | HTTP proxy URL (optional) |
| `PROXY_HTTPS` | *empty* | HTTPS proxy URL (optional) |
| `LOG_LEVEL` | `INFO` | Logging level |

### Advanced Settings (in `bot/config.py`)

| Setting | Default | Description |
|---------|---------|-------------|
| `HISTORY_DAYS` | 30 | Days of historical data to analyze |
| `CANDLE_PERIOD` | 60 | Candle period in seconds (1 min) |
| `CACHE_DURATION_HOURS` | 1 | How long to cache data before refresh |
| `MIN_CONFIDENCE_PCT` | 95.0 | Minimum confidence % to emit a signal |
| `BACKTEST_WINDOW` | 500 | Candles used for backtesting window |

---

## 🚀 Running the Bot

### Start the bot

```bash
python run.py
```

You will see:

```
╔═══════════════════════════════════════════════════════════════╗
║              🤖 TRADING BOT ZAI v1 🤖                        ║
║         Quotex Signal Generator — 1-Min Binary Options       ║
╚═══════════════════════════════════════════════════════════════╝

🌐 Dashboard: http://0.0.0.0:5000
🚀 Starting trading bot...
```

### Open the dashboard

Navigate to **http://localhost:5000** in your browser to see live signals.

### Stop the bot

Press `Ctrl+C` in the terminal to gracefully stop the bot.

---

## 📊 Understanding the Signals

### Signal Format

| Symbol | Meaning |
|--------|---------|
| 🟢 | **UP** signal — The bot predicts the next 1-minute candle will close higher than it opens |
| 🔴 | **DOWN** signal — The bot predicts the next 1-minute candle will close lower than it opens |

### Confidence Score

The confidence score (0-100%) is calculated as:

```
Final Confidence = (Strategy Confidence × 0.4) + (Backtest Win Rate × 0.6)
```

- **Strategy Confidence**: How many of the 7 analysis layers agree on the direction
- **Backtest Win Rate**: Historical accuracy of the strategy on this specific asset

Signals are only emitted when `Final Confidence >= 95%`.

### Category Badges

| Badge | Category | Examples |
|-------|----------|----------|
| `forex` | Standard Forex pairs | EURUSD, GBPUSD, USDJPY |
| `otc` | Over-The-Counter pairs | EURUSD_otc, USDPKR_otc |
| `commodity` | Gold, Silver, Oil | XAUUSD, XAGUSD, UKOIL |
| `crypto` | Cryptocurrency | BTCUSD, ETHUSD |
| `index` | Stock Indices | US100, DAX30, NIKKEI225 |

---

## 🧠 Strategy Details

### 7-Layer Confluence Strategy

The bot uses 7 independent analysis layers. A signal requires at least 6 of 7 layers to agree:

#### Layer 1: Trend Detection
- **Indicators**: EMA-20, EMA-50, ADX-14
- **Bullish**: Price > EMA-20 > EMA-50 with ADX > 25
- **Bearish**: Price < EMA-20 < EMA-50 with ADX > 25

#### Layer 2: Momentum (RSI)
- **Indicators**: RSI-7, RSI-14
- **Bullish**: RSI-7 < 30 and RSI-14 < 35 (oversold reversal)
- **Bearish**: RSI-7 > 70 and RSI-14 > 65 (overbought reversal)

#### Layer 3: MACD
- **Indicators**: MACD(12,26,9) line, signal, histogram
- **Bullish**: MACD line > signal line with expanding histogram
- **Bearish**: MACD line < signal line with expanding histogram

#### Layer 4: Bollinger Bands
- **Indicators**: BB(20, 2.0) upper, middle, lower
- **Bullish**: Price near lower band (< 5th percentile)
- **Bearish**: Price near upper band (> 95th percentile)

#### Layer 5: Stochastic Oscillator
- **Indicators**: Stochastic(14,3,3) %K, %D
- **Bullish**: Bullish crossover in oversold zone (%K, %D < 20)
- **Bearish**: Bearish crossover in overbought zone (%K, %D > 80)

#### Layer 6: Candlestick Patterns
- **Patterns**: Engulfing, Hammer, Shooting Star, Morning/Evening Star, Doji
- **Bullish**: Bullish Engulfing, Hammer, Morning Star
- **Bearish**: Bearish Engulfing, Shooting Star, Evening Star

#### Layer 7: Ichimoku Cloud
- **Indicators**: Tenkan-sen, Kijun-sen, Senkou Span A/B
- **Bullish**: Price above cloud + TK bullish cross
- **Bearish**: Price below cloud + TK bearish cross

### Backtesting Engine

The backtester uses walk-forward validation:

1. Takes the last 500 candles of historical data
2. Slides a 200-candle window forward, one step at a time
3. At each step, runs the strategy and records the signal
4. Compares each signal against the actual next candle's direction
5. Calculates win rate, profit factor, and direction-specific accuracy
6. Signals are only approved if backtest win rate >= 95%

---

## 📁 Project Structure

```
Trading_Bot_Zai_v1/
├── run.py                    # Main entry point
├── requirements.txt          # Python dependencies
├── .env.example              # Environment variable template
├── README.md                 # This guide
│
├── bot/                      # Core bot package
│   ├── __init__.py           # Package init
│   ├── config.py             # Configuration & constants
│   ├── quotex_client.py      # Quotex API client wrapper
│   ├── asset_manager.py      # Asset pair management (100+ pairs)
│   ├── data_fetcher.py       # Historical data fetching with rate limiting
│   ├── cache_manager.py      # 1-hour cache with merge logic
│   ├── indicators.py         # All technical indicators (pure Python)
│   ├── strategy.py           # 7-Layer confluence strategy + patterns
│   ├── backtester.py         # Walk-forward backtesting engine
│   ├── signal_generator.py   # Signal generation orchestrator
│   ├── scheduler.py          # Continuous hourly scheduler
│   └── flask_app.py          # Flask web dashboard
│
├── data_cache/               # Cached candle data (auto-created)
├── logs/                     # Log files (auto-created)
├── static/                   # Flask static files
└── templates/                # Flask templates
```

---

## 🌐 API Endpoints

The Flask server exposes these REST API endpoints:

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/` | Interactive web dashboard |
| GET | `/api/signals` | Current active signals (JSON) |
| GET | `/api/status` | Bot status and statistics (JSON) |
| GET | `/api/history?limit=100` | Signal history (JSON) |
| GET | `/api/assets` | Available asset list and stats |
| GET | `/api/cache/stats` | Cache statistics |

### Example API Response

```json
GET /api/signals

[
  {
    "asset": "EURUSD_otc",
    "direction": "UP",
    "direction_emoji": "🟢",
    "direction_arrow": "▲",
    "confidence": 97.3,
    "timestamp": 1700000000,
    "expires_at": 1700000060,
    "is_expired": false,
    "strategy": {
      "up_votes": 7,
      "down_votes": 0,
      "neutral_votes": 0,
      "layers": {
        "trend": {"direction": "UP", "reason": "EMA bullish alignment, ADX=32.5 (strong)"},
        "momentum": {"direction": "UP", "reason": "Oversold RSI7=28.1, RSI14=33.2"},
        ...
      },
      "patterns_detected": [
        {"pattern": "bullish_engulfing", "direction": "bullish"}
      ]
    },
    "backtest": {
      "total_trades": 45,
      "wins": 43,
      "losses": 2,
      "win_rate": 95.56,
      ...
    }
  }
]
```

---

## 🔧 Troubleshooting

### "Connection failed" error

- Verify your Quotex email and password in `.env`
- Check your internet connection
- Try using a proxy if Quotex is blocked in your region
- Delete `session.json` and retry (stale session)

### "No assets available"

- Your Quotex account may not have access to all assets
- Try logging into the Quotex web platform first to verify your account
- Some assets are only available during market hours

### "Insufficient data" warnings

- OTC pairs may have less historical data
- Some exotic pairs may not have 30 days of history
- This is normal — the bot will skip assets with insufficient data

### Flask dashboard not loading

- Check if port 5000 is already in use: `lsof -i :5000`
- Change the port in `.env`: `FLASK_PORT=8080`
- Make sure you're accessing the correct host

### Rate limiting / Connection drops

- The bot includes rate limiting (3 concurrent requests) and retry logic
- If you get rate-limited, reduce `max_concurrent` in `data_fetcher.py`
- Use a proxy for better stability
- The bot auto-reconnects on connection drops

### Session expiration

- Quotex sessions expire periodically
- The bot automatically re-authenticates when the session expires
- If re-auth fails, check your credentials and restart the bot

---

## ⚠️ Disclaimer

**This bot is for educational and research purposes only.**

- Trading binary options involves significant risk of loss
- Past performance (backtesting) does not guarantee future results
- No signal is 100% accurate — the "approximately 100% confidence" refers to the strategy's internal agreement level, not actual market certainty
- Always use a PRACTICE/DEMO account first
- Never trade with money you cannot afford to lose
- The authors are not responsible for any financial losses

---

## 📄 License

This project is provided as-is for educational purposes. Use at your own risk.

---

**Built with ❤️ by Z AI**
