"""智能选股路由模块"""
import logging
from flask import request, jsonify

logger = logging.getLogger(__name__)

# 全局选股器实例
_screener = None


def get_screener():
    """获取或创建选股器实例"""
    global _screener
    if _screener is None:
        from src.core.screener import SmartStockScreener
        _screener = SmartStockScreener()

        # 启动股票缓存后台更新
        from src.core.stock_cache import stock_cache
        stock_cache.start_background_update(interval=60)
        logger.info("股票缓存后台更新已启动")

    return _screener


def register_screener_routes(app, check_auth_config_fn=None):
    """注册智能选股相关路由"""

    from src.api.analyze_routes import create_require_auth

    if check_auth_config_fn:
        require_auth = create_require_auth(check_auth_config_fn)
    else:
        def require_auth(f):
            return f

    # ========== 智能选股接口 ==========

    @app.route('/api/screener', methods=['POST'])
    @require_auth
    def smart_screener():
        """真实扫盘接口。

        当前扫描范围为自选股 + 持仓股，使用腾讯真实行情；没有数据时返回空列表，不降级 mock。
        """
        try:
            import json as _json
            import threading
            from src.data.base import infer_market
            from src.data.tencent import TencentSource
            from src.storage.watchlist_repo import WatchlistRepository
            from src.storage.patrol_repo import PatrolRepository

            data = request.json or {}
            strategy = (data.get('strategy') or 'ALL').upper()
            limit = min(int(data.get('limit', 20)), 100)
            sort_by = data.get('sort_by')
            asc = bool(data.get('asc', False))

            rows = {}
            for row in WatchlistRepository().get_all():
                if row.get('code'):
                    rows[row['code']] = row.get('name') or row['code']
            for row in PatrolRepository().get_all_sorted():
                if row.get('code'):
                    rows[row['code']] = row.get('name') or row['code']

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
                    'volume_ratio': None,
                    'north_flow': None,
                    'themes': [],
                })

            if strategy == 'TOP_GAIN':
                result = [r for r in result if (r.get('change_pct') or 0) > 0]
                sort_by = sort_by or 'change_pct'
                asc = False
            elif strategy == 'TOP_LOSS':
                result = [r for r in result if (r.get('change_pct') or 0) < 0]
                sort_by = sort_by or 'change_pct'
                asc = True
            elif strategy == 'VOLUME':
                sort_by = sort_by or 'volume'
                asc = False
            elif strategy in ('NORTH', 'HOT'):
                # 暂无真实北向/题材数据源；返回真实行情池并按涨跌幅排序。
                sort_by = sort_by or 'change_pct'
                asc = False
            elif strategy == 'BOTTLENECK':
                # 铲子股卡位：独立算法（走全市场 + 知识库）
                from src.core.bottleneck_strategy import screen as bottleneck_screen
                bn = bottleneck_screen(
                    top_sectors=int(data.get('top_sectors', 6)),
                    pe_min=float(data.get('pe_min', 0)),
                    pe_max=float(data.get('pe_max', 50)),
                    min_market_cap_yi=float(data.get('min_mc', 0)),
                    max_market_cap_yi=float(data.get('max_mc', 300)),
                    min_turnover=float(data.get('min_turnover', 1.0)),
                    limit=limit,
                )
                return jsonify({
                    'success': True,
                    'source': 'real:akshare-spot+ths-industry',
                    'strategy': 'BOTTLENECK',
                    'data': bn.get('candidates', []),
                    'meta': {
                        'top_sectors': bn.get('top_sectors', []),
                        'scanned': bn.get('scanned', 0),
                        'sector_summary': bn.get('sector_summary', {}),
                        'candidates_count': len(bn.get('candidates', [])),
                    },
                })

            if sort_by:
                result.sort(key=lambda r: (r.get(sort_by) is None, r.get(sort_by) or 0), reverse=not asc)
            else:
                result.sort(key=lambda r: r.get('change_pct') or 0, reverse=True)
            result = result[:limit]

            def _save_async():
                try:
                    from src.storage.sqlite_db import get_connection
                    codes = [r.get('code') for r in result if r.get('code')]
                    if not codes:
                        return
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute(
                        "INSERT INTO scanner_snapshots (label, strategy, params, codes) VALUES (?, ?, ?, ?)",
                        (strategy, strategy, _json.dumps(data, ensure_ascii=False), _json.dumps(codes, ensure_ascii=False)),
                    )
                    conn.commit()
                    snap_id = cur.lastrowid
                    conn.close()
                    logger.info(f"选股快照 #{snap_id} 已保存 ({len(codes)} 只)")
                except Exception as e:
                    logger.warning(f"快照保存失败 (非致命): {e}")

            threading.Thread(target=_save_async, daemon=True).start()

            return jsonify({
                'success': True,
                'source': 'real:tencent-tracked',
                'data': result,
                'meta': {
                    'universe': 'watchlist+positions',
                    'total_scanned': len(rows),
                    'matched_count': len(result),
                },
                'unavailable': {
                    'north_flow': '暂无真实北向资金数据源，未展示占位数据',
                    'themes': '暂无真实题材热点数据源，未展示占位数据',
                },
            })
        except Exception as e:
            logger.error(f"智能选股失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    # ========== v1.2 选股快照与历史对比 ==========

    @app.route('/api/screener/snapshots', methods=['POST'])
    @require_auth
    def save_snapshot():
        """保存一次扫描结果为快照"""
        try:
            import json
            data = request.json or {}
            codes = data.get('codes') or []
            strategy = data.get('strategy', '')
            label = (data.get('label') or '').strip()
            params = data.get('params') or {}
            if not codes:
                return jsonify({'success': False, 'error': 'codes 为空'}), 400
            from src.storage.sqlite_db import get_connection
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO scanner_snapshots (label, strategy, params, codes) VALUES (?, ?, ?, ?)",
                (label, strategy, json.dumps(params, ensure_ascii=False), json.dumps(codes, ensure_ascii=False)),
            )
            conn.commit()
            snap_id = cur.lastrowid
            conn.close()
            return jsonify({'success': True, 'id': snap_id, 'count': len(codes)})
        except Exception as e:
            logger.exception('save_snapshot failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/screener/snapshots', methods=['GET'])
    @require_auth
    def list_snapshots():
        """列出最近的快照（每 strategy 最近 5 条）"""
        try:
            from src.storage.sqlite_db import get_connection
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("""
                SELECT id, label, strategy, params, codes, created_at
                FROM scanner_snapshots
                ORDER BY created_at DESC
                LIMIT 50
            """)
            rows = cur.fetchall()
            conn.close()
            import json
            out = []
            for r in rows:
                out.append({
                    'id': r[0],
                    'label': r[1],
                    'strategy': r[2],
                    'params': json.loads(r[3]) if r[3] else {},
                    'codes': json.loads(r[4]) if r[4] else [],
                    'count': len(json.loads(r[4])) if r[4] else 0,
                    'created_at': r[5],
                })
            return jsonify({'success': True, 'snapshots': out})
        except Exception as e:
            logger.exception('list_snapshots failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/screener/compare', methods=['GET'])
    @require_auth
    def compare_snapshots():
        """对比两个快照：A vs B → entered / exited / still_in 三个集合"""
        try:
            from src.storage.sqlite_db import get_connection
            import json
            a = request.args.get('a', type=int)
            b = request.args.get('b', type=int)
            if not a or not b:
                return jsonify({'success': False, 'error': '需要 a 和 b 两个快照 id'}), 400
            conn = get_connection()
            cur = conn.cursor()
            cur.execute("SELECT id, codes, label, strategy, created_at FROM scanner_snapshots WHERE id IN (?, ?)", (a, b))
            rows = cur.fetchall()
            conn.close()
            if len(rows) != 2:
                return jsonify({'success': False, 'error': '快照不存在'}), 404
            # 按 id 排序保证 a/b 顺序
            by_id = {r[0]: r for r in rows}
            codes_a = set(json.loads(by_id[a][1])) if by_id[a][1] else set()
            codes_b = set(json.loads(by_id[b][1])) if by_id[b][1] else set()
            return jsonify({
                'success': True,
                'a': {'id': a, 'label': by_id[a][2], 'strategy': by_id[a][3], 'created_at': by_id[a][4], 'count': len(codes_a)},
                'b': {'id': b, 'label': by_id[b][2], 'strategy': by_id[b][3], 'created_at': by_id[b][4], 'count': len(codes_b)},
                'entered': sorted(codes_b - codes_a),  # B 比 A 新增
                'exited':  sorted(codes_a - codes_b),  # A 有 B 没有
                'still_in': sorted(codes_a & codes_b),  # 都在
            })
        except Exception as e:
            logger.exception('compare_snapshots failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    logger.info("智能选股路由注册完成")
