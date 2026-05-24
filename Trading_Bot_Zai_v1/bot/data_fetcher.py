"""
Historical Data Fetcher for Trading Bot Zai v1.

Handles fetching 30 days of 1-minute candle data for all asset pairs,
with rate limiting, retry logic, and progress tracking.
"""

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Callable, Optional

from bot.config import DATA_CACHE_DIR, CANDLE_PERIOD, HISTORY_SECONDS

logger = logging.getLogger("data_fetcher")


class DataFetcher:
    """
    Fetches historical candle data for all assets.
    Handles rate limiting, retries, and parallel fetching.
    """

    def __init__(self, quotex_client, max_concurrent: int = 3):
        self.client = quotex_client
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._progress: dict[str, dict] = {}

    async def fetch_asset_history(
        self,
        asset: str,
        amount_of_seconds: int = HISTORY_SECONDS,
        period: int = CANDLE_PERIOD,
        retries: int = 3,
    ) -> list:
        """
        Fetch full historical data for a single asset with retry logic.

        Args:
            asset: Asset symbol (e.g. "EURUSD_otc")
            amount_of_seconds: How far back to fetch (default 30 days)
            period: Candle period in seconds (default 60 = 1 min)
            retries: Number of retry attempts

        Returns:
            List of candle dicts sorted by time
        """
        async with self._semaphore:
            self._progress[asset] = {"status": "fetching", "attempt": 0, "candles": 0}

            for attempt in range(1, retries + 1):
                try:
                    self._progress[asset]["attempt"] = attempt

                    def progress_cb(fetched_sec, total_sec, count, worker_label=""):
                        self._progress[asset]["candles"] = count

                    candles = await self.client.fetch_deep_candles(
                        asset=asset,
                        amount_of_seconds=amount_of_seconds,
                        period=period,
                        progress_callback=progress_cb,
                    )

                    if candles and len(candles) > 0:
                        # Sort by time
                        candles.sort(key=lambda c: c.get("time", 0))
                        self._progress[asset]["status"] = "done"
                        self._progress[asset]["candles"] = len(candles)
                        logger.info(f"[{asset}] Fetched {len(candles)} candles (attempt {attempt})")
                        return candles
                    else:
                        logger.warning(f"[{asset}] No candles on attempt {attempt}")

                except Exception as e:
                    logger.warning(f"[{asset}] Fetch error attempt {attempt}: {e}")

                # Exponential backoff between retries
                if attempt < retries:
                    wait = 2 ** attempt
                    logger.info(f"[{asset}] Retrying in {wait}s...")
                    await asyncio.sleep(wait)

            self._progress[asset]["status"] = "failed"
            logger.error(f"[{asset}] All {retries} fetch attempts failed")
            return []

    async def fetch_all_assets(
        self,
        assets: list[str],
        amount_of_seconds: int = HISTORY_SECONDS,
        period: int = CANDLE_PERIOD,
        progress_callback: Optional[Callable] = None,
    ) -> dict[str, list]:
        """
        Fetch historical data for all assets in parallel (with rate limiting).

        Args:
            assets: List of asset symbols
            amount_of_seconds: History depth
            period: Candle period
            progress_callback: Optional callback(asset, index, total, candles_count)

        Returns:
            Dict mapping asset symbol to candle list
        """
        results = {}
        total = len(assets)

        logger.info(f"Starting historical data fetch for {total} assets...")

        # Process in batches to avoid overwhelming the API
        batch_size = self.max_concurrent
        for i in range(0, total, batch_size):
            batch = assets[i:i + batch_size]

            tasks = []
            for asset in batch:
                tasks.append(self.fetch_asset_history(asset, amount_of_seconds, period))

            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for asset, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    logger.error(f"[{asset}] Exception: {result}")
                    results[asset] = []
                else:
                    results[asset] = result

                if progress_callback:
                    idx = assets.index(asset) + 1
                    progress_callback(asset, idx, total, len(results[asset]))

            # Small delay between batches to be respectful
            if i + batch_size < total:
                await asyncio.sleep(1)

        successful = sum(1 for v in results.values() if v)
        logger.info(
            f"Historical fetch complete: {successful}/{total} assets with data"
        )

        return results

    async def fetch_recent_data(
        self,
        assets: list[str],
        offset: int = 3600,
        period: int = CANDLE_PERIOD,
    ) -> dict[str, list]:
        """
        Fetch the most recent hour of candle data for cache merging.

        Args:
            assets: List of asset symbols
            offset: Seconds of recent data (default 3600 = 1 hour)
            period: Candle period

        Returns:
            Dict mapping asset symbol to recent candle list
        """
        results = {}
        batch_size = self.max_concurrent

        for i in range(0, len(assets), batch_size):
            batch = assets[i:i + batch_size]

            tasks = []
            for asset in batch:
                tasks.append(self.client.fetch_recent_candles(asset, offset, period))

            batch_results = await asyncio.gather(*tasks, return_exceptions=True)

            for asset, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    results[asset] = []
                elif result:
                    results[asset] = result
                else:
                    results[asset] = []

            await asyncio.sleep(0.5)

        return results

    def get_progress(self) -> dict:
        """Get current fetch progress for all assets."""
        return dict(self._progress)
