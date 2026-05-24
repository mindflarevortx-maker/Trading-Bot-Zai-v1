#!/usr/bin/env python3
"""
Trading Bot Zai v1.2 — Main Entry Point

Run this script to start the trading bot:
    python run.py

The bot will:
  1. Connect to Quotex using your credentials
  2. Fetch 30 days of 1-minute historical data for 100+ assets
  3. Run backtesting to validate the strategy
  4. Generate high-confidence signals for the next hour
  5. Refresh and repeat every hour automatically

Signals are displayed at: http://localhost:5000
"""

import asyncio
import logging
import os
import sys
import signal as sig
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# ─── Load .env file BEFORE importing config ────────────────────────
# config.py reads env vars at import time, so we must load .env first.
try:
    from dotenv import load_dotenv
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Loaded .env from {env_path}")
    else:
        print(f"⚠️  No .env file found at {env_path}")
        print(f"   Copy .env.example to .env and fill in your credentials.")
except ImportError:
    print("⚠️  python-dotenv not installed. Install with: pip install python-dotenv")
    print("   Environment variables must be set manually.")

from bot.config import (
    QUOTEX_EMAIL, QUOTEX_PASSWORD, QUOTEX_HOST, FLASK_HOST, FLASK_PORT,
    LOG_LEVEL, LOG_FORMAT, LOG_DIR,
)
from bot.scheduler import TradingScheduler
from bot.flask_app import run_flask

# ─── Setup Logging ────────────────────────────────────────────────────

def setup_logging():
    """Configure logging to both console and file."""
    log_dir = LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "trading_bot.log"

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.addHandler(console)

    # File handler
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root_logger.addHandler(file_handler)

    # Reduce noise from third-party loggers
    for noisy in ["urllib3", "websocket", "httpx", "httpcore", "engineio", "socketio", "pyquotex._api.history"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return root_logger


# ─── Banner ────────────────────────────────────────────────────────────

BANNER = """
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║            🤖 TRADING BOT ZAI v1.2 🤖                        ║
║                                                               ║
║       Quotex Signal Timeline — 1-Min Binary Options           ║
║                                                               ║
║  • 100+ Asset Pairs (Forex, OTC, Crypto, Commodities)        ║
║  • 30-Day Historical Analysis with 1-Min Candles             ║
║  • Time-Ordered Signals with Exact Trade Times (UTC+5)       ║
║  • 7-Layer Confluence Strategy + Backtesting                  ║
║  • Persistent Cache (fetch once, gap-fill hourly)             ║
║  • 🟢 UP  /  🔴 DOWN  + 1 Martingale Step                    ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
"""


# ─── Main ──────────────────────────────────────────────────────────────

async def main():
    """Main async entry point."""
    print(BANNER)

    logger = setup_logging()
    logger.info("Trading Bot Zai v1.2 starting...")

    # Validate credentials
    if not QUOTEX_EMAIL or not QUOTEX_PASSWORD:
        print("\n❌ ERROR: Quotex credentials not set!")
        print("\nSet them via environment variables:")
        print("  export QUOTEX_EMAIL='your_email@example.com'")
        print("  export QUOTEX_PASSWORD='your_password'")
        print("\nOr create a .env file in the project root:")
        print("  QUOTEX_EMAIL=your_email@example.com")
        print("  QUOTEX_PASSWORD=your_password")
        sys.exit(1)

    # Initialize scheduler
    scheduler = TradingScheduler()

    # Start Flask dashboard in background thread
    flask_thread = run_flask(scheduler, FLASK_HOST, FLASK_PORT)
    print(f"\n🌐 Dashboard: http://{FLASK_HOST}:{FLASK_PORT}")
    print(f"   (Use 0.0.0.0 to access from other devices)")

    # Start the trading scheduler
    print(f"\n🚀 Starting trading bot...")
    print(f"   Host: {QUOTEX_HOST}")
    print(f"   Email: {QUOTEX_EMAIL[:3]}***@{QUOTEX_EMAIL.split('@')[1] if '@' in QUOTEX_EMAIL else '***'}")
    print(f"   Mode: PRACTICE")
    print(f"   Assets: 100+ pairs (Forex, OTC, Crypto, Commodities, Indices)")
    print(f"   Strategy: 7-Layer Confluence + Backtesting")
    print(f"   Signal threshold: 95%+ confidence")
    print(f"   Signals: Time-ordered with exact trade times (UTC+5)")
    print(f"   Martingale: 1 step (2x on loss)")
    print()

    started = await scheduler.start()
    if not started:
        print("\n❌ Failed to start. Check logs for details.")
        sys.exit(1)

    # Keep running until interrupted
    try:
        while scheduler.is_running:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n\n⏹️  Stopping Trading Bot Zai v1.2...")
        await scheduler.stop()
        print("✅ Bot stopped. Goodbye!")


def run():
    """Synchronous wrapper for the async main."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⏹️  Bot terminated by user.")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        logging.getLogger().error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    run()
