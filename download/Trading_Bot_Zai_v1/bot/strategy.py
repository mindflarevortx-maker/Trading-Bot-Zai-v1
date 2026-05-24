"""
Trading Strategy & Pattern Recognition for Trading Bot Zai v1.

Implements a multi-layer confluence strategy that combines:
  1. Trend Detection (EMA alignment + ADX)
  2. Momentum Confirmation (RSI + MACD)
  3. Volatility Squeeze / Expansion (Bollinger + ATR)
  4. Overbought/Oversold Zones (Stochastic + RSI)
  5. Support/Resistance Proximity (Pivot Points + SAR)
  6. Candlestick Pattern Recognition
  7. Ichimoku Cloud Position

Signal is only generated when ALL layers agree on direction,
producing a high-confidence signal.
"""

import logging
from typing import Optional

import numpy as np

from bot.indicators import TechnicalIndicators as TI

logger = logging.getLogger("strategy")


class CandlestickPatterns:
    """
    Detects common candlestick patterns in OHLC data.
    Returns pattern name and bullish/bearish direction.
    """

    @staticmethod
    def is_bullish_engulfing(prev_open, prev_close, curr_open, curr_close) -> bool:
        """Bullish Engulfing: prev bearish, curr bullish, curr body engulfs prev."""
        prev_bearish = prev_close < prev_open
        curr_bullish = curr_close > curr_open
        curr_engulfs = curr_open <= prev_close and curr_close >= prev_open
        return prev_bearish and curr_bullish and curr_engulfs

    @staticmethod
    def is_bearish_engulfing(prev_open, prev_close, curr_open, curr_close) -> bool:
        """Bearish Engulfing: prev bullish, curr bearish, curr body engulfs prev."""
        prev_bullish = prev_close > prev_open
        curr_bearish = curr_close < curr_open
        curr_engulfs = curr_open >= prev_close and curr_close <= prev_open
        return prev_bullish and curr_bearish and curr_engulfs

    @staticmethod
    def is_hammer(open_p, high, low, close) -> bool:
        """Hammer: small body at top, long lower shadow (>= 2x body)."""
        body = abs(close - open_p)
        lower_shadow = min(open_p, close) - low
        upper_shadow = high - max(open_p, close)
        return lower_shadow >= 2 * body and upper_shadow < body and body > 0

    @staticmethod
    def is_shooting_star(open_p, high, low, close) -> bool:
        """Shooting Star: small body at bottom, long upper shadow (>= 2x body)."""
        body = abs(close - open_p)
        upper_shadow = high - max(open_p, close)
        lower_shadow = min(open_p, close) - low
        return upper_shadow >= 2 * body and lower_shadow < body and body > 0

    @staticmethod
    def is_doji(open_p, close, threshold=0.0001) -> bool:
        """Doji: open and close are nearly equal."""
        return abs(close - open_p) <= threshold * close

    @staticmethod
    def is_morning_star(c1_o, c1_c, c2_o, c2_c, c3_o, c3_c) -> bool:
        """Morning Star: bearish -> small body -> bullish reversal."""
        return (c1_c < c1_o and  # Candle 1 bearish
                abs(c2_c - c2_o) < abs(c1_c - c1_o) * 0.3 and  # Candle 2 small body
                c3_c > c3_o and  # Candle 3 bullish
                c3_c > (c1_o + c1_c) / 2)  # Closes above midpoint of candle 1

    @staticmethod
    def is_evening_star(c1_o, c1_c, c2_o, c2_c, c3_o, c3_c) -> bool:
        """Evening Star: bullish -> small body -> bearish reversal."""
        return (c1_c > c1_o and
                abs(c2_c - c2_o) < abs(c1_c - c1_o) * 0.3 and
                c3_c < c3_o and
                c3_c < (c1_o + c1_c) / 2)

    @staticmethod
    def detect_patterns(candles: list, lookback: int = 5) -> list[dict]:
        """
        Detect all known patterns in the most recent candles.
        Returns list of {pattern_name, direction: "bullish"|"bearish", index}.
        """
        patterns = []
        n = len(candles)
        if n < 3:
            return patterns

        # Check last few candles
        for i in range(max(n - lookback, 2), n):
            c = candles[i]
            p = candles[i - 1]

            o, h, l, cl = c["open"], c["high"], c["low"], c["close"]
            po, pc = p["open"], p["close"]

            if CandlestickPatterns.is_bullish_engulfing(po, pc, o, cl):
                patterns.append({"pattern": "bullish_engulfing", "direction": "bullish", "index": i})

            if CandlestickPatterns.is_bearish_engulfing(po, pc, o, cl):
                patterns.append({"pattern": "bearish_engulfing", "direction": "bearish", "index": i})

            if CandlestickPatterns.is_hammer(o, h, l, cl):
                patterns.append({"pattern": "hammer", "direction": "bullish", "index": i})

            if CandlestickPatterns.is_shooting_star(o, h, l, cl):
                patterns.append({"pattern": "shooting_star", "direction": "bearish", "index": i})

            if CandlestickPatterns.is_doji(o, cl):
                patterns.append({"pattern": "doji", "direction": "neutral", "index": i})

            # 3-candle patterns
            if i >= 2:
                pp = candles[i - 2]
                if CandlestickPatterns.is_morning_star(pp["open"], pp["close"], po, pc, o, cl):
                    patterns.append({"pattern": "morning_star", "direction": "bullish", "index": i})

                if CandlestickPatterns.is_evening_star(pp["open"], pp["close"], po, pc, o, cl):
                    patterns.append({"pattern": "evening_star", "direction": "bearish", "index": i})

        return patterns


class ConfluenceStrategy:
    """
    Multi-layer confluence strategy for high-confidence signal generation.

    A signal is generated ONLY when at least 6 out of 7 layers agree:
      1. Trend (EMA alignment + ADX)
      2. Momentum (RSI directional)
      3. MACD (Line/Signal crossover or direction)
      4. Bollinger Band position
      5. Stochastic (Overbought/Oversold + crossover)
      6. Candlestick patterns
      7. Ichimoku cloud position

    The confidence score is calculated as: (agreeing_layers / total_layers) * 100
    """

    def __init__(self, min_agreement: int = 6):
        self.min_agreement = min_agreement
        self.patterns = CandlestickPatterns()

    def analyze(self, candles: list) -> dict:
        """
        Run full confluence analysis on candle data.

        Returns:
            {
                "direction": "UP" | "DOWN" | None,
                "confidence": float (0-100),
                "layers": dict of layer results,
                "patterns_detected": list,
                "signal": bool (True if confidence >= threshold),
            }
        """
        if len(candles) < 200:
            return self._empty_result("Insufficient data (need 200+ candles)")

        try:
            indicators = TI.full_analysis(candles)
            if not indicators:
                return self._empty_result("Indicator computation failed")

            n = len(candles)

            # ─── Layer 1: Trend Detection ──────────────────────────────
            trend = self._analyze_trend(indicators, candles)

            # ─── Layer 2: Momentum (RSI) ──────────────────────────────
            momentum = self._analyze_momentum(indicators)

            # ─── Layer 3: MACD ────────────────────────────────────────
            macd = self._analyze_macd(indicators)

            # ─── Layer 4: Bollinger Bands ─────────────────────────────
            bollinger = self._analyze_bollinger(indicators, candles)

            # ─── Layer 5: Stochastic ──────────────────────────────────
            stochastic = self._analyze_stochastic(indicators)

            # ─── Layer 6: Candlestick Patterns ────────────────────────
            candlestick = self._analyze_candlestick(candles)

            # ─── Layer 7: Ichimoku ────────────────────────────────────
            ichimoku = self._analyze_ichimoku(indicators, candles)

            # ─── Confluence Calculation ────────────────────────────────
            layers = {
                "trend": trend,
                "momentum": momentum,
                "macd": macd,
                "bollinger": bollinger,
                "stochastic": stochastic,
                "candlestick": candlestick,
                "ichimoku": ichimoku,
            }

            # Count directions
            up_votes = sum(1 for v in layers.values() if v.get("direction") == "UP")
            down_votes = sum(1 for v in layers.values() if v.get("direction") == "DOWN")
            neutral_votes = sum(1 for v in layers.values() if v.get("direction") == "NEUTRAL")

            # Determine overall direction
            if up_votes >= self.min_agreement:
                direction = "UP"
                confidence = (up_votes / 7.0) * 100
            elif down_votes >= self.min_agreement:
                direction = "DOWN"
                confidence = (down_votes / 7.0) * 100
            elif up_votes > down_votes and up_votes >= 4:
                direction = "UP"
                confidence = (up_votes / 7.0) * 100
            elif down_votes > up_votes and down_votes >= 4:
                direction = "DOWN"
                confidence = (down_votes / 7.0) * 100
            else:
                direction = None
                confidence = max(up_votes, down_votes) / 7.0 * 100

            # Detect patterns
            patterns_detected = self.patterns.detect_patterns(candles)

            return {
                "direction": direction,
                "confidence": round(confidence, 2),
                "layers": layers,
                "patterns_detected": patterns_detected,
                "signal": direction is not None and confidence >= 85.0,
                "up_votes": up_votes,
                "down_votes": down_votes,
                "neutral_votes": neutral_votes,
            }

        except Exception as e:
            logger.error(f"Analysis error: {e}", exc_info=True)
            return self._empty_result(f"Error: {str(e)}")

    def _analyze_trend(self, indicators: dict, candles: list) -> dict:
        """Layer 1: Trend detection via EMA alignment and ADX."""
        n = len(candles)
        ema_20 = indicators.get("ema_20", np.array([]))
        ema_50 = indicators.get("ema_50", np.array([]))
        ema_200 = indicators.get("ema_200", np.array([]))
        adx = indicators.get("adx_14", np.array([]))
        close = TI.closes(candles)

        if len(ema_20) == 0 or len(ema_50) == 0:
            return {"direction": "NEUTRAL", "strength": 0, "reason": "Insufficient data"}

        # Last valid indices
        last_close = close[-1]
        last_ema20 = ema_20[-1] if not np.isnan(ema_20[-1]) else ema_20[~np.isnan(ema_20)][-1]
        last_ema50 = ema_50[-1] if not np.isnan(ema_50[-1]) else ema_50[~np.isnan(ema_50)][-1]

        # EMA alignment
        bullish_alignment = last_close > last_ema20 > last_ema50
        bearish_alignment = last_close < last_ema20 < last_ema50

        # ADX strength
        adx_val = adx[-1] if len(adx) > 0 and not np.isnan(adx[-1]) else 0
        trend_strength = "strong" if adx_val > 25 else "weak"

        if bullish_alignment:
            return {"direction": "UP", "strength": adx_val, "reason": f"EMA bullish alignment, ADX={adx_val:.1f} ({trend_strength})"}
        elif bearish_alignment:
            return {"direction": "DOWN", "strength": adx_val, "reason": f"EMA bearish alignment, ADX={adx_val:.1f} ({trend_strength})"}
        else:
            return {"direction": "NEUTRAL", "strength": adx_val, "reason": f"No EMA alignment, ADX={adx_val:.1f}"}

    def _analyze_momentum(self, indicators: dict) -> dict:
        """Layer 2: RSI momentum analysis."""
        rsi_7 = indicators.get("rsi_7", np.array([]))
        rsi_14 = indicators.get("rsi_14", np.array([]))

        if len(rsi_14) == 0:
            return {"direction": "NEUTRAL", "strength": 0, "reason": "No RSI data"}

        last_rsi7 = rsi_7[-1] if not np.isnan(rsi_7[-1]) else 50
        last_rsi14 = rsi_14[-1] if not np.isnan(rsi_14[-1]) else 50

        # Strong overbought/oversold
        if last_rsi7 > 70 and last_rsi14 > 65:
            # Overbought → potential reversal DOWN
            return {"direction": "DOWN", "strength": last_rsi14, "reason": f"Overbought RSI7={last_rsi7:.1f}, RSI14={last_rsi14:.1f}"}
        elif last_rsi7 < 30 and last_rsi14 < 35:
            # Oversold → potential reversal UP
            return {"direction": "UP", "strength": last_rsi14, "reason": f"Oversold RSI7={last_rsi7:.1f}, RSI14={last_rsi14:.1f}"}
        elif last_rsi7 > 50 and last_rsi14 > 50:
            return {"direction": "UP", "strength": last_rsi14, "reason": f"Bullish momentum RSI7={last_rsi7:.1f}, RSI14={last_rsi14:.1f}"}
        elif last_rsi7 < 50 and last_rsi14 < 50:
            return {"direction": "DOWN", "strength": last_rsi14, "reason": f"Bearish momentum RSI7={last_rsi7:.1f}, RSI14={last_rsi14:.1f}"}
        else:
            return {"direction": "NEUTRAL", "strength": last_rsi14, "reason": f"Mixed RSI signals RSI7={last_rsi7:.1f}, RSI14={last_rsi14:.1f}"}

    def _analyze_macd(self, indicators: dict) -> dict:
        """Layer 3: MACD analysis."""
        macd_line = indicators.get("macd_line", np.array([]))
        macd_signal = indicators.get("macd_signal", np.array([]))
        macd_hist = indicators.get("macd_histogram", np.array([]))

        if len(macd_line) == 0 or len(macd_signal) == 0:
            return {"direction": "NEUTRAL", "strength": 0, "reason": "No MACD data"}

        valid_mask = ~np.isnan(macd_line) & ~np.isnan(macd_signal)
        if valid_mask.sum() < 3:
            return {"direction": "NEUTRAL", "strength": 0, "reason": "Insufficient MACD data"}

        last_macd = macd_line[valid_mask][-1]
        last_signal = macd_signal[valid_mask][-1]
        prev_hist = macd_hist[valid_mask][-2] if len(macd_hist[valid_mask]) >= 2 else 0
        last_hist = macd_hist[valid_mask][-1]

        # MACD above signal = bullish; below = bearish
        # Histogram expanding = strengthening
        if last_macd > last_signal and last_hist > 0:
            if last_hist > prev_hist:
                return {"direction": "UP", "strength": abs(last_hist), "reason": f"Bullish MACD, expanding histogram"}
            else:
                return {"direction": "UP", "strength": abs(last_hist) * 0.7, "reason": f"Bullish MACD, contracting histogram"}
        elif last_macd < last_signal and last_hist < 0:
            if last_hist < prev_hist:
                return {"direction": "DOWN", "strength": abs(last_hist), "reason": f"Bearish MACD, expanding histogram"}
            else:
                return {"direction": "DOWN", "strength": abs(last_hist) * 0.7, "reason": f"Bearish MACD, contracting histogram"}
        else:
            return {"direction": "NEUTRAL", "strength": abs(last_hist), "reason": "MACD crossover zone"}

    def _analyze_bollinger(self, indicators: dict, candles: list) -> dict:
        """Layer 4: Bollinger Band position analysis."""
        bb_upper = indicators.get("bb_upper", np.array([]))
        bb_lower = indicators.get("bb_lower", np.array([]))
        bb_middle = indicators.get("bb_middle", np.array([]))
        close = TI.closes(candles)

        if len(bb_upper) == 0 or len(bb_lower) == 0:
            return {"direction": "NEUTRAL", "strength": 0, "reason": "No Bollinger data"}

        last_close = close[-1]
        last_upper = bb_upper[-1] if not np.isnan(bb_upper[-1]) else bb_upper[~np.isnan(bb_upper)][-1]
        last_lower = bb_lower[-1] if not np.isnan(bb_lower[-1]) else bb_lower[~np.isnan(bb_lower)][-1]
        last_middle = bb_middle[-1] if not np.isnan(bb_middle[-1]) else bb_middle[~np.isnan(bb_middle)][-1]

        band_width = last_upper - last_lower
        if band_width == 0:
            return {"direction": "NEUTRAL", "strength": 0, "reason": "Zero band width"}

        # Position within bands (0 = lower, 1 = upper)
        position = (last_close - last_lower) / band_width

        if position > 0.95:
            # Near upper band → potential reversal DOWN
            return {"direction": "DOWN", "strength": position * 100, "reason": f"Near upper band ({position:.1%})"}
        elif position < 0.05:
            # Near lower band → potential reversal UP
            return {"direction": "UP", "strength": (1 - position) * 100, "reason": f"Near lower band ({position:.1%})"}
        elif position > 0.5:
            return {"direction": "UP", "strength": position * 60, "reason": f"Above midline ({position:.1%})"}
        elif position < 0.5:
            return {"direction": "DOWN", "strength": (1 - position) * 60, "reason": f"Below midline ({position:.1%})"}
        else:
            return {"direction": "NEUTRAL", "strength": 50, "reason": f"At midline ({position:.1%})"}

    def _analyze_stochastic(self, indicators: dict) -> dict:
        """Layer 5: Stochastic oscillator analysis."""
        stoch_k = indicators.get("stoch_k", np.array([]))
        stoch_d = indicators.get("stoch_d", np.array([]))

        if len(stoch_k) == 0 or len(stoch_d) == 0:
            return {"direction": "NEUTRAL", "strength": 0, "reason": "No Stochastic data"}

        valid_mask = ~np.isnan(stoch_k) & ~np.isnan(stoch_d)
        if valid_mask.sum() < 3:
            return {"direction": "NEUTRAL", "strength": 0, "reason": "Insufficient Stochastic data"}

        last_k = stoch_k[valid_mask][-1]
        last_d = stoch_d[valid_mask][-1]
        prev_k = stoch_k[valid_mask][-2]
        prev_d = stoch_d[valid_mask][-2]

        # Overbought/oversold zones
        if last_k > 80 and last_d > 80:
            # Overbought zone
            if prev_k < prev_d and last_k > last_d:
                # Bearish crossover in overbought → strong DOWN
                return {"direction": "DOWN", "strength": last_k, "reason": f"Bearish crossover overbought K={last_k:.1f} D={last_d:.1f}"}
            return {"direction": "DOWN", "strength": last_k * 0.8, "reason": f"Overbought K={last_k:.1f} D={last_d:.1f}"}

        elif last_k < 20 and last_d < 20:
            # Oversold zone
            if prev_k > prev_d and last_k < last_d:
                # Bullish crossover in oversold → strong UP
                return {"direction": "UP", "strength": 100 - last_k, "reason": f"Bullish crossover oversold K={last_k:.1f} D={last_d:.1f}"}
            return {"direction": "UP", "strength": (100 - last_k) * 0.8, "reason": f"Oversold K={last_k:.1f} D={last_d:.1f}"}

        elif last_k > last_d and prev_k <= prev_d:
            # Bullish crossover
            return {"direction": "UP", "strength": 60, "reason": f"Bullish crossover K={last_k:.1f} D={last_d:.1f}"}

        elif last_k < last_d and prev_k >= prev_d:
            # Bearish crossover
            return {"direction": "DOWN", "strength": 60, "reason": f"Bearish crossover K={last_k:.1f} D={last_d:.1f}"}

        elif last_k > 50:
            return {"direction": "UP", "strength": 40, "reason": f"K above 50 ({last_k:.1f})"}
        elif last_k < 50:
            return {"direction": "DOWN", "strength": 40, "reason": f"K below 50 ({last_k:.1f})"}

        return {"direction": "NEUTRAL", "strength": 0, "reason": "No clear signal"}

    def _analyze_candlestick(self, candles: list) -> dict:
        """Layer 6: Candlestick pattern analysis."""
        patterns = self.patterns.detect_patterns(candles, lookback=3)

        if not patterns:
            # Check last candle direction
            last = candles[-1]
            if last["close"] > last["open"]:
                return {"direction": "UP", "strength": 30, "reason": "Last candle bullish (no pattern)"}
            elif last["close"] < last["open"]:
                return {"direction": "DOWN", "strength": 30, "reason": "Last candle bearish (no pattern)"}
            return {"direction": "NEUTRAL", "strength": 0, "reason": "No patterns detected"}

        # Weight patterns by type
        bullish_weight = 0
        bearish_weight = 0

        pattern_weights = {
            "bullish_engulfing": 3,
            "bearish_engulfing": 3,
            "morning_star": 4,
            "evening_star": 4,
            "hammer": 2,
            "shooting_star": 2,
            "doji": 1,
        }

        for p in patterns:
            weight = pattern_weights.get(p["pattern"], 1)
            if p["direction"] == "bullish":
                bullish_weight += weight
            elif p["direction"] == "bearish":
                bearish_weight += weight

        pattern_names = [p["pattern"] for p in patterns]

        if bullish_weight > bearish_weight:
            return {"direction": "UP", "strength": bullish_weight * 20, "reason": f"Patterns: {', '.join(pattern_names)}"}
        elif bearish_weight > bullish_weight:
            return {"direction": "DOWN", "strength": bearish_weight * 20, "reason": f"Patterns: {', '.join(pattern_names)}"}
        else:
            return {"direction": "NEUTRAL", "strength": 0, "reason": f"Mixed patterns: {', '.join(pattern_names)}"}

    def _analyze_ichimoku(self, indicators: dict, candles: list) -> dict:
        """Layer 7: Ichimoku Cloud position analysis."""
        ichimoku = indicators.get("ichimoku", {})
        close = TI.closes(candles)

        if not ichimoku or len(close) == 0:
            return {"direction": "NEUTRAL", "strength": 0, "reason": "No Ichimoku data"}

        tenkan = ichimoku.get("tenkan_sen", np.array([]))
        kijun = ichimoku.get("kijun_sen", np.array([]))
        senkou_a = ichimoku.get("senkou_span_a", np.array([]))
        senkou_b = ichimoku.get("senkou_span_b", np.array([]))

        if len(tenkan) == 0 or len(kijun) == 0:
            return {"direction": "NEUTRAL", "strength": 0, "reason": "Insufficient Ichimoku data"}

        last_close = close[-1]
        last_tenkan = tenkan[-1] if not np.isnan(tenkan[-1]) else tenkan[~np.isnan(tenkan)][-1]
        last_kijun = kijun[-1] if not np.isnan(kijun[-1]) else kijun[~np.isnan(kijun)][-1]

        # Get cloud values (Senkou spans)
        valid_a = senkou_a[~np.isnan(senkou_a)]
        valid_b = senkou_b[~np.isnan(senkou_b)]

        if len(valid_a) > 0 and len(valid_b) > 0:
            cloud_top = max(valid_a[-1], valid_b[-1])
            cloud_bottom = min(valid_a[-1], valid_b[-1])
        else:
            cloud_top = cloud_bottom = last_close

        # Price above cloud = bullish
        # Price below cloud = bearish
        # TK cross above = bullish signal

        if last_close > cloud_top and last_tenkan > last_kijun:
            return {"direction": "UP", "strength": 80, "reason": f"Price above cloud + TK bullish cross"}
        elif last_close < cloud_bottom and last_tenkan < last_kijun:
            return {"direction": "DOWN", "strength": 80, "reason": f"Price below cloud + TK bearish cross"}
        elif last_close > cloud_top:
            return {"direction": "UP", "strength": 60, "reason": f"Price above cloud"}
        elif last_close < cloud_bottom:
            return {"direction": "DOWN", "strength": 60, "reason": f"Price below cloud"}
        elif last_tenkan > last_kijun:
            return {"direction": "UP", "strength": 40, "reason": f"TK bullish cross (in cloud)"}
        elif last_tenkan < last_kijun:
            return {"direction": "DOWN", "strength": 40, "reason": f"TK bearish cross (in cloud)"}
        else:
            return {"direction": "NEUTRAL", "strength": 0, "reason": "Inside cloud, no TK cross"}

    @staticmethod
    def _empty_result(reason: str = "") -> dict:
        return {
            "direction": None,
            "confidence": 0.0,
            "layers": {},
            "patterns_detected": [],
            "signal": False,
            "up_votes": 0,
            "down_votes": 0,
            "neutral_votes": 7,
            "reason": reason,
        }
