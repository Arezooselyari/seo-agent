"""کانال رزرو تقویمی — صفحه‌ی /booking + API تعیین اسلات‌های خالی و ثبت رزرو.

مکمل «ثبت لید» مکالمه‌ای در app/tools/lead_capture.py: همان جدول‌های
leads/consultation_requests را پر می‌کند، فقط با تاریخ+ساعت مشخص به‌جای
پیگیری تلفنی صرف.

ساعت کاری و روزهای تعطیل از دیتابیس خوانده می‌شوند (جدول‌های
availability_rules / availability_exceptions / booking_settings) و از پنل
CRM تنظیم می‌شوند — نه از config.yaml. جزئیات در app/availability.py.
"""
from __future__ import annotations

import re
import uuid
from datetime import date as date_cls, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import availability, db, tz as tz_util
from ..config import Secrets, TenantConfig
from ..notify_admin import notify_new_booking
from ..rate_limit import allow

router = APIRouter()

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "booking"

_PHONE_DIGITS = re.compile(r"\D+")


def _slots_for(client, cfg: TenantConfig, *, target: date_cls, date_iso: str) -> list[str]:
    """اسلات‌های خالی یک روز — منبع اصلی دیتابیس است."""
    tenant_id = cfg.tenant_id
    settings = availability.get_settings(client, tenant_id=tenant_id)

    tz = tz_util.resolve(settings.get("timezone"))

    rules = availability.get_rules(client, tenant_id=tenant_id)
    all_exc = availability.get_exceptions(client, tenant_id=tenant_id)

    # حالت اضطراری: مایگریشن 004_crm.sql هنوز اجرا نشده. بدون این، همه‌ی
    # روزها تعطیل نشان داده می‌شدند و رزرو عملاً می‌خوابید.
    if not rules:
        rules = availability.rules_from_config(cfg.booking)
        all_exc = availability.exceptions_from_config(cfg.booking)

    return availability.available_slots_for_date(
        target,
        rules_by_weekday=rules,
        exceptions=availability.exceptions_for(all_exc, target),
        booked=db.list_booked_times(client, tenant_id=tenant_id, booking_date=date_iso),
        now_local=datetime.now(tz),
        slot_minutes=settings.get("slot_minutes", 30),
        min_notice_hours=settings.get("min_notice_hours", 2),
        max_advance_days=settings.get("max_advance_days", 60),
    )


@router.get("/booking")
async def booking_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@router.get("/api/booking/available-slots")
async def api_available_slots(date: str) -> dict:
    try:
        target = date_cls.fromisoformat(date)
    except ValueError:
        raise HTTPException(status_code=400, detail="تاریخ نامعتبر است.")

    cfg = TenantConfig.load()
    client = db.get_client()
    slots = _slots_for(client, cfg, target=target, date_iso=date)
    return {"slots": slots}


class BookingCreateRequest(BaseModel):
    name: str
    phone: str
    date: str
    time: str
    topic: str | None = None
    notes: str | None = None


@router.post("/api/booking/create")
async def api_booking_create(body: BookingCreateRequest, request: Request) -> dict:
    client_ip = request.client.host if request.client else "unknown"
    if not allow(f"booking:{client_ip}", limit=3, window_seconds=600):
        raise HTTPException(status_code=429, detail="درخواست‌های زیاد؛ کمی بعد دوباره تلاش کنید.")

    name = body.name.strip()
    phone = _PHONE_DIGITS.sub("", body.phone)
    if not name or not phone:
        raise HTTPException(status_code=400, detail="نام و شماره تماس لازم است.")

    try:
        target = date_cls.fromisoformat(body.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="تاریخ نامعتبر است.")

    cfg = TenantConfig.load()
    secrets = Secrets()
    client = db.get_client(secrets)

    valid_slots = _slots_for(client, cfg, target=target, date_iso=body.date)
    if body.time not in valid_slots:
        raise HTTPException(status_code=409, detail="این ساعت دیگر خالی نیست؛ لطفاً ساعت دیگری انتخاب کنید.")

    reference_code = f"BK-{uuid.uuid4().hex[:6].upper()}"
    try:
        result = db.insert_booking(
            client, tenant_id=cfg.tenant_id, name=name, phone=phone,
            topic=body.topic, notes=body.notes,
            booking_date=body.date, booking_time=body.time,
            reference_code=reference_code,
        )
    except Exception as e:  # noqa: BLE001
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail="این ساعت لحظاتی پیش رزرو شد؛ ساعت دیگری انتخاب کنید.")
        raise HTTPException(status_code=500, detail="خطا در ثبت رزرو.")

    notify_new_booking(
        name=name, phone=phone, reference_code=reference_code,
        booking_date=body.date, booking_time=body.time, topic=body.topic,
        secrets=secrets,
    )

    return {"reference_code": reference_code, "status": result["consultation"]["status"]}
