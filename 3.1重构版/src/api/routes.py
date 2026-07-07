"""Flask路由模块

从原始 flask_web_server.py 迁移的所有API路由，
委托给核心层模块处理业务逻辑。

拆分说明：
- analyze_routes: 单股票分析相关路由
- signal_routes: 市场信号相关路由
- patrol_routes: 持仓巡检相关路由
- screener_routes: 扫盘相关路由
- review_routes: 盘前/盘后复盘路由
"""
import logging

logger = logging.getLogger(__name__)


def register_routes(app, get_analyzer_fn=None, check_auth_config_fn=None):
    """注册所有Flask路由

    Args:
        app: Flask应用实例
        get_analyzer_fn: 获取分析器实例的函数（可选）
        check_auth_config_fn: 检查鉴权配置的函数（可选）
    """
    from src.api.analyze_routes import register_analyze_routes
    from src.api.signal_routes import register_signal_routes
    from src.api.screener_routes import register_screener_routes
    from src.api.patrol_routes import register_patrol_routes
    from src.api.review_routes import register_review_routes
    from src.api.extra_routes import register_extra_routes

    register_analyze_routes(app, get_analyzer_fn, check_auth_config_fn)
    register_signal_routes(app, check_auth_config_fn)
    register_screener_routes(app, check_auth_config_fn)
    register_patrol_routes(app, check_auth_config_fn)
    register_review_routes(app, check_auth_config_fn)
    register_extra_routes(app, get_analyzer_fn, check_auth_config_fn)

    logger.info("所有路由注册完成")