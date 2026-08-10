"""اطلاع‌رسانی ساده به ادمین وقتی لید جدید ثبت می‌شود — از طریق همان بات
عمومی چت‌بات (نه بات ادمین src/bot.py)، به ADMIN_TELEGRAM_CHAT_ID.
"""
from __future__ import annotations

import httpx

from .config import Secrets

_TELEGRAM_API = "https://api.telegram.org/bot"


def notify_new_lead(*, name: str, phone: str, reference_code: str, topic: str | None,
                    secrets: Secrets) -> None:
    if not secrets.chatbot_telegram_bot_token or not secrets.admin_telegram_chat_id:
        return
    text = (
        f"🆕 لید جدید از چت‌بات\n"
        f"نام: {name}\n"
        f"تماس: {phone}\n"
        f"موضوع: {topic or '-'}\n"
        f"کد پیگیری: {reference_code}"
    )
    try:
        httpx.post(
            f"{_TELEGRAM_API}{secrets.chatbot_telegram_bot_token}/sendMessage",
            json={"chat_id": secrets.admin_telegram_chat_id, "text": text},
            timeout=10,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[notify_admin] خطا: {e}")


def notify_new_booking(*, name: str, phone: str, reference_code: str,
                       booking_date: str, booking_time: str, topic: str | None,
                       secrets: Secrets) -> None:
    if not secrets.chatbot_telegram_bot_token or not secrets.admin_telegram_chat_id:
        return
    text = (
        f"📅 رزرو جدید از تقویم\n"
        f"نام: {name}\n"
        f"تماس: {phone}\n"
        f"تاریخ: {booking_date}\n"
        f"ساعت: {booking_time}\n"
        f"موضوع: {topic or '-'}\n"
        f"کد پیگیری: {reference_code}"
    )
    try:
        httpx.post(
            f"{_TELEGRAM_API}{secrets.chatbot_telegram_bot_token}/sendMessage",
            json={"chat_id": secrets.admin_telegram_chat_id, "text": text},
            timeout=10,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[notify_admin] خطا: {e}")
