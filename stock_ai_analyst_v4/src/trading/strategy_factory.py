"""策略工厂"""
from typing import Dict
from src.trading.strategies.base_strategy import BaseStrategy
from src.trading.strategies.combination import CombinationStrategy
from src.trading.strategies.turtle import TurtleStrategy
from src.trading.strategies.aberration import AberrationStrategy
from src.trading.strategies.natgator import NatGatorStrategy
from src.trading.strategies.catscan import CatscanStrategy
from src.trading.strategies.dcs2 import DCS2Strategy
from src.trading.strategies.support_resistance import SupportResistanceStrategy
from src.trading.strategies.ma_cross import MACrossStrategy
from src.trading.strategies.breakout import BreakoutStrategy
from src.trading.strategies.volume import VolumeStrategy
from src.trading.strategies.ensemble import EnsembleStrategy
from src.trading.strategies.four_step import FourStepStrategy
from src.core.models import TradingSignal


class StrategyFactory:
    """策略工厂"""

    def __init__(self, settings):
        self.settings = settings
        self._strategies = {}
        self._register_strategies()

    def _register_strategies(self):
        """注册所有策略"""
        # 现有组合策略
        self._strategies['sentiment_leader'] = CombinationStrategy(
            primary='sentiment_leader',
            secondary='chanlun_structure',
            period='short'
        )
        self._strategies['chanlun_structure'] = CombinationStrategy(
            primary='chanlun_structure',
            secondary='can_slim_trend',
            period='medium'
        )
        self._strategies['combination_short'] = CombinationStrategy(
            primary='sentiment_leader',
            secondary='chanlun_structure',
            period='short'
        )
        self._strategies['combination_medium'] = CombinationStrategy(
            primary='chanlun_structure',
            secondary='can_slim_trend',
            period='medium'
        )

        # 九大经典策略
        self._strategies['turtle'] = TurtleStrategy()
        self._strategies['aberration'] = AberrationStrategy()
        self._strategies['natgator'] = NatGatorStrategy()
        self._strategies['catscan'] = CatscanStrategy()
        self._strategies['dcs2'] = DCS2Strategy()
        self._strategies['support_resistance'] = SupportResistanceStrategy()
        self._strategies['ma_cross'] = MACrossStrategy()
        self._strategies['breakout'] = BreakoutStrategy()
        self._strategies['volume'] = VolumeStrategy()

        # 组合策略
        self._strategies['ensemble'] = EnsembleStrategy([
            TurtleStrategy(),
            MACrossStrategy(),
            BreakoutStrategy(),
            VolumeStrategy()
        ])

        # 四步定量筛股策略
        self._strategies['four_step'] = FourStepStrategy()

    def get_strategy(self, name: str) -> BaseStrategy:
        """获取指定策略"""
        return self._strategies.get(name)

    def list_strategies(self) -> Dict[str, str]:
        """列出所有可用策略"""
        return {
            'sentiment_leader': '情绪题材龙头战法',
            'chanlun_structure': '缠论结构策略',
            'can_slim_trend': 'CAN SLIM趋势策略',
            'combination_short': '短期组合策略（情绪题材+缠论）',
            'combination_medium': '中期组合策略（缠论+CAN SLIM）',
            # 九大经典策略
            'turtle': '海龟交易法则',
            'aberration': 'Aberration趋势跟踪',
            'natgator': 'NatGator大幅趋势',
            'catscan': 'Catscan趋势初期',
            'dcs2': 'DCS II中长期趋势',
            'support_resistance': '支撑压力波段',
            'ma_cross': '均线金叉死叉',
            'breakout': '突破系统',
            'volume': '成交量验证',
            'ensemble': '多策略共识 Ensemble',
            # 四步定量筛股策略
            'four_step': '四步定量筛股模型',
        }
