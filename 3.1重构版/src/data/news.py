"""新闻数据源模块"""
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class NewsSource(ABC):
    """新闻数据源基类"""

    name: str = "base"
    priority: int = 100

    @abstractmethod
    def get_stock_news(self, code: str, name: str = "", sector: str = "", max_items: int = 30) -> List[Dict]:
        """获取个股相关新闻"""
        pass

    @abstractmethod
    def get_market_news(self, max_items: int = 30) -> List[Dict]:
        """获取市场热点新闻（用于大盘情绪）"""
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """健康检查"""
        pass


class EastMoneyStockNewsSource(NewsSource):
    """东方财富个股新闻数据源"""

    name = "eastmoney_stock"
    priority = 1

    def __init__(self):
        self.timeout = 15

    def get_stock_news(self, code: str, name: str = "", sector: str = "", max_items: int = 30) -> List[Dict]:
        """获取个股相关新闻（东方财富）"""
        try:
            import akshare as ak

            df = ak.stock_news_em(code)
            if df is None or df.empty:
                return []

            stock_news = []
            for _, row in df.head(max_items).iterrows():
                try:
                    news_item = {
                        'title': str(row.get('新闻标题', '')),
                        'content': str(row.get('新闻内容', ''))[:200],
                        'date': str(row.get('发布时间', datetime.now().strftime('%Y-%m-%d'))),
                        'source': str(row.get('文章来源', '东方财富')),
                        'url': str(row.get('新闻链接', '')),
                    }
                    stock_news.append(news_item)
                except Exception:
                    continue

            logger.info(f"东财个股新闻: 获取{code} {len(stock_news)} 条")
            return stock_news
        except Exception as e:
            logger.warning(f"获取东财个股新闻失败 {code}: {e}")
            return []

    def get_market_news(self, max_items: int = 30) -> List[Dict]:
        """获取市场热点新闻（东方财富暂不支持，用财联社）"""
        return []

    def health_check(self) -> bool:
        """健康检查"""
        try:
            news = self.get_stock_news('000001', max_items=1)
            return len(news) > 0
        except Exception:
            return False


class CCTVNewsSource(NewsSource):
    """央视新闻数据源（市场热点）"""

    name = "cctv"
    priority = 2

    def __init__(self):
        self.timeout = 15

    def get_stock_news(self, code: str, name: str = "", sector: str = "", max_items: int = 30) -> List[Dict]:
        """央视新闻不提供个股新闻"""
        return []

    def get_market_news(self, max_items: int = 30) -> List[Dict]:
        """获取市场热点新闻（央视新闻）"""
        try:
            import akshare as ak

            df = ak.news_cctv()
            if df is None or df.empty:
                logger.warning("央视新闻数据为空")
                return []

            hot_news = []
            for _, row in df.head(max_items).iterrows():
                try:
                    news_item = {
                        'title': str(row.get('title', '')),
                        'content': str(row.get('content', ''))[:200],
                        'date': str(row.get('date', datetime.now().strftime('%Y-%m-%d'))),
                        'source': '央视新闻',
                        'url': 'https://www.cctv.com/',
                    }
                    hot_news.append(news_item)
                except Exception:
                    continue

            logger.info(f"央视新闻: 获取市场热点 {len(hot_news)} 条")
            return hot_news
        except Exception as e:
            logger.warning(f"获取央视新闻失败: {e}")
            return []

    def health_check(self) -> bool:
        """健康检查"""
        try:
            news = self.get_market_news(max_items=1)
            return len(news) > 0
        except Exception:
            return False


class EastMoneyNewsSource(NewsSource):
    """东方财富市场新闻数据源"""

    name = "eastmoney_news"
    priority = 3

    def __init__(self):
        self.timeout = 15

    def get_stock_news(self, code: str, name: str = "", sector: str = "", max_items: int = 30) -> List[Dict]:
        """获取个股相关新闻（不支持，使用东财个股新闻源）"""
        return []

    def get_market_news(self, max_items: int = 30) -> List[Dict]:
        """获取市场热点新闻"""
        try:
            import requests

            url = "https://np-listapi.eastmoney.com/comm/web/getGeneralNewsList"
            params = {
                "client": "web",
                "biz": "web.home",
                "id": f"mac_{datetime.now().strftime('%Y%m%d')}",
                "start": 0,
                "pagesize": str(max_items),
                "callback": ""
            }
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer": "https://www.eastmoney.com/"
            }

            resp = requests.get(url, params=params, headers=headers, timeout=self.timeout)
            data = resp.json()

            news_list = data.get("data", {}).get("list", [])
            hot_news = []

            for item in news_list[:max_items]:
                news_item = {
                    'title': item.get('title', ''),
                    'content': item.get('digest', ''),
                    'date': datetime.fromtimestamp(item.get('ctime', 0)).strftime('%Y-%m-%d') if item.get('ctime') else datetime.now().strftime('%Y-%m-%d'),
                    'source': '东方财富',
                    'url': item.get('url', ''),
                }
                hot_news.append(news_item)

            logger.info(f"东财市场: 获取热点 {len(hot_news)} 条")
            return hot_news
        except Exception as e:
            logger.warning(f"获取东财市场新闻失败: {e}")
            return []

    def health_check(self) -> bool:
        """健康检查"""
        try:
            news = self.get_market_news(max_items=1)
            return len(news) > 0
        except Exception:
            return False


class NewsAggregator:
    """新闻聚合器，管理多个新闻源"""

    def __init__(self):
        self.sources: List[NewsSource] = [
            EastMoneyStockNewsSource(),  # 个股新闻优先
            CCTVNewsSource(),            # 央视新闻补充市场热点
            EastMoneyNewsSource(),        # 市场热点兜底
        ]

    def get_stock_news(self, code: str, name: str = "", sector: str = "", max_items: int = 30) -> List[Dict]:
        """获取个股相关新闻（合并去重）"""
        all_news = []
        seen_titles = set()

        for source in self.sources:
            if not hasattr(source, 'get_stock_news') or source.name == 'eastmoney_news':
                continue
            try:
                news = source.get_stock_news(code, name, sector, max_items)
                for item in news:
                    title_key = item.get('title', '')[:50]
                    if title_key not in seen_titles:
                        seen_titles.add(title_key)
                        all_news.append(item)
            except Exception as e:
                logger.warning(f"从{source.name}获取个股新闻失败: {e}")
                continue

        # 按日期排序
        all_news.sort(key=lambda x: x.get('date', ''), reverse=True)
        return all_news[:max_items]

    def get_market_news(self, max_items: int = 50) -> List[Dict]:
        """获取市场热点新闻"""
        all_news = []
        seen_titles = set()

        for source in self.sources:
            if not hasattr(source, 'get_market_news'):
                continue
            try:
                news = source.get_market_news(max_items)
                for item in news:
                    title_key = item.get('title', '')[:50]
                    if title_key not in seen_titles:
                        seen_titles.add(title_key)
                        all_news.append(item)
            except Exception as e:
                logger.warning(f"从{source.name}获取市场新闻失败: {e}")
                continue

        all_news.sort(key=lambda x: x.get('date', ''), reverse=True)
        return all_news

    def health_check(self) -> Dict[str, bool]:
        """检查所有源的健康状态"""
        results = {}
        for source in self.sources:
            try:
                results[source.name] = source.health_check()
            except Exception:
                results[source.name] = False
        return results