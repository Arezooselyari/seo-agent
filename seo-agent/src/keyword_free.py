"""کیوردِ رایگان از Google Autocomplete — جایگزینِ SEMrush برای سایتِ تازه.

فلسفه: سایتِ نو روی کیوردِ رقابتی رتبه نمی‌گیرد؛ پس long-tailِ کم‌رقابتِ واقعی را
از پیشنهادهای تکمیلِ خودکارِ گوگل (چیزی که مردم واقعاً جستجو می‌کنند) استخراج می‌کنیم.
بدونِ کلید، بدونِ هزینه. خروجی **هم‌شکلِ** semrush_bridge است تا نویسنده بدونِ تغییر
مصرفش کند (primary/primary_fa/secondary/longtail/fa_map).

محدودیت صادقانه: حجمِ جستجو و سختیِ کیورد (KD) نمی‌دهد — فقط پیشنهادهای واقعیِ گوگل.
"""
import logging
import re
import time

import requests

logger = logging.getLogger(__name__)

_AUTOCOMPLETE = "https://suggestqueries.google.com/complete/search"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}

# پیشوند/پسوندهای پرسشی و تجاریِ فارسی برای کشفِ long-tailِ متنوع
_MODIFIERS = [
    "", "چیست", "چگونه", "چطور", "آموزش", "بهترین", "مزایای", "کاربرد",
    "برای کسب و کار", "نمونه", "رایگان", "قیمت", "مقایسه", "معایب",
]
_STOP = frozenset("و در به از با برای که را این آن یک های ها یا تا هم بر می".split())
_QUESTION_CUES = ("چیست", "چگونه", "چطور", "چرا", "آیا", "کدام", "چه", "چند")
# واژه‌های نویزِ autocomplete (تکمیل‌های صوتی/بله‌خیری) — پیشنهادِ حاویِ این‌ها دور ریخته می‌شود
_NOISE = frozenset({"بله", "خیر", "آره", "نه", "نیست"})


def _is_relevant(suggestion: str, base_tokens: set[str]) -> bool:
    """آیا پیشنهاد واقعاً هم‌موضوعِ کیوردِ اصلی است؟

    قاعده: باید (تقریباً) **همه‌ی** واژه‌های محتواییِ کیورد را داشته باشد، نه یکی.
    اشتراکِ یک واژه دو جور خراب می‌شد:
      «هوش مصنوعی پادکست»      → «هوش مصنوعی ساخت عکس رایگان» (فقط «هوش مصنوعی» مشترک)
      «تولید صدا با هوش مصنوعی» → «تولید صدا در حنجره علوم هفتم» (فقط «تولید صدا» مشترک)
    هر دو از فیلترِ قبلی رد می‌شدند و نویسنده مجبور می‌شد بی‌ربط‌ها را در متن بگنجاند.
    """
    if not base_tokens:
        return True
    covered = len(_tokens(suggestion) & base_tokens) / len(base_tokens)
    # کیوردهای بلندتر حقِ یک واژه اغماض دارند؛ کوتاه‌ها باید کامل بیایند
    return covered >= (0.75 if len(base_tokens) > 4 else 1.0)


def _tokens(s: str) -> set[str]:
    # lower() برای مقایسه‌ی درستِ توکن‌های انگلیسی («Claude» باید با «claude» یکی باشد)؛
    # روی حروفِ فارسی بی‌اثر است.
    return {t for t in re.split(r"\s+", s.strip().lower()) if t and t not in _STOP and len(t) > 1}


def _is_question(s: str) -> bool:
    return s.endswith("؟") or any(c in s for c in _QUESTION_CUES)


def _dedupe_near_duplicates(items: list[str], base_tokens: set[str],
                            max_single_word_variants: int = 2) -> list[str]:
    """عبارت‌های ساختاری‌شبیه به seed را جمع می‌کند.

    وقتی seed کوتاه است («آموزش X»)، autocomplete معمولاً چندین تکمیلِ هم‌ریشه برمی‌گرداند
    که فقط با **یک کلمه‌ی عمومی** از seed فرق دارند («آموزش X ai»، «آموزش X design»،
    «آموزش کامل X»، «آموزش جامع X»...). این‌ها از نظرِ معنایی یک مفهوم‌اند، نه چند LSI
    متفاوت؛ اگر بدونِ فیلتر به نویسنده داده شوند، نویسنده مجبور می‌شود همه را در متن
    بچپاند تا «پوشش» بدهد — نتیجه‌اش کیوردِ چپان‌شده و لحنِ مصنوعی است.

    منطق: تفاوتِ هر پیشنهاد با seed را می‌سنجیم (توکن‌های اضافه). اگر این تفاوت فقط
    «یک کلمه‌ی عمومی» است، حداکثر `max_single_word_variants` نمونه از این نوع نگه
    می‌داریم؛ پیشنهادهایی که واقعاً عبارتِ چندکلمه‌ایِ متفاوت‌اند (نیتِ جستجوی دیگر،
    مثلِ «آموزش X برای کسب و کار») بدونِ محدودیت می‌مانند.
    """
    kept, seen_distinct = [], []
    single_word_count = 0
    for s in items:
        distinct = _tokens(s) - base_tokens
        if not distinct or distinct in seen_distinct:
            continue
        if len(distinct) == 1:
            if single_word_count >= max_single_word_variants:
                continue
            single_word_count += 1
        seen_distinct.append(distinct)
        kept.append(s)
    return kept


def _suggest(query: str, hl: str = "fa", gl: str = "ir") -> list[str]:
    """پیشنهادهای تکمیلِ خودکارِ گوگل برای یک عبارت (JSON: [query, [suggestions...]])."""
    try:
        r = requests.get(
            _AUTOCOMPLETE,
            params={"client": "firefox", "hl": hl, "gl": gl, "q": query},
            headers=_HEADERS, timeout=10,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        return [s.strip() for s in (data[1] if len(data) > 1 else []) if s and s.strip()]
    except Exception as e:
        logger.warning(f"keyword_free: autocomplete نشد ({query[:30]}): {e}")
        return []


def research_topic(topic: str, seed: str | None = None,
                   max_secondary: int = 8, max_longtail: int = 8,
                   delay: float = 0.25) -> dict:
    """کیوردهای long-tailِ رایگان را از Google Autocomplete برای یک موضوع می‌سازد.

    خروجی هم‌شکلِ semrush_bridge: {primary, primary_fa, secondary, longtail, fa_map, ...}
    """
    # seedِ صریح (کیوردِ کوتاهِ قابلِ‌جستجو) بر topicِ توصیفیِ بلند اولویت دارد
    base = (seed or topic or "").strip()
    base_tokens = _tokens(base)
    seen: set[str] = set()
    suggestions: list[str] = []

    # عبارتِ کاملِ موضوع اغلب بلند است و autocomplete برایش کم پیشنهاد می‌دهد؛ پس
    # «هسته‌»های کوتاه‌ترِ موضوع (۲ و ۳ کلمه‌ی محتوایی) را هم seed می‌کنیم تا شبکه‌ی
    # پیشنهاد گسترده‌تر شود. فیلترِ ربط، نتایج را روی موضوعِ اصلی نگه می‌دارد.
    sig = [t for t in base.split() if t not in _STOP and len(t) > 1]
    seeds = [base]
    if len(sig) >= 3:
        seeds.append(" ".join(sig[:3]))
    if len(sig) >= 2:
        seeds.append(" ".join(sig[:2]))
    seeds = list(dict.fromkeys(seeds))   # حذفِ تکراری با حفظِ ترتیب

    # فهرستِ عبارت‌های جستجو: هر seed به‌تنهایی + موضوعِ اصلی با هر modifier
    queries = list(seeds) + [f"{base} {m}".strip() for m in _MODIFIERS if m]

    for q in queries:
        for s in _suggest(q):
            key = s.lower()
            if key in seen or key == base.lower():
                continue
            # فیلترِ ربط: پیشنهاد باید حداقل یکی از واژه‌های *متمایزکننده‌ی* موضوع را
            # داشته باشد — نه صرفاً «هوش مصنوعی» که در همه‌ی موضوع‌ها هست.
            if not _is_relevant(s, base_tokens):
                continue
            if _tokens(s) & _NOISE:      # تکمیل‌های نویزِ بله/خیر را دور بریز
                continue
            seen.add(key)
            suggestions.append(s)
        time.sleep(delay)   # مؤدب با گوگل

    questions = _dedupe_near_duplicates([s for s in suggestions if _is_question(s)], base_tokens)
    phrases = _dedupe_near_duplicates([s for s in suggestions if not _is_question(s)], base_tokens)

    data = {
        "primary": base,
        "primary_fa": base,
        "secondary": phrases[:max_secondary],
        "longtail": questions[:max_longtail],
        "fa_map": {},
        "source": "google_autocomplete",
        "total_found": len(suggestions),
        "note": "کیوردِ رایگان از Google Autocomplete (long-tailِ کم‌رقابت؛ بدونِ حجم/سختی).",
    }
    logger.info(
        f"keyword_free: «{base}» → {len(phrases)} عبارت + {len(questions)} سوال "
        f"(از {len(suggestions)} پیشنهادِ واقعیِ گوگل)"
    )
    return data
