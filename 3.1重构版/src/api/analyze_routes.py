"""单股票分析路由模块

包含：/api/analyze, /api/analyze_stream, /api/task_status, /api/system_info
"""
from datetime import datetime
import logging
import math
from functools import wraps
from queue import Queue, Empty
from threading import Lock

from flask import (
    request, jsonify, Response,
    redirect, url_for, session
)
import json

logger = logging.getLogger(__name__)

from concurrent.futures import ThreadPoolExecutor
_ANALYSIS_EXECUTOR = ThreadPoolExecutor(max_workers=4)

# 新闻监控器（懒加载）
_news_monitor = None

def get_news_monitor():
    """获取新闻监控器单例"""
    global _news_monitor
    if _news_monitor is None:
        from src.core.news_monitor import get_news_monitor as _get_monitor
        _news_monitor = _get_monitor(sse_manager=sse_manager)
    return _news_monitor

# SSE事件类型常量
LOG_EVENT = 'log'
PROGRESS_EVENT = 'progress'
SCORES_UPDATE_EVENT = 'scores_update'
DATA_QUALITY_EVENT = 'data_quality_update'
PARTIAL_RESULT_EVENT = 'partial_result'
FINAL_RESULT_EVENT = 'final_result'
ANALYSIS_COMPLETE_EVENT = 'analysis_complete'
ANALYSIS_ERROR_EVENT = 'analysis_error'
AI_STREAM_EVENT = 'ai_stream'
ERROR_EVENT = 'error'
HEARTBEAT_EVENT = 'heartbeat'


def clean_data_for_json(obj):
    """清理数据中的NaN、Infinity、日期等无效值"""
    import numpy as np
    import pandas as pd
    from datetime import datetime as dt, date, time

    if isinstance(obj, dict):
        return {key: clean_data_for_json(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [clean_data_for_json(item) for item in obj]
    elif isinstance(obj, tuple):
        return [clean_data_for_json(item) for item in obj]
    elif isinstance(obj, (int, float)):
        if math.isnan(obj):
            return None
        elif math.isinf(obj):
            return None
        else:
            return obj
    elif isinstance(obj, np.ndarray):
        return clean_data_for_json(obj.tolist())
    elif isinstance(obj, (np.integer, np.floating)):
        if np.isnan(obj):
            return None
        elif np.isinf(obj):
            return None
        else:
            return obj.item()
    elif isinstance(obj, (dt, date)):
        return obj.isoformat() if hasattr(obj, 'isoformat') else str(obj)
    elif isinstance(obj, time):
        return obj.isoformat()
    elif isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    elif isinstance(obj, type(pd.NaT)):
        return None
    elif pd.isna(obj):
        return None
    elif hasattr(obj, 'to_dict'):
        try:
            return clean_data_for_json(obj.to_dict())
        except Exception:
            return str(obj)
    elif hasattr(obj, 'item'):
        try:
            return clean_data_for_json(obj.item())
        except Exception:
            return str(obj)
    elif obj is None:
        return None
    elif isinstance(obj, (str, bool)):
        return obj
    else:
        try:
            json.dumps(obj)
            return obj
        except (TypeError, ValueError):
            return str(obj)




class SSEManager:
    """SSE连接管理器"""

    def __init__(self):
        self.clients = {}
        self.lock = Lock()

    def add_client(self, client_id: str, queue: Queue):
        """添加SSE客户端"""
        with self.lock:
            self.clients[client_id] = queue
            logger.info(f"SSE客户端连接: {client_id}, 当前客户端数: {len(self.clients)}, 管理器ID: {id(self)}")

    def remove_client(self, client_id: str, queue: Queue = None):
        """移除SSE客户端。

        同一个 client_id 可能因为浏览器自动重连而同时存在新旧两个生成器。
        旧生成器退出时不能删除新连接刚注册的 queue，否则后端会误判客户端不存在。
        """
        with self.lock:
            current = self.clients.get(client_id)
            if current is not None and (queue is None or current is queue):
                del self.clients[client_id]
                logger.info(f"SSE客户端断开: {client_id}, 当前客户端数: {len(self.clients)}")
            elif current is not None:
                logger.info(f"忽略旧SSE连接清理: {client_id}, 新连接仍在")

    def send_to_client(self, client_id: str, event_type: str, data):
        """向特定客户端发送消息"""
        with self.lock:
            logger.debug(f"尝试发送 {event_type} 到 {client_id}, 当前客户端: {list(self.clients.keys())}, 管理器ID: {id(self)}")
            if client_id in self.clients:
                try:
                    cleaned_data = clean_data_for_json(data)
                    message = {
                        'event': event_type,
                        'data': cleaned_data,
                        'timestamp': datetime.now().isoformat()
                    }
                    self.clients[client_id].put(message, block=False)
                    logger.debug(f"消息已放入队列: {event_type}")
                    return True
                except Exception as e:
                    logger.error(f"SSE消息发送失败: {e}")
                    return False
            logger.warning(f"客户端 {client_id} 不存在，可用客户端: {list(self.clients.keys())}")
            return False

    def broadcast(self, event_type: str, data):
        """广播消息给所有客户端"""
        with self.lock:
            cleaned_data = clean_data_for_json(data)
            message = {
                'event': event_type,
                'data': cleaned_data,
                'timestamp': datetime.now().isoformat()
            }

            dead_clients = []
            for client_id, queue in self.clients.items():
                try:
                    queue.put(message, block=False)
                except Exception as e:
                    logger.error(f"SSE广播失败给客户端 {client_id}: {e}")
                    dead_clients.append(client_id)

            for client_id in dead_clients:
                del self.clients[client_id]


# 全局SSE管理器
sse_manager = SSEManager()


class StreamingAnalyzer:
    """流式分析器"""

    stream_sequence = 0

    def __init__(self, client_id: str):
        self.client_id = client_id
        self.accumulated_ai_content = ""

    def send_log(self, message: str, log_type: str = 'info'):
        """发送日志消息"""
        sse_manager.send_to_client(self.client_id, LOG_EVENT, {
            'message': message,
            'type': log_type
        })

    def send_progress(self, element_id: str, percent: int, message: str = None, current_stock: str = None):
        """发送进度更新"""
        sse_manager.send_to_client(self.client_id, PROGRESS_EVENT, {
            'element_id': element_id,
            'percent': percent,
            'message': message,
            'current_stock': current_stock
        })

    def send_scores(self, scores: dict, animate: bool = True):
        """发送评分更新"""
        sse_manager.send_to_client(self.client_id, SCORES_UPDATE_EVENT, {
            'scores': scores,
            'animate': animate
        })

    def send_data_quality(self, data_quality: dict):
        """发送数据质量更新"""
        sse_manager.send_to_client(self.client_id, DATA_QUALITY_EVENT, data_quality)

    def send_partial_result(self, data: dict):
        """发送部分结果"""
        sse_manager.send_to_client(self.client_id, PARTIAL_RESULT_EVENT, data)

    def send_final_result(self, result: dict):
        """发送最终结果"""
        sse_manager.send_to_client(self.client_id, FINAL_RESULT_EVENT, result)

    def send_completion(self, message: str = None):
        """发送完成消息"""
        sse_manager.send_to_client(self.client_id, ANALYSIS_COMPLETE_EVENT, {
            'message': message or '分析完成'
        })

    def send_error(self, error_message: str, partial_ai_content: str = None):
        """发送错误消息"""
        sse_manager.send_to_client(self.client_id, ERROR_EVENT, {
            'error': error_message,
            'partial_ai_content': partial_ai_content
        })

    def send_ai_stream(self, content: str):
        """发送AI流式内容"""
        StreamingAnalyzer.stream_sequence += 1
        self.accumulated_ai_content += content
        success = sse_manager.send_to_client(self.client_id, AI_STREAM_EVENT, {
            'content': content,
            'sequence': StreamingAnalyzer.stream_sequence,
            'full_content': self.accumulated_ai_content
        })
        if StreamingAnalyzer.stream_sequence <= 3:  # 只打印前3个发送日志
            logger.debug(f"send_ai_stream success={success}, client_id={self.client_id}, seq={StreamingAnalyzer.stream_sequence}")
        return success


def create_require_auth(check_auth_config_fn):
    """创建鉴权装饰器工厂"""
    def require_auth(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            auth_enabled, auth_config = check_auth_config_fn()

            if not auth_enabled:
                return f(*args, **kwargs)

            if session.get('authenticated'):
                login_time = session.get('login_time')
                if login_time:
                    session_timeout = auth_config.get('session_timeout', 3600)
                    if (datetime.now() - datetime.fromisoformat(login_time)).total_seconds() < session_timeout:
                        return f(*args, **kwargs)
                    else:
                        session.pop('authenticated', None)
                        session.pop('login_time', None)

            return redirect(url_for('login'))

        return decorated_function
    return require_auth


def register_analyze_routes(app, get_analyzer_fn=None, check_auth_config_fn=None):
    """注册单股票分析相关路由

    Args:
        app: Flask应用实例
        get_analyzer_fn: 获取分析器实例的函数（可选）
        check_auth_config_fn: 检查鉴权配置的函数（可选）
    """

    _analyzer = None
    if get_analyzer_fn:
        def get_analyzer():
            global _analyzer
            if _analyzer is None:
                _analyzer = get_analyzer_fn()
            return _analyzer
    else:
        def get_analyzer():
            return _analyzer

    if check_auth_config_fn:
        require_auth = create_require_auth(check_auth_config_fn)
    else:
        def require_auth(f):
            return f

    # ========== SSE流式接口 ==========

    @app.route('/api/sse')
    def sse_stream():
        """SSE流接口"""
        client_id = request.args.get('client_id')
        if not client_id:
            return "Missing client_id", 400

        def event_stream():
            client_queue = Queue()
            sse_manager.add_client(client_id, client_queue)

            try:
                yield f"event: connected\ndata: {json.dumps({'client_id': client_id}, ensure_ascii=False)}\n\n"

                while True:
                    try:
                        message = client_queue.get(timeout=30)
                        try:
                            event_type = message.get('event', 'message')
                            event_data = message.get('data', message)
                            json_data = json.dumps(event_data, ensure_ascii=False)
                            yield f"event: {event_type}\ndata: {json_data}\n\n"
                        except (TypeError, ValueError) as e:
                            logger.error(f"SSE消息序列化失败: {e}, 消息类型: {type(message)}")
                            yield f"event: error\ndata: {json.dumps({'error': f'消息序列化失败: {str(e)}'}, ensure_ascii=False)}\n\n"

                    except Empty:
                        yield f"event: heartbeat\ndata: {json.dumps({'timestamp': datetime.now().isoformat()}, ensure_ascii=False)}\n\n"
                    except GeneratorExit:
                        break
                    except Exception as e:
                        logger.error(f"SSE流处理错误: {e}")
                        try:
                            yield f"event: error\ndata: {json.dumps({'error': f'流处理错误: {str(e)}'}, ensure_ascii=False)}\n\n"
                        except Exception:
                            pass
                        break

            except Exception as e:
                logger.error(f"SSE流错误: {e}")
            finally:
                sse_manager.remove_client(client_id, client_queue)

        # 有客户端连接时，启动新闻监控（如果尚未启动）
        try:
            nm = get_news_monitor()
            if not nm._monitor_thread or not nm._monitor_thread.is_alive():
                nm.start(interval=5)
                logger.info("有SSE客户端连接，启动新闻监控")
        except Exception as e:
            logger.warning(f"启动新闻监控失败: {e}")

        return Response(
            event_stream(),
            content_type='text/event-stream; charset=utf-8',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'Access-Control-Allow-Origin': '*',
                'X-Accel-Buffering': 'no',
            }
        )

    # ========== 单股票分析接口 ==========

    @app.route('/api/analyze_stream', methods=['POST'])
    @require_auth
    def analyze_stock_stream():
        """单只股票流式分析"""
        try:
            data = request.json
            stock_code = data.get('stock_code', '').strip()
            client_id = data.get('client_id')
            enable_streaming = data.get('enable_streaming', True)

            if not stock_code:
                return jsonify({'success': False, 'error': '股票代码不能为空'}), 400

            if not client_id:
                return jsonify({'success': False, 'error': '缺少client_id'}), 400

            if client_id not in sse_manager.clients:
                logger.warning(f"分析请求被拒绝：SSE客户端未连接 client_id={client_id}, 可用客户端={list(sse_manager.clients.keys())}")
                return jsonify({'success': False, 'error': 'SSE实时连接未建立，请等待左下角显示“SSE 实时”后重试'}), 409

            def run_analysis():
                from src.core.analyzer import StockAnalyzer

                analyzer_instance = StockAnalyzer()
                streamer = StreamingAnalyzer(client_id)

                try:
                    # 自动检测市场
                    norm_code, norm_market, display = StockAnalyzer.normalize_stock_code(stock_code)
                    market_label = {'SH': 'A股', 'SZ': 'A股'}.get(norm_market, 'A股')
                    streamer.send_log(f"开始分析股票: {display} ({market_label})", 'info')
                    streamer.send_log(f"正在获取行情数据并计算技术指标（首次分析约需 1-2 分钟）…", 'progress')

                    # 查 patrol_repo 获取真实持仓数据
                    position_data = None
                    try:
                        from src.storage.patrol_repo import PatrolRepository
                        pos = next((p for p in PatrolRepository().get_all_sorted()
                                    if str(p.get('code')) == str(norm_code)), None)
                        if pos and pos.get('cost_price') and pos.get('shares'):
                            position_data = {
                                'cost': float(pos['cost_price']),
                                'shares': float(pos['shares']),
                            }
                    except Exception:
                        pass

                    result = analyzer_instance.analyze_stock(
                        code=norm_code,
                        market=norm_market
                    )

                    streamer.send_log("市场数据获取完成", 'progress')
                    streamer.send_log("正在计算技术指标...", 'progress')

                    # 构建前端兼容的响应
                    scores_raw = result.get('scores', {})
                    price_info = result.get('price_info', {})

                    transformed = {
                        'code': norm_code,
                        'name': result.get('name', norm_code),
                        'market': norm_market,
                        'timestamp': result.get('timestamp', ''),
                        'quote': result.get('quote', {}),
                        'scores': {
                            'technical_score': scores_raw.get('technical_score', 0),
                            'fundamental_score': scores_raw.get('fundamental_score', 0),
                            'sentiment_score': scores_raw.get('sentiment_score', 0),
                            'comprehensive_score': scores_raw.get('comprehensive_score', 0),
                        },
                        'technical': result.get('technical', {}),
                        'fundamental': result.get('fundamental', {}),
                        'sentiment': result.get('sentiment', {}),
                        'chanlun': result.get('chanlun', {}),
                        'signals': result.get('signals', []),
                        'recommendation': {
                            'action': result.get('recommendation', ''),
                            'reason': result.get('reason', ''),
                        },
                        'strategy': result.get('strategy', {}),
                    }

                    streamer.send_scores(transformed['scores'])

                    # 推送快速解读（规则生成，0 额外延迟 — analyze_stock 已完成）
                    strategy = transformed.get('strategy', {})
                    streamer.send_partial_result({
                        'recommendation': transformed['recommendation'],
                        'decision': strategy.get('decision', {}),
                        'current_advice': strategy.get('current_advice', {}),
                        'target_and_stop': strategy.get('target_and_stop', {}),
                        'batch_operation': strategy.get('batch_operation', ''),
                        'cycles': strategy.get('cycles', {}),
                        'market_state': strategy.get('market_state', ''),
                        'chanlun': transformed.get('chanlun', {}),
                        'signals': (transformed.get('signals') or [])[:5],
                        'price_info': transformed.get('price_info', {}),
                        'scores': transformed.get('scores', {}),
                    })

                    streamer.send_log("技术分析完成，开始 AI 解读...", 'progress')

                    # v1.5: AI 调用前检查客户端是否还在线
                    if client_id not in sse_manager.clients:
                        logger.warning(f"[AI] 客户端 {client_id} 已断开，取消 AI 分析")
                        streamer.send_log("客户端已断开，分析终止", 'warning')
                        return

                    # AI分析（支持SSE流式输出）
                    try:
                        logger.info(f"开始AI分析，client_id={client_id}")
                        ai_parts = []
                        chunk_count = [0]  # 使用列表以便在闭包中修改

                        def on_ai_chunk(chunk):
                            ai_parts.append(chunk)
                            chunk_count[0] += 1
                            if chunk_count[0] == 1:
                                logger.info(f"AI流开始，收到第一个chunk")
                            elif chunk_count[0] % 50 == 0:  # 每50个chunk报告一次进度
                                logger.info(f"AI流式输出进行中，已收到 {chunk_count[0]} 个chunks，总长度 {len(''.join(ai_parts))}")
                            streamer.send_ai_stream(chunk)

                        streamer.send_log("正在生成 AI 深度分析报告...", 'progress')
                        ai_text = analyzer_instance.generate_ai_analysis(
                            result,
                            stream_callback=on_ai_chunk,
                            position_data=position_data
                        )
                        logger.info(f"AI分析完成，共收到 {chunk_count[0]} 个 chunks，总长度 {len(ai_text)}")
                        if ai_text:
                            transformed['ai_analysis'] = ''.join(ai_parts) or ai_text
                            streamer.send_log("AI分析完成", 'success')
                    except Exception as ai_err:
                        logger.error(f"[AI] 分析失败: {ai_err}", exc_info=True)
                        streamer.send_log(f"AI分析失败: {str(ai_err)}", 'error')
                        transformed['ai_analysis'] = f"## AI 分析失败\n\n错误：{str(ai_err)[:200]}\n\n请检查 config.json 中 model_preference / api_key / api_base_url 是否正确。"
                    
                    cleaned = clean_data_for_json(transformed)
                    streamer.send_final_result(cleaned)
                    streamer.send_completion("分析完成")

                except Exception as e:
                    logger.error(f"流式分析失败: {e}", exc_info=True)
                    streamer.send_error(str(e))

            _ANALYSIS_EXECUTOR.submit(run_analysis)

            return jsonify({'success': True, 'message': '分析已启动'})

        except Exception as e:
            logger.error(f"分析请求失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/analyze', methods=['POST'])
    @require_auth
    def analyze_stock():
        """单只股票分析 - 兼容接口（非流式）"""
        try:
            data = request.json
            stock_code = data.get('stock_code', '').strip()
            enable_streaming = data.get('enable_streaming', False)

            if not stock_code:
                return jsonify({'success': False, 'error': '股票代码不能为空'}), 400

            from src.core.analyzer import StockAnalyzer
            analyzer_instance = StockAnalyzer()

            # Normalize stock code to detect market
            norm_code, norm_market, _ = StockAnalyzer.normalize_stock_code(stock_code)

            # 查 patrol_repo 获取真实持仓数据
            position_data = None
            try:
                from src.storage.patrol_repo import PatrolRepository
                pos = next((p for p in PatrolRepository().get_all_sorted()
                            if str(p.get('code')) == str(norm_code)), None)
                if pos and pos.get('cost_price') and pos.get('shares'):
                    position_data = {
                        'cost': float(pos['cost_price']),
                        'shares': float(pos['shares']),
                    }
            except Exception:
                pass

            report = analyzer_instance.analyze_stock(
                code=norm_code,
                market=norm_market
            )

            # 非流式端点也生成 AI 报告
            try:
                ai_text = analyzer_instance.generate_ai_analysis(report, position_data=position_data)
                if ai_text:
                    report['ai_analysis'] = ai_text
            except Exception as ai_err:
                logger.warning(f"非流式 AI 分析失败（不阻塞主流程）: {ai_err}")

            cleaned_report = clean_data_for_json(report)

            return jsonify({
                'success': True,
                'data': cleaned_report,
                'message': f'股票 {stock_code} 分析完成'
            })

        except Exception as e:
            logger.error(f"股票分析失败: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/task_status/<stock_code>', methods=['GET'])
    @require_auth
    def get_task_status(stock_code):
        """获取任务状态"""
        return jsonify({
            'success': True,
            'status': 'completed',
            'stock_code': stock_code,
            'message': '同步分析模式，无任务状态追踪'
        })

    @app.route('/api/system_info', methods=['GET'])
    @require_auth
    def get_system_info():
        """获取系统信息"""
        try:
            auth_enabled, auth_config = check_auth_config_fn() if check_auth_config_fn else (False, {})

            return jsonify({
                'success': True,
                'data': {
                    'version': '3.1',
                    'sse_support': True,
                    'auth_enabled': auth_enabled,
                    'timestamp': datetime.now().isoformat()
                }
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    # ========== 新闻监控相关接口 ==========

    @app.route('/api/news/monitor_status', methods=['GET'])
    @require_auth
    def get_news_monitor_status():
        """获取新闻监控状态"""
        try:
            nm = get_news_monitor()
            return jsonify({
                'success': True,
                'data': nm.get_stats()
            })
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/news/update_monitored_stocks', methods=['POST'])
    @require_auth
    def update_monitored_stocks():
        """更新要监控的股票列表

        请求体:
        {
            "positions": [{"code": "000001", "name": "平安银行"}, ...],
            "watchlist": [{"code": "600000", "name": "浦发银行"}, ...]
        }
        """
        try:
            data = request.get_json() or {}
            positions = data.get('positions', [])
            watchlist = data.get('watchlist', [])

            nm = get_news_monitor()
            nm.update_stock_map(positions, watchlist)

            return jsonify({
                'success': True,
                'message': f'已更新监控股票列表，共 {len(nm._stock_name_map)} 只股票'
            })
        except Exception as e:
            logger.error(f'更新监控股票失败: {e}')
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/news/test_alert', methods=['POST'])
    @require_auth
    def test_news_alert():
        """测试新闻提醒推送（调试用）"""
        try:
            data = request.get_json() or {}
            from src.core.news_monitor import NewsAlert
            from datetime import datetime

            alert = NewsAlert(
                id=f'test_{int(datetime.now().timestamp())}',
                title=data.get('title', '测试新闻提醒'),
                content=data.get('content', '这是一条测试新闻提醒内容'),
                source='财联社',
                time=datetime.now().strftime('%Y-%m-%d %H:%M'),
                url=data.get('url', 'https://www.cls.cn'),
                impact_type=data.get('impact_type', 'positive'),
                related_stocks=data.get('related_stocks', ['000001', '600000']),
                keywords=['测试', '利好'],
                importance=3
            )

            nm = get_news_monitor()
            nm._push_alert(alert)

            return jsonify({
                'success': True,
                'message': '测试提醒已推送'
            })
        except Exception as e:
            logger.error(f'测试新闻提醒失败: {e}')
            return jsonify({'success': False, 'error': str(e)}), 500

    logger.info("单股票分析路由注册完成")