"""Simple in-memory TTL cache for frequently accessed data."""

import threading
import time
from typing import Any


_cache: dict[str, tuple[Any, float]] = {}  # key -> (value, expires_at)
_lock = threading.Lock()


def get(key: str) -> Any | None:
    """Return cached value for key, or None if missing/expired.

    Args:
        key: Cache key string.

    Returns:
        Cached value if present and not expired, otherwise None.
    """
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() > expires_at:
            del _cache[key]
            return None
        return value


def set(key: str, value: Any, ttl: int = 300) -> None:
    """Store a value in the cache with a TTL in seconds.

    Args:
        key: Cache key string.
        value: Value to cache.
        ttl: Time-to-live in seconds (default 300).
    """
    with _lock:
        expires_at = time.monotonic() + ttl
        _cache[key] = (value, expires_at)


def delete(key: str) -> None:
    """Remove a key from the cache.

    Args:
        key: Cache key string to remove.
    """
    with _lock:
        _cache.pop(key, None)


def clear() -> None:
    """Remove all entries from the cache."""
    with _lock:
        _cache.clear()


def evict_expired() -> int:
    """Remove all expired entries from the cache.

    Returns:
        Number of entries evicted.
    """
    now = time.monotonic()
    evicted = 0
    with _lock:
        expired_keys = [k for k, (_, exp) in _cache.items() if now > exp]
        for k in expired_keys:
            del _cache[k]
            evicted += 1
    return evicted
