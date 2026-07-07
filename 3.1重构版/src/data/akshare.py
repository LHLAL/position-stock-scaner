"""AkShare数据源"""
import os
import time
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional, Dict, List

from .base import DataSource, Quote


# 清除代理环境变量
for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy']:
    os.environ.pop(key, None)
os.environ['no_proxy'] = '*'
os.environ['NO_PROXY'] = '*'

# A 股全量快照缓存（避免每次 quote 请求都拉全市场 ~5000 只）
_SPOT_CACHE: Optional[pd.DataFrame] = None
_SPOT_CACHE_TIME: float = 0
_SPOT_CACHE_TTL = 60  # 秒（v1.2 60s 内同一份快照复用；超过重拉）


class AkShareSource(DataSource):
    name = "akshare"
    priority = 3

    def __init__(self):
        self.timeout = 10

    def get_quote(self, code: str, market: str = "SH") -> Optional[Quote]:
        # v1.3: 仅支持 A 股（SH/SZ），港美股已停支持
        try:
            if market in ("SH", "SZ"):
                return self._get_a_share_quote(code, market)
            return None
        except Exception as e:
            print(f"[AkShare] 报价获取失败 {market}:{code} - {e}")
            return None

    def get_intraday_data(self, code: str, market: str = "SH", period: str = "5") -> Optional[pd.DataFrame]:
        """
        获取A股历史分钟K线数据
        Args:
            code: 股票代码
            market: 市场 SH/SZ
            period: "1"/"5"/"15"/"30"/"60" 分钟
        Returns:
            DataFrame: 时间,开盘,收盘,最高,最低,涨跌幅,成交量等
        """
        try:
            if market not in ("SH", "SZ"):
                return None
            # period: 1=1min, 5=5min, 15=15min, 30=30min, 60=60min
            period_map = {"1": "1", "5": "5", "15": "15", "30": "30", "60": "60"}
            p = period_map.get(period, "5")
            df = ak.stock_zh_a_hist_min_em(symbol=code, period=p, adjust="")
            if df is not None and not df.empty:
                return df
            return None
        except Exception as e:
            print(f"[AkShare] 分钟数据获取失败 {market}:{code} period={period} - {e}")
            return None

    def get_realtime_intraday(self, code: str, market: str = "SH") -> Optional[pd.DataFrame]:
        """
        获取日内分时数据（当日逐笔）

        Args:
            code: 股票代码，如 "600519"
            market: 市场，如 "SH", "SZ"

        Returns:
            DataFrame with columns: 时间, 成交价, 手数, 买卖盘性质
            失败返回 None
        """
        try:
            if market not in ("SH", "SZ"):
                return None
            df = ak.stock_intraday_em(symbol=code)
            if df is not None and not df.empty:
                return df
            return None
        except Exception as e:
            print(f"[AkShare] 日内分时获取失败 {market}:{code} - {e}")
            return None

    def _fetch_spot_snapshot(self) -> Optional[pd.DataFrame]:
        global _SPOT_CACHE, _SPOT_CACHE_TIME
        now = time.time()
        if _SPOT_CACHE is not None and (now - _SPOT_CACHE_TIME) < _SPOT_CACHE_TTL:
            return _SPOT_CACHE
        try:
            _SPOT_CACHE = ak.stock_zh_a_spot_em()
            _SPOT_CACHE_TIME = now
            return _SPOT_CACHE
        except Exception as e:
            print(f"[AkShare] 全量快照获取失败: {e}")
            return None

    def get_batch_quotes_from_spot(self, codes: List[str]) -> Dict[str, Optional[Quote]]:
        """v1.2: 一次拉全市场快照，从中挑出多只目标 code 的报价。

        内部复用 _SPOT_CACHE：60s 内同一次拉，所有 quote 都从同一份 DataFrame 找。
        """
        df = self._fetch_spot_snapshot()
        if df is None or df.empty:
            return {c: None for c in codes}
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        out: Dict[str, Optional[Quote]] = {}
        for code in codes:
            row = df[df['代码'] == code]
            if row.empty:
                out[code] = None
                continue
            r = row.iloc[0]
            try:
                out[code] = Quote(
                    code=code,
                    name=str(r.get('名称', '')),
                    price=float(r.get('最新价', 0) or 0),
                    change_pct=float(r.get('涨跌幅', 0) or 0),
                    volume=int(r.get('成交量', 0) or 0),
                    market='SH' if str(code).startswith('6') else 'SZ',
                    timestamp=ts,
                )
            except Exception as e:
                print(f"[AkShare] {code} 报价解析失败: {e}")
                out[code] = None
        return out

    def _get_a_share_quote(self, code: str, market: str) -> Optional[Quote]:
        try:
            df = self._fetch_spot_snapshot()
            if df is None:
                return None
            row = df[df['代码'] == code]
            if row.empty:
                return None

            row = row.iloc[0]
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            return Quote(
                code=code,
                name=str(row.get('名称', '')),
                price=float(row.get('最新价', 0) or 0),
                change_pct=float(row.get('涨跌幅', 0) or 0),
                volume=int(row.get('成交量', 0) or 0),
                market=market,
                timestamp=timestamp
            )
        except Exception as e:
            print(f"[AkShare] A股报价异常 {code}: {e}")
            return None

    def get_batch_quotes(self, codes: List[str], market: str = "SH") -> Dict[str, Optional[Quote]]:
        results = {}
        for code in codes:
            quote = self.get_quote(code, market)
            results[code] = quote
        return results