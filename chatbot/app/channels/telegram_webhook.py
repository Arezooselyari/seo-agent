"""کانال تلگرام — بات عمومی *جدید*، از طریق webhook (نه long-polling).

امنیت با هدر X-Telegram-Bot-Api-Secret-Token تأمین می‌شود، نه allowlist
بودن chat_id (چون این بات برای کاربران عمومی است، نه فقط ادمین).
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Header, HTTPException, Request

from .. import brain, identity
from ..config import Secrets, TenantConfig

router = APIRouter()

_TELEGRAM_API = "https://api.telegram.org/bot"
_MAX_MESSAGE_LEN = 4000


def _send_reply(token: str, chat_id: str | int, text: str) -> None:
    for i in range(0, len(text), _MAX_MESSAGE_LEN) or [0]:
        chunk = text[i:i + _MAX_MESSAGE_LEN] or "..."
        try:
            httpx.post(
                f"{_TELEGRAM_API}{token}/sendMessage",
                json={"chat_id": chat_id, "text": chunk},
                timeout=15,
            )
        except Exception as e:  # noqa: BLE001
            print(f"[telegram_webhook] sendMessage خطا: {e}")


def _parse_update(update: dict) -> tuple[str, str] | None:
    message = update.get("message")
    if not message or "text" not in message:
        return None
    chat_id = str(message["chat"]["id"])
    text = message["text"]
    return chat_id, text


@router.post("/webhook/telegram")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    secrets = Secrets()
    cfg = TenantConfig.load()

    if x_telegram_bot_api_secret_token != secrets.telegram_webhook_secret:
        raise HTTPException(status_code=401, detail="توکن webhook نامعتبر است.")

    update = await request.json()
    parsed = _parse_update(update)
    if parsed is None:
        return {"ok": True}

    chat_id, text = parsed
    external_user_id = identity.telegram_identity(chat_id)

    try:
        reply = brain.handle_message("telegram", external_user_id, text, cfg=cfg, secrets=secrets)
    except Exception as e:  # noqa: BLE001
        print(f"[telegram_webhook] brain خطا: {e}")
        reply = "متأسفم، خطایی پیش آمد. لطفاً دوباره امتحان کن."

    _send_reply(secrets.chatbot_telegram_bot_token, chat_id, reply)
    return {"ok": True}
