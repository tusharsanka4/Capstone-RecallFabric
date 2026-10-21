import time
from collections import defaultdict
from threading import Lock


class RateLimiter:
    def __init__(self):
        self._buckets = defaultdict(lambda: {"tokens": 0.0, "last_time": 0.0})
        self._lock = Lock()

    def check_rate_limit(self, key: str, rps: float, burst: int) -> bool:
        if rps <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets[key]
            tokens = bucket["tokens"]
            last_time = bucket["last_time"]
            if last_time == 0.0:
                tokens = float(burst)
            else:
                elapsed = now - last_time
                tokens = min(float(burst), tokens + elapsed * rps)
            if tokens < 1.0:
                bucket["tokens"] = tokens
                bucket["last_time"] = now
                return False
            bucket["tokens"] = tokens - 1.0
            bucket["last_time"] = now
            return True

    def reset(self):
        with self._lock:
            self._buckets.clear()


rate_limiter = RateLimiter()
