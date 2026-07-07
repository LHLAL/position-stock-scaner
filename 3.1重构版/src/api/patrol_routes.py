"""持仓巡检路由模块

包含：/api/patrol/*
"""
from datetime import datetime
import logging

from src.data.registry import registry
from src.data.base import infer_market
from flask import request, jsonify, Response


# ── positions quotes helpers · v1.2 ──
def _format_quotes(positions):
    """positions 列表 → {pos_id: quote dict}"""
    out = {}
    for pos in positions:
        pos_id = pos.get('id')
        if not pos_id:
            continue
        cur = pos.get('current_price') or pos.get('cost_price', 0)
        out[pos_id] = {
            'code': pos.get('code'),
            'name': pos.get('name'),
            'current_price': cur,
            'current_value': cur * pos.get('shares', 0),
            'profit_loss': pos.get('profit_loss', 0),
            'profit_loss_pct': pos.get('profit_loss_pct', 0),
            'change_pct': pos.get('change_pct', 0) or 0,
            'today_profit_loss': ((pos.get('change_pct', 0) or 0) / 100) * cur * pos.get('shares', 0),
        }
    return out


def pm_get_all_positions_fallback():
    """negative cache 命中时：直接走成本价占位（不调 akshare）"""
    from src.core.patrol import PatrolManager
    pm = PatrolManager()
    positions = pm.get_all_positions()
    for p in positions:
        p['current_price'] = p['cost_price']
        p['change_pct'] = 0
        p['profit_loss'] = 0
        p['profit_loss_pct'] = 0
    return positions


def _format_quotes_response(positions, degraded=False):
    quotes = _format_quotes(positions)
    resp = {'success': True, 'quotes': quotes}
    if degraded:
        resp['degraded'] = True
        resp['note'] = 'akshare 限流中,显示成本价 (30s 内有效)'
    return jsonify(resp)

logger = logging.getLogger(__name__)


def register_patrol_routes(app, check_auth_config_fn=None):
    """注册持仓巡检相关路由

    Args:
        app: Flask应用实例
        check_auth_config_fn: 检查鉴权配置的函数（可选）
    """

    from src.api.analyze_routes import create_require_auth

    if check_auth_config_fn:
        require_auth = create_require_auth(check_auth_config_fn)
    else:
        def require_auth(f):
            return f

    # ========== 巡检监控 API ==========

    @app.route('/api/patrol/positions', methods=['GET'])
    @require_auth
    def get_patrol_positions():
        """获取所有持仓列表"""
        try:
            from src.core.patrol import PatrolManager

            pm = PatrolManager()
            positions = pm.get_all_positions()

            return jsonify({'success': True, 'positions': positions})
        except Exception as e:
            logger.error(f"获取持仓列表失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/patrol/positions', methods=['POST'])
    @require_auth
    def create_or_update_position():
        """创建或更新持仓"""
        try:
            from src.core.patrol import PatrolManager

            data = request.json
            position_id = data.get('id')

            pm = PatrolManager()

            if position_id:
                position = pm.update_position(position_id,
                    code=data.get('stock_code'),
                    shares=data.get('position_quantity'),
                    cost_price=data.get('position_price'),
                    project=data.get('project'),
                    group_color=data.get('group_color'),
                )
            else:
                position = pm.add_position(
                    code=data.get('stock_code'),
                    shares=data.get('position_quantity', 0),
                    cost_price=data.get('position_price', 0),
                    market=data.get('market', 'SH'),
                    project=data.get('project', ''),
                    notes=data.get('notes', '')
                )

            return jsonify({'success': True, 'position': position})
        except Exception as e:
            logger.error(f"创建/更新持仓失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/patrol/positions/<int:position_id>', methods=['PUT'])
    @require_auth
    def update_position(position_id):
        """更新持仓"""
        try:
            from src.core.patrol import PatrolManager

            data = request.json
            pm = PatrolManager()

            update_data = {}
            if 'stock_code' in data:
                update_data['code'] = data['stock_code']
            if 'position_price' in data:
                update_data['cost_price'] = data['position_price']
            if 'position_quantity' in data:
                update_data['shares'] = data['position_quantity']
            if 'notes' in data:
                update_data['notes'] = data['notes']
            if 'project' in data:
                update_data['project'] = data['project']
            if 'group_color' in data:
                update_data['group_color'] = data['group_color']

            position = pm.update_position(position_id, **update_data)

            if position:
                return jsonify({'success': True, 'position': position})
            else:
                return jsonify({'success': False, 'error': '持仓不存在'}), 404

        except Exception as e:
            logger.error(f"更新持仓失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/patrol/positions/reorder', methods=['POST'])
    @require_auth
    def reorder_positions():
        """v1.2: 拖拽排序持久化
        body: {"order": [position_id, position_id, ...]}
        按列表顺序逐个写 sort_order
        """
        try:
            from src.core.patrol import PatrolManager
            data = request.json or {}
            order = data.get('order') or []
            if not isinstance(order, list):
                return jsonify({'success': False, 'error': 'order must be list'}), 400
            pm = PatrolManager()
            n = pm.reorder_positions(order)
            return jsonify({'success': True, 'updated': n})
        except Exception as e:
            logger.exception('reorder_positions failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/patrol/positions/<int:position_id>', methods=['DELETE'])
    @require_auth
    def delete_position(position_id):
        """删除持仓"""
        try:
            from src.core.patrol import PatrolManager
            pm = PatrolManager()
            success = pm.delete_position(position_id)

            if success:
                return jsonify({'success': True})
            else:
                return jsonify({'success': False, 'error': '删除失败'}), 500

        except Exception as e:
            logger.error(f"删除持仓失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/patrol/positions/quotes', methods=['GET'])
    @require_auth
    def get_patrol_positions_quotes():
        """批量获取持仓实时报价

        v1.2:
        - 走 PatrolManager.get_quotes → registry.get_batch_quotes_v2（一次拉全市场快照）
        - 5s 超时保护：akshare 卡住时回退 cost_price
        - 5s positive cache：避免前端 5s 间隔刷新反复打
        - 30s negative cache：akshare 限流时秒返 cost_price 占位
        """
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
        from src.util.ttl_cache import TTLCache
        _quotes_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='quotes')
        # 进程级 cache（reload-safe；同进程多请求共享）
        if not hasattr(app, '_quotes_cache'):
            app._quotes_cache = TTLCache(max_size=4, ttl_seconds=5)    # positive 5s
            app._quotes_neg = TTLCache(max_size=4, ttl_seconds=30)    # negative 30s

        # negative cache hit → 直接返 cost_price 占位
        if app._quotes_neg.get('positions_quotes') is not None:
            positions = pm_get_all_positions_fallback()
            return _format_quotes_response(positions, degraded=True)

        from src.core.patrol import PatrolManager
        pm = PatrolManager()

        def _fetch():
            return pm.get_quotes()

        try:
            future = _quotes_pool.submit(_fetch)
            positions = future.result(timeout=5.0)
            app._quotes_cache.set('positions_quotes', positions)
        except FutureTimeout:
            logger.warning('positions quotes 超时 5s, fallback + negative cache')
            app._quotes_neg.set('positions_quotes', True)
            positions = pm.get_all_positions()
            for p in positions:
                p['current_price'] = p['cost_price']
                p['profit_loss'] = 0
                p['profit_loss_pct'] = 0
                p['change_pct'] = 0
        except Exception as e:
            logger.error(f"获取持仓报价失败: {e}")
            app._quotes_neg.set('positions_quotes', True)
            return jsonify({'success': False, 'error': str(e)}), 500

        quotes = _format_quotes(positions)
        return jsonify({'success': True, 'quotes': quotes})

    @app.route('/api/quote/batch', methods=['GET'])
    @require_auth
    def get_quote_batch():
        """通用批量报价接口（供自选股等非持仓列表使用）

        query: codes=600519,000001,300750
        返回: { success, data: { code: { current_price, change_pct, ... } } }
        """
        from src.data.base import infer_market
        from src.data.tencent import TencentSource
        codes_param = (request.args.get('codes') or '').strip()
        codes = [c.strip() for c in codes_param.split(',') if c.strip()]
        if not codes:
            return jsonify({'success': True, 'data': {}})
        try:
            source = TencentSource()
            data = {}
            for code in codes:
                quote = source.get_quote(code, infer_market(code))
                if quote is None:
                    continue
                data[code] = {
                    'code': code,
                    'name': quote.name,
                    'current_price': quote.price,
                    'change_pct': quote.change_pct,
                    'volume': quote.volume,
                }
            return jsonify({'success': True, 'data': data})
        except Exception as e:
            logger.error(f"get_quote_batch 失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/patrol/projects', methods=['GET'])
    @require_auth
    def get_patrol_projects():
        """获取所有项目"""
        try:
            from src.storage.patrol_repo import PatrolRepository

            repo = PatrolRepository()
            positions = repo.get_all()

            projects_set = set()
            for pos in positions:
                project = pos.get('project', '')
                if project:
                    projects_set.add(project)

            projects = [{'name': p} for p in projects_set]

            return jsonify({'success': True, 'projects': projects})
        except Exception as e:
            logger.error(f"获取项目列表失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/patrol/projects', methods=['POST'])
    @require_auth
    def create_patrol_project():
        """创建项目"""
        try:
            from src.storage.patrol_repo import PatrolRepository

            data = request.json
            project_name = data.get('name', '').strip()

            if not project_name:
                return jsonify({'success': False, 'error': '项目名称不能为空'}), 400

            repo = PatrolRepository()

            existing = repo.get_by_project(project_name)
            if existing:
                return jsonify({'success': False, 'error': '项目已存在'}), 400

            repo.add(code='PROJECT_INIT', shares=0, cost_price=0, market='SH', project=project_name)

            return jsonify({'success': True, 'project': {'name': project_name}})
        except Exception as e:
            logger.error(f"创建项目失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/patrol/projects/<name>', methods=['DELETE'])
    @require_auth
    def delete_patrol_project(name):
        """删除项目"""
        try:
            from src.storage.patrol_repo import PatrolRepository

            repo = PatrolRepository()

            positions = repo.get_by_project(name)

            for pos in positions:
                repo.delete(pos['id'])

            return jsonify({'success': True})
        except Exception as e:
            logger.error(f"删除项目失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    logger.info("持仓巡检路由注册完成")

    @app.route('/api/patrol/position/<int:position_id>/analyze', methods=['GET'])
    @require_auth
    def analyze_position_sse(position_id):
        try:
            from src.core.patrol import PatrolManager
            from src.core.analyzer import StockAnalyzer
            from src.data.registry import registry
            from src.data.base import infer_market
            import json

            pm = PatrolManager()
            position = pm.get_position(position_id)

            if not position:
                return jsonify({'success': False, 'error': '持仓不存在'}), 404

            stock_code = position['code']
            position_price = float(position['cost_price'])
            position_quantity = position['shares']
            position_amount = position_price * position_quantity
            market = position.get('market', infer_market(stock_code))

            quote = registry.get_quote(stock_code, market)
            current_price = quote.price if quote else position_price
            current_value = current_price * position_quantity
            profit_loss = current_value - position_amount
            profit_loss_pct = (profit_loss / position_amount * 100) if position_amount > 0 else 0

            analyzer = StockAnalyzer()

            def generate():
                yield "event: log\ndata: {\"message\": \"正在获取持仓数据...\", \"type\": \"info\"}\n\n"
                yield "event: log\ndata: {\"message\": \"正在分析 " + stock_code + "...\", \"type\": \"info\"}\n\n"

                # 运行完整量化分析
                report = analyzer.analyze_stock(stock_code, market)
                scores = report.get('scores', {})
                score_dict = {
                    'technical': scores.get('technical_score', 0),
                    'fundamental': scores.get('fundamental_score', 0),
                    'sentiment': scores.get('sentiment_score', 0),
                    'comprehensive': scores.get('comprehensive_score', 0),
                }
                yield "event: scores_update\ndata: " + json.dumps({'scores': score_dict}) + "\n\n"

                position_status = '盈利' if profit_loss >= 0 else '亏损'
                yield "event: log\ndata: {\"message\": \"量化分析完成，开始 AI 解读...\", \"type\": \"progress\"}\n\n"

                ai_chunks = []
                def collect_chunk(chunk):
                    ai_chunks.append(chunk)

                try:
                    ai_text = analyzer.generate_ai_analysis(
                        report,
                        stream_callback=collect_chunk,
                        position_data={'cost': position_price, 'shares': position_quantity}
                    )
                    for chunk in ai_chunks:
                        yield "event: ai_stream\ndata: " + json.dumps({"chunk": chunk}) + "\n\n"
                except Exception as ai_err:
                    logger.error(f"[patrol AI] 分析失败: {ai_err}")
                    ai_text = ""

                combined_ai = ''.join(ai_chunks) or ai_text or '分析完成。'
                yield "event: log\ndata: {\"message\": \"AI分析完成\", \"type\": \"success\"}\n\n"

                result = {
                    'position_status': position_status,
                    'profit_loss': profit_loss,
                    'profit_loss_pct': profit_loss_pct,
                    'recommendation': report.get('recommendation', {}),
                    'ai_analysis': combined_ai,
                    'scores': score_dict,
                }
                yield "event: analysis_complete\ndata: " + json.dumps(result) + "\n\n"

                # 持久化分析结果（带 position_id）
                try:
                    from src.storage.patrol_repo import PatrolRepository
                    repo = PatrolRepository()
                    repo.save_analysis_result(
                        position_id=position_id,
                        code=stock_code,
                        analysis_data={
                            'ai_analysis': combined_ai,
                            'technical_score': score_dict.get('technical', 0),
                            'fundamental_score': score_dict.get('fundamental', 0),
                            'sentiment_score': score_dict.get('sentiment', 0),
                            'comprehensive_score': score_dict.get('comprehensive', 0),
                            'recommendation': report.get('recommendation', {}),
                            'recommendation_reason': report.get('reason', ''),
                            'strategy': report.get('strategy', {}),
                        }
                    )
                except Exception as save_err:
                    logger.error(f"存储持仓分析结果失败: {save_err}")

            return Response(generate(), mimetype='text/event-stream')
        except Exception as e:
            logger.error(f"分析持仓失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/patrol/position/<int:position_id>/strategy', methods=['POST', 'GET'])
    @require_auth
    def get_position_strategy(position_id):
        try:
            from src.core.patrol import PatrolManager
            from src.core.analyzer import StockAnalyzer

            pm = PatrolManager()
            position = pm.get_position(position_id)

            if not position:
                return jsonify({'success': False, 'error': '持仓不存在'}), 404

            stock_code = position['code']
            position_price = float(position['cost_price'])
            position_quantity = position['shares']
            market = position.get('market', 'SH')

            quote = registry.get_quote(stock_code, market)
            current_price = quote.price if quote else position_price
            profit_loss = (current_price - position_price) * position_quantity
            profit_loss_pct = ((current_price / position_price - 1) * 100) if position_price > 0 else 0

            analyzer = StockAnalyzer()
            signals = analyzer.calculate_signals_l0123(stock_code, market, position_price)

            strategy_text = analyzer.generate_strategy_recommendation(
                {
                    'code': stock_code,
                    'cost_price': position_price,
                    'shares': position_quantity,
                    'current_price': current_price,
                },
                signals,
                {'current_price': current_price}
            )

            # 清理 signals 中的 numpy 类型，确保 JSON 序列化
            from src.api.analyze_routes import clean_data_for_json
            cleaned_signals = clean_data_for_json(signals)

            return jsonify({
                'success': True,
                'data': {
                    'stock_code': stock_code,
                    'stock_name': analyzer.get_stock_name(stock_code),
                    'position_price': position_price,
                    'position_quantity': position_quantity,
                    'current_price': current_price,
                    'profit_loss': round(profit_loss, 2),
                    'profit_loss_pct': round(profit_loss_pct, 2),
                    'signals': cleaned_signals,
                    'strategy_text': strategy_text,
                    'generated_at': datetime.now().isoformat()
                }
            })
        except Exception as e:
            logger.error(f"策略分析失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/patrol/positions/<int:position_id>/analysis', methods=['GET'])
    @require_auth
    def get_position_analysis(position_id):
        try:
            from src.storage.patrol_repo import PatrolRepository

            repo = PatrolRepository()
            analysis = repo.get_analysis_result(position_id)

            if analysis:
                return jsonify({'success': True, 'analysis': analysis})
            else:
                return jsonify({'success': False, 'error': '暂无分析报告'}), 200
        except Exception as e:
            logger.error(f"获取分析报告失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500