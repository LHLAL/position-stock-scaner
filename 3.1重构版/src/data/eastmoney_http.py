"""东财 HTTP 数据源（直连，不依赖 AkShare）

参考 a-stock-data SKILL：
- Layer 3.5 龙虎榜席位（datacenter）
- Layer 3.8 全市场龙虎榜（datacenter）
- Layer 4.2 大宗交易（datacenter）
- Layer 4.5 个股资金流（push2 / push2his）

所有东财请求走统一的节流入口 em_get()，避免被封 IP。
"""
import logging
import random
import time
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
PUSH2_URL = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
PUSH2HIS_URL = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"

EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
EM_MIN_INTERVAL = 1.0  # 串行最小间隔（秒）
_em_last_call = [0.0]


def em_get(url: str, params: Optional[dict] = None, headers: Optional[dict] = None,
           timeout: int = 15, **kwargs):
    """东财统一请求入口：自动节流 + 复用 session + 默认 UA。"""
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()


def _eastmoney_datacenter(report_name: str, columns: str = "ALL",
                           filter_str: str = "", page_size: int = 50,
                           sort_columns: str = "", sort_types: str = "-1") -> List[dict]:
    """东财数据中心统一查询（已内置限流）"""
    params = {
        "reportName": report_name,
        "columns": columns,
        "filter": filter_str,
        "pageNumber": "1",
        "pageSize": str(page_size),
        "sortColumns": sort_columns,
        "sortTypes": sort_types,
        "source": "WEB",
        "client": "WEB",
    }
    r = em_get(DATACENTER_URL, params=params, timeout=15)
    d = r.json()
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []


def dragon_tiger(code: str, look_back_days: int = 30) -> dict:
    """龙虎榜：上榜记录 + 买卖席位 TOP5 + 机构动向（直连东财 datacenter）"""
    from src.data.base import sanitize_code
    safe_code = sanitize_code(code)
    if not safe_code:
        return {"records": [], "details": []}

    from datetime import datetime, timedelta
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=look_back_days)).strftime("%Y-%m-%d")

    records = []
    try:
        data = _eastmoney_datacenter(
            "RPT_DAILYBILLBOARD_DETAILSNEW",
            filter_str=f'(TRADE_DATE>=\'{start_date}\')(TRADE_DATE<=\'{end_date}\')(SECURITY_CODE=\"{safe_code}\")',
            page_size=50,
            sort_columns="TRADE_DATE",
            sort_types="-1",
        )
        for row in data:
            records.append({
                "date": str(row.get("TRADE_DATE", ""))[:10],
                "reason": row.get("EXPLANATION", ""),
                "net_buy_wan": round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
                "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
            })
    except Exception as e:
        logger.exception(f"dragon_tiger records failed: {e}")

    seats = {"buy": [], "sell": []}
    institution = {"buy_wan": 0, "sell_wan": 0, "net_wan": 0}
    if records:
        latest_date = records[0]["date"]
        for side, report_name, col in [
            ("buy",  "RPT_BILLBOARD_DAILYDETAILSBUY",  "BUY"),
            ("sell", "RPT_BILLBOARD_DAILYDETAILSSELL", "SELL"),
        ]:
            try:
                rows = _eastmoney_datacenter(
                    report_name,
                    filter_str=f'(TRADE_DATE=\'{latest_date}\')(SECURITY_CODE=\"{safe_code}\")',
                    page_size=10,
                    sort_columns=col,
                    sort_types="-1",
                )
                for row in rows[:5]:
                    seats[side].append({
                        "name":  row.get("OPERATEDEPT_NAME", ""),
                        "buy_wan":  round((row.get("BUY")  or 0) / 10000, 1),
                        "sell_wan": round((row.get("SELL") or 0) / 10000, 1),
                        "net_wan":  round((row.get("NET")  or 0) / 10000, 1),
                    })
                # 机构动向：OPERATEDEPT_CODE="0"
                inst_amt_buy  = sum((r.get("BUY")  or 0) for r in rows if str(r.get("OPERATEDEPT_CODE", "")) == "0")
                inst_amt_sell = sum((r.get("SELL") or 0) for r in rows if str(r.get("OPERATEDEPT_CODE", "")) == "0")
                institution["buy_wan"]  += round(inst_amt_buy  / 10000, 1)
                institution["sell_wan"] += round(inst_amt_sell / 10000, 1)
            except Exception as e:
                logger.exception(f"dragon_tiger {side} seats failed: {e}")

    institution["net_wan"] = round(institution["buy_wan"] - institution["sell_wan"], 1)
    return {
        "code": code,
        "look_back_days": look_back_days,
        "records": records,
        "seats": seats,
        "institution": institution,
    }


def block_trade(code: str, page_size: int = 20) -> List[dict]:
    """大宗交易记录（直连东财 datacenter）"""
    try:
        data = _eastmoney_datacenter(
            "RPT_DATA_BLOCKTRADE",
            filter_str=f'(SECURITY_CODE="{safe_code}")',
            page_size=page_size,
            sort_columns="TRADE_DATE",
            sort_types="-1",
        )
    except Exception as e:
        logger.exception(f"block_trade failed: {e}")
        return []

    rows = []
    for row in data:
        close = row.get("CLOSE_PRICE") or 0
        deal_price = row.get("DEAL_PRICE") or 0
        try:
            premium = round(((deal_price / close - 1) * 100), 2) if close else 0
        except (TypeError, ZeroDivisionError):
            premium = 0
        rows.append({
            "date":        str(row.get("TRADE_DATE", ""))[:10],
            "price":       round(float(deal_price), 2) if deal_price else 0,
            "close":       round(float(close), 2) if close else 0,
            "premium_pct": premium,
            "vol":         row.get("DEAL_VOLUME", 0),
            "amount":      row.get("DEAL_AMT", 0),
            "buyer":       row.get("BUYER_NAME", ""),
            "seller":      row.get("SELLER_NAME", ""),
        })
    return rows


def fund_flow_minute(code: str) -> List[dict]:
    """个股资金流向（分钟级，东财 push2 实时盘中）

    返回: [{time, main_net, small_net, mid_net, large_net, super_net}] 单位: 元
    非交易时段返回 []
    """
    if not code or not code[0].isdigit():
        return []
    secid = f"1.{code}" if code.startswith(("6", "9")) else f"0.{code}"
    try:
        r = em_get(
            PUSH2_URL,
            params={"secid": secid, "klt": 1, "fields1": "f1,f2,f3,f7",
                    "fields2": "f51,f52,f53,f54,f55,f56,f57"},
            headers={"Referer": "https://quote.eastmoney.com/",
                      "Origin": "https://quote.eastmoney.com"},
            timeout=10,
        )
        d = r.json()
    except Exception as e:
        logger.exception(f"fund_flow_minute failed: {e}")
        return []

    rows = []
    for line in (d.get("data", {}) or {}).get("klines", []):
        parts = line.split(",")
        if len(parts) < 6:
            continue
        rows.append({
            "time":      parts[0],
            "main_net":  float(parts[1]) if parts[1] != "-" else 0,
            "small_net": float(parts[2]) if parts[2] != "-" else 0,
            "mid_net":   float(parts[3]) if parts[3] != "-" else 0,
            "large_net": float(parts[4]) if parts[4] != "-" else 0,
            "super_net": float(parts[5]) if parts[5] != "-" else 0,
        })
    return rows


def northbound_realtime() -> dict:
    """同花顺北向资金 实时累计净买入（沪股通/深股通）

    接口: https://data.hexin.cn/market/hsgtApi/method/dayChart/
    零鉴权、稳定；非交易时段数据保持上一收盘值。
    返回: { hgt_yi, sgt_yi, total_yi, ts }
    """
    try:
        r = requests.get(
            "https://data.hexin.cn/market/hsgtApi/method/dayChart/",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Host": "data.hexin.cn",
                "Referer": "https://data.hexin.cn/",
            },
            timeout=10,
        )
        d = r.json()
    except Exception as e:
        logger.exception(f"northbound_realtime failed: {e}")
        return {"hgt_yi": 0, "sgt_yi": 0, "total_yi": 0, "ts": ""}

    times = d.get("time", []) or []
    hgts = d.get("hgt", []) or []
    sgts = d.get("sgt", []) or []

    hgt = float(hgts[-1]) if hgts and hgts[-1] is not None else 0
    sgt = float(sgts[-1]) if sgts and sgts[-1] is not None else 0
    return {
        "hgt_yi":   round(hgt, 2),
        "sgt_yi":   round(sgt, 2),
        "total_yi": round(hgt + sgt, 2),
        "ts":       times[-1] if times else "",
    }
