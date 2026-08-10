"""لایه‌ی اطلاع‌رسانی — تلگرام (Bot API با httpx، بدون کتابخانه‌ی اضافه).

سه نوع پیام:
- خبرِ پیش‌نویس آماده: عنوان + متا + امتیاز/دلیل + دکمه‌ها
- فایل HTML کامل مقاله: برای خواندنِ واقعی با عکس و فرمت
- خطا: هر مرحله از پایپ‌لاین fail شد، ساکت نمی‌مانیم
"""
from __future__ import annotations

from pathlib import Path

import httpx

from .config import Secrets

TELEGRAM_MAX = 4096


def _destinations(secrets: Secrets) -> list[tuple[str, str]]:
    """همه‌ی مقصدهای تلگرامِ تنظیم‌شده را برمی‌گرداند: [(token, chat_id), ...].

    تلگرام اول همیشه (اگر تنظیم باشد) + تلگرام دوم (اگر تنظیم باشد).
    """
    dests: list[tuple[str, str]] = []
    if secrets.telegram_bot_token and secrets.telegram_chat_id:
        dests.append((secrets.telegram_bot_token, secrets.telegram_chat_id))
    if secrets.telegram_bot_token_2 and secrets.telegram_chat_id_2:
        dests.append((secrets.telegram_bot_token_2, secrets.telegram_chat_id_2))
    return dests


def _split_message(text: str, limit: int = TELEGRAM_MAX) -> list[str]:
    """پیام بلند را روی مرزِ خط می‌شکند تا هر تکه زیر limit بماند."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            parts.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) + 1 > limit:
            parts.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        parts.append(current)
    return parts


def _send_to_one(token: str, chat_id: str, text: str,
                 reply_markup: dict | None = None) -> bool:
    """پیام را به یک مقصد مشخص می‌فرستد."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    chunks = _split_message(text)
    ok_all = True
    for i, chunk in enumerate(chunks):
        payload: dict = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup and i == len(chunks) - 1:
            payload["reply_markup"] = reply_markup
        try:
            resp = httpx.post(url, json=payload, timeout=20)
            if not resp.json().get("ok"):
                ok_all = False
        except httpx.HTTPError:
            ok_all = False
    return ok_all


def send_telegram(text: str, secrets: Secrets | None = None,
                  reply_markup: dict | None = None) -> bool:
    """پیام به همه‌ی چت‌های تلگرامِ تنظیم‌شده (اول + دوم).
    پیام بلند خودکار تکه می‌شود. اگر هیچ توکنی نباشد، بی‌صدا رد می‌شود."""
    secrets = secrets or Secrets()
    dests = _destinations(secrets)
    if not dests:
        return False
    ok_all = True
    for token, chat_id in dests:
        if not _send_to_one(token, chat_id, text, reply_markup):
            ok_all = False
    return ok_all


def send_document(file_path: str | Path, caption: str = "",
                  secrets: Secrets | None = None) -> bool:
    """یک فایل (مثلاً مقاله‌ی HTML کامل) را به همه‌ی چت‌های تلگرام می‌فرستد."""
    secrets = secrets or Secrets()
    dests = _destinations(secrets)
    if not dests:
        return False
    path = Path(file_path)
    if not path.exists():
        return False
    ok_all = True
    for token, chat_id in dests:
        url = f"https://api.telegram.org/bot{token}/sendDocument"
        try:
            with path.open("rb") as fh:
                resp = httpx.post(
                    url,
                    data={
                        "chat_id": chat_id,
                        "caption": caption[:1024],
                        "parse_mode": "HTML",
                    },
                    files={"document": (path.name, fh, "text/html")},
                    timeout=60,
                )
            if not resp.json().get("ok", False):
                ok_all = False
        except (httpx.HTTPError, OSError):
            ok_all = False
    return ok_all


def notify_draft(*, title: str, meta_description: str, score: float,
                 reason: str, edit_url: str = "", secrets: Secrets | None = None) -> bool:
    """خبرِ کوتاهِ آماده‌شدنِ مقاله. اگر edit_url داده شود لینک وردپرس هم می‌گذارد."""
    text = (
        "📝 <b>مقاله‌ی امروز آماده است</b>\n\n"
        f"<b>{title}</b>\n"
        f"{meta_description}\n\n"
        f"⭐ امتیاز موضوع: {score:.0f}\n"
        f"💡 دلیل انتخاب: {reason}"
    )
    if edit_url:
        text += f'\n\n✏️ <a href="{edit_url}">بازبینی و انتشار در وردپرس</a>'
    else:
        text += "\n\n📎 فایل کامل مقاله (با عکس و فرمت) در پیام بعدی فرستاده می‌شود."
    return send_telegram(text, secrets)


def notify_pipeline_start(target_count: int, secrets: Secrets | None = None) -> bool:
    """پیام شروع اجرای خودکار ایجنت — همان لحظه‌ای که pipeline آغاز می‌شود."""
    from datetime import datetime
    now = datetime.now().strftime("%H:%M")
    text = (
        f"🚀 <b>ایجنت شروع به کار کرد</b> — ساعت {now}\n\n"
        f"در حال تولید {target_count} مقاله‌ی امروز هستم.\n"
        f"تا حدود ۱۵ دقیقه دیگر مقالات در تلگرام ارسال می‌شوند. ⏳"
    )
    return send_telegram(text, secrets)


def notify_error(stage: str, error: str, secrets: Secrets | None = None) -> bool:
    return send_telegram(f"❌ <b>خطا در مرحله‌ی {stage}</b>\n<code>{error[:500]}</code>", secrets)
