"""市场信号路由模块

包含：/api/hotstocks, /api/concept_blocks, /api/fund_flow, /api/industry,
      /api/northbound, /api/dragon_tiger, /api/lockup_expiry, /api/research_reports
"""
from datetime import datetime
import logging

from flask import request, jsonify

logger = logging.getLogger(__name__)


def register_signal_routes(app, check_auth_config_fn=None):
    """注册市场信号相关路由

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

    # ========== 市场信号接口 ==========

    @app.route('/api/hotstocks', methods=['GET'])
    @require_auth
    def get_hot_stocks():
        """获取今日热点股票"""
        try:
            from src.core.signals import SignalsGenerator

            gen = SignalsGenerator()
            date = request.args.get('date')
            df = gen.get_hot_stocks(date)

            if df is not None and not df.empty:
                data = df.to_dict('records') if hasattr(df, 'to_dict') else []
            else:
                data = []

            return jsonify({'success': True, 'data': data})
        except Exception as e:
            logger.error(f"获取热点股票失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/concept_blocks', methods=['POST'])
    @require_auth
    def get_concept_blocks():
        """获取股票概念板块"""
        try:
            from src.core.signals import SignalsGenerator

            data = request.json
            stock_code = data.get('stock_code', '').strip()

            if not stock_code:
                return jsonify({'success': False, 'error': '股票代码不能为空'}), 400

            gen = SignalsGenerator()
            blocks = gen.get_concept_blocks(stock_code)

            return jsonify({'success': True, 'data': blocks})
        except Exception as e:
            logger.error(f"获取概念板块失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/fund_flow', methods=['POST'])
    @require_auth
    def get_fund_flow():
        """获取资金流向"""
        try:
            from src.core.signals import SignalsGenerator

            data = request.json
            stock_code = data.get('stock_code', '').strip()
            date = data.get('date')

            if not stock_code:
                return jsonify({'success': False, 'error': '股票代码不能为空'}), 400

            if not date:
                date = datetime.now().strftime('%Y%m%d')

            gen = SignalsGenerator()
            flow = gen.get_fund_flow(stock_code, date)

            return jsonify({'success': True, 'data': flow, 'count': len(flow) if flow else 0})
        except Exception as e:
            logger.error(f"获取资金流向失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/industry', methods=['GET'])
    @require_auth
    def get_industry_comparison():
        """全行业涨跌幅排名"""
        try:
            from src.core.signals import SignalsGenerator

            top_n = request.args.get('top_n', 20, type=int)

            gen = SignalsGenerator()
            df = gen.get_industry_comparison(top_n)

            if df is not None and not df.empty:
                data = df.to_dict('records') if hasattr(df, 'to_dict') else []
            else:
                data = []

            return jsonify({'success': True, 'data': data})
        except Exception as e:
            logger.error(f"获取行业对比失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/northbound', methods=['GET'])
    @require_auth
    def get_northbound():
        """沪深股通北向资金实时"""
        try:
            from src.core.signals import SignalsGenerator

            gen = SignalsGenerator()
            data = gen.get_northbound()

            return jsonify({'success': True, 'data': data})
        except Exception as e:
            logger.error(f"获取北向资金失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/dragon_tiger', methods=['POST'])
    @require_auth
    def get_dragon_tiger():
        """龙虎榜席位"""
        try:
            from src.core.signals import SignalsGenerator

            data = request.json
            stock_code = data.get('stock_code', '').strip()
            date = data.get('date')
            look_back = int(data.get('look_back', 30))

            if not stock_code:
                return jsonify({'success': False, 'error': '股票代码不能为空'}), 400

            gen = SignalsGenerator()

            dragon_data = gen.get_dragon_tiger(stock_code, date, look_back)

            return jsonify({'success': True, 'data': dragon_data})
        except Exception as e:
            logger.error(f"获取龙虎榜失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/lockup_expiry', methods=['GET'])
    @require_auth
    def get_lockup_expiry():
        """限售解禁日历"""
        try:
            from src.core.signals import SignalsGenerator

            stock_code = request.args.get('stock_code', '').strip()
            date = request.args.get('date')
            forward_days = request.args.get('forward_days', 90, type=int)

            if not stock_code:
                return jsonify({'success': False, 'error': '股票代码不能为空'}), 400

            gen = SignalsGenerator()
            data = gen.get_lockup_expiry(stock_code=stock_code, forward_days=forward_days)

            return jsonify({'success': True, 'data': data})
        except Exception as e:
            logger.error(f"获取限售解禁失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/signals/today_prediction', methods=['GET'])
    @require_auth
    def today_prediction():
        """今日预测：国际股市 + 政策法规 + 财联社近12小时新闻。"""
        try:
            from src.core.today_prediction import build_today_prediction
            return jsonify({'success': True, 'data': build_today_prediction()})
        except Exception as e:
            logger.exception('today_prediction failed')
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/research_reports', methods=['POST'])
    @require_auth
    def get_research_reports():
        """研报列表"""
        try:
            from src.core.signals import SignalsGenerator

            data = request.json
            stock_code = data.get('stock_code', '').strip()
            max_pages = int(data.get('max_pages', 3))

            if not stock_code:
                return jsonify({'success': False, 'error': '股票代码不能为空'}), 400

            gen = SignalsGenerator()
            reports = gen.get_research_reports(stock_code, max_pages)

            return jsonify({'success': True, 'data': reports})
        except Exception as e:
            logger.error(f"获取研报失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    logger.info("市场信号路由注册完成")