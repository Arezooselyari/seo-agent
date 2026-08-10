"""اپ اصلی FastAPI — تمام کانال‌ها (تلگرام، چت سایت، ویجت) را وصل می‌کند."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .channels import booking, telegram_webhook, web_chat, widget
from .config import Secrets

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

secrets = Secrets()

app = FastAPI(title="Persian RAG Chatbot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=secrets.widget_allowed_origins_list(),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(telegram_webhook.router)
app.include_router(web_chat.router)
app.include_router(widget.router)
app.include_router(booking.router)


@app.get("/health")
async def health() -> dict:
    return {"ok": True}
