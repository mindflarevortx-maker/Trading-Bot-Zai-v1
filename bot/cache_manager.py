"""
Cache Manager for Trading Bot Zai v1.2.

Implements a PERSISTENT caching system for historical candle data:
  - Data never expires once fetched (CACHE_DURATION = 0)
  - On hourly refresh, only the GAP between cached and live is fetched
  - Merges new data with cached data (no duplicates)
  - Trims to 30-day window to prevent unbounded growth
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional

from bot.config import DATA_CACHE_DIR, HISTORY_SECONDS

logger = logging.getLogger("cache_manager")


class CacheManager:
    """
    Persistent cache with gap-filling merge logic.
    Data is saved to disk and never expires — only gap-filled on refresh.
    """

    def __init__(self, cache_dir: Path = DATA_CACHE_DIR):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: dict[str, dict] = {}

    def _cache_path(self, asset: str) -> Path:
        safe_name = asset.replace("/", "_").replace("\\", "_")
        return self.cache_dir / f"{safe_name}_1m.json"

    def _meta_path(self, asset: str) -> Path:
        safe_name = asset.replace("/", "_").replace("\\", "_")
        return self.cache_dir / f"{safe_name}_1m_meta.json"

    def save(self, asset: str, candles: list, metadata: Optional[dict] = None) -> bool:
        """Save candle data and metadata to cache (persistent)."""
        try:
            now = time.time()
            cache_data = {
                "asset": asset,
                "candles": candles,
                "saved_at": now,
                "candle_count": len(candles),
            }
            with open(self._cache_path(asset), "w") as f:
                json.dump(cache_data, f)

            meta = metadata or {}
            meta.update({
                "saved_at": now,
                "expires_at": 0,  # Never expires
                "candle_count": len(candles),
                "oldest_time": candles[0]["time"] if candles else None,
                "newest_time": candles[-1]["time"] if candles else None,
            })
            with open(self._meta_path(asset), "w") as f:
                json.dump(meta, f)

            self._memory_cache[asset] = cache_data
            logger.info(f"[{asset}] Cached {len(candles)} candles (persistent)")
            return True
        except Exception as e:
            logger.error(f"[{asset}] Cache save error: {e}")
            return False

    def load(self, asset: str) -> Optional[list]:
        """Load candle data from cache. Returns None only if no cache exists."""
        # Check memory cache first
        if asset in self._memory_cache:
            return self._memory_cache[asset].get("candles")

        # Check disk cache
        cache_path = self._cache_path(asset)
        if not cache_path.exists():
            return None

        try:
            with open(cache_path, "r") as f:
                data = json.load(f)
            candles = data.get("candles", [])
            if candles:
                self._memory_cache[asset] = data
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

    def get_newest_candle_time(self, asset: str) -> Optional[float]:
        """Get the timestamp of the newest cached candle for an asset."""
        candles = self.load(asset)
        if candles:
            return candles[-1].get("time", 0)
        return None

    def has_data(self, asset: str) -> bool:
        """Check if cache exists for an asset (regardless of age)."""
        return self.load(asset) is not None

    def is_cache_valid(self, asset: str) -> bool:
        """Check if valid cache exists (always True if data exists, since persistent)."""
        return self.has_data(asset)

    def merge_candles(self, existing: list, new: list) -> list:
        """
        Merge existing cached candles with newly fetched candles.
        Deduplicates by time, sorts chronologically, and trims to 30 days.
        """
        if not existing:
            return sorted(new, key=lambda c: c.get("time", 0))
        if not new:
            return existing

        merged = {}
        for candle in existing:
            t = candle.get("time")
            if t is not None:
                merged[t] = candle
        for candle in new:
            t = candle.get("time")
            if t is not None:
                merged[t] = candle

        result = sorted(merged.values(), key=lambda c: c.get("time", 0))
        logger.info(
            f"Merged: {len(existing)} existing + {len(new)} new = {len(result)} total"
        )
        return result

    def trim_to_history_depth(self, candles: list, history_seconds: int = None) -> list:
        """Trim candles to keep only the most recent N seconds of data."""
        if not candles:
            return candles
        if history_seconds is None:
            history_seconds = HISTORY_SECONDS

        newest_time = candles[-1].get("time", 0)
        cutoff_time = newest_time - history_seconds
        trimmed = [c for c in candles if c.get("time", 0) >= cutoff_time]

        if len(trimmed) < len(candles):
            logger.info(f"Trimmed: {len(candles)} → {len(trimmed)} (kept last {history_seconds / 86400:.0f} days)")
        return trimmed

    def clear(self, asset: Optional[str] = None):
        """Clear cache for a specific asset or all assets."""
        if asset:
            for p in [self._cache_path(asset), self._meta_path(asset)]:
                if p.exists():
                    p.unlink()
            self._memory_cache.pop(asset, None)
        else:
            for p in self.cache_dir.glob("*.json"):
                p.unlink()
            self._memory_cache.clear()

    def get_cache_stats(self) -> dict:
        """Get statistics about the cache."""
        stats = {"total_assets": 0, "valid_caches": 0, "expired_caches": 0, "total_candles": 0}
        for meta_file in self.cache_dir.glob("*_meta.json"):
            stats["total_assets"] += 1
            try:
                with open(meta_file, "r") as f:
                    meta = json.load(f)
                stats["valid_caches"] += 1
                stats["total_candles"] += meta.get("candle_count", 0)
            except Exception:
                stats["expired_caches"] += 1
        return stats
