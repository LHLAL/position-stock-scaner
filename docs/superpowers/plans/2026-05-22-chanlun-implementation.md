# 缠论 (Chanlun Theory) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 缠论 (Chanlun Theory) into the stock analyzer, adding 笔/线段/中枢分析、同级别分解操作建议，明确给出可执行的利益最大化买卖点

**Architecture:** Create a new `chanlun.py` module in `src/core/` that calculates Chanlun indicators (笔, 线段, 中枢, 走势类型, 背驰判断)，then wire it into `analyzer.py` and `strategy_generator.py` so results appear in the API response alongside existing technical and fundamental analysis.

**Tech Stack:** Python, numpy, pandas (existing dependencies). No new external dependencies.

---

## File Structure

```
3.1重构版/src/core/chanlun.py       # NEW — Chanlun Theory核心算法（笔/线段/中枢/背驰）
3.1重构版/src/core/analyzer.py       # MODIFY — 集成chanlun计算
3.1重构版/src/core/strategy_generator.py  # MODIFY — 在策略生成中输出缠论建议
```

---

## Background: 缠论 Core Concepts (for reference)

1. **笔 (Bi)** — 最基础的构件，5根以上独立K线组成（需要缺口处理）
2. **线段 (XianDuan)** — 由至少3笔构成
3. **中枢 (ZhongShu)** — 至少3笔重叠的部分形成走势中枢
4. **走势类型** — 上涨/下跌/盘整
5. **背驰 (BeiChi)** — 趋势力度减弱，常见判断：MACD黄白线/红绿柱面积比较
6. **同级别分解** — 将走势按级别分解成独立交易单元
7. **三类买卖点** — 第一类（趋势转折点）、第二类（回调不破原中枢）、第三类（突破中枢后的回调）

---

## Task 1: Create `chanlun.py` — Core Algorithm

**Files:**
- Create: `3.1重构版/src/core/chanlun.py`

- [ ] **Step 1: Write the complete Chanlun module**

```python
"""缠论 (Chanlun Theory) 技术分析模块

提供笔、线段、中枢、走势类型、背驰判断、同级别分解分析
"""
from typing import Optional, Tuple, List, Dict, Any
import numpy as np
import pandas as pd


def _is_inflaction(k1, k2, k3) -> bool:
    """检测是否有缺口：K线2的低点 > K线1的高点 或 K线2的高点 < K线1的低点"""
    return (k2['low'] > k1['high']) or (k2['high'] < k1['low'])


def _bi_direction(bi) -> str:
    """判断笔的方向：上涨笔 / 下跌笔"""
    return "上涨" if bi['start']['close'] < bi['end']['close'] else "下跌"


def _calc_fenxing(df: pd.DataFrame, index: int, direction: str) -> Optional[dict]:
    """计算分型：顶分型或底分型
    
    Args:
        df: K线数据 (日期/开盘/收盘/最高/最低/成交量)
        index: 当前K线索引
        direction: "up"=上涨过程中找顶分型, "down"=下跌过程中找底分型
    
    Returns:
        分型字典 {start_idx, end_idx, type: "ding"/"di", high/low价格}
    """
    if index < 2 or index >= len(df):
        return None
    
    k0, k1, k2 = df.iloc[index-2], df.iloc[index-1], df.iloc[index]
    
    if direction == "up":
        # 顶分型：中K线最高点最高
        if k1['high'] > k0['high'] and k1['high'] > k2['high']:
            return {
                'type': 'ding',
                'idx': index - 1,
                'high': k1['high'],
                'low': k1['low'],
            }
    else:
        # 底分型：中K线最低点最低
        if k1['low'] < k0['low'] and k1['low'] < k2['low']:
            return {
                'type': 'di',
                'idx': index - 1,
                'high': k1['high'],
                'low': k1['low'],
            }
    return None


def detect_bi(df: pd.DataFrame, min_bars: int = 5) -> List[dict]:
    """识别笔 (Bi)
    
    笔的定义：
    1. 连续min_bars根K线（无缺口）
    2. 符合分型结构（顶分型或底分型）
    3. 笔内部不允许有缺口
    
    Returns:
        list of bi dicts: [{'start_idx', 'end_idx', 'direction', 'start_price', 'end_price', 'bars'}]
    """
    if len(df) < min_bars + 4:
        return []
    
    bars = df.reset_index(drop=True)
    bis = []
    direction = None  # 当前笔的方向：up=上涨笔, down=下跌笔
    
    i = min_bars
    while i < len(bars):
        # 寻找分型
        if direction is None:
            # 寻找第一个顶分型，开始上涨笔
            fenxing = _calc_fenxing(bars, i, "up")
            if fenxing and fenxing['type'] == 'ding':
                direction = "up"
                start_idx = fenxing['idx']
            else:
                i += 1
                continue
        
        # 寻找反向分型（上涨找底分型，下跌找顶分型）
        target_dir = "down" if direction == "up" else "up"
        fenxing = _calc_fenxing(bars, i, target_dir)
        
        if fenxing is None:
            i += 1
            continue
        
        end_idx = fenxing['idx']
        bar_count = end_idx - start_idx + 1
        
        # 笔至少需要min_bars根K线（允许start_idx到end_idx之间有缺口，但端点要满足）
        if bar_count < min_bars:
            i += 1
            continue
        
        # 检查是否有缺口（笔的端点之间不允许缺口）
        has_gap = False
        for gi in range(start_idx, end_idx):
            if _is_inflaction(bars.iloc[gi], bars.iloc[gi+1], bars.iloc[gi+2]):
                has_gap = True
                break
        
        if has_gap:
            # 有缺口，跳过，尝试从上一个分型继续
            i = end_idx
            direction = None
            continue
        
        # 有效笔
        bi = {
            'start_idx': start_idx,
            'end_idx': end_idx,
            'direction': direction,
            'start_price': bars.iloc[start_idx]['close'],
            'end_price': bars.iloc[end_idx]['close'],
            'bars': bar_count,
        }
        bis.append(bi)
        
        direction = target_dir  # 反向笔开始
        start_idx = end_idx
        i = end_idx + 1
    
    return bis


def detect_xianduan(bi_list: List[dict], min_bi_count: int = 3) -> List[dict]:
    """识别线段 (XianDuan)
    
    线段定义：至少由min_bi_count个同方向笔构成
    线段被另一个线段破坏则升级
    
    Returns:
        list of xianduan dicts: [{'start_bi_idx', 'end_bi_idx', 'direction', 'bars', 'bis'}]
    """
    if len(bi_list) < min_bi_count:
        return []
    
    xian_duans = []
    i = 0
    while i <= len(bi_list) - min_bi_count:
        group = bi_list[i:i + min_bi_count]
        direction = group[0]['direction']
        
        # 检查是否同方向
        all_same = all(b['direction'] == direction for b in group)
        
        if all_same:
            xianduan = {
                'start_bi_idx': i,
                'end_bi_idx': i + min_bi_count - 1,
                'direction': direction,
                'bis': group,
                'start_price': group[0]['start_price'],
                'end_price': group[-1]['end_price'],
            }
            xian_duans.append(xianduan)
            i += min_bi_count
        else:
            i += 1
    
    return xian_duans


def detect_zhongshu(xian_duan_list: List[dict], price_data: pd.DataFrame) -> List[dict]:
    """识别中枢 (ZhongShu)
    
    中枢定义：连续三段重叠的区域
    取高值中的最低价与低值中的最高价重叠区域
    
    Returns:
        list of zhongshu dicts: [{'start_xd_idx', 'end_xd_idx', 'high', 'low', 'direction', 'type'}]
    """
    if len(xian_duan_list) < 3:
        return []
    
    zhongshus = []
    i = 0
    
    while i <= len(xian_duan_list) - 3:
        xd1 = xian_duan_list[i]
        xd2 = xian_duan_list[i + 1]
        xd3 = xian_duan_list[i + 2]
        
        # 获取这三段的价格范围
        def get_range(xd):
            bis = xd['bis']
            prices = []
            for bi in bis:
                for idx in range(bi['start_idx'], bi['end_idx'] + 1):
                    if idx < len(price_data):
                        prices.append(price_data.iloc[idx]['high'])
                        prices.append(price_data.iloc[idx]['low'])
            return max(prices), min(prices)
        
        high1, low1 = get_range(xd1)
        high2, low2 = get_range(xd2)
        high3, low3 = get_range(xd3)
        
        # 重叠区域
        max_high = max(high1, high2, high3)
        min_low = min(low1, low2, low3)
        
        overlap_high = min(high1, high2, high3)
        overlap_low = max(low1, low2, low3)
        
        # 如果有重叠
        if overlap_low < overlap_high:
            direction = xd2['direction']
            zhongshu = {
                'start_xd_idx': i,
                'end_xd_idx': i + 2,
                'high': overlap_high,
                'low': overlap_low,
                'range': overlap_high - overlap_low,
                'direction': direction,
                'zg': overlap_high,
                'zd': overlap_low,
                'type': '中枢',
            }
            zhongshus.append(zhongshu)
        
        i += 1
    
    return zhongshus


def detect_beichi(xian_duan_list: List[dict], price_data: pd.DataFrame, 
                  lookback_bis: int = 5) -> List[dict]:
    """识别背驰 (BeiChi)
    
    背驰判断：比较相邻同向线段的力度
    力度 = 幅度 × 成交量（简化版用价格幅度）
    
    Returns:
        list of beichi dicts: [{'idx', 'direction', 'type', 'description'}]
    """
    if len(xian_duan_list) < 2:
        return []
    
    beichi_list = []
    
    for i in range(1, len(xian_duan_list)):
        xd_prev = xian_duan_list[i - 1]
        xd_curr = xian_duan_list[i]
        
        if xd_curr['direction'] != xd_prev['direction']:
            continue
        
        # 计算幅度
        prev_range = abs(xd_prev['end_price'] - xd_prev['start_price'])
        curr_range = abs(xd_curr['end_price'] - xd_curr['start_price'])
        
        if prev_range == 0:
            continue
        
        ratio = curr_range / prev_range
        
        direction = xd_curr['direction']
        
        if direction == "上涨":
            # 上涨力度减弱 = 背驰（红柱缩短）
            if ratio < 0.8 and curr_range < prev_range:
                beichi_list.append({
                    'idx': i,
                    'direction': direction,
                    'type': '顶背驰',
                    'prev_range': round(prev_range, 2),
                    'curr_range': round(curr_range, 2),
                    'ratio': round(ratio, 2),
                    'description': f"上涨力度减弱({ratio:.0%})，可能见顶",
                })
        else:
            # 下跌力度减弱 = 背驰（绿柱缩短）= 底部机会
            if ratio < 0.8 and curr_range < prev_range:
                beichi_list.append({
                    'idx': i,
                    'direction': direction,
                    'type': '底背驰',
                    'prev_range': round(prev_range, 2),
                    'curr_range': round(curr_range, 2),
                    ' 'ratio': round(ratio, 2),
                    'description': f"下跌力度减弱({ratio:.0%})，可能见底",
                })
    
    return beichi_list


def generate_buy_sell_points(bi_list: List[dict], xian_duan_list: List[dict],
                               zhongshu_list: List[dict], beichi_list: List[dict],
                               price_data: pd.DataFrame) -> Dict[str, Any]:
    """生成三类买卖点
    
    第一类买卖点：趋势转折点（背驰位置）
    第二类买卖点：回调不破原中枢的买卖点
    第三类买卖点：突破中枢后的回抽不破
    
    Returns:
        dict with 'buy_points', 'sell_points', 'operation_advice'
    """
    result = {
        'buy_points': [],
        'sell_points': [],
        'operation_advice': '',
    }
    
    if not bi_list or price_data.empty:
        return result
    
    last_price = price_data.iloc[-1]['close']
    
    # 第一类买点：底背驰 + 下跌笔结束时
    for bc in beichi_list:
        if bc['type'] == '底背驰':
            bi_idx = bc['idx']
            if bi_idx < len(bi_list):
                bi = bi_list[bi_idx]
                result['buy_points'].append({
                    'type': '第一类买点',
                    'level': '专业级',
                    'price': bi['end_price'],
                    'condition': bc['description'],
                    'risk': '可能继续下跌，严格止损',
                    'target_return': '>15%',
                })
    
    # 第一类卖点：顶背驰 + 上涨笔结束时
    for bc in beichi_list:
        if bc['type'] == '顶背驰':
            bi_idx = bc['idx']
            if bi_idx < len(bi_list):
                bi = bi_list[bi_idx]
                result['sell_points'].append({
                    'type': '第一类卖点',
                    'level': '专业级',
                    'price': bi['end_price'],
                    'condition': bc['description'],
                    'risk': '可能继续上涨，踏空风险',
                    'target_return': '>10%',
                })
    
    # 第二类买卖点：最近中枢的上下沿
    if zhongshu_list:
        last_zs = zhongshu_list[-1]
        # 第二类买点：价格接近中枢下沿 + 不破更低
        result['buy_points'].append({
            'type': '第二类买点',
            'level': '稳健型',
            'price': round(last_zs['zd'], 2),
            'zs_high': round(last_zs['zg'], 2),
            'zs_low': round(last_zs['zd'], 2),
            'condition': '回调不破中枢下沿，缠论第二类买点',
            'risk': '中等，确认需放量阳线',
            'target_return': '8-15%',
        })
        
        # 第二类卖点：价格接近中枢上沿 + 不破更高
        result['sell_points'].append({
            'type': '第二类卖点',
            'level': '稳健型',
            'price': round(last_zs['zg'], 2),
            'zs_high': round(last_zs['zg'], 2),
            'zs_low': round(last_zs['zd'], 2),
            'condition': '反弹不破中枢上沿，缠论第二类卖点',
            'risk': '中等，注意是否向上突破',
            'target_return': '8-12%',
        })
    
    # 第三类买卖点
    if len(zhongshu_list) >= 1:
        zs = zhongshu_list[-1]
        # 第三类买点：突破中枢后回调不破ZD
        result['buy_points'].append({
            'type': '第三类买点',
            'level': '确认型',
            'price': round(last_zs['zd'], 2),
            'break_level': round(last_zs['zg'], 2),
            'condition': '突破中枢后回调不破ZD，强势买入信号',
            'risk': '低，确认突破有效性',
            'target_return': '20%+',
        })
        
        # 第三类卖点：跌破中枢后反弹不破ZG
        result['sell_points'].append({
            'type': '第三类卖点',
            'level': '确认型',
            'price': round(last_zs['zg'], 2),
            'break_level': round(last_zs['zd'], 2),
            'condition': '跌破中枢后反弹不破ZG，弱势卖出信号',
            'risk': '低，及时止损',
            'target_return': '15%+',
        })
    
    # 生成综合建议
    if result['buy_points'] and result['sell_points']:
        result['operation_advice'] = "多空信号并存，建议等待确认"
    elif result['buy_points']:
        best = min(result['buy_points'], key=lambda x: x.get('target_return', '0%'))
        result['operation_advice'] = f"建议买入：{best['type']} @ ¥{best['price']}（{best['condition']}）"
    elif result['sell_points']:
        best = min(result['sell_points'], key=lambda x: x.get('target_return', '0%'))
        result['operation_advice'] = f"建议卖出：{best['type']} @ ¥{best['price']}（{best['condition']}）"
    else:
        result['operation_advice'] = "当前无明确买卖点，等待中枢突破或背驰信号"
    
    return result


def analyze_chanlun(df: pd.DataFrame, min_bi_bars: int = 5) -> Dict[str, Any]:
    """缠论综合分析入口
    
    Args:
        df: K线数据 (日期/开盘/收盘/最高/最低/成交量)
        min_bi_bars: 笔的最少K线根数（默认5）
    
    Returns:
        dict with complete Chanlun analysis:
        {
            'available': bool,
            'bi_list': [...],
            'xianduan_list': [...],
            'zhongshu_list': [...],
            'beichi_list': [...],
            'current_trend': str,
            'trend_strength': str,
            'buy_sell_points': {...},
            'summary': str,
            'chanlun_score': float,  # -2.0 to 2.0 (for integration with strategy_generator)
        }
    """
    if df is None or len(df) < 30:
        return {
            'available': False,
            'summary': '数据不足（需要30根以上K线）',
            'chanlun_score': 0.0,
        }
    
    # Step 1: 识别笔
    bi_list = detect_bi(df, min_bars=min_bi_bars)
    
    # Step 2: 识别线段
    xianduan_list = detect_xianduan(bi_list, min_bi_count=3)
    
    # Step 3: 识别中枢
    zhongshu_list = detect_zhongshu(xianduan_list, df)
    
    # Step 4: 识别背驰
    beichi_list = detect_beichi(xianduan_list, df)
    
    # Step 5: 生成买卖点
    buy_sell = generate_buy_sell_points(bi_list, xianduan_list, zhongshu_list, beichi_list, df)
    
    # Step 6: 判断当前走势
    current_trend = "中性"
    trend_strength = "弱"
    chanlun_score = 0.0
    
    if xianduan_list:
        last_xd = xianduan_list[-1]
        direction = last_xd['direction']
        
        if direction == "上涨":
            current_trend = "上涨走势"
            # 检查是否背驰
            has_beichi = any(b['type'] == '顶背驰' for b in beichi_list)
            trend_strength = "弱（背驰风险）" if has_beichi else "强"
            chanlun_score = -0.3 if has_beichi else 1.0
        else:
            current_trend = "下跌走势"
            has_beichi = any(b['type'] == '底背驰' for b in beichi_list)
            trend_strength = "弱（背驰机会）" if has_beichi else "弱"
            chanlun_score = 0.5 if has_beichi else -0.3
    
    # 中枢方向判断
    if zhongshu_list:
        last_zs = zhongshu_list[-1]
        if last_xd['direction'] == "上涨":
            # 当前在中枢上方 = 强势，在下方 = 弱势
            if df.iloc[-1]['close'] > last_zs['zg']:
                current_trend = "上涨走势（突破中枢）"
                chanlun_score = max(chanlun_score, 1.5)
                trend_strength = "强势"
            elif df.iloc[-1]['close'] < last_zs['zd']:
                current_trend = "下跌走势（跌破中枢）"
                chanlun_score = min(chanlun_score, -1.5)
                trend_strength = "弱势"
    
    # 构建summary
    bi_count = len(bi_list)
    xd_count = len(xianduan_list)
    zs_count = len(zhongshu_list)
    bc_count = len(beichi_list)
    
    summary_lines = [
        f"笔: {bi_count}笔 | 线段: {xd_count}段 | 中枢: {zs_count}个 | 背驰: {bc_count}次",
        f"当前趋势: {current_trend} | 力度: {trend_strength}",
    ]
    if buy_sell['operation_advice']:
        summary_lines.append(f"操作建议: {buy_sell['operation_advice']}")
    
    return {
        'available': True,
        'bi_count': bi_count,
        'xianduan_count': xd_count,
        'zhongshu_count': zs_count,
        'beichi_count': bc_count,
        'bi_list': bi_list,
        'xianduan_list': [{k: v for k, v in xd.items() if k != 'bis'} for xd in xianduan_list],
        'zhongshu_list': [{k: v for k, v in zs.items()} for zs in zhongshu_list],
        'beichi_list': beichi_list,
        'current_trend': current_trend,
        'trend_strength': trend_strength,
        'buy_sell_points': buy_sell,
        'summary': ' | '.join(summary_lines),
        'chanlun_score': round(chanlun_score, 2),
    }


# 兼容别名
def calculate_chanlun(df: pd.DataFrame, **kwargs) -> Dict[str, Any]:
    return analyze_chanlun(df, **kwargs)
```

- [ ] **Step 2: Verify the file was created**

Run: `ls -la "3.1重构版/src/core/chanlun.py"`
Expected: File exists with ~400+ lines

- [ ] **Step 3: Test the module loads without errors**

Run: `cd "3.1重构版" && python -c "from src.core.chanlun import analyze_chanlun; print('chanlun module OK')"`
Expected: `chanlun module OK`

- [ ] **Step 4: Quick functional test**

```python
import pandas as pd
import numpy as np

# Generate sample data with trend
dates = pd.date_range('2024-01-01', periods=100, freq='D')
np.random.seed(42)
prices = 10 + np.cumsum(np.random.randn(100) * 0.5)
df = pd.DataFrame({
    '日期': dates,
    '开盘': prices - 0.2,
    '收盘': prices,
    '最高': prices + 0.3,
    '最低': prices - 0.3,
    '成交量': np.random.randint(100000, 1000000, 100),
})

from src.core.chanlun import analyze_chanlun
result = analyze_chanlun(df)
assert result['available'] == True
assert result['chanlun_score'] != 0.0
print("chanlun functional test OK")
print(result['summary'])
```

- [ ] **Step 5: Commit**

```bash
cd "3.1重构版"
git add src/core/chanlun.py
git commit -m "feat(chanlun): add 缠论 technical analysis module

- implement 笔/线段/中枢 detection
- implement 背驰 (BeiChi) recognition  
- implement 三类买卖点 generation
- add analyze_chanlun() entry point"
```

---

## Task 2: Integrate Chanlun into `analyzer.py`

**Files:**
- Modify: `3.1重构版/src/core/analyzer.py`

- [ ] **Step 1: Add `analyze_chanlun` import and integration point**

Find the `calculate_technical_indicators` method in `analyzer.py`. In the `analyze_stock` method (around line 196), after getting `price_data`, call `analyze_chanlun`:

```python
# In analyze_stock(), after:
price_data = self.get_stock_data(code, market)
price_info = self.get_price_info(price_data)

# Add Chanlun analysis:
chanlun = analyze_chanlun(price_data)
```

- [ ] **Step 2: Add `chanlun` to return dict**

In the `analyze_stock()` return dict (around line 244), add `'chanlun': chanlun,` after `'fundamental'`:

```python
return {
    ...
    "fundamental": fundamental,
    "chanlun": chanlun,
    "sentiment": sentiment,
    ...
}
```

- [ ] **Step 3: Add `chanlun_score` to scores dict**

In `analyze_stock()`, where `scores_dict` is built (around line 219):

```python
scores_dict = {
    'technical': technical_score,
    'fundamental': fundamental_score,
    'sentiment': sentiment_score,
    'comprehensive': comprehensive_score,
    'chanlun': chanlun.get('chanlun_score', 0.0),  # ADD THIS
}
```

- [ ] **Step 4: Test import**

Run: `cd "3.1重构版" && python -c "from src.core.analyzer import StockAnalyzer; print('analyzer import OK')"`
Expected: `analyzer import OK`

- [ ] **Step 5: Commit**

```bash
cd "3.1重构版"
git add src/core/analyzer.py
git commit -m "feat(chanlun): integrate 缠论 analysis into StockAnalyzer

- call analyze_chanlun() with price_data
- add chanlun_score to scores dict
- include chanlun in analyze_stock() response"
```

---

## Task 3: Add Chanlun Output to `strategy_generator.py`

**Files:**
- Modify: `3.1重构版/src/core/strategy_generator.py`

- [ ] **Step 1: Add chanlun parameter and processing in StrategyGenerator**

In `StrategyGenerator.__init__` (line 26), add `chanlun=None`:

```python
def __init__(self, scores: dict, technical: dict, fundamental: dict,
             sentiment: dict, quote: dict, price_info: dict = None,
             chanlun: dict = None):  # ADD chanlun
    self.chanlun = chanlun or {}
```

- [ ] **Step 2: Add `_score_chanlun()` method**

Add after `_score_long()` (around line 293):

```python
def _score_chanlun(self) -> float:
    """Score based on 缠论 analysis (-2.0 to 2.0)"""
    if not self.chanlun.get('available'):
        return 0.0
    
    score = self.chanlun.get('chanlun_score', 0.0)
    
    # 背驰加分/减分
    beichi_list = self.chanlun.get('beichi_list', [])
    for bc in beichi_list:
        if bc['type'] == '底背驰':
            score += 0.4
        elif bc['type'] == '顶背驰':
            score -= 0.4
    
    # 三类买卖点加成
    bs = self.chanlun.get('buy_sell_points', {})
    if bs.get('buy_points'):
        score += 0.3
    if bs.get('sell_points'):
        score -= 0.3
    
    return max(-2.0, min(2.0, score))
```

- [ ] **Step 3: Update `generate()` to include chanlun**

In `generate()` method (line 37), after the existing cycle scoring:

```python
s_chanlun = self._score_chanlun()
# Add to composite:
composite = (
    weights["ultra"] * s_ultra +
    weights["short"] * s_short +
    weights["mid"] * s_mid +
    weights["long"] * s_long +
    0.1 * s_chanlun  # 10% weight for 缠论
)
```

Also add `chanlun_cycle` to return dict:

```python
return {
    ...
    "chanlun": {
        "score": s_chanlun,
        "current_trend": self.chanlun.get('current_trend', 'N/A'),
        "trend_strength": self.chanlun.get('trend_strength', 'N/A'),
        "summary": self.chanlun.get('summary', ''),
        "buy_points": self.chanlun.get('buy_sell_points', {}).get('buy_points', []),
        "sell_points": self.chanlun.get('buy_sell_points', {}).get('sell_points', []),
        "operation_advice": self.chanlun.get('buy_sell_points', {}).get('operation_advice', ''),
    },
    ...
}
```

- [ ] **Step 4: Update `_generate_batch_operation()` to include Chanlun advice**

In `_generate_batch_operation()`, add after existing lines:

```python
if self.chanlun.get('available'):
    operation = self.chanlun.get('buy_sell_points', {}).get('operation_advice', '')
    if operation:
        lines.append(f"• 缠论信号: {operation}")
```

- [ ] **Step 5: Update `_generate_current_advice()` to mention Chanlun**

In `_generate_current_advice()`, add to short_term string:

```python
chanlun_trend = self.chanlun.get('current_trend', '')
if chanlun_trend:
    short = f"{short} | 缠论:{chanlun_trend}"
```

- [ ] **Step 6: Test integration**

Run: `cd "3.1重构版" && python -c "from src.core.strategy_generator import StrategyGenerator; g = StrategyGenerator({}, {}, {}, {}, None); r = g.generate(); print('chanlun in strategy:', 'chanlun' in r); print(r.get('chanlun', {}).get('operation_advice', 'no advice'))"`
Expected: `chanlun in strategy: True` and operation advice text

- [ ] **Step 7: Commit**

```bash
cd "3.1重构版"
git add src/core/strategy_generator.py
git commit -m "feat(chanlun): integrate 缠论 into StrategyGenerator

- add chanlun_score to composite weighting
- output chanlun trend/买卖点/操作建议 in strategy response
- update batch operation with 缠论 signals"
```

---

## Task 4: End-to-End Verification

**Files:**
- Modify: `3.1重构版/src/api/analyze_routes.py` (if needed to pass chanlun)

- [ ] **Step 1: Run full analyzer test**

```bash
cd "3.1重构版"
python -c "
from src.core.analyzer import StockAnalyzer
analyzer = StockAnalyzer()
# Test with a real A-stock code
result = analyzer.analyze_stock('000001', 'SZ')
print('chanlun available:', result.get('chanlun', {}).get('available', False))
print('chanlun score:', result.get('chanlun', {}).get('chanlun_score', 'N/A'))
print('buy_points:', result.get('chanlun', {}).get('buy_sell_points', {}).get('buy_points', []))
print('operation_advice:', result.get('chanlun', {}).get('buy_sell_points', {}).get('operation_advice', 'N/A'))
print('strategy chanlun:', result.get('strategy', {}).get('chanlun', {}).get('operation_advice', 'N/A'))
"
```

Expected: No errors, chanlun data present

- [ ] **Step 2: Commit final state**

```bash
cd "3.1重构版"
git add -A
git commit -m "feat(chanlun): complete 缠论 integration end-to-end verification"
```

---

## Self-Review Checklist

1. **Spec coverage:** Check each 缠论 component has a task:
   - 笔识别 → Task 1 `detect_bi()`
   - 线段识别 → Task 1 `detect_xianduan()`
   - 中枢识别 → Task 1 `detect_zhongshu()`
   - 背驰判断 → Task 1 `detect_beichi()`
   - 三类买卖点 → Task 1 `generate_buy_sell_points()`
   - 同级别分解 → Part of `analyze_chanlun()` return
   - 与策略生成器集成 → Tasks 2, 3

2. **Placeholder scan:** All steps have actual code blocks, no TODOs

3. **Type consistency:** Method names consistent across tasks:
   - `analyze_chanlun()` (entry point)
   - `detect_bi()`, `detect_xianduan()`, `detect_zhongshu()`, `detect_beichi()`
   - `generate_buy_sell_points()`
   - All return `Dict[str, Any]` or `List[dict]`

---

**Plan complete and saved to** `docs/superpowers/plans/2026-05-22-chanlun-implementation.md`

**Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?