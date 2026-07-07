"""盘前/盘后复盘聚合。

第一版复用现有数据源：今日预测、全球市场、财联社、扫盘增强、持仓。
所有外部数据失败都降级为空/摘要，保证复盘页不空白。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List
from src.repository.stock_repo import stock_repo


def _safe_call(fn, default):
    try:
        return fn()
    except Exception:
        return default


def _now_text() -> str:
    return datetime.now().isoformat(timespec='seconds')


def _score_direction(up: List[Dict], down: List[Dict], global_summary: str = '') -> str:
    up_score = sum(float(x.get('score') or 0) for x in up)
    down_score = abs(sum(float(x.get('score') or 0) for x in down))
    if up_score > down_score + 2:
        return '偏多'
    if down_score > up_score + 2:
        return '偏空'
    if '明显负面' in global_summary or '大跌' in global_summary:
        return '震荡偏空'
    if '明显正面' in global_summary or '大涨' in global_summary:
        return '震荡偏多'
    return '震荡'


def _position_advice(direction: str, risk_level: str) -> str:
    if '偏空' in direction or risk_level == '高':
        return '降至 50-60%，先防回撤'
    if '偏多' in direction and risk_level == '低':
        return '维持 70-80%，强势方向可低吸'
    return '控制 60-70%，等开盘承接确认'


def _risk_level(direction: str, positions: List[Dict], global_summary: str = '') -> str:
    if '偏空' in direction or '明显负面' in global_summary:
        return '高'
    if len(positions) >= 5:
        return '中'
    return '中'


def _fetch_positions() -> List[Dict]:
    from src.core.patrol import PatrolManager
    return PatrolManager().get_all_positions() or []


def _affected_positions(positions: List[Dict], up: List[Dict], down: List[Dict], news: List[Dict]) -> List[Dict]:
    up_names = [x.get('sector') for x in up]
    down_names = [x.get('sector') for x in down]
    news_blob = '\n'.join((n.get('title') or '') + ' ' + (n.get('content') or '') for n in news[:20])
    rows = []
    for p in positions[:12]:
        code = p.get('code') or p.get('stock_code') or ''
        name = p.get('name') or p.get('stock_name') or code
        pnl = p.get('profit_loss_pct') or 0
        reasons = []
        impact = 0
        if name and name in news_blob:
            reasons.append('财联社/新闻命中')
            impact += 2
        if pnl and pnl > 8:
            reasons.append('已有较厚盈利，适合移动止盈')
            impact += 1
        elif pnl and pnl < -5:
            reasons.append('浮亏扩大，需检查止损')
            impact -= 1
        if not reasons:
            reasons.append('未发现直接新闻，按板块和技术面观察')
        rows.append({
            'code': code,
            'name': name,
            'profit_loss_pct': round(float(pnl or 0), 2),
            'impact_score': impact,
            'matched': reasons[:3],
            'up_sectors': up_names[:3],
            'down_sectors': down_names[:3],
        })
    return rows


def _recent_cls(limit: int = 20) -> List[Dict]:
    return stock_repo.fetch_cls_telegraph(page_size=limit, last_time=0)[:limit]


def _hotspots_from_prediction(prediction: Dict) -> List[Dict]:
    rows = []
    for item in prediction.get('up_sectors') or []:
        rows.append({
            'name': item.get('sector'),
            'score': item.get('score'),
            'direction': 'up',
            'reason': ' / '.join((item.get('reason') or [])[:2]) or '今日预测偏强',
        })
    for item in prediction.get('down_sectors') or []:
        rows.append({
            'name': item.get('sector'),
            'score': item.get('score'),
            'direction': 'down',
            'reason': ' / '.join((item.get('reason') or [])[:2]) or '今日预测承压',
        })
    return rows[:10]


# 科技赛道卡位扫描（用 bottleneck_kb 动态筛选）
# fallback：当动态扫描失败时的手动候选
_FALLBACK_TECH_CANDIDATES = [
    {'code': '688256', 'name': '寒武纪', 'track': 'AI/算力', 'node': 'AI 训练/推理芯片',
     'moat': '国产高端 AI 芯片稀缺标的', 'irreplaceable': '国产算力自主可控核心'},
    {'code': '300308', 'name': '中际旭创', 'track': 'AI/算力', 'node': '800G/1.6T 光模块',
     'moat': '全球光模块龙头、北美大客户', 'irreplaceable': 'AI 数据中心高速光互联卡位'},
    {'code': '688041', 'name': '海光信息', 'track': '半导体', 'node': 'CPU/DCU',
     'moat': '国产服务器 CPU 生态', 'irreplaceable': '信创+算力国产替代'},
    {'code': '688012', 'name': '中微公司', 'track': '半导体', 'node': '刻蚀设备',
     'moat': '国产刻蚀设备龙头', 'irreplaceable': '晶圆制造卡脖子设备'},
    {'code': '688017', 'name': '绿的谐波', 'track': '人形机器人', 'node': '谐波减速器',
     'moat': '国产谐波减速器龙头', 'irreplaceable': '机器人关节不可替代环节'},
    {'code': '002472', 'name': '双环传动', 'track': '人形机器人', 'node': '精密减速器齿轮',
     'moat': '谐波/RV 减速器齿轮卡位', 'irreplaceable': '机器人关节核心传动件'},
]
_FALLBACK_TECH_CANDIDATES = [c for c in _FALLBACK_TECH_CANDIDATES if c.get('code', '').isdigit()]


def _is_low_value(metrics: Dict) -> bool:
    """成长科技股放宽估值口径：PE<60 或 PB<8 视为相对低估。"""
    pe = metrics.get('pe')
    pb = metrics.get('pb')
    if pe is not None and 0 < pe < 60:
        return True
    if pb is not None and 0 < pb < 8:
        return True
    return False


def _tech_bottleneck_stocks(prediction: Dict, news: List[Dict]) -> List[Dict]:
    """今日热门科技赛道 + 低估值 + 关键零部件/材料环节的卡位标的。

    优先用 bottleneck_strategy 动态扫描，失败时退回手动候选。"""
    from src.core.today_prediction import _candidate_metrics

    up = prediction.get('up_sectors') or []
    hot_tracks = {x.get('sector') for x in up}
    if '机器人' in hot_tracks:
        hot_tracks.add('人形机器人')

    # KB key 映射
    TRACK_TO_KB = {
        'AI/算力': 'AI算力',
        '半导体': '半导体设备',
        '先进制造': '先进制造',
        '人形机器人': '人形机器人',
        '机器人': '人形机器人',
    }
    kb_keys = [TRACK_TO_KB[t] for t in hot_tracks if t in TRACK_TO_KB]
    if not kb_keys:
        kb_keys = ['AI算力', '半导体设备', '人形机器人']  # 默认热门赛道

    picked = []
    try:
        from src.core.bottleneck_strategy import screen as bottleneck_screen
        result = bottleneck_screen(top_sector_names=kb_keys, limit=10)
        candidates = result.get('candidates', [])
        for c in candidates:
            code = c.get('code', '')
            if not code:
                continue
            name = c.get('name', '')
            sector = c.get('main_sector', '')
            # 映射回 track 名
            track = next((k for k, v in TRACK_TO_KB.items() if v == sector), sector)
            picked.append({
                'code': code,
                'name': name,
                'track': track,
                'node': c.get('bottleneck', ''),
                'moat': c.get('reason', ''),
                'irreplaceable': c.get('reason', ''),
                'pe': c.get('pe'),
                'pb': c.get('pb'),
                'price': c.get('price', 0),
                'change_pct': c.get('change_pct', 0),
                'is_hot': True,
                'low_value': _is_low_value(c),
                'rank_score': c.get('score', 0),
            })
    except Exception as ex:
        logger.warning(f"瓶颈策略扫描失败，退回手动候选: {ex}")

    # 动态扫描不足 5 只时，用 fallback 候选补齐
    if len(picked) < 5:
        existing = {x['code'] for x in picked}
        for c in _FALLBACK_TECH_CANDIDATES:
            if c['code'] in existing:
                continue
            track = c.get('track', '')
            hot = track in hot_tracks or (track == '人形机器人' and '机器人' in hot_tracks)
            if not hot:
                continue
            metrics = _safe_call(lambda: _candidate_metrics(c['code']), {}) or {}
            picked.append({**c, **metrics, 'is_hot': True, 'low_value': _is_low_value(metrics), 'rank_score': 1})
            if len(picked) >= 5:
                break

    picked.sort(key=lambda x: (x.get('rank_score', 0), -(x.get('pe') or 999)), reverse=True)
    return picked[:5]


def build_premarket_review() -> Dict[str, Any]:
    from src.core.today_prediction import build_today_prediction

    prediction = _safe_call(build_today_prediction, {})
    # v1.3: 不再调用 global_market（港美股已停支持）
    global_summary = prediction.get('global_summary') or '国内宏观/板块联动信息暂不可用'
    positions = _safe_call(_fetch_positions, [])
    news = _safe_call(lambda: _recent_cls(24), [])

    up = prediction.get('up_sectors') or []
    down = prediction.get('down_sectors') or []
    direction = prediction.get('direction') or _score_direction(up, down, global_summary)
    risk = _risk_level(direction, positions, global_summary)

    actions = [
        '开盘前先看高开/低开后的 15 分钟承接，不追第一笔',
        '优先观察预测偏强板块中低估值、低位、有真实催化的个股',
        '持仓若低开放量跌破昨日低点，先减仓再等确认',
    ]
    if up:
        actions.insert(0, f"重点看 {up[0].get('sector')} 是否延续强势")
    if down:
        actions.append(f"回避 {down[0].get('sector')} 中高位弱承接标的")

    return {
        'generated_at': _now_text(),
        'mode': 'premarket',
        'source': 'today_prediction + cls + patrol',
        'headline': {
            'direction': direction,
            'position_advice': _position_advice(direction, risk),
            'summary': f"{global_summary.splitlines()[-1] if global_summary else '国内宏观中性'}；财联社样本 {prediction.get('news_count_12h', len(news))} 条。",
            'risk_level': risk,
            'actions': actions[:5],
        },
        'external_factors': [],
        'sector_mapping': [
            {'chain': 'AI 算力链', 'mapping': '光模块、液冷、服务器、电源', 'signal': 'A 股板块联动方向'},
            {'chain': '新能源车链', 'mapping': '电池、零部件、智驾、机器人', 'signal': '产业链上下游联动方向'},
            {'chain': '半导体链', 'mapping': '设备、材料、先进封装、IP', 'signal': '国产替代节奏'},
        ],
        'news': news[:10],
        'hotspots': _hotspots_from_prediction(prediction),
        'low_value_stocks': _tech_bottleneck_stocks(prediction, news),
        'affected_positions': _affected_positions(positions, up, down, news),
        'strategy': actions[:5],
    }


def _market_decode_from_prediction(prediction: Dict) -> List[Dict]:
    rows = []
    for item in (prediction.get('up_sectors') or [])[:4]:
        rows.append({'label': item.get('sector'), 'trend': '强势/待确认', 'feature': '新闻与外盘映射偏正面', 'score': item.get('score')})
    for item in (prediction.get('down_sectors') or [])[:3]:
        rows.append({'label': item.get('sector'), 'trend': '承压', 'feature': '消息面或外盘映射偏弱', 'score': item.get('score')})
    return rows or [{'label': '全市场', 'trend': prediction.get('direction', '震荡'), 'feature': '暂无明显单边主线', 'score': 0}]


def _position_attribution(positions: List[Dict]) -> List[Dict]:
    rows = []
    for p in positions[:12]:
        code = p.get('code') or ''
        name = p.get('name') or code
        pnl = float(p.get('profit_loss_pct') or 0)
        today = float(p.get('change_pct') or 0)
        if pnl > 8:
            action = '移动止盈'
        elif pnl < -5:
            action = '检查止损'
        elif today > 3:
            action = '冲高不追，观察量能'
        elif today < -3:
            action = '弱势减仓观察'
        else:
            action = '继续观察'
        rows.append({'code': code, 'name': name, 'profit_loss_pct': round(pnl, 2), 'today_change_pct': round(today, 2), 'action': action})
    return rows


def build_postmarket_review() -> Dict[str, Any]:
    from src.core.today_prediction import build_today_prediction

    prediction = _safe_call(build_today_prediction, {})
    positions = _safe_call(_fetch_positions, [])
    news = _safe_call(lambda: _recent_cls(24), [])
    up = prediction.get('up_sectors') or []
    down = prediction.get('down_sectors') or []
    direction = prediction.get('direction') or _score_direction(up, down, prediction.get('global_summary', ''))
    risk = '中高' if len(down) >= len(up) and down else '中'

    actions = [
        '复盘今日最强板块是否有持续新闻和资金承接',
        '盈利仓位设置移动止盈，避免明日冲高回落',
        '浮亏仓位若明日不能收回关键均线，按纪律减仓',
        '明日优先观察低估值候选与强催化板块的交集',
    ]
    if up:
        actions.insert(0, f"明日优先观察 {up[0].get('sector')} 的分歧低吸机会")

    return {
        'generated_at': _now_text(),
        'mode': 'postmarket',
        'source': 'today_prediction + cls + patrol',
        'headline': {
            'direction': f"明日{direction}",
            'position_advice': '保留核心仓，弱势仓降风险' if risk != '高' else '优先降风险，等待次日确认',
            'summary': f"今日主线集中在 {', '.join([x.get('sector', '') for x in up[:3]]) or '暂无明确主线'}；承压方向 {', '.join([x.get('sector', '') for x in down[:2]]) or '不明显'}。",
            'risk_level': risk,
            'actions': actions[:5],
        },
        'market_decode': _market_decode_from_prediction(prediction),
        'sentiment': [
            {'label': '新闻样本', 'value': prediction.get('news_count_12h', len(news)), 'signal': '样本充足' if len(news) >= 10 else '样本偏少'},
            {'label': '上涨板块', 'value': len(up), 'signal': '结构性机会' if up else '主线不明'},
            {'label': '承压板块', 'value': len(down), 'signal': '分化需控仓' if down else '压力不明显'},
        ],
        'breadth': {
            'summary': '第一版未接全市场涨跌家数，使用热点/承压板块数量近似市场宽度。',
            'up_count': len(up),
            'down_count': len(down),
        },
        'volume': [
            {'label': '量能判断', 'value': '待接入全市场成交额', 'signal': '先按热点延续性判断'},
            {'label': '数据状态', 'value': 'MVP fallback', 'signal': '不影响策略结论展示'},
        ],
        'hotspots': _hotspots_from_prediction(prediction),
        'position_attribution': _position_attribution(positions),
        'risk_checks': [
            '检查持仓是否过度集中在同一板块',
            '检查浮盈较大的个股是否需要移动止盈',
            '检查浮亏个股是否跌破预设止损线',
            '若明日外盘继续偏弱，降低追高和满仓操作',
        ],
        'tomorrow_strategy': actions[:5],
        'news': news[:8],
    }
