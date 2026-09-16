"""Token-bucket rate limits for corpus network calls."""

from __future__ import annotations

import threading
import time


class TokenBucket:
    def __init__(self, min_interval_s: float) -> None:
        self.min_interval_s = min_interval_s
        self._lock = threading.Lock()
        self._last = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self.min_interval_s - (now - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()


PROFILE_HTML = TokenBucket(6.0)
LISTING = TokenBucket(30.0)
BROWSER_DISCOVERY = TokenBucket(4.5)
