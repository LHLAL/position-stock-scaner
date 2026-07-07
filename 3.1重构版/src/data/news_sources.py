"""个股新闻 + 板块政策新闻（直连 HTTP，零 AkShare）

参考 a-stock-data SKILL（2026-06 验证）：
- §5.1 东财个股新闻（search-api-web JSONP）
- §5.3 东财全球资讯（np-weblist 7×24 滚动）— 替代已下线的财联社
- §6.x 板块相关公告
"""

import json
import logging
import re
import time
import uuid
from typing import Dict, List, Optional

import requests

from .eastmoney_http import em_get

logger = logging.getLogger(__name__)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})


# ── §5.1 东财个股新闻（JSONP） ──
def fetch_eastmoney_stock_news(code: str, page_size: int = 20) -> List[dict]:
    """东财个股新闻（JSONP 接口，按股票代码搜索）"""
    try:
        url = "https://search-api-web.eastmoney.com/search/jsonp"
        inner_params = json.dumps({
            "uid": "",
            "keyword": code,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default",
                      "pageIndex": 1, "pageSize": page_size, "preTag": "", "postTag": ""}},
        }, separators=(',', ':'))
        params = {"cb": "jQuery_news", "param": inner_params}
        r = em_get(url, params=params, headers={"User-Agent": UA, "Referer": "https://so.eastmoney.com/"}, timeout=12)
        text = r.text
        if "(" not in text or ")" not in text:
            return []
        json_str = text[text.index("(") + 1 : text.rindex(")")]
        d = json.loads(json_str)
        articles = d.get("result", {}).get("cmsArticleWebOld", []) or []
        out = []
        for a in articles:
            out.append({
                "title":   re.sub(r'<[^>]+>', '', a.get("title", "")),
                "content": re.sub(r'<[^>]+>', '', a.get("content", ""))[:200],
                "date":    a.get("date", ""),
                "source":  a.get("mediaName", "东方财富"),
                "url":     a.get("url", ""),
                "category": "个股新闻",
            })
        return out
    except Exception as e:
        logger.warning(f"eastmoney stock news failed for {code}: {e}")
        return []


# ── §5.2 财联社电报（直连 cls.cn · 2026-06 重新可用）──
CLS_CACHE_URL = "https://www.cls.cn/api/cache"
CLS_ROLL_URL  = "https://www.cls.cn/v1/roll/get_roll_list"
# 两个接口的公开 sign 都不一样；任一接口拿不到数据自动降级到东财 7×24
CLS_CACHE_SIGN = "24768359f4c5f403f754bcd3ac6b5f4d"
CLS_ROLL_SIGN  = "e11ef7d616d8f9a2f056e6df1aefc4d4"
CLS_SV = "8.7.9"


def _parse_cls_roll(roll: List[dict]) -> List[dict]:
    out = []
    for x in roll:
        title = (x.get("title") or "").strip() or (x.get("brief") or "").strip()
        content = re.sub(r"<[^>]+>", "", x.get("content") or "")[:300]
        ts = x.get("ctime")
        if isinstance(ts, (int, float)):
            from datetime import datetime
            date = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
        else:
            date = str(ts)[:16] if ts else ""
        subjects = x.get("subjects") or []
        subj_names = ",".join([s.get("subject_name", "") for s in subjects[:3] if s.get("subject_name")])
        out.append({
            "title":     title,
            "content":   content,
            "date":      date,
            "source":    "财联社",
            "url":       f"https://www.cls.cn/detail/{x.get('id', '')}",
            "subjects":  subj_names,
            "ctime":     ts,
            "category":  "财联社电报",
        })
    return out


def fetch_cls_telegraph(page_size: int = 30, last_time: int = 0) -> List[dict]:
    """财联社电报（7×24 实时快讯）

    - 首发：/api/cache?lastTime=0 拿最新 20 条历史
    - 增量：/v1/roll/get_roll_list?last_time=最新ctime 翻页
    任一接口失败/签名失效自动回退东财 7×24，避免阻塞主流程
    """
    # 1) 先用 /v1/roll/get_roll_list 拿增量（实时）
    try:
        params = {
            "app": "CailianpressWeb",
            "last_time": str(last_time),
            "os": "web",
            "refresh_type": "1",
            "rn": str(page_size),
            "sv": CLS_SV,
            "sign": CLS_ROLL_SIGN,
        }
        r = em_get(
            CLS_ROLL_URL, params=params,
            headers={"User-Agent": UA, "Referer": "https://www.cls.cn/telegraph", "Host": "www.cls.cn"},
            timeout=10,
        )
        d = r.json()
        if d.get("errno") in (0, None) and (d.get("data") or {}).get("roll_data"):
            return _parse_cls_roll(d["data"]["roll_data"])
        logger.warning(f"cls roll errno={d.get('errno')} msg={d.get('msg')}, fallback to cache")
    except Exception as e:
        logger.warning(f"cls roll failed: {e}, fallback to cache")

    # 2) 回退到 /api/cache（拿历史首批 20 条）
    try:
        params = {
            "app": "CailianpressWeb",
            "lastTime": str(last_time),
            "name": "telegraphList",
            "os": "web",
            "sv": CLS_SV,
            "sign": CLS_CACHE_SIGN,
        }
        r = em_get(
            CLS_CACHE_URL, params=params,
            headers={"User-Agent": UA, "Referer": "https://www.cls.cn/telegraph", "Host": "www.cls.cn"},
            timeout=10,
        )
        d = r.json()
        if d.get("errno") in (0, None) and (d.get("data") or {}).get("roll_data"):
            return _parse_cls_roll(d["data"]["roll_data"])
        logger.warning(f"cls cache errno={d.get('errno')} msg={d.get('msg')}")
    except Exception as e:
        logger.warning(f"cls cache failed: {e}")

    # 3) 全部失败时回退东财 7×24
    return []


# ── §5.3 东财全球资讯（7×24 滚动）──
def fetch_eastmoney_global_news(page_size: int = 50) -> List[dict]:
    """东财 7×24 全球财经快讯（替代已下线的财联社电报）"""
    try:
        url = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
        params = {
            "client": "web", "biz": "web_724",
            "fastColumn": "102", "sortEnd": "",
            "pageSize": str(page_size),
            "req_trace": str(uuid.uuid4()),
        }
        r = em_get(url, params=params, headers={"User-Agent": UA, "Referer": "https://kuaixun.eastmoney.com/"}, timeout=10)
        d = r.json()
        rows = []
        for item in (d.get("data", {}) or {}).get("fastNewsList", []):
            rows.append({
                "title":   item.get("title", ""),
                "content": (item.get("summary") or "")[:200],
                "date":    item.get("showTime", ""),
                "source":  "东方财富 7×24",
                "url":     item.get("url") or "",
                "category": "全球快讯",
            })
        return rows
    except Exception as e:
        logger.warning(f"eastmoney global news failed: {e}")
        return []


# ── 行业/政策新闻（按行业关键词筛全球快讯）──
POLICY_KEYWORDS = [
    "政策", "央行", "证监会", "国务院", "工信部", "发改委", "财政部",
    "减税", "降准", "降息", "LPR", "MLF", "回购", "增持", "重组",
    "国资委", "印发", "实施", "征求意见", "出台", "中央", "监管",
    "扩内需", "刺激", "补贴", "产业", "互联网", "新能源", "汽车",
    "半导体", "芯片", "人工智能", "AI", "数字经济",
]


def fetch_sector_policy(sector: str, page_size: int = 20) -> List[dict]:
    """板块相关政策/快讯：从全球快讯里筛行业关键词"""
    out = []
    seen = set()

    # 1) 全球快讯筛关键词
    telegraph = fetch_eastmoney_global_news(page_size=80)
    for n in telegraph:
        text = (n.get("title", "") + " " + n.get("content", ""))
        is_policy = (sector and sector in text) or any(k in text for k in POLICY_KEYWORDS)
        if is_policy:
            key = n.get("title", "")[:50]
            if key and key not in seen:
                seen.add(key)
                n["category"] = "政策/快讯"
                out.append(n)
        if len(out) >= page_size:
            break

    # 2) 行业个股新闻（兜底）
    if sector and len(out) < page_size:
        try:
            extra = fetch_eastmoney_stock_news(sector, page_size=page_size)
            for n in extra:
                key = n.get("title", "")[:50]
                if key and key not in seen:
                    seen.add(key)
                    n["category"] = "行业新闻"
                    out.append(n)
                if len(out) >= page_size:
                    break
        except Exception:
            pass

    return out[:page_size]


SECTOR_THEME_KEYWORDS = {
    "人工智能/算力": ["人工智能", "AI", "大模型", "算力", "数据中心", "服务器", "液冷", "光模块", "GPU", "云计算"],
    "半导体/芯片": ["半导体", "芯片", "先进封装", "晶圆", "存储", "光刻", "EDA", "国产替代"],
    "机器人/高端制造": ["机器人", "人形机器人", "减速器", "伺服", "传感器", "工业母机", "高端制造", "自动化"],
    "新能源/电力设备": ["新能源", "光伏", "风电", "储能", "锂电", "电池", "充电", "800V", "特高压", "电网"],
    "汽车/智能驾驶": ["汽车", "智能驾驶", "自动驾驶", "车联网", "新能源车", "比亚迪", "特斯拉", "华为汽车"],
    "数字经济/传媒互联网": ["数字经济", "互联网", "传媒", "内容", "游戏", "短剧", "数据要素", "政务数据", "舆情"],
    "金融/券商": ["降准", "降息", "LPR", "资本市场", "并购重组", "券商", "保险", "银行", "回购", "增持"],
    "地产/基建": ["房地产", "地产", "城中村", "基建", "专项债", "水利", "保障房", "棚改"],
    "医药/医疗": ["医药", "医疗", "创新药", "医保", "集采", "疫苗", "器械", "CXO"],
    "军工/低空经济": ["军工", "低空经济", "无人机", "商业航天", "卫星", "航空", "航天"],
    "消费/旅游": ["消费", "旅游", "免税", "白酒", "食品", "餐饮", "文旅", "暑运", "春节"],
}

POSITIVE_POLICY_WORDS = ["支持", "促进", "加快", "推动", "印发", "出台", "通过", "获批", "补贴", "降准", "降息", "回购", "增持", "突破", "订单", "涨价", "扩产", "投资", "采购", "试点"]
NEGATIVE_POLICY_WORDS = ["监管", "处罚", "调查", "制裁", "限制", "加征", "下滑", "亏损", "降价", "风险", "暂停", "叫停", "收紧", "退市", "暴雷", "违约"]


def analyze_political_sector_impact(page_size: int = 80, top_n: int = 8) -> List[dict]:
    """时政/政策/新闻情绪对板块影响分析。

    数据来源：财联社电报 + 东财 7×24 快讯。返回：
    [{sector, score, impact, confidence, headlines, positive_hits, negative_hits}]
    """
    news = fetch_cls_telegraph(page_size=page_size, last_time=0)
    if len(news) < page_size // 2:
        news += fetch_eastmoney_global_news(page_size=page_size)
    buckets = {}
    for n in news:
        text = f"{n.get('title', '')} {n.get('content', '')}"
        if not text.strip():
            continue
        pos = sum(1 for w in POSITIVE_POLICY_WORDS if w in text)
        neg = sum(1 for w in NEGATIVE_POLICY_WORDS if w in text)
        policy_weight = 1 if any(w in text for w in POLICY_KEYWORDS) else 0
        for sector, keys in SECTOR_THEME_KEYWORDS.items():
            hit_keys = [k for k in keys if k in text]
            if not hit_keys:
                continue
            b = buckets.setdefault(sector, {
                "sector": sector,
                "score": 0,
                "positive_hits": 0,
                "negative_hits": 0,
                "policy_hits": 0,
                "keywords": set(),
                "headlines": [],
            })
            delta = pos - neg
            if delta == 0 and policy_weight:
                delta = 0.5
            b["score"] += delta
            b["positive_hits"] += pos
            b["negative_hits"] += neg
            b["policy_hits"] += policy_weight
            b["keywords"].update(hit_keys)
            if len(b["headlines"]) < 4:
                b["headlines"].append({
                    "title": n.get("title", ""),
                    "date": n.get("date", ""),
                    "source": n.get("source", "东方财富 7×24"),
                    "url": n.get("url", ""),
                    "keywords": hit_keys[:4],
                })

    rows = []
    for b in buckets.values():
        score = float(b["score"])
        if score >= 2:
            impact = "明显利好"
        elif score > 0:
            impact = "偏利好"
        elif score <= -2:
            impact = "明显利空"
        elif score < 0:
            impact = "偏利空"
        else:
            impact = "中性"
        confidence = min(100, 35 + len(b["headlines"]) * 12 + b["policy_hits"] * 8)
        rows.append({
            "sector": b["sector"],
            "score": round(score, 2),
            "impact": impact,
            "confidence": confidence,
            "positive_hits": b["positive_hits"],
            "negative_hits": b["negative_hits"],
            "policy_hits": b["policy_hits"],
            "keywords": sorted(b["keywords"])[:8],
            "headlines": b["headlines"],
        })
    rows.sort(key=lambda x: (abs(x["score"]), x["confidence"]), reverse=True)
    return rows[:top_n]


def build_stock_news_bundle(code: str, name: str = "", sector: str = "") -> dict:
    """聚合个股新闻 + 板块政策 + 全球快讯 + 财联社电报"""
    stock_news = fetch_eastmoney_stock_news(code, page_size=20)

    cls_news = fetch_cls_telegraph(page_size=30, last_time=0)
    if name:
        keys = [k for k in [name, code] if k]
        stock_news = list(stock_news) + [
            n for n in cls_news
            if any(k and k in (n.get("title", "") + n.get("content", "")) for k in keys)
        ]
        seen = set()
        deduped = []
        for n in stock_news:
            key = n.get("title", "")[:50]
            if key and key not in seen:
                seen.add(key)
                deduped.append(n)
        stock_news = deduped[:20]

    sector_news = []
    if sector and sector != "—":
        sector_news = fetch_sector_policy(sector, page_size=15)
        # 把财联社里行业关键词命中的电报也并到板块/政策
        for n in cls_news:
            text = (n.get("title", "") + n.get("content", ""))
            if sector in text or any(k in text for k in POLICY_KEYWORDS):
                sector_news.insert(0, n)
        sector_news = sector_news[:15]

    market_news = fetch_eastmoney_global_news(page_size=20)
    # 财联社顶部 20 条作为“7×24 财联社电报”独立展示
    cls_top = cls_news[:20]

    return {
        "stock_news":  stock_news,
        "sector_news": sector_news,
        "market_news": market_news,
        "cls_news":    cls_top,
    }
