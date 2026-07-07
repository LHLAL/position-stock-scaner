"""Flask应用入口点"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, jsonify, render_template
from src.api.routes import register_routes
from src.storage.sqlite_db import init_db


def main():
    _base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    app = Flask(__name__,
                template_folder=os.path.join(_base, 'templates'),
                static_folder=os.path.join(_base, 'static'),
                static_url_path='/static')
    init_db()

    # v1.3: 启动后异步 bootstrap 全市场基础信息到 SQLite（不阻塞启动）
    def _bootstrap_basics():
        try:
            from src.repository.stock_repo import stock_repo
            stock_repo.bootstrap()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f'stock_basics bootstrap 失败: {e}')

    import threading
    _bootstrap_thread = threading.Thread(target=_bootstrap_basics, daemon=True, name='bootstrap-basics')
    _bootstrap_thread.start()

    from src.data.registry import registry
    from src.data.akshare import AkShareSource
    from src.data.tencent import TencentSource
    from src.data.eastmoney import EastMoneySource
    from src.data.ths import THSSource
    # v1.3: 只保留 A 股数据源，港美股不再支持
    registry.register(AkShareSource())
    registry.register(TencentSource())
    registry.register(EastMoneySource())
    registry.register(THSSource())

    # v1.2: lazy analyzer singleton — 只在 indicators 等真实路径首次被调用时构造
    _analyzer = {'instance': None}

    # 启动 StockCache 后台行情刷新（全市场报价缓存，每分钟更新一次）
    try:
        from src.core.stock_cache import stock_cache
        stock_cache.start_background_update(interval=60)
    except Exception:
        pass
    def get_analyzer():
        if _analyzer['instance'] is None:
            try:
                from src.core.analyzer import StockAnalyzer
                _analyzer['instance'] = StockAnalyzer(registry=registry)
            except Exception as e:
                import logging
                logging.getLogger(__name__).exception(f'StockAnalyzer 初始化失败: {e}')
                return None
        return _analyzer['instance']

    register_routes(app, get_analyzer_fn=get_analyzer)

    # ── 后台预热缓存（并行） ──
    def _start_cache_warmup():
        """启动时后台并行预热持仓股的指标和图表缓存"""
        import threading, logging as _lg
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _warm_one(code):
            import requests as _req
            try:
                _req.get(f'http://127.0.0.1:5000/api/indicators/{code}', timeout=600)
                _req.get(f'http://127.0.0.1:5000/api/indicators/{code}/signals', timeout=600)
                _req.get(f'http://127.0.0.1:5000/api/chart/{code}?type=kline&period=1M', timeout=600)
                _req.get(f'http://127.0.0.1:5000/api/backtest/{code}', timeout=600)
                return code, True
            except Exception as e:
                return code, False

        def _warm_all():
            try:
                from src.storage.patrol_repo import PatrolRepository
                codes = [p['code'] for p in PatrolRepository().get_all_sorted() if p.get('code')]
                if not codes:
                    return
                _lg.getLogger(__name__).info(f"缓存预热: {len(codes)} 只股票（并行 {len(codes)} 线程）")
                with ThreadPoolExecutor(max_workers=len(codes)) as pool:
                    futures = {pool.submit(_warm_one, c): c for c in codes}
                    for f in as_completed(futures):
                        c, ok = f.result()
                        if ok:
                            _lg.getLogger(__name__).info(f"缓存预热完成: {c}")
                _lg.getLogger(__name__).info("缓存预热全部完成")
            except Exception as e:
                _lg.getLogger(__name__).warning(f"缓存预热异常: {e}")

        threading.Thread(target=_warm_all, daemon=True).start()
    _start_cache_warmup()

    @app.route('/api/status')
    def status():
        model_label = 'gpt-4o'
        try:
            import json as _json, os as _os
            for _p in [_os.path.join(_os.path.dirname(__file__), '..', 'config.json'),
                       _os.path.join(_os.getcwd(), 'config.json')]:
                if _os.path.exists(_p):
                    with open(_p) as _f:
                        _cfg = _json.load(_f)
                    _ai = _cfg.get('ai', {})
                    _pref = _ai.get('model_preference', '')
                    _model = _ai.get('models', {}).get(_pref, '')
                    if _pref and _model:
                        model_label = f'{_pref}:{_model}'
                    break
        except Exception:
            pass
        return jsonify({'success': True, 'status': 'ready', 'model': model_label})

    @app.errorhandler(404)
    def not_found(_e):
        """API 路径 404 返回 JSON，避免被 SPA 模板吞掉"""
        from flask import request
        if request.path.startswith('/api/'):
            return jsonify({'success': False, 'error': f'endpoint not found: {request.path}'}), 404
        return render_template('index.html'), 404

    @app.route('/')
    @app.route('/v2')
    @app.route('/scan')
    @app.route('/patrol')
    @app.route('/signals')
    def index(path=None):
        """SPA: 4 个页面入口都返回 index.html（hash 路由在客户端处理）"""
        return render_template('index.html')

    host = os.environ.get('STOCK_SCANNER_HOST', '0.0.0.0')
    port = int(os.environ.get('STOCK_SCANNER_PORT', '5000'))
    debug = os.environ.get('STOCK_SCANNER_DEBUG', '').lower() in ('1', 'true', 'yes')
    print(f"[startup] Stock Scanner 3.1 -> http://{host}:{port}  (debug={debug})")
    app.run(host=host, port=port, threaded=True, debug=debug, use_reloader=False)


if __name__ == '__main__':
    main()
