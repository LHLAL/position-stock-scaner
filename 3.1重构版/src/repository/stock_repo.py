"""股票业务仓库 —— 统一对外接口，组合 data + storage"""
from __future__ import annotations
import logging
import threading
import pandas as pd
from typing import Optional, List, Dict
from datetime import datetime

from src.data.registry import registry
from src.storage.stock_basic_repo import StockBasicRepo, StockBasic, stock_basic_repo
from src.storage.stock_kline_repo import KLineRepo, kline_repo

logger = logging.getLogger(__name__)


class StockRepository:
    """股票业务仓库（单例）—— core 层调这里就够了

    设计要点：
    - get_basic:  SQLite 优先（启动同步一次），未命中才走 data 层
    - get_quote:  内存行情（StockCache）→ 降级 registry
    - get_history: SQLite K 线（按 days 查）→ miss 走 akshare + 写回
    - get_financial: 内存 TTM 缓存（7 天 TTL）→ miss 走 akshare
    """

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
        self.basic_repo: StockBasicRepo = stock_basic_repo
        self.kline_repo: KLineRepo = kline_repo
        # v1.3: 统一 TTL 缓存：Dict[(namespace, key), (value, fetched_at)]
        self._ttl_store: Dict[tuple, tuple] = {}
        self._ttl_days_cfg = {
            'fin': 7, 'industry': 1, 'problem': 1,
        }
        self._ttl_seconds_cfg = {
            'sector_trend': 30 * 60,  # 30 分钟
        }

    # ── 基础信息 ─────────────────────────────────
    def get_basic(self, code: str) -> Optional[StockBasic]:
        b = self.basic_repo.get(code)
        if b is not None:
            return b
        # miss: 走 data 层兜底（罕见：仅在 stock_basics 还没初始化时）
        try:
            market = 'SH' if code.startswith('6') else 'SZ'
            quote = registry.get_quote(code, market)
            if quote and quote.name:
                basic = StockBasic(code=code, name=quote.name, market=market)
                self.basic_repo.upsert_many([basic])
                return basic
        except Exception as e:
            logger.debug(f"get_basic 兜底失败 {code}: {e}")
        return None

    def get_name(self, code: str) -> str:
        b = self.get_basic(code)
        return b.name if b else code

    def get_names(self, codes: List[str]) -> Dict[str, str]:
        """批量取名（扫盘时一次查 N 只）"""
        result = self.basic_repo.get_names_batch(codes)
        miss = [c for c in codes if c not in result]
        if miss:
            try:
                quotes = registry.get_batch_quotes_v2(miss)
                to_upsert = []
                for c, q in quotes.items():
                    if q and q.name:
                        result[c] = q.name
                        market = 'SH' if c.startswith('6') else 'SZ'
                        to_upsert.append(StockBasic(code=c, name=q.name, market=market))
                if to_upsert:
                    self.basic_repo.upsert_many(to_upsert)
            except Exception as e:
                logger.debug(f"批量兜底取名失败: {e}")
        return result

    # ── 实时行情（走内存 StockCache）─────────────
    def get_quote(self, code: str, market: str = 'SH'):
        try:
            from src.core.stock_cache import stock_cache
            info = stock_cache.get_stock(code)
            if info and info.is_valid():
                return info
        except Exception:
            pass
        # 兜底
        return registry.get_quote(code, market)

    def get_quote_extended(self, code: str, market: str = 'SH') -> Optional[Dict]:
        """扩展行情（PE/PB/换手率等）—— 走 TencentSource.get_quote_extended"""
        try:
            from src.data.tencent import TencentSource
            return TencentSource().get_quote_extended(code, market)
        except Exception as e:
            logger.debug(f"get_quote_extended 失败 {code}: {e}")
            return None

    # ── K 线（Cache-Aside）──────────────────────
    def get_history(self, code: str, days: int = 60) -> Optional[pd.DataFrame]:
        df = self.kline_repo.get(code, days)
        # 本地数据够用就直接返回：小周期(1D/5D)有5条就行，大周期至少20条
        if df is not None and len(df) >= min(days, 20):
            return df
        df = self._fetch_history_from_data(code, days)
        if df is not None and not df.empty:
            self.kline_repo.upsert(code, df)
        return df

    def _fetch_history_from_data(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """从 data 层拉 K 线（走腾讯，不再调 akshare/东财）"""
        from src.data.tencent_kline import fetch_daily_kline
        market = 'SH' if str(code).startswith('6') or str(code).startswith('9') else 'SZ'
        return fetch_daily_kline(code, market=market, datalen=max(days + 30, 250))

    def get_weekly_kline(self, code: str, weeks: int = 60) -> Optional[pd.DataFrame]:
        """周 K 线（SQLite 优先，miss 走腾讯 + 回写）"""
        from src.storage.stock_weekly_repo import weekly_kline_repo
        df = weekly_kline_repo.get(code, weeks)
        if df is not None and len(df) >= min(weeks // 2, 15):
            return df
        from src.data.tencent_kline import fetch_weekly_kline
        market = 'SH' if str(code).startswith('6') or str(code).startswith('9') else 'SZ'
        df = fetch_weekly_kline(code, market=market, datalen=max(weeks, 60))
        if df is not None and not df.empty:
            weekly_kline_repo.upsert(code, df)
        return df

    def get_minute_kline(self, code: str, market: str = "SH", period: str = "5") -> Optional[pd.DataFrame]:
        """分钟 K 线"""
        from src.data.tencent_kline import fetch_minute_kline
        return fetch_minute_kline(code, market=market, period=period, datalen=240)

    # ── 财务数据（TTL 缓存）─────────────────────
    def get_financial(self, code: str) -> Optional[pd.DataFrame]:
        from src.data.akshare import AkShareSource
        def _load(_: str):
            try:
                import os
                for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
                    os.environ.pop(k, None)
                os.environ['no_proxy'] = '*'
                import akshare as ak
                return ak.stock_financial_abstract(symbol=code)
            except Exception as e:
                logger.warning(f"拉财务摘要失败 {code}: {e}")
                return None
        return self._ttl_cache('fin2', code, _load)

    # ── 启动同步（一次性）───────────────────────
    def bootstrap(self):
        """启动时同步全市场基础信息到 SQLite（含 industry 行业归属）"""
        try:
            import akshare as ak
            df = ak.stock_info_a_code_name()
            if df is None or df.empty:
                logger.warning("akshare.stock_info_a_code_name 返回空")
                return
            stocks = []
            for _, row in df.iterrows():
                code = str(row.get('code', '')).strip()
                name = str(row.get('name', '')).strip()
                if not (code and name):
                    continue
                market = 'SH' if code.startswith('6') else 'SZ'
                # v1.3: 同步 industry 行业归属（铲子股算法依赖）
                industry = str(row.get('industry', '') or '').strip()
                stocks.append(StockBasic(code=code, name=name, industry=industry, market=market))
            n = self.basic_repo.upsert_many(stocks)
            logger.info(f"stock_basics bootstrap 写入 {n} 只（含 industry）")
        except Exception as e:
            logger.warning(f"stock_basics 启动同步失败: {e}")

    # ── 铲子股辅助：批量取行业归属 ─────────────────
    def get_industries_batch(self, codes: List[str]) -> Dict[str, str]:
        """批量取行业归属（避免 N 次查询）"""
        if not codes:
            return {}
        out = {}
        # 优先从 SQLite 拿
        try:
            from src.storage.stock_basic_repo import stock_basic_repo
            for code in codes:
                b = stock_basic_repo.get(code)
                if b and b.industry:
                    out[code] = b.industry
        except Exception as e:
            logger.debug(f"get_industries_batch sqlite miss: {e}")
        return out

    # ── 通用 TTL 缓存（v1.3 简化：4 段重复 → 1 个工具）──
    def _ttl_cache(self, namespace: str, key: str, loader):
        """统一 TTL 缓存：自动从 _ttl_days_cfg / _ttl_seconds_cfg 读 TTL

        用法: value = self._ttl_cache('industry', code, get_industry_and_concept)
        """
        if not key:
            return None
        full_key = (namespace, key)
        cached = self._ttl_store.get(full_key)
        now = datetime.now()
        if cached:
            val, ts = cached
            ttl_days = self._ttl_days_cfg.get(namespace)
            ttl_seconds = self._ttl_seconds_cfg.get(namespace)
            if ttl_days is not None and (now - ts).days < ttl_days:
                return val
            if ttl_seconds is not None and (now - ts).total_seconds() < ttl_seconds:
                return val
        val = loader(key)
        self._ttl_store[full_key] = (val, now)
        return val

    # ── 行业/板块（TTL 缓存）───────────────────
    def get_industry(self, code: str) -> Dict:
        from src.data.industry import get_industry_and_concept
        return self._ttl_cache('industry', code, get_industry_and_concept) or {'industry': [], 'concept': []}

    def get_sector_trend(self, sector_name: str) -> float:
        from src.data.industry import get_sector_3d_trend
        return self._ttl_cache('sector_trend', sector_name, get_sector_3d_trend) or 0

    # ── 问题股检查（TTL 缓存）─────────────────
    def is_problem_stock(self, code: str, name: str) -> Tuple[bool, Optional[str]]:
        from src.data.company_info import quick_problem_check, cninfo_problem_check
        def _check(_: str):
            quick = quick_problem_check(name)
            if quick:
                return (True, quick)
            cninfo = cninfo_problem_check(code)
            return (bool(cninfo), cninfo)
        return self._ttl_cache('problem', code, _check) or (False, None)

    # ── 全市场快照（兜底：仅 cache miss 时用）────
    def get_all_quotes(self) -> List[Dict]:
        """全市场股票 + 实时行情（akshare 兜底，~5000 只）

        这是 `data` 层的最后一搏：先 stock_cache，再 akshare 全市场。
        core 层不直接 import akshare。
        """
        try:
            from src.core.stock_cache import stock_cache
            cached = stock_cache.get_stocks_by_price_range(limit=5000)
            valid = [s for s in cached if s.is_valid()]
            if len(valid) > 100:
                return [{
                    'code': s.code, 'name': s.name,
                    'price': s.price, 'change_pct': s.change_pct,
                    'volume': s.volume,
                } for s in valid]
        except Exception:
            pass

        # 兜底：akshare 全市场
        try:
            import os
            for k in ('HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy'):
                os.environ.pop(k, None)
            os.environ['no_proxy'] = '*'
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            if df is not None and not df.empty:
                return [{
                    'code': str(row.get('代码', '')).strip(),
                    'name': str(row.get('名称', '')).strip(),
                    'price': float(row.get('最新价', 0) or 0),
                    'change_pct': float(row.get('涨跌幅', 0) or 0),
                    'volume': int(float(row.get('成交量', 0) or 0)),
                } for _, row in df.iterrows()
                    if str(row.get('代码', '')).strip() and float(row.get('最新价', 0) or 0) > 0]
        except Exception as e:
            logger.warning(f"全市场快照兜底失败: {e}")
        return []

    # ── core 层代理方法（避免 core 直接 import data/）────
    def get_news_aggregator(self):
        """返回 NewsAggregator 实例（_calculate_sentiment 用）"""
        from src.data.news import NewsAggregator
        return NewsAggregator()

    def fetch_stock_sector(self, code: str) -> str:
        from src.data.market_sentiment import fetch_stock_sector
        return fetch_stock_sector(code)

    def build_market_overview(self) -> dict:
        from src.data.market_sentiment import build_market_overview
        return build_market_overview()

    def get_fund_flow_minute(self, code: str) -> list:
        from src.data.eastmoney_http import fund_flow_minute
        return fund_flow_minute(code)

    def get_news_bundle(self, code: str, name: str = "", sector: str = "") -> dict:
        from src.data.news_sources import build_stock_news_bundle
        return build_stock_news_bundle(code, name, sector)

    def get_patrol_repo(self):
        from src.storage.patrol_repo import PatrolRepository
        return PatrolRepository()

    def infer_market(self, code: str) -> str:
        return 'SH' if str(code).startswith(('6', '9')) else 'SZ'

    def get_batch_quotes(self, codes: List[str]) -> Dict[str, Any]:
        from src.data.registry import registry
        return registry.get_batch_quotes_v2(codes)

    def get_ths_source(self):
        from src.data.ths import THSSource
        return THSSource()

    def get_baidu_source(self):
        from src.data.baidu import BaiduSource
        return BaiduSource()

    def get_eastmoney_source(self):
        from src.data.eastmoney import EastMoneySource
        return EastMoneySource()

    def fetch_cls_telegraph(self, page_size: int = 30, last_time: int = 0) -> list:
        from src.data.news_sources import fetch_cls_telegraph
        return fetch_cls_telegraph(page_size, last_time)

    def get_stock_basic_repo(self):
        from src.storage.stock_basic_repo import stock_basic_repo
        return stock_basic_repo

    def get_tencent_source(self):
        from src.data.tencent import TencentSource
        return TencentSource()

    def get_sqlite_connection(self):
        from src.storage.sqlite_db import get_connection
        return get_connection()


# 全局单例
stock_repo = StockRepository()
