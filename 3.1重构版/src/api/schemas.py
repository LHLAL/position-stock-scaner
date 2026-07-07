# -*- coding: utf-8 -*-
"""
API Request/Response Schemas
请求/响应数据模型定义
"""

import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import numpy as np

# =============================================================================
# Request Schemas
# =============================================================================


class AnalyzeRequest:
    """单股票分析请求"""

    def __init__(
        self,
        stock_code: str,
        client_id: Optional[str] = None,
        market: Optional[str] = None,
        enable_streaming: bool = False,
        position_cost: Optional[float] = None,
    ):
        self.stock_code = stock_code
        self.client_id = client_id
        self.market = market
        self.enable_streaming = enable_streaming
        self.position_cost = position_cost

    @classmethod
    def from_dict(cls, data: Dict) -> "AnalyzeRequest":
        """从字典创建请求对象"""
        return cls(
            stock_code=data.get("stock_code", "").strip(),
            client_id=data.get("client_id"),
            market=data.get("market"),
            enable_streaming=data.get("enable_streaming", False),
            position_cost=parse_position_cost(data.get("position_cost")),
        )

    def validate(self) -> tuple[bool, Optional[str]]:
        """验证请求，返回 (是否有效, 错误信息)"""
        if not self.stock_code:
            return False, "股票代码不能为空"
        return True, None


class PositionRequest:
    """持仓请求（用于组合管理）"""

    def __init__(
        self,
        code: str,
        shares: float,
        cost_price: float,
        market: str = "SH",
        project: str = "",
    ):
        self.code = code
        self.shares = shares
        self.cost_price = cost_price
        self.market = market
        self.project = project

    @classmethod
    def from_dict(cls, data: Dict) -> "PositionRequest":
        """从字典创建请求对象"""
        return cls(
            code=data.get("code", "").strip(),
            shares=float(data.get("shares", 0)),
            cost_price=float(data.get("cost_price", 0)),
            market=data.get("market", "SH"),
            project=data.get("project", ""),
        )

    def validate(self) -> tuple[bool, Optional[str]]:
        """验证请求，返回 (是否有效, 错误信息)"""
        if not self.code:
            return False, "股票代码不能为空"
        if self.shares < 0:
            return False, "持仓数量不能为负"
        if self.cost_price < 0:
            return False, "成本价不能为负"
        return True, None


class FullscanRequest:
    """全盘扫描请求"""

    def __init__(
        self,
        client_id: str,
        market_filter: str = "all",
        min_score: float = 85.0,
    ):
        self.client_id = client_id
        self.market_filter = market_filter
        self.min_score = min_score

    @classmethod
    def from_dict(cls, data: Dict) -> "FullscanRequest":
        """从字典创建请求对象"""
        return cls(
            client_id=data.get("client_id"),
            market_filter=data.get("market_filter", "all"),
            min_score=float(data.get("min_score", 85)),
        )

    def validate(self) -> tuple[bool, Optional[str]]:
        """验证请求，返回 (是否有效, 错误信息)"""
        if not self.client_id:
            return False, "缺少客户端ID"
        return True, None


# =============================================================================
# Response Schemas
# =============================================================================


class ErrorResponse:
    """错误响应"""

    def __init__(self, error: str, code: str = "ERROR"):
        self.error = error
        self.code = code

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "error": self.error,
            "code": self.code,
        }

    @classmethod
    def from_exception(cls, e: Exception, code: str = "INTERNAL_ERROR") -> "ErrorResponse":
        """从异常创建错误响应"""
        return cls(error=str(e), code=code)


class SuccessResponse:
    """通用成功响应"""

    def __init__(
        self,
        data: Any = None,
        message: str = None,
        **extra,
    ):
        self.success = True
        self.data = data
        self.message = message
        self._extra = extra

    def to_dict(self) -> Dict:
        """转换为字典"""
        result = {"success": True}
        if self.data is not None:
            result["data"] = self.data
        if self.message is not None:
            result["message"] = self.message
        result.update(self._extra)
        return serialize_response(result)


class AnalysisScores:
    """分析评分结构"""

    def __init__(
        self,
        technical_score: float = 0.0,
        fundamental_score: float = 0.0,
        sentiment_score: float = 0.0,
        comprehensive_score: float = 0.0,
    ):
        self.technical_score = technical_score
        self.fundamental_score = fundamental_score
        self.sentiment_score = sentiment_score
        self.comprehensive_score = comprehensive_score

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            "technical_score": self.technical_score,
            "fundamental_score": self.fundamental_score,
            "sentiment_score": self.sentiment_score,
            "comprehensive_score": self.comprehensive_score,
        }


class AnalysisResponse:
    """股票分析完整响应"""

    def __init__(
        self,
        code: str,
        name: str = "",
        timestamp: str = None,
        quote: Dict = None,
        technical: Dict = None,
        fundamental: Dict = None,
        sentiment: Dict = None,
        scores: AnalysisScores = None,
        recommendation: str = "",
        reason: str = "",
    ):
        self.code = code
        self.name = name
        self.timestamp = timestamp or datetime.now().isoformat()
        self.quote = quote or {}
        self.technical = technical or {}
        self.fundamental = fundamental or {}
        self.sentiment = sentiment or {}
        self.scores = scores or AnalysisScores()
        self.recommendation = recommendation
        self.reason = reason

    def to_dict(self) -> Dict:
        """转换为字典"""
        return serialize_response({
            "code": self.code,
            "name": self.name,
            "timestamp": self.timestamp,
            "quote": self.quote,
            "technical": self.technical,
            "fundamental": self.fundamental,
            "sentiment": self.sentiment,
            "scores": self.scores.to_dict() if isinstance(self.scores, AnalysisScores) else self.scores,
            "recommendation": self.recommendation,
            "reason": self.reason,
        })


# =============================================================================
# Helper Functions
# =============================================================================


def parse_position_cost(raw_value: Any) -> Optional[float]:
    """解析可选持仓成本，返回float或None"""
    if raw_value is None:
        return None
    text = str(raw_value).strip().replace(",", "")
    if not text:
        return None
    try:
        value = float(text)
        if value <= 0 or math.isnan(value) or math.isinf(value):
            return None
        return value
    except Exception:
        return None


def validate_request(schema_class: type, data: Dict) -> tuple[bool, Union[Any, "ErrorResponse"]]:
    """
    验证请求数据

    Args:
        schema_class: 请求schema类
        data: 请求数据字典

    Returns:
        (验证通过, schema实例) 或 (验证失败, ErrorResponse)
    """
    try:
        request_obj = schema_class.from_dict(data)
        is_valid, error_msg = request_obj.validate()
        if not is_valid:
            return False, ErrorResponse(error=error_msg, code="VALIDATION_ERROR")
        return True, request_obj
    except Exception as e:
        return False, ErrorResponse.from_exception(e)


def serialize_response(data: Any) -> Any:
    """
    序列化响应数据，处理NaN、Infinity、日期等无效值

    Args:
        data: 任意数据

    Returns:
        清理后的可序列化数据
    """
    if isinstance(data, dict):
        return {key: serialize_response(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [serialize_response(item) for item in data]
    elif isinstance(data, tuple):
        return [serialize_response(item) for item in data]
    elif isinstance(data, (int, float)):
        if math.isnan(data):
            return None
        elif math.isinf(data):
            return None
        return data
    elif isinstance(data, np.ndarray):
        return serialize_response(data.tolist())
    elif isinstance(data, (np.integer, np.floating)):
        if np.isnan(data):
            return None
        elif np.isinf(data):
            return None
        return data.item()
    elif isinstance(data, datetime):
        return data.isoformat()
    elif isinstance(data, (bytes, bytearray)):
        try:
            return data.decode("utf-8")
        except Exception:
            return str(data)
    elif isinstance(data, (str, bool, type(None))):
        return data
    else:
        try:
            # 尝试JSON序列化检查
            import json
            json.dumps(data)
            return data
        except (TypeError, ValueError):
            return str(data)


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    # Request schemas
    "AnalyzeRequest",
    "PositionRequest",
    "FullscanRequest",
    # Response schemas
    "ErrorResponse",
    "SuccessResponse",
    "AnalysisScores",
    "AnalysisResponse",
    # Helper functions
    "validate_request",
    "serialize_response",
    "parse_position_cost",
]