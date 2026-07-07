"""同花顺数据源"""
from __future__ import annotations
import requests
import pandas as pd
from .base import DataSource, Quote


class THSSource(DataSource):
    name = "ths"
    priority = 1

    def __init__(self):
        self.timeout = 10

    def get_quote(self, code: str, market: str = "SH") -> Quote | None:
        return None

    def get_batch_quotes(self, codes: list[str], market: str = "SH") -> dict[str, Quote | None]:
        return {code: None for code in codes}

    def get_hot_stocks(self, date: str | None = None) -> pd.DataFrame:
        from datetime import date as _date

        if date is None:
            date = _date.today().strftime("%Y-%m-%d")

        url = (
            f"http://zx.10jqka.com.cn/event/api/getharden/"
            f"date/{date}/orderby/date/orderway/desc/charset/GBK/"
        )
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "Chrome/117.0.0.0 Safari/537.36"
            )
        }

        try:
            resp = requests.get(url, headers=headers, timeout=self.timeout)
            data = resp.json()

            if data.get("errocode", 0) != 0:
                print(f"同花顺热点错误: {data.get('errormsg', '')}")
                return pd.DataFrame()

            rows = data.get("data") or []
            df = pd.DataFrame(rows)
            if df.empty:
                return df

            rename_map = {
                "name": "名称",
                "code": "代码",
                "reason": "题材归因",
                "close": "收盘价",
                "zhangdie": "涨跌额",
                "zhangfu": "涨幅%",
                "huanshou": "换手率%",
                "chengjiaoe": "成交额",
                "chengjiaoliang": "成交量",
                "ddejingliang": "大单净量",
                "market": "市场",
            }
            df = df.rename(columns=rename_map)
            return df

        except Exception as e:
            print(f"同花顺热点失败: {e}")
            return pd.DataFrame()

    def get_industry_comparison(self, top_n: int = 20) -> pd.DataFrame:
        try:
            import akshare as ak

            df = ak.stock_board_industry_summary_ths()
            return df if not df.empty else pd.DataFrame()
        except Exception as e:
            print(f"同花顺行业对比失败: {e}")
            return pd.DataFrame()