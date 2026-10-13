from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindowLimiter:
    """Per-key sliding window limiter (per process). Account lockout in the
    database provides the cross-process guarantee; this limits spraying."""

    def __init__(self, max_events: int, window_seconds: float, max_keys: int = 50_000):
        self.max_events = max_events
        self.window = window_seconds
        self.max_keys = max_keys
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._events.get(key)
            if q is None:
                if len(self._events) >= self.max_keys:
                    self._gc(now)
                q = self._events[key] = deque()
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max_events:
                return False
            q.append(now)
            return True

    def reset(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)

    def _gc(self, now: float) -> None:
        for k in [k for k, q in self._events.items() if not q or now - q[-1] > self.window]:
            del self._events[k]


login_limiter = SlidingWindowLimiter(max_events=10, window_seconds=60)
enroll_limiter = SlidingWindowLimiter(max_events=20, window_seconds=60)
