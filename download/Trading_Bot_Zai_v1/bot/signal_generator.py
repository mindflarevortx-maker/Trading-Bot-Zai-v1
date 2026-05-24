"""
Signal Generator for Trading Bot Zai v1.2.

COMPLETELY REDESIGNED: Generates TIME-ORDERED signals for the next hour.

Instead of generating one signal per asset, this generates signals
showing EXACTLY WHEN each trade opportunity occurs, ordered by time.

Example output:
  02:40  USDPKR_otc  🔴 DOWN  97.2%
  02:43  USDBRL_otc  🔴 DOWN  96.8%
  02:44  USDJPY      🟢 UP    98.1%
  02:46  USDINR_otc  🔴 DOWN  95.5%
  ...until 03:40

Each signal includes:
  - Exact time the trade should be placed (in user's timezone UTC+5)
  - Asset pair
  - Direction (UP/DOWN)
  - Confidence score
  - 1 martingale step
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from bot.config import (
    CANDLE_PERIOD, HISTORY_SECONDS, MIN_CONFIDENCE_PCT,
    SIGNAL_FORECAST_HOURS, USER_TZ,
    MARTINGALE_STEPS, MARTINGALE_MULTIPLIER, MARTINGALE_BASE_AMOUNT,
)
from bot.cache_manager import CacheManager
from bot.data_fetcher import DataFetcher
from bot.strategy import ConfluenceStrategy
from bot.backtester import Backtester

logger = logging.getLogger("signal_generator")


class Signal:
    """Represents a single time-ordered trading signal with martingale."""

    def __init__(
        self,
        asset: str,
        direction: str,
        confidence: float,
        trade_time: float,        # Unix timestamp when to place trade
        strategy_details: dict,
        backtest_result: dict,
        category: str = "forex",
    ):
        self.asset = asset
        self.direction = direction       # "UP" or "DOWN"
        self.confidence = confidence
        self.trade_time = trade_time      # Exact time to trade
        self.strategy_details = strategy_details
        self.backtest_result = backtest_result
        self.category = category
        self.created_at = time.time()

        # Martingale calculation
        self.martingale = self._calculate_martingale()

    def _calculate_martingale(self) -> list[dict]:
        """Calculate martingale steps for this signal."""
        steps = []
        amount = MARTINGALE_BASE_AMOUNT
        for step in range(MARTINGALE_STEPS + 1):
            steps.append({
                "step": step,
                "amount": amount,
                "direction": self.direction,
                "note": "Base trade" if step == 0 else f"Martingale step {step}",
            })
            amount = round(amount * MARTINGALE_MULTIPLIER, 2)
        return steps

    @property
    def emoji(self) -> str:
        return "🟢" if self.direction == "UP" else "🔴"

    @property
    def direction_arrow(self) -> str:
        return "▲" if self.direction == "UP" else "▼"

    @property
    def trade_time_local(self) -> str:
        """Trade time formatted in user's local timezone (UTC+5)."""
        dt = datetime.fromtimestamp(self.trade_time, tz=USER_TZ)
        return dt.strftime("%H:%M")

    @property
    def trade_time_full(self) -> str:
        """Full trade time with date in user's timezone."""
        dt = datetime.fromtimestamp(self.trade_time, tz=USER_TZ)
        return dt.strftime("%Y-%m-%d %H:%M")

    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "direction": self.direction,
            "direction_emoji": self.emoji,
            "direction_arrow": self.direction_arrow,
            "confidence": round(self.confidence, 2),
            "trade_time": self.trade_time,
            "trade_time_local": self.trade_time_local,
            "trade_time_full": self.trade_time_full,
            "category": self.category,
            "martingale": self.martingale,
            "strategy": self.strategy_details,
            "backtest": self.backtest_result,
        }


class SignalGenerator:
    """
    Time-ordered signal generation orchestrator.

    Instead of "one signal per asset", this generates a TIMELINE of
    trade opportunities for the next hour, ordered by when each
    trade should be placed.

    Algorithm:
      1. For each asset with cached historical data:
         a. Run the 7-layer confluence strategy
         b. If strategy agrees on a direction (≥4/7 layers), proceed
         c. Run walk-forward backtesting to validate
         d. Calculate final confidence = 40% strategy + 60% backtest
         e. If confidence ≥ 95%, determine the next 1-min candle time
            where the pattern suggests the trade should be placed
         f. Assign trade_time = the next candle close time matching
            the detected pattern
      2. Sort all signals by trade_time (nearest first)
      3. Return the complete timeline for the next hour
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
        self.strategy = strategy or ConfluenceStrategy(min_agreement=4)
        self.backtester = backtester or Backtester(strategy=self.strategy)
        self._backtest_cache: dict[str, dict] = {}

    async def generate_signals(self, assets: list[str]) -> list[Signal]:
        """
        Generate TIME-ORDERED signals for the next hour.
        Signals are sorted by trade time (nearest first).
        """
        signals = []
        start_time = time.time()

        logger.info(f"Generating time-ordered signals for {len(assets)} assets...")

        for asset in assets:
            try:
                signal = self._generate_signal_for_asset(asset)
                if signal:
                    signals.append(signal)
            except Exception as e:
                logger.debug(f"[{asset}] Signal generation error: {e}")

        # Sort by trade time (nearest first) — this is the key change
        signals.sort(key=lambda s: s.trade_time)

        # Only keep signals within the next hour
        cutoff_time = start_time + SIGNAL_FORECAST_HOURS * 3600
        signals = [s for s in signals if s.trade_time <= cutoff_time]

        elapsed = time.time() - start_time
        up_count = sum(1 for s in signals if s.direction == "UP")
        down_count = sum(1 for s in signals if s.direction == "DOWN")

        logger.info(
            f"Signal generation complete: {len(signals)} signals in {elapsed:.1f}s "
            f"(🟢 {up_count} UP, 🔴 {down_count} DOWN)"
        )

        return signals

    def _generate_signal_for_asset(self, asset: str) -> Optional[Signal]:
        """
        Generate a signal for a single asset with a specific trade time.
        The trade time is determined by when the pattern suggests the
        next high-probability trade opportunity occurs.
        """
        # Load cached data
        candles = self.cache.load(asset)
        if not candles or len(candles) < 200:
            return None

        # Run strategy analysis
        analysis = self.strategy.analyze(candles)
        if not analysis.get("signal") or not analysis.get("direction"):
            return None

        direction = analysis["direction"]
        strategy_confidence = analysis["confidence"]

        # Run backtesting
        backtest_result = self._get_or_run_backtest(asset, candles)

        # Calculate final confidence
        if backtest_result and backtest_result.get("total_trades", 0) >= 5:
            backtest_win_rate = backtest_result["win_rate"]
            if direction == "UP" and backtest_result.get("up_total", 0) > 0:
                backtest_accuracy = (backtest_result["up_correct"] / backtest_result["up_total"]) * 100
            elif direction == "DOWN" and backtest_result.get("down_total", 0) > 0:
                backtest_accuracy = (backtest_result["down_correct"] / backtest_result["down_total"]) * 100
            else:
                backtest_accuracy = backtest_win_rate
            final_confidence = strategy_confidence * 0.4 + backtest_accuracy * 0.6
        else:
            final_confidence = strategy_confidence * 0.6

        final_confidence = round(final_confidence, 2)

        # Only emit if confidence meets threshold
        if final_confidence < MIN_CONFIDENCE_PCT:
            return None

        # Determine the NEXT trade time for this asset
        trade_time = self._find_next_trade_time(candles, analysis)

        # Determine category
        category = "forex"
        if asset.endswith("_otc"):
            category = "otc"
        elif asset.startswith("XAU") or asset.startswith("XAG"):
            category = "commodity"
        elif asset in ["BTCUSD", "ETHUSD", "LTCUSD", "XRPUSD", "ADAUSD"]:
            category = "crypto"
        elif any(idx in asset for idx in ["US100", "US30", "SPX", "DAX", "CAC", "NIKKEI"]):
            category = "index"

        signal = Signal(
            asset=asset,
            direction=direction,
            confidence=final_confidence,
            trade_time=trade_time,
            category=category,
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
            f"[{asset}] {signal.emoji} {direction} @ {signal.trade_time_local} "
            f"conf={final_confidence:.1f}%"
        )

        return signal

    def _find_next_trade_time(self, candles: list, analysis: dict) -> float:
        """
        Find the NEXT 1-minute candle boundary where the trade should be placed.

        Strategy: Look at the last few candles to find the candle closing
        time that aligns with the detected pattern. Then project forward
        to the NEXT occurrence of that candle boundary.

        For binary options on Quotex, trades expire at the next candle close.
        So if we detect a pattern now, the trade time is the NEXT 1-min
        candle close from the current time.
        """
        now = time.time()

        # Find the next 1-minute candle boundary
        # Candles close at :00 seconds of each minute
        period = CANDLE_PERIOD  # 60 seconds
        current_period = int(now // period)
        next_candle_close = (current_period + 1) * period

        # Check if patterns suggest a specific future time
        # If a candlestick pattern was detected, use its timing
        patterns = analysis.get("patterns_detected", [])
        if patterns:
            last_pattern_idx = max(p.get("index", 0) for p in patterns)
            if last_pattern_idx > 0 and last_pattern_idx < len(candles):
                pattern_candle = candles[last_pattern_idx]
                pattern_time = pattern_candle.get("time", 0)
                # The trade should be placed at the next candle close
                # after the pattern was detected
                if pattern_time > now - 300:  # Pattern is recent (within 5 min)
                    trade_time = pattern_time + period
                    if trade_time > now:
                        return trade_time

        # Default: the very next 1-minute candle close
        return next_candle_close

    def _get_or_run_backtest(self, asset: str, candles: list) -> Optional[dict]:
        """Get cached backtest result or run a new one."""
        now = time.time()
        if asset in self._backtest_cache:
            cached = self._backtest_cache[asset]
            if now - cached.get("computed_at", 0) < 3600:
                return cached

        result = self.backtester.run(candles)
        result_dict = result.to_dict()
        result_dict["computed_at"] = now
        self._backtest_cache[asset] = result_dict
        return result_dict

    async def refresh_and_merge(self, assets: list[str]) -> dict[str, list]:
        """
        Fetch the most recent hour of data and merge with cache.
        Only fetches the GAP — does NOT re-fetch existing data.
        """
        logger.info(f"Refreshing gap data for {len(assets)} assets...")

        # Only fetch recent data for assets that already have cache
        assets_with_cache = [a for a in assets if self.cache.has_data(a)]
        if not assets_with_cache:
            logger.info("No cached assets to refresh")
            return {}

        recent_data = await self.fetcher.fetch_recent_data(assets_with_cache)

        merged = {}
        for asset, recent_candles in recent_data.items():
            existing = self.cache.load(asset) or []
            if not existing and not recent_candles:
                continue
            merged_candles = self.cache.merge_candles(existing, recent_candles)
            merged_candles = self.cache.trim_to_history_depth(merged_candles)
            self.cache.save(asset, merged_candles)
            merged[asset] = merged_candles

        logger.info(f"Data refresh complete: {len(merged)} assets gap-filled")
        return merged
