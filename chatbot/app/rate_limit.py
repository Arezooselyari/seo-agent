"""محدودکننده‌ی نرخ ساده و بدون وابستگی — درون‌حافظه‌ای (کافی برای یک process
روی یک سرور، طبق deploy فعلی). اگر بعداً پشت چند instance رفت، باید به Redis
منتقل شود.
"""
from __future__ import annotations

import time

_hits: dict[str, list[float]] = {}


def allow(key: str, *, limit: int, window_seconds: int) -> bool:
    """True یعنی درخواست مجاز است؛ False یعنی از حد گذشته."""
    now = time.time()
    hits = [t for t in _hits.get(key, []) if now - t < window_seconds]
    if len(hits) >= limit:
        _hits[key] = hits
        return False
    hits.append(now)
    _hits[key] = hits
    return True
