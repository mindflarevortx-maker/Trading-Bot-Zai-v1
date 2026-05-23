"""
Technical Indicators for Trading Bot Zai v1.

Pure-Python implementations of all technical indicators used by the
signal generation and backtesting engines. No external TA library required.

Includes:
  - SMA (Simple Moving Average)
  - EMA (Exponential Moving Average)
  - RSI (Relative Strength Index)
  - MACD (Moving Average Convergence Divergence)
  - Bollinger Bands
  - Stochastic Oscillator
  - ATR (Average True Range)
  - ADX (Average Directional Index)
  - Ichimoku Cloud
  - VWAP (Volume-Weighted Average Price)
  - Parabolic SAR
"""

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger("indicators")


class TechnicalIndicators:
    """
    Computes technical indicators from OHLC candle data.
    All methods accept and return numpy arrays or Python floats.
    """

    @staticmethod
    def closes(candles: list) -> np.ndarray:
        """Extract close prices from candle list."""
        return np.array([c["close"] for c in candles], dtype=np.float64)

    @staticmethod
    def opens(candles: list) -> np.ndarray:
        return np.array([c["open"] for c in candles], dtype=np.float64)

    @staticmethod
    def highs(candles: list) -> np.ndarray:
        return np.array([c["high"] for c in candles], dtype=np.float64)

    @staticmethod
    def lows(candles: list) -> np.ndarray:
        return np.array([c["low"] for c in candles], dtype=np.float64)

    @staticmethod
    def ticks(candles: list) -> np.ndarray:
        return np.array([c.get("ticks", c.get("volume", 1)) for c in candles], dtype=np.float64)

    # ─── Moving Averages ───────────────────────────────────────────────

    @staticmethod
    def sma(data: np.ndarray, period: int) -> np.ndarray:
        """Simple Moving Average."""
        if len(data) < period:
            return np.array([])
        cumsum = np.cumsum(data)
        result = np.empty_like(data)
        result[:period - 1] = np.nan
        result[period - 1:] = (cumsum[period - 1:] - np.concatenate([[0], cumsum[:-period]])) / period
        return result

    @staticmethod
    def ema(data: np.ndarray, period: int) -> np.ndarray:
        """Exponential Moving Average."""
        if len(data) < period:
            return np.array([])
        result = np.empty_like(data)
        multiplier = 2.0 / (period + 1)
        # Start with SMA for the first value
        result[:period - 1] = np.nan
        result[period - 1] = np.mean(data[:period])
        for i in range(period, len(data)):
            result[i] = (data[i] - result[i - 1]) * multiplier + result[i - 1]
        return result

    @staticmethod
    def wma(data: np.ndarray, period: int) -> np.ndarray:
        """Weighted Moving Average."""
        if len(data) < period:
            return np.array([])
        weights = np.arange(1, period + 1, dtype=np.float64)
        weights_sum = weights.sum()
        result = np.empty_like(data)
        result[:period - 1] = np.nan
        for i in range(period - 1, len(data)):
            result[i] = np.dot(data[i - period + 1:i + 1], weights) / weights_sum
        return result

    # ─── Oscillators ───────────────────────────────────────────────────

    @staticmethod
    def rsi(data: np.ndarray, period: int = 14) -> np.ndarray:
        """Relative Strength Index."""
        if len(data) < period + 1:
            return np.array([])
        deltas = np.diff(data)
        result = np.empty(len(data))
        result[:period] = np.nan

        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)

        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        if avg_loss == 0:
            result[period] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[period] = 100.0 - (100.0 / (1.0 + rs))

        for i in range(period + 1, len(data)):
            avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period

            if avg_loss == 0:
                result[i] = 100.0
            else:
                rs = avg_gain / avg_loss
                result[i] = 100.0 - (100.0 / (1.0 + rs))

        return result

    @staticmethod
    def stochastic(
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        k_period: int = 14,
        d_period: int = 3,
        smooth: int = 3,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Stochastic Oscillator.
        Returns (k_percent, d_percent) arrays.
        """
        n = len(closes)
        k_raw = np.empty(n)
        k_raw[:] = np.nan

        for i in range(k_period - 1, n):
            hh = np.max(highs[i - k_period + 1:i + 1])
            ll = np.min(lows[i - k_period + 1:i + 1])
            if hh - ll != 0:
                k_raw[i] = ((closes[i] - ll) / (hh - ll)) * 100.0
            else:
                k_raw[i] = 50.0

        # Smooth K with SMA
        if smooth > 1:
            k_smooth = TechnicalIndicators.sma(k_raw[~np.isnan(k_raw)], smooth)
            k_result = np.empty(n)
            k_result[:] = np.nan
            valid_start = k_period - 1 + smooth - 1
            k_result[valid_start:valid_start + len(k_smooth)] = k_smooth
        else:
            k_result = k_raw

        # D line = SMA of K
        d_result = TechnicalIndicators.sma(k_result, d_period)

        return k_result, d_result

    # ─── MACD ──────────────────────────────────────────────────────────

    @staticmethod
    def macd(
        data: np.ndarray,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        MACD (Moving Average Convergence Divergence).
        Returns (macd_line, signal_line, histogram).
        """
        ema_fast = TechnicalIndicators.ema(data, fast)
        ema_slow = TechnicalIndicators.ema(data, slow)

        macd_line = ema_fast - ema_slow
        signal_line = TechnicalIndicators.ema(macd_line[~np.isnan(macd_line)], signal)

        # Align signal line
        macd_valid_start = np.argmax(~np.isnan(macd_line))
        full_signal = np.empty_like(macd_line)
        full_signal[:] = np.nan
        sig_start = macd_valid_start
        full_signal[sig_start:sig_start + len(signal_line)] = signal_line

        histogram = macd_line - full_signal

        return macd_line, full_signal, histogram

    # ─── Bollinger Bands ───────────────────────────────────────────────

    @staticmethod
    def bollinger_bands(
        data: np.ndarray,
        period: int = 20,
        std_dev: float = 2.0,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        Bollinger Bands.
        Returns (upper_band, middle_band, lower_band).
        """
        middle = TechnicalIndicators.sma(data, period)
        if len(middle) == 0:
            return np.array([]), np.array([]), np.array([])

        rolling_std = np.empty_like(data)
        rolling_std[:period - 1] = np.nan
        for i in range(period - 1, len(data)):
            rolling_std[i] = np.std(data[i - period + 1:i + 1])

        upper = middle + std_dev * rolling_std
        lower = middle - std_dev * rolling_std

        return upper, middle, lower

    # ─── ATR ───────────────────────────────────────────────────────────

    @staticmethod
    def atr(
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        period: int = 14,
    ) -> np.ndarray:
        """Average True Range."""
        n = len(closes)
        if n < 2:
            return np.array([])

        tr = np.empty(n)
        tr[0] = highs[0] - lows[0]
        for i in range(1, n):
            hl = highs[i] - lows[i]
            hc = abs(highs[i] - closes[i - 1])
            lc = abs(lows[i] - closes[i - 1])
            tr[i] = max(hl, hc, lc)

        result = TechnicalIndicators.ema(tr, period)
        return result

    # ─── ADX ───────────────────────────────────────────────────────────

    @staticmethod
    def adx(
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        period: int = 14,
    ) -> np.ndarray:
        """Average Directional Index."""
        n = len(closes)
        if n < period + 1:
            return np.array([])

        # True Range
        tr = np.empty(n)
        tr[0] = highs[0] - lows[0]
        for i in range(1, n):
            tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))

        # +DM and -DM
        plus_dm = np.zeros(n)
        minus_dm = np.zeros(n)
        for i in range(1, n):
            up_move = highs[i] - highs[i-1]
            down_move = lows[i-1] - lows[i]
            if up_move > down_move and up_move > 0:
                plus_dm[i] = up_move
            if down_move > up_move and down_move > 0:
                minus_dm[i] = down_move

        # Smooth
        atr_val = TechnicalIndicators.ema(tr, period)
        smooth_plus_dm = TechnicalIndicators.ema(plus_dm, period)
        smooth_minus_dm = TechnicalIndicators.ema(minus_dm, period)

        # +DI and -DI
        with np.errstate(divide='ignore', invalid='ignore'):
            plus_di = np.where(atr_val != 0, (smooth_plus_dm / atr_val) * 100, 0)
            minus_di = np.where(atr_val != 0, (smooth_minus_dm / atr_val) * 100, 0)

        # DX
        with np.errstate(divide='ignore', invalid='ignore'):
            dx = np.where(
                (plus_di + minus_di) != 0,
                abs(plus_di - minus_di) / (plus_di + minus_di) * 100,
                0
            )

        # ADX = smoothed DX
        adx_result = TechnicalIndicators.ema(dx, period)
        return adx_result

    # ─── Ichimoku Cloud ────────────────────────────────────────────────

    @staticmethod
    def ichimoku(
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        tenkan: int = 9,
        kijun: int = 26,
        senkou_b: int = 52,
    ) -> dict:
        """
        Ichimoku Cloud.
        Returns dict with: tenkan_sen, kijun_sen, senkou_span_a, senkou_span_b, chikou_span
        """
        n = len(closes)

        def midpoint(h, l, period):
            result = np.empty(n)
            result[:] = np.nan
            for i in range(period - 1, n):
                hh = np.max(h[i - period + 1:i + 1])
                ll = np.min(l[i - period + 1:i + 1])
                result[i] = (hh + ll) / 2.0
            return result

        tenkan_sen = midpoint(highs, lows, tenkan)
        kijun_sen = midpoint(highs, lows, kijun)

        # Senkou Span A = (Tenkan + Kijun) / 2, shifted 26 periods forward
        senkou_a = np.empty(n + kijun)
        senkou_a[:] = np.nan
        for i in range(kijun - 1, n):
            if not np.isnan(tenkan_sen[i]) and not np.isnan(kijun_sen[i]):
                senkou_a[i + kijun] = (tenkan_sen[i] + kijun_sen[i]) / 2.0

        # Senkou Span B = midpoint of last 52 periods, shifted 26 forward
        senkou_b_line = midpoint(highs, lows, senkou_b)
        senkou_b_result = np.empty(n + kijun)
        senkou_b_result[:] = np.nan
        for i in range(senkou_b - 1, n):
            if not np.isnan(senkou_b_line[i]):
                senkou_b_result[i + kijun] = senkou_b_line[i]

        # Chikou Span = close shifted 26 periods back
        chikou = np.empty(n)
        chikou[:] = np.nan
        if n > kijun:
            chikou[:n - kijun] = closes[kijun:]

        return {
            "tenkan_sen": tenkan_sen,
            "kijun_sen": kijun_sen,
            "senkou_span_a": senkou_a[:n],
            "senkou_span_b": senkou_b_result[:n],
            "chikou_span": chikou,
        }

    # ─── Parabolic SAR ─────────────────────────────────────────────────

    @staticmethod
    def parabolic_sar(
        highs: np.ndarray,
        lows: np.ndarray,
        af_step: float = 0.02,
        af_max: float = 0.2,
    ) -> np.ndarray:
        """Parabolic SAR."""
        n = len(highs)
        if n < 2:
            return np.array([])

        sar = np.empty(n)
        trend = np.empty(n, dtype=int)  # 1 = uptrend, -1 = downtrend
        af = np.empty(n)

        # Initialize
        trend[0] = 1
        sar[0] = lows[0]
        af[0] = af_step
        ep = highs[0]

        for i in range(1, n):
            # Calculate SAR
            sar[i] = sar[i - 1] + af[i - 1] * (ep - sar[i - 1])

            if trend[i - 1] == 1:  # Uptrend
                sar[i] = min(sar[i], lows[i - 1])
                if i >= 2:
                    sar[i] = min(sar[i], lows[i - 2])

                if lows[i] < sar[i]:
                    # Trend reversal to downtrend
                    trend[i] = -1
                    sar[i] = ep
                    ep = lows[i]
                    af[i] = af_step
                else:
                    trend[i] = 1
                    if highs[i] > ep:
                        ep = highs[i]
                        af[i] = min(af[i - 1] + af_step, af_max)
                    else:
                        af[i] = af[i - 1]

            else:  # Downtrend
                sar[i] = max(sar[i], highs[i - 1])
                if i >= 2:
                    sar[i] = max(sar[i], highs[i - 2])

                if highs[i] > sar[i]:
                    # Trend reversal to uptrend
                    trend[i] = 1
                    sar[i] = ep
                    ep = highs[i]
                    af[i] = af_step
                else:
                    trend[i] = -1
                    if lows[i] < ep:
                        ep = lows[i]
                        af[i] = min(af[i - 1] + af_step, af_max)
                    else:
                        af[i] = af[i - 1]

        return sar

    # ─── VWAP ──────────────────────────────────────────────────────────

    @staticmethod
    def vwap(
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        volumes: np.ndarray,
    ) -> np.ndarray:
        """Volume-Weighted Average Price."""
        typical_price = (highs + lows + closes) / 3.0
        cum_tp_vol = np.cumsum(typical_price * volumes)
        cum_vol = np.cumsum(volumes)

        with np.errstate(divide='ignore', invalid='ignore'):
            result = np.where(cum_vol != 0, cum_tp_vol / cum_vol, typical_price)

        return result

    # ─── Support / Resistance ──────────────────────────────────────────

    @staticmethod
    def pivot_points(high: float, low: float, close: float) -> dict:
        """Classic Pivot Points."""
        pivot = (high + low + close) / 3.0
        return {
            "pivot": pivot,
            "r1": 2 * pivot - low,
            "r2": pivot + (high - low),
            "r3": high + 2 * (pivot - low),
            "s1": 2 * pivot - high,
            "s2": pivot - (high - low),
            "s3": low - 2 * (high - pivot),
        }

    # ─── Comprehensive Analysis ────────────────────────────────────────

    @classmethod
    def full_analysis(cls, candles: list) -> dict:
        """
        Compute all indicators at once for a candle dataset.

        Returns dict with all indicator arrays keyed by name.
        """
        if len(candles) < 50:
            return {}

        c = cls.closes(candles)
        h = cls.highs(candles)
        l = cls.lows(candles)
        o = cls.opens(candles)
        v = cls.ticks(candles)

        result = {
            # Moving averages
            "sma_5": cls.sma(c, 5),
            "sma_10": cls.sma(c, 10),
            "sma_20": cls.sma(c, 20),
            "sma_50": cls.sma(c, 50),
            "sma_100": cls.sma(c, 100),
            "sma_200": cls.sma(c, 200),
            "ema_5": cls.ema(c, 5),
            "ema_9": cls.ema(c, 9),
            "ema_12": cls.ema(c, 12),
            "ema_20": cls.ema(c, 20),
            "ema_26": cls.ema(c, 26),
            "ema_50": cls.ema(c, 50),
            "ema_200": cls.ema(c, 200),
            "wma_20": cls.wma(c, 20),

            # Oscillators
            "rsi_7": cls.rsi(c, 7),
            "rsi_14": cls.rsi(c, 14),
            "rsi_21": cls.rsi(c, 21),

            # MACD
            "macd_line": None,
            "macd_signal": None,
            "macd_histogram": None,

            # Bollinger Bands
            "bb_upper": None,
            "bb_middle": None,
            "bb_lower": None,

            # Stochastic
            "stoch_k": None,
            "stoch_d": None,

            # ATR
            "atr_14": cls.atr(h, l, c, 14),

            # ADX
            "adx_14": cls.adx(h, l, c, 14),

            # SAR
            "parabolic_sar": cls.parabolic_sar(h, l),

            # VWAP
            "vwap": cls.vwap(h, l, c, v),

            # Ichimoku
            "ichimoku": cls.ichimoku(h, l, c),
        }

        # MACD
        macd_line, macd_signal, macd_hist = cls.macd(c)
        result["macd_line"] = macd_line
        result["macd_signal"] = macd_signal
        result["macd_histogram"] = macd_hist

        # Bollinger Bands
        bb_upper, bb_middle, bb_lower = cls.bollinger_bands(c)
        result["bb_upper"] = bb_upper
        result["bb_middle"] = bb_middle
        result["bb_lower"] = bb_lower

        # Stochastic
        stoch_k, stoch_d = cls.stochastic(h, l, c)
        result["stoch_k"] = stoch_k
        result["stoch_d"] = stoch_d

        return result
