"""خط‌لوله‌ی فکتِ معتبر — استخراجِ آمارِ عددیِ واقعی و منبع‌دار از متنِ منابعِ واقعی.

هدف: مقاله از حالتِ «عمومی» دربیاید و آمارِ واقعی (با استناد) داشته باشد، بدون هیچ
جعلی. این ماژول از متنِ *واقعیِ* مقالاتِ جمع‌آوری‌شده (collector) آمار بیرون می‌کشد و
هر فکت را به منبعِ خودش نگاشت می‌کند.

ضدجعلِ قطعی (مبنای اعتماد کلِ سیستم):
مدل برای هر آمار یک `verbatim_snippet` (عینِ جمله از متن) برمی‌گرداند. فکت فقط وقتی
پذیرفته می‌شود که این جمله — پس از نرمال‌سازیِ ارقام/حروف/فاصله و حذفِ نشانه‌ها —
*واقعاً* در متنِ همان منبع موجود باشد و شاملِ عدد باشد. اگر نبود، حذف می‌شود.
پس حتی اگر مدل توهم کند، عددِ ساختگی وارد citable_facts نمی‌شود.

خروجی با citable_facts (رشته‌ها) + verified_facts (نگاشتِ claim↔source_url) سازگارِ
همان قراردادِ نویسنده/گیت است (بدون تغییرِ Schema).
"""
import logging
import re

from . import llm

logger = logging.getLogger(__name__)

# ارقامِ فارسی/عربی → لاتین (برای تطبیقِ «۸۳» با «83»)
_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_HAS_DIGIT = re.compile(r"\d")

_EXTRACT_PROMPT = """از متنِ زیر فقط جملاتی را استخراج کن که شاملِ یک «عدد، درصد، مبلغ، تاریخ یا مدت‌زمانِ مشخص» هستند.

قوانین سخت (نقضِ هرکدام = خروجیِ باطل):
- فقط جملاتی که «واقعاً و عیناً در متن هستند». چیزی از خودت نساز و عدد را تغییر نده.
- verbatim_snippet باید کلمه‌به‌کلمه از متن کپی شود (بدونِ حتی یک کلمه تغییر).
- stat یک بازنویسیِ کوتاه و تمیزِ همان ادعا برای استفاده در مقاله است — با «همان عدد» و «همان معنا».
- ادعای بدونِ عددِ مشخص را نیاور (مثلِ «بسیار سریع» بدونِ رقم).
- اگر هیچ آمارِ عددیِ واقعی در متن نیست، آرایه‌ی خالی بده.

حداکثر {k} مورد. فقط JSON معتبر:
{{"facts": [{{"stat": "ادعای تمیز با عدد", "verbatim_snippet": "عینِ جمله از متن", "number": "83%"}}]}}

عنوان منبع: {title}

متن منبع:
{text}"""


def _norm(s: str) -> str:
    """نرمال‌سازیِ عمومی: ارقام لاتین، یکسان‌سازیِ ی/ک، جمعِ فاصله‌ها و حذفِ ZWNJ."""
    s = (s or "").translate(_DIGIT_MAP)
    s = s.replace("ي", "ی").replace("ك", "ک").replace("ﻻ", "لا").replace("ـ", "")
    return re.sub(r"[\s‌]+", " ", s).strip()


def _match_key(s: str) -> str:
    """کلیدِ تطبیقِ containment: بدونِ نشانه‌گذاری، فقط حروف/رقم/فاصله."""
    return re.sub(r"[^\w\s%٪]", "", _norm(s)).strip()


def _extract_from_source(source: dict, k: int = 6) -> list[dict]:
    text = (source.get("text") or "")[:15000]
    if len(text) < 200:
        return []
    try:
        res = llm.ask(
            "fact_research",
            _EXTRACT_PROMPT.format(k=k, title=source.get("title", ""), text=text),
            model_tier="main",
            json_output=True,
            max_tokens=4000,
        ) or {}
    except Exception as e:
        logger.warning(f"fact_research: استخراج از {source.get('url')} نشد: {e}")
        return []

    src_key = _match_key(text)
    out = []
    for f in (res.get("facts") or []):
        stat = (f.get("stat") or "").strip()
        snip = f.get("verbatim_snippet") or ""
        snip_key = _match_key(snip)
        if not stat or len(snip_key) < 12:
            continue
        if not _HAS_DIGIT.search(_norm(snip)):
            continue
        # ── ضدجعلِ قطعی: جمله باید واقعاً در متنِ منبع باشد ──
        if snip_key not in src_key:
            logger.info(f"fact_research: رد شد (در منبع نبود): {stat[:60]}")
            continue
        # عددِ ادعا هم باید در متن باشد (اطمینانِ مضاعف)
        nums = re.findall(r"\d+", _norm(stat))
        norm_src = _norm(text)
        if nums and not any(n in norm_src for n in nums):
            logger.info(f"fact_research: رد شد (عدد در منبع نبود): {stat[:60]}")
            continue
        out.append({"claim": stat, "source_url": source.get("url"),
                    "snippet": snip.strip()})
    return out


def research_facts(topic: str, sources: list[dict], max_facts: int = 12) -> dict:
    """آمارِ عددیِ معتبر را از متنِ منابعِ واقعی استخراج و به منبع نگاشت می‌کند.

    Args:
        topic: موضوع (فعلاً فقط برای لاگ).
        sources: [{"url":.., "title":.., "text":..}] — خروجیِ collector.collect
        max_facts: سقفِ تعدادِ فکت.

    Returns:
        {"citable_facts": [str,...], "verified_facts": [{claim, source_url, snippet},...],
         "source_urls": [url,...], "count": int}
    """
    all_facts: list[dict] = []
    seen: set[str] = set()
    for src in sources or []:
        for f in _extract_from_source(src):
            key = _match_key(f["claim"])[:60]
            if not key or key in seen:
                continue
            seen.add(key)
            all_facts.append(f)
            if len(all_facts) >= max_facts:
                break
        if len(all_facts) >= max_facts:
            break

    citable = [f["claim"] for f in all_facts]
    urls = list(dict.fromkeys(f["source_url"] for f in all_facts if f.get("source_url")))
    logger.info(f"fact_research: {len(all_facts)} فکتِ عددیِ معتبر از {len(sources or [])} منبع.")
    return {"citable_facts": citable, "verified_facts": all_facts,
            "source_urls": urls, "count": len(all_facts)}
