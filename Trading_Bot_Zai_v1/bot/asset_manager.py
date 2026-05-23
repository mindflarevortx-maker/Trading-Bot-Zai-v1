"""
Asset Manager for Trading Bot Zai v1.

Manages the full list of 100+ asset pairs including:
  - Major & Minor Forex pairs
  - OTC (Over-The-Counter) pairs
  - Commodities (Gold, Silver, Oil, Gas)
  - Crypto pairs
  - Stock Indices

Provides categorization, filtering, and availability checking.
"""

import logging
from typing import Optional

from bot.config import (
    FOREX_PAIRS, OTC_PAIRS, COMMODITY_PAIRS,
    CRYPTO_PAIRS, INDEX_PAIRS, ALL_TARGET_ASSETS,
)

logger = logging.getLogger("asset_manager")


class AssetManager:
    """
    Manages the complete universe of tradeable asset pairs.
    Dynamically filters by broker availability at runtime.
    """

    # Category definitions
    CATEGORIES = {
        "forex": FOREX_PAIRS,
        "otc": OTC_PAIRS,
        "commodity": COMMODITY_PAIRS,
        "crypto": CRYPTO_PAIRS,
        "index": INDEX_PAIRS,
    }

    def __init__(self):
        self._available_assets: list[str] = []
        self._unavailable_assets: list[str] = []
        self._asset_categories: dict[str, str] = {}
        self._initialized = False

        # Build category lookup
        for cat, pairs in self.CATEGORIES.items():
            for pair in pairs:
                self._asset_categories[pair] = cat

    def get_all_target_assets(self) -> list[str]:
        """Return the complete list of target asset symbols."""
        return list(ALL_TARGET_ASSETS)

    def get_assets_by_category(self, category: str) -> list[str]:
        """Get all assets in a specific category."""
        return self.CATEGORIES.get(category, [])

    def get_category(self, asset: str) -> str:
        """Get the category of an asset."""
        return self._asset_categories.get(asset, "unknown")

    def is_otc(self, asset: str) -> bool:
        """Check if an asset is an OTC pair."""
        return asset.endswith("_otc")

    def get_base_symbol(self, asset: str) -> str:
        """Get the base symbol (without _otc suffix)."""
        return asset.replace("_otc", "")

    async def initialize(self, quotex_client) -> bool:
        """
        Initialize asset list by checking broker availability.
        Cross-references our target list with what's actually available.
        """
        try:
            broker_assets = await quotex_client.get_available_assets()

            if not broker_assets:
                logger.warning("Could not fetch broker assets; using full target list")
                self._available_assets = list(ALL_TARGET_ASSETS)
            else:
                broker_set = set(broker_assets)
                self._available_assets = [a for a in ALL_TARGET_ASSETS if a in broker_set]

                # Add any broker assets we didn't have in our list
                for a in broker_assets:
                    if a not in self._asset_categories:
                        # Categorize dynamically
                        if a.endswith("_otc"):
                            self._asset_categories[a] = "otc"
                        elif any(a.startswith(prefix) for prefix in ["XAU", "XAG", "XPT", "XPD"]):
                            self._asset_categories[a] = "commodity"
                        elif a in ["BTCUSD", "ETHUSD", "LTCUSD", "XRPUSD", "ADAUSD"]:
                            self._asset_categories[a] = "crypto"
                        elif any(idx in a for idx in ["US100", "US30", "SPX", "UK100", "DAX", "CAC", "NIKKEI", "HSI", "AUS"]):
                            self._asset_categories[a] = "index"
                        else:
                            self._asset_categories[a] = "forex"

                        if a not in self._available_assets:
                            self._available_assets.append(a)

                # Track unavailable
                self._unavailable_assets = [
                    a for a in ALL_TARGET_ASSETS if a not in broker_set
                ]

            self._initialized = True
            logger.info(
                f"Asset manager initialized: {len(self._available_assets)} available, "
                f"{len(self._unavailable_assets)} unavailable"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to initialize asset manager: {e}")
            self._available_assets = list(ALL_TARGET_ASSETS)
            self._initialized = True
            return False

    @property
    def available_assets(self) -> list[str]:
        """All currently available asset symbols."""
        return self._available_assets

    @property
    def unavailable_assets(self) -> list[str]:
        """Assets in our target list that are not available on broker."""
        return self._unavailable_assets

    def get_stats(self) -> dict:
        """Get statistics about managed assets."""
        cat_counts = {}
        for asset in self._available_assets:
            cat = self._asset_categories.get(asset, "unknown")
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

        return {
            "total_available": len(self._available_assets),
            "total_unavailable": len(self._unavailable_assets),
            "by_category": cat_counts,
        }
