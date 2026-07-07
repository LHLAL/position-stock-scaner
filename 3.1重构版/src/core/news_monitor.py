"""
新闻监控管理器
每5秒从财联社获取最新电报，分析是否对当前自选/持仓股票有影响，通过SSE推送通知
"""
import threading
import time
import re
import logging
from typing import Dict, List, Set, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from src.repository.stock_repo import stock_repo

logger = logging.getLogger(__name__)


@dataclass
class NewsAlert:
    """新闻提醒数据结构"""
    id: str
    title: str
    content: str
    source: str
    time: str
    url: str
    impact_type: str  # 'positive', 'negative', 'neutral'
    related_stocks: List[str]  # 关联的股票代码列表
    keywords: List[str]  # 匹配的关键词
    importance: int  # 重要程度 1-5


class NewsMonitor:
    """新闻监控器"""

    def __init__(self, sse_manager=None):
        self._sse_manager = sse_manager
        self._monitor_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._interval = 5  # 5秒轮询间隔
        self._last_ctime = 0  # 上次获取的最新新闻时间戳
        self._seen_ids: Set[str] = set()  # 已处理过的新闻ID，避免重复推送

        # 股票代码到名称的映射（用于匹配）
        self._stock_name_map: Dict[str, str] = {}

        # 行业/板块关键词映射
        self._sector_keywords: Dict[str, List[str]] = {
            'AI': ['人工智能', 'AI', '大模型', 'GPT', '算力', '芯片', '半导体', '集成电路'],
            '新能源': ['新能源', '光伏', '风电', '储能', '锂电池', '宁德时代', '比亚迪'],
            '汽车': ['汽车', '电动车', '整车', '特斯拉', '蔚来', '小鹏', '理想'],
            '医药': ['医药', '创新药', 'CRO', '疫苗', '医疗', '医院', '健康'],
            '消费': ['消费', '白酒', '食品', '饮料', '零售', '电商', '直播'],
            '地产': ['地产', '房地产', '房价', '房贷', '保利', '万科', '金地'],
            '金融': ['银行', '证券', '券商', '保险', '金融', '央行', '降息'],
            '军工': ['军工', '航天', '航空', '导弹', '国防', '军事'],
        }

        # 利好/利空关键词
        self._positive_keywords = ['大涨', '上涨', '盈利', '增长', '利好', '突破', '创新高', '超预期',
                                    '获得', '中标', '签约', '收购', '获批', '通过', '解禁', '回购', '增持']
        self._negative_keywords = ['大跌', '下跌', '亏损', '下降', '利空', '暴跌', '减持', '解禁',
                                    '立案', '调查', '处罚', '违规', '退市', '风险', '警告', '违约']

    def set_sse_manager(self, sse_manager):
        """设置SSE管理器（用于推送通知）"""
        self._sse_manager = sse_manager

    def update_stock_map(self, positions: List[Dict], watchlist: List[Dict]):
        """更新股票代码到名称的映射（用于新闻匹配）

        Args:
            positions: 持仓列表，每项包含 code, name 字段
            watchlist: 自选列表，每项包含 code, name 字段
        """
        for item in positions + watchlist:
            code = item.get('code', '')
            name = item.get('name', '')
            if code and name:
                self._stock_name_map[code] = name

    def start(self, interval: int = 5):
        """启动新闻监控线程"""
        self._interval = interval
        if self._monitor_thread is None or not self._monitor_thread.is_alive():
            self._stop_event.clear()
            self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._monitor_thread.start()
            logger.info(f"启动新闻监控，间隔{interval}秒")

    def stop(self):
        """停止新闻监控"""
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
            logger.info("停止新闻监控")

    def _monitor_loop(self):
        """监控主循环"""
        while not self._stop_event.is_set():
            try:
                self._fetch_and_analyze()
            except Exception as e:
                logger.warning(f"新闻监控异常: {e}")

            # 等待下一次轮询或停止信号
            self._stop_event.wait(self._interval)

    def _fetch_and_analyze(self):
        """获取并分析新闻"""
        try:
            # 获取最新财联社电报（增量）
            news_list = stock_repo.fetch_cls_telegraph(page_size=20, last_time=self._last_ctime)

            if not news_list:
                return

            # 更新最新时间戳
            for news in news_list:
                ctime = news.get('ctime', 0)
                if ctime > self._last_ctime:
                    self._last_ctime = ctime

            # 分析每条新闻
            for news in news_list:
                news_id = str(news.get('id', ''))
                if not news_id or news_id in self._seen_ids:
                    continue

                self._seen_ids.add(news_id)
                # 只保留最近1000条已处理ID，防止内存泄漏
                if len(self._seen_ids) > 1000:
                    self._seen_ids = set(list(self._seen_ids)[-500:])

                # 分析新闻影响
                alert = self._analyze_news_impact(news)
                if alert and alert.related_stocks:
                    # 有关联股票，推送通知
                    self._push_alert(alert)

        except Exception as e:
            logger.warning(f"获取新闻失败: {e}")

    def _analyze_news_impact(self, news: Dict) -> Optional[NewsAlert]:
        """分析新闻对持仓/自选股票的影响"""
        title = news.get('title', '') or news.get('brief', '') or ''
        content = news.get('content', '') or ''
        full_text = f"{title} {content}"

        # 匹配关联股票（股票代码或名称）
        related_stocks = []
        matched_keywords = []

        for code, name in self._stock_name_map.items():
            # 匹配股票代码或名称
            if code in full_text or name in full_text:
                related_stocks.append(code)
                matched_keywords.append(name)

        # 如果没有直接匹配的股票，尝试匹配行业关键词
        if not related_stocks:
            for sector, keywords in self._sector_keywords.items():
                for kw in keywords:
                    if kw in full_text:
                        matched_keywords.append(kw)
                        # 行业匹配不直接关联具体股票，可以后续扩展

        # 判断利好/利空
        impact_type = 'neutral'
        pos_count = sum(1 for kw in self._positive_keywords if kw in full_text)
        neg_count = sum(1 for kw in self._negative_keywords if kw in full_text)

        if pos_count > neg_count:
            impact_type = 'positive'
        elif neg_count > pos_count:
            impact_type = 'negative'

        # 计算重要程度（根据关联股票数量、关键词匹配数、新闻长度）
        importance = min(5, max(1, len(related_stocks) + len(matched_keywords) // 2 + len(full_text) // 200))

        if related_stocks or matched_keywords:
            return NewsAlert(
                id=str(news.get('id', '')),
                title=title,
                content=content[:200] + '...' if len(content) > 200 else content,
                source=news.get('source', '财联社'),
                time=news.get('date', datetime.now().strftime('%Y-%m-%d %H:%M')),
                url=news.get('url', ''),
                impact_type=impact_type,
                related_stocks=related_stocks,
                keywords=matched_keywords,
                importance=importance
            )

        return None

    def _push_alert(self, alert: NewsAlert):
        """通过SSE推送新闻提醒"""
        if self._sse_manager is None:
            return

        try:
            event_data = {
                'id': alert.id,
                'title': alert.title,
                'content': alert.content,
                'source': alert.source,
                'time': alert.time,
                'url': alert.url,
                'impact_type': alert.impact_type,
                'related_stocks': alert.related_stocks,
                'keywords': alert.keywords,
                'importance': alert.importance,
                'timestamp': datetime.now().isoformat()
            }

            # 广播给所有连接的客户端
            self._sse_manager.broadcast('news_alert', event_data)
            logger.info(f"推送新闻提醒: {alert.title} (关联股票: {', '.join(alert.related_stocks)})")

        except Exception as e:
            logger.warning(f"推送新闻提醒失败: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """获取监控统计信息"""
        return {
            'running': self._monitor_thread is not None and self._monitor_thread.is_alive(),
            'interval': self._interval,
            'last_ctime': self._last_ctime,
            'seen_count': len(self._seen_ids),
            'monitored_stocks': list(self._stock_name_map.keys())
        }


# 全局单例
_news_monitor: Optional[NewsMonitor] = None


def get_news_monitor(sse_manager=None) -> NewsMonitor:
    """获取新闻监控器单例"""
    global _news_monitor
    if _news_monitor is None:
        _news_monitor = NewsMonitor(sse_manager=sse_manager)
    return _news_monitor
