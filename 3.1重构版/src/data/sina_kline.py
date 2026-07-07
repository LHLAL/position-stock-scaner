"""新浪财经 K 线适配器（HTTP 直连，不依赖 akshare）"""
from __future__ import annotations
import logging
import requests
import pandas as pd
from typing import Optional

logger = logging.getLogger(__name__)


def fetch_daily_kline(code: str, market: str = "SH", datalen: int = 400) -> Optional[pd.DataFrame]:
    """从新浪财经拉日 K 线（JSON 接口）"""
    prefix = "sh" if market.upper() == "SH" else "sz"
    url = (
        f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={prefix}{code}&scale=240&ma=5&datalen={datalen}"
    )
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200 or not resp.text.strip():
            return None
        import json
        data = json.loads(resp.text)
        if not data or len(data) < 20:
            return None
        records = []
        for item in data:
            records.append({
                'date': str(item.get('day', ''))[:10],
                'open': float(item.get('open', 0)),
                'close': float(item.get('close', 0)),
                'high': float(item.get('high', 0)),
                'low': float(item.get('low', 0)),
                'volume': int(float(item.get('volume', 0))),
            })
        return pd.DataFrame(records)
    except Exception as e:
        logger.debug(f"新浪日 K 拉取失败 {code}: {e}")
        return None


def fetch_daily_then_resample_weekly(code: str, weeks: int = 60, market: str = "SH") -> Optional[pd.DataFrame]:
    """日 K → 周 K resample"""
    daily = fetch_daily_kline(code, market, datalen=weeks * 5 + 50)
    if daily is None or daily.empty:
        return None
    try:
        daily['date'] = pd.to_datetime(daily['date'])
        weekly = daily.set_index('date').resample('W').agg({
            'open': 'first',
            'close': 'last',
            'high': 'max',
            'low': 'min',
            'volume': 'sum',
        }).dropna()
        weekly = weekly.reset_index()
        weekly['date'] = weekly['date'].dt.strftime('%Y-%m-%d')
        return weekly.tail(weeks)
    except Exception as e:
        logger.debug(f"周 K resample 失败 {code}: {e}")
        return None


def fetch_minute_kline(code: str, market: str = "SH", period: str = "5") -> Optional[pd.DataFrame]:
    """从新浪财经拉分钟 K 线（period: 1/5/15/30/60）"""
    scale_map = {"1": 1, "5": 5, "15": 15, "30": 30, "60": 60}
    scale = scale_map.get(period, 5)
    prefix = "sh" if market.upper() == "SH" else "sz"
    url = (
        f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={prefix}{code}&scale={scale}&ma=5&datalen=200"
    )
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200 or not resp.text.strip():
            return None
        import json
        data = json.loads(resp.text)
        if not data or len(data) < 20:
            return None
        records = [{
            'date': str(item.get('day', ''))[:16],
            'open': float(item.get('open', 0)),
            'close': float(item.get('close', 0)),
            'high': float(item.get('high', 0)),
            'low': float(item.get('low', 0)),
            'volume': int(float(item.get('volume', 0))),
        } for item in data]
        return pd.DataFrame(records)
    except Exception as e:
        logger.debug(f"新浪分钟 K 拉取失败 {code}: {e}")
        return None
