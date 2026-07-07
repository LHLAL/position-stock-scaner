"""技术指标纯函数测试"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '3.1重构版', 'src'))

import numpy as np
from core.indicators import sma, ema, calc_rsi, calc_macd, calc_kdj, calc_bollinger_position


class TestSMA:
    def test_simple(self):
        arr = [1, 2, 3, 4, 5]
        result = sma(arr, 3)
        assert len(result) == 5
        assert np.isnan(result[0])
        assert np.isnan(result[1])
        assert result[2] == 2.0
        assert result[3] == 3.0
        assert result[4] == 4.0

    def test_window_larger_than_array(self):
        arr = [1, 2]
        result = sma(arr, 5)
        assert len(result) == 2
        assert np.isnan(result[0])
        assert np.isnan(result[1])

    def test_empty(self):
        result = sma([], 3)
        assert len(result) == 0


class TestEMA:
    def test_simple(self):
        arr = [1, 2, 3, 4, 5]
        result = ema(arr, 3)
        assert len(result) == 5

    def test_constant(self):
        arr = [5] * 10
        result = ema(arr, 3)
        assert all(abs(v - 5) < 0.001 for v in result)

    def test_short_array(self):
        result = ema([1], 5)
        assert len(result) == 1


class TestRSI:
    def test_normal(self):
        arr = [44, 44.34, 44.09, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
               45.89, 46.03, 45.61, 46.28, 46.28, 46.00, 46.03, 46.41, 46.22, 46.21]
        result = calc_rsi(arr, 14)
        assert len(result) == len(arr)
        assert 0 <= result[-1] <= 100

    def test_short_array(self):
        arr = [1, 2]
        result = calc_rsi(arr, 14)
        assert len(result) == 2
        assert all(v == 50.0 for v in result)

    def test_all_up(self):
        arr = list(range(1, 60))
        result = calc_rsi(arr, 5)
        assert result[-1] >= 50.0

    def test_all_down(self):
        arr = list(range(20, 1, -1))
        result = calc_rsi(arr, 5)
        assert result[-1] < 50

    def test_empty(self):
        result = calc_rsi([], 14)
        assert len(result) == 0


class TestMACD:
    def test_normal(self):
        arr = [10 + np.sin(i * 0.3) * 2 for i in range(50)]
        macd_line, signal_line, hist = calc_macd(arr)
        assert len(macd_line) == len(arr)
        assert len(signal_line) == len(arr)
        assert len(hist) == len(arr)

    def test_short_array(self):
        arr = [1, 2]
        macd_line, signal_line, hist = calc_macd(arr)
        assert len(macd_line) == 2


class TestKDJ:
    def test_normal(self):
        highs = [10 + i * 0.1 for i in range(30)]
        lows = [9 + i * 0.1 for i in range(30)]
        closes = [9.5 + i * 0.1 for i in range(30)]
        k, d, j = calc_kdj(highs, lows, closes)
        assert isinstance(k, float)
        assert isinstance(d, float)
        assert isinstance(j, float)
        assert 0 <= k <= 100
        assert 0 <= d <= 100
        assert 0 <= j <= 100

    def test_short_array(self):
        k, d, j = calc_kdj([1], [1], [1])
        assert isinstance(k, float)
        assert isinstance(d, float)
        assert isinstance(j, float)


class TestBollinger:
    def test_normal(self):
        closes = np.array([10 + np.sin(i * 0.3) * 2 for i in range(30)])
        ma20 = np.array([np.mean(closes[max(0, i-19):i+1]) for i in range(len(closes))])
        position = calc_bollinger_position(closes, ma20, std_mult=2)
        assert isinstance(position, float) or np.isnan(position)

    def test_short_array(self):
        closes = np.array([1.0, 2.0])
        ma20 = np.array([1.0, 2.0])
        position = calc_bollinger_position(closes, ma20)
        assert isinstance(position, float) or np.isnan(position)


class TestRegression:
    """回归测试：确保之前修过的 bug 不再复现"""

    def test_rsi_short_guard(self):
        """calc_rsi 在数组过短时不抛 IndexError"""
        calc_rsi([50.0], 14)

    def test_macd_short_guard(self):
        """calc_macd 在数组过短时不抛异常"""
        calc_macd([50.0])

    def test_kdj_short_guard(self):
        """calc_kdj 在数组过短时不抛异常"""
        calc_kdj([50.0], [49.0], [49.5])

    def test_bollinger_short_guard(self):
        calc_bollinger_position(np.array([50.0]), 50.0)
