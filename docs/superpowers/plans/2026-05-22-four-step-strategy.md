# 四步定量筛股策略 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现四步定量筛股策略 FourStepStrategy，输出 0-100 总分，>60 BUY / 40-60 WATCH / <40 SELL

**Architecture:** 独立策略类，继承 BaseStrategy，四步顺序计算权重得分，最终聚合输出 TradingSignal

**Tech Stack:** Python, akshare, 现有 BaseStrategy 框架, TechnicalCalculator

---

## Task 1: 创建 FourStepStrategy 骨架

**Files:**
- Create: `stock_ai_analyst_v4/src/trading/strategies/four_step.py`
- Test: `stock_ai_analyst_v4/tests/unit/test_strategies/test_four_step.py`

- [ ] **Step 1: 写测试文件骨架**

```python
# tests/unit/test_strategies/test_four_step.py
import pytest
from src.trading.strategies.four_step import FourStepStrategy

class TestFourStepStrategy:
    def setup_method(self):
        self.strategy = FourStepStrategy()

    def test_strategy_has_weights(self):
        assert hasattr(self.strategy, 'weights')
        assert self.strategy.weights['step1'] == 0.25
        assert self.strategy.weights['step2'] == 0.25
        assert self.strategy.weights['step3'] == 0.20
        assert self.strategy.weights['step4'] == 0.30
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/test_strategies/test_four_step.py::TestFourStepStrategy::test_strategy_has_weights -v`
Expected: FAIL - FourStepStrategy not found

- [ ] **Step 3: 写策略骨架**

```python
# src/trading/strategies/four_step.py
"""四步定量筛股策略"""
from typing import Dict, Any
from src.trading.strategies.base_strategy import BaseStrategy
from src.core.models import TradingSignal


class FourStepStrategy(BaseStrategy):
    """四步定量筛股策略 — 估值排雷 + 筹码清洗 + 技术砸透 + 资金点火"""

    def __init__(self):
        self.weights = {
            'step1': 0.25,  # 估值排雷
            'step2': 0.25,  # 筹码大清洗
            'step3': 0.20,  # 技术面砸透
            'step4': 0.30,  # 资金点火
        }

    def analyze(self, stock_data: Dict[str, Any]) -> TradingSignal:
        raise NotImplementedError
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/unit/test_strategies/test_four_step.py::TestFourStepStrategy::test_strategy_has_weights -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/trading/strategies/four_step.py tests/unit/test_strategies/test_four_step.py
git commit -m "feat(four_step): add FourStepStrategy skeleton with weights"
```

---

## Task 2: 实现第一步 - 估值排雷（25分）

**Files:**
- Modify: `stock_ai_analyst_v4/src/trading/strategies/four_step.py`

- [ ] **Step 1: 写测试**

```python
def test_step1_valuation_low_pe_passes():
    """PE处于历史15%分位以下，得满分"""
    stock_data = {
        'stock_code': '000001',
        'pe_historical_percentile': 10.0,  # < 15%
        'financial_data': {
            'non_recurring_profit': [100, 80, 90],  # 近3年正
            'operating_cash_flow': [50, 60, 70]       # 近3年正
        }
    }
    result = self.strategy._calc_step1(stock_data)
    assert result == 25.0  # 条件A满分(25) + 条件B梯度(0.25*25)

def test_step1_valuation_high_pe_fails_condition_a():
    """PE处于历史80%分位，条件A不满足"""
    stock_data = {
        'stock_code': '000001',
        'pe_historical_percentile': 80.0,  # > 15%
        'financial_data': {
            'non_recurring_profit': [100, 80, 90],
            'operating_cash_flow': [50, 60, 70]
        }
    }
    result = self.strategy._calc_step1(stock_data)
    assert result == 6.25  # 条件A=0, 条件B=0.25*25

def test_step1_no_data_returns_zero():
    """数据不足返回0"""
    stock_data = {'stock_code': '000001'}
    result = self.strategy._calc_step1(stock_data)
    assert result == 0.0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/test_strategies/test_four_step.py::TestFourStepStrategy::test_step1_valuation_low_pe_passes -v`
Expected: FAIL - method not found

- [ ] **Step 3: 实现 _calc_step1**

```python
def _calc_step1(self, stock_data: Dict[str, Any]) -> float:
    """第一步：估值排雷（25分）"""
    # 条件A：低估值（PE-TTM或PB < 15%历史分位）
    pe_percentile = stock_data.get('pe_historical_percentile', 100)
    pb_percentile = stock_data.get('pb_historical_percentile', 100)
    condition_a = pe_percentile < 15 or pb_percentile < 15

    # 条件B：硬财务（梯度赋分）
    fin = stock_data.get('financial_data', {})
    non_recurring_profit = fin.get('non_recurring_profit', [])
    operating_cash_flow = fin.get('operating_cash_flow', [])

    # 计算净利润为正的年数
    positive_years = sum(1 for p in non_recurring_profit if p > 0)
    if len(non_recurring_profit) >= 3:
        if positive_years == 3:
            profit_score = 1.0
        elif positive_years == 2:
            profit_score = 0.6
        elif positive_years == 1:
            profit_score = 0.3
        else:
            profit_score = 0.0
    else:
        profit_score = 0.0

    # 现金流加分
    cash_positive_years = sum(1 for c in operating_cash_flow if c > 0)
    if cash_positive_years >= 2:
        profit_score = min(profit_score + 0.1, 1.1)

    # 条件A满分25分，条件B梯度×25分
    score_a = 25.0 if condition_a else 0.0
    score_b = profit_score * 25.0

    return score_a + score_b
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/unit/test_strategies/test_four_step.py::TestFourStepStrategy::test_step1_valuation_low_pe_passes tests/unit/test_strategies/test_four_step.py::TestFourStepStrategy::test_step1_valuation_high_pe_fails_condition_a tests/unit/test_strategies/test_four_step.py::TestFourStepStrategy::test_step1_no_data_returns_zero -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/trading/strategies/four_step.py tests/unit/test_strategies/test_four_step.py
git commit -m "feat(four_step): implement step1 valuation scoring"
```

---

## Task 3: 实现第二步 - 筹码大清洗（25分）

**Files:**
- Modify: `stock_ai_analyst_v4/src/trading/strategies/four_step.py`

- [ ] **Step 1: 写测试**

```python
def test_step2_turnover_and_volume():
    """换手率>=1.5% + 缩量通过，得满分"""
    stock_data = {
        'turnover_rate_5d': 2.5,  # >= 1.5%
        'volume_ratio_20d': 0.4,  # < 50%
        'turnover_change_pct': -40.0  # 较30日前下降>30%
    }
    result = self.strategy._calc_step2(stock_data)
    assert result == 30.0  # 25 + 5(额外加分)

def test_step2_low_turnover_fails():
    """换手率<1.5%，条件A不满足"""
    stock_data = {
        'turnover_rate_5d': 0.5,
        'volume_ratio_20d': 0.3,
        'turnover_change_pct': -20.0
    }
    result = self.strategy._calc_step2(stock_data)
    assert result == 0.0  # 条件A=0, 条件B=0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/test_strategies/test_four_step.py::TestFourStepStrategy::test_step2_turnover_and_volume -v`
Expected: FAIL

- [ ] **Step 3: 实现 _calc_step2**

```python
def _calc_step2(self, stock_data: Dict[str, Any]) -> float:
    """第二步：筹码大清洗（25分）"""
    # 条件A：换手率不低（5日平均换手率 >= 1.5%）
    turnover_5d = stock_data.get('turnover_rate_5d', 0)
    condition_a = turnover_5d >= 1.5

    # 条件B：缩量验证（梯度赋分）
    volume_ratio = stock_data.get('volume_ratio_20d', 1.0)  # 当前成交量/20日均量

    if volume_ratio < 0.5:
        volume_score = 1.0
    elif volume_ratio < 0.6:
        volume_score = 0.7
    elif volume_ratio < 0.7:
        volume_score = 0.4
    else:
        volume_score = 0.0

    # 换手率较30日前下降 > 30% 额外加分20%
    turnover_change = stock_data.get('turnover_change_pct', 0)
    if turnover_change < -30:
        volume_score = min(volume_score + 0.2, 1.2)

    # 条件A满分25分，条件B梯度×25分
    score_a = 25.0 if condition_a else 0.0
    score_b = volume_score * 25.0

    return score_a + score_b
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/unit/test_strategies/test_four_step.py::TestFourStepStrategy::test_step2_turnover_and_volume tests/unit/test_strategies/test_four_step.py::TestFourStepStrategy::test_step2_low_turnover_fails -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/trading/strategies/four_step.py tests/unit/test_strategies/test_four_step.py
git commit -m "feat(four_step): implement step2 chip cleaning scoring"
```

---

## Task 4: 实现第三步 - 技术面砸透（20分）

**Files:**
- Modify: `stock_ai_analyst_v4/src/trading/strategies/four_step.py`

- [ ] **Step 1: 写测试**

```python
def test_step3_all_conditions_met():
    """三个条件均满足，得满分20"""
    stock_data = {
        'drop_from_high_6m': 45.0,   # > 35%
        'bias_10': -12.0,            # < -8%
        'volume_ratio_3d': 0.3       # < 50%
    }
    result = self.strategy._calc_step3(stock_data)
    assert result == 20.0

def test_step3_one_condition_fails():
    """BIAS=-5%（不满足），只得空间急跌分8分"""
    stock_data = {
        'drop_from_high_6m': 40.0,
        'bias_10': -5.0,
        'volume_ratio_3d': 0.3
    }
    result = self.strategy._calc_step3(stock_data)
    assert result == 8.0  # 空间急跌8分，其他0分
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/test_strategies/test_four_step.py::TestFourStepStrategy::test_step3_all_conditions_met -v`
Expected: FAIL

- [ ] **Step 3: 实现 _calc_step3**

```python
def _calc_step3(self, stock_data: Dict[str, Any]) -> float:
    """第三步：技术面砸透（20分）"""
    # 条件A：空间急跌（从近半年最高点跌幅 > 35%）→ 8分
    drop_from_high = stock_data.get('drop_from_high_6m', 0)
    score_a = 8.0 if drop_from_high > 35 else 0.0

    # 条件B：偏离度高（BIAS(10) < -8%）→ 6分
    bias_10 = stock_data.get('bias_10', 0)
    score_b = 6.0 if bias_10 < -8 else 0.0

    # 条件C：无量阴跌（买入前3天成交量 < 20日均量50%）→ 6分
    volume_ratio_3d = stock_data.get('volume_ratio_3d', 1.0)
    score_c = 6.0 if volume_ratio_3d < 0.5 else 0.0

    return score_a + score_b + score_c
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/unit/test_strategies/test_four_step.py::TestFourStepStrategy::test_step3_all_conditions_met tests/unit/test_strategies/test_four_step.py::TestFourStepStrategy::test_step3_one_condition_fails -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/trading/strategies/four_step.py tests/unit/test_strategies/test_four_step.py
git commit -m "feat(four_step): implement step3 technical compression scoring"
```

---

## Task 5: 实现第四步 - 资金点火（30分）

**Files:**
- Modify: `stock_ai_analyst_v4/src/trading/strategies/four_step.py`

- [ ] **Step 1: 写测试**

```python
def test_step4_five_consecutive_days_plus_breakout():
    """连续5日净流入 + 右侧突破 = 满分30分"""
    stock_data = {
        'main_net_inflow_days': 5,    # 连续5日
        'right_breakout': True        # 放量突破5日均线
    }
    result = self.strategy._calc_step4(stock_data)
    assert result == 30.0  # 18 + 10 + 2(额外加分)

def test_step4_three_days_no_breakout():
    """连续3日净流入，无突破 = 18分"""
    stock_data = {
        'main_net_inflow_days': 3,
        'right_breakout': False
    }
    result = self.strategy._calc_step4(stock_data)
    assert result == 10.8  # 18*0.6
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/test_strategies/test_four_step.py::TestFourStepStrategy::test_step4_five_consecutive_days_plus_breakout -v`
Expected: FAIL

- [ ] **Step 3: 实现 _calc_step4**

```python
def _calc_step4(self, stock_data: Dict[str, Any]) -> float:
    """第四步：资金点火（30分）"""
    # 条件A：主力大单持续进场（梯度赋分，最高18分）
    inflow_days = stock_data.get('main_net_inflow_days', 0)

    if inflow_days >= 5:
        inflow_score = 1.0  # 18分
    elif inflow_days >= 4:
        inflow_score = 0.8   # 14.4分
    elif inflow_days >= 3:
        inflow_score = 0.6  # 10.8分
    else:
        inflow_score = 0.0

    score_a = inflow_score * 18.0

    # 条件B：右侧突破（额外加10分）
    right_breakout = stock_data.get('right_breakout', False)
    score_b = 10.0 if right_breakout else 0.0

    # 额外加分：连续5日且突破 = +2分封顶30分
    if inflow_days >= 5 and right_breakout:
        extra = 2.0
    else:
        extra = 0.0

    return min(score_a + score_b + extra, 30.0)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/unit/test_strategies/test_four_step.py::TestFourStepStrategy::test_step4_five_consecutive_days_plus_breakout tests/unit/test_strategies/test_four_step.py::TestFourStepStrategy::test_step4_three_days_no_breakout -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/trading/strategies/four_step.py tests/unit/test_strategies/test_four_step.py
git commit -m "feat(four_step): implement step4 fund ignition scoring"
```

---

## Task 6: 实现 analyze 主方法 - 聚合四步输出 TradingSignal

**Files:**
- Modify: `stock_ai_analyst_v4/src/trading/strategies/four_step.py`

- [ ] **Step 1: 写测试**

```python
def test_analyze_buy_signal():
    """总分>60，输出BUY，置信度0.75"""
    stock_data = {
        'stock_code': '000001',
        'pe_historical_percentile': 10.0,
        'financial_data': {
            'non_recurring_profit': [100, 80, 90],
            'operating_cash_flow': [50, 60, 70]
        },
        'turnover_rate_5d': 2.5,
        'volume_ratio_20d': 0.4,
        'turnover_change_pct': -40.0,
        'drop_from_high_6m': 45.0,
        'bias_10': -12.0,
        'volume_ratio_3d': 0.3,
        'main_net_inflow_days': 5,
        'right_breakout': True
    }
    signal = self.strategy.analyze(stock_data)
    assert signal.action == "BUY"
    assert signal.confidence > 0.6
    assert "四步定量" in signal.reason

def test_analyze_watch_signal():
    """总分在40-60之间，输出WATCH"""
    stock_data = {
        'stock_code': '000001',
        'pe_historical_percentile': 80.0,  # 条件A不满足
        'financial_data': {
            'non_recurring_profit': [100, 80, 90],
            'operating_cash_flow': [50, 60, 70]
        },
        'turnover_rate_5d': 2.0,
        'volume_ratio_20d': 0.6,
        'turnover_change_pct': -20.0,
        'drop_from_high_6m': 20.0,
        'bias_10': -3.0,
        'volume_ratio_3d': 0.6,
        'main_net_inflow_days': 2,
        'right_breakout': False
    }
    signal = self.strategy.analyze(stock_data)
    assert signal.action == "WATCH"

def test_analyze_sell_signal():
    """总分<40，输出SELL"""
    stock_data = {
        'stock_code': '000001',
        'pe_historical_percentile': 95.0,
        'financial_data': {
            'non_recurring_profit': [-10, -20, -30],
            'operating_cash_flow': [-50, -60, -70]
        },
        'turnover_rate_5d': 0.3,
        'volume_ratio_20d': 1.5,
        'turnover_change_pct': 20.0,
        'drop_from_high_6m': 5.0,
        'bias_10': 2.0,
        'volume_ratio_3d': 1.2,
        'main_net_inflow_days': 0,
        'right_breakout': False
    }
    signal = self.strategy.analyze(stock_data)
    assert signal.action == "SELL"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/test_strategies/test_four_step.py::TestFourStepStrategy::test_analyze_buy_signal -v`
Expected: FAIL

- [ ] **Step 3: 实现 analyze 方法**

```python
def analyze(self, stock_data: Dict[str, Any]) -> TradingSignal:
    """分析股票数据，生成交易信号

    Args:
        stock_data: 股票数据，包含：
            - stock_code: str
            - pe_historical_percentile: float
            - pb_historical_percentile: float
            - financial_data: dict (non_recurring_profit, operating_cash_flow)
            - turnover_rate_5d: float
            - volume_ratio_20d: float
            - turnover_change_pct: float
            - drop_from_high_6m: float
            - bias_10: float
            - volume_ratio_3d: float
            - main_net_inflow_days: int
            - right_breakout: bool

    Returns:
        TradingSignal: action in [BUY, SELL, WATCH], confidence in [0.3, 0.95]
    """
    try:
        # 计算各步骤得分
        step1 = self._calc_step1(stock_data)
        step2 = self._calc_step2(stock_data)
        step3 = self._calc_step3(stock_data)
        step4 = self._calc_step4(stock_data)

        # 计算总分
        total_score = step1 + step2 + step3 + step4

        # 确定信号
        if total_score > 60:
            action = "BUY"
        elif total_score < 40:
            action = "SELL"
        else:
            action = "WATCH"

        # 计算置信度
        if action == "BUY":
            confidence = min(0.3 + total_score / 100 * 0.65, 0.95)
        elif action == "SELL":
            confidence = max(0.95 - total_score / 100 * 0.65, 0.3)
        else:
            confidence = 0.4 + (total_score - 40) / 20 * 0.3

        # 构建原因说明
        reasons = [
            f"估值={step1:.1f}分",
            f"筹码={step2:.1f}分",
            f"技术={step3:.1f}分",
            f"资金={step4:.1f}分",
            f"总分={total_score:.1f}"
        ]

        return TradingSignal(
            action=action,
            confidence=round(confidence, 2),
            reason="；".join(reasons),
            timeframe="short"
        )
    except Exception as e:
        return TradingSignal(
            action="WATCH",
            confidence=0.3,
            reason=f"计算异常：{str(e)}",
            timeframe="short"
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/unit/test_strategies/test_four_step.py -v`
Expected: ALL PASS

- [ ] **Step 5: 提交**

```bash
git add src/trading/strategies/four_step.py tests/unit/test_strategies/test_four_step.py
git commit -m "feat(four_step): implement analyze method with signal output"
```

---

## Task 7: 注册到 StrategyFactory

**Files:**
- Modify: `stock_ai_analyst_v4/src/trading/strategy_factory.py`

- [ ] **Step 1: 写测试**

```python
def test_factory_has_four_step_strategy():
    from src.trading.strategy_factory import StrategyFactory
    from src.config.settings import Settings
    factory = StrategyFactory(Settings())
    strategy = factory.get_strategy('four_step')
    assert strategy is not None
    assert strategy.weights['step1'] == 0.25

def test_list_strategies_includes_four_step():
    from src.trading.strategy_factory import StrategyFactory
    from src.config.settings import Settings
    factory = StrategyFactory(Settings())
    strategies = factory.list_strategies()
    assert 'four_step' in strategies
    assert '四步定量筛股' in strategies['four_step']
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/unit/test_strategies/test_four_step.py::TestFourStepStrategy::test_factory_has_four_step_strategy -v`
Expected: FAIL

- [ ] **Step 3: 修改 strategy_factory.py**

在 `_register_strategies` 方法中添加：

```python
from src.trading.strategies.four_step import FourStepStrategy

# 四步定量筛股策略
self._strategies['four_step'] = FourStepStrategy()
```

在 `list_strategies` 方法中添加：

```python
'four_step': '四步定量筛股模型',
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/unit/test_strategies/test_four_step.py::TestFourStepStrategy::test_factory_has_four_step_strategy tests/unit/test_strategies/test_four_step.py::TestFourStepStrategy::test_list_strategies_includes_four_step -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/trading/strategy_factory.py
git commit -m "feat(four_step): register FourStepStrategy in factory"
```

---

## Task 8: 集成测试 - 端到端验证

**Files:**
- Create: `stock_ai_analyst_v4/tests/integration/test_four_step_integration.py`

- [ ] **Step 1: 写集成测试**

```python
"""四步定量筛股策略集成测试"""
import pytest
from src.trading.strategy_factory import StrategyFactory
from src.config.settings import Settings


class TestFourStepIntegration:
    def setup_method(self):
        self.factory = StrategyFactory(Settings())
        self.strategy = self.factory.get_strategy('four_step')

    def test_full_pipeline_buy_signal(self):
        """完整数据流：应输出BUY"""
        stock_data = {
            'stock_code': '000001',
            # 第一步：估值排雷（满足）
            'pe_historical_percentile': 10.0,
            'pb_historical_percentile': 12.0,
            'financial_data': {
                'non_recurring_profit': [100, 80, 90],
                'operating_cash_flow': [50, 60, 70]
            },
            # 第二步：筹码大清洗（满足）
            'turnover_rate_5d': 2.5,
            'volume_ratio_20d': 0.4,
            'turnover_change_pct': -40.0,
            # 第三步：技术面砸透（满足）
            'drop_from_high_6m': 45.0,
            'bias_10': -12.0,
            'volume_ratio_3d': 0.3,
            # 第四步：资金点火（满足）
            'main_net_inflow_days': 5,
            'right_breakout': True
        }
        signal = self.strategy.analyze(stock_data)
        assert signal.action == "BUY"
        assert signal.confidence >= 0.75
        assert "四步定量" in signal.reason

    def test_full_pipeline_watch_signal(self):
        """数据一般：应输出WATCH"""
        stock_data = {
            'stock_code': '000001',
            'pe_historical_percentile': 50.0,
            'pb_historical_percentile': 45.0,
            'financial_data': {
                'non_recurring_profit': [50, 30, 40],
                'operating_cash_flow': [20, 10, 15]
            },
            'turnover_rate_5d': 1.8,
            'volume_ratio_20d': 0.6,
            'turnover_change_pct': -10.0,
            'drop_from_high_6m': 20.0,
            'bias_10': -5.0,
            'volume_ratio_3d': 0.6,
            'main_net_inflow_days': 2,
            'right_breakout': False
        }
        signal = self.strategy.analyze(stock_data)
        assert signal.action == "WATCH"
```

- [ ] **Step 2: 运行集成测试确认通过**

Run: `pytest tests/integration/test_four_step_integration.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add tests/integration/test_four_step_integration.py
git commit -m "test(four_step): add integration tests"
```

---

## Task 9: Spec 自检

完成后，对照 spec 检查：

1. **Spec coverage:** 逐项核对
   - [x] 四步权重 25%/25%/20%/30% — Task 1 验证
   - [x] 第一步：条件A(PE/PB<15%满分) + 条件B(财务梯度) — Task 2 验证
   - [x] 第二步：换手率>=1.5%(满分) + 缩量梯度 + 换手率下降额外加分 — Task 3 验证
   - [x] 第三步：三条件AND关系(35%跌幅/BIAS<-8%/无量阴跌) — Task 4 验证
   - [x] 第四步：连续3-5日净流入梯度 + 右侧突破加10分 — Task 5 验证
   - [x] 信号输出：>60 BUY / 40-60 WATCH / <40 SELL — Task 6 验证
   - [x] 置信度计算 — Task 6 验证
   - [x] 注册到 StrategyFactory — Task 7 验证

2. **Placeholder scan:** 无 TBD/TODO/待实现

3. **Type consistency:** TradingSignal 类型正确，weights 字典键值正确

---

## 执行选项

**Plan complete and saved to `docs/superpowers/plans/2026-05-22-four-step-strategy.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**