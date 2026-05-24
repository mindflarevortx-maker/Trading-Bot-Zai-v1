"""
Backtesting Engine for Trading Bot Zai v1.

Implements walk-forward backtesting on historical candle data:
  - Splits data into training windows
  - Runs the confluence strategy on each window
  - Measures accuracy of predicted direction vs actual outcome
  - Computes win rate, profit factor, and confidence score
  - Only approves a signal if the backtest win rate exceeds threshold
"""

import logging
from typing import Optional

from bot.strategy import ConfluenceStrategy
from bot.config import MIN_CONFIDENCE_PCT, BACKTEST_WINDOW

logger = logging.getLogger("backtester")


class BacktestResult:
    """Holds the results of a backtest run."""

    def __init__(self):
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.win_rate = 0.0
        self.up_correct = 0
        self.up_total = 0
        self.down_correct = 0
        self.down_total = 0
        self.avg_confidence = 0.0
        self.profit_factor = 0.0
        self.max_consecutive_wins = 0
        self.max_consecutive_losses = 0
        self.signals_passed = 0
        self.signals_rejected = 0
        self.details: list[dict] = []

    def to_dict(self) -> dict:
        return {
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 2),
            "up_accuracy": round(self.up_correct / self.up_total * 100, 2) if self.up_total > 0 else 0,
            "down_accuracy": round(self.down_correct / self.down_total * 100, 2) if self.down_total > 0 else 0,
            "avg_confidence": round(self.avg_confidence, 2),
            "profit_factor": round(self.profit_factor, 2),
            "max_consecutive_wins": self.max_consecutive_wins,
            "max_consecutive_losses": self.max_consecutive_losses,
            "signals_passed": self.signals_passed,
            "signals_rejected": self.signals_rejected,
        }


class Backtester:
    """
    Walk-forward backtester using the ConfluenceStrategy.

    How it works:
      1. Take the last N candles of historical data
      2. Slide a window of ~200 candles forward, one candle at a time
      3. At each step, run the strategy on the window
      4. If the strategy produces a signal, check if the NEXT candle
         confirms the direction (close > open for UP, close < open for DOWN)
      5. Calculate win rate across all signals
      6. The backtest confidence = win_rate
      7. Signal is only approved if backtest confidence >= MIN_CONFIDENCE_PCT
    """

    def __init__(
        self,
        strategy: Optional[ConfluenceStrategy] = None,
        min_confidence: float = MIN_CONFIDENCE_PCT,
        window_size: int = 200,
        step_size: int = 5,
        max_tests: int = 500,
    ):
        self.strategy = strategy or ConfluenceStrategy(min_agreement=6)
        self.min_confidence = min_confidence
        self.window_size = window_size
        self.step_size = step_size
        self.max_tests = max_tests

    def run(self, candles: list) -> BacktestResult:
        """
        Run walk-forward backtest on historical candle data.

        Args:
            candles: List of candle dicts sorted by time

        Returns:
            BacktestResult with detailed statistics
        """
        result = BacktestResult()

        if len(candles) < self.window_size + 10:
            logger.warning(
                f"Insufficient data for backtesting: {len(candles)} candles "
                f"(need {self.window_size + 10})"
            )
            return result

        # We test from the end of the data backwards
        total_candles = len(candles)
        end_idx = total_candles - 1

        # Calculate test range
        # Start from the end and move backwards
        test_count = 0
        current_idx = end_idx

        confidences = []
        gross_profit = 0.0
        gross_loss = 0.0
        consecutive_wins = 0
        consecutive_losses = 0

        while current_idx > self.window_size and test_count < self.max_tests:
            # Window: [current_idx - window_size : current_idx]
            window_start = current_idx - self.window_size
            window = candles[window_start:current_idx]

            if len(window) < self.window_size:
                break

            # The "next" candle to validate against
            next_candle = candles[current_idx]

            # Run strategy analysis on the window
            analysis = self.strategy.analyze(window)

            # Only count if the strategy produced a signal
            if analysis.get("signal") and analysis.get("direction"):
                direction = analysis["direction"]
                confidence = analysis["confidence"]

                # Determine if the prediction was correct
                # For UP: next candle should close higher than it opened
                # For DOWN: next candle should close lower than it opened
                next_open = next_candle["open"]
                next_close = next_candle["close"]
                actual_up = next_close > next_open
                actual_down = next_close < next_open

                predicted_correct = (
                    (direction == "UP" and actual_up) or
                    (direction == "DOWN" and actual_down)
                )

                result.total_trades += 1

                if predicted_correct:
                    result.wins += 1
                    gross_profit += abs(next_close - next_open)
                    consecutive_wins += 1
                    consecutive_losses = 0
                    if direction == "UP":
                        result.up_correct += 1
                    else:
                        result.down_correct += 1
                else:
                    result.losses += 1
                    gross_loss += abs(next_close - next_open)
                    consecutive_losses += 1
                    consecutive_wins = 0

                if direction == "UP":
                    result.up_total += 1
                else:
                    result.down_total += 1

                confidences.append(confidence)
                result.details.append({
                    "index": current_idx,
                    "direction": direction,
                    "confidence": confidence,
                    "correct": predicted_correct,
                    "next_change": next_close - next_open,
                })

                # Check confidence threshold
                if confidence >= self.min_confidence:
                    result.signals_passed += 1
                else:
                    result.signals_rejected += 1

            # Track max consecutive
            result.max_consecutive_wins = max(result.max_consecutive_wins, consecutive_wins)
            result.max_consecutive_losses = max(result.max_consecutive_losses, consecutive_losses)

            # Move backwards
            current_idx -= self.step_size
            test_count += 1

        # Calculate final statistics
        if result.total_trades > 0:
            result.win_rate = (result.wins / result.total_trades) * 100
        if confidences:
            result.avg_confidence = sum(confidences) / len(confidences)
        if gross_loss > 0:
            result.profit_factor = gross_profit / gross_loss
        elif gross_profit > 0:
            result.profit_factor = float('inf')

        logger.info(
            f"Backtest complete: {result.total_trades} trades, "
            f"{result.win_rate:.1f}% win rate, "
            f"{result.avg_confidence:.1f}% avg confidence"
        )

        return result

    def is_strategy_reliable(self, candles: list) -> tuple[bool, BacktestResult]:
        """
        Determine if the strategy is reliable enough for this asset.

        Returns:
            (is_reliable, backtest_result)
            is_reliable is True if win_rate >= min_confidence
        """
        result = self.run(candles)
        is_reliable = result.win_rate >= self.min_confidence and result.total_trades >= 10

        if is_reliable:
            logger.info(
                f"Strategy RELIABLE: {result.win_rate:.1f}% win rate "
                f"({result.wins}/{result.total_trades})"
            )
        else:
            logger.info(
                f"Strategy NOT RELIABLE: {result.win_rate:.1f}% win rate "
                f"({result.wins}/{result.total_trades}) - need {self.min_confidence}%"
            )

        return is_reliable, result

    def calculate_signal_confidence(self, candles: list, signal_direction: str, strategy_confidence: float) -> float:
        """
        Combine strategy confidence with backtest win rate to produce
        a final confidence score for a signal.

        Formula: final_confidence = (strategy_confidence * 0.4 + backtest_win_rate * 0.6)
        Backtesting gets more weight because it's validated on historical data.
        """
        result = self.run(candles)

        if result.total_trades == 0:
            return strategy_confidence * 0.5  # No backtest data, reduce confidence

        # Use direction-specific accuracy if available
        if signal_direction == "UP" and result.up_total > 0:
            backtest_accuracy = (result.up_correct / result.up_total) * 100
        elif signal_direction == "DOWN" and result.down_total > 0:
            backtest_accuracy = (result.down_correct / result.down_total) * 100
        else:
            backtest_accuracy = result.win_rate

        final_confidence = strategy_confidence * 0.4 + backtest_accuracy * 0.6

        logger.info(
            f"Signal confidence: strategy={strategy_confidence:.1f}%, "
            f"backtest={backtest_accuracy:.1f}%, "
            f"final={final_confidence:.1f}%"
        )

        return round(final_confidence, 2)
