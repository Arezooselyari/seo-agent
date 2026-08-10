"""دریافت عکس استوک مرتبط از Pexels API.

برای دریافت کلید رایگان: https://www.pexels.com/api/
کلید را در .env به‌صورت PEXELS_API_KEY=... ذخیره کن.
"""
from __future__ import annotations

import httpx

from .config import Secrets

PEXELS_SEARCH = "https://api.pexels.com/v1/search"


def _to_image_dict(p: dict, alt: str) -> dict:
    """یک نتیجه‌ی Pexels را به dict استاندارد ما تبدیل می‌کند."""
    return {
        "url": p["src"]["large2x"],
        "thumb": p["src"]["medium"],
        "photographer": p["photographer"],
        "photographer_url": p["photographer_url"],
        "pexels_url": p["url"],
        "alt": alt,
    }


def fetch_pexels_image(query: str, secrets: Secrets) -> dict | None:
    """یک عکس افقی مرتبط از Pexels پیدا می‌کند.

    برمی‌گرداند: dict با کلیدهای url، thumb، photographer، pexels_url، alt
    یا None اگر کلید تنظیم نشده یا نتیجه‌ای نبود.
    """
    images = fetch_pexels_images(query, secrets, count=1)
    return images[0] if images else None


def fetch_pexels_images(query: str, secrets: Secrets, count: int = 2) -> list[dict]:
    """چند عکس افقی مرتبط از Pexels پیدا می‌کند (پیش‌فرض ۲ عکس متفاوت).

    برمی‌گرداند: لیست dict (هر کدام: url، thumb، photographer، pexels_url، alt)
    یا لیست خالی اگر کلید تنظیم نشده یا نتیجه‌ای نبود.
    """
    api_key = secrets.pexels_api_key or ""
    if not api_key:
        return []

    from .llm import call_with_retry

    def _do_request() -> list[dict]:
        resp = httpx.get(
            PEXELS_SEARCH,
            headers={"Authorization": api_key},
            # عکس بیشتری می‌گیریم تا بتوانیم count عکس متفاوت برداریم
            params={"query": query, "per_page": max(count * 3, 9), "orientation": "landscape"},
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json().get("photos", [])

    try:
        # روی timeout/قطعیِ موقتِ شبکه چند بار تلاش می‌کند (مثل Gemini)
        photos = call_with_retry(_do_request, retries=3, base_delay=3)
    except Exception as e:  # noqa: BLE001
        print(f"[images] Pexels بعد از چند تلاش هم نشد: {e}")
        return []

    if not photos:
        return []
    # عکس‌های متفاوت (نه تکراری) برمی‌داریم
    result: list[dict] = []
    for p in photos:
        result.append(_to_image_dict(p, query))
        if len(result) >= count:
            break
    return result
