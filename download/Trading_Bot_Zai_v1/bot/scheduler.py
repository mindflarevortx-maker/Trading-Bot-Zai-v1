"""
Continuous Scheduler for Trading Bot Zai v1.2.

Implements the main loop:
  1. Connect to Quotex
  2. Fetch 30 days of 1-min historical data for all available assets (ONCE)
  3. Save/caches all data locally (persistent — never re-fetches)
  4. Generate TIME-ORDERED signals for next 1 hour
  5. Wait 1 hour
  6. Fetch ONLY the missing gap data for all assets (last hour)
  7. Merge gap data with cached data
  8. Re-run analysis on updated data + generate new signals
  9. Repeat from step 5

The key change: historical data is fetched ONCE and cached persistently.
Subsequent cycles only fetch the 1-hour gap to fill missing candles.
"""

import asyncio
import logging
import time
from typing import Optional

from bot.config import (
    FULL_REFRESH_INTERVAL_HOURS,
    CACHE_DURATION_SECONDS,
    HISTORY_SECONDS,
    CANDLE_PERIOD,
    USER_TZ,
)
from bot.quotex_client import QuotexClient
from bot.asset_manager import AssetManager
from bot.data_fetcher import DataFetcher
from bot.cache_manager import CacheManager
from bot.signal_generator import SignalGenerator
from datetime import datetime

logger = logging.getLogger("scheduler")


class TradingScheduler:
    """
    Main continuous trading scheduler.
    Fetches data ONCE, then only gap-fills on hourly cycles.
    """

    def __init__(self):
        self.client = QuotexClient()
        self.asset_manager = AssetManager()
        self.cache_manager = CacheManager()
        self.data_fetcher: Optional[DataFetcher] = None
        self.signal_generator: Optional[SignalGenerator] = None

        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cycle_count = 0
        self._last_full_refresh: float = 0
        self._status = "idle"

        # Signal storage for Flask API
        self._current_signals: list[dict] = []
        self._signal_history: list[dict] = []

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def status(self) -> str:
        return self._status

    @property
    def current_signals(self) -> list[dict]:
        return self._current_signals

    @property
    def signal_history(self) -> list[dict]:
        return self._signal_history

    @property
    def cycle_count(self) -> int:
        return self._cycle_count

    async def start(self) -> bool:
        """Start the trading scheduler."""
        if self._running:
            return True

        logger.info("Starting Trading Bot Zai v1.2...")

        # Step 1: Connect to Quotex
        self._status = "connecting"
        connected = await self.client.connect()
        if not connected:
            logger.error("Failed to connect to Quotex. Check credentials.")
            self._status = "connection_failed"
            return False

        # Step 2: Initialize asset manager
        self._status = "initializing_assets"
        await self.asset_manager.initialize(self.client)
        assets = self.asset_manager.available_assets
        if not assets:
            logger.error("No assets available.")
            self._status = "no_assets"
            return False
        logger.info(f"Trading {len(assets)} assets")

        # Step 3: Initialize data fetcher and signal generator
        self.data_fetcher = DataFetcher(self.client, max_concurrent=3)
        self.signal_generator = SignalGenerator(
            quotex_client=self.client,
            cache_manager=self.cache_manager,
            data_fetcher=self.data_fetcher,
        )

        # Step 4: Start main loop
        self._running = True
        self._task = asyncio.create_task(self._main_loop())
        logger.info("Trading Bot Zai v1.2 started successfully!")
        return True

    async def stop(self):
        """Stop the trading scheduler gracefully."""
        logger.info("Stopping Trading Bot Zai v1.2...")
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self.client.disconnect()
        self._status = "stopped"

    async def _main_loop(self):
        """Main continuous loop."""
        try:
            while self._running:
                self._cycle_count += 1
                cycle_start = time.time()

                now_local = datetime.now(tz=USER_TZ)
                logger.info(f"{'='*60}")
                logger.info(f"CYCLE #{self._cycle_count} STARTING at {now_local.strftime('%H:%M:%S')}")
                logger.info(f"{'='*60}")

                # Phase 1: Fetch or gap-fill data
                if self._cycle_count == 1:
                    await self._phase_initial_fetch()
                else:
                    await self._phase_gap_fill()

                # Phase 2: Generate time-ordered signals
                await self._phase_generate_signals()

                # Phase 3: Wait for next cycle
                cycle_elapsed = time.time() - cycle_start
                wait_time = max(0, FULL_REFRESH_INTERVAL_HOURS * 3600 - cycle_elapsed)

                if wait_time > 0:
                    self._status = "waiting"
                    next_cycle = datetime.fromtimestamp(
                        time.time() + wait_time, tz=USER_TZ
                    )
                    logger.info(
                        f"Cycle #{self._cycle_count} complete. "
                        f"Next cycle at {next_cycle.strftime('%H:%M:%S')} "
                        f"({wait_time/60:.1f} min)"
                    )
                    await self._interruptible_sleep(wait_time)

        except asyncio.CancelledError:
            logger.info("Main loop cancelled")
        except Exception as e:
            logger.error(f"Main loop error: {e}", exc_info=True)
            self._status = "error"

    async def _phase_initial_fetch(self):
        """
        Initial fetch: Get 30 days of historical data for ALL assets.
        Only fetch assets that don't already have cached data.
        """
        self._status = "fetching_initial_data"
        assets = self.asset_manager.available_assets

        # Check which assets already have cached data
        assets_to_fetch = [a for a in assets if not self.cache_manager.has_data(a)]
        cached_count = len(assets) - len(assets_to_fetch)

        logger.info(
            f"Phase 1: Initial data fetch — "
            f"{len(assets_to_fetch)} assets need data, "
            f"{cached_count} already cached"
        )

        if assets_to_fetch:
            results = await self.data_fetcher.fetch_all_assets(
                assets=assets_to_fetch,
                amount_of_seconds=HISTORY_SECONDS,
                period=CANDLE_PERIOD,
            )
            for asset, candles in results.items():
                if candles:
                    self.cache_manager.save(asset, candles)

        self._last_full_refresh = time.time()
        cached_total = sum(1 for a in assets if self.cache_manager.has_data(a))
        logger.info(f"Data ready: {cached_total}/{len(assets)} assets cached")

    async def _phase_gap_fill(self):
        """
        Hourly gap-fill: Fetch ONLY the missing hour of data and merge.
        Does NOT re-fetch the entire 30-day history.
        """
        self._status = "gap_filling"
        assets = self.asset_manager.available_assets
        logger.info(f"Phase 1b: Gap-fill for {len(assets)} assets...")

        await self.signal_generator.refresh_and_merge(assets)

        # Check for any assets that still have no data at all
        missing = [a for a in assets if not self.cache_manager.has_data(a)]
        if missing:
            logger.info(f"Found {len(missing)} assets with no data, fetching...")
            results = await self.data_fetcher.fetch_all_assets(
                assets=missing,
                amount_of_seconds=HISTORY_SECONDS,
                period=CANDLE_PERIOD,
            )
            for asset, candles in results.items():
                if candles:
                    self.cache_manager.save(asset, candles)

    async def _phase_generate_signals(self):
        """Generate TIME-ORDERED signals for the next hour."""
        self._status = "generating_signals"
        assets = self.asset_manager.available_assets

        # Only analyze assets that have cached data
        cached_assets = [a for a in assets if self.cache_manager.has_data(a)]
        logger.info(f"Phase 2: Generating signals for {len(cached_assets)} cached assets...")

        signals = await self.signal_generator.generate_signals(cached_assets)

        # Store current signals
        self._current_signals = [s.to_dict() for s in signals]

        # Add to history
        timestamp = time.time()
        for s in signals:
            self._signal_history.append({
                **s.to_dict(),
                "cycle": self._cycle_count,
                "generated_at": timestamp,
            })
        if len(self._signal_history) > 1000:
            self._signal_history = self._signal_history[-1000:]

        # Print signal timeline
        up_count = sum(1 for s in signals if s.direction == "UP")
        down_count = sum(1 for s in signals if s.direction == "DOWN")

        now_local = datetime.now(tz=USER_TZ)
        end_local = datetime.fromtimestamp(
            time.time() + FULL_REFRESH_INTERVAL_HOURS * 3600, tz=USER_TZ
        )

        logger.info(f"{'='*60}")
        logger.info(f"SIGNAL TIMELINE — Cycle #{self._cycle_count}")
        logger.info(f"  {now_local.strftime('%H:%M')} → {end_local.strftime('%H:%M')} ({USER_TZ})")
        logger.info(f"  Total: {len(signals)} | 🟢 UP: {up_count} | 🔴 DOWN: {down_count}")
        logger.info(f"{'='*60}")

        for s in signals:
            martingale_info = ""
            if s.martingale and len(s.martingale) > 1:
                m = s.martingale[1]
                martingale_info = f" | Martingale: {m['amount']}x if loss"

            logger.info(
                f"  {s.trade_time_local}  {s.emoji} {s.asset:20s} "
                f"{s.direction:4s} ({s.confidence:.1f}%){martingale_info}"
            )

        if not signals:
            logger.info("  No high-confidence signals this cycle")

        logger.info(f"{'='*60}")

    async def _interruptible_sleep(self, seconds: float):
        """Sleep that can be interrupted by stop()."""
        check_interval = 5
        elapsed = 0.0
        while elapsed < seconds and self._running:
            sleep_time = min(check_interval, seconds - elapsed)
            await asyncio.sleep(sleep_time)
            elapsed += sleep_time

    def get_status_dict(self) -> dict:
        """Get full status information."""
        cache_stats = self.cache_manager.get_cache_stats()
        asset_stats = self.asset_manager.get_stats()
        now_local = datetime.now(tz=USER_TZ)

        return {
            "running": self._running,
            "status": self._status,
            "cycle_count": self._cycle_count,
            "connected": self.client.is_connected,
            "assets": asset_stats,
            "cache": cache_stats,
            "current_signals_count": len(self._current_signals),
            "signal_history_count": len(self._signal_history),
            "last_full_refresh": self._last_full_refresh,
            "local_time": now_local.strftime("%Y-%m-%d %H:%M:%S"),
            "timezone": str(USER_TZ),
        }
