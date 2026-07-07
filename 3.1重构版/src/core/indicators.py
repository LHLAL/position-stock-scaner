"""技术指标计算 —— 纯函数模块（无副作用、可独立单测）

v1.3 拆分：analyzer.py 上帝类拆出来的纯计算层
"""
from __future__ import annotations
import numpy as np
from typing import Any, Dict, Optional


# ── 基础工具 ────────────────────────────────────
def sma(data, window: int):
    """简单移动平均"""
    arr = np.array(data, dtype=float)
    result = np.full_like(arr, np.nan)
    for i in range(len(arr)):
        if i >= window - 1:
            result[i] = np.mean(arr[i - window + 1:i + 1])
    return result


def ema(data, window: int):
    """指数移动平均"""
    arr = np.array(data, dtype=float)
    result = np.full_like(arr, np.nan)
    multiplier = 2 / (window + 1)
    result[0] = arr[0]
    for i in range(1, len(arr)):
        result[i] = (arr[i] - result[i - 1]) * multiplier + result[i - 1]
    return result


# ── 趋势类 ──────────────────────────────────────
def calc_rsi(closes, period: int = 14):
    arr = np.array(closes, dtype=float)
    if len(arr) <= period:
        return np.full_like(arr, 50.0)
    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    rsi = np.full_like(arr, 50.0)
    avg_gain = np.mean(gains[:period]) if len(gains) >= period else 0
    avg_loss = np.mean(losses[:period]) if len(losses) >= period else 0.001
    rs = avg_gain / avg_loss if avg_loss else 1
    rsi[period] = 100 - (100 / (1 + rs))
    for i in range(range_to_start := period + 1, len(arr)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i - 1]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i - 1]) / period
        rs = avg_gain / avg_loss if avg_loss else 1
        rsi[i] = 100 - (100 / (1 + rs))
    return rsi


def calc_macd(closes, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD 线、信号线、柱状图"""
    arr = np.array(closes, dtype=float)
    ema_fast = ema(arr, fast)
    ema_slow = ema(arr, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calc_ma_biass(closes, period: int = 5):
    """乖离率 (BIAS)"""
    c = np.array(closes, dtype=float)
    if len(c) < period:
        return 0.0
    ma = np.mean(c[-period:])
    if ma == 0:
        return 0.0
    return float((c[-1] - ma) / ma * 100)


def calc_histogram_slope(histogram, n: int = 5):
    """MACD 柱状图斜率"""
    h = np.array(histogram, dtype=float)
    if len(h) < n + 1:
        return 0.0
    recent = h[-n:]
    earlier = h[-n * 2:-n]
    if len(earlier) == 0:
        return 0.0
    slope = (np.mean(recent) - np.mean(earlier)) / (np.abs(np.mean(earlier)) + 1e-9)
    return float(slope)


# ── 摆动类 ──────────────────────────────────────
def calc_kdj(highs, lows, closes, period: int = 9):
    """KDJ 指标"""
    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)
    c = np.array(closes, dtype=float)
    hn = np.full_like(c, np.nan)
    ln = np.full_like(c, np.nan)
    for i in range(len(c)):
        start = max(0, i - period + 1)
        hn[i] = np.max(h[start:i + 1])
        ln[i] = np.min(l[start:i + 1])
    rsv = np.where((hn - ln) != 0, (c - ln) / (hn - ln) * 100, 50)
    k = np.full_like(c, 50.0)
    d = np.full_like(c, 50.0)
    for i in range(1, len(c)):
        k[i] = 2 / 3 * k[i - 1] + 1 / 3 * rsv[i]
        d[i] = 2 / 3 * d[i - 1] + 1 / 3 * k[i]
    j = 3 * k - 2 * d
    return float(k[-1]), float(d[-1]), float(j[-1])


def calc_cci(highs, lows, closes, period: int = 20):
    """CCI 顺势指标"""
    if len(closes) < period:
        return 0.0
    h = np.array(highs[-period:], dtype=float)
    l = np.array(lows[-period:], dtype=float)
    c = np.array(closes[-period:], dtype=float)
    tp = (h + l + c) / 3
    ma_tp = np.mean(tp)
    md = np.mean(np.abs(tp - ma_tp))
    if md == 0:
        return 0.0
    return (tp[-1] - ma_tp) / (0.015 * md)


def calc_williams_r(highs, lows, closes, period: int = 14):
    """威廉指标 %R"""
    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)
    c = np.array(closes, dtype=float)
    if len(c) < period:
        return -50.0
    period_high = np.max(h[-period:])
    period_low = np.min(l[-period:])
    if period_high == period_low:
        return -50.0
    return float((period_high - c[-1]) / (period_high - period_low) * -100)


# ── 通道/波动 ───────────────────────────────────
def calc_bollinger_position(closes, ma20, std_mult: float = 2):
    """布林带位置 (0-1, 0=下轨, 1=上轨)"""
    c = np.array(closes, dtype=float)
    m20 = np.atleast_1d(np.array(ma20, dtype=float))
    std = np.full_like(c, np.nan)
    for i in range(len(c)):
        if i >= 19:
            std[i] = np.std(c[i - 19:i + 1])
    if np.isnan(std[-1]) or m20[-1] == 0:
        return 0.5
    upper = m20[-1] + std_mult * std[-1]
    lower = m20[-1] - std_mult * std[-1]
    if upper == lower:
        return 0.5
    return (c[-1] - lower) / (upper - lower)


def calc_atr(highs, lows, closes, period: int = 14):
    """平均真实波幅"""
    if len(closes) < period + 1:
        return 0.0
    h = np.array(highs[-(period + 1):], dtype=float)
    l = np.array(lows[-(period + 1):], dtype=float)
    c = np.array(closes[-(period + 1):], dtype=float)
    tr = np.maximum(h[1:] - l[1:],
                    np.maximum(np.abs(h[1:] - c[:-1]), np.abs(l[1:] - c[:-1])))
    return float(np.mean(tr))


def calc_adx(highs, lows, closes, period: int = 14):
    """平均趋向指数"""
    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)
    c = np.array(closes, dtype=float)
    if len(c) < period + 1:
        return 0.0
    up_move = h[1:] - h[:-1]
    down_move = l[:-1] - l[1:]
    plus_dm = np.where(up_move > down_move, up_move, 0.0)
    minus_dm = np.where(down_move > up_move, down_move, 0.0)
    tr_list = np.maximum(h[1:] - l[1:], np.abs(c[1:] - c[:-1]))
    if len(tr_list) < period:
        return 0.0
    atr_smooth = float(np.mean(tr_list[:period]))
    plus_dm_smooth = float(np.mean(plus_dm[:period]))
    minus_dm_smooth = float(np.mean(minus_dm[:period]))
    for i in range(period, len(tr_list)):
        atr_smooth = (atr_smooth * (period - 1) + tr_list[i]) / period
        plus_dm_smooth = (plus_dm_smooth * (period - 1) + plus_dm[i]) / period
        minus_dm_smooth = (minus_dm_smooth * (period - 1) + minus_dm[i]) / period
    plus_di = (plus_dm_smooth / atr_smooth * 100) if atr_smooth > 0 else 0
    minus_di = (minus_dm_smooth / atr_smooth * 100) if atr_smooth > 0 else 0
    dx = (abs(plus_di - minus_di) / (plus_di + minus_di) * 100) if (plus_di + minus_di) > 0 else 0
    return float(np.mean([dx] * period))


# ── 量能类 ─────────────────────────────────────
def calc_vr(closes, volumes, period: int = 26):
    """成交量比率 VR"""
    if len(closes) < period:
        return 100.0
    c = np.array(closes[-period:], dtype=float)
    v = np.array(volumes[-period:], dtype=float)
    if len(c) < 2:
        return 100.0
    deltas = np.diff(c)
    up_vol = np.sum(v[1:][deltas >= 0])
    down_vol = np.sum(v[1:][deltas < 0])
    if down_vol == 0:
        return 200.0
    return up_vol / down_vol * 100


def calc_obv(closes, volumes):
    """能量潮指标 OBV"""
    c = np.array(closes, dtype=float)
    v = np.array(volumes, dtype=float)
    if len(c) < 2:
        return 0.0
    obv = np.zeros(len(c))
    obv[0] = v[0]
    deltas = np.diff(c)
    for i in range(1, len(c)):
        if deltas[i - 1] > 0:
            obv[i] = obv[i - 1] + v[i]
        elif deltas[i - 1] < 0:
            obv[i] = obv[i - 1] - v[i]
        else:
            obv[i] = obv[i - 1]
    return float(obv[-1])


def calc_obv_signal(closes, volumes, period: int = 20):
    """OBV 顶底背离信号"""
    c = np.array(closes, dtype=float)
    v = np.array(volumes, dtype=float)
    if len(c) < period + 1:
        return "数据不足"
    obv_vals = np.zeros(len(c))
    obv_vals[0] = v[0]
    deltas = np.diff(c)
    for i in range(1, len(c)):
        if deltas[i - 1] > 0:
            obv_vals[i] = obv_vals[i - 1] + v[i]
        elif deltas[i - 1] < 0:
            obv_vals[i] = obv_vals[i - 1] - v[i]
        else:
            obv_vals[i] = obv_vals[i - 1]
    ma_obv = np.convolve(obv_vals, np.ones(period) / period, mode='valid')
    if len(ma_obv) < 2:
        return "数据不足"
    cur_obv, cur_ma, prev_ma = obv_vals[-1], ma_obv[-1], ma_obv[-2] if len(ma_obv) > 1 else cur_ma
    price_cur = c[-1]
    price_prev = c[-period] if len(c) > period else c[0]
    if cur_obv > cur_ma and price_cur <= price_prev:
        return "顶背离"
    elif cur_obv < cur_ma and price_cur >= price_prev:
        return "底背离"
    elif cur_obv > cur_ma:
        return "量价配合"
    return "中性"


def calc_cmf(closes, highs, lows, volumes, period: int = 20):
    """资金流量指标 CMF"""
    c = np.array(closes, dtype=float)
    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)
    v = np.array(volumes, dtype=float)
    if len(c) < period + 1:
        return 0.0
    hl_diff = h - l
    mf_multiplier = np.where(hl_diff != 0, ((c - l) - (h - c)) / hl_diff, 0.0)
    mf_volume = mf_multiplier * v
    denom = np.sum(v[-period:])
    return float(np.sum(mf_volume[-period:]) / denom) if denom > 0 else 0.0


# ── 趋势判断辅助 ───────────────────────────────
def judge_ma_trend(price: float, ma5: float, ma10: float, ma20: float) -> str:
    """均线排列判断"""
    if price > ma5 > ma10 > ma20:
        return "多头排列"
    if price < ma5 < ma10 < ma20:
        return "空头排列"
    return "震荡整理"


def judge_volume(volume: int, avg_volume: int) -> str:
    """量能状态判断"""
    if volume > avg_volume * 1.5:
        return "放量"
    if volume < avg_volume * 0.5:
        return "缩量"
    return "量能平稳"


# ── 默认值模板（缺数据时返回）───────────────────
def default_technical() -> Dict[str, Any]:
    return {
        "ma_trend": "数据不足",
        "rsi": 50.0,
        "macd_signal": "数据不足",
        "volume_status": "数据不足",
        "kdj": {"k": 50.0, "d": 50.0, "j": 50.0},
        "bollinger_position": 0.5,
        "vr": 100.0,
        "cci": 0.0,
        "trix": 0.0,
        "atr": 0.0,
        "obv": 0.0,
        "obv_signal": "数据不足",
        "pdi": 0.0, "mdi": 0.0, "adx": 0.0,
        "bias6": 0.0, "wr10": 0.0,
        "mtm": 0.0, "roc": 0.0, "psy": 50.0,
    }
