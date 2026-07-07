"""事件总线模块"""
from enum import Enum
from typing import Callable, Dict, List, Any
from collections import defaultdict


class Event(Enum):
    """事件枚举"""
    QUOTE_UPDATED = "quote_updated"           # 报价更新
    ANALYSIS_START = "analysis_start"         # 分析开始
    ANALYSIS_COMPLETE = "analysis_complete"    # 分析完成
    ANALYSIS_PROGRESS = "analysis_progress"    # 分析进度
    PATROL_ALERT = "patrol_alert"              # 持仓警报
    PATROL_UPDATED = "patrol_updated"          # 持仓更新
    SSE_CLIENT_CONNECT = "sse_client_connect"  # SSE客户端连接
    SSE_CLIENT_DISCONNECT = "sse_client_disconnect"  # SSE客户端断开
    ERROR = "error"                            # 错误事件


class EventBus:
    """事件总线单例"""
    _instance = None

    def __init__(self):
        self._subscribers: Dict[Event, List[Callable]] = defaultdict(list)

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def subscribe(self, event: Event, handler: Callable[[Any], None]) -> None:
        """
        订阅事件

        Args:
            event: 事件类型
            handler: 回调函数，接收任意参数
        """
        if handler not in self._subscribers[event]:
            self._subscribers[event].append(handler)

    def unsubscribe(self, event: Event, handler: Callable[[Any], None]) -> None:
        """
        取消订阅

        Args:
            event: 事件类型
            handler: 回调函数
        """
        if handler in self._subscribers[event]:
            self._subscribers[event].remove(handler)

    def publish(self, event: Event, data: Any = None) -> None:
        """
        发布事件

        Args:
            event: 事件类型
            data: 事件数据
        """
        for handler in self._subscribers[event]:
            try:
                handler(data)
            except Exception as e:
                print(f"事件处理错误 {event}: {e}")

    def clear(self, event: Event = None) -> None:
        """
        清除订阅

        Args:
            event: 如果为None，清除所有事件订阅
        """
        if event is None:
            self._subscribers.clear()
        else:
            self._subscribers[event].clear()


# 全局单例
event_bus = EventBus.get_instance()