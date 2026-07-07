"""盘前/盘后复盘 API。

v1.3 修复：build_premarket_review / build_postmarket_review 都要拉财联社 + 全市场聚合，
单次响应 20-30s，前端超时拿不到数据。加 60s 进程级缓存，重复访问秒开。
"""
import logging
import threading
from datetime import datetime, timedelta

from flask import jsonify

logger = logging.getLogger(__name__)

_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 60  # 秒


def _cached(key: str, loader, ttl: int = _CACHE_TTL):
    now = datetime.now()
    with _CACHE_LOCK:
        entry = _CACHE.get(key)
        if entry and entry[1] > now:
            return entry[0]
    val = loader()
    with _CACHE_LOCK:
        _CACHE[key] = (val, now + timedelta(seconds=ttl))
        for k in list(_CACHE.keys()):
            if _CACHE[k][1] <= now:
                _CACHE.pop(k, None)
    return val


def register_review_routes(app, check_auth_config_fn=None):
    from src.api.analyze_routes import create_require_auth

    if check_auth_config_fn:
        require_auth = create_require_auth(check_auth_config_fn)
    else:
        def require_auth(f):
            return f

    @app.route('/api/review/premarket', methods=['GET'])
    @require_auth
    def premarket_review():
        try:
            def _load():
                from src.core.prepost_review import build_premarket_review
                return build_premarket_review()
            data = _cached('premarket', _load, ttl=60)
            return jsonify({'success': True, 'data': data})
        except Exception as e:
            logger.exception('premarket_review failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/review/postmarket', methods=['GET'])
    @require_auth
    def postmarket_review():
        try:
            def _load():
                from src.core.prepost_review import build_postmarket_review
                return build_postmarket_review()
            data = _cached('postmarket', _load, ttl=60)
            return jsonify({'success': True, 'data': data})
        except Exception as e:
            logger.exception('postmarket_review failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    logger.info('盘前/盘后复盘路由注册完成')