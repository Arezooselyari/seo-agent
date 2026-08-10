"""کانال ویجت قابل‌جاسازی — یک <script> که در هر سایتی (از جمله سایت اصلی) نصب می‌شود.

دفاع دو لایه: CORS (مرورگر، بر اساس Origin) + site_key (سمت سرور، در بدنه‌ی
درخواست) — چون هدر Origin همیشه قابل‌اعتماد ۱۰۰٪ نیست و site_key بعداً
هم می‌تواند کلید پیکربندی مخصوص هر سایت باشد.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import brain, identity
from ..config import Secrets, TenantConfig

router = APIRouter()

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "widget"


class WidgetChatRequest(BaseModel):
    session_id: str
    site_key: str
    message: str


class WidgetChatResponse(BaseModel):
    reply: str


@router.get("/widget.js")
async def widget_script() -> FileResponse:
    return FileResponse(STATIC_DIR / "widget.js", media_type="application/javascript")


@router.post("/api/widget/chat", response_model=WidgetChatResponse)
async def api_widget_chat(body: WidgetChatRequest) -> WidgetChatResponse:
    cfg = TenantConfig.load()
    secrets = Secrets()

    if cfg.widget_site_for_key(body.site_key) is None:
        raise HTTPException(status_code=403, detail="site_key نامعتبر است.")

    external_user_id = identity.widget_identity(body.site_key, body.session_id)
    reply = brain.handle_message("widget", external_user_id, body.message, cfg=cfg, secrets=secrets)
    return WidgetChatResponse(reply=reply)
