"""行业/板块数据源 —— 百度 + 同花顺"""
from __future__ import annotations
import logging
import requests
from typing import Dict, List, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def get_industry_and_concept(code: str) -> Dict:
    """单只股票的行业/概念板块信息（百度金融）

    Returns:
        {'industry': [{'name', 'change_pct'}, ...], 'concept': [...]}
    """
    url = f"https://finance.pae.baidu.com/api/getrelatedblock?code={code}&market=ab&typeCode=all&finClientType=pc"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Host': 'finance.pae.baidu.com',
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        if str(data.get("ResultCode", -1)) != "0":
            return {'industry': [], 'concept': []}
        result: Dict[str, List] = {'industry': [], 'concept': []}
        for block in data.get("Result", []):
            block_type = block.get("type", "")
            for item in block.get("list", []):
                entry = {
                    'name': item.get('name', ''),
                    'change_pct': item.get('increase', ''),
                }
                if "行业" in block_type:
                    result['industry'].append(entry)
                elif "概念" in block_type:
                    result['concept'].append(entry)
        return result
    except Exception as e:
        logger.debug(f"百度板块查询失败 {code}: {e}")
        return {'industry': [], 'concept': []}


def get_sector_3d_trend(sector_name: str) -> float:
    """板块 3 日涨跌幅（同花顺）—— 单次 HTTP 拉全市场"""
    try:
        import akshare as ak
        # 清除代理
        for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
            import os
            os.environ.pop(k, None)
        os.environ['no_proxy'] = '*'
        df = ak.stock_board_industry_summary_ths()
        if df is None or df.empty:
            return 0
        matches = df[df['板块'].str.contains(sector_name, na=False)]
        if matches.empty:
            return 0
        change = matches.iloc[0].get('涨跌幅', 0)
        return float(change) if change else 0
    except Exception as e:
        logger.debug(f"板块趋势查询失败 {sector_name}: {e}")
        return 0
