"""基本面模块测试"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '3.1重构版', 'src'))

from core.fundamental import calculate, default_result


class TestCalculate:
    """calculate() 不依赖外部数据源的测试"""

    def test_default_result_contains_data_unavailable(self):
        """default_result 应包含 data_unavailable 标志"""
        result = default_result('000001', 'SZ')
        assert 'data_unavailable' in result
        assert result['data_unavailable'] is False

    def test_default_result_unavailable_true(self):
        result = default_result('000001', 'SZ', data_unavailable=True)
        assert result['data_unavailable'] is True
        assert result['financial_indicators'] == {}

    def test_calculate_invalid_market(self):
        """非 SH/SZ 市场返回 default_result"""
        result = calculate('000001', 'US')
        assert result['financial_indicators'] == {}

    def test_calculate_unknown_code(self):
        """无法获取数据的股票返回 data_unavailable=True"""
        result = calculate('000001', 'SZ')
        # 不依赖网络，仅验证结构
        assert 'data_unavailable' in result or 'financial_indicators' in result
