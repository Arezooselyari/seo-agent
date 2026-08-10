"""چرخشِ صفِ ابزارها برای موضوعِ مقاله‌های «آموزشی» (config/tool_topics.yaml).

هر بار `next_tool()` ابزاری با کمترین usage_count را برمی‌گرداند (idempotent rotation —
لیست تمام نمی‌شود، فقط دوباره از اول می‌چرخد). بعد از تولیدِ موفق، `mark_used(name)`
شمارنده را +۱ می‌کند تا نوبتِ ابزارهای دیگر برسد.
"""
import logging

import yaml

from .config import CONFIG_DIR

logger = logging.getLogger(__name__)
_FILE = CONFIG_DIR / "tool_topics.yaml"


def _load() -> dict:
    if not _FILE.exists():
        return {"tools": []}
    with open(_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f) or {"tools": []}


def _save(data: dict) -> None:
    with open(_FILE, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def next_tool() -> dict | None:
    """ابزارِ بعدی برای معرفی/آموزش را برمی‌گرداند (کمترین usage_count)."""
    tools = _load().get("tools") or []
    if not tools:
        return None
    return min(tools, key=lambda t: t.get("usage_count", 0))


def mark_used(name: str) -> None:
    """شمارنده‌ی استفاده‌ی این ابزار را +۱ می‌کند (بعد از تولیدِ موفق فراخوانی شود)."""
    data = _load()
    for t in data.get("tools") or []:
        if t.get("name") == name:
            t["usage_count"] = t.get("usage_count", 0) + 1
            break
    _save(data)
