"""
Pluggable cancel-signal store.

Backends:
  - "memory": single-process dict with TTL prune (default).
  - "redis":  shared store for multi-worker / multi-replica deployments.

Public API (sync, fire-and-forget):
  set_cancel(thread_id)
  consume_cancel(thread_id) -> bool   # True if an unexpired signal was present
"""
import logging
import time
from typing import Protocol

from core.config import (
    CANCEL_SIGNAL_BACKEND,
    CANCEL_SIGNAL_REDIS_URL,
    CANCEL_SIGNAL_TTL_SECONDS,
)

logger = logging.getLogger(__name__)


class _Backend(Protocol):
    def set(self, thread_id: str) -> None: ...
    def consume(self, thread_id: str) -> bool: ...


class _MemoryBackend:
    def __init__(self, ttl: int):
        self._ttl = ttl
        self._signals: dict[str, float] = {}

    def _prune(self) -> None:
        now = time.time()
        expired = [k for k, exp in self._signals.items() if exp <= now]
        for k in expired:
            self._signals.pop(k, None)

    def set(self, thread_id: str) -> None:
        self._prune()
        self._signals[thread_id] = time.time() + self._ttl

    def consume(self, thread_id: str) -> bool:
        self._prune()
        exp = self._signals.pop(thread_id, None)
        return exp is not None and exp > time.time()


class _RedisBackend:
    """Redis-backed signals. Key = cancel:{thread_id}, NX with TTL."""

    def __init__(self, url: str, ttl: int):
        import redis  # imported lazily so memory mode works without redis installed
        self._ttl = ttl
        self._client = redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)

    def _key(self, thread_id: str) -> str:
        return f"cancel:{thread_id}"

    def set(self, thread_id: str) -> None:
        try:
            self._client.set(self._key(thread_id), "1", ex=self._ttl)
        except Exception:
            logger.warning("cancel signal set failed (redis)", exc_info=True)

    def consume(self, thread_id: str) -> bool:
        try:
            return bool(self._client.delete(self._key(thread_id)))
        except Exception:
            logger.warning("cancel signal consume failed (redis)", exc_info=True)
            return False


def _build_backend() -> _Backend:
    if CANCEL_SIGNAL_BACKEND == "redis" and CANCEL_SIGNAL_REDIS_URL:
        try:
            backend = _RedisBackend(CANCEL_SIGNAL_REDIS_URL, CANCEL_SIGNAL_TTL_SECONDS)
            logger.info("Cancel-signal backend: redis")
            return backend
        except Exception:
            logger.warning(
                "Redis cancel-signal init failed; falling back to memory backend",
                exc_info=True,
            )
    logger.info("Cancel-signal backend: memory (TTL=%ds)", CANCEL_SIGNAL_TTL_SECONDS)
    return _MemoryBackend(CANCEL_SIGNAL_TTL_SECONDS)


_backend: _Backend = _build_backend()


def set_cancel(thread_id: str) -> None:
    _backend.set(thread_id)


def consume_cancel(thread_id: str) -> bool:
    return _backend.consume(thread_id)
