"""轻量 TTL LRU 缓存 · v1.2 · 2026-06-14

用法：
    cache = TTLCache(max_size=64, ttl_seconds=300)
    cache.set('600519', {'scores': ...})
    cache.get('600519')  # 自动按 ttl 判定是否过期

特性：
- 线程安全 + 简单 LRU 驱逐（dict 顺序就是 LRU 序，访问时移到尾）
- single-flight：同 key 并发请求共享同一份计算（避免 thundering herd）
  get_or_compute(key, fn) —— fn 只在第一个请求里执行，其余 await 同一结果
"""
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Optional, Tuple


class TTLCache:
    def __init__(self, max_size: int = 64, ttl_seconds: int = 300):
        self.max_size = max_size
        self.ttl = ttl_seconds
        self._d: "OrderedDict[Any, Tuple[float, Any]]" = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        # single-flight: {key: Event + value}
        self._inflight: "OrderedDict[Any, Tuple[threading.Event, Any, Exception | None]]" = OrderedDict()
        self._inflight_lock = threading.Lock()

    def get(self, key: Any) -> Optional[Any]:
        now = time.time()
        with self._lock:
            v = self._d.get(key)
            if v is None:
                self.misses += 1
                return None
            ts, data = v
            if now - ts > self.ttl:
                self._d.pop(key, None)
                self.misses += 1
                return None
            # hit → 移到尾
            self._d.move_to_end(key)
            self.hits += 1
            return data

    def set(self, key: Any, value: Any) -> None:
        now = time.time()
        with self._lock:
            if key in self._d:
                self._d.move_to_end(key)
            self._d[key] = (now, value)
            # LRU 驱逐
            while len(self._d) > self.max_size:
                self._d.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()
            self.hits = self.misses = 0

    def stats(self) -> dict:
        with self._lock:
            return {
                'size': len(self._d),
                'max_size': self.max_size,
                'ttl': self.ttl,
                'hits': self.hits,
                'misses': self.misses,
            }

    def get_or_compute(self, key: Any, compute: Callable[[], Any], timeout: float = 30.0) -> Tuple[bool, Any]:
        """single-flight 版的 get：miss 时只有一个线程跑 compute，其余 await 同一结果。

        返回 (cache_hit, value)：
          - cache_hit=True：直接命中（外层已有或本层 get 命中）→ 不跑 compute
          - cache_hit=False：本线程跑了 compute 写入 cache
        compute 抛异常时所有等待者都抛同一异常。
        """
        # 1) 缓存命中直接返回
        v = self.get(key)
        if v is not None:
            return (True, v)

        # 2) 已经有别的线程在算这个 key，await 它
        ev = None
        first = False
        with self._inflight_lock:
            if key in self._inflight:
                ev, _, _ = self._inflight[key]
            else:
                ev = threading.Event()
                self._inflight[key] = (ev, None, None)
                first = True

        if not first:
            # 等别人算完
            ev.wait(timeout=timeout)
            with self._inflight_lock:
                _, val, err = self._inflight.get(key, (None, None, None))
            if err is not None:
                raise err
            if val is not None:
                return (True, val)
            # 超时 / 没结果 → 当作 miss 自己重算
            v = self.get(key)
            if v is not None:
                return (True, v)
            # 走下面的 compute 路径
            first = True
            ev = threading.Event()
            with self._inflight_lock:
                self._inflight[key] = (ev, None, None)

        # 3) 第一个线程：跑 compute，写回 inflight + cache
        try:
            val = compute()
            with self._inflight_lock:
                self._inflight[key] = (ev, val, None)
            self.set(key, val)
            return (False, val)
        except Exception as e:
            with self._inflight_lock:
                self._inflight[key] = (ev, None, e)
            raise
        finally:
            ev.set()
            # 延迟清 inflight：让其他 waiter 醒来后能"从 inflight 拿到值"而不是看到空就再算
            # （cache 已写，理论上 get() 也能命中，但线程竞争窗口里新请求可能走到
            #   "inflight 空 + cache 还没写"的状态。保险起见用 Event + 短延迟即可。）
            def _cleanup():
                time.sleep(0.05)
                with self._inflight_lock:
                    self._inflight.pop(key, None)
            threading.Thread(target=_cleanup, daemon=True).start()
