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

    def test_step1_valuation_low_pe_passes(self):
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
        # 条件A满分(25) + 条件B梯度(1.1*25=27.5)
        assert result == 52.5

    def test_step1_valuation_high_pe_fails_condition_a(self):
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
        # 条件A=0, 条件B梯度(1.1*25=27.5)
        assert result == pytest.approx(27.5)

    def test_step1_no_data_returns_zero(self):
        """数据不足返回0"""
        stock_data = {'stock_code': '000001'}
        result = self.strategy._calc_step1(stock_data)
        assert result == 0.0

    def test_step2_turnover_and_volume(self):
        """换手率>=1.5% + 缩量通过，得满分"""
        stock_data = {
            'turnover_rate_5d': 2.5,  # >= 1.5%
            'volume_ratio_20d': 0.4,  # < 50%
            'turnover_change_pct': -40.0  # 较30日前下降>30%
        }
        result = self.strategy._calc_step2(stock_data)
        # 条件A满分(25) + 条件B梯度(1.0*25=25) + 额外加分(5) = 55
        assert result == 55.0

    def test_step2_low_turnover_fails(self):
        """换手率<1.5%，条件A不满足，但缩量满足"""
        stock_data = {
            'turnover_rate_5d': 0.5,
            'volume_ratio_20d': 0.3,
            'turnover_change_pct': -20.0
        }
        result = self.strategy._calc_step2(stock_data)
        # 条件A=0, 条件B梯度(1.0*25=25)
        assert result == 25.0

    def test_step3_all_conditions_met(self):
        """三个条件均满足，得满分20"""
        stock_data = {
            'drop_from_high_6m': 45.0,   # > 35%
            'bias_10': -12.0,            # < -8%
            'volume_ratio_3d': 0.3       # < 50%
        }
        result = self.strategy._calc_step3(stock_data)
        assert result == 20.0

    def test_step3_one_condition_fails(self):
        """BIAS=-5%（不满足），只得空间急跌分8分"""
        stock_data = {
            'drop_from_high_6m': 40.0,
            'bias_10': -5.0,
            'volume_ratio_3d': 0.8  # 0.8 >= 0.5，不满足
        }
        result = self.strategy._calc_step3(stock_data)
        assert result == 8.0  # 空间急跌8分，其他0分

    def test_step4_five_consecutive_days_plus_breakout(self):
        """连续5日净流入 + 右侧突破 = 满分30分"""
        stock_data = {
            'main_net_inflow_days': 5,    # 连续5日
            'right_breakout': True        # 放量突破5日均线
        }
        result = self.strategy._calc_step4(stock_data)
        assert result == 30.0  # 18 + 10 + 2(额外加分)

    def test_step4_three_days_no_breakout(self):
        """连续3日净流入，无突破 = 10.8分"""
        stock_data = {
            'main_net_inflow_days': 3,
            'right_breakout': False
        }
        result = self.strategy._calc_step4(stock_data)
        assert result == pytest.approx(10.8)  # 18*0.6

    def test_analyze_buy_signal(self):
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
        assert "总分" in signal.reason

    def test_analyze_watch_signal(self):
        """总分在40-60之间，输出WATCH"""
        stock_data = {
            'stock_code': '000001',
            'pe_historical_percentile': 50.0,  # 中等估值
            'financial_data': {
                'non_recurring_profit': [0, 0, 0],  # 都是0，得分0
                'operating_cash_flow': [0, 0, 0]
            },
            'turnover_rate_5d': 2.0,  # >=1.5, 得25
            'volume_ratio_20d': 0.35,  # <0.5, 得25
            'turnover_change_pct': -40.0,  # <-30%, +5
            'drop_from_high_6m': 0.0,  # 0
            'bias_10': 0.0,  # 0
            'volume_ratio_3d': 1.0,  # 1.0
            'main_net_inflow_days': 0,  # 0
            'right_breakout': False
        }
        signal = self.strategy.analyze(stock_data)
        assert signal.action == "WATCH"

    def test_analyze_sell_signal(self):
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