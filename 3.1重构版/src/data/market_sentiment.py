"""市场情绪 / 板块热度 数据源（直连东财 + 腾讯，零 AkShare）

参考 a-stock-data SKILL：
- Layer 5.x 大盘涨/跌家数、涨停/跌停
- Layer 5.6 板块涨幅榜
- Layer 5.7 板块资金流入
- Layer 3.4 同花顺北向
"""

import logging
import random
import time
from typing import Dict, List, Optional

import requests

from .eastmoney_http import em_get, northbound_realtime

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})

# 大盘指数列表（沪市/深市/创业板/科创板 4 大指数）
INDEX_CODES = {
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sz399006": "创业板指",
    "sh000688": "科创50",
}

# 板块行业列表（东财接口）
SECTOR_LIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
SECTOR_FLOW_URL = "https://push2.eastmoney.com/api/qt/clist/get"


def _tencent_index_quote(symbol: str) -> Optional[dict]:
    """腾讯拉一只指数的实时报价（不依赖 AkShare）"""
    try:
        r = requests.get(
            f"https://qt.gtimg.cn/q={symbol}",
            headers={"User-Agent": UA, "Referer": "https://finance.qq.com/"},
            timeout=5,
        )
        text = r.text.strip()
        if '="' not in text:
            return None
        fields = text.split('="', 1)[1].rstrip('";').split('~')
        if len(fields) < 35:
            return None

        def _f(i):
            try:
                v = fields[i]
                return float(v) if v else 0.0
            except (ValueError, IndexError):
                return 0.0

        name = fields[1] if len(fields) > 1 else symbol
        return {
            "symbol": symbol,
            "name": name,
            "price": _f(3),
            "change": _f(31),
            "change_pct": _f(32),
            "open": _f(5),
            "high": _f(33),
            "low": _f(34),
            "volume": _f(6),
            "amount": _f(37),  # 成交额（亿）
        }
    except Exception as e:
        logger.warning(f"tencent index quote failed for {symbol}: {e}")
        return None


def fetch_market_indices() -> List[dict]:
    """4 大指数实时报价"""
    out = []
    for sym, name in INDEX_CODES.items():
        q = _tencent_index_quote(sym)
        if q:
            out.append(q)
    return out


def fetch_advance_decline() -> dict:
    """东财 push2：全市场涨/跌/平家数 + 涨停/跌停数

    接口: f14/f3/f12 等字段映射在 push2 文档里
    """
    try:
        # 沪深京全市场快照
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": 1, "pz": 1, "po": 1, "np": 1,
            "fltt": 2, "invt": 2,
            "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
            "fields": "f1,f2,f3,f4,f8,f9,f10,f12,f13,f14,f23",
            "_": int(time.time() * 1000),
        }
        # 用 em_get（节流）
        r = em_get(url, params=params, headers={"Referer": "https://quote.eastmoney.com/"}, timeout=10)
        d = r.json()

        # 全市场统计接口
        url2 = "https://push2.eastmoney.com/api/qt/clist/get"
        # 用 dpks / dpss 字段（涨家数 / 跌家数 / 平家数 / 涨停 / 跌停）
        params2 = {
            "fid": "f3",
            "po": 1, "pz": 1, "pn": 1, "np": 1, "fltt": 2, "invt": 2,
            "fs": "m:0+t:6+f:!2,m:0+t:80+f:!2,m:1+t:2+f:!2,m:1+t:23+f:!2",
            "fields": "f1,f2,f3,f4,f8,f9,f10,f12,f13,f14,f23,f104,f105,f106,f107,f128",
            "_": int(time.time() * 1000),
        }
        r2 = em_get(url2, params=params2, headers={"Referer": "https://quote.eastmoney.com/"}, timeout=10)
        d2 = r2.json().get("data") or {}

        return {
            "up_count":        d2.get("f104", 0) or 0,
            "down_count":      d2.get("f105", 0) or 0,
            "flat_count":      d2.get("f128", 0) or 0,
            "limit_up":        d2.get("f106", 0) or 0,
            "limit_down":      d2.get("f107", 0) or 0,
            "total":           d2.get("f1", 0) or 0,
        }
    except Exception as e:
        logger.warning(f"advance_decline unavailable: {e}")
        return {"up_count": 0, "down_count": 0, "flat_count": 0, "limit_up": 0, "limit_down": 0, "total": 0}


def fetch_sector_ranking(top_n: int = 10, asc: bool = False) -> List[dict]:
    """板块涨幅榜 / 跌幅榜（东财行业板块）

    使用 a-stock-data §3.7 验证过的写法：一次取全行业，再本地取 top/bottom。
    asc=False 涨幅榜; asc=True 跌幅榜
    """
    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "pn": "1", "pz": "100", "po": "1", "np": "1",
            "fltt": "2", "invt": "2",
            "fs": "m:90+t:2",
            "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207",
        }
        r = em_get(url, params=params, headers={"User-Agent": UA}, timeout=15)
        d = r.json()
        items = (d.get("data") or {}).get("diff", []) or []
        rows = []
        for i, item in enumerate(items):
            rows.append({
                "rank": i + 1,
                "code": item.get("f12", ""),
                "name": item.get("f14", ""),
                "change_pct": round(float(item.get("f3", 0) or 0), 2),
                "change": round(float(item.get("f4", 0) or 0), 2),
                "up_count": item.get("f104", 0) or 0,
                "down_count": item.get("f105", 0) or 0,
                "lead_stock": item.get("f140", "") or "",
                "lead_pct": round(float(item.get("f136", 0) or 0), 2),
            })
        if asc:
            return sorted(rows, key=lambda x: x["change_pct"])[:top_n]
        return sorted(rows, key=lambda x: x["change_pct"], reverse=True)[:top_n]
    except Exception as e:
        logger.warning(f"sector ranking failed: {e}")
        return []


def fetch_sector_funds(top_n: int = 10, asc: bool = False) -> List[dict]:
    """板块主力资金流入/流出榜（东财 push2）

    f62 主力净额 / f184 主力净占比 / f66 超大单净额
    """
    try:
        url = "https://push2.eastmoney.com/api/qt/clist/get"
        params = {
            "fid": "f62",
            "po": 1 if asc else 0,
            "pz": top_n,
            "pn": 1,
            "np": 1,
            "fltt": 2,
            "invt": 2,
            "fs": "m:90+t:2",
            "fields": "f1,f2,f3,f12,f14,f62,f66,f69,f72,f184",
            "_": int(time.time() * 1000),
        }
        r = em_get(url, params=params, headers={"Referer": "https://quote.eastmoney.com/"}, timeout=10)
        d = r.json()
        rows = (d.get("data") or {}).get("diff", []) or []
        out = []
        for row in rows:
            out.append({
                "code":       row.get("f12", ""),
                "name":       row.get("f14", ""),
                "change_pct": round(float(row.get("f3", 0) or 0), 2),
                "main_net":   round(float(row.get("f62", 0) or 0) / 1e8, 2),  # 亿
                "super_net":  round(float(row.get("f66", 0) or 0) / 1e8, 2),
                "big_net":    round(float(row.get("f69", 0) or 0) / 1e8, 2),
                "mid_net":    round(float(row.get("f72", 0) or 0) / 1e8, 2),
                "main_pct":   round(float(row.get("f184", 0) or 0), 2),
            })
        return out
    except Exception as e:
        logger.warning(f"sector funds unavailable: {e}")
        return []


def fetch_stock_sector(code: str) -> str:
    """个股所属行业（东财 F10 公司概况）

    返回板块名；失败返回 '—'
    """
    try:
        # 6/9 开头沪市(1.)，其他深市(0.)，8/4 北交所(0.)
        if code.startswith(("6", "9")):
            market = "SH"
        elif code.startswith(("8", "4")):
            market = "BJ"
        else:
            market = "SZ"
        url = f"https://emweb.eastmoney.com/PC_HSF10/CompanySurvey/PageAjax"
        params = {"code": f"{market}{code}"}
        r = requests.get(url, params=params, headers={"User-Agent": UA, "Referer": "https://emweb.eastmoney.com/"}, timeout=8)
        d = r.json()
        jbzl = (d.get("jbzl") or [])
        if not jbzl:
            return '—'
        return jbzl[0].get("EM2016", "") or '—'  # 行业-子行业-细分（如 互联网-互联网服务-网络媒体）
    except Exception as e:
        logger.debug(f"stock sector lookup failed for {code}: {e}")
        return '—'


def build_market_overview() -> dict:
    """汇总：大盘情绪 + 板块涨跌 + 板块资金 + 北向"""
    indices = fetch_market_indices()
    ad = fetch_advance_decline()
    sector_top = fetch_sector_ranking(top_n=5, asc=False)
    sector_bot = fetch_sector_ranking(top_n=5, asc=True)
    sector_inflow = fetch_sector_funds(top_n=5, asc=False)
    sector_outflow = fetch_sector_funds(top_n=5, asc=True)
    nb = northbound_realtime()
    political_sector_impact = []
    try:
        from .news_sources import analyze_political_sector_impact
        political_sector_impact = analyze_political_sector_impact(page_size=80, top_n=8)
    except Exception as e:
        logger.warning(f"political sector impact unavailable: {e}")

    # 情绪温度计：-100..+100
    if ad["total"]:
        up_pct = ad["up_count"] / ad["total"] * 100
        dn_pct = ad["down_count"] / ad["total"] * 100
    else:
        up_pct = dn_pct = 0
    # 涨/跌家数差 + 涨跌停差 + 指数平均涨跌
    avg_idx_pct = (sum(x["change_pct"] for x in indices) / len(indices)) if indices else 0
    thermometer = round(
        (up_pct - dn_pct) * 0.4 +
        (ad.get("limit_up", 0) - ad.get("limit_down", 0)) * 2.0 +
        avg_idx_pct * 5.0
    , 1)
    thermometer = max(-100, min(100, thermometer))
    if thermometer >= 60:
        mood = "极度贪婪"
    elif thermometer >= 30:
        mood = "贪婪"
    elif thermometer >= 0:
        mood = "偏多"
    elif thermometer >= -30:
        mood = "偏空"
    elif thermometer >= -60:
        mood = "恐慌"
    else:
        mood = "极度恐慌"

    return {
        "indices": indices,
        "advance_decline": ad,
        "sector_top": sector_top,
        "sector_bot": sector_bot,
        "sector_inflow": sector_inflow,
        "sector_outflow": sector_outflow,
        "northbound": nb,
        "political_sector_impact": political_sector_impact,
        "thermometer": thermometer,
        "mood": mood,
    }
