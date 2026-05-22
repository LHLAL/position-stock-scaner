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