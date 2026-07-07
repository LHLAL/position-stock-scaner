"""补齐路由 —— v1.3 拆分时从 v1_routes.py 抽出的端点

覆盖：
- /api/analyze/quick/<code>          快速分析（K线+指标+财务摘要）
- /api/chart/<code>?type=&period=    K线/成交量 Plotly fig
- /api/financials/<code>             财务摘要（替代 akshare stock_financial_abstract）
- /api/indicators/<code>             18 项技术指标 + L0-L3 信号
- /api/news/<code>                   个股新闻聚合（东财+财联社+板块政策）
- /api/screener/enriched             增强扫盘（价格+持仓+板块+北向）
- /api/sentiment/market              市场情绪
- /api/signals/<type>                单类信号
- /api/signals/all                   全部信号
- /api/watchlist                     自选股 CRUD + reorder + rename-project
"""
import logging
from datetime import datetime

from flask import request, jsonify

logger = logging.getLogger(__name__)


# ── 模块级 TTL 缓存（review / signals / sentiment 都属于"全市场聚合"型）──
# 这些端点要拉财联社 + 板块 + 北向数据，单次 20-30s。
# 用 60s 缓存让前端切页面后秒开，而不是每次都等 20s+。
import threading as _threading
_CACHE: dict = {}      # key -> (value, expire_at)
_CACHE_LOCK = _threading.Lock()
_CACHE_TTL_SECONDS = 60

# 缓存统计（用于监控面板）
_CACHE_STATS: dict = {'hit': 0, 'miss': 0, 'keys': {}}
_CACHE_HIT_LOG: list = []  # 最近 50 次命中日志 [(key, was_hit, ts), ...]


def _cached(key: str, loader, ttl: int = _CACHE_TTL_SECONDS):
    """简单 TTL 缓存：60s 内同 key 直接返回旧值；同时记录 hit/miss 统计 + 日志"""
    now = datetime.now()
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry and entry[1] > now:
            _CACHE_STATS['hit'] += 1
            _CACHE_STATS['keys'].setdefault(key, {'hit': 0, 'miss': 0, 'last_hit': None})
            _CACHE_STATS['keys'][key]['hit'] += 1
            _CACHE_STATS['keys'][key]['last_hit'] = now.isoformat()
            _CACHE_HIT_LOG.append({'key': key, 'hit': True, 'ts': now.isoformat()})
            if len(_CACHE_HIT_LOG) > 50:
                _CACHE_HIT_LOG.pop(0)
            return entry[0]
    # 缓存外（解锁后执行 loader，避免锁内调用慢函数）
    val = loader()
    with _CACHE_LOCK:
        from datetime import timedelta
        _CACHE[key] = (val, now + timedelta(seconds=ttl))
        _CACHE_STATS['miss'] += 1
        _CACHE_STATS['keys'].setdefault(key, {'hit': 0, 'miss': 0, 'last_hit': None})
        _CACHE_STATS['keys'][key]['miss'] += 1
        _CACHE_HIT_LOG.append({'key': key, 'hit': False, 'ts': now.isoformat()})
        if len(_CACHE_HIT_LOG) > 50:
            _CACHE_HIT_LOG.pop(0)
        # 清理过期
        for k in list(_CACHE.keys()):
            if _CACHE[k][1] <= now:
                _CACHE.pop(k, None)
    return val


def get_cache_stats() -> dict:
    """返回缓存命中率统计（给前端监控面板用）"""
    with _CACHE_LOCK:
        total = _CACHE_STATS['hit'] + _CACHE_STATS['miss']
        hit_rate = round(_CACHE_STATS['hit'] / total * 100, 1) if total else 0
        keys_detail = []
        for k, v in sorted(_CACHE_STATS['keys'].items(), key=lambda x: x[1]['hit'] + x[1]['miss'], reverse=True):
            keys_detail.append({
                'key': k,
                'hit': v['hit'],
                'miss': v['miss'],
                'rate': round(v['hit'] / (v['hit'] + v['miss']) * 100, 1) if (v['hit'] + v['miss']) else 0,
                'last_hit': v['last_hit'],
            })
        return {
            'total_requests': total,
            'hit': _CACHE_STATS['hit'],
            'miss': _CACHE_STATS['miss'],
            'hit_rate': hit_rate,
            'active_keys': len(_CACHE),
            'keys': keys_detail[:20],  # 只返回 TOP 20
            'recent_log': list(_CACHE_HIT_LOG)[-20:],  # 最近 20 次命中日志
        }


def register_extra_routes(app, get_analyzer_fn=None, check_auth_config_fn=None):
    from src.api.analyze_routes import create_require_auth

    if check_auth_config_fn:
        require_auth = create_require_auth(check_auth_config_fn)
    else:
        def require_auth(f):
            return f

    # ── 单股分析（快速接口）────────────────────
    @app.route('/api/analyze/quick/<code>', methods=['GET'])
    @require_auth
    def analyze_quick(code):
        """快速分析 —— 给 signals.js 用的 1 次性 JSON，60s 缓存"""
        try:
            market = 'SH' if code.startswith('6') else 'SZ'

            def _load():
                analyzer = get_analyzer_fn() if get_analyzer_fn else None
                if analyzer is None:
                    from src.core.analyzer import StockAnalyzer
                    from src.data.registry import registry
                    analyzer = StockAnalyzer(registry=registry)
                result = analyzer.analyze_stock(code, market)
                tech = result.get('technical') or {}
                return {
                    'code': code,
                    'name': result.get('name', code),
                    'price': (result.get('quote') or {}).get('current_price'),
                    'change_pct': (result.get('quote') or {}).get('change_pct'),
                    'indicators': _format_indicators(tech),
                    'signals': result.get('signals', []),
                    'scores': result.get('scores', {}),
                    'score_explains': result.get('strategy', {}).get('explain', {}),
                    'technical': tech,
                    'fundamental': result.get('fundamental', {}),
                    'sentiment': result.get('sentiment', {}),
                    'recommendation': result.get('recommendation', ''),
                    'reason': result.get('reason', ''),
                }

            data = _cached(f'analyze_quick:{code}', _load, ttl=60)
            return jsonify({'success': True, 'data': data, 'source': 'real'})
        except Exception as e:
            logger.exception('analyze_quick failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    # ── K线 / 成交量（Plotly）───────────────────
    @app.route('/api/chart/<code>', methods=['GET'])
    @require_auth
    def get_chart(code):
        """K线/成交量 Plotly fig。type=kline|volume, period=1M|3M|6M|1Y"""
        try:
            from src.repository.stock_repo import stock_repo
            market = 'SH' if code.startswith('6') else 'SZ'
            chart_type = request.args.get('type', 'kline')
            period = request.args.get('period', '1M')

            days_map = {'1D': 5, '5D': 10, '1M': 30, '3M': 90, '6M': 180, '1Y': 365, 'ALL': 730}
            days = days_map.get(period, 30)
            cache_key = f'chart:{code}:{chart_type}:{period}'
            def _load_chart():
                df = stock_repo.get_history(code, days=days)
                if df is None or df.empty or len(df) < 2:
                    return None
                if len(df) > days * 1.5:
                    df = df.tail(days)
                fig = _build_plotly_fig(df, code, chart_type)
                return {'fig': fig, 'source': 'real'}
            data = _cached(cache_key, _load_chart, ttl=300)
            if data is None:
                return jsonify({'success': False, 'error': 'K线数据不足'}), 404
            return jsonify({'success': True, 'fig': data['fig'], 'source': data['source']})
        except Exception as e:
            logger.exception('get_chart failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    # ── 财务摘要（替代 akshare stock_financial_abstract）──
    @app.route('/api/financials/<code>', methods=['GET'])
    @require_auth
    def get_financials(code):
        try:
            from src.core.fundamental import calculate
            market = 'SH' if code.startswith('6') else 'SZ'
            result = calculate(code, market)
            # v1.3: 兼容前端 table.js（期望数组格式：label/current/previous/change/peer）
            indicators = result.get('financial_indicators') or {}
            table_items = [
                {
                    'label': name,
                    'current': round(val, 2) if isinstance(val, float) else val,
                    'previous': '—',
                    'change': '—',
                    'peer': '—',
                }
                for name, val in indicators.items()
            ]
            return jsonify({
                'success': True,
                'data': table_items,
                'raw': result,  # 原始对象也返回，供新前端使用
                'source': 'real',
            })
        except Exception as e:
            logger.exception('get_financials failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    # ── 龙虎榜（table.js dragon tab）───────────
    @app.route('/api/financials/<code>/dragon', methods=['GET'])
    @require_auth
    def get_dragon_tiger_tab(code):
        """龙虎榜数据（table.js dragon tab）"""
        try:
            from src.core.signals import SignalsGenerator
            gen = SignalsGenerator()
            data = gen.get_dragon_tiger(code) if hasattr(gen, 'get_dragon_tiger') else {}
            records = data.get('records', []) if isinstance(data, dict) else []
            # 转换为 table.js 期望的 {label,current,previous,change,peer} 格式
            items = [
                {
                    'label': r.get('date', '—'),
                    'current': r.get('net_buy', '—'),
                    'previous': r.get('turnover', '—'),
                    'change': r.get('reason', '—'),
                    'peer': '—',
                }
                for r in records
            ]
            return jsonify({'success': True, 'data': items, 'source': 'real', 'meta': {'count': len(items)}})
        except Exception as e:
            logger.warning(f'龙虎榜数据获取失败 {code}: {e}')
            return jsonify({'success': True, 'data': [], 'source': 'unavailable'})

    # ── 资金流向（table.js fund tab）────────────
    @app.route('/api/financials/<code>/fund', methods=['GET'])
    @require_auth
    def get_fund_flow_tab(code):
        """资金流向数据（table.js fund tab）"""
        try:
            from src.core.signals import SignalsGenerator
            gen = SignalsGenerator()
            data = gen.get_fund_flow(code) if hasattr(gen, 'get_fund_flow') else {}
            # 转换为 table.js 期望格式
            items = [
                {'label': k, 'current': v, 'previous': '—', 'change': '—', 'peer': '—'}
                for k, v in (data.items() if isinstance(data, dict) else [])
            ]
            return jsonify({'success': True, 'data': items, 'source': 'real'})
        except Exception as e:
            logger.warning(f'资金流向获取失败 {code}: {e}')
            return jsonify({'success': True, 'data': [], 'source': 'unavailable'})

    # ── 大宗交易（table.js block tab）───────────
    @app.route('/api/financials/<code>/block', methods=['GET'])
    @require_auth
    def get_block_deals_tab(code):
        """大宗交易数据（table.js block tab）—— 当前无真实数据源"""
        return jsonify({
            'success': True,
            'data': [],
            'source': 'unavailable',
            'meta': {'note': '大宗交易数据暂未接入'}
        })

    # ── 技术指标（signals.js 主路径）────────────
    @app.route('/api/indicators/<code>', methods=['GET'])
    @require_auth
    def get_indicators(code):
        """与 /api/analyze/quick 同源，但仅返回 indicators + signals + scores + L0-L3

        单股分析单次 30-40s（缠论+财务+AI 策略），60s 内复用缓存。
        """
        try:
            market = 'SH' if code.startswith('6') else 'SZ'

            def _load():
                analyzer = get_analyzer_fn() if get_analyzer_fn else None
                if analyzer is None:
                    from src.core.analyzer import StockAnalyzer
                    from src.data.registry import registry
                    analyzer = StockAnalyzer(registry=registry)
                result = analyzer.analyze_stock(code, market)
                tech = result.get('technical') or {}
                # four_layer 改为懒加载（独立 API 调用），不阻塞主指标返回
                return {
                    'indicators': _format_indicators(tech, four_layer=None, chanlun=result.get('chanlun')),
                    'signals': result.get('signals', []),
                    'scores': result.get('scores', {}),
                    'score_explains': result.get('strategy', {}).get('explain', {}),
                    'four_layer': None,  # 由 /api/indicators/<code>/signals 独立拉取
                }

            data = _cached(f'indicators:{code}', _load, ttl=300)
            return jsonify({'success': True, 'data': data, 'source': 'real'})
        except Exception as e:
            logger.exception('get_indicators failed')
            return _indicators_fallback(code, e)

    # ── 个股新闻聚合 ──────────────────────────
    @app.route('/api/news/<code>', methods=['GET'])
    @require_auth
    def get_stock_news(code):
        try:
            from src.data.news_sources import build_stock_news_bundle
            from src.repository.stock_repo import stock_repo
            name = stock_repo.get_name(code) or code
            sector_info = stock_repo.get_industry(code)
            sector = (sector_info.get('industry') or ['—'])[0] if sector_info.get('industry') else '—'
            bundle = build_stock_news_bundle(code, name, sector)
            return jsonify({'success': True, 'data': bundle, 'source': 'real'})
        except Exception as e:
            logger.exception('get_stock_news failed')
            return jsonify({'success': False, 'error': str(e)}), 500


    # ── 四层量化信号（独立懒加载）──────────────
    @app.route('/api/indicators/<code>/signals', methods=['GET'])
    @require_auth
    def get_stock_signals(code):
        try:
            market = 'SH' if code.startswith('6') else 'SZ'
            data = _cached(f'four_layer:{code}', lambda: _compute_four_layer_safe(code, market), ttl=300)
            return jsonify({'success': True, 'data': data, 'source': 'real'})
        except Exception as e:
            logger.exception('get_stock_signals failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    # ── 策略回测 ──────────────────────────────
    @app.route('/api/backtest/<code>', methods=['GET'])
    @require_auth
    def get_backtest(code):
        """回测指定股票的所有策略"""
        try:
            market = 'SH' if code.startswith('6') else 'SZ'
            from src.repository.stock_repo import stock_repo
            df = stock_repo.get_history(code, days=365 * 2)
            if df is None or df.empty or len(df) < 60:
                return jsonify({'success': False, 'error': '历史数据不足 60 日'}), 400

            # 标准化列名
            df.columns = [c.lower() for c in df.columns]
            if 'date' not in df.columns:
                df['date'] = df.index.astype(str)

            from src.core.backtest import compare_strategies

            def _load_bt():
                return compare_strategies(df)
            results = _cached(f'backtest:{code}', _load_bt, ttl=300)

            out = {}
            for key, res in results.items():
                out[key] = {
                    'name': res.strategy_name,
                    'total_return': res.total_return,
                    'annual_return': res.annual_return,
                    'win_rate': res.win_rate,
                    'total_trades': res.total_trades,
                    'winning_trades': res.winning_trades,
                    'losing_trades': res.losing_trades,
                    'max_drawdown': res.max_drawdown,
                    'sharpe': res.sharpe,
                    'profit_factor': res.profit_factor,
                    'avg_win': res.avg_win,
                    'avg_loss': res.avg_loss,
                    'best_trade': res.best_trade,
                    'worst_trade': res.worst_trade,
                    'buy_hold_return': res.buy_hold_return,
                }

            return jsonify({'success': True, 'data': out})
        except Exception as e:
            logger.exception('get_backtest failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    # ── 增强扫盘 ──────────────────────────────
    @app.route('/api/screener/enriched', methods=['GET'])
    @require_auth
    def get_screener_enriched():
        """增强扫盘。
        scope=tracked（默认）：持仓+自选，瞬时
        scope=all：全市场，慢（60s+）
        """
        scope = request.args.get('scope', 'tracked').lower()
        if scope == 'all':
            return _screener_scope_all(request)

        # ── scope=tracked（默认）：快路径 ──
        try:
            from src.data.tencent import TencentSource
            from src.data.base import infer_market
            from src.storage.watchlist_repo import WatchlistRepository
            from src.storage.patrol_repo import PatrolRepository

            strategy = request.args.get('strategy', 'ALL').upper()
            limit = min(int(request.args.get('limit', 50)), 200)

            # 收集关注的股票代码（持仓 + 自选）
            rows = {}
            for row in WatchlistRepository().get_all():
                if row.get('code'):
                    rows[row['code']] = row.get('name') or row['code']
            for row in PatrolRepository().get_all_sorted():
                if row.get('code'):
                    rows[row['code']] = row.get('name') or row['code']

            # 如果关注列表为空，从 stock_basics 取前 500 只兜底
            if not rows:
                from src.repository.stock_repo import stock_repo
                basics = stock_repo.get_sqlite_connection()
                try:
                    cur = basics.execute("SELECT code, name FROM stock_basics LIMIT 500")
                    for r in cur:
                        rows[r['code']] = r['name'] or r['code']
                finally:
                    basics.close()

            source = TencentSource()
            result = []
            for code, fallback_name in rows.items():
                quote = source.get_quote(code, infer_market(code))
                if quote is None:
                    continue
                result.append({
                    'code': code,
                    'name': quote.name or fallback_name,
                    'price': quote.price,
                    'change_pct': quote.change_pct,
                    'volume': quote.volume,
                    'volume_ratio': getattr(quote, 'volume_ratio', None),
                    'turnover_pct': None,
                    'pe': None,
                    'final_score': 50,
                    'themes': [],
                })

            if strategy == 'TOP_GAIN':
                result = [r for r in result if (r.get('change_pct') or 0) > 0]
                result.sort(key=lambda r: -(r['change_pct'] or 0))
            elif strategy == 'TOP_LOSS':
                result = [r for r in result if (r.get('change_pct') or 0) < 0]
                result.sort(key=lambda r: r['change_pct'] or 0)
            elif strategy == 'VOLUME':
                result.sort(key=lambda r: -(r.get('volume') or 0))
            elif strategy in ('NORTH', 'HOT'):
                result.sort(key=lambda r: -(r.get('change_pct') or 0))
            else:
                result.sort(key=lambda r: -(r.get('change_pct') or 0))

            result = result[:limit]
            return jsonify({
                'success': True,
                'data': result,
                'source': 'real:tencent-tracked',
                'meta': {'total_scanned': len(rows), 'matched': len(result)},
                'scope': 'tracked',
                'unavailable': {
                    'pe': '暂无市盈率数据源',
                    'turnover_pct': '暂无换手率数据源',
                    'north_flow': '暂无北向资金数据源',
                    'themes': '暂无热点题材数据源',
                },
            })
        except Exception as e:
            logger.exception('get_screener_enriched(tracked) failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    # ── Part 2 路由：铲子股 / 情绪 / 信号 / 自选股 / 缓存 ──
    _register_routes_part2(app, require_auth)


def _register_routes_part2(app, require_auth):
    """续接路由注册（Part 1 register_extra_routes 末尾调用）"""
    @app.route('/api/screener/bottleneck', methods=['GET'])
    @require_auth
    def get_screener_bottleneck():
        """铲子股卡位策略

        算法：THS 热门板块 → 知识库卡脖子关键词 → 全市场快照 → 估值/市值/换手过滤 → 评分
        缓存 60s（避免重复拉全市场 5000+ 只）

        Query:
          sectors: 逗号分隔业务板块名（KB key），如 "AI算力,半导体设备,人形机器人"
                   留空时回退到 THS 涨幅榜
        """
        try:
            from src.core.bottleneck_strategy import screen as bottleneck_screen
            from src.core.bottleneck_kb import list_sectors

            # 解析 sectors 参数
            sectors_param = request.args.get('sectors', '').strip()
            top_sector_names = [s.strip() for s in sectors_param.split(',') if s.strip()] or None

            cache_key = f'screener_bottleneck:{sectors_param or "ths"}:{request.args.get("pe_max", 50)}:{request.args.get("max_mc", 300)}:{request.args.get("min_turnover", 1.0)}'

            def _load():
                return bottleneck_screen(
                    top_sectors=int(request.args.get('top_sectors', 6)),
                    top_sector_names=top_sector_names,
                    pe_min=float(request.args.get('pe_min', 0)),
                    pe_max=float(request.args.get('pe_max', 50)),
                    pb_max=float(request.args.get('pb_max', 10)),
                    min_market_cap_yi=float(request.args.get('min_mc', 0)),
                    max_market_cap_yi=float(request.args.get('max_mc', 300)),
                    min_turnover=float(request.args.get('min_turnover', 1.0)),
                    limit=int(request.args.get('limit', 30)),
                )

            data = _cached(cache_key, _load, ttl=300)
            return jsonify({
                'success': True,
                'source': 'real:akshare-spot+ths-industry',
                'strategy': 'BOTTLENECK',
                'data': data.get('candidates', []),
                'meta': {
                    'top_sectors': data.get('top_sectors', []),
                    'scanned': data.get('scanned', 0),
                    'sector_summary': data.get('sector_summary', {}),
                    'candidates_count': len(data.get('candidates', [])),
                    'available_sectors': list_sectors(),
                    'requested_sectors': top_sector_names or [],
                    'error': data.get('error'),
                },
            })
        except Exception as e:
            logger.exception('get_screener_bottleneck failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    # ── 市场情绪 ──────────────────────────────
    @app.route('/api/sentiment/market', methods=['GET'])
    @require_auth
    def get_market_sentiment():
        try:
            def _load():
                from src.core.signals import SignalsGenerator
                gen = SignalsGenerator()
                data = gen.get_market_sentiment() if hasattr(gen, 'get_market_sentiment') else {}
                if not data:
                    north = gen.get_northbound() if hasattr(gen, 'get_northbound') else {}
                    data = {'north': north, 'timestamp': datetime.now().isoformat()}
                # v1.3: 补充涨跌家数（advance_decline）
                # 优先从 stock_cache 实时统计，不可用则放占位值
                try:
                    from src.core.stock_cache import stock_cache
                    cached = stock_cache.get_stocks_by_price_range(limit=5000)
                    valid = [s for s in cached if s.is_valid()]
                    # StockCache 刚启动时可能还没拉数据，尝试手动触发一次刷新
                    if len(valid) < 100:
                        try:
                            updated = stock_cache.update_prices()
                            if updated > 0:
                                cached = stock_cache.get_stocks_by_price_range(limit=5000)
                                valid = [s for s in cached if s.is_valid()]
                        except Exception:
                            pass
                    up = sum(1 for s in valid if s.change_pct > 0)
                    down = sum(1 for s in valid if s.change_pct < 0)
                    flat = len(valid) - up - down
                    data['advance_decline'] = {
                        'up': up, 'down': down, 'flat': flat, 'total': len(valid)
                    }
                except Exception:
                    data.setdefault('advance_decline', {'up': 0, 'down': 0, 'flat': 0, 'total': 0})
                return data
            data = _cached('sentiment_market', _load, ttl=60)
            return jsonify({'success': True, 'data': data, 'source': 'real'})
        except Exception as e:
            logger.exception('get_market_sentiment failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    # ── 单类信号 ──────────────────────────────
    @app.route('/api/signals/<signal_type>', methods=['GET'])
    @require_auth
    def get_signal_by_type(signal_type):
        try:
            from src.core.signals import SignalsGenerator
            gen = SignalsGenerator()
            method = getattr(gen, f'get_{signal_type}_signal', None) or getattr(gen, f'get_{signal_type}', None)
            items = method() if method else []
            return jsonify({
                'success': True,
                'data': items if isinstance(items, list) else [],
                'source': 'real',
            })
        except Exception as e:
            logger.exception(f'get_signal_{signal_type} failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    # ── 全部信号 ──────────────────────────────
    @app.route('/api/signals/all', methods=['GET'])
    @require_auth
    def get_signals_all():
        try:
            def _load():
                from src.core.signals import SignalsGenerator
                gen = SignalsGenerator()
                payload = {}
                unavailable = {}
                try:
                    res = gen.get_hot_stocks()
                    raw = res.to_dict('records') if hasattr(res, 'to_dict') and res is not None else (res or [])
                    # 兼容中文列名 → 英文列名
                    payload['hot'] = [{
                        'code': r.get('code') or r.get('代码', ''),
                        'name': r.get('name') or r.get('名称', ''),
                        'change_pct': r.get('change_pct') or r.get('涨幅', 0),
                        'reason': r.get('reason') or r.get('题材归因', ''),
                    } for r in raw]
                except Exception as ex:
                    logger.warning(f'信号 hot 失败: {ex}')
                    payload['hot'] = []
                try:
                    res = gen.get_fund_flow_signal() if hasattr(gen, 'get_fund_flow_signal') else []
                    payload['fund'] = res if isinstance(res, list) else []
                except Exception as ex:
                    logger.warning(f'信号 fund 失败: {ex}')
                    payload['fund'] = []
                try:
                    res = gen.get_dragon_tiger()
                    raw = res.to_dict('records') if hasattr(res, 'to_dict') else (res if isinstance(res, list) else [])
                    payload['dragon'] = [{
                        'code': r.get('code', ''),
                        'name': r.get('name', ''),
                        'reason': r.get('reason', ''),
                        'net_buy': r.get('net_buy', 0),
                    } for r in raw][:10]
                except Exception as ex:
                    logger.warning(f'信号 dragon 失败: {ex}')
                    payload['dragon'] = []
                    unavailable['dragon'] = True
                unavailable['report'] = True
                payload['report'] = []
                return {'payload': payload, 'unavailable': unavailable}
            cached = _cached('signals_all', _load, ttl=60)
            return jsonify({
                'success': True,
                'data': cached['payload'],
                'source': 'real',
                'unavailable': cached['unavailable'],
                'timestamp': datetime.now().isoformat(),
            })
        except Exception as e:
            logger.exception('get_signals_all failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    # ── 自选股 CRUD ───────────────────────────
    @app.route('/api/watchlist', methods=['GET'])
    @require_auth
    def watchlist_list():
        try:
            from src.storage.watchlist_repo import get_repo
            return jsonify({'success': True, 'data': get_repo().get_all()})
        except Exception as e:
            logger.exception('watchlist_list failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/watchlist', methods=['POST'])
    @require_auth
    def watchlist_add():
        try:
            from src.storage.watchlist_repo import get_repo
            data = request.get_json(silent=True) or {}
            code = (data.get('code') or '').strip()
            if not code:
                return jsonify({'success': False, 'error': 'code required'}), 400
            from src.repository.stock_repo import stock_repo
            name = stock_repo.get_name(code) or code
            project = (data.get('project') or '默认').strip() or '默认'
            group_color = data.get('group_color', '') or ''
            added = get_repo().add(code, name, project, group_color)
            if added is None:
                return jsonify({'success': False, 'error': 'already exists'}), 409
            return jsonify({'success': True, 'data': added})
        except Exception as e:
            logger.exception('watchlist_add failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/watchlist/<code>', methods=['DELETE'])
    @require_auth
    def watchlist_remove(code):
        try:
            from src.storage.watchlist_repo import get_repo
            ok = get_repo().remove(code)
            if not ok:
                return jsonify({'success': False, 'error': 'not found'}), 404
            return jsonify({'success': True, 'data': get_repo().get_all()})
        except Exception as e:
            logger.exception('watchlist_remove failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/watchlist/reorder', methods=['POST'])
    @require_auth
    def watchlist_reorder():
        try:
            from src.storage.watchlist_repo import get_repo
            data = request.get_json(silent=True) or {}
            ordered = data.get('ordered') or []
            if not isinstance(ordered, list):
                return jsonify({'success': False, 'error': 'ordered must be list'}), 400
            n = get_repo().reorder(ordered)
            return jsonify({'success': True, 'data': get_repo().get_all(), 'updated': n})
        except Exception as e:
            logger.exception('watchlist_reorder failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/watchlist/rename-project', methods=['POST'])
    @require_auth
    def watchlist_rename_project():
        try:
            from src.storage.watchlist_repo import get_repo
            data = request.get_json(silent=True) or {}
            old = (data.get('old') or '').strip()
            new = (data.get('new') or '').strip()
            if not old or not new:
                return jsonify({'success': False, 'error': 'old/new required'}), 400
            n = get_repo().rename_project(old, new)
            return jsonify({'success': True, 'data': get_repo().get_all(), 'updated': n})
        except Exception as e:
            logger.exception('watchlist_rename_project failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    # ── 缓存统计（监控面板）────────────────────────
    @app.route('/api/cache/stats', methods=['GET'])
    @require_auth
    def get_cache_stats_endpoint():
        """返回进程级 TTL 缓存命中率统计"""
        try:
            return jsonify({'success': True, 'data': get_cache_stats()})
        except Exception as e:
            logger.exception('get_cache_stats failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    logger.info("补齐路由注册完成 (extra_routes)")


def _screener_scope_all(req):
    """全市场扫盘（慢，60s+），用 SmartStockScreener，结果缓存 300s"""
    try:
        strategy = req.args.get('strategy', 'ALL').upper()
        limit = min(int(req.args.get('limit', 50)), 100)

        def _load():
            from src.core.screener import SmartStockScreener
            screener = SmartStockScreener()
            results = screener.screener(strategy='ALL', limit=200).get('stocks', [])
            out = []
            for r in results:
                themes_raw = (r.get('sector') or '')
                out.append({
                    'code': r.get('code', ''),
                    'name': r.get('name', ''),
                    'price': r.get('price', 0),
                    'change_pct': r.get('change_pct', 0),
                    'volume': r.get('volume', 0),
                    'volume_ratio': r.get('volume_ratio', None),
                    'turnover_pct': None,
                    'pe': r.get('pe', None),
                    'final_score': r.get('final_score', 50),
                    'themes': [themes_raw] if themes_raw and themes_raw != '未知' else [],
                    'risk_level': r.get('risk_level', 'MEDIUM'),
                    'strategy_b_desc': r.get('strategy_b_desc', ''),
                })
            return out

        all_data = _cached('screener_scope_all', _load, ttl=300)

        # 在缓存外按策略 + limit 过滤
        if strategy == 'TOP_GAIN':
            all_data = [r for r in all_data if (r.get('change_pct') or 0) > 0]
            all_data.sort(key=lambda r: -(r['change_pct'] or 0))
        elif strategy == 'TOP_LOSS':
            all_data = [r for r in all_data if (r.get('change_pct') or 0) < 0]
            all_data.sort(key=lambda r: r['change_pct'] or 0)
        elif strategy == 'VOLUME':
            all_data.sort(key=lambda r: -(r.get('volume') or 0))
        elif strategy == 'NORTH':
            all_data.sort(key=lambda r: -(r['final_score'] or 0))
        else:
            all_data.sort(key=lambda r: -(r.get('final_score') or 0))

        all_data = all_data[:limit]
        return jsonify({
            'success': True,
            'data': all_data,
            'source': 'screener:v3',
            'meta': {'total_scanned': len(all_data), 'matched': len(all_data)},
            'scope': 'all',
        })
    except Exception as e:
        logger.exception('_screener_scope_all failed')
        return jsonify({'success': False, 'error': str(e)}), 500




# ── helpers ─────────────────────────────────────
def _format_indicators(tech: dict, four_layer: dict = None, chanlun: dict = None) -> list:
    """analyzer.technical dict → 前端 indicator-grid 友好结构"""
    if not tech:
        return []
    kdj = tech.get('kdj', {}) or {}
    rsi_val = tech.get('rsi', 50)
    boll_val = tech.get('bollinger_position', 0.5)
    cci_val = tech.get('cci', 0)
    vr_val = tech.get('vr', 100)
    items = [
        {
            'key': 'ma_trend', 'label': '均线排列', 'value': tech.get('ma_trend', '—'), 'kind': 'text',
            'explain': _ma_trend_explain(tech.get('ma_trend', '')),
        },
        {
            'key': 'rsi', 'label': 'RSI(14)', 'value': rsi_val, 'kind': 'number',
            'explain': _rsi_explain(rsi_val),
        },
        {
            'key': 'macd_signal', 'label': 'MACD', 'value': tech.get('macd_signal', '—'), 'kind': 'text',
            'explain': _macd_explain(tech.get('macd_signal', '')),
        },
        {
            'key': 'volume_status', 'label': '量能', 'value': tech.get('volume_status', '—'), 'kind': 'text',
            'explain': _volume_explain(tech.get('volume_status', '')),
        },
        {
            'key': 'kdj', 'label': 'KDJ', 'value': f"K{kdj.get('k', 50):.1f} D{kdj.get('d', 50):.1f} J{kdj.get('j', 50):.1f}", 'kind': 'text',
            'explain': _kdj_explain(kdj),
        },
        {
            'key': 'bollinger_position', 'label': '布林带位置', 'value': boll_val, 'kind': 'number',
            'explain': _boll_explain(boll_val),
        },
        {
            'key': 'vr', 'label': 'VR', 'value': vr_val, 'kind': 'number',
            'explain': _vr_explain(vr_val),
        },
        {
            'key': 'cci', 'label': 'CCI', 'value': cci_val, 'kind': 'number',
            'explain': _cci_explain(cci_val),
        },
        {
            'key': 'trix', 'label': 'TRIX', 'value': tech.get('trix', 0), 'kind': 'number',
            'explain': {'meaning': '三重指数平滑平均线，过滤短期波动', 'action': '结合价格趋势使用'},
        },
        {
            'key': 'atr', 'label': 'ATR', 'value': tech.get('atr', 0), 'kind': 'number',
            'explain': {'meaning': '平均真实波幅，衡量价格波动程度', 'action': 'ATR 越大止损应设越宽'},
        },
        {
            'key': 'obv', 'label': 'OBV', 'value': tech.get('obv', 0), 'kind': 'number',
            'explain': {'meaning': '累积成交量，量能先行指标', 'action': 'OBV 领先价格需关注'},
        },
        {
            'key': 'obv_signal', 'label': 'OBV信号', 'value': tech.get('obv_signal', '—'), 'kind': 'text',
            'explain': _obv_signal_explain(tech.get('obv_signal', '')),
        },
        # MyTT 扩展指标
        {
            'key': 'pdi', 'label': 'PDI', 'value': tech.get('pdi', 0), 'kind': 'number',
            'explain': _dmi_explain(tech),
        },
        {
            'key': 'adx', 'label': 'ADX', 'value': tech.get('adx', 0), 'kind': 'number',
            'explain': {'meaning': '平均趋向指数，衡量趋势强度', 'action': 'ADX > 25 趋势强劲，ADX < 20 震荡盘整'},
        },
        {
            'key': 'bias6', 'label': 'BIAS(6)', 'value': tech.get('bias6', 0), 'kind': 'number',
            'explain': _bias_explain(tech.get('bias6', 0)),
        },
        {
            'key': 'wr10', 'label': 'WR(10)', 'value': tech.get('wr10', 0), 'kind': 'number',
            'explain': _wr_explain(tech.get('wr10', 0)),
        },
        {
            'key': 'mtm', 'label': 'MTM', 'value': tech.get('mtm', 0), 'kind': 'number',
            'explain': {'meaning': '动量指标，衡量价格变动速度', 'action': 'MTM 上穿零轴可关注'},
        },
        {
            'key': 'roc', 'label': 'ROC', 'value': tech.get('roc', 0), 'kind': 'number',
            'explain': {'meaning': '变动率指标，衡量价格变化百分比', 'action': 'ROC 上穿零轴为参考买入信号'},
        },
        {
            'key': 'psy', 'label': 'PSY', 'value': tech.get('psy', 50), 'kind': 'number',
            'explain': {'meaning': '心理线指标，反映市场情绪', 'action': 'PSY > 75 过热，PSY < 25 过冷'},
        },
    ]
    # 缠论：优先用直接传入的 chanlun dict（from analyze_stock），其次用 four_layer L3
    if chanlun:
        ch = chanlun
        score = ch.get('chanlun_score', 0.0)
        val = ch.get('chanlun_score', 0.0)
        trend = ch.get('current_trend', 'N/A')
        strength = ch.get('trend_strength', '')
        summary = ch.get('summary', '')
        available = ch.get('available', False)
        if available:
            label_val = f"{score:.2f}" if isinstance(score, (int, float)) else str(score)
            meaning = f"缠论 {trend} {'（' + strength + '）' if strength else ''}｜{summary}" if summary else f"缠论 {trend} {'（' + strength + '）' if strength else ''}"
        else:
            label_val = summary or '数据不足'
            meaning = summary or '缠论数据暂不可用'
        items.append({
            'key': 'chanlun', 'label': '缠论', 'value': label_val, 'kind': 'number',
            'level': 'neg' if val < -0.3 else 'pos' if val > 0.3 else '',
            'explain': {'meaning': meaning, 'action': '关注中枢突破方向'}
        })
        # 中枢状态（直接 chanlun 有 fenxing/beichi 等信息）
        fenxing = ch.get('fenxing', '')
        if fenxing:
            items.append({
                'key': 'chanlun_fenxing', 'label': '分型状态', 'value': fenxing,
                'kind': 'text',
            })
    elif four_layer and 'L3' in four_layer:
        l3 = four_layer['L3']
        val = l3.get('value', 0.0)
        expl = l3.get('explain', {}) or {}
        desc = f"{val:.2f}" if isinstance(val, (int, float)) else str(val)
        items.append({
            'key': 'chanlun', 'label': '缠论', 'value': desc, 'kind': 'number',
            'level': 'neg' if val < -0.3 else 'pos' if val > 0.3 else '',
            'explain': {'meaning': expl.get('meaning', ''), 'action': expl.get('action', '')}
        })
        # 缠论辅助：中枢状态
        chanlun_detail = l3.get('chanlun_detail') or {}
        if chanlun_detail:
            items.append({
                'key': 'chanlun_zhongshu', 'label': '中枢状态', 'value': chanlun_detail.get('zhongshu', '—'),
                'kind': 'text',
            })
    return items


def _ma_trend_explain(val: str) -> dict:
    if '多头' in val:
        return {'meaning': '短期均线在长期均线上方，趋势向上', 'action': '趋势向上，可持有'}
    if '空头' in val:
        return {'meaning': '短期均线在长期均线下方，趋势向下', 'action': '趋势向下，观望为主'}
    return {'meaning': '均线缠绕交叉，方向不明', 'action': '震荡整理，高抛低吸或观望'}

def _rsi_explain(val) -> dict:
    if isinstance(val, str):
        try: val = float(val)
        except (ValueError, TypeError): return {'meaning': 'RSI 值异常', 'action': '参考其他指标'}
    if val > 80:
        return {'meaning': f'RSI {val:.1f}，严重超买，价格可能回调', 'action': '注意风险，可考虑减仓'}
    if val > 70:
        return {'meaning': f'RSI {val:.1f}，进入超买区，上涨动能趋弱', 'action': '持有关注，不追高'}
    if val > 60:
        return {'meaning': f'RSI {val:.1f}，偏强区间', 'action': '持有为主'}
    if val < 20:
        return {'meaning': f'RSI {val:.1f}，极度超卖，价格可能反弹', 'action': '分批布局，设好止损'}
    if val < 30:
        return {'meaning': f'RSI {val:.1f}，进入超卖区，下跌动能衰减', 'action': '关注反弹机会，需等信号确认'}
    if val < 40:
        return {'meaning': f'RSI {val:.1f}，偏弱区间', 'action': '观望为主'}
    return {'meaning': f'RSI {val:.1f}，中性区间', 'action': '结合其他指标判断'}

def _macd_explain(val: str) -> dict:
    if '金叉' in val or '向上' in val:
        return {'meaning': 'DIF 上穿 DEA，多头信号', 'action': '可考虑建仓或加仓'}
    if '死叉' in val or '向下' in val:
        return {'meaning': 'DIF 下穿 DEA，空头信号', 'action': '减仓或离场观望'}
    if '零轴' in val:
        return {'meaning': 'MACD 在零轴附近，多空平衡', 'action': '观望等待方向选择'}
    return {'meaning': 'MACD 信号', 'action': '结合 K 线形态判断'}

def _volume_explain(val: str) -> dict:
    if '放量' in val:
        return {'meaning': '成交量显著放大，市场活跃', 'action': '放量上涨可跟进，放量下跌需警惕'}
    if '缩量' in val:
        return {'meaning': '成交量萎缩，市场观望情绪浓', 'action': '缩量整理等待变盘方向'}
    return {'meaning': '成交量平稳，无明显变化', 'action': '观望为主'}

def _kdj_explain(kdj: dict) -> dict:
    k = kdj.get('k', 50)
    d = kdj.get('d', 50)
    j = kdj.get('j', 50)
    if j < 0:
        return {'meaning': f'J值 {j:.1f} < 0，极度超卖', 'action': '短线可能反弹，关注 K 线反转信号'}
    if k > 80 and d > 80:
        return {'meaning': f'K {k:.1f} D {d:.1f} 均 > 80，超买', 'action': '短线过热，注意回调'}
    if k > 80:
        return {'meaning': f'K {k:.1f} > 80，接近超买', 'action': '持有关注，不追高'}
    if k < 20 and d < 20:
        return {'meaning': f'K {k:.1f} D {d:.1f} 均 < 20，超卖', 'action': '关注超卖反弹机会'}
    if k < 20:
        return {'meaning': f'K {k:.1f} < 20，接近超卖', 'action': '短线可能见底'}
    if k > d:
        return {'meaning': f'K {k:.1f} > D {d:.1f}，K线上穿', 'action': '短线偏多'}
    return {'meaning': f'K {k:.1f} D {d:.1f} J {j:.1f}，中性', 'action': '观望'}

def _boll_explain(val) -> dict:
    if isinstance(val, str):
        try: val = float(val)
        except (ValueError, TypeError): return {'meaning': '布林带位置异常', 'action': '参考其他指标'}
    if val > 1.0:
        return {'meaning': f'价格贴近布林上轨 (位置 {val:.2f})，超买', 'action': '注意回调风险，可减仓'}
    if val > 0.8:
        return {'meaning': f'价格偏向上轨 (位置 {val:.2f})，强势', 'action': '持有但不追高'}
    if val < -1.0:
        return {'meaning': f'价格贴近布林下轨 (位置 {val:.2f})，超卖', 'action': '关注支撑位反弹机会'}
    if val < -0.8:
        return {'meaning': f'价格偏向下轨 (位置 {val:.2f})，弱势', 'action': '观望，等止跌信号'}
    return {'meaning': f'价格在布林中轨附近 (位置 {val:.2f})，震荡', 'action': '高抛低吸或观望'}

def _vr_explain(val) -> dict:
    if isinstance(val, str):
        try: val = float(val)
        except (ValueError, TypeError): return {'meaning': 'VR 值异常', 'action': '参考其他指标'}
    if val > 300:
        return {'meaning': f'VR {val:.0f}，高量区，人气过热', 'action': '注意主力出货风险'}
    if val > 150:
        return {'meaning': f'VR {val:.0f}，量能偏高', 'action': '持有关注量能变化'}
    if val < 70:
        return {'meaning': f'VR {val:.0f}，低量区，市场冷清', 'action': '关注放量启动信号'}
    if val < 100:
        return {'meaning': f'VR {val:.0f}，量能偏低', 'action': '量能不足，不宜重仓'}
    return {'meaning': f'VR {val:.0f}，正常量能区间', 'action': '中性'}

def _cci_explain(val) -> dict:
    if isinstance(val, str):
        try: val = float(val)
        except (ValueError, TypeError): return {'meaning': 'CCI 值异常', 'action': '参考其他指标'}
    if val > 200:
        return {'meaning': f'CCI {val:.0f} > 200，严重超买', 'action': '注意高位回调风险'}
    if val > 100:
        return {'meaning': f'CCI {val:.0f} > 100，进入超买区', 'action': '短期偏强但需警惕'}
    if val < -200:
        return {'meaning': f'CCI {val:.0f} < -200，严重超卖', 'action': '关注超卖反弹机会'}
    if val < -100:
        return {'meaning': f'CCI {val:.0f} < -100，进入超卖区', 'action': '下跌动能强，观望'}
    if val < 0:
        return {'meaning': f'CCI {val:.0f} < 0，弱势', 'action': '空头主导，观望为主'}
    return {'meaning': f'CCI {val:.0f}，中性区间', 'action': '结合价格趋势判断'}

def _obv_signal_explain(val: str) -> dict:
    if '背离' in val:
        return {'meaning': 'OBV 与价格走势背离，信号强烈', 'action': '顶背离减仓，底背离关注买入'}
    if '同步' in val:
        return {'meaning': 'OBV 与价格同步，趋势稳健', 'action': '趋势延续概率大'}
    if '中性' in val:
        return {'meaning': 'OBV 方向不明显', 'action': '等待更明确信号'}
    return {'meaning': f'OBV {val}', 'action': '结合价格趋势判断'}


def _dmi_explain(tech: dict) -> dict:
    """DMI 指标说明（PDI / MDI / ADX 组合）"""
    pdi = tech.get('pdi', 0) or 0
    mdi = tech.get('mdi', 0) or 0
    adx = tech.get('adx', 0) or 0
    if adx > 25 and pdi > mdi:
        return {'meaning': f'ADX {adx:.0f} 趋势强劲，PDI {pdi:.0f} > MDI {mdi:.0f} 多头主导', 'action': '上升趋势中，可持有'}
    if adx > 25 and pdi < mdi:
        return {'meaning': f'ADX {adx:.0f} 趋势强劲，MDI {mdi:.0f} > PDI {pdi:.0f} 空头主导', 'action': '下跌趋势中，规避为主'}
    if adx < 20:
        return {'meaning': f'ADX {adx:.0f} < 20，无趋势震荡', 'action': '横盘整理，高抛低吸或观望'}
    if pdi > mdi:
        return {'meaning': f'PDI {pdi:.0f} > MDI {mdi:.0f}，偏多', 'action': '短线偏多，关注 ADX 确认趋势'}
    return {'meaning': f'MDI {mdi:.0f} > PDI {pdi:.0f}，偏空', 'action': '短线偏空，观望'}


def _bias_explain(val) -> dict:
    """乖离率 BIAS 说明"""
    if isinstance(val, str):
        try: val = float(val)
        except (ValueError, TypeError): return {'meaning': 'BIAS 值异常', 'action': '参考其他指标'}
    if val > 8:
        return {'meaning': f'BIAS {val:.1f} > 8，严重偏离均线', 'action': '超买严重，注意回调'}
    if val > 5:
        return {'meaning': f'BIAS {val:.1f} > 5，偏离均线', 'action': '短期可能回调'}
    if val < -8:
        return {'meaning': f'BIAS {val:.1f} < -8，严重偏离均线', 'action': '超卖严重，关注反弹'}
    if val < -5:
        return {'meaning': f'BIAS {val:.1f} < -5，偏离均线', 'action': '短期可能有反弹'}
    if val < -3:
        return {'meaning': f'BIAS {val:.1f}，轻度偏离', 'action': '关注回踩均线后的走势'}
    return {'meaning': f'BIAS {val:.1f}，在均线附近', 'action': '中性'}


def _wr_explain(val) -> dict:
    """威廉指标 WR 说明"""
    if isinstance(val, str):
        try: val = float(val)
        except (ValueError, TypeError): return {'meaning': 'WR 值异常', 'action': '参考其他指标'}
    if val < -90:
        return {'meaning': f'WR {val:.0f} < -90，超卖', 'action': '关注反弹机会'}
    if val < -80:
        return {'meaning': f'WR {val:.0f} < -80，接近超卖', 'action': '短线可能见底'}
    if val > -10:
        return {'meaning': f'WR {val:.0f} > -10，超买', 'action': '注意回调风险'}
    if val > -20:
        return {'meaning': f'WR {val:.0f} > -20，接近超买', 'action': '短线可能见顶'}
    return {'meaning': f'WR {val:.0f}，中性区间', 'action': '观望'}


def _compute_four_layer_safe(code: str, market: str) -> dict:
    """L0/L1/L2/L3 计算的兜底包装

    即使某层失败也返回结构化空层（前端 signals.js 会渲染占位 UI），
    避免单个 sub-system 故障把整个 /api/indicators 拖崩。
    """
    try:
        from src.repository.stock_repo import stock_repo
        from src.core.quant_signals import compute_four_layer
        daily = stock_repo.get_history(code, days=180)
        weekly = stock_repo.get_weekly_kline(code, weeks=60)
        minute = stock_repo.get_minute_kline(code, market, period='5')
        return compute_four_layer(daily, weekly, minute)
    except Exception as e:
        logger.warning(f'four_layer 兜底失败 {code}: {e}')
        return {k: {'value': 0.0, 'history': [0.0] * 30,
                   'explain': {'meaning': '信号计算失败', 'action': '稍后重试'}}
                for k in ('L0', 'L1', 'L2', 'L3')}


def _indicators_fallback(code: str, exc: Exception):
    """指标接口全链路失败时的兜底响应

    之前 worker 线程会被 uncaught exception 拖死导致响应体为空；
    现在即使 analyze_stock 全挂，前端也能拿到结构化降级数据。
    """
    logger.error(f'get_indicators 整体兜底 {code}: {exc}')
    return jsonify({
        'success': True,
        'source': 'unavailable',
        'data': {
            'indicators': [],
            'signals': [{'type': '数据加载失败', 'signal': 'neutral',
                         'description': f'分析失败：{str(exc)[:80]}'}],
            'scores': {},
            'score_explains': {},
            'four_layer': _compute_four_layer_safe(
                code, 'SH' if code.startswith('6') else 'SZ'
            ),
        },
        'error': str(exc)[:200],
    }), 200


def _build_plotly_fig(df, code: str, chart_type: str) -> dict:
    """K线/成交量 → Plotly fig dict (前端不依赖 plotly.js 也可降级)"""
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                            row_heights=[0.7, 0.3])
        # 兼容中英文列
        date_col = 'date' if 'date' in df.columns else '日期'
        open_col = 'open' if 'open' in df.columns else '开盘'
        high_col = 'high' if 'high' in df.columns else '最高'
        low_col = 'low' if 'low' in df.columns else '最低'
        close_col = 'close' if 'close' in df.columns else '收盘'
        vol_col = 'volume' if 'volume' in df.columns else '成交量'

        dates = df[date_col].astype(str).tolist()
        # .tolist() 把 numpy 标量转成 Python 原生类型，避免 JSON 序列化失败
        o = df[open_col].astype(float).tolist()
        h = df[high_col].astype(float).tolist()
        l = df[low_col].astype(float).tolist()
        c = df[close_col].astype(float).tolist()
        v = df[vol_col].astype(float).tolist()

        fig.add_trace(go.Candlestick(
            x=dates, open=o, high=h, low=l, close=c, name='K线',
            increasing_line_color='#ef5350', decreasing_line_color='#26a69a'
        ), row=1, col=1)

        # 中国行情惯例：涨=红色(#ef5350)，跌=绿色(#26a69a)
        colors = ['#ef5350' if c[i] >= o[i] else '#26a69a' for i in range(len(df))]
        fig.add_trace(go.Bar(
            x=dates, y=v, marker_color=colors, name='成交量'
        ), row=2, col=1)
        fig.update_layout(xaxis_rangeslider_visible=False, height=500,
                          title=f'{code} K线', template='plotly_dark')
        return _jsonable(fig.to_dict())
    except ImportError:
        # 无 plotly 时返回降级数据
        return {'data': [{'x': df.get('date', df.get('日期', [])).astype(str).tolist(),
                          'close': df.get('close', df.get('收盘', [])).astype(float).tolist(),
                          'type': 'scatter', 'mode': 'lines',
                          'name': chart_type}], 'layout': {'title': f'{code} {chart_type}'}}


def _jsonable(obj):
    """递归把 numpy / pandas 类型转 Python 原生，让 jsonify 不爆"""
    try:
        import numpy as np
    except ImportError:
        return obj
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    if isinstance(obj, np.ndarray):
        return _jsonable(obj.tolist())
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj
