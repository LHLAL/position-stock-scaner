"""今日市场预测
基于国际股市、政策/法规关键词、财联社近12小时电报，预测今日板块方向与低估值个股影响。
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, List, Tuple
from src.repository.stock_repo import stock_repo


SECTOR_KEYWORDS = {
    'AI/算力': ['AI', '人工智能', '大模型', '算力', '服务器', '液冷', '光模块', 'CPO', '数据中心'],
    '半导体': ['半导体', '芯片', '晶圆', '光刻', '先进封装', '存储', '衬底', 'EDA'],
    '机器人': ['机器人', '人形机器人', '减速器', '丝杠', '执行器', '传感器'],
    '新能源': ['新能源', '光伏', '储能', '锂电', '电池', '风电', '充电桩'],
    '汽车': ['汽车', '智能驾驶', '电动车', '零部件', '特斯拉', '无人驾驶'],
    '金融': ['银行', '保险', '券商', '证券', '金融', '降准', '降息', '地产融资'],
    '地产链': ['房地产', '地产', '房贷', '城中村', '建材', '家居', '水泥'],
    '消费': ['消费', '白酒', '食品', '旅游', '免税', '零售', '家电'],
    '医药': ['医药', '创新药', '医疗', '医保', '疫苗', 'CXO', '器械'],
    '军工': ['军工', '国防', '航天', '航空', '卫星', '低空经济'],
    '中字头/高股息': ['央企', '国企', '中特估', '分红', '高股息', '电力', '煤炭', '运营商'],
}

POSITIVE_WORDS = ['利好', '增长', '支持', '鼓励', '加快', '突破', '创新高', '上调', '中标', '回购', '增持', '获批', '放宽']
NEGATIVE_WORDS = ['利空', '下滑', '下降', '风险', '调查', '处罚', '减持', '亏损', '暂停', '收紧', '限制', '退市']
POLICY_WORDS = ['国务院', '发改委', '工信部', '财政部', '央行', '证监会', '交易所', '政策', '法规', '条例', '通知', '意见']

# 低估值候选池：优先从自选/持仓补充；这里作为无全市场估值源时的稳定候选。
LOW_VALUE_CANDIDATES = [
    {'code': '601318', 'name': '中国平安', 'tags': ['金融', '保险', '高股息']},
    {'code': '600036', 'name': '招商银行', 'tags': ['金融', '银行', '高股息']},
    {'code': '601398', 'name': '工商银行', 'tags': ['金融', '银行', '高股息', '中字头/高股息']},
    {'code': '601088', 'name': '中国神华', 'tags': ['煤炭', '高股息', '中字头/高股息']},
    {'code': '600900', 'name': '长江电力', 'tags': ['电力', '高股息', '中字头/高股息']},
    {'code': '601668', 'name': '中国建筑', 'tags': ['地产链', '基建', '中字头/高股息']},
    {'code': '600048', 'name': '保利发展', 'tags': ['地产链', '房地产']},
    {'code': '600030', 'name': '中信证券', 'tags': ['金融', '券商']},
    {'code': '601857', 'name': '中国石油', 'tags': ['能源', '高股息', '中字头/高股息']},
    {'code': '600276', 'name': '恒瑞医药', 'tags': ['医药', '创新药']},
]


def _news_text(n: Dict) -> str:
    return f"{n.get('title', '')} {n.get('content', '')} {n.get('subjects', '')}"


def _fetch_cls_12h() -> List[Dict]:
    try:
        rows = stock_repo.fetch_cls_telegraph(page_size=80, last_time=0)
    except Exception:
        return []
    cutoff = int(time.time()) - 12 * 3600
    out = []
    for n in rows or []:
        ctime = n.get('ctime')
        if isinstance(ctime, (int, float)) and ctime < cutoff:
            continue
        out.append(n)
    return out[:50]


def _score_sectors(news: List[Dict], global_impact: Dict) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    scores = {k: 0 for k in SECTOR_KEYWORDS}
    evidence = {k: [] for k in SECTOR_KEYWORDS}
    policy_hits = []

    for n in news:
        text = _news_text(n)
        if any(w in text for w in POLICY_WORDS):
            policy_hits.append({'title': n.get('title', ''), 'time': n.get('date', ''), 'url': n.get('url', '')})
        sentiment = 0
        sentiment += sum(1 for w in POSITIVE_WORDS if w in text)
        sentiment -= sum(1 for w in NEGATIVE_WORDS if w in text)
        if sentiment == 0:
            sentiment = 1 if any(w in text for w in POLICY_WORDS) else 0
        for sector, kws in SECTOR_KEYWORDS.items():
            if any(kw in text for kw in kws):
                scores[sector] += sentiment
                if len(evidence[sector]) < 3:
                    evidence[sector].append(n.get('title', ''))

    # v1.3: 不再读 global_market（港美股已停支持）；仅靠新闻板块信号打分
    _ = global_impact  # 兼容旧调用签名
    details = []

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    up = [{'sector': k, 'score': round(v, 1), 'reason': evidence[k][:3] or ['国际市场情绪映射']} for k, v in ranked if v > 0][:5]
    down = [{'sector': k, 'score': round(v, 1), 'reason': evidence[k][:3] or ['消息面偏弱或海外映射偏空']} for k, v in sorted(scores.items(), key=lambda x: x[1]) if v < 0][:5]
    return up, down, policy_hits[:8]


def _candidate_metrics(code: str) -> Dict:
    """获取候选股行情 + 估值数据"""
    market = stock_repo.infer_market(code)
    quote = stock_repo.get_quote(code, market)
    if not quote:
        return {}
    result = {
        'price': quote.price,
        'change_pct': quote.change_pct,
        'name': quote.name,
    }
    try:
        ext = stock_repo.get_quote_extended(code, market)
        if ext:
            result['pe'] = ext.get('pe')
            result['pb'] = ext.get('pb')
    except Exception:
        pass
    return result


def _low_value_stocks(up: List[Dict], down: List[Dict], news: List[Dict]) -> List[Dict]:
    sector_scores = {x['sector']: x['score'] for x in up}
    sector_scores.update({x['sector']: x['score'] for x in down})
    news_blob = '\n'.join(_news_text(n) for n in news[:30])
    picked = []
    for c in LOW_VALUE_CANDIDATES:
        impact = 0
        matched = []
        for tag in c['tags']:
            for sector, kws in SECTOR_KEYWORDS.items():
                if tag == sector or tag in kws:
                    impact += sector_scores.get(sector, 0)
                    if sector_scores.get(sector, 0):
                        matched.append(sector)
        if c['name'] in news_blob or c['code'] in news_blob:
            impact += 2
            matched.append('个股新闻命中')
        metrics = _candidate_metrics(c['code'])
        pe = metrics.get('pe')
        pb = metrics.get('pb')
        low_value = (pe is not None and pe > 0 and pe < 15) or (pb is not None and pb > 0 and pb < 1.5)
        if low_value or impact != 0:
            picked.append({
                **c,
                **metrics,
                'impact_score': round(impact, 1),
                'matched': list(dict.fromkeys(matched))[:3],
                'reason': '低估值防御/重估候选' if low_value else '板块消息影响候选',
            })
    picked.sort(key=lambda x: (abs(x.get('impact_score') or 0), -(x.get('pe') or 99)), reverse=True)
    return picked[:5]


def build_today_prediction() -> Dict:
    from src.util.trading_calendar import build_calendar_analysis

    news = _fetch_cls_12h()
    # v1.3: 不再调用 global_market（港美股已停支持），传入空 dict
    global_impact: Dict = {}
    calendar = build_calendar_analysis('', 'A股')
    up, down, policy_hits = _score_sectors(news, global_impact)
    stocks = _low_value_stocks(up, down, news)
    direction = '偏多' if len(up) > len(down) else ('偏空' if len(down) > len(up) else '震荡')

    return {
        'generated_at': datetime.now().isoformat(timespec='seconds'),
        'direction': direction,
        'calendar': calendar.get('today', {}),
        'global_summary': global_impact.get('summary', ''),
        'news_count_12h': len(news),
        'policy_hits': policy_hits,
        'up_sectors': up,
        'down_sectors': down,
        'low_value_stocks': stocks,
        'method': '国际股市映射 + 政策/法规关键词 + 财联社近12小时新闻 + 低PE/PB候选筛选',
    }
