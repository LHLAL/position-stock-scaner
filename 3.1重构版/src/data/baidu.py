"""百度股市通数据源"""
import requests
from typing import Optional, Dict, List
from typing import Any

from .base import DataSource, Quote


_BAIDU_PAE_HEADERS = {
    "Host": "finance.pae.baidu.com",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://gushitong.baidu.com",
    "Referer": "https://gushitong.baidu.com/",
}


class BaiduSource(DataSource):
    """百度股市通数据源 - 专注于概念板块和资金流向"""

    name = "baidu"
    priority = 1

    def __init__(self):
        self.timeout = 10

    def get_quote(self, code: str, market: str = "SH") -> Optional[Quote]:
        """百度主要用于概念和资金流，暂不实现报价"""
        return None

    def get_batch_quotes(self, codes: List[str], market: str = "SH") -> Dict[str, Quote]:
        return {code: None for code in codes}

    def get_concept_blocks(self, code: str) -> Dict:
        """
        获取股票概念板块归属（行业/概念/地域三维分类）

        Args:
            code: 股票代码，如 "600519" 或 "688017"

        Returns:
            dict: {
                "industry": [{"name": str, "change_pct": str, "desc": str}, ...],
                "concept": [{"name": str, "change_pct": str, "desc": str}, ...],
                "region": [{"name": str, "change_pct": str, "desc": str}, ...],
                "concept_tags": [str, ...]  # 仅概念名称列表
            }
        """
        url = (
            f"https://finance.pae.baidu.com/api/getrelatedblock"
            f"?code={code}&market=ab&typeCode=all&finClientType=pc"
        )
        try:
            resp = requests.get(url, headers=_BAIDU_PAE_HEADERS, timeout=self.timeout)
            # 百度有时返回非UTF-8编码，尝试处理
            resp.encoding = resp.apparent_encoding or 'utf-8'
            data = resp.json()

            if str(data.get("ResultCode", -1)) != "0":
                print(f"百度概念板块API错误 {code}: ResultCode={data.get('ResultCode')}")
                return {"industry": [], "concept": [], "region": [], "concept_tags": []}

            result = {"industry": [], "concept": [], "region": [], "concept_tags": []}
            for block in data.get("Result", []):
                block_type = block.get("type", "")
                for item in block.get("list", []):
                    entry = {
                        "name": item.get("name", ""),
                        "change_pct": item.get("increase", ""),
                        "desc": item.get("desc", ""),
                    }
                    if "行业" in block_type:
                        result["industry"].append(entry)
                    elif "概念" in block_type:
                        result["concept"].append(entry)
                        result["concept_tags"].append(entry["name"])
                    elif "地域" in block_type:
                        result["region"].append(entry)
            return result
        except Exception as e:
            print(f"百度概念板块失败 {code}: {e}")
            return {"industry": [], "concept": [], "region": [], "concept_tags": []}

    def get_fund_flow(self, code: str, date: str = None) -> Dict:
        """
        获取资金流向数据

        Args:
            code: 股票代码，如 "000858"
            date: 日期，YYYYMMDD格式（如 "20260512"），默认当日

        Returns:
            dict: {
                "realtime": [{time, mainForce, retail, super, large, price}, ...],
                "history": [{date, close, change_pct, superNetIn, largeNetIn, mediumNetIn, littleNetIn, mainIn}, ...]
            }
        """
        result = {"realtime": [], "history": []}

        # 获取实时分钟级资金流向
        if date:
            result["realtime"] = self._get_fund_flow_realtime(code, date)

        # 获取20日历史资金流向
        result["history"] = self._get_fund_flow_history(code, days=20)

        return result

    def _get_fund_flow_realtime(self, code: str, date: str) -> List[Dict]:
        """
        获取实时分钟级资金流向

        Args:
            code: 股票代码
            date: YYYYMMDD紧凑格式

        Returns:
            list: [{time, mainForce, retail, super, large, price}, ...]
        """
        url = (
            f"https://finance.pae.baidu.com/vapi/v1/fundflow"
            f"?code={code}&market=ab&date={date}&finClientType=pc"
        )
        try:
            resp = requests.get(url, headers=_BAIDU_PAE_HEADERS, timeout=self.timeout)
            resp.encoding = resp.apparent_encoding or 'utf-8'
            data = resp.json()

            if str(data.get("ResultCode", -1)) != "0":
                return []

            raw = data.get("Result", {}).get("update_data", "")
            if not raw:
                return []

            rows = []
            for segment in raw.split(";"):
                parts = segment.split(",")
                if len(parts) >= 9:
                    rows.append({
                        "time": parts[0],
                        "mainForce": float(parts[2]) if parts[2] else 0,
                        "retail": float(parts[3]) if parts[3] else 0,
                        "super": float(parts[4]) if parts[4] else 0,
                        "large": float(parts[5]) if parts[5] else 0,
                        "price": float(parts[8]) if parts[8] else 0,
                    })
            return rows
        except Exception as e:
            print(f"百度实时资金流向失败 {code}: {e}")
            return []

    def _get_fund_flow_history(self, code: str, days: int = 20) -> List[Dict]:
        """
        获取历史日级资金流向

        Args:
            code: 股票代码
            days: 最近N交易日，默认20

        Returns:
            list: [{date, close, change_pct, superNetIn, largeNetIn, mediumNetIn, littleNetIn, mainIn}, ...]
        """
        url = (
            f"https://finance.pae.baidu.com/vapi/v1/fundsortlist"
            f"?code={code}&market=ab&pn=0&rn={days}&finClientType=pc"
        )
        try:
            resp = requests.get(url, headers=_BAIDU_PAE_HEADERS, timeout=self.timeout)
            resp.encoding = resp.apparent_encoding or 'utf-8'
            data = resp.json()

            if str(data.get("ResultCode", -1)) != "0":
                return []

            rows = []
            for item in data.get("Result", {}).get("list", []):
                rows.append({
                    "date": item.get("showtime", ""),
                    "close": item.get("closepx", ""),
                    "change_pct": item.get("ratio", ""),
                    "superNetIn": item.get("superNetIn", ""),
                    "largeNetIn": item.get("largeNetIn", ""),
                    "mediumNetIn": item.get("mediumNetIn", ""),
                    "littleNetIn": item.get("littleNetIn", ""),
                    "mainIn": item.get("extMainIn", ""),
                })
            return rows
        except Exception as e:
            print(f"百度历史资金流向失败 {code}: {e}")
            return []