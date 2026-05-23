"""
Signal Generator for Trading Bot Zai v1.

Orchestrates the full signal generation pipeline:
  1. Load/refresh cached historical data for each asset
  2. Run technical analysis (indicators)
  3. Run confluence strategy
  4. Run backtesting to validate signals
  5. Emit high-confidence signals only

Signals are represented as:
  {
      "asset": "EURUSD_otc",
      "direction": "UP" | "DOWN",
      "confidence": 97.5,
      "timestamp": 1700000000,
      "indicators": {...},
      "backtest": {...},
      "expires_at": 1700000060,  # Signal valid for 1 minute
  }
"""

import asyncio
import logging
import time
from typing import Optional

from bot.config import CANDLE_PERIOD, HISTORY_SECONDS, MIN_CONFIDENCE_PCT
from bot.cache_manager import CacheManager
from bot.data_fetcher import DataFetcher
from bot.strategy import ConfluenceStrategy
from bot.backtester import Backtester

logger = logging.getLogger("signal_generator")


class Signal:
    """Represents a single trading signal."""

    def __init__(
        self,
        asset: str,
        direction: str,  # "UP" or "DOWN"
        confidence: float,
        timestamp: float,
        strategy_details: dict,
        backtest_result: dict,
        expires_in: int = 60,  # Signal valid for 60 seconds
    ):
        self.asset = asset
        self.direction = direction
        self.confidence = confidence
        self.timestamp = timestamp
        self.strategy_details = strategy_details
        self.backtest_result = backtest_result
        self.expires_at = timestamp + expires_in
        self.created_at = time.time()

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def emoji(self) -> str:
        """Get the visual indicator: green circle for UP, red circle for DOWN."""
        if self.direction == "UP":
            return "🟢"
        elif self.direction == "DOWN":
            return "🔴"
        return "⚪"

    @property
    def direction_arrow(self) -> str:
        if self.direction == "UP":
            return "▲"
        elif self.direction == "DOWN":
            return "▼"
        return "—"

    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "direction": self.direction,
            "direction_emoji": self.emoji,
            "direction_arrow": self.direction_arrow,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
            "expires_at": self.expires_at,
            "is_expired": self.is_expired,
            "strategy": self.strategy_details,
            "backtest": self.backtest_result,
        }


class SignalGenerator:
    """
    Main signal generation orchestrator.

    Workflow per asset:
      1. Load cached data (or fetch fresh 30-day history)
      2. Merge any new data since last cache
      3. Run confluence strategy analysis
      4. If strategy produces a signal, run backtesting
      5. If backtest confirms high confidence, emit signal
    """

    def __init__(
        self,
        quotex_client,
        cache_manager: Optional[CacheManager] = None,
        data_fetcher: Optional[DataFetcher] = None,
        strategy: Optional[ConfluenceStrategy] = None,
        backtester: Optional[Backtester] = None,
    ):
        self.client = quotex_client
        self.cache = cache_manager or CacheManager()
        self.fetcher = data_fetcher or DataFetcher(quotex_client)
        self.strategy = strategy or ConfluenceStrategy(min_agreement=6)
        self.backtester = backtester or Backtester(strategy=self.strategy)

        # Current signals
        self._signals: dict[str, Signal] = {}
        self._last_generation_time: float = 0
        self._generation_count: int = 0
        self._backtest_cache: dict[str, dict] = {}

    async def generate_signals(
        self,
        assets: list[str],
        force_refresh: bool = False,
    ) -> list[Signal]:
        """
        Generate signals for all specified assets.

        Args:
            assets: List of asset symbols
            force_refresh: If True, skip cache and fetch fresh data

        Returns:
            List of Signal objects (only high-confidence signals)
        """
        signals = []
        self._generation_count += 1
        start_time = time.time()

        logger.info(f"Generating signals for {len(assets)} assets (cycle #{self._generation_count})")

        for asset in assets:
            try:
                signal = await self._generate_signal_for_asset(asset, force_refresh)
                if signal:
                    signals.append(signal)
                    self._signals[asset] = signal
            except Exception as e:
                logger.error(f"[{asset}] Signal generation error: {e}", exc_info=True)

        self._last_generation_time = time.time()
        elapsed = self._last_generation_time - start_time

        # Clean expired signals
        self._clean_expired_signals()

        logger.info(
            f"Signal generation complete: {len(signals)}/{len(assets)} signals "
            f"in {elapsed:.1f}s"
        )

        return signals

    async def _generate_signal_for_asset(
        self,
        asset: str,
        force_refresh: bool = False,
    ) -> Optional[Signal]:
        """
        Generate a signal for a single asset.
        Returns None if no high-confidence signal is found.
        """
        # Step 1: Load or fetch candle data
        candles = await self._get_candle_data(asset, force_refresh)
        if not candles or len(candles) < 200:
            logger.debug(f"[{asset}] Insufficient data ({len(candles) if candles else 0} candles)")
            return None

        # Step 2: Run strategy analysis
        analysis = self.strategy.analyze(candles)

        if not analysis.get("signal") or not analysis.get("direction"):
            logger.debug(f"[{asset}] No strategy signal (confidence: {analysis.get('confidence', 0):.1f}%)")
            return None

        direction = analysis["direction"]
        strategy_confidence = analysis["confidence"]

        # Step 3: Run backtesting (use cached result if recent)
        backtest_result = self._get_or_run_backtest(asset, candles)

        # Step 4: Calculate final confidence
        if backtest_result and backtest_result.get("total_trades", 0) >= 5:
            backtest_win_rate = backtest_result["win_rate"]

            # Direction-specific accuracy
            if direction == "UP" and backtest_result.get("up_total", 0) > 0:
                backtest_accuracy = (backtest_result.get("up_correct", 0) / backtest_result["up_total"]) * 100
            elif direction == "DOWN" and backtest_result.get("down_total", 0) > 0:
                backtest_accuracy = (backtest_result.get("down_correct", 0) / backtest_result["down_total"]) * 100
            else:
                backtest_accuracy = backtest_win_rate

            # Weighted combination: backtest gets 60%, strategy gets 40%
            final_confidence = strategy_confidence * 0.4 + backtest_accuracy * 0.6
        else:
            # Insufficient backtest data - rely solely on strategy but reduce confidence
            final_confidence = strategy_confidence * 0.6

        final_confidence = round(final_confidence, 2)

        # Step 5: Only emit signal if confidence meets threshold
        if final_confidence < MIN_CONFIDENCE_PCT:
            logger.info(
                f"[{asset}] Signal {direction} rejected: {final_confidence:.1f}% "
                f"< {MIN_CONFIDENCE_PCT}% threshold"
            )
            return None

        # Create signal
        signal = Signal(
            asset=asset,
            direction=direction,
            confidence=final_confidence,
            timestamp=time.time(),
            strategy_details={
                "up_votes": analysis.get("up_votes", 0),
                "down_votes": analysis.get("down_votes", 0),
                "neutral_votes": analysis.get("neutral_votes", 0),
                "layers": {
                    k: {"direction": v.get("direction"), "reason": v.get("reason", "")}
                    for k, v in analysis.get("layers", {}).items()
                },
                "patterns_detected": [
                    {"pattern": p["pattern"], "direction": p["direction"]}
                    for p in analysis.get("patterns_detected", [])
                ],
            },
            backtest_result=backtest_result or {},
        )

        logger.info(
            f"[{asset}] SIGNAL: {signal.emoji} {direction} "
            f"confidence={final_confidence:.1f}% "
            f"(strategy={strategy_confidence:.1f}%)"
        )

        return signal

    async def _get_candle_data(
        self,
        asset: str,
        force_refresh: bool = False,
    ) -> Optional[list]:
        """
        Get candle data for an asset, using cache when available.
        Fetches fresh data if cache is expired or force_refresh is True.
        """
        # Try loading from cache
        if not force_refresh:
            cached = self.cache.load(asset)
            if cached:
                return cached

        # Fetch fresh data
        logger.info(f"[{asset}] Fetching fresh historical data...")
        candles = await self.fetcher.fetch_asset_history(
            asset=asset,
            amount_of_seconds=HISTORY_SECONDS,
            period=CANDLE_PERIOD,
        )

        if candles:
            # Save to cache
            self.cache.save(asset, candles)
            return candles

        return None

    async def refresh_and_merge(self, assets: list[str]) -> dict[str, list]:
        """
        Fetch the most recent hour of data and merge with cache.
        This is called at the end of each 1-hour cycle.

        Args:
            assets: List of asset symbols

        Returns:
            Dict of {asset: merged_candles}
        """
        logger.info(f"Refreshing data for {len(assets)} assets (hourly merge)...")

        # Fetch recent 1-hour data
        recent_data = await self.fetcher.fetch_recent_data(assets)

        merged = {}
        for asset, recent_candles in recent_data.items():
            # Load existing cache
            existing = self.cache.load(asset) or []

            # Merge
            merged_candles = self.cache.merge_candles(existing, recent_candles)

            # Trim to 30 days
            merged_candles = self.cache.trim_to_history_depth(merged_candles)

            # Save back to cache
            self.cache.save(asset, merged_candles)
            merged[asset] = merged_candles

        logger.info(f"Data refresh complete: {len(merged)} assets updated")
        return merged

    def _get_or_run_backtest(self, asset: str, candles: list) -> Optional[dict]:
        """
        Get cached backtest result or run a new backtest.
        Backtest results are cached for the cycle duration.
        """
        now = time.time()

        if asset in self._backtest_cache:
            cached = self._backtest_cache[asset]
            if now - cached.get("computed_at", 0) < 3600:  # Cache for 1 hour
                return cached

        # Run backtest
        result = self.backtester.run(candles)
        result_dict = result.to_dict()
        result_dict["computed_at"] = now

        self._backtest_cache[asset] = result_dict
        return result_dict

    def _clean_expired_signals(self):
        """Remove expired signals from the current set."""
        expired = [k for k, v in self._signals.items() if v.is_expired]
        for k in expired:
            del self._signals[k]

    def get_current_signals(self) -> list[Signal]:
        """Get all current (non-expired) signals."""
        self._clean_expired_signals()
        return list(self._signals.values())

    def get_signals_dict(self) -> list[dict]:
        """Get all current signals as dicts (for API/Flask)."""
        return [s.to_dict() for s in self.get_current_signals()]

    @property
    def last_generation_time(self) -> float:
        return self._last_generation_time

    @property
    def generation_count(self) -> int:
        return self._generation_count
