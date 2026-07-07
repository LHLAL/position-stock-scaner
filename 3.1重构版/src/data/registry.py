"""数据源注册表"""
import logging
from typing import Dict, List, Optional
from .base import DataSource, Quote

logger = logging.getLogger(__name__)


class DataSourceRegistry:
    """数据源注册表，管理多个数据源的注册和获取"""

    def __init__(self):
        self._sources: Dict[str, DataSource] = {}
        self._priorities: List[tuple] = []  # [(priority, name), ...]

    def register(self, source: DataSource) -> None:
        """
        注册数据源

        Args:
            source: DataSource实例
        """
        self._sources[source.name] = source
        self._priorities.append((source.priority, source.name))
        self._priorities.sort(key=lambda x: x[0])  # 按优先级排序

    def get_quote(self, code: str, market: str = "SH") -> Optional[Quote]:
        for priority, name in self._priorities:
            source = self._sources.get(name)
            if source is None:
                continue
            try:
                quote = source.get_quote(code, market)
                if quote is not None:
                    return quote
                logger.info("数据源 %s 未返回 %s(%s) 的报价", name, code, market)
            except Exception as e:
                logger.warning("数据源 %s 获取 %s(%s) 失败: %s", name, code, market, e)
        return None

    def get_batch_quotes(self, codes: List[str], market: str = "SH") -> Dict[str, Quote]:
        """
        批量获取报价

        Args:
            codes: 股票代码列表
            market: 市场

        Returns:
            Dict[code, Quote]，失败的key对应的值为None
        """
        results = {}
        for code in codes:
            results[code] = self.get_quote(code, market)
        return results

    def get_batch_quotes_v2(self, codes: List[str], _timeout: float = 4.0) -> Dict[str, Optional[Quote]]:
        """v1.3: 真批量 —— 按 priority 升序遍历 source，优先用真批量方法。

        修复 v1.2 的 bug：旧版本用 `hasattr(get_batch_quotes_from_spot)` 判定批量能力，
        让 AkShare (priority=3) 凭"特殊方法名"抢到第一优先权，而 Tencent (priority=1)
        的 `get_batch_quotes` 被忽略。新版按 priority 升序，每个 source 用它**自己最强**
        的批量能力：
          1. `get_batch_quotes_from_spot`  ——  AkShare 风格，一次 HTTP 拉全市场
          2. `get_batch_quotes`           ——  Tencent/Yahoo 风格，按 market 分组拉 N 只
        任一 source 命中即返回；都失败/超时再回退到单只 `get_quote` 串行。

        _timeout: 单次批量/单只调用的硬上限（秒）。
        """
        if not codes:
            return {}
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
        from .base import infer_market
        _pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='batch-quote')

        def _try_snapshot(source, name: str):
            """尝试 get_batch_quotes_from_spot（AkShare 风格全市场快照）"""
            fut = _pool.submit(source.get_batch_quotes_from_spot, codes)
            res = fut.result(timeout=_timeout)
            if any(v is not None for v in res.values()):
                return res
            return None

        def _try_grouped_batch(source, name: str):
            """尝试 get_batch_quotes（按 market 分组调，因为大多数源一个 request 只支持单 market）"""
            grouped: Dict[str, List[str]] = {}
            for c in codes:
                m = infer_market(c)
                grouped.setdefault(m, []).append(c)
            merged: Dict[str, Optional[Quote]] = {}
            for m, m_codes in grouped.items():
                fut = _pool.submit(source.get_batch_quotes, m_codes, m)
                res = fut.result(timeout=_timeout)
                if res:
                    merged.update(res)
            if any(v is not None for v in merged.values()):
                return merged
            return None

        # 第一轮：按 priority 升序，每个 source 用它最强的批量能力
        for priority, name in self._priorities:
            source = self._sources.get(name)
            if source is None:
                continue
            try:
                if hasattr(source, 'get_batch_quotes_from_spot'):
                    res = _try_snapshot(source, name)
                elif hasattr(source, 'get_batch_quotes'):
                    res = _try_grouped_batch(source, name)
                else:
                    continue
                if res is not None:
                    logger.debug('批量报价命中: %s (priority=%d)', name, priority)
                    return res
            except FutureTimeout:
                logger.warning('数据源 %s 批量报价超时 %ss', name, _timeout)
            except Exception as e:
                logger.warning('数据源 %s 批量报价失败: %s', name, e)

        # 第二轮：单只 get_quote 兜底（registry.get_quote 内部已按 priority 降级）
        out: Dict[str, Optional[Quote]] = {}
        for c in codes:
            try:
                out[c] = self.get_quote(c, infer_market(c))
            except Exception as e:
                logger.debug('get_quote fallback failed for %s: %s', c, e)
                out[c] = None
        return out

    def health_check(self) -> Dict[str, bool]:
        """健康检查所有数据源"""
        return {name: src.health_check() for name, src in self._sources.items()}

    def get_source(self, name: str) -> Optional[DataSource]:
        """获取指定数据源"""
        return self._sources.get(name)

    def list_sources(self) -> List[str]:
        """列出所有已注册的数据源"""
        return [name for _, name in self._priorities]


# 全局注册表实例
registry = DataSourceRegistry()