"""تصاویرِ استوکِ رایگان از Pexels — تصویرِ شاخص + inline بر اساسِ موضوعِ مقاله.

Pexels با عبارتِ انگلیسی نتیجه‌ی بهتری می‌دهد؛ موضوعِ فارسی با یک تماسِ ارزانِ LLM به
عبارتِ کوتاهِ انگلیسی تبدیل می‌شود. کلید: PEXELS_API_KEY در .env (رایگان).
لایسنسِ Pexels استفاده‌ی رایگان (تجاری/غیرتجاری) را اجازه می‌دهد.
"""
import logging
import re

import requests

from . import llm
from .config import env

logger = logging.getLogger(__name__)
_PEXELS = "https://api.pexels.com/v1/search"


def _english_query(payload: dict) -> str:
    """موضوعِ مقاله را به یک عبارتِ کوتاهِ انگلیسیِ جستجوی عکس تبدیل می‌کند."""
    topic = (payload.get("topic") or payload.get("title_seo")
             or (payload.get("target_keywords") or {}).get("primary") or "").strip()
    if not topic:
        return "technology business"
    try:
        r = llm.ask(
            "image_query",
            "این موضوع را به یک عبارتِ کوتاهِ ۲ تا ۴ کلمه‌ایِ انگلیسی برای جستجوی عکسِ "
            "استوکِ مرتبط تبدیل کن (مفهومی و بصری، نه ترجمه‌ی تحت‌اللفظی). "
            'فقط JSON: {"q": "english search phrase"}\n\nموضوع: ' + topic,
            model_tier="cheap", json_output=True, max_tokens=80,
        )
        q = (r.get("q") or "").strip()
        return q or "artificial intelligence technology"
    except Exception as e:
        logger.warning(f"images: ترجمه‌ی کوئری نشد ({e}) — fallback عمومی.")
        return "artificial intelligence technology"


def search_images(query: str, count: int = 1, orientation: str = "landscape") -> list[dict]:
    """عکس‌های مرتبط را از Pexels برمی‌گرداند: [{url, alt, photographer, src_url}]."""
    pk = (env("PEXELS_API_KEY") or "").strip()
    if not pk:
        logger.warning("images: PEXELS_API_KEY تنظیم نشده.")
        return []
    try:
        r = requests.get(
            _PEXELS, headers={"Authorization": pk},
            params={"query": query, "per_page": max(count, 1),
                    "orientation": orientation}, timeout=20,
        )
        if r.status_code != 200:
            logger.warning(f"images: Pexels {r.status_code} — {r.text[:100]}")
            return []
        out = []
        for p in r.json().get("photos", [])[:count]:
            out.append({
                "url": p["src"].get("large") or p["src"].get("original"),
                "alt": (p.get("alt") or query).strip(),
                "photographer": p.get("photographer"),
                "src_url": p.get("url"),
            })
        return out
    except Exception as e:
        logger.warning(f"images: جستجوی Pexels نشد ({e}).")
        return []


def add_images_to_payload(payload: dict, inline: int = 1) -> dict:
    """تصویرِ شاخص (فیلدِ جدا) + (اختیاری) یک تصویرِ inline بعد از اولین H2 را اضافه می‌کند.

    - featured_image_url/alt/credit: فیلدهای payload (شاخص جدا از متن — برای وردپرس و پیش‌نمایش)
    - inline: به‌صورتِ <figure><img> در body_html درج می‌شود (در متن دیده می‌شود)
    """
    q = _english_query(payload)
    imgs = search_images(q, count=1 + max(inline, 0))
    if not imgs:
        logger.info(f"images: تصویری برای «{q}» یافت نشد.")
        return payload

    payload["featured_image_url"] = imgs[0]["url"]
    payload["featured_image_alt"] = imgs[0]["alt"]
    payload["image_credit"] = imgs[0].get("photographer")
    payload["image_query"] = q

    if inline and len(imgs) > 1:
        im = imgs[1]
        fig = (f'<figure><img src="{im["url"]}" alt="{im["alt"]}" loading="lazy" '
               f'style="max-width:100%;height:auto;border-radius:12px">'
               f'<figcaption style="font-size:.85rem;color:#888">عکس: {im.get("photographer","Pexels")} / Pexels</figcaption></figure>')
        body = payload.get("body_html", "") or ""
        m = re.search(r"</h2>", body)
        body = (body[:m.end()] + fig + body[m.end():]) if m else (fig + body)
        payload["body_html"] = body

    logger.info(f"images: شاخص + {min(inline, max(len(imgs)-1, 0))} inline افزوده شد (query='{q}').")
    return payload
