"""基本面/财务指标计算 —— 业务模块（依赖 stock_repo）

v1.3 拆分：analyzer.py 上帝类拆出来的财务层
"""
from __future__ import annotations
import math
import warnings
from typing import Any, Dict, List


# 财务字段映射（akshare 中文行名 → 统一指标名）
ROW_MAP = {
    '归母净利润': '归母净利润', '营业总收入': '营业总收入', '净利润': '净利润',
    '基本每股收益': '基本每股收益', '每股净资产': '每股净资产',
    '每股经营现金流': '每股经营现金流',
    '净资产收益率(ROE)': '净资产收益率(ROE)',
    '总资产报酬率(ROA)': '总资产报酬率(ROA)',
    '毛利率': '毛利率', '销售净利率': '销售净利率',
    '资产负债率': '资产负债率',
    '净利润同比增长率': '归属母公司净利润增长率',
    '营收同比增长率': '营业总收入增长率',
}


def _extract_from_financial_df(fin_df) -> Dict[str, float]:
    """从 akshare stock_financial_abstract 返回的 DataFrame 提取 13 项基础指标"""
    if fin_df is None or fin_df.empty or '指标' not in fin_df.columns:
        return {}
    data_col = fin_df.columns[2]
    out: Dict[str, float] = {}
    for cn_name, row_name in ROW_MAP.items():
        match = fin_df[fin_df['指标'] == row_name]
        if match.empty or data_col not in match.columns:
            continue
        val = match[data_col].iloc[0]
        if val is None or not isinstance(val, (int, float)) or math.isnan(val):
            continue
        out[cn_name] = round(float(val), 2)
    return out


def _merge_pe_pb(indicators: Dict[str, float], code: str, market: str) -> Dict[str, float]:
    """叠加 PE/PB（腾讯行情），不覆盖已有"""
    try:
        from src.repository.stock_repo import stock_repo
        ext = stock_repo.get_quote_extended(code, market)
        if ext:
            if ext.get('pe') is not None and '市盈率' not in indicators:
                indicators['市盈率'] = round(float(ext['pe']), 2)
            if ext.get('pb') is not None and '市净率' not in indicators:
                indicators['市净率'] = round(float(ext['pb']), 2)
    except Exception:
        pass
    return indicators


def _calc_peg(indicators: Dict[str, float]) -> Dict[str, float]:
    """计算 PEG（市盈率 / 净利润增速）"""
    pe = indicators.get('市盈率', 0)
    profit_growth = indicators.get('净利润同比增长率', 0)
    if isinstance(pe, (int, float)) and isinstance(profit_growth, (int, float)) and pe > 0 and profit_growth > 0:
        indicators.setdefault('PEG比率', round(pe / profit_growth, 2))
    return indicators


def calculate(code: str, market: str = "SH") -> Dict[str, Any]:
    """计算 25 项真实财务指标，失败时返回占位值"""
    if market not in ("SH", "SZ"):
        return default_result(code, market)
    warnings.filterwarnings('ignore')
    try:
        from src.repository.stock_repo import stock_repo
        fin_df = stock_repo.get_financial(code)
        indicators = _extract_from_financial_df(fin_df)
        indicators = _merge_pe_pb(indicators, code, market)
    except Exception:
        indicators = {}

    if not indicators:
        return default_result(code, market, data_unavailable=True)

    indicators = _calc_peg(indicators)

    return {
        "basic_info": {"股票代码": code, "市场": market, "股票名称": code},
        "financial_indicators": indicators,
        "valuation": {},
        "performance_forecast": [],
        "dividend_info": [],
        "industry_analysis": {},
    }


def default_result(code: str = "", market: str = "", data_unavailable: bool = False) -> Dict[str, Any]:
    """缺数据时的默认结构（兼容旧调用方）"""
    return {
        "basic_info": {"股票代码": code, "市场": market},
        "financial_indicators": {},
        "valuation": {},
        "performance_forecast": [],
        "dividend_info": [],
        "industry_analysis": {},
        "data_unavailable": data_unavailable,
    }
