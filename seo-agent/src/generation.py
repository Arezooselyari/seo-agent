"""موتورِ مشترکِ تولیدِ مقاله — یک خطِ تولید، چند رابطِ کاربری.

دموی وب (`client_demo.py`) و باتِ تلگرام (`bot.py`) هر دو همین را صدا می‌زنند تا
دو نسخه از یک منطق نگه داشته نشود.

این ماژول عمداً از هیچ رابطی خبر ندارد: نه job dict، نه chat_id، نه توکن. فقط
`payload` برمی‌گرداند و پیشرفت را از راهِ callback گزارش می‌دهد.
"""
from __future__ import annotations

import logging
from typing import Callable

from . import analyzer, demo_tavily, images, references

logger = logging.getLogger(__name__)

# حوزه‌های از پیش تعریف‌شده — رابط‌ها همین را نمایش می‌دهند
NICHES = {
    "business": "کسب‌وکار و مدیریت",
    "tech": "فناوری و هوش مصنوعی",
    "medical": "پزشکی و سلامت",
    "beauty": "زیبایی و پوست",
    "legal": "حقوقی و وکالت",
    "realestate": "املاک و مسکن",
    "finance": "مالی و سرمایه‌گذاری",
    "education": "آموزش و مهارت",
}

# تعدادِ منابع: هر منبعِ اضافه یک تماسِ seo_analysis و یک fact_research می‌سازد که
# هر دو ورودیِ سنگین دارند — ۳ منبع ~۲۵٪ هزینه و ~۳۰ ثانیه صرفه‌جویی می‌دهد.
_MAX_SOURCES = 3

StepFn = Callable[[str, int], None]


def search_query(niche_label: str, ctype: str, keyword: str) -> str:
    """پرس‌وجوی گراندینگ. برای «خبری» تازگی مهم است، برای «آموزشی» راهنما."""
    subject = keyword.strip() or niche_label
    suffix = ("اخبار و تازه‌ترین تحولات latest news" if ctype == "news"
              else "راهنمای جامع guide how to")
    return f"{subject} {suffix}"


def generate(niche: str, ctype: str, keyword: str,
             on_step: StepFn | None = None) -> dict:
    """یک مقاله‌ی کامل تولید می‌کند و payload را برمی‌گرداند.

    niche: شناسه‌ی حوزه (کلیدِ NICHES) یا برچسبِ آزاد.
    ctype: "tutorial" یا "news".
    keyword: موضوع/کلیدواژه‌ی دلخواه؛ اگر خالی باشد از حوزه برداشته می‌شود.
    on_step: (متنِ فارسیِ مرحله، درصد) — برای نمایشِ پیشرفت.

    خطا: RuntimeError اگر هیچ منبعِ قابلِ استنادی پیدا نشود.
    """
    def step(name: str, percent: int) -> None:
        logger.info(f"[generation] {percent}% — {name}")
        if on_step:
            try:
                on_step(name, percent)
            except Exception:  # noqa: BLE001 — گزارشِ پیشرفت نباید تولید را بکُشد
                logger.warning("on_step خطا داد — نادیده گرفته شد.", exc_info=True)

    niche_label = NICHES.get(niche, niche)
    topic = keyword.strip() or niche_label

    step("در حال جست‌وجوی منابع معتبر…", 10)
    sources = demo_tavily.search(search_query(niche_label, ctype, keyword),
                                 max_results=_MAX_SOURCES)
    if not sources:
        raise RuntimeError("برای این موضوع منبعِ قابلِ استنادی پیدا نشد. "
                           "لطفاً کلیدواژه را کمی عمومی‌تر بنویسید.")

    step(f"{len(sources)} منبع پیدا شد — در حال تحلیل محتوا…", 30)
    brief = analyzer.analyze(topic, sources)

    step("در حال یافتن کلیدواژه‌های هدف…", 45)
    keywords = None
    try:
        from . import keyword_free
        keywords = keyword_free.research_topic(topic, seed=keyword or None)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"کیوردِ رایگان نشد ({e}) — نویسنده خودش برمی‌دارد.")

    step("در حال نگارش مقاله… (طولانی‌ترین مرحله)", 55)
    from . import writer
    payload = writer.write_article(brief, keywords=keywords, content_type=ctype)

    step("در حال افزودن منابع و تصویر…", 88)
    # لینکِ داخلی عمداً اضافه نمی‌شود: به sagharnazari.ir اشاره می‌کند و برای
    # مشتریِ حوزه‌ی دیگر بی‌معنی است.
    try:
        payload = references.add_references_to_payload(payload)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"افزودنِ منابع نشد: {e}")
    try:
        payload = images.add_images_to_payload(payload)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"افزودنِ تصویر نشد: {e}")

    payload.setdefault("niche", niche)
    payload.setdefault("content_type", ctype)
    return payload


def seo_score(payload: dict) -> float:
    """امتیازِ عواملِ رتبه‌ی گوگل. صفر اگر محاسبه ممکن نبود.

    نویسنده لینک‌ها را به‌شکلِ `<a href>` می‌نویسد ولی چک‌لیست نشانگرهای
    `[[anchor:]]`/`[[external:]]` را می‌شمارد؛ پس قبلِ سنجش تبدیل می‌کنیم وگرنه
    امتیازِ لینک‌ها الکی صفر می‌شود.
    """
    import re
    try:
        from . import seo_checklist

        def _to_marker(m: re.Match) -> str:
            href = m.group(1)
            text = re.sub(r"<[^>]+>", "", m.group(2))
            kind = ("external" if href.startswith("http")
                    and "sagharnazari" not in href else "anchor")
            return f"[[{kind}: {text} | {href}]]"

        probe = dict(payload)
        probe["body_html"] = re.sub(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                                    _to_marker, payload.get("body_html", ""))
        return float(seo_checklist.score(probe).get("seo_score", 0.0))
    except Exception:  # noqa: BLE001 — امتیاز نمایشی است، نباید تحویل را بکُشد
        logger.warning("محاسبه‌ی امتیاز سئو نشد.", exc_info=True)
        return 0.0
