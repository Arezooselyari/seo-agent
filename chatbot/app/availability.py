"""ساعت کاری مؤثر و اسلات‌های خالی — خوانده‌شده از دیتابیس، نه config.yaml.

منبع حقیقت این داده‌ها پنل CRM است (پروژه‌ی جدا در saghar-crm/). این ماژول
فقط می‌خواندشان.

⚠️ همتای این فایل: saghar-crm/app/availability.py
   تابع `available_slots_for_date` باید در هر دو یکسان بماند، وگرنه پیش‌نمایشِ
   پنل با آنچه مشتری می‌بیند فرق می‌کند. هر تغییری اینجا باید آنجا هم اعمال شود.

قانون اولویت:
    استثنا (closed / custom_hours)  ←  بر  →  ساعت هفتگی
"""
from __future__ import annotations

import time
from datetime import date as date_cls, datetime, time as dt_time, timedelta

from supabase import Client

# کش کوتاه‌مدت: تقویم رزرو برای هر ماه چندین بار اسلات می‌پرسد و بدون کش
# هر بار چند کوئری اضافه به Supabase می‌خورد. ۶۰ ثانیه به‌قدری کوتاه است که
# تغییرات پنل تقریباً بلافاصله دیده شوند.
_CACHE_TTL = 60.0
_cache: dict[str, tuple[float, object]] = {}

DEFAULT_SETTINGS = {
    "enabled": True,
    "slot_minutes": 30,
    "timezone": "Asia/Tehran",
    "min_notice_hours": 2,
    "max_advance_days": 60,
}


def _cached(key: str, loader):
    hit = _cache.get(key)
    now = time.monotonic()
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    value = loader()
    _cache[key] = (now, value)
    return value


def clear_cache() -> None:
    """پاک‌کردن دستی کش — برای تست.

    نکته: رزروهای ثبت‌شده کش نمی‌شوند (هر بار مستقیم از
    db.list_booked_times خوانده می‌شوند)، پس اسلاتی که همین الان پر شده
    بلافاصله از لیست می‌رود. کش فقط برای ساعت کاری و استثناهاست، که
    تغییرشان تا ۶۰ ثانیه طول می‌کشد تا دیده شود.
    """
    _cache.clear()


# ---------------------------------------------------------------------------
# خواندن از دیتابیس
# ---------------------------------------------------------------------------

def get_settings(client: Client, *, tenant_id: int) -> dict:
    def load() -> dict:
        try:
            res = (
                client.table("booking_settings").select("*")
                .eq("tenant_id", tenant_id).limit(1).execute()
            )
            return (res.data or [None])[0] or dict(DEFAULT_SETTINGS)
        except Exception:  # noqa: BLE001 — اگر مایگریشن هنوز اجرا نشده، رزرو نباید بخوابد
            return dict(DEFAULT_SETTINGS)

    return _cached(f"settings:{tenant_id}", load)


def get_rules(client: Client, *, tenant_id: int) -> dict[int, dict]:
    def load() -> dict[int, dict]:
        try:
            res = (
                client.table("availability_rules")
                .select("weekday, is_open, start_time, end_time")
                .eq("tenant_id", tenant_id).execute()
            )
            return {r["weekday"]: r for r in (res.data or [])}
        except Exception:  # noqa: BLE001
            return {}

    return _cached(f"rules:{tenant_id}", load)


def get_exceptions(client: Client, *, tenant_id: int) -> list[dict]:
    """همه‌ی استثناهای جاری و آینده — یکجا، تا برای هر روز کوئری جدا نزنیم."""
    def load() -> list[dict]:
        try:
            res = (
                client.table("availability_exceptions")
                .select("start_date, end_date, kind, start_time, end_time")
                .eq("tenant_id", tenant_id)
                .gte("end_date", date_cls.today().isoformat())
                .execute()
            )
            return res.data or []
        except Exception:  # noqa: BLE001
            return []

    return _cached(f"exceptions:{tenant_id}", load)


_CONFIG_WEEKDAY_KEYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def rules_from_config(booking_cfg) -> dict[int, dict]:
    """ساعت‌های config.yaml را به شکل جدول درمی‌آورد — فقط حالت اضطراری.

    اگر مایگریشن 004_crm.sql هنوز اجرا نشده باشد، جدول availability_rules
    وجود ندارد و بدون این fallback صفحه‌ی رزرو همه‌ی روزها را تعطیل نشان
    می‌داد. با این کار ترتیب «آپلود کد» و «اجرای مایگریشن» اهمیتی ندارد.

    به‌محض اینکه جدول پر شود، دیتابیس منبع حقیقت است و این تابع دیگر
    صدا زده نمی‌شود.
    """
    out: dict[int, dict] = {}
    for idx, key in enumerate(_CONFIG_WEEKDAY_KEYS):
        hours = getattr(booking_cfg, "weekly_hours", {}).get(key)
        if hours:
            out[idx] = {
                "weekday": idx, "is_open": True,
                "start_time": hours.start, "end_time": hours.end,
            }
    return out


def exceptions_from_config(booking_cfg) -> list[dict]:
    """blackout_dates قدیمی config.yaml → استثناهای «بسته»."""
    return [
        {"start_date": d, "end_date": d, "kind": "closed",
         "start_time": None, "end_time": None}
        for d in getattr(booking_cfg, "blackout_dates", []) or []
    ]


def exceptions_for(exceptions: list[dict], target: date_cls) -> list[dict]:
    out = []
    for e in exceptions:
        try:
            if date_cls.fromisoformat(e["start_date"]) <= target <= date_cls.fromisoformat(e["end_date"]):
                out.append(e)
        except (KeyError, ValueError):
            continue
    return out


# ---------------------------------------------------------------------------
# منطق اسلات — باید با saghar-crm/app/availability.py یکسان بماند
# ---------------------------------------------------------------------------

def to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def slot_times(day_start: str, day_end: str, slot_minutes: int) -> list[str]:
    cur = to_minutes(day_start)
    end = to_minutes(day_end)
    out: list[str] = []
    while cur + slot_minutes <= end:
        out.append(f"{cur // 60:02d}:{cur % 60:02d}")
        cur += slot_minutes
    return out


def hours_for_date(
    target: date_cls,
    rules_by_weekday: dict[int, dict],
    exceptions: list[dict],
) -> tuple[str, str] | None:
    # ۱) «بسته» بر همه‌چیز اولویت دارد
    for exc in exceptions:
        if exc.get("kind") == "closed":
            return None

    # ۲) ساعت سفارشی جای ساعت هفتگی را می‌گیرد
    for exc in exceptions:
        if exc.get("kind") == "custom_hours" and exc.get("start_time") and exc.get("end_time"):
            return exc["start_time"], exc["end_time"]

    # ۳) ساعت هفتگی
    rule = rules_by_weekday.get(target.weekday())
    if not rule or not rule.get("is_open"):
        return None
    return rule["start_time"], rule["end_time"]


def available_slots_for_date(
    target: date_cls,
    *,
    rules_by_weekday: dict[int, dict],
    exceptions: list[dict],
    booked: set[str],
    now_local: datetime,
    slot_minutes: int,
    min_notice_hours: int,
    max_advance_days: int = 0,
) -> list[str]:
    today = now_local.date()

    if target < today:
        return []
    if max_advance_days and target > today + timedelta(days=max_advance_days):
        return []

    hours = hours_for_date(target, rules_by_weekday, exceptions)
    if hours is None:
        return []

    slots = slot_times(hours[0], hours[1], slot_minutes)

    if target == today:
        min_time = now_local + timedelta(hours=min_notice_hours)
        slots = [
            s for s in slots
            if datetime.combine(target, dt_time.fromisoformat(s), tzinfo=now_local.tzinfo) >= min_time
        ]

    return [s for s in slots if s not in booked]
