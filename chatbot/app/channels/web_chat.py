"""کانال صفحه‌ی کامل چت در سایت (/chat)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import brain, identity
from ..config import Secrets, TenantConfig

router = APIRouter()

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static" / "chat"


class ChatRequest(BaseModel):
    session_id: str
    message: str


class ChatResponse(BaseModel):
    reply: str


@router.get("/chat")
async def chat_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@router.post("/api/chat", response_model=ChatResponse)
async def api_chat(body: ChatRequest) -> ChatResponse:
    cfg = TenantConfig.load()
    secrets = Secrets()
    external_user_id = identity.web_identity(body.session_id)
    reply = brain.handle_message("web", external_user_id, body.message, cfg=cfg, secrets=secrets)
    return ChatResponse(reply=reply)
