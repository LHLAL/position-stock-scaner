"""四步定量筛股策略集成测试"""
import pytest
from unittest.mock import MagicMock
from src.trading.strategy_factory import StrategyFactory


class TestFourStepIntegration:
    def setup_method(self):
        settings = MagicMock()
        self.factory = StrategyFactory(settings)
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
        assert "总分" in signal.reason

    def test_full_pipeline_watch_signal(self):
        """数据一般：应输出WATCH"""
        stock_data = {
            'stock_code': '000001',
            'pe_historical_percentile': 50.0,
            'financial_data': {
                'non_recurring_profit': [0, 0, 0],
                'operating_cash_flow': [0, 0, 0]
            },
            'turnover_rate_5d': 2.0,
            'volume_ratio_20d': 0.35,
            'turnover_change_pct': -40.0,
            'drop_from_high_6m': 0.0,
            'bias_10': 0.0,
            'volume_ratio_3d': 1.0,
            'main_net_inflow_days': 0,
            'right_breakout': False
        }
        signal = self.strategy.analyze(stock_data)
        assert signal.action == "WATCH"