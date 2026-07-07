"""股票缓存模块 —— 实时行情内存缓存（v1.3 基础设施层）

设计定位：这是"基础设施缓存"，类似 data 层（直接调外部 HTTP），
不属于业务核心。core/ 其他模块应通过 stock_repo 间接访问，不要直接用。
"""
import logging
import time
import threading
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class StockInfo:
    """股票基本信息"""
    code: str
    name: str
    price: float = 0.0
    change_pct: float = 0.0
    volume: int = 0
    last_update: str = ""

    def is_valid(self) -> bool:
        """判断数据是否有效（价格在非交易时段可能为0）"""
        return self.price > 0

    def to_dict(self) -> dict:
        """转为字典，兼容 Quote.to_dict()"""
        return {
            'code': self.code,
            'name': self.name,
            'price': self.price,
            'change_pct': self.change_pct,
            'volume': self.volume,
        }


class StockCache:
    """股票缓存管理器"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        self._cache: Dict[str, StockInfo] = {}
        self._update_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._update_interval = 60  # 更新间隔秒数

        # 初始化时先加载一次
        self._initial_load()

    def _initial_load(self):
        """初始加载股票列表 —— v1.3: 优先从 SQLite 读，避免重复调 akshare"""
        import os
        for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
            os.environ.pop(key, None)
        os.environ['no_proxy'] = '*'
        os.environ['NO_PROXY'] = '*'

        # v1.3: 先查 SQLite（启动后会被 stock_repo.bootstrap 异步填充）
        try:
            from src.repository.stock_repo import stock_repo
            basic_repo = stock_repo.get_stock_basic_repo()
            codes_basic = basic_repo.count()
            if codes_basic > 100:
                conn = stock_repo.get_sqlite_connection()
                try:
                    rows = conn.execute(
                        "SELECT code, name FROM stock_basics"
                    ).fetchall()
                    for r in rows:
                        self._cache[r['code']] = StockInfo(
                            code=r['code'], name=r['name'] or ''
                        )
                    logger.info(f"从 SQLite 加载 {len(rows)} 只股票到缓存")
                    return
                finally:
                    conn.close()
        except Exception as e:
            logger.debug(f"SQLite 读股票列表失败: {e}")

        # SQLite 还没数据（bootstrap 还没完成）—— 静默等待 bootstrap
        logger.debug("stock_basics 还没就绪，等 bootstrap 线程填充")

    def update_prices(self) -> int:
        """更新所有股票价格，返回更新数量"""
        # 清除代理
        import os
        for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
            os.environ.pop(key, None)
        os.environ['no_proxy'] = '*'
        os.environ['NO_PROXY'] = '*'

        updated = 0

        # v1.3: 走 stock_repo 代理 TencentSource
        try:
            from src.repository.stock_repo import stock_repo
            ts = stock_repo.get_tencent_source()
            code_map: Dict[str, str] = {}  # 带前缀 -> 原始
            codes_with_prefix: List[str] = []

            for code in self._cache.keys():
                if code.startswith('6') or code.startswith('9'):
                    tc = f"sh{code}"
                elif code.startswith('0') or code.startswith('3'):
                    tc = f"sz{code}"
                elif code.startswith('8') or code.startswith('4'):
                    tc = f"bj{code}"
                else:
                    tc = f"sz{code}"
                codes_with_prefix.append(tc)
                code_map[tc] = code

            # 分批获取（每批 50 只）
            batch_size = 50
            for i in range(0, min(len(codes_with_prefix), 3000), batch_size):
                batch = codes_with_prefix[i:i + batch_size]
                quote_map = ts.fetch_batch_with_prefix(batch, delay=0)
                for tc, orig in code_map.items():
                    if tc not in batch:
                        continue
                    raw_code = tc.replace('sh', '').replace('sz', '').replace('bj', '')
                    q = quote_map.get(raw_code)
                    if not q:
                        continue
                    stock = self._cache.get(orig)
                    if stock:
                        stock.price = q['price']
                        stock.change_pct = q['change_pct']
                        stock.last_update = datetime.now().strftime('%H:%M:%S')
                        updated += 1
                time.sleep(0.2)  # 避免请求过快
        except Exception as e:
            logger.warning(f"更新股票价格失败: {e}")

        if updated > 0:
            logger.info(f"更新了 {updated} 只股票价格")
        return updated

    def start_background_update(self, interval: int = 60):
        """启动后台更新线程"""
        self._update_interval = interval
        if self._update_thread is None or not self._update_thread.is_alive():
            self._stop_event.clear()
            self._update_thread = threading.Thread(target=self._background_update, daemon=True)
            self._update_thread.start()
            logger.info(f"启动股票价格后台更新，间隔{interval}秒")

    def stop_background_update(self):
        """停止后台更新"""
        self._stop_event.set()
        if self._update_thread:
            self._update_thread.join(timeout=5)
            logger.info("停止股票价格后台更新")

    def _background_update(self):
        """后台更新线程"""
        while not self._stop_event.is_set():
            try:
                self.update_prices()
            except Exception as e:
                logger.warning(f"后台更新异常: {e}")

            # 等待下一次更新或停止信号
            self._stop_event.wait(self._update_interval)

    def get_stock(self, code: str) -> Optional[StockInfo]:
        """获取单个股票信息"""
        return self._cache.get(code)

    def get_stocks_by_price_range(self, min_price: float = None, max_price: float = None,
                                   change_pct_min: float = None, change_pct_max: float = None,
                                   limit: int = None) -> List[StockInfo]:
        """根据条件筛选股票"""
        results = []

        for stock in self._cache.values():
            if not stock.is_valid() and (min_price or max_price):
                continue

            # 价格筛选
            if min_price is not None and stock.price < min_price:
                continue
            if max_price is not None and stock.price > max_price:
                continue

            # 涨跌幅筛选
            if change_pct_min is not None and stock.change_pct < change_pct_min:
                continue
            if change_pct_max is not None and stock.change_pct > change_pct_max:
                continue

            results.append(stock)

        # 按价格排序
        results.sort(key=lambda x: x.price, reverse=True)

        if limit:
            results = results[:limit]

        return results

    def get_all_stocks(self) -> List[StockInfo]:
        """获取所有股票"""
        return list(self._cache.values())

    def get_cache_stats(self) -> Dict:
        """获取缓存统计信息"""
        valid_count = sum(1 for s in self._cache.values() if s.is_valid())
        return {
            'total': len(self._cache),
            'with_price': valid_count,
            'update_thread_alive': self._update_thread.is_alive() if self._update_thread else False
        }


# 全局单例
stock_cache = StockCache()