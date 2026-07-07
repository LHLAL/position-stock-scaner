"""缠论 (Chanlun Theory) 技术分析模块 — 实用版

核心思想：走势必完美 — 任何级别都有上涨/下跌/震荡三种状态

简化实现（保留核心逻辑，适用于A股等小波动市场）：
- 分型识别（顶分型/底分型）
- 均线走势判断（多/空头排列 + 支撑阻力）
- 背驰判断（基于波段力度对比）
- 三类买卖点（简化版）
"""
from typing import Optional, List, Dict, Any
import numpy as np
import pandas as pd


def _sma(data, window):
    arr = np.array(data, dtype=float)
    result = np.full_like(arr, np.nan, dtype=float)
    for i in range(len(arr)):
        if i >= window - 1:
            result[i] = np.mean(arr[i - window + 1:i + 1])
    return result


def _calc_rsi(closes, period=14):
    arr = np.array(closes, dtype=float)
    deltas = np.diff(arr)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    rsi = np.full_like(arr, 50.0)
    avg_gain = np.mean(gains[:period]) if len(gains) >= period else 0.001
    avg_loss = np.mean(losses[:period]) if len(losses) >= period else 0.001
    rs = avg_gain / avg_loss if avg_loss else 1.0
    rsi[period] = 100 - (100 / (1 + rs))
    for i in range(period + 1, len(arr)):
        avg_gain = ((avg_gain * (period - 1)) + gains[i - 1]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[i - 1]) / period
        rs = avg_gain / avg_loss if avg_loss else 1.0
        rsi[i] = 100 - (100 / (1 + rs))
    return rsi


def _detect_fenxing_type(highs, lows, lookback=5):
    """识别最近的分型"""
    if len(highs) < lookback + 3:
        return None, None

    h = highs[-(lookback + 3):]
    l = lows[-(lookback + 3):]
    n = len(h)

    if h[n-3] == max(h[n-3:n]) and h[n-4] < h[n-3] and h[n-2] <= h[n-3]:
        return '顶分型', float(h[n-3])
    if l[n-3] == min(l[n-3:n]) and l[n-4] > l[n-3] and l[n-2] >= l[n-3]:
        return '底分型', float(l[n-3])

    return None, None


def _detect_beichi(closes, volumes):
    """背驰判断：比较最近两个同向波段力度"""
    if len(closes) < 30:
        return []

    c = np.array(closes, dtype=float)
    ma5 = _sma(c, 5)

    peaks_idx = []
    troughs_idx = []
    for i in range(2, len(c) - 2):
        if (not np.isnan(ma5[i]) and not np.isnan(ma5[i-1])
            and not np.isnan(ma5[i+1]) and not np.isnan(ma5[i+2])):
            if ma5[i-1] < ma5[i] > ma5[i+1] and ma5[i] > ma5[i-2] and ma5[i] > ma5[i+2]:
                peaks_idx.append(i)
            elif ma5[i-1] > ma5[i] < ma5[i+1] and ma5[i] < ma5[i-2] and ma5[i] < ma5[i+2]:
                troughs_idx.append(i)

    if len(peaks_idx) < 2 or len(troughs_idx) < 2:
        return []

    beichi_list = []

    # 最近峰谷关系
    last_peak = peaks_idx[-1]
    last_trough = troughs_idx[-1]

    if last_peak > last_trough:
        # 刚完成上涨波段 → 检查是否顶背驰
        prev_trough = None
        for t in reversed(troughs_idx[:-1]):
            if t < last_trough:
                prev_trough = t
                break

        if prev_trough is not None and last_trough > prev_trough:
            prev_amp = abs(c[prev_trough] - c[last_trough]) / c[last_trough] * 100
            curr_amp = abs(c[last_peak] - c[last_trough]) / c[last_trough] * 100
            if prev_amp > 0.3 and curr_amp > 0.3:
                ratio = curr_amp / prev_amp
                if ratio < 0.8:
                    beichi_list.append({
                        'type': '顶背驰',
                        'description': f'上涨力度仅上一波{ratio:.0%}，注意见顶风险',
                        'prev_amplitude': round(prev_amp, 2),
                        'curr_amplitude': round(curr_amp, 2),
                        'ratio': round(ratio, 2),
                    })
    else:
        # 刚完成下跌波段 → 检查是否底背驰
        prev_peak = None
        for p in reversed(peaks_idx[:-1]):
            if p < last_peak:
                prev_peak = p
                break

        if prev_peak is not None and last_peak > prev_peak:
            prev_amp = abs(c[prev_peak] - c[last_peak]) / c[last_peak] * 100
            curr_amp = abs(c[last_trough] - c[last_peak]) / c[last_peak] * 100
            if prev_amp > 0.3 and curr_amp > 0.3:
                ratio = curr_amp / prev_amp
                if ratio < 0.8:
                    beichi_list.append({
                        'type': '底背驰',
                        'description': f'下跌力度仅上一波{ratio:.0%}，关注见底机会',
                        'prev_amplitude': round(prev_amp, 2),
                        'curr_amplitude': round(curr_amp, 2),
                        'ratio': round(ratio, 2),
                    })

    return beichi_list


def _generate_buy_sell_points(closes, highs, lows, ma5, ma10, ma20,
                            beichi_list, current_price,
                            trend_label, ma_arrangement) -> Dict[str, Any]:
    """生成三类买卖点"""
    result = {'buy_points': [], 'sell_points': [], 'operation_advice': ''}

    if current_price <= 0:
        return result

    c = np.array(closes, dtype=float)
    h = np.array(highs, dtype=float)
    l = np.array(lows, dtype=float)

    # === 第一类：背驰转折点 ===
    for bc in beichi_list:
        if bc['type'] == '底背驰':
            result['buy_points'].append({
                'type': '第一类买点', 'level': '专业级',
                'condition': bc['description'],
                'risk': '可能继续下跌，需严格止损', 'target_return': '>15%',
            })
        elif bc['type'] == '顶背驰':
            result['sell_points'].append({
                'type': '第一类卖点', 'level': '专业级',
                'condition': bc['description'],
                'risk': '可能继续上涨，踏空风险', 'target_return': '>10%',
            })

    # === 第二类：均线支撑/压力 ===
    if ma_arrangement == '多头排列':
        for ma_val, ma_name in [(ma5, 'MA5'), (ma10, 'MA10')]:
            if not np.isnan(ma_val[-1]) and ma_val[-1] > 0:
                result['buy_points'].append({
                    'type': '第二类买点', 'level': '稳健型',
                    'price': round(float(ma_val[-1]), 2),
                    'condition': f'回调至{ma_name}获得支撑（多头排列）',
                    'risk': '中等，需价格站上MA5确认', 'target_return': '8-15%',
                })
    elif ma_arrangement == '空头排列':
        for ma_val, ma_name in [(ma5, 'MA5'), (ma10, 'MA10')]:
            if not np.isnan(ma_val[-1]) and ma_val[-1] > 0:
                result['sell_points'].append({
                    'type': '第二类卖点', 'level': '稳健型',
                    'price': round(float(ma_val[-1]), 2),
                    'condition': f'反弹至{ma_name}受压（空头排列）',
                    'risk': '中等，需价格跌破MA5确认', 'target_return': '8-12%',
                })
    elif ma_arrangement == '混乱' and not np.isnan(ma20[-1]):
        if current_price > ma20[-1]:
            result['buy_points'].append({
                'type': '第二类买点', 'level': '稳健型',
                'price': round(float(ma20[-1]), 2),
                'condition': '价格站稳MA20（震荡格局）',
                'risk': '低', 'target_return': '5-10%',
            })
        else:
            result['sell_points'].append({
                'type': '第二类卖点', 'level': '稳健型',
                'price': round(float(ma20[-1]), 2),
                'condition': '价格跌破MA20（震荡格局）',
                'risk': '低', 'target_return': '5-10%',
            })

    # === 第三类：突破近期高低点 ===
    if len(c) >= 20:
        recent_high = float(np.max(h[-20:]))
        recent_low = float(np.min(l[-20:]))

        if current_price > recent_high * 0.98 and ma_arrangement == '多头排列':
            result['buy_points'].append({
                'type': '第三类买点', 'level': '确认型',
                'price': round(float(current_price), 2),
                'break_level': round(recent_high, 2),
                'condition': f'突破前高{recent_high:.2f}，强势信号',
                'risk': '低，确认突破有效性（需放量）', 'target_return': '20%+',
            })
        elif current_price < recent_low * 1.02 and ma_arrangement == '空头排列':
            result['sell_points'].append({
                'type': '第三类卖点', 'level': '确认型',
                'price': round(float(current_price), 2),
                'break_level': round(recent_low, 2),
                'condition': f'跌破前低{recent_low:.2f}，弱势信号',
                'risk': '低，及时止损', 'target_return': '15%+',
            })

    # === 综合建议 ===
    buy_pts = result['buy_points']
    sell_pts = result['sell_points']
    if not buy_pts and not sell_pts:
        result['operation_advice'] = "趋势不明，等待方向确认"
    elif buy_pts and sell_pts:
        result['operation_advice'] = "多空信号并存，建议观望等待确认"
    elif buy_pts:
        best = min(buy_pts, key=lambda x: {'专业级': 1, '确认型': 2, '稳健型': 3}.get(x.get('level', ''), 4))
        result['operation_advice'] = f"建议买入：{best['type']}（{best['condition']}）"
    elif sell_pts:
        best = min(sell_pts, key=lambda x: {'专业级': 1, '确认型': 2, '稳健型': 3}.get(x.get('level', ''), 4))
        result['operation_advice'] = f"建议卖出：{best['type']}（{best['condition']}）"

    return result


def analyze_chanlun(df: pd.DataFrame, min_bi_bars: int = 5) -> Dict[str, Any]:
    """缠论综合分析入口（实用版）"""
    if df is None or len(df) < 30:
        return {'available': False, 'summary': '数据不足（需要30根以上K线）', 'chanlun_score': 0.0}

    try:
        closes = df['收盘'].values.astype(float)
        highs = df['最高'].values.astype(float)
        lows = df['最低'].values.astype(float)
        volumes = df['成交量'].values.astype(float)
    except Exception:
        return {'available': False, 'summary': '数据格式错误', 'chanlun_score': 0.0}

    current_price = float(closes[-1])

    ma5 = _sma(closes, 5)
    ma10 = _sma(closes, 10)
    ma20 = _sma(closes, 20)

    m5, m10, m20 = ma5[-1], ma10[-1], ma20[-1]
    if np.isnan(m5) or np.isnan(m10) or np.isnan(m20):
        return {'available': False, 'summary': '均线数据不足', 'chanlun_score': 0.0}

    # 均线排列
    if m5 > m10 > m20:
        ma_arrangement = '多头排列'
    elif m5 < m10 < m20:
        ma_arrangement = '空头排列'
    else:
        ma_arrangement = '混乱'

    # 趋势
    trend_label = {'多头排列': '上涨', '空头排列': '下跌', '混乱': '震荡'}[ma_arrangement]
    spread = abs(m20 - m5) / m20 * 100
    strength_label = '强势' if spread > 3 else '弱势'

    # 评分
    base_score = 0.0
    if ma_arrangement == '多头排列':
        base_score = 1.0 + (0.5 if spread > 3 else 0.0)
    elif ma_arrangement == '空头排列':
        base_score = -1.0 - (0.5 if spread > 3 else 0.0)

    # 分型
    fenxing_type, fenxing_price = _detect_fenxing_type(highs, lows)
    if fenxing_type == '顶分型':
        base_score -= 0.3
        fenxing_desc = f'顶分型({fenxing_price:.2f})注意回调'
    elif fenxing_type == '底分型':
        base_score += 0.3
        fenxing_desc = f'底分型({fenxing_price:.2f})关注反弹'
    else:
        fenxing_desc = '无明显分型'

    base_score = max(-2.0, min(2.0, base_score))

    # 背驰
    beichi_list = _detect_beichi(closes, volumes)
    for bc in beichi_list:
        if bc['type'] == '底背驰':
            base_score += 0.4
        elif bc['type'] == '顶背驰':
            base_score -= 0.4
    base_score = max(-2.0, min(2.0, base_score))

    # 买卖点
    buy_sell = _generate_buy_sell_points(
        closes, highs, lows, ma5, ma10, ma20,
        beichi_list, current_price, trend_label, ma_arrangement
    )

    # MA状态文字
    vs = lambda a, b: '>' if a > b else '<'
    ma_status = f"价格{m5:.2f}{vs(current_price,m5)}MA5; MA5{m5:.2f}{vs(m5,m10)}MA10; MA10{m10:.2f}{vs(m10,m20)}MA20; {ma_arrangement}"

    # summary
    parts = [f"趋势:{trend_label}({strength_label})", f"均线:{ma_arrangement}"]
    parts.append(fenxing_desc)
    if beichi_list:
        parts.append('/'.join(set(bc['type'] for bc in beichi_list)))
    if buy_sell['operation_advice']:
        parts.append(buy_sell['operation_advice'])

    return {
        'available': True,
        'current_trend': trend_label,
        'trend_strength': strength_label,
        'chanlun_score': round(base_score, 2),
        'ma_arrangement': ma_arrangement,
        'ma_status': ma_status,
        'fenxing': fenxing_desc,
        'beichi_list': beichi_list,
        'buy_sell_points': buy_sell,
        'support_resistance': {
            'ma5': round(float(m5), 2),
            'ma10': round(float(m10), 2),
            'ma20': round(float(m20), 2),
            'recent_high': round(float(np.max(highs[-20:])), 2),
            'recent_low': round(float(np.min(lows[-20:])), 2),
        },
        'summary': ' | '.join(parts),
    }


def calculate_chanlun(df: pd.DataFrame, **kwargs) -> Dict[str, Any]:
    return analyze_chanlun(df, **kwargs)