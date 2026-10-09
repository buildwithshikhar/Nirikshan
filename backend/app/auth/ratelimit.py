"""Login throttling.

Two independent limits (documented in docs/security/auth.md):
- per client address, in memory: at most ADDR_MAX_FAILURES failed logins in a sliding window of
  ADDR_WINDOW_S seconds, then 429 until the oldest failure leaves the window. The table holds at
  most ADDR_MAX_TRACKED addresses (least recently failed evicted first), so memory is bounded.
  It is per process and resets on restart.
- per account, in the database (users.failed_logins / locked_until): USER_MAX_FAILURES consecutive
  failures lock the account for USER_LOCK_S seconds; a correct password during the lock still
  fails. An admin can unlock early. A successful login resets the counter.
"""

import os
import threading
import time
from collections import OrderedDict, deque


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, "") or default))
    except ValueError:
        return default


ADDR_MAX_TRACKED = 10_000


def addr_max_failures() -> int:
    return _int_env("NIRIKSHAN_LOGIN_ADDR_MAX_FAILURES", 20)


def addr_window_s() -> int:
    return _int_env("NIRIKSHAN_LOGIN_ADDR_WINDOW_S", 900)


def user_max_failures() -> int:
    return _int_env("NIRIKSHAN_LOGIN_USER_MAX_FAILURES", 5)


def user_lock_s() -> int:
    return _int_env("NIRIKSHAN_LOGIN_USER_LOCK_S", 900)


class AddressLimiter:
    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._fails: OrderedDict[str, deque] = OrderedDict()

    def _prune(self, q: deque, now: float) -> None:
        window = addr_window_s()
        while q and now - q[0] >= window:
            q.popleft()

    def retry_after(self, addr: str) -> int:
        """Seconds until another attempt is allowed (0 = allowed now)."""
        now = self._clock()
        with self._lock:
            q = self._fails.get(addr)
            if not q:
                return 0
            self._prune(q, now)
            if len(q) < addr_max_failures():
                return 0
            return max(1, int(addr_window_s() - (now - q[0])) + 1)

    def failure(self, addr: str) -> None:
        now = self._clock()
        with self._lock:
            q = self._fails.pop(addr, None) or deque()
            self._prune(q, now)
            q.append(now)
            while len(q) > addr_max_failures():
                q.popleft()
            self._fails[addr] = q  # most recently failed at the end
            while len(self._fails) > ADDR_MAX_TRACKED:
                self._fails.popitem(last=False)

    def reset(self) -> None:
        with self._lock:
            self._fails.clear()

    def tracked(self) -> int:
        with self._lock:
            return len(self._fails)


address_limiter = AddressLimiter()
