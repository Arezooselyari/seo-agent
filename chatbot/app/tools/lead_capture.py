"""ابزار ۱ — ثبت لید / درخواست مشاوره.

مدل وقتی نام و شماره تماس کاربر را جمع‌آوری کرد این ابزار را صدا می‌زند.
یک ردیف در leads و یک ردیف ۱-به-۱ در consultation_requests (status=pending)
می‌سازد و یک reference_code کوتاه برمی‌گرداند تا کاربر بعداً بتواند وضعیتش
را با همان کد پیگیری کند.
"""
from __future__ import annotations

import re
import uuid

from supabase import Client

from .. import db
from ..config import Secrets
from ..notify_admin import notify_new_lead

DECLARATION = {
    "name": "capture_lead",
    "description": (
        "ثبت درخواست مشاوره‌ی کاربر. فقط وقتی صدا بزن که حداقل نام و شماره "
        "تماس را از کاربر گرفته باشی."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "نام کاربر"},
            "phone": {"type": "string", "description": "شماره تماس کاربر"},
            "topic": {"type": "string", "description": "موضوع مورد علاقه‌ی کاربر (اختیاری)"},
            "message": {"type": "string", "description": "توضیح اضافه‌ی کاربر (اختیاری)"},
        },
        "required": ["name", "phone"],
    },
}

_PHONE_DIGITS = re.compile(r"\D+")


def _normalize_phone(phone: str) -> str:
    return _PHONE_DIGITS.sub("", phone or "")


def _new_reference_code() -> str:
    return f"LD-{uuid.uuid4().hex[:6].upper()}"


def make_executor(*, client: Client, tenant_id: int, conversation_id: int,
                  secrets: Secrets | None = None):
    secrets = secrets or Secrets()

    def execute(args: dict) -> dict:
        name = (args.get("name") or "").strip()
        phone = _normalize_phone(args.get("phone") or "")
        if not name or not phone:
            return {"error": "نام یا شماره تماس ناقص است."}

        reference_code = _new_reference_code()
        result = db.insert_lead_and_consultation(
            client,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            name=name,
            phone=phone,
            topic=args.get("topic"),
            message=args.get("message"),
            reference_code=reference_code,
        )

        notify_new_lead(
            name=name, phone=phone, reference_code=reference_code,
            topic=args.get("topic"), secrets=secrets,
        )

        return {
            "reference_code": reference_code,
            "status": result["consultation"]["status"],
        }

    return execute
