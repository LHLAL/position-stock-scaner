"""腾讯财经 K 线适配器（HTTP 直连，不依赖 akshare/东财）

v3.1-fix: 替代原 sina_kline（sina 在代理环境下 403）。
腾讯 web.ifzq.gtimg.cn 在 verge-mihomo 代理下可用，2026-06 验证。
"""
from __future__ import annotations
import logging
import requests
import pandas as pd
from typing import Optional

logger = logging.getLogger(__name__)

_SESSION: Optional[requests.Session] = None


def _get_session() -> requests.Session:
    """复用 requests.Session（避免每次新建连接）

    ⚠️ 故意不 pop HTTP_PROXY/HTTPS_PROXY —— 系统代理（verge-mihomo:7897）
    是出网唯一通道，原 sina_kline/_clear_proxy 关掉代理导致东财/sina 全部超时。
    """
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Referer': 'https://gu.qq.com/',
        })
    return _SESSION


def _to_market_prefix(code: str, market: str) -> str:
    if str(code).lower().startswith(('sh', 'sz', 'bj')):
        return str(code).lower()
    if not market:
        market = 'SH' if str(code).startswith('6') or str(code).startswith('9') else 'SZ'
    market = market.upper()
    return f'{"sh" if market == "SH" else "sz"}{code}'


def fetch_daily_kline(code: str, market: str = "SH", datalen: int = 250) -> Optional[pd.DataFrame]:
    """从腾讯拉日 K 线（前复权）

    端点: https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600519,day,,,250,qfq
    返回 data.sh600519.qfqday: [[date, open, close, high, low, volume], ...]
    """
    full = _to_market_prefix(code, market)
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={full},day,,,{datalen},qfq'
    try:
        resp = _get_session().get(url, timeout=10)
        if resp.status_code != 200:
            logger.debug(f'腾讯日 K {code} HTTP {resp.status_code}')
            return None
        data = resp.json()
        if data.get('code') != 0:
            logger.debug(f'腾讯日 K {code} code={data.get("code")} msg={data.get("msg")}')
            return None
        rows = data.get('data', {}).get(full, {}).get('qfqday', [])
        return _rows_to_df(rows, trim_date=10) if rows else None
    except Exception as e:
        logger.warning(f'腾讯日 K 拉取失败 {code}: {e}')
        return None


def fetch_weekly_kline(code: str, market: str = "SH", datalen: int = 104) -> Optional[pd.DataFrame]:
    full = _to_market_prefix(code, market)
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={full},week,,,{datalen},qfq'
    try:
        resp = _get_session().get(url, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get('code') != 0:
            return None
        rows = data.get('data', {}).get(full, {}).get('qfqweek', [])
        return _rows_to_df(rows, trim_date=10) if rows else None
    except Exception as e:
        logger.debug(f'腾讯周 K 拉取失败 {code}: {e}')
        return None


def fetch_minute_kline(code: str, market: str = "SH", period: str = "5",
                       datalen: int = 240) -> Optional[pd.DataFrame]:
    """从腾讯拉分钟 K 线（period: 1/5/15/30/60）

    注意：腾讯 fqkline 的 m5/m15/m30/m60 在代理下被风控（code=1），
    优先尝试直拉，失败时从 1 分钟 K resample。
    """
    full = _to_market_prefix(code, market)
    scale = {'1': 1, '5': 5, '15': 15, '30': 30, '60': 60}.get(str(period), 5)

    direct = _fetch_minute_direct(full, scale, datalen)
    if direct is not None:
        return direct

    return _fetch_minute_from_1min_resampled(full, scale, datalen)


def _fetch_minute_direct(full: str, scale: int, datalen: int) -> Optional[pd.DataFrame]:
    url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={full},m{scale},,,{datalen},qfq'
    try:
        resp = _get_session().get(url, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get('code') != 0:
            return None
        rows = data.get('data', {}).get(full, {}).get(f'm{scale}', [])
        if not rows or len(rows) < 5:
            return None
        return _rows_to_df(rows, trim_date=16)
    except Exception:
        return None


def _fetch_minute_from_1min_resampled(full: str, scale: int, datalen: int) -> Optional[pd.DataFrame]:
    url = f'https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={full}'
    try:
        resp = _get_session().get(url, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        rows = data.get('data', {}).get(full, {}).get('data', {}).get('data', [])
        if not rows or len(rows) < scale:
            return None
        parsed = []
        for r in rows:
            parts = str(r).split()
            if len(parts) < 2:
                continue
            parsed.append({'time': parts[0], 'price': float(parts[1])})
        if not parsed:
            return None
        minute_df = pd.DataFrame(parsed)
        today = pd.to_datetime('today').strftime('%Y-%m-%d')
        minute_df['datetime'] = pd.to_datetime(
            today + ' ' + minute_df['time'], format='%Y-%m-%d %H%M'
        )
        agg = (minute_df
               .set_index('datetime')['price']
               .resample(f'{scale}min')
               .agg(['first', 'last', 'max', 'min'])
               .dropna())
        agg.columns = ['open', 'close', 'high', 'low']
        agg = agg.reset_index()
        agg['date'] = agg['datetime'].dt.strftime('%Y-%m-%d %H:%M')
        agg['volume'] = 0
        out = agg[['date', 'open', 'close', 'high', 'low', 'volume']]
        return out.tail(datalen // scale)
    except Exception as e:
        logger.debug(f'腾讯分钟 K 兜底失败 {full}: {e}')
        return None


def _rows_to_df(rows, trim_date: int = 10) -> pd.DataFrame:
    """腾讯 fqkline 行 → 标准 DataFrame

    腾讯格式: [date, open, close, high, low, volume] — close 在 [2]，非 [3]。
    """
    return pd.DataFrame([{
        'date': str(r[0])[:trim_date],
        'open': float(r[1]),
        'close': float(r[2]),
        'high': float(r[3]),
        'low': float(r[4]),
        'volume': int(float(r[5])),
    } for r in rows])
