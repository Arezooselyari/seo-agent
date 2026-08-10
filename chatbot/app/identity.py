"""ساخت external_user_id یکتا برای هر کانال و پیدا/ساخت مکالمه‌ی فعال.

هیچ یکپارچه‌سازی هویت بین کانال‌ها در نسخه‌ی فعلی انجام نمی‌شود — یک کاربر
تلگرام و همان فرد در وب، دو external_user_id جدا دارند. اگر بعداً لید با
شماره تلفن ثبت شود، user_profiles.phone می‌تواند کلید تطبیق دستی باشد.
"""
from __future__ import annotations

from supabase import Client

from . import db


def telegram_identity(chat_id: str | int) -> str:
    return f"tg:{chat_id}"


def web_identity(session_id: str) -> str:
    return f"web:{session_id}"


def widget_identity(site_key: str, session_id: str) -> str:
    return f"widget:{site_key}:{session_id}"


def get_or_create_conversation(client: Client, *, tenant_id: int, channel: str,
                               external_user_id: str) -> dict:
    conversation = db.get_active_conversation(
        client, tenant_id=tenant_id, channel=channel, external_user_id=external_user_id
    )
    if conversation is None:
        conversation = db.create_conversation(
            client, tenant_id=tenant_id, channel=channel, external_user_id=external_user_id
        )
    return conversation
