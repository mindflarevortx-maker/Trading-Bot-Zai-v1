"""
Historical Data Fetcher for Trading Bot Zai v1.2.

Handles fetching 30 days of 1-minute candle data for all asset pairs,
with rate limiting, retry logic, and progress tracking.

Key fix: progress_callback now takes 4 args (fetched_sec, total_sec, count, label)
matching pyquotex's get_historical_candles signature.
"""

import asyncio
import logging
import time
from typing import Callable, Optional

from bot.config import (
    DATA_CACHE_DIR, CANDLE_PERIOD, HISTORY_SECONDS,
    FETCH_MAX_CONCURRENT, FETCH_RETRIES, FETCH_BATCH_TIMEOUT,
)

logger = logging.getLogger("data_fetcher")


class DataFetcher:
    """Fetches historical candle data for all assets with rate limiting and retries."""

    def __init__(self, quotex_client, max_concurrent: int = FETCH_MAX_CONCURRENT):
        self.client = quotex_client
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._progress: dict[str, dict] = {}

    async def fetch_asset_history(
        self,
        asset: str,
        amount_of_seconds: int = HISTORY_SECONDS,
        period: int = CANDLE_PERIOD,
        retries: int = FETCH_RETRIES,
    ) -> list:
        """
        Fetch full historical data for a single asset with retry logic.
        Returns list of candle dicts sorted by time.
        """
        async with self._semaphore:
            self._progress[asset] = {"status": "fetching", "attempt": 0, "candles": 0}

            for attempt in range(1, retries + 1):
                try:
                    self._progress[asset]["attempt"] = attempt

                    # IMPORTANT: pyquotex progress_callback takes 4 args:
                    # (fetched_seconds, total_seconds, candle_count, worker_label)
                    def progress_cb(fetched_sec, total_sec, count, label=""):
                        self._progress[asset]["candles"] = count

                    candles = await self.client.fetch_historical_candles(
                        asset=asset,
                        amount_of_seconds=amount_of_seconds,
                        period=period,
                        progress_callback=progress_cb,
                    )

                    if candles and len(candles) > 0:
                        candles.sort(key=lambda c: c.get("time", 0))
                        self._progress[asset]["status"] = "done"
                        self._progress[asset]["candles"] = len(candles)
                        logger.info(f"[{asset}] Fetched {len(candles)} candles (attempt {attempt})")
                        return candles
                    else:
                        logger.warning(f"[{asset}] No candles on attempt {attempt}")

                except Exception as e:
                    logger.warning(f"[{asset}] Fetch error attempt {attempt}: {e}")

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
        """Fetch historical data for all assets in parallel batches."""
        results = {}
        total = len(assets)
        logger.info(f"Starting historical data fetch for {total} assets...")

        batch_size = self.max_concurrent
        for i in range(0, total, batch_size):
            batch = assets[i:i + batch_size]
            tasks = [self.fetch_asset_history(a, amount_of_seconds, period) for a in batch]
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

            if i + batch_size < total:
                await asyncio.sleep(1)

        successful = sum(1 for v in results.values() if v)
        logger.info(f"Historical fetch complete: {successful}/{total} assets with data")
        return results

    async def fetch_recent_data(
        self,
        assets: list[str],
        offset: int = 3600,
        period: int = CANDLE_PERIOD,
    ) -> dict[str, list]:
        """Fetch the most recent hour of candle data for cache gap-fill."""
        results = {}
        batch_size = self.max_concurrent

        for i in range(0, len(assets), batch_size):
            batch = assets[i:i + batch_size]
            tasks = [self.client.fetch_recent_candles(a, offset, period) for a in batch]
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
        return dict(self._progress)
