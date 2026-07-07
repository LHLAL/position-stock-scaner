"""HTTP 请求重试工具

为外部 API 调用提供指数退避重试能力。
"""
import logging
import time
from functools import wraps
from typing import Callable, Optional, Type, Tuple

logger = logging.getLogger(__name__)


def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable] = None,
):
    """指数退避重试装饰器

    Args:
        max_attempts: 最大重试次数（含首次）
        base_delay: 首次重试等待秒数
        max_delay: 最大等待秒数
        backoff: 退避倍数
        exceptions: 可重试的异常类型
        on_retry: 每次重试前的回调，签名 fn(attempt, exception)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exc = e
                    if attempt < max_attempts:
                        delay = min(base_delay * (backoff ** (attempt - 1)), max_delay)
                        logger.warning(
                            f"{func.__name__} 第 {attempt}/{max_attempts} 次失败: {e}，"
                            f"{delay:.1f}s 后重试"
                        )
                        if on_retry:
                            on_retry(attempt, e)
                        time.sleep(delay)
            raise last_exc
        return wrapper
    return decorator
