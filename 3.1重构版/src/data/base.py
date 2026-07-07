"""数据源抽象基类和Quote数据类"""
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, List


_INFER_MARKET_RE = re.compile(r'^\d{6}$')


def infer_market(code: str) -> str:
    """根据6位A股代码推断市场（SZ: 0/3开头, SH: 6开头）。非数字代码原样返回SH。"""
    if not _INFER_MARKET_RE.match(code):
        return "SH"
    return "SZ" if code[0] in ('0', '3') else "SH"


def validate_stock_code(code: str) -> bool:
    """校验股票代码是否为合法6位数字A股代码。

    Returns:
        True 如果代码是合法A股代码（6位数字，以0/3/6开头）。
    """
    return bool(re.match(r'^(0|3|6)\d{5}$', str(code).strip()))


def sanitize_code(code: str) -> str:
    """清理并校验股票代码，非法代码返回空字符串。"""
    cleaned = str(code).strip().upper()
    # 去掉前缀（SH/SZ/SS/.SS/.SH/.SZ）
    for prefix in ['SH', 'SZ', 'SS']:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    cleaned = cleaned.split('.')[0]
    if validate_stock_code(cleaned):
        return cleaned
    return ''


@dataclass
class Quote:
    """股票报价数据类"""
    code: str           # 股票代码，如 "603000"
    name: str           # 股票名称，如 "人民网"
    price: float        # 当前价格
    change_pct: float   # 涨跌幅百分比，如 1.79 表示 1.79%
    volume: int         # 成交量
    market: str         # 市场，如 "SH", "SZ", "HK", "US"
    timestamp: str      # 数据时间戳

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "code": self.code,
            "name": self.name,
            "price": self.price,
            "change_pct": self.change_pct,
            "volume": self.volume,
            "market": self.market,
            "timestamp": self.timestamp
        }


class DataSource(ABC):
    """数据源抽象基类"""

    name: str = "base"  # 数据源名称
    priority: int = 99  # 优先级，数字越小优先级越高

    @abstractmethod
    def get_quote(self, code: str, market: str = "SH") -> Optional[Quote]:
        """
        获取单个股票报价

        Args:
            code: 股票代码，如 "603000"
            market: 市场，如 "SH", "SZ", "HK", "US"

        Returns:
            Quote对象，失败返回None
        """
        pass

    @abstractmethod
    def get_batch_quotes(self, codes: List[str], market: str = "SH") -> Dict[str, Quote]:
        """
        批量获取股票报价

        Args:
            codes: 股票代码列表
            market: 市场

        Returns:
            Dict[code, Quote]，失败的返回None
        """
        pass

    def health_check(self) -> bool:
        """健康检查"""
        try:
            test_quote = self.get_quote("603000", "SH")
            return test_quote is not None
        except Exception:
            return False