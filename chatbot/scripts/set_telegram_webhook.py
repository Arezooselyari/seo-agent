"""تنظیم یا حذف webhook بات تلگرام چت‌بات.

استفاده:
    python -m chatbot.scripts.set_telegram_webhook set
    python -m chatbot.scripts.set_telegram_webhook delete
"""
from __future__ import annotations

import sys

import httpx

from ..app.config import Secrets

_TELEGRAM_API = "https://api.telegram.org/bot"


def set_webhook(secrets: Secrets) -> None:
    url = f"{secrets.app_base_url.rstrip('/')}/webhook/telegram"
    resp = httpx.post(
        f"{_TELEGRAM_API}{secrets.chatbot_telegram_bot_token}/setWebhook",
        json={
            "url": url,
            "secret_token": secrets.telegram_webhook_secret,
        },
        timeout=15,
    )
    print(resp.status_code, resp.json())


def delete_webhook(secrets: Secrets) -> None:
    resp = httpx.post(
        f"{_TELEGRAM_API}{secrets.chatbot_telegram_bot_token}/deleteWebhook",
        timeout=15,
    )
    print(resp.status_code, resp.json())


def main() -> None:
    secrets = Secrets()
    action = sys.argv[1] if len(sys.argv) > 1 else "set"

    if action == "set":
        set_webhook(secrets)
    elif action == "delete":
        delete_webhook(secrets)
    else:
        print("استفاده: python -m chatbot.scripts.set_telegram_webhook [set|delete]")
        sys.exit(1)


if __name__ == "__main__":
    main()
