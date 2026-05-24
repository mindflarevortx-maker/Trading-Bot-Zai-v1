"""
Continuous Scheduler for Trading Bot Zai v1.

Implements the main loop:
  1. Connect to Quotex
  2. Initial fetch: 30 days of 1-min historical data for all assets
  3. Run backtesting on all assets
  4. Generate signals for the next 1 hour
  5. Wait 1 hour
  6. Fetch recent hour data, merge with cached data
  7. Re-run backtesting on merged data
  8. Generate new signals
  9. Repeat from step 5

The scheduler runs as an asyncio task and can be started/stopped.
"""

import asyncio
import logging
import time
from typing import Optional

from bot.config import (
    FULL_REFRESH_INTERVAL_HOURS,
    SIGNAL_GENERATION_INTERVAL,
    CACHE_DURATION_SECONDS,
    HISTORY_SECONDS,
    CANDLE_PERIOD,
)
from bot.quotex_client import QuotexClient
from bot.asset_manager import AssetManager
from bot.data_fetcher import DataFetcher
from bot.cache_manager import CacheManager
from bot.signal_generator import SignalGenerator

logger = logging.getLogger("scheduler")


class TradingScheduler:
    """
    Main continuous trading scheduler.
    Manages the full lifecycle: connect → fetch → analyze → signal → refresh → repeat.
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
        """
        Start the trading scheduler.
        Connects to Quotex, initializes assets, and begins the main loop.
        """
        if self._running:
            logger.warning("Scheduler is already running")
            return True

        logger.info("Starting Trading Bot Zai v1...")

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
            logger.error("No assets available. Check your Quotex account.")
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

        # Step 4: Start the main loop as an async task
        self._running = True
        self._task = asyncio.create_task(self._main_loop())

        logger.info("Trading Bot Zai v1 started successfully!")
        return True

    async def stop(self):
        """Stop the trading scheduler gracefully."""
        logger.info("Stopping Trading Bot Zai v1...")
        self._running = False

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        await self.client.disconnect()
        self._status = "stopped"
        logger.info("Trading Bot Zai v1 stopped.")

    async def _main_loop(self):
        """Main continuous loop."""
        try:
            while self._running:
                self._cycle_count += 1
                cycle_start = time.time()

                logger.info(f"{'='*60}")
                logger.info(f"CYCLE #{self._cycle_count} STARTING")
                logger.info(f"{'='*60}")

                # ─── Phase 1: Initial or Full Refresh ──────────────────
                if self._cycle_count == 1 or self._need_full_refresh():
                    await self._phase_full_refresh()
                else:
                    await self._phase_hourly_refresh()

                # ─── Phase 2: Generate Signals ─────────────────────────
                await self._phase_generate_signals()

                # ─── Phase 3: Wait for next cycle ──────────────────────
                cycle_elapsed = time.time() - cycle_start
                wait_time = max(0, FULL_REFRESH_INTERVAL_HOURS * 3600 - cycle_elapsed)

                if wait_time > 0:
                    self._status = "waiting"
                    logger.info(
                        f"Cycle #{self._cycle_count} complete. "
                        f"Next cycle in {wait_time/60:.1f} minutes"
                    )
                    await self._interruptible_sleep(wait_time)

        except asyncio.CancelledError:
            logger.info("Main loop cancelled")
        except Exception as e:
            logger.error(f"Main loop error: {e}", exc_info=True)
            self._status = "error"

    async def _phase_full_refresh(self):
        """
        Full data refresh: Fetch 30 days of historical data for all assets.
        """
        self._status = "fetching_full_data"
        assets = self.asset_manager.available_assets

        logger.info(f"Phase 1: Full data refresh for {len(assets)} assets...")

        # Check which assets need fresh data
        assets_to_fetch = []
        for asset in assets:
            if not self.cache_manager.is_cache_valid(asset):
                assets_to_fetch.append(asset)

        if assets_to_fetch:
            logger.info(f"Fetching data for {len(assets_to_fetch)} assets (rest cached)")

            # Fetch in batches
            results = await self.data_fetcher.fetch_all_assets(
                assets=assets_to_fetch,
                amount_of_seconds=HISTORY_SECONDS,
                period=CANDLE_PERIOD,
                progress_callback=self._fetch_progress_callback,
            )

            # Save to cache
            for asset, candles in results.items():
                if candles:
                    self.cache_manager.save(asset, candles)
        else:
            logger.info("All assets have valid cached data")

        self._last_full_refresh = time.time()

    async def _phase_hourly_refresh(self):
        """
        Hourly refresh: Fetch last hour of data and merge with cache.
        """
        self._status = "refreshing_hourly"
        assets = self.asset_manager.available_assets

        logger.info(f"Phase 1b: Hourly data refresh for {len(assets)} assets...")

        # Fetch recent data and merge
        await self.signal_generator.refresh_and_merge(assets)

        # Also check for any assets that have expired cache
        for asset in assets:
            if not self.cache_manager.is_cache_valid(asset):
                logger.info(f"[{asset}] Cache expired, fetching full history...")
                candles = await self.data_fetcher.fetch_asset_history(asset)
                if candles:
                    self.cache_manager.save(asset, candles)

    async def _phase_generate_signals(self):
        """
        Generate signals for all assets.
        """
        self._status = "generating_signals"
        assets = self.asset_manager.available_assets

        logger.info(f"Phase 2: Generating signals for {len(assets)} assets...")

        signals = await self.signal_generator.generate_signals(assets)

        # Store current signals
        self._current_signals = [s.to_dict() for s in signals]

        # Add to history (keep last 1000)
        timestamp = time.time()
        for s in signals:
            self._signal_history.append({
                **s.to_dict(),
                "cycle": self._cycle_count,
                "generated_at": timestamp,
            })

        # Trim history
        if len(self._signal_history) > 1000:
            self._signal_history = self._signal_history[-1000:]

        # Print summary
        up_count = sum(1 for s in signals if s.direction == "UP")
        down_count = sum(1 for s in signals if s.direction == "DOWN")

        logger.info(f"{'='*60}")
        logger.info(f"SIGNAL SUMMARY — Cycle #{self._cycle_count}")
        logger.info(f"{'='*60}")
        logger.info(f"  Total Signals: {len(signals)}")
        logger.info(f"  🟢 UP:   {up_count}")
        logger.info(f"  🔴 DOWN: {down_count}")
        logger.info(f"{'='*60}")

        for s in sorted(signals, key=lambda x: x.asset):
            logger.info(f"  {s.emoji} {s.asset:20s} {s.direction:4s} ({s.confidence:.1f}%)")

        logger.info(f"{'='*60}")

    def _need_full_refresh(self) -> bool:
        """Check if a full data refresh is needed."""
        if self._last_full_refresh == 0:
            return True
        elapsed = time.time() - self._last_full_refresh
        return elapsed > FULL_REFRESH_INTERVAL_HOURS * 3600

    async def _interruptible_sleep(self, seconds: float):
        """Sleep that can be interrupted by stop()."""
        check_interval = 5  # Check every 5 seconds
        elapsed = 0.0

        while elapsed < seconds and self._running:
            sleep_time = min(check_interval, seconds - elapsed)
            await asyncio.sleep(sleep_time)
            elapsed += sleep_time

    def _fetch_progress_callback(self, asset: str, index: int, total: int, candles: int):
        """Callback for data fetching progress."""
        if index % 10 == 0 or index == total:
            logger.info(f"  Fetch progress: {index}/{total} ({candles} candles for {asset})")

    def get_status_dict(self) -> dict:
        """Get full status information."""
        cache_stats = self.cache_manager.get_cache_stats()
        asset_stats = self.asset_manager.get_stats()

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
        }
