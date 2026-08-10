"""حلِّ نشانگرهای [[anchor:]] به صفحاتِ **واقعیِ** سایت (نه اسلاگِ ساختگیِ LLM).

مشکل: نویسنده (LLM) نمی‌داند سایت چه صفحاتی واقعاً دارد، پس یک مسیرِ قابلِ‌قبول
می‌سازد (مثلِ «/automation-consulting») که وجود ندارد → ۴۰۴ در انتشارِ زنده.
راه‌حل: لیستِ واقعیِ صفحاتِ منتشرشده از WP REST گرفته می‌شود؛ متنِ anchor با
کلیدواژه به نزدیک‌ترین صفحه‌ی واقعی نگاشت می‌شود؛ اگر تطابقی نبود، به‌جای لینکِ
شکسته به صفحه‌ی وبلاگ (همیشه واقعی و مرتبط) لینک می‌شود.
"""
import logging
import re

import requests

from .config import env

logger = logging.getLogger(__name__)

# کلیدواژه (فارسی/انگلیسی) → کلیدواژه‌ای که باید در «تیترِ» صفحه‌ی واقعی جست‌وجو شود
# (اسلاگ‌های فارسیِ وردپرس گاه percent-encoded برمی‌گردند؛ تیتر همیشه متنِ خوانا است)
_KEYWORD_TITLE_HINTS = [
    (["مشاوره", "کسب و کار", "کسب‌وکار", "consulting", "اتوماسیون", "جلسه"], ["مشاوره", "جلسه"]),
    (["کتاب", "book"], ["کتاب"]),
    (["داستان", "story", "stories"], ["استوری"]),
    (["تماس", "contact"], ["تماس"]),
    (["درباره", "about"], ["درباره"]),
    (["فروشگاه", "shop", "دوره", "محصول"], ["فروشگاه"]),
]


def _fetch_real_pages() -> list[dict]:
    """صفحاتِ منتشرشده‌ی وردپرس را می‌گیرد: [{slug, link, title}]."""
    base = (env("WP_URL") or "").strip().rstrip("/")
    if not base:
        return []
    try:
        r = requests.get(f"{base}/wp-json/wp/v2/pages",
                         params={"per_page": 50, "status": "publish"}, timeout=15)
        if r.status_code != 200:
            return []
        return [{"slug": p.get("slug", ""), "link": p.get("link", ""),
                 "title": (p.get("title") or {}).get("rendered", "")}
                for p in r.json()]
    except Exception as e:
        logger.warning(f"internal_links: خواندنِ صفحاتِ وردپرس نشد ({e}).")
        return []


def resolve(anchor_text: str, suggested_path: str, pages: list[dict] | None = None) -> str | None:
    """بهترین صفحه‌ی واقعی را برای این anchor برمی‌گرداند؛ None اگر صفحه‌ای در دسترس نبود."""
    # اگر مسیرِ پیشنهادی خودش URLِ کاملِ همین سایت است (مثلاً ساخته‌ی
    # ensure_min_internal_links از پست‌های واقعی)، همان درست است — حدس نزن.
    base = (env("WP_URL") or "").strip().rstrip("/")
    if base and suggested_path.startswith(base):
        return suggested_path

    pages = _fetch_real_pages() if pages is None else pages
    if not pages:
        return None

    hay = f"{anchor_text} {suggested_path}".lower()
    for keywords, title_hints in _KEYWORD_TITLE_HINTS:
        if any(k.lower() in hay for k in keywords):
            for p in pages:
                title = (p.get("title") or "")
                if any(th in title for th in title_hints):
                    return p["link"]

    # fallback: صفحه‌ی وبلاگ (همیشه مرتبط و واقعی است) اگر موجود باشد
    for p in pages:
        if p["slug"] == "blog":
            return p["link"]
    return None


def _fetch_recent_posts(count: int = 6) -> list[dict]:
    """آخرین نوشته‌های منتشرشده‌ی وبلاگ: [{title, link}] — برای بلوکِ «مطالب مرتبط»."""
    base = (env("WP_URL") or "").strip().rstrip("/")
    if not base:
        return []
    try:
        r = requests.get(f"{base}/wp-json/wp/v2/posts",
                         params={"per_page": count, "status": "publish",
                                 "orderby": "date", "order": "desc"}, timeout=15)
        if r.status_code != 200:
            return []
        out = []
        for p in r.json():
            title = re.sub(r"<[^>]+>", "", (p.get("title") or {}).get("rendered", "")).strip()
            link = p.get("link", "")
            if title and link:
                out.append({"title": title, "link": link})
        return out
    except Exception as e:
        logger.warning(f"internal_links: خواندنِ نوشته‌های اخیر نشد ({e}).")
        return []


def ensure_min_internal_links(payload: dict, minimum: int = 2) -> dict:
    """اگر نویسنده کمتر از `minimum` لینکِ داخلی گذاشته، بلوکِ «مطالب مرتبط» با لینک به
    **نوشته‌های واقعیِ منتشرشده‌ی سایت** اضافه می‌کند.

    قطعی و بدونِ LLM. از نشانگرِ [[anchor: عنوان | URLِ واقعی]] استفاده می‌کند تا هم
    چک‌های موجود آن را بشمارند و هم مسیرِ انتشار همان لینکِ درست را بسازد.
    خودِ مقاله (اگر قبلاً منتشر شده) و تکراری‌ها کنار گذاشته می‌شوند.
    """
    body = payload.get("body_html", "") or ""
    have = len(re.findall(r"\[\[anchor:", body)) + len(re.findall(r'<a\s[^>]*href="/', body))
    if have >= minimum:
        return payload
    if "مطالب مرتبط" in body:  # idempotent — دوباره اضافه نکن
        return payload

    need = minimum - have
    own_title = (payload.get("title_seo") or "").strip()
    posts = [p for p in _fetch_recent_posts(count=need + 3) if p["title"] != own_title]
    if not posts:
        logger.info("internal_links: نوشته‌ی منتشرشده‌ای برای «مطالب مرتبط» نبود.")
        return payload

    items = "".join(
        f'<li>[[anchor: {p["title"]} | {p["link"]}]]</li>' for p in posts[:need]
    )
    payload["body_html"] = body.rstrip() + f"\n<h2>مطالب مرتبط</h2>\n<ul>{items}</ul>"
    logger.info(f"internal_links: {min(need, len(posts))} لینکِ داخلیِ واقعی افزوده شد.")
    return payload


def linkify_internal(body: str) -> str:
    """[[anchor: متن | مسیرِ‌پیشنهادی]] را به <a href="واقعی"> یا متنِ ساده (اگر صفحه‌ای نبود) تبدیل می‌کند."""
    pages = _fetch_real_pages()

    def _repl(m):
        inner = m.group(1).split("|")
        text = inner[0].split(":", 1)[-1].strip()
        suggested = inner[1].strip() if len(inner) > 1 else ""
        real_url = resolve(text, suggested, pages)
        if real_url:
            return f'<a href="{real_url}">{text}</a>'
        logger.info(f"internal_links: صفحه‌ی واقعی برای «{text}» نبود — لینک حذف شد.")
        return text

    return re.sub(r"\[\[(anchor:[^\]]*)\]\]", _repl, body or "")
