"""تبدیل نام منطقه‌ی زمانی به شیء tzinfo، بدون امکان خطا.

چرا فایل جدا: ZoneInfo روی ویندوز بدون بسته‌ی tzdata خطا می‌دهد. اگر
fallback هم خودش ZoneInfo صدا بزند، همان خطا دوباره بالا می‌آید و کل
صفحه‌ی رزرو می‌خوابد. این تابع تضمین می‌کند همیشه یک tzinfo برمی‌گردد.
"""
from __future__ import annotations

from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

# ایران از سال ۱۴۰۱ ساعت تابستانی ندارد، پس UTC+3:30 ثابت است.
TEHRAN_FALLBACK = timezone(timedelta(hours=3, minutes=30), "Asia/Tehran")


def resolve(name: str | None):
    """نام منطقه‌ی زمانی → tzinfo. هرگز خطا نمی‌دهد."""
    for candidate in (name, "Asia/Tehran"):
        if not candidate:
            continue
        try:
            return ZoneInfo(candidate)
        except Exception:  # noqa: BLE001 — نام نامعتبر یا نبودن tzdata
            continue
    return TEHRAN_FALLBACK
