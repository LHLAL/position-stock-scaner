"""铲子股卡位策略 —— 全市场扫盘

v1.1 思路（5 步）：
  1. THS 行业涨幅榜 → 选 TOP 热门板块（确认时代趋势方向）
  2. 全市场快照（akshare） + SQLite stock_basics industry join → 拿到 code/name/PE/PB/市值/行业
  3. 知识库双路匹配：name 含卡脖子关键词 OR industry 命中板块别名
  4. 估值过滤：PE > 0 且 < 50，PB < 10（排除 ST/亏损/异常）
  5. 评分 = 关键词命中数 × 30 + 板块强度 × 0.5 + 换手率活跃度 × 0.2

输出：list[{code, name, sector, bottleneck, keywords_matched,
            pe, pb, market_cap, score, change_pct, turnover, reason}]
"""
from __future__ import annotations
import logging
import os
import threading
from typing import Dict, List, Optional

from src.repository.stock_repo import stock_repo
from .bottleneck_kb import BOTTLENECK_KB, match_sectors

logger = logging.getLogger(__name__)


# ── 进程级缓存（全市场快照 60s） ─────────────────
_SNAPSHOT_CACHE: Dict = {}
_SNAPSHOT_LOCK = threading.Lock()
_SNAPSHOT_TTL = 60


def _enrich_with_industry(rows: List[Dict]) -> List[Dict]:
    """从 SQLite stock_basics 给每行补 industry 字段（铲子股匹配核心）"""
    try:
        basic_repo = stock_repo.get_stock_basic_repo()
        for r in rows:
            b = basic_repo.get(r['code'])
            r['industry'] = b.industry if b else ''
    except Exception as e:
        logger.debug(f"enrich_with_industry 失败（不影响主流程）: {e}")
        for r in rows:
            r.setdefault('industry', '')
    return rows


def _fetch_full_market() -> List[Dict]:
    """获取全市场快照：优先 StockCache（Tencent），akshare 兜底。60s 缓存"""
    import time
    now = time.time()
    with _SNAPSHOT_LOCK:
        cached = _SNAPSHOT_CACHE.get('ts', 0)
        if now - cached < _SNAPSHOT_TTL and 'data' in _SNAPSHOT_CACHE:
            return _SNAPSHOT_CACHE['data']

    out = []
    # 优先：StockCache（Tencent 实时行情，60s 刷新，全市场 ~5000 只）
    try:
        from src.core.stock_cache import stock_cache
        cached = stock_cache.get_stocks_by_price_range(limit=5000)
        valid = [s for s in cached if s.is_valid()]
        if len(valid) > 500:  # 需要足够多的有效行情才跳过 akshare
            out = [{
                'code': s.code, 'name': s.name or '',
                'price': s.price,
                'change_pct': s.change_pct,
                'volume': s.volume,
                'turnover': 0, 'pe': 0, 'pb': 0,
                'market_cap': 0, 'circ_mv': 0, 'industry': '',
            } for s in valid]
            logger.info(f"铲子股: StockCache {len(out)} 只")
    except Exception as e:
        logger.warning(f"铲子股 StockCache 失败: {e}")

    # 兜底：akshare 全市场（含 PE/PB/市值等完整数据）
    if len(out) < 100:
        out = []
        try:
            for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
                os.environ.pop(k, None)
            os.environ['no_proxy'] = '*'
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    try:
                        code = str(row.get('代码', '')).strip()
                        name = str(row.get('名称', '')).strip()
                        if not code or not name:
                            continue
                        price = float(row.get('最新价', 0) or 0)
                        if price <= 0:
                            continue
                        out.append({
                            'code': code, 'name': name, 'price': price,
                            'change_pct': float(row.get('涨跌幅', 0) or 0),
                            'volume': int(float(row.get('成交量', 0) or 0)),
                            'turnover': float(row.get('换手率', 0) or 0),
                            'pe': float(row.get('市盈率-动态', 0) or 0),
                            'pb': float(row.get('市净率', 0) or 0),
                            'market_cap': float(row.get('总市值', 0) or 0),
                            'circ_mv': float(row.get('流通市值', 0) or 0),
                            'industry': '',
                        })
                    except Exception:
                        continue
                logger.info(f"铲子股: akshare {len(out)} 只")
        except Exception as e:
            logger.warning(f"铲子股 akshare 兜底失败: {e}")

    out = _enrich_with_industry(out)
    with _SNAPSHOT_LOCK:
        _SNAPSHOT_CACHE['ts'] = now
        _SNAPSHOT_CACHE['data'] = out
    return out


# ── 热门板块识别 ──────────────────────────────
def _get_top_sectors(top_n: int = 6) -> List[Dict]:
    """THS 行业涨幅榜 → TOP N 热门板块"""
    try:
        ths = stock_repo.get_ths_source()
        df = ths.get_industry_comparison(top_n=top_n)
        if df is None or df.empty:
            return []
        # 取涨跌幅前 N
        if '涨跌幅' in df.columns:
            df = df.sort_values('涨跌幅', ascending=False).head(top_n)
        sectors = []
        for _, row in df.iterrows():
            sectors.append({
                'name': str(row.get('板块', '')).strip(),
                'change_pct': float(row.get('涨跌幅', 0) or 0),
            })
        return sectors
    except Exception as e:
        logger.warning(f"热门板块识别失败: {e}")
        return []


# ── 核心筛选 ────────────────────────────────────
def screen(
    top_sectors: int = 6,
    top_sector_names: Optional[List[str]] = None,  # 直接指定业务板块名（KB 里的 key）
    pe_min: float = 0,
    pe_max: float = 50,
    pb_max: float = 10,
    min_market_cap_yi: float = 0,     # 单位：亿；0=不限
    max_market_cap_yi: float = 300,   # 单位：亿；偏好小市值
    min_turnover: float = 1.0,        # 换手率下限，避免死水
    limit: int = 30,
) -> Dict:
    """铲子股卡位扫盘

    Args:
        top_sectors: 当 top_sector_names 为空时，从 THS 拉涨幅榜 TOP N 板块
        top_sector_names: 直接指定业务板块（KB key），如 ["半导体设备", "AI算力"]
                          优先级高于 top_sectors；命中的股票必须踩中其中至少一个

    Returns:
        {
          'top_sectors': [...],          # 实际使用的板块列表
          'scanned': int,
          'candidates': [...],
          'sector_summary': {sector: count}
        }
    """
    # 1. 板块列表 —— 直接指定优先，否则走 THS 涨幅榜
    if top_sector_names:
        # 用户直接指定业务板块（用 KB 默认 trend 强度 0.5 作为底）
        hot = [{'name': n, 'change_pct': 0.5} for n in top_sector_names if n in BOTTLENECK_KB]
        if not hot:
            return {
                'top_sectors': [],
                'scanned': 0,
                'candidates': [],
                'sector_summary': {},
                'error': f'指定的板块都不在知识库: {top_sector_names}',
            }
        target_sectors = set(top_sector_names)
    else:
        hot = _get_top_sectors(top_sectors)
        target_sectors = {s['name'] for s in hot}

    hot_names = [s['name'] for s in hot]
    hot_strength = {s['name']: s['change_pct'] for s in hot}

    # 2. 全市场快照
    market = _fetch_full_market()
    if not market:
        return {
            'top_sectors': hot,
            'scanned': 0,
            'candidates': [],
            'sector_summary': {},
            'error': '全市场数据源不可用',
        }

    # 3+4. 三重过滤 + 评分
    candidates = []
    sector_counter: Dict[str, int] = {}

    for s in market:
        # 双路匹配（name 关键词 + industry 别名）—— 必须命中至少 1 个板块
        hit_sectors = match_sectors(s['name'], s.get('industry', ''))
        if not hit_sectors:
            continue

        # 如果指定了板块，必须命中其中至少一个
        if top_sector_names:
            if not (set(hit_sectors) & target_sectors):
                continue

        # 估值过滤
        if not (pe_min < s['pe'] < pe_max):
            continue
        if s['pb'] > pb_max or s['pb'] <= 0:
            continue

        # 市值过滤（单位转换：元 → 亿）
        mc_yi = s['market_cap'] / 1e8
        if mc_yi < min_market_cap_yi or mc_yi > max_market_cap_yi:
            continue

        # 换手率过滤
        if s['turnover'] < min_turnover:
            continue

        # 命中板块：取命中的**目标板块**优先（用户指定的那个），否则取第一个
        if top_sector_names:
            target_hits = [h for h in hit_sectors if h in target_sectors]
            main_sector = target_hits[0] if target_hits else hit_sectors[0]
        else:
            main_sector = hit_sectors[0]
        bottleneck_info = BOTTLENECK_KB.get(main_sector, {})

        # 计算"踩了几个热点板块"（多热点加权）
        sector_score = len(hit_sectors) * 30

        # 板块强度（如果该板块在热门榜，加分）
        # 行业名可能不严格匹配，做模糊匹配
        plate_bonus = 0
        for hot_name in hot_names:
            if hot_name in main_sector or main_sector in hot_name:
                plate_bonus = max(plate_bonus, hot_strength.get(hot_name, 0))
        plate_score = plate_bonus * 0.5

        # 换手率活跃度（1% 起步，10% 封顶）
        activity_score = min(s['turnover'], 10) * 0.2

        # 价格动量加分（小幅正值更稳）
        momentum = 0
        if 0 < s['change_pct'] < 5:
            momentum = 5
        elif s['change_pct'] >= 5:
            momentum = 10

        score = round(sector_score + plate_score + activity_score + momentum, 1)

        # 命中关键词列表（从 KB 里回查）
        matched_keywords = [
            kw for kw in bottleneck_info.get('keywords', [])
            if kw in s['name']
        ]

        candidates.append({
            'code': s['code'],
            'name': s['name'],
            'price': s['price'],
            'change_pct': s['change_pct'],
            'turnover': s['turnover'],
            'pe': s['pe'],
            'pb': s['pb'],
            'market_cap_yi': round(mc_yi, 1),
            'sector': main_sector,
            'bottleneck': bottleneck_info.get('bottleneck', ''),
            'trend': bottleneck_info.get('trend', ''),
            'matched_keywords': matched_keywords,
            'multi_sectors': hit_sectors[1:],  # 同时踩的其它板块
            'score': score,
            'reason': f"踩中「{main_sector}」{len(matched_keywords)} 个卡脖子关键词，市值 {mc_yi:.0f} 亿，PE {s['pe']:.1f}",
        })

        # 板块命中统计
        for sec in hit_sectors:
            sector_counter[sec] = sector_counter.get(sec, 0) + 1

    # 排序：score desc
    candidates.sort(key=lambda x: (x['score'], x['change_pct']), reverse=True)

    return {
        'top_sectors': hot,
        'scanned': len(market),
        'candidates': candidates[:limit],
        'sector_summary': dict(sorted(
            sector_counter.items(), key=lambda x: x[1], reverse=True
        )),
    }
