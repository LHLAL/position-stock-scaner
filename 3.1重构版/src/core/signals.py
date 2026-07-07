"""市场信号生成器"""
from typing import Dict, List, Optional
import pandas as pd

from src.repository.stock_repo import stock_repo

class SignalsGenerator:
    """市场信号生成器"""

    def __init__(self):
        self.ths = stock_repo.get_ths_source()
        self.baidu = stock_repo.get_baidu_source()
        self.eastmoney = stock_repo.get_eastmoney_source()

    def get_hot_stocks(self, date: str = None) -> pd.DataFrame:
        """获取今日热点股票"""
        return self.ths.get_hot_stocks(date)

    def get_concept_blocks(self, code: str) -> Dict:
        """获取股票概念板块"""
        return self.baidu.get_concept_blocks(code)

    def get_fund_flow(self, code: str, date: str = None) -> Dict:
        """获取个股资金流向"""
        return self.baidu.get_fund_flow(code, date)

    def get_fund_flow_signal(self) -> list:
        """获取全市场资金流向信号（简洁格式，适配 /api/signals/all）"""
        try:
            nb = self.eastmoney.get_northbound()
            nb_total = nb.get('total_yi', None) if nb else None
            result = []
            if nb_total is not None:
                result.append({
                    'type': 'northbound',
                    'value': nb_total,
                    'unit': '亿',
                    'direction': '流入' if nb_total > 0 else '流出',
                    'description': f"北向资金{'净流入' if nb_total > 0 else '净流出'} {abs(nb_total):.1f}亿",
                })
            return result
        except Exception:
            return []

    def get_industry_comparison(self, top_n: int = 10) -> pd.DataFrame:
        """获取行业对比"""
        return self.ths.get_industry_comparison(top_n)

    def get_northbound(self) -> Dict:
        """获取北向资金"""
        return self.eastmoney.get_northbound()

    def get_dragon_tiger(self, code: str = None, date: str = None, look_back: int = 30) -> Dict:
        """获取龙虎榜"""
        return self.eastmoney.get_daily_dragon_tiger(code, date, look_back)

    def get_lockup_expiry(self, stock_code: str = None, forward_days: int = 90) -> Dict:
        """获取限售股解禁"""
        return self.eastmoney.get_lockup_expiry(stock_code, forward_days)

    def get_research_reports(self, code: str, max_pages: int = 3) -> List[Dict]:
        """获取研报"""
        return self.eastmoney.get_research_reports(code, max_pages)