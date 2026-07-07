"""数据源模块"""
from .base import DataSource, Quote
from .registry import DataSourceRegistry, registry
from .news import (
    NewsAggregator, NewsSource,
    EastMoneyStockNewsSource,  # 东方财富个股新闻
    CCTVNewsSource,            # 央视新闻
    EastMoneyNewsSource,        # 东方财富市场新闻
)

__all__ = [
    'DataSource', 'Quote', 'DataSourceRegistry', 'registry',
    'NewsAggregator', 'NewsSource',
    'EastMoneyStockNewsSource', 'CCTVNewsSource', 'EastMoneyNewsSource'
]