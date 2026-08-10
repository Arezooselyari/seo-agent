"""ابزار ۲ — استعلام وضعیت درخواست مشاوره با کد پیگیری یا شماره تماس."""
from __future__ import annotations

import re

from supabase import Client

from .. import db

DECLARATION = {
    "name": "check_consultation_status",
    "description": (
        "استعلام وضعیت یک درخواست مشاوره‌ی قبلی. اگر کاربر کد پیگیری دارد از "
        "همان استفاده کن؛ وگرنه شماره تماسش را بپرس."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "reference_code": {"type": "string", "description": "کد پیگیری (مثل LD-7F2A1B)"},
            "phone": {"type": "string", "description": "شماره تماسی که قبلاً ثبت شده"},
        },
        "required": [],
    },
}

_STATUS_FA = {
    "pending": "در انتظار تماس",
    "contacted": "تماس گرفته شده",
    "done": "انجام شده",
    "cancelled": "لغو شده",
}

_PHONE_DIGITS = re.compile(r"\D+")


def make_executor(*, client: Client, tenant_id: int):
    def execute(args: dict) -> dict:
        reference_code = (args.get("reference_code") or "").strip() or None
        phone_raw = (args.get("phone") or "").strip()
        phone = _PHONE_DIGITS.sub("", phone_raw) if phone_raw else None

        if not reference_code and not phone:
            return {"error": "برای استعلام، کد پیگیری یا شماره تماس لازم است."}

        row = db.find_consultation_request(
            client, tenant_id=tenant_id, reference_code=reference_code, phone=phone
        )
        if not row:
            return {"found": False}

        return {
            "found": True,
            "reference_code": row["reference_code"],
            "status": row["status"],
            "status_fa": _STATUS_FA.get(row["status"], row["status"]),
            "created_at": row["created_at"],
        }

    return execute
