"""
Cache Manager for Trading Bot Zai v1.

Implements a 1-hour caching system for historical candle data:
  - Saves fetched data to disk with timestamps
  - Loads cached data on startup
  - Merges new hourly data with cached data
  - Automatically expires stale cache entries
  - Handles gap filling between cached and new data
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

from bot.config import DATA_CACHE_DIR, CACHE_DURATION_SECONDS

logger = logging.getLogger("cache_manager")


class CacheManager:
    """
    Manages 1-hour candle data cache with gap-filling merge logic.
    """

    def __init__(self, cache_dir: Path = DATA_CACHE_DIR):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: dict[str, dict] = {}

    def _cache_path(self, asset: str) -> Path:
        """Get the cache file path for an asset."""
        safe_name = asset.replace("/", "_").replace("\\", "_")
        return self.cache_dir / f"{safe_name}_1m.json"

    def _meta_path(self, asset: str) -> Path:
        """Get the metadata file path for an asset."""
        safe_name = asset.replace("/", "_").replace("\\", "_")
        return self.cache_dir / f"{safe_name}_1m_meta.json"

    def save(
        self,
        asset: str,
        candles: list,
        metadata: Optional[dict] = None,
    ) -> bool:
        """
        Save candle data and metadata to cache.

        Args:
            asset: Asset symbol
            candles: List of candle dicts
            metadata: Optional dict with extra info (fetch_time, etc.)

        Returns:
            True if saved successfully
        """
        try:
            now = time.time()

            # Save candle data
            cache_data = {
                "asset": asset,
                "candles": candles,
                "saved_at": now,
                "candle_count": len(candles),
            }

            with open(self._cache_path(asset), "w") as f:
                json.dump(cache_data, f)

            # Save metadata
            meta = metadata or {}
            meta.update({
                "saved_at": now,
                "expires_at": now + CACHE_DURATION_SECONDS,
                "candle_count": len(candles),
                "oldest_time": candles[0]["time"] if candles else None,
                "newest_time": candles[-1]["time"] if candles else None,
            })

            with open(self._meta_path(asset), "w") as f:
                json.dump(meta, f)

            # Update memory cache
            self._memory_cache[asset] = cache_data

            logger.info(f"[{asset}] Cached {len(candles)} candles (expires in {CACHE_DURATION_SECONDS}s)")
            return True

        except Exception as e:
            logger.error(f"[{asset}] Cache save error: {e}")
            return False

    def load(self, asset: str) -> Optional[list]:
        """
        Load candle data from cache.

        Args:
            asset: Asset symbol

        Returns:
            List of candle dicts if valid cache exists, None otherwise
        """
        # Check memory cache first
        if asset in self._memory_cache:
            mem_data = self._memory_cache[asset]
            if not self._is_expired(mem_data.get("saved_at", 0)):
                return mem_data["candles"]

        # Check disk cache
        cache_path = self._cache_path(asset)
        if not cache_path.exists():
            return None

        try:
            with open(cache_path, "r") as f:
                data = json.load(f)

            saved_at = data.get("saved_at", 0)

            if self._is_expired(saved_at):
                logger.info(f"[{asset}] Cache expired (saved {time.time() - saved_at:.0f}s ago)")
                return None

            candles = data.get("candles", [])
            if candles:
                # Update memory cache
                self._memory_cache[asset] = data
                logger.info(f"[{asset}] Loaded {len(candles)} candles from cache")
                return candles

            return None

        except Exception as e:
            logger.error(f"[{asset}] Cache load error: {e}")
            return None

    def load_meta(self, asset: str) -> Optional[dict]:
        """Load metadata for an asset's cache."""
        meta_path = self._meta_path(asset)
        if not meta_path.exists():
            return None

        try:
            with open(meta_path, "r") as f:
                return json.load(f)
        except Exception:
            return None

    def merge_candles(
        self,
        existing: list,
        new: list,
    ) -> list:
        """
        Merge existing cached candles with newly fetched candles.

        Strategy:
          1. Build a dict keyed by candle time for deduplication
          2. Add all existing candles
          3. Add/overwrite with new candles (newer data takes priority)
          4. Sort by time
          5. Return merged list

        This fills gaps between cached data and the latest data,
        ensuring no duplicates and chronological order.

        Args:
            existing: Previously cached candle list
            new: Newly fetched candle list

        Returns:
            Merged, deduplicated, sorted candle list
        """
        if not existing:
            return sorted(new, key=lambda c: c.get("time", 0))
        if not new:
            return existing

        # Build dict by time for O(1) dedup
        merged = {}

        # Add existing candles
        for candle in existing:
            t = candle.get("time")
            if t is not None:
                merged[t] = candle

        # Add/overwrite with new candles (newer data is more accurate)
        for candle in new:
            t = candle.get("time")
            if t is not None:
                merged[t] = candle

        # Sort by time
        result = sorted(merged.values(), key=lambda c: c.get("time", 0))

        logger.info(
            f"Merged candles: {len(existing)} existing + {len(new)} new = {len(result)} merged "
            f"(filled {len(result) - len(existing) - len(new) + len([t for t in set(c.get('time') for c in new) if t in set(c.get('time') for c in existing)])} gaps)"
        )

        return result

    def trim_to_history_depth(
        self,
        candles: list,
        history_seconds: int = 30 * 86400,
    ) -> list:
        """
        Trim candles to only keep the most recent `history_seconds` of data.
        Ensures we always analyze exactly 30 days (or configured depth).

        Args:
            candles: Full candle list
            history_seconds: Seconds of history to keep

        Returns:
            Trimmed candle list
        """
        if not candles:
            return candles

        newest_time = candles[-1].get("time", 0)
        cutoff_time = newest_time - history_seconds

        trimmed = [c for c in candles if c.get("time", 0) >= cutoff_time]

        if len(trimmed) < len(candles):
            logger.info(
                f"Trimmed candles: {len(candles)} -> {len(trimmed)} "
                f"(kept last {history_seconds / 86400:.0f} days)"
            )

        return trimmed

    def _is_expired(self, saved_at: float) -> bool:
        """Check if a cache entry has expired."""
        if saved_at <= 0:
            return True
        return (time.time() - saved_at) > CACHE_DURATION_SECONDS

    def is_cache_valid(self, asset: str) -> bool:
        """Check if a valid (non-expired) cache exists for an asset."""
        candles = self.load(asset)
        return candles is not None

    def clear(self, asset: Optional[str] = None):
        """Clear cache for a specific asset or all assets."""
        if asset:
            paths = [self._cache_path(asset), self._meta_path(asset)]
            for p in paths:
                if p.exists():
                    p.unlink()
            self._memory_cache.pop(asset, None)
            logger.info(f"[{asset}] Cache cleared")
        else:
            for p in self.cache_dir.glob("*.json"):
                p.unlink()
            self._memory_cache.clear()
            logger.info("All caches cleared")

    def get_cache_stats(self) -> dict:
        """Get statistics about the cache."""
        stats = {
            "total_assets": 0,
            "valid_caches": 0,
            "expired_caches": 0,
            "total_candles": 0,
        }

        for meta_file in self.cache_dir.glob("*_meta.json"):
            stats["total_assets"] += 1
            try:
                with open(meta_file, "r") as f:
                    meta = json.load(f)
                if self._is_expired(meta.get("saved_at", 0)):
                    stats["expired_caches"] += 1
                else:
                    stats["valid_caches"] += 1
                    stats["total_candles"] += meta.get("candle_count", 0)
            except Exception:
                stats["expired_caches"] += 1

        return stats
