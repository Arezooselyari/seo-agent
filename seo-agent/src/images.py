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


def _inline_slots(body: str, count: int) -> list[int]:
    """محلِ درجِ تصویرها را بینِ H2ها پخش می‌کند (نه همه در آغازِ متن).

    تصویرِ شاخص خودش بالای مقاله دیده می‌شود، پس H2ِ اول رد می‌شود؛ وگرنه هر دو
    تصویر بالای صفحه جمع می‌شوند و بقیه‌ی مقاله بی‌تصویر می‌ماند.
    """
    ends = [m.end() for m in re.finditer(r"</h2>", body)]
    if not ends or count <= 0:
        return []
    candidates = ends[1:] if len(ends) > 1 else ends
    if count >= len(candidates):
        return candidates
    step = len(candidates) / (count + 1)
    picked: list[int] = []
    for i in range(1, count + 1):
        idx = min(len(candidates) - 1, round(i * step))
        if candidates[idx] not in picked:
            picked.append(candidates[idx])
    return picked


def _figure_html(im: dict) -> str:
    return (f'<figure><img src="{im["url"]}" alt="{im["alt"]}" loading="lazy" '
            f'style="max-width:100%;height:auto;border-radius:12px">'
            f'<figcaption style="font-size:.85rem;color:#888">'
            f'عکس: {im.get("photographer", "Pexels")} / Pexels</figcaption></figure>')


def add_images_to_payload(payload: dict, inline: int | None = None) -> dict:
    """تصویرِ شاخص (فیلدِ جدا) + چند تصویرِ inline پخش‌شده در متن اضافه می‌کند.

    - featured_image_url/alt/credit: فیلدهای payload (شاخص جدا از متن — وردپرس آن را
      بالای مقاله نشان می‌دهد)
    - inline: <figure><img> در body_html، پخش‌شده بینِ H2های میانی. تعدادش از
      settings→images.inline خوانده می‌شود (پارامتر فقط برای override دستی).
    """
    if inline is None:
        from .config import load_settings
        inline = int((load_settings().get("images", {}) or {}).get("inline", 1))
    inline = max(inline, 0)

    q = _english_query(payload)
    imgs = search_images(q, count=1 + inline)
    if not imgs:
        logger.info(f"images: تصویری برای «{q}» یافت نشد.")
        return payload

    payload["featured_image_url"] = imgs[0]["url"]
    payload["featured_image_alt"] = imgs[0]["alt"]
    payload["image_credit"] = imgs[0].get("photographer")
    payload["image_query"] = q

    placed = 0
    if inline and len(imgs) > 1:
        body = payload.get("body_html", "") or ""
        figures = [_figure_html(im) for im in imgs[1:1 + inline]]
        slots = _inline_slots(body, len(figures))
        if slots:
            # از انتها به ابتدا درج کن تا آفستِ محل‌های بعدی جابه‌جا نشود
            for fig, pos in sorted(zip(figures, slots), key=lambda t: -t[1]):
                body = body[:pos] + fig + body[pos:]
            placed = len(slots)
        else:
            body += "".join(figures)
            placed = len(figures)
        payload["body_html"] = body

    logger.info(f"images: شاخص + {placed} inline افزوده شد (query='{q}').")
    return payload
