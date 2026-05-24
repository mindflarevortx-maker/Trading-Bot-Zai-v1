#!/usr/bin/env python3
"""
Trading Bot Zai v1 — Main Entry Point

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
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

# ─── Load .env file BEFORE importing config ──────────────────────────
def load_dotenv():
    """Load .env file into os.environ if it exists."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'\"")
                # Only set if not already in environment
                if key and key not in os.environ:
                    os.environ[key] = value

load_dotenv()

from bot.config import (
    QUOTEX_EMAIL, QUOTEX_PASSWORD, QUOTEX_HOST, FLASK_HOST, FLASK_PORT,
    LOG_LEVEL, LOG_FORMAT, LOG_DIR, ACCOUNT_MODE,
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
    for noisy in ["urllib3", "websocket", "httpx", "httpcore", "engineio", "socketio"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    return root_logger


# ─── Banner ────────────────────────────────────────────────────────────

BANNER = """
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║              🤖 TRADING BOT ZAI v1 🤖                        ║
║                                                               ║
║         Quotex Signal Generator — 1-Min Binary Options       ║
║                                                               ║
║  • 100+ Asset Pairs (Forex, OTC, Crypto, Commodities)        ║
║  • 30-Day Historical Analysis with 1-Min Candles             ║
║  • Multi-Layer Confluence Strategy + Backtesting              ║
║  • Continuous Hourly Signal Generation                        ║
║  • 🟢 UP  /  🔴 DOWN  Signal Display                         ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
"""


# ─── Main ──────────────────────────────────────────────────────────────

async def main():
    """Main async entry point."""
    print(BANNER)

    logger = setup_logging()
    logger.info("Trading Bot Zai v1 starting...")

    # Validate credentials
    if not QUOTEX_EMAIL or not QUOTEX_PASSWORD:
        print("\n❌ ERROR: Quotex credentials not set!")
        print("\nSet them via environment variables:")
        print("  export QUOTEX_EMAIL='your_email@example.com'")
        print("  export QUOTEX_PASSWORD='your_password'")
        print("\nOr create a .env file in the project root:")
        print("  QUOTEX_EMAIL=your_email@example.com")
        print("  QUOTEX_PASSWORD=your_password")
        print("  QUOTEX_HOST=market-qx.trade")
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
    print(f"   Mode: {ACCOUNT_MODE}")
    print(f"   Assets: 100+ pairs (Forex, OTC, Crypto, Commodities, Indices)")
    print(f"   Strategy: 7-Layer Confluence + Backtesting")
    print(f"   Signal threshold: 95%+ confidence")
    print()

    started = await scheduler.start()
    if not started:
        print("\n❌ Failed to start. Check logs for details.")
        print("   Common fixes:")
        print("   1. Check your email/password in .env")
        print("   2. Make sure QUOTEX_HOST is correct (e.g. market-qx.trade)")
        print("   3. Delete session.json and retry")
        print("   4. Check your internet connection")
        sys.exit(1)

    # Keep running until interrupted
    try:
        while scheduler.is_running:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n\n⏹️  Stopping Trading Bot Zai v1...")
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
