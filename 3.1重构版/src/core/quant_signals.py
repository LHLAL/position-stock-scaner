"""四层量化信号 L0/L1/L2/L3

v3.1-fix: 之前 signals.py 只含市场信号（hot/fund/dragon），L0-L3 在 README 宣传过但没实现。
本模块为前端 signals.js 提供 {L0,L1,L2,L3} 结构，每层返回:
    {
        "value": float,           # -1..+1，看多/看空强度
        "history": list[float],   # 最近 30 个值（sparkline 用）
        "explain": {meaning, action},
    }
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

from src.core import indicators as ind
from src.core.chanlun import analyze_chanlun


SIGNAL_HISTORY_LEN = 30


def _empty_layer(reason: str = "数据不足") -> Dict[str, Any]:
    return {
        "value": 0.0,
        "history": [0.0] * SIGNAL_HISTORY_LEN,
        "explain": {"meaning": reason, "action": "建议观望"},
    }


def _clamp(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _safe_rsi(closes, period: int = 14) -> np.ndarray:
    try:
        return ind.calc_rsi(closes, period)
    except Exception:
        return np.full(len(closes), 50.0)


def _safe_macd(closes):
    try:
        return ind.calc_macd(closes)
    except Exception:
        n = len(closes)
        return np.zeros(n), np.zeros(n), np.zeros(n)


def _safe_kdj(highs, lows, closes, period: int = 9):
    try:
        return ind.calc_kdj(highs, lows, closes, period)
    except Exception:
        return 50.0, 50.0, 50.0


def _trend_score(closes) -> float:
    """基于均线排列的趋势分（-1..+1）"""
    if len(closes) < 20:
        return 0.0
    try:
        ma5 = ind.sma(closes, 5)[-1]
        ma10 = ind.sma(closes, 10)[-1]
        ma20 = ind.sma(closes, 20)[-1]
    except Exception:
        return 0.0
    p = float(closes[-1])
    if p > ma5 > ma10 > ma20:
        return 1.0
    if p < ma5 < ma10 < ma20:
        return -1.0
    if p > ma20 and ma5 > ma10:
        return 0.4
    if p < ma20 and ma5 < ma10:
        return -0.4
    return 0.0


def _ma_diff_pct(closes) -> float:
    """价格 vs MA20 的偏离度（-1..+1 截断）"""
    if len(closes) < 20:
        return 0.0
    try:
        ma20 = ind.sma(closes, 20)[-1]
    except Exception:
        return 0.0
    if not ma20:
        return 0.0
    pct = (float(closes[-1]) - ma20) / ma20
    return _clamp(pct * 20)  # 5% 偏离 = 满格


def _macd_value(closes) -> float:
    """MACD 柱图归一化（-1..+1）"""
    if len(closes) < 30:
        return 0.0
    _, _, hist = _safe_macd(closes)
    h = float(hist[-1]) if len(hist) else 0.0
    return _clamp(h * 50)


def _rsi_value(closes) -> float:
    if len(closes) < 15:
        return 0.0
    rsi = float(_safe_rsi(closes)[-1])
    if rsi < 30:
        return _clamp((30 - rsi) / 30)  # 超卖 → 正分（看多）
    if rsi > 70:
        return -_clamp((rsi - 70) / 30)  # 超买 → 负分
    return _clamp((rsi - 50) / 20)


def _kline_to_indicators(closes, highs, lows) -> Dict[str, float]:
    """把多维指标合成单一信号分"""
    s_trend = _trend_score(closes)
    s_ma = _ma_diff_pct(closes)
    s_macd = _macd_value(closes)
    s_rsi = _rsi_value(closes)
    return {
        "trend": s_trend,
        "ma_diff": s_ma,
        "macd": s_macd,
        "rsi": s_rsi,
    }


def _build_history_from_indicators(closes, highs, lows, window: int = 60) -> List[float]:
    """从 K 线逐根重算指标 → 生成 30 点历史 sparkline"""
    if len(closes) < 30:
        return [0.0] * SIGNAL_HISTORY_LEN
    end = len(closes)
    start = max(30, end - window)
    history: List[float] = []
    for i in range(start, end + 1):
        sub_c = closes[:i]
        sub_h = highs[:i] if highs is not None else sub_c
        sub_l = lows[:i] if lows is not None else sub_c
        comp = _kline_to_indicators(sub_c, sub_h, sub_l)
        score = (
            comp["trend"] * 0.4
            + comp["ma_diff"] * 0.2
            + comp["macd"] * 0.25
            + comp["rsi"] * 0.15
        )
        history.append(round(_clamp(score), 3))
    if len(history) >= SIGNAL_HISTORY_LEN:
        return history[-SIGNAL_HISTORY_LEN:]
    return [0.0] * (SIGNAL_HISTORY_LEN - len(history)) + history


def _layer_from_components(components: Dict[str, float], history: List[float],
                           meaning: str, action: str) -> Dict[str, Any]:
    score = (
        components["trend"] * 0.4
        + components["ma_diff"] * 0.2
        + components["macd"] * 0.25
        + components["rsi"] * 0.15
    )
    value = round(_clamp(score), 3)
    return {
        "value": value,
        "history": history,
        "explain": {"meaning": meaning, "action": action},
    }


def compute_l0(minute_df: Optional[pd.DataFrame]) -> Dict[str, Any]:
    """L0 极短线：5 分钟 K 线（最敏感，反应当日资金动向）"""
    if minute_df is None or minute_df.empty or len(minute_df) < 20:
        return _empty_layer("分钟 K 数据不足")
    closes, highs, lows = _extract_ohlc(minute_df)
    comp = _kline_to_indicators(closes, highs, lows)
    history = _build_history_from_indicators(closes, highs, lows, window=80)
    if comp["trend"] > 0.3:
        meaning = "5 分钟均线多头排列，资金短期偏多"
        action = "可短线跟进，注意 30 分钟压力"
    elif comp["trend"] < -0.3:
        meaning = "5 分钟均线空头排列，资金短期偏空"
        action = "观望为主，等反弹再做决策"
    else:
        meaning = "5 分钟级别震荡整理"
        action = "等方向明确再入场"
    return _layer_from_components(comp, history, meaning, action)


def compute_l1(daily_df: Optional[pd.DataFrame]) -> Dict[str, Any]:
    """L1 短期：日 K 线（最常用，捕捉主趋势）"""
    if daily_df is None or daily_df.empty or len(daily_df) < 20:
        return _empty_layer("日 K 数据不足")
    closes, highs, lows = _extract_ohlc(daily_df)
    comp = _kline_to_indicators(closes, highs, lows)
    history = _build_history_from_indicators(closes, highs, lows, window=60)
    if comp["trend"] > 0.5:
        meaning = "日 K 均线多头排列，趋势向上"
        action = "沿 MA5 持多，跌破 MA10 减仓"
    elif comp["trend"] < -0.5:
        meaning = "日 K 均线空头排列，趋势向下"
        action = "不接飞刀，等 MA5 拐头"
    else:
        if comp["macd"] > 0.2:
            meaning = "日 K 震荡但 MACD 偏多"
            action = "小仓位试多，止损 MA20"
        elif comp["macd"] < -0.2:
            meaning = "日 K 震荡但 MACD 偏空"
            action = "减仓为主"
        else:
            meaning = "日 K 级别方向不明"
            action = "观望等突破"
    return _layer_from_components(comp, history, meaning, action)


def compute_l2(weekly_df: Optional[pd.DataFrame]) -> Dict[str, Any]:
    """L2 中期：周 K 线（看中期方向）"""
    if weekly_df is None or weekly_df.empty or len(weekly_df) < 10:
        return _empty_layer("周 K 数据不足")
    closes, highs, lows = _extract_ohlc(weekly_df)
    comp = _kline_to_indicators(closes, highs, lows)
    history = _build_history_from_indicators(closes, highs, lows, window=40)
    if comp["trend"] > 0.5:
        meaning = "周 K 均线多头排列，中期向上"
        action = "中线持有，回调到 MA20 可加仓"
    elif comp["trend"] < -0.5:
        meaning = "周 K 均线空头排列，中期向下"
        action = "中线规避，等周线企稳"
    else:
        meaning = "周 K 级别震荡"
        action = "中线观望"
    return _layer_from_components(comp, history, meaning, action)


def compute_l3(daily_df: Optional[pd.DataFrame]) -> Dict[str, Any]:
    """L3 长线：缠论结构（最稳定，反映多空力量格局）"""
    if daily_df is None or daily_df.empty or len(daily_df) < 30:
        return _empty_layer("K 线数据不足，无法计算缠论")
    try:
        ch = analyze_chanlun(daily_df)
    except Exception:
        return _empty_layer("缠论计算失败")
    if not ch.get('available'):
        return _empty_layer("缠论暂不可用")
    raw = float(ch.get('chanlun_score', 0.0))
    value = _clamp(raw / 2.0)
    trend = ch.get('current_trend', '震荡')
    strength = ch.get('trend_strength', '震荡')
    ma = ch.get('ma_arrangement', '—')
    history = _build_chanlun_history(daily_df, value)
    if value > 0.5:
        meaning = f"缠论{strength}{trend}，{ma}，长线向好"
        action = "长线持有，回调即机会"
    elif value < -0.5:
        meaning = f"缠论{strength}{trend}，{ma}，长线偏空"
        action = "长线规避，等结构修复"
    else:
        meaning = f"缠论{trend}（{strength}），{ma}"
        action = "长线中性，等方向确认"
    return {
        "value": round(value, 3),
        "history": history,
        "explain": {"meaning": meaning, "action": action},
    }


_OHLC_MAP = {
    'open': '开盘', 'close': '收盘', 'high': '最高', 'low': '最低',
    '开盘': '开盘', '收盘': '收盘', '最高': '最高', '最低': '最低',
}


def _extract_ohlc(df: pd.DataFrame):
    def col(*names):
        for n in names:
            if n in df.columns:
                return n
        return None
    c = col('close', '收盘')
    h = col('high', '最高')
    l = col('low', '最低')
    return (
        df[c].astype(float).values if c else df['收盘'].astype(float).values,
        df[h].astype(float).values if h else df['最高'].astype(float).values,
        df[l].astype(float).values if l else df['最低'].astype(float).values,
    )


def _build_chanlun_history(daily_df: pd.DataFrame, current_value: float) -> List[float]:
    """缠论 L3 历史：用滑动窗口重算 chanlun_score 得到时间序列"""
    n = len(daily_df)
    if n < 60:
        return [current_value] * SIGNAL_HISTORY_LEN
    window = 30
    step = max(1, (n - 60) // SIGNAL_HISTORY_LEN)
    history: List[float] = []
    for end in range(60, n + 1, step):
        try:
            ch = analyze_chanlun(daily_df.iloc[:end])
            v = float(ch.get('chanlun_score', 0.0)) / 2.0
            history.append(round(_clamp(v), 3))
        except Exception:
            history.append(0.0)
    while len(history) < SIGNAL_HISTORY_LEN:
        history.insert(0, 0.0)
    return history[-SIGNAL_HISTORY_LEN:]


def compute_four_layer(daily_df: Optional[pd.DataFrame],
                       weekly_df: Optional[pd.DataFrame],
                       minute_df: Optional[pd.DataFrame]) -> Dict[str, Dict[str, Any]]:
    """一次性计算 L0/L1/L2/L3 四层（供 /api/indicators 调用）

    输入列名归一化（open/close/high/low ↔ 开盘/收盘/最高/最低）
    让 L0/L1/L2（自实现指标）和 L3（依赖 chanlun）共享同一份数据。
    """
    return {
        "L0": compute_l0(_ensure_cn_columns(minute_df)),
        "L1": compute_l1(_ensure_cn_columns(daily_df)),
        "L2": compute_l2(_ensure_cn_columns(weekly_df)),
        "L3": compute_l3(_ensure_cn_columns(daily_df)),
    }


_CN_RENAME = {
    'date': '日期', 'open': '开盘', 'close': '收盘',
    'high': '最高', 'low': '最低', 'volume': '成交量',
}


def _ensure_cn_columns(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """把英文列名转成中文（已是中文则原样返回）"""
    if df is None or df.empty:
        return df
    if '收盘' in df.columns:
        return df
    return df.rename(columns=_CN_RENAME)
