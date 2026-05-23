"""
Quotex API Client Wrapper for Trading Bot Zai v1.

Combines the best of both repos:
  - pyquotex (full API + indicators + streaming)
  - quotex-historical-data (get_candles_deep for unlimited history)

Provides a clean async interface for:
  - Authentication & connection
  - Fetching all available instruments
  - Getting deep historical candle data (30 days, 1-min)
  - Getting recent candle updates for cache merging
"""

import asyncio
import json
import logging
import time
from typing import Optional

from bot.config import (
    QUOTEX_EMAIL, QUOTEX_PASSWORD, QUOTEX_HOST, QUOTEX_LANG,
    ACCOUNT_MODE, CANDLE_PERIOD, HISTORY_SECONDS,
    PROXY_HTTP, PROXY_HTTPS, SESSION_FILE,
)

logger = logging.getLogger("quotex_client")


class QuotexClient:
    """
    High-level async client for Quotex broker.
    Wraps the pyquotex library with deep-candle support.
    """

    def __init__(self):
        self.client = None
        self._connected = False
        self._proxies = None

        if PROXY_HTTPS:
            self._proxies = {"https": PROXY_HTTPS, "http": PROXY_HTTP or PROXY_HTTPS}

    async def connect(self) -> bool:
        """Connect to Quotex with full authentication flow."""
        try:
            from quotex.stable_api import Quotex
        except ImportError:
            # Fallback: use the bundled pyquotex from quotex-historical-data
            try:
                from pyquotex.stable_api import Quotex
            except ImportError:
                logger.error(
                    "Neither 'quotex' nor 'pyquotex' package found. "
                    "Install with: pip install pyquotex"
                )
                return False

        try:
            self.client = Quotex(
                email=QUOTEX_EMAIL,
                password=QUOTEX_PASSWORD,
                host=QUOTEX_HOST,
                lang=QUOTEX_LANG,
                asset_default="EURUSD_otc",
                period_default=CANDLE_PERIOD,
                proxies=self._proxies,
            )

            # Set account mode
            if ACCOUNT_MODE == "PRACTICE":
                self.client.set_account_mode("PRACTICE")
            else:
                self.client.set_account_mode("REAL")

            # Attempt connection
            check, reason = await self.client.connect()
            if check:
                self._connected = True
                logger.info(f"Connected to Quotex: {reason}")
                return True
            else:
                logger.error(f"Connection failed: {reason}")
                return False

        except Exception as e:
            logger.error(f"Connection error: {e}")
            return False

    async def disconnect(self):
        """Gracefully disconnect from Quotex."""
        if self.client and self._connected:
            try:
                await self.client.close()
            except Exception as e:
                logger.warning(f"Disconnect error: {e}")
            finally:
                self._connected = False
                logger.info("Disconnected from Quotex")

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def get_all_instruments(self) -> list:
        """
        Fetch all available instruments from the broker.
        Returns the raw instrument list from WebSocket.
        """
        if not self._connected:
            logger.error("Not connected. Call connect() first.")
            return []

        try:
            instruments = await self.client.get_instruments(timeout=30)
            logger.info(f"Received {len(instruments) if instruments else 0} instruments")
            return instruments or []
        except Exception as e:
            logger.error(f"Failed to get instruments: {e}")
            return []

    async def get_asset_names(self) -> list:
        """Get list of [symbol, display_name] for all assets."""
        if not self._connected:
            return []
        try:
            return self.client.get_all_asset_name()
        except Exception as e:
            logger.error(f"Failed to get asset names: {e}")
            return []

    async def get_asset_codes(self) -> dict:
        """Get {symbol: code} mapping for all assets."""
        if not self._connected:
            return {}
        try:
            return await self.client.get_all_assets()
        except Exception as e:
            logger.error(f"Failed to get asset codes: {e}")
            return {}

    async def get_available_assets(self) -> list:
        """
        Get all available and currently open asset symbols.
        Filters to include forex, OTC, commodities, crypto, and indices.
        Returns list of asset symbol strings.
        """
        from bot.config import ALL_TARGET_ASSETS

        all_names = await self.get_asset_names()
        if not all_names:
            logger.warning("Could not fetch asset names, using default list")
            return ALL_TARGET_ASSETS

        # all_names is [[symbol, display_name], ...]
        available = set()
        for item in all_names:
            if isinstance(item, (list, tuple)) and len(item) >= 1:
                available.add(item[0])
            elif isinstance(item, str):
                available.add(item)

        # Filter to our target assets that are available
        found = [a for a in ALL_TARGET_ASSETS if a in available]

        # Also add any OTC or forex-like assets we might have missed
        for sym in available:
            if sym not in found and (
                "_otc" in sym.lower()
                or any(fx in sym for fx in ["USD", "EUR", "GBP", "JPY", "AUD", "NZD", "CAD", "CHF"])
                or sym.startswith("XAU") or sym.startswith("XAG")
                or sym in ["BTCUSD", "ETHUSD"]
            ):
                found.append(sym)

        logger.info(f"Found {len(found)} tradeable assets from {len(available)} total")
        return found

    async def fetch_deep_candles(
        self,
        asset: str,
        amount_of_seconds: int = HISTORY_SECONDS,
        period: int = CANDLE_PERIOD,
        progress_callback=None,
    ) -> list:
        """
        Fetch deep historical candle data using get_candles_deep().
        This can fetch unlimited candles (30+ days of 1-min data).

        Returns list of candle dicts: [{time, open, close, high, low, ticks}, ...]
        """
        if not self._connected:
            logger.error(f"Cannot fetch candles for {asset}: not connected")
            return []

        try:
            # Try get_candles_deep first (from quotex-historical-data)
            if hasattr(self.client, 'get_candles_deep'):
                candles = await self.client.get_candles_deep(
                    asset=asset,
                    amount_of_seconds=amount_of_seconds,
                    period=period,
                    timeout=30,
                    progress_callback=progress_callback,
                )
            else:
                # Fallback to get_historical_candles (from pyquotex)
                candles = await self.client.get_historical_candles(
                    asset=asset,
                    amount_of_seconds=amount_of_seconds,
                    period=period,
                    timeout=30,
                )

            if candles:
                logger.info(f"Fetched {len(candles)} candles for {asset}")
            else:
                logger.warning(f"No candles returned for {asset}")

            return candles or []

        except Exception as e:
            logger.error(f"Error fetching candles for {asset}: {e}")
            return []

    async def fetch_recent_candles(
        self,
        asset: str,
        offset: int = 3600,
        period: int = CANDLE_PERIOD,
    ) -> list:
        """
        Fetch the most recent hour of candle data for cache merging.
        Uses the standard get_candles() with a 1-hour offset.

        Returns list of candle dicts.
        """
        if not self._connected:
            return []

        try:
            end_time = time.time()
            candles = await self.client.get_candles(
                asset=asset,
                end_from_time=end_time,
                offset=offset,
                period=period,
                timeout=15,
            )
            return candles or []

        except Exception as e:
            logger.error(f"Error fetching recent candles for {asset}: {e}")
            return []

    async def get_payout(self, asset: str, timeframe: int = 60) -> float:
        """Get payout percentage for an asset."""
        if not self._connected:
            return 0.0
        try:
            result = self.client.get_payout_by_asset(asset, timeframe)
            if isinstance(result, dict):
                return float(result.get("turbo", 0))
            return float(result) if result else 0.0
        except Exception:
            return 0.0
