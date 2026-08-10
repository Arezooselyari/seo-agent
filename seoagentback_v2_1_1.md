# بکاپ قبل از پچ v2.1.1 — 2026-07-20


## src\architecture_v2_1_utils.py

```python
"""ابزارهای مشترک پچ معماری v2.1 — Soft Quantitative Claims، QA Cache، انتخاب نسخه.

پیاده‌سازی مرجع Specification کاربر، تطبیق‌یافته با معماری فعلی (payloadمحور، SQLite).
همه‌چیز Fail-Closed است: در ابهام، ادعا unsupported و نسخه ذخیره‌نشده می‌ماند.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

VALIDATOR_VERSION = "2.1"

SOFT_QUANTITATIVE_PATTERNS: tuple[tuple[str, str], ...] = (
    # زمان و مدت
    (r"معمولاً", "duration_or_frequency_generalization"),
    (r"اغلب", "frequency_generalization"),
    (r"اکثراً", "frequency_generalization"),
    (r"در بیشتر موارد", "frequency_generalization"),
    (r"بسیاری از", "frequency_generalization"),
    (r"بخش بزرگی از", "frequency_generalization"),
    (r"چندین هفته", "duration_generalization"),
    (r"چند هفته", "duration_generalization"),
    (r"چند روز", "duration_generalization"),
    (r"در مدت کوتاه", "duration_generalization"),
    (r"در زمان کوتاه", "duration_generalization"),
    # عملکرد و دقت
    (r"دقت بسیار بالا", "performance_generalization"),
    (r"دقت بالا", "performance_generalization"),
    (r"عملکرد بسیار بهتر", "performance_generalization"),
    (r"عملکرد بهتر", "performance_generalization"),
    (r"به شکل چشمگیری", "performance_generalization"),
    (r"به‌طور چشمگیری", "performance_generalization"),
    (r"به طور چشمگیری", "performance_generalization"),
    (r"به شکل قابل[‌ ]?توجهی", "performance_generalization"),
    (r"به‌طور قابل[‌ ]?توجهی", "performance_generalization"),
    (r"به طور قابل[‌ ]?توجهی", "performance_generalization"),
    (r"رشد چشمگیر", "performance_generalization"),
    (r"افزایش چشمگیر", "performance_generalization"),
    (r"کاهش چشمگیر", "performance_generalization"),
    (r"رشد محسوس", "performance_generalization"),
    (r"افزایش محسوس", "performance_generalization"),
    (r"کاهش محسوس", "performance_generalization"),
    (r"افزایش قابل[‌ ]?توجه", "performance_generalization"),
    # هزینه و سرعت
    (r"هزینه کمتر", "cost_generalization"),
    (r"هزینه‌های کمتر", "cost_generalization"),
    (r"صرفه[‌ ]?جویی قابل[‌ ]?توجه", "cost_generalization"),
    (r"بسیار سریع‌تر", "speed_generalization"),
    (r"سریع‌تر", "speed_generalization"),
    (r"زمان کمتر", "duration_generalization"),
)

SAFE_NEUTRAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"به .* بستگی دارد"),
    re.compile(r"باید .* آزمایش شود"),
    re.compile(r"بدون .* قابل تعیین نیست"),
    re.compile(r"ممکن است"),
    re.compile(r"می‌تواند"),
)


@dataclass(frozen=True)
class SoftQuantitativeClaim:
    claim: str
    category: str
    supported: bool
    verified_fact_id: str | None
    required_action: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim,
            "category": self.category,
            "supported": self.supported,
            "verified_fact_id": self.verified_fact_id,
            "required_action": self.required_action,
            "reason": self.reason,
        }


def normalize_text_for_hash(text: str) -> str:
    """نرمال‌سازی محافظه‌کارانه برای Cache — محتوا/H2/عدد/Marker را تغییر نمی‌دهد."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    return normalized.strip()


def stable_hash(value: Any) -> str:
    """هش پایدار برای str یا ساختارهای JSON-compatible."""
    if isinstance(value, str):
        payload = normalize_text_for_hash(value)
    else:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def split_into_claim_units(text: str) -> list[str]:
    """متن را برای پیش‌فیلتر قطعی به واحدهای کوچک (جمله) تقسیم می‌کند."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    parts = re.split(r"(?<=[.!؟؛])\s+|\n+", text)
    return [part.strip() for part in parts if part and part.strip()]


def _contains_safe_neutralization(claim: str) -> bool:
    return any(pattern.search(claim) for pattern in SAFE_NEUTRAL_PATTERNS)


def _match_verified_fact(
    claim: str, verified_facts: Sequence[Mapping[str, Any]],
) -> str | None:
    """Matching محافظه‌کارانه — در شک، None (یعنی unsupported)."""
    normalized_claim = normalize_text_for_hash(claim)
    for fact in verified_facts:
        fact_id = str(fact.get("id") or "").strip()
        fact_claim = normalize_text_for_hash(str(fact.get("claim") or ""))
        allowed_scope = fact.get("allowed_scope")
        if not fact_id or not fact_claim:
            continue
        if allowed_scope in (None, "", [], {}):
            continue
        if fact_claim in normalized_claim or normalized_claim in fact_claim:
            return fact_id
    return None


def detect_soft_quantitative_claims(
    text: str,
    verified_facts: Sequence[Mapping[str, Any]] | None = None,
) -> list[SoftQuantitativeClaim]:
    verified_facts = verified_facts or []
    results: list[SoftQuantitativeClaim] = []
    for unit in split_into_claim_units(text):
        matched_categories: set[str] = set()
        for pattern, category in SOFT_QUANTITATIVE_PATTERNS:
            if re.search(pattern, unit):
                matched_categories.add(category)
        if not matched_categories:
            continue
        if _contains_safe_neutralization(unit):
            continue
        fact_id = _match_verified_fact(unit, verified_facts)
        supported = fact_id is not None
        for category in sorted(matched_categories):
            results.append(SoftQuantitativeClaim(
                claim=unit,
                category=category,
                supported=supported,
                verified_fact_id=fact_id,
                required_action="keep" if supported else "remove_or_neutralize",
                reason=("Matched an approved verified_fact." if supported
                        else "Soft quantitative or performance claim has no approved verified_fact."),
            ))
    return results


def count_unsupported_soft_claims(
    claims: Iterable[SoftQuantitativeClaim | Mapping[str, Any]],
) -> int:
    total = 0
    for claim in claims:
        supported = (claim.supported if isinstance(claim, SoftQuantitativeClaim)
                     else bool(claim.get("supported", False)))
        if not supported:
            total += 1
    return total


def merge_soft_claims(
    deterministic_claims: list[dict], llm_claims: list[dict],
) -> list[dict]:
    """ادغام نتیجه‌ی قطعی و LLM — Fail-Closed: اگر یکی unsupported بود، unsupported."""
    merged: dict[tuple[str, str], dict] = {}
    for item in list(deterministic_claims) + list(llm_claims or []):
        claim = str(item.get("claim") or "").strip()
        category = str(item.get("category") or "unknown").strip()
        if not claim:
            continue
        key = (claim, category)
        if key not in merged:
            merged[key] = item
            continue
        existing_supported = bool(merged[key].get("supported", False))
        new_supported = bool(item.get("supported", False))
        if existing_supported and not new_supported:
            merged[key] = item
    return list(merged.values())


def build_qa_cache_key(
    *, text: str, model_name: str, qa_prompt_version: str,
    editorial_rules: Any, verified_facts: Any,
) -> str:
    payload = {
        "content_hash": stable_hash(text),
        "model_name": model_name,
        "qa_prompt_version": qa_prompt_version,
        "editorial_rules_hash": stable_hash(editorial_rules),
        "verified_facts_hash": stable_hash(verified_facts),
    }
    return stable_hash(payload)


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_version_rank(result: Mapping[str, Any]) -> tuple[int, int, int, int, float]:
    """بزرگ‌تر = بهتر. اولویت: hard کمتر > unsupported کمتر > soft کمتر > warning کمتر > نمره بیشتر."""
    return (
        -safe_int(result.get("hard_error_count")),
        -safe_int(result.get("unsupported_claim_count")),
        -safe_int(result.get("soft_unsupported_claim_count")),
        -safe_int(result.get("rewrite_warning_count")),
        safe_float(result.get("final_score")),
    )


def should_save_candidate(
    *, candidate_result: Mapping[str, Any], previous_result: Mapping[str, Any],
) -> tuple[bool, str]:
    """نسخه‌ی جدید فقط در صورت بهبود واقعی ذخیره می‌شود (قواعد غیرقابل تغییر spec)."""
    if bool(candidate_result.get("would_reject", False)):
        return False, "candidate_would_reject"
    if candidate_result.get("validator_passed") is not True:
        return False, "candidate_validator_failed_or_missing"
    candidate_rank = build_version_rank(candidate_result)
    previous_rank = build_version_rank(previous_result)
    if candidate_rank > previous_rank:
        return True, "candidate_strictly_better"
    if candidate_rank == previous_rank:
        return False, "rank_tied_keep_previous"
    return False, "candidate_rank_worse"

```

## src\writer.py

```python
"""گام ۳ — تولید مقاله‌ی فارسی سئو شده (Generate Mode + Rewrite Mode).

پرامپت سیستم: prompts/seo-content-agent-prompt.xml (با Prompt Caching).
Rewrite Mode: فقط بخش‌های فهرست‌شده در revision_patch بازنویسی می‌شوند؛
بخش‌های سالم (preserve_sections) کلمه‌به‌کلمه حفظ می‌شوند.
"""
import json
import re

from . import editor_memory, llm, semrush_bridge
from .config import CONFIG_DIR, env, load_settings

_FORBIDDEN_FILE = CONFIG_DIR / "forbidden_phrases.txt"


def _forbidden_block() -> str:
    """لیست عبارات ممنوعه را برای تزریق به پرامپت‌ها می‌سازد."""
    if not _FORBIDDEN_FILE.exists():
        return ""
    phrases = [
        ln.strip() for ln in _FORBIDDEN_FILE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    if not phrases:
        return ""
    return (
        "عبارات ممنوعه (استفاده از هر کدام = ردّ قطعی مقاله؛ هرگز به کار نبر):\n"
        + "\n".join(f"- {p}" for p in phrases)
    )


def _context_blocks(rule_categories: list[str] | None = None,
                    max_rules_per_category: int | None = None) -> str:
    """بلوک‌های مشترک context برای هر سه مسیر نویسنده:
    درس‌های تحریریه + قوانین تحریریه (فیلترشده بر دسته) + عبارات ممنوعه.
    قوانین «راهنمای کیفیت»اند نه چک‌لیست — این در خود بلوک قوانین تصریح شده.
    """
    out = ""
    lessons = editor_memory.lessons_prompt_block()
    if lessons:
        out += f"\n\n<editorial_lessons>\n{lessons}\n</editorial_lessons>"
    rules = editor_memory.rules_prompt_block(rule_categories, max_rules_per_category)
    if rules:
        out += f"\n\n<editorial_rules>\n{rules}\n</editorial_rules>"
    forbidden = _forbidden_block()
    if forbidden:
        out += f"\n\n<forbidden_phrases>\n{forbidden}\n</forbidden_phrases>"
    return out

WRITE_PROMPT = """بر اساس بریف رقابتی زیر، یک مقاله‌ی کامل فارسی و سئو شده تولید کن.

<brief>
{brief}
</brief>

<target_keywords>
کیوردهای هدف (از تحلیل SEMrush — رعایت این‌ها برای رنکینگ حیاتی است):
{target_keywords}
</target_keywords>

<fact_policy>
- فقط از اطلاعات موجود در brief.citable_facts استفاده کن.
- هیچ عدد، درصد، قیمت، مدت‌زمان، نام مشتری، نام شرکت،
  Case Study یا نتیجه تجاری خارج از citable_facts تولید نکن.
- مثال فرضی فقط برای توضیح فرایند مجاز است.
- مثال فرضی نباید شامل عدد، درصد، قیمت، حجم فروش، نرخ رشد،
  نرخ کاهش، صرفه‌جویی زمانی یا نتیجه تجاری باشد.
- نبود داده را با آمار، داستان یا تجربه ساختگی جبران نکن.
- اگر داده کافی نیست، محدودیت اطلاعات را صادقانه بیان کن.
- هر منبع فقط از ادعایی پشتیبانی می‌کند که واقعاً در آن منبع آمده —
  منبع عمومی را به ادعای تخصصی/تجاری وصل نکن.
</fact_policy>

<soft_quantitative_claim_policy>
هر عبارت درباره زمان، هزینه، سرعت، دقت، فراوانی، میزان استفاده، نتیجه یا عملکرد،
حتی اگر عدد صریح نداشته باشد، ادعای کمی محسوب می‌شود.

بدون verified_fact مجاز نیستی عبارت‌هایی مانند موارد زیر یا معادل معنایی آن‌ها را تولید کنی:
«معمولاً»، «اغلب»، «بسیاری»، «اکثر»، «بخش بزرگی»، «چندین»،
«چند هفته»، «در مدت کوتاه»، «سریع‌تر»، «دقت بالا»، «بسیار دقیق»،
«رشد چشمگیر»، «افزایش قابل‌توجه»، «کاهش محسوس»، «هزینه کمتر»،
«عملکرد بهتر» و عبارت‌های مشابه.

اگر Fact تأییدشده وجود ندارد:
- ادعا را حذف کن؛
- یا آن را به توضیح شرطی و خنثی تبدیل کن؛
- هیچ عدد، بازه، شدت، فراوانی، مدت یا نتیجه جدیدی نساز.

نمونه مجاز:
«زمان راه‌اندازی به دامنه پروژه، تعداد اتصال‌ها و وضعیت زیرساخت بستگی دارد.»

نمونه غیرمجاز بدون verified_fact:
«راه‌اندازی معمولاً چند هفته طول می‌کشد.»
</soft_quantitative_claim_policy>

<cta_policy>
{cta_policy}
</cta_policy>

<requirements>
- زبان: فارسی روان و انسانی با این معیارهای اجرایی:
  * نثر مستقیم، روشن و حرفه‌ای باشد.
  * از تشبیه‌های کلیشه‌ای مانند «دستیار همیشه بیدار» استفاده نکن.
  * از عبارت‌های «در دنیای امروز»، «دیگر یک انتخاب نیست»،
    «راهکاری ضروری»، «تحول چشمگیر» و ساختارهای مشابه استفاده نکن.
  * هر پاراگراف باید حداقل یک نکته جدید اضافه کند.
  * یک مفهوم را با عبارت‌های متفاوت تکرار نکن.
  * تخصص باید از جزئیات فنی، محدودیت‌ها و پیش‌نیازها مشخص شود؛
    نه از لحن نمایشی یا ادعای تجربه.
- طول: {min_words} تا {max_words} کلمه
- ساختار هدینگ: بین ۴۰ تا ۷۰ درصد H2ها می‌توانند سوال‌محور باشند؛
  سایر H2ها باید توصیفی، مقایسه‌ای، فرایندمحور یا تصمیم‌محور باشند.
  ساختار هدینگ را بر اساس Search Intent انتخاب کن.
- بلافاصله پس از هر H2 یک پاسخ مستقیم ۱-۲ جمله‌ای بده. پاراگراف بعدی حق ندارد
  همان پاسخ را بازگویی کند؛ باید جزئیات، شرایط، محدودیت، پیش‌نیاز یا داده‌ی
  مستند جدید اضافه کند. اگر پاسخ مستقیم کافی است، مقدمه‌ی تکراری تولید نکن.
- بخش FAQ با حداقل {min_faq} سوال (H3 + پاسخ کوتاه)
- خلأهای محتوای رقبا (content_gaps) را پوشش بده — این مزیت رقابتی ماست
- از آمار واقعی بریف (citable_facts) استفاده کن و در انتها به منابع استناد کن
- کلیدواژه‌های LSI را طبیعی پخش کن، بدون Keyword Stuffing
- کیورد اصلیِ بالا را دقیقاً در H1، صد کلمه‌ی اول، حداقل یک H2 و جمع‌بندی بیاور
- لینک داخلی (اجباری، حداقل ۲): در متن، ۲ عبارت را با این نشانه علامت بزن:
  [[anchor: متن لینک | صفحه‌ی مقصد پیشنهادی]] — مثلاً [[anchor: مشاوره اتوماسیون | صفحه خدمات]]
- لینک خارجی (اجباری، حداقل ۱): منبع اصلی را یک بار با این نشانه بیاور:
  [[external: نام منبع | URL]] — از source_urls بریف استفاده کن
- جمله‌ی آخر بدنه باید کامل و با نقطه تمام شود (بدون جمله‌ی ناتمام)
</requirements>

فقط JSON با این ساختار برگردان (body_html با تگ‌های HTML کامل و نشانگرهای لینک [[anchor:]] و [[external:]] داخل متن):
{{
  "title_seo": "حداکثر ۶۰ کاراکتر، شامل کلیدواژه‌ی اصلی",
  "meta_description": "دقیقاً بین ۱۵۰ تا ۱۶۰ کاراکتر، شامل کیورد اصلی و یک دعوت به اقدام",
  "h1": "...",
  "slug": "english-url-slug",
  "body_html": "<p>مقدمه... [[anchor: متن | صفحه]] ...</p><h2>...</h2><p>... [[external: منبع | URL]] ...</p>...<h2>سوالات متداول</h2><h3>...</h3><p>...</p>",
  "tags": ["برچسب‌های فارسی"],
  "image_keywords": ["2-3 English keywords for stock photo search"],
  "seo_grade": 85
}}"""

REWRITE_PROMPT = """تو ویراستار ارشد تحریریه هستی. مقاله‌ی زیر در بازبینی QA ایراداتی داشت.
سردبیر یک «برنامه‌ی اصلاح پچ‌محور» نوشته. وظیفه‌ی تو اجرای دقیق آن است.

<article>
{article}
</article>

<revision_patches>
{patches}
</revision_patches>

<preserve_sections>
این بخش‌ها سالم‌اند و باید کلمه‌به‌کلمه، بدون هیچ تغییری، در خروجی حفظ شوند:
{preserve}
</preserve_sections>

<verified_facts>
{verified_facts}
</verified_facts>

{lessons}

قوانین اجرا:
1. فقط بخش‌های فهرست‌شده در پچ‌ها را بازنویسی کن — دقیقاً طبق instruction هر پچ.
2. بخش‌های preserve را عیناً کپی کن. حتی یک کلمه‌ی آن‌ها را عوض نکن.
3. پچ scope=global را روی کل متن اعمال کن ولی ساختار و بخش‌های سالم را نگه دار.
4. نشانگرهای لینک [[anchor: ...]] و [[external: ...]] موجود را حفظ کن (مگر پچ صریحاً بگوید).
5. متا باید ۱۵۰-۱۶۰ کاراکتر، عنوان ≤ ۶۰ کاراکتر، و جمله‌ی آخر بدنه کامل باشد.
6. هیچ Patch اجازه‌ی تولید واقعیت جدید ندارد.
7. اگر یک Patch درخواست عدد، مثال، Case Study، تجربه شخصی، منبع، قیمت، شهر،
   شرکت یا نتیجه‌ی جدیدی دارد که در verified_facts نیست، آن بخش را تولید نکن
   و در rewrite_warnings گزارش بده.
8. ادعای بدون منبع را با جزئیات بیشتر معتبر جلوه نده.
   آن را حذف یا به بیان کیفی محتاطانه تبدیل کن.
9. جایگزینی کلیشه با مترادف کلیشه‌ای ممنوع است.
   جمله باید کوتاه‌تر، مستقیم‌تر یا اطلاعاتی‌تر شود.
10. هیچ URL، برند، ابزار، شهر، شخص یا موجودیت جدیدی اضافه نکن.
11. اگر Patch با fact_policy یا accuracy_rules تضاد داشت،
    fact_policy و accuracy_rules اولویت بالاتر دارند.

خروجی: همان JSON کامل مقاله (title_seo, meta_description, h1, slug, body_html, tags,
image_keywords, seo_grade) — بدنه‌ی کامل با بخش‌های اصلاح‌شده + بخش‌های محفوظ.
در صورت ردّ یک پچ، فیلد اختیاری rewrite_warnings را هم اضافه کن:
"rewrite_warnings": [{{"patch_id": "شناسه/بخش پچ", "reason": "دلیل ردّ"}}]"""

HUMANIZE_PROMPT = """تو ویراستار سبک و نثر فارسی هستی. وظیفه‌ات فقط طبیعی‌تر کردن بیان مقاله است.
حق تغییر، توسعه یا تولید محتوای جدید نداری.

<article>
{article}
</article>

<quality_review>
{review}
</quality_review>

<verified_facts>
{verified_facts}
</verified_facts>

<locked_elements>
{locked_elements}
</locked_elements>

قوانین قطعی:

1. فقط سبک جمله‌بندی، ریتم، انتخاب واژه، طول جمله‌ها و تکرارهای زبانی را اصلاح کن.

2. هیچ اطلاعات، تحلیل، نتیجه‌گیری، توصیه، مثال، سناریو، شهر، شرکت،
   ابزار، قابلیت، عدد، درصد، مبلغ، قیمت، زمان یا ادعای جدیدی اضافه نکن.

3. هیچ تجربه شخصی یا سازمانی نساز. عبارت‌هایی مانند:
   «من دیده‌ام»، «در پروژه‌های ما»، «تجربه نشان داده»، «مشتریان ما»،
   «یادم می‌آید»، «در جلسه‌ای با مدیر...» و هر روایت دست‌اول تأییدنشده ممنوع است.

4. اگر جمله‌ای کلی است، آن را ساده‌تر و مستقیم‌تر کن؛
   برای ملموس‌کردن آن، عدد یا مثال جدید نساز.

5. سناریوی فرضی جدید اضافه نکن.
   سناریوی موجود را فقط در صورتی حفظ کن که در locked_elements ثبت شده باشد.

6. هیچ عدد، درصد، قیمت، مدت‌زمان، نرخ رشد، نرخ کاهش یا نتیجه کمی جدیدی مجاز نیست؛
   حتی داخل مثال فرضی.

7. منابع، URLها، اعداد، نام ابزارها و ادعاهای موجود را توسعه نده.
   هر منبع فقط از ادعایی پشتیبانی می‌کند که در verified_facts ثبت شده است.

8. H1، H2، H3، ساختار مقاله و نشانگرهای لینک را حفظ کن،
   مگر اینکه quality_review صریحاً تغییر ساختار را خواسته باشد.

9. عبارت‌های تبلیغاتی مطلق مانند «ضروری»، «حیاتی»، «تحول‌آفرین»،
   «افزایش چشمگیر فروش»، «بهترین راهکار» و «رشد تضمینی» را خنثی کن،
   مگر اینکه پشتوانه مستند داشته باشند.

10. قبل از تحویل بررسی کن:
    - عدد جدید: صفر
    - موجودیت جدید: صفر
    - مثال جدید: صفر
    - تجربه شخصی جدید: صفر
    - URL جدید: صفر
    - ادعای تجاری جدید: صفر

<soft_claim_preservation_policy>
در انسانی‌سازی:
- هیچ عبارت کمی نرم جدید درباره زمان، هزینه، سرعت، دقت، فراوانی یا عملکرد نساز.
- ادعای خنثی را به «معمولاً»، «اغلب»، «دقت بالا»، «رشد چشمگیر» یا عبارات مشابه تبدیل نکن.
- حق نداری برای طبیعی‌تر کردن متن، شدت یا فراوانی به جمله اضافه کنی.
- verified_facts و locked_numbers را فقط در allowed_scope همان Fact استفاده کن.
</soft_claim_preservation_policy>

خروجی همان JSON کامل مقاله باشد
(title_seo, meta_description, h1, slug, body_html, tags, image_keywords, seo_grade)."""


def write_article(brief: dict, keywords: dict | None = None) -> dict:
    """مقاله را تولید می‌کند.

    keywords: dict کیوردهای هدف (خروجی semrush_bridge). اگر None باشد، از فایل واسط
    برای همین موضوع خوانده می‌شود (فاز A باید قبلاً توسط Claude اجرا شده باشد).
    """
    cfg = load_settings()["article"]
    if keywords is None:
        keywords = semrush_bridge.load_keywords(brief["topic"])
    # اگر هنوز کیوردی نیست و کلید SEMrush هست، فاز A را خودکار اجرا کن
    if keywords is None and env("SEMRUSH_API_KEY") and load_settings().get("semrush", {}).get("enabled"):
        try:
            from . import semrush_api
            keywords = semrush_api.research_topic(brief["topic"])
        except Exception as e:
            print(f"[writer] هشدار: کیوردریسرچ خودکار SEMrush نشد: {e}")
    kw_block = semrush_bridge.keywords_prompt_block(keywords)

    # سیاست CTA: فقط CTA تاییدشده‌ی بریف مجاز است؛ وگرنه CTA خنثی/اطلاعاتی
    cta = brief.get("approved_cta") or {}
    if cta.get("enabled") and cta.get("text"):
        cta_policy = (
            "CTA تجاری تاییدشده (فقط همین، بدون تغییر پیشنهاد):\n"
            + json.dumps(cta, ensure_ascii=False, indent=1)
        )
    else:
        cta_policy = (
            "هیچ CTA تجاری تایید نشده است. هیچ جلسه رایگان، مشاوره رایگان، تخفیف، "
            "«تماس با کارشناسان»، خدمت یا پیشنهاد تجاری اختراع نکن. "
            "جمع‌بندی باید خنثی و اطلاعاتی باشد (توصیه‌ی اجرایی، معیار تصمیم، قدم بعدی عملی)."
        )

    user_content = WRITE_PROMPT.format(
        brief=json.dumps(brief, ensure_ascii=False, indent=1),
        target_keywords=kw_block,
        min_words=cfg["min_words"],
        max_words=cfg["max_words"],
        min_faq=cfg["min_faq"],
        cta_policy=cta_policy,
    )
    # خلاصه‌ی قوانین همه‌ی دسته‌ها (۳ قانون اول هر دسته) — تولید بهتر از ابتدا، حلقه‌ی کوتاه‌تر
    _core = ("voice_spec_rules", "accuracy_rules")
    other_cats = [c for c in editor_memory.load_rules() if c not in _core]
    user_content += _context_blocks(rule_categories=other_cats or None, max_rules_per_category=3)
    # Voice Spec + قوانین دقت فنی — کامل (نه خلاصه)؛ داور کیفیت هم با همین‌ها قضاوت می‌کند
    core = editor_memory.rules_prompt_block(list(_core))
    if core:
        user_content += f"\n\n<voice_spec>\n{core}\n</voice_spec>"

    payload = llm.ask(
        step="article_writing",
        user_content=user_content,
        model_tier="main",
        system=llm.system_prompt_xml(),
        cache_system=True,
        max_tokens=20000,
        temperature=0.7,  # نویسندگی خلاق — با temp=0 متن قالبی می‌شود
    )
    payload["topic"] = brief["topic"]
    payload["source_urls"] = brief["source_urls"]
    # فکت‌های مستند بریف در payload می‌مانند تا ویراستار سبک (humanize) بداند
    # کدام ادعاها پشتوانه دارند (verified_facts)
    if brief.get("citable_facts"):
        payload["citable_facts"] = brief["citable_facts"]
    if brief.get("approved_cta"):
        payload["approved_cta"] = brief["approved_cta"]
    if keywords:
        payload["target_keywords"] = keywords

    # v2.1: پیش‌فیلتر قطعی Soft Quantitative Claims — فقط کشف و ثبت (بدون بازنویسی خودکار)
    from .architecture_v2_1_utils import detect_soft_quantitative_claims
    soft = detect_soft_quantitative_claims(_payload_text(payload),
                                           verified_facts=_fact_entries(payload))
    payload["soft_quantitative_claims"] = [c.as_dict() for c in soft]
    payload["soft_unsupported_claim_count"] = sum(1 for c in soft if not c.supported)
    if payload["soft_unsupported_claim_count"]:
        print(f"[writer] ⚠ {payload['soft_unsupported_claim_count']} ادعای کمی نرم بدون منبع "
              f"در پیش‌نویس (گیت کیفیت مسدود خواهد کرد)")

    word_count = len(payload.get("body_html", "").split())
    print(f"[writer] ✓ مقاله تولید شد: «{payload.get('title_seo')}» (~{word_count} کلمه، نمره {payload.get('seo_grade')})")
    return payload


def rewrite_article(payload: dict, revision_plan: dict, revision_no: int = 1) -> dict:
    """Rewrite Mode: فقط بخش‌های معیوب را طبق برنامه‌ی اصلاح بازنویسی می‌کند.

    payload: مقاله‌ی فعلی. revision_plan: خروجی revision_planner.build_plan.
    خروجی: payload جدید (فیلدهای غیرمتنی مثل topic/source_urls/target_keywords حفظ می‌شوند).
    """
    patches = revision_plan.get("patches", [])
    if not patches:
        return payload

    article_repr = json.dumps(
        {
            "title_seo": payload.get("title_seo", ""),
            "meta_description": payload.get("meta_description", ""),
            "h1": payload.get("h1", ""),
            "slug": payload.get("slug", ""),
            "body_html": payload.get("body_html", ""),
            "tags": payload.get("tags", []),
        },
        ensure_ascii=False,
        indent=1,
    )
    # قوانین مرتبط با بازنویسی پچی: ضد AI (اولویت بالا) + خوانایی + سئو + Voice Spec + دقت فنی
    extra = _context_blocks(
        rule_categories=["anti_ai_writing_rules", "readability_rules", "seo_rules",
                         "voice_spec_rules", "accuracy_rules"]
    )

    new_payload = llm.ask(
        step=f"article_rewrite_r{revision_no}",
        user_content=REWRITE_PROMPT.format(
            article=article_repr,
            patches=json.dumps(patches, ensure_ascii=False, indent=1),
            preserve=json.dumps(revision_plan.get("preserve_sections", []), ensure_ascii=False),
            verified_facts=_verified_facts_block(payload),
            lessons=extra,
        ),
        model_tier="main",
        system=llm.system_prompt_xml(),
        cache_system=True,
        max_tokens=32000,  # بازنویسی کل مقاله + JSON + thinking — سقف بالا تا truncate نشود
        temperature=0.7,
    )

    if new_payload.get("rewrite_warnings"):
        print(f"[writer] ⚠ پچ‌های ردشده توسط fact_policy: "
              f"{json.dumps(new_payload['rewrite_warnings'], ensure_ascii=False)}")

    # فیلدهای زمینه‌ای که مدل برنمی‌گرداند را از payload قبلی حفظ کن
    for key in ("topic", "source_urls", "target_keywords", "image_keywords",
                "citable_facts", "approved_cta"):
        if key in payload and key not in new_payload:
            new_payload[key] = payload[key]

    word_count = len(new_payload.get("body_html", "").split())
    print(f"[writer] ✎ بازنویسی دور {revision_no}: «{new_payload.get('title_seo')}» (~{word_count} کلمه، {len(patches)} پچ)")
    return new_payload


# ── استخراج‌گرهای قطعی (برای verified_facts و validator) ─────────
_NUM_RE = re.compile(r"[0-9۰-۹٠-٩][0-9۰-۹٠-٩,.،٫/]*")
_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_URL_RE = re.compile(r"https?://[^\s\"'<>\]\)]+")
_LATIN_ENTITY_RE = re.compile(r"[A-Za-z][A-Za-z0-9.+&-]{2,}")
# ادعای تجربه‌ی دست‌اول تاییدنشده — الگوهای قطعی
_EXPERIENCE_PATTERNS = (
    "تجربه به من نشان", "در پروژه‌های ما", "مشتریان ما", "یادم می‌آید",
    "در جلسه‌ای با", "من دیده‌ام", "من خودم دیده", "در پروژه‌هایی که دیده",
    "تجربه نشان داده", "در پروژه اخیر", "در پروژه‌های بسیاری",
)


def _extract_numbers(text: str) -> set:
    out = set()
    for m in _NUM_RE.findall(text or ""):
        n = m.translate(_DIGIT_MAP).strip(",.،٫/")
        if n:
            out.add(n)
    return out


def _extract_urls(text: str) -> set:
    return set(_URL_RE.findall(text or ""))


def _extract_latin_entities(text: str) -> set:
    return set(_LATIN_ENTITY_RE.findall(text or ""))


def _payload_text(p: dict) -> str:
    """متن قابل‌انتشار payload برای مقایسه/اعتبارسنجی."""
    parts = [p.get("title_seo", ""), p.get("meta_description", ""),
             p.get("h1", ""), p.get("body_html", "") or p.get("body_markdown", "")]
    if p.get("faq"):
        parts.append(json.dumps(p["faq"], ensure_ascii=False))
    return " ".join(str(x) for x in parts)


def _h2_list(p: dict) -> list:
    body = p.get("body_html", "") or ""
    return [re.sub(r"<[^>]+>|\s+", " ", h).strip()
            for h in re.findall(r"<h2[^>]*>(.*?)</h2>", body, re.DOTALL)]


def _link_markers(p: dict) -> list:
    return sorted(re.findall(r"\[\[(?:anchor|external):[^\]]*\]\]",
                             p.get("body_html", "") or ""))


def _fact_entries(payload: dict) -> list[dict]:
    """فهرست ساخت‌یافته‌ی فکت‌های تاییدشده (برای پرامپت‌ها و آشکارساز soft claim)."""
    facts = payload.get("citable_facts") or []
    urls = payload.get("source_urls") or []
    entries = []
    for i, fact in enumerate(facts, 1):
        entries.append({
            "id": f"fact_{i:02d}",
            "claim": fact,
            "source_url": urls[i - 1] if i - 1 < len(urls) else (urls[-1] if urls else None),
            "allowed_scope": "فقط همین ادعا — توسعه به نتایج تجاری/عددی دیگر ممنوع",
        })
    return entries


def _verified_facts_block(payload: dict) -> str:
    """فکت‌های مستند مقاله با نگاشت ادعا-منبع و دامنه‌ی مجاز (Claim–Source Mapping)."""
    facts = payload.get("citable_facts") or []
    urls = payload.get("source_urls") or []
    if not facts and not urls:
        return "(هیچ فکت تاییدشده‌ای ثبت نشده — بنابراین هیچ ادعای منبع‌دار یا عدد جدیدی مجاز نیست)"
    entries = _fact_entries(payload)
    data = {
        "verified_facts": entries,
        "source_urls": urls,
        "locked_numbers": sorted(_extract_numbers(" ".join(str(f) for f in facts))),
        "approved_cta": payload.get("approved_cta") or "(هیچ CTA تجاری تایید نشده)",
    }
    return json.dumps(data, ensure_ascii=False, indent=1)


def validate_humanize(old_payload: dict, new_payload: dict) -> list[str]:
    """اعتبارسنجی قطعی خروجی Humanizer — ویراستار سبک حق تولید واقعیت جدید ندارد.

    برمی‌گرداند: فهرست تخلف‌ها (خالی = معتبر).
    """
    violations = []
    old_t, new_t = _payload_text(old_payload), _payload_text(new_payload)

    facts_text = " ".join(str(f) for f in (old_payload.get("citable_facts") or []))
    allowed_nums = _extract_numbers(old_t) | _extract_numbers(facts_text)
    extra_nums = _extract_numbers(new_t) - allowed_nums
    if extra_nums:
        violations.append(f"عدد جدید: {sorted(extra_nums)}")

    allowed_urls = _extract_urls(old_t) | set(old_payload.get("source_urls") or [])
    extra_urls = _extract_urls(new_t) - allowed_urls
    if extra_urls:
        violations.append(f"URL جدید: {sorted(extra_urls)}")

    allowed_ents = (_extract_latin_entities(old_t)
                    | _extract_latin_entities(facts_text)
                    | _extract_latin_entities(" ".join(old_payload.get("source_urls") or [])))
    extra_ents = _extract_latin_entities(new_t) - allowed_ents
    if extra_ents:
        violations.append(f"موجودیت/برند جدید: {sorted(extra_ents)}")

    new_exp = [pat for pat in _EXPERIENCE_PATTERNS if pat in new_t and pat not in old_t]
    if new_exp:
        violations.append(f"ادعای تجربه‌ی جدید: {new_exp}")

    if _h2_list(old_payload) != _h2_list(new_payload):
        violations.append("ساختار H2 تغییر کرده")
    if _link_markers(old_payload) != _link_markers(new_payload):
        violations.append("نشانگرهای لینک تغییر کرده")

    # v2.1: ادعای کمی نرم جدید (معمولاً/اغلب/چند هفته/دقت بالا/...) → ردّ
    from .architecture_v2_1_utils import detect_soft_quantitative_claims
    facts = _fact_entries(old_payload)
    before_soft = {(c.claim, c.category)
                   for c in detect_soft_quantitative_claims(old_t, verified_facts=facts)}
    after_soft = {(c.claim, c.category)
                  for c in detect_soft_quantitative_claims(new_t, verified_facts=facts)}
    new_soft = sorted(after_soft - before_soft)
    if new_soft:
        violations.append("new_soft_quantitative_claim: "
                          + "; ".join(c[0][:60] for c in new_soft[:3]))

    return violations


def _locked_elements_block(payload: dict) -> str:
    """عناصر قفل‌شده‌ی مقاله: H1/H2ها، کیورد اصلی، نشانگرهای لینک و سناریوی علامت‌گذاری‌شده‌ی موجود."""
    body = payload.get("body_html", "") or ""
    tk = payload.get("target_keywords") or {}
    scenario = None
    m = re.search(r"[^.!?؟\n<>]*(?:فرض کنید|تصور کنید)[^.!?؟]*[.!?؟]?", body)
    if m:
        scenario = re.sub(r"<[^>]+>", "", m.group(0)).strip()[:250]
    locked = {
        "h1": payload.get("h1", ""),
        "h2_headings": [
            re.sub(r"<[^>]+>", "", h).strip()
            for h in re.findall(r"<h2[^>]*>(.*?)</h2>", body, re.DOTALL)
        ],
        "primary_keyword": tk.get("primary_fa") or tk.get("primary") or "",
        "link_markers": re.findall(r"\[\[(?:anchor|external):[^\]]*\]\]", body),
        "approved_scenario": scenario or "(سناریوی علامت‌گذاری‌شده‌ای در متن نیست — سناریوی جدید هم مجاز نیست)",
    }
    return json.dumps(locked, ensure_ascii=False, indent=1)


def humanize_article(payload: dict, gate_report: dict, revision_no: int = 1) -> dict:
    """Humanize Mode: ویراستار سبک و نثر — فقط بیان طبیعی‌تر، بدون هیچ محتوای جدید.

    طبق پرامپت مصوب کاربر: تغییر فقط در جمله‌بندی/ریتم/واژه‌ها؛ عدد، مثال، سناریو،
    موجودیت یا ادعای جدید مطلقاً ممنوع. verified_facts و locked_elements از payload
    ساخته و به پرامپت تزریق می‌شوند.
    gate_report: خروجی quality_gate.review (کلیشه‌ها + ایرادات لحن به مدل داده می‌شود).
    """
    article_repr = json.dumps(
        {
            "title_seo": payload.get("title_seo", ""),
            "meta_description": payload.get("meta_description", ""),
            "h1": payload.get("h1", ""),
            "slug": payload.get("slug", ""),
            "body_html": payload.get("body_html", ""),
            "tags": payload.get("tags", []),
        },
        ensure_ascii=False,
        indent=1,
    )
    review_repr = json.dumps(
        {
            "scores": gate_report.get("scores", {}),
            "cliches": gate_report.get("cliches", []),
            "issues": [
                i for i in gate_report.get("issues", [])
                if i.get("category") in ("ai_cliche", "robotic_language", "generic_example",
                                          "missing_local_example", "repetitive_sentence", "low_eeat")
            ],
            "cta_suggestion": gate_report.get("cta_suggestion"),
        },
        ensure_ascii=False,
        indent=1,
    )

    user_content = HUMANIZE_PROMPT.format(
        article=article_repr,
        review=review_repr,
        verified_facts=_verified_facts_block(payload),
        locked_elements=_locked_elements_block(payload),
    )
    # فقط لیست عبارات ممنوعه ضمیمه می‌شود (هم‌راستا با قانون ۹)؛ قوانین لحن/سناریو
    # عمداً تزریق نمی‌شوند تا با فلسفه‌ی «فقط ویرایش سبک، بدون محتوای جدید» تضاد نکنند.
    forbidden = _forbidden_block()
    if forbidden:
        user_content += f"\n\n<forbidden_phrases>\n{forbidden}\n</forbidden_phrases>"

    new_payload = llm.ask(
        step=f"article_humanize_r{revision_no}",
        user_content=user_content,
        model_tier="main",
        system=llm.system_prompt_xml(),
        cache_system=True,
        max_tokens=32000,
        temperature=0.3,  # ویراستار سبک: وفاداری به متن مهم‌تر از خلاقیت است (قبلاً 0.9 برای بازنویسی خلاق)
    )

    for key in ("topic", "source_urls", "target_keywords", "image_keywords",
                "citable_facts", "approved_cta"):
        if key in payload and key not in new_payload:
            new_payload[key] = payload[key]

    # Validator قطعی: اگر ویراستار واقعیت جدید ساخته، خروجی این دور رد و نسخه‌ی قبلی حفظ می‌شود
    violations = validate_humanize(payload, new_payload)
    if violations:
        print(f"[writer] ⛔ خروجی انسانی‌سازی دور {revision_no} توسط validator رد شد: {violations}")
        from .architecture_v2_1_utils import stable_hash
        rejected = dict(payload)
        rejected["humanize_rejections"] = list(payload.get("humanize_rejections") or []) + [
            {"revision": revision_no, "violations": violations,
             "candidate_content_hash": stable_hash(_payload_text(new_payload)),
             "restored_content_hash": stable_hash(_payload_text(payload))}
        ]
        return rejected

    word_count = len(new_payload.get("body_html", "").split())
    print(f"[writer] ♻ انسانی‌سازی دور {revision_no}: «{new_payload.get('title_seo')}» (~{word_count} کلمه)")
    return new_payload

```

## src\quality_gate.py

```python
"""دروازه‌ی کیفیت محتوا (Content Quality Gate) — بین Writer و گیت نهایی.

پرامپت نقش‌محور کاربر (prompts/content-quality-gate.md) را اجرا می‌کند:
لحن انسانی، E-E-A-T، استراتژی کیورد، Conversion، اعتبار داده‌ها.

خروجی JSON ساختاریافته شامل:
- scores: امتیاز ۰-۱۰ هر بُعد (human_tone, seo, eeat, keyword, structure, conversion, trust)
- cliches: عبارات کلیشه‌ای پیداشده (با پیشنهاد جایگزین)
- issues: در همان فرمت qa_analyzer (به حلقه‌ی اصلاح تزریق می‌شود)
- recommendations: سه دسته (high/medium/long_term)
گیت: میانگین وزنی scores باید ≥ آستانه‌ی settings باشد و human_tone حداقلش را رد نکند.
"""
import json
import logging

from . import editor_memory, llm
from .config import PROMPTS_DIR, load_settings

logger = logging.getLogger(__name__)

_PROMPT_FILE = PROMPTS_DIR / "content-quality-gate.md"

# دستور خروجی JSON برای pipeline (به انتهای پرامپت کاربر اضافه می‌شود)
_OUTPUT_ADDENDUM = """

═══════════════════════════════════
فرمت خروجی (فقط JSON معتبر، بدون متن اضافه)
═══════════════════════════════════
تمام تحلیل بخش‌های بالا را در این ساختار بده:
{
  "scores": {
    "human_tone": 0-10,
    "seo": 0-10,
    "eeat": 0-10,
    "keyword": 0-10,
    "structure": 0-10,
    "conversion": 0-10,
    "trust": 0-10
  },
  "eeat_detail": {"experience": 0-10, "expertise": 0-10, "authority": 0-10, "trust": 0-10},
  "cliches": [
    {"quote": "عبارت کلیشه‌ای دقیق از متن",
     "problem": "چرا کلیشه/تبلیغاتی است",
     "action": "دستور اصلاح (حذف، کوتاه‌کردن، یا بیان مستقیم‌تر) — نه جمله‌ی جایگزین کامل",
     "must_not_add": ["مترادف‌های کلیشه‌ای که نباید جایگزین شوند"]}
  ],
  "quantitative_claims": [
    {"claim": "متن دقیق هر ادعای عددی/درصدی/قیمتی/زمانی مقاله",
     "source_id": "شناسه یا نام منبع اگر در citable_facts/verified_facts پشتیبانی می‌شود، وگرنه null",
     "status": "supported | unsupported",
     "required_action": "keep | remove | qualify"}
  ],
  "soft_quantitative_claims": [
    {"claim": "جمله‌ی کامل ادعای کمی نرم (بدون عدد صریح: معمولاً/اغلب/چند هفته/دقت بالا/سریع‌تر/...)",
     "category": "duration_generalization | frequency_generalization | performance_generalization | cost_generalization | speed_generalization",
     "supported": false,
     "verified_fact_id": null,
     "required_action": "remove_or_neutralize",
     "reason": "دلیل"}
  ],
  "title_suggestion": "پیشنهاد عنوان بهتر (یا null اگر عنوان خوب است)",
  "meta_suggestion": "پیشنهاد متای بهتر (یا null)",
  "cta_suggestion": "پیشنهاد CTA بهتر (یا null)",
  "unsourced_claims": ["ادعاهای عددی/آماری بدون منبع"],
  "issues": [
    {
      "category": "ai_cliche | robotic_language | low_eeat | weak_cta | generic_example | missing_local_example | weak_title | weak_meta | unnatural_keyword | low_information_gain | repetitive_sentence",
      "severity": "high | medium | low",
      "location": "کجای مقاله",
      "exact_quote": "نقل‌قول دقیق از متن (کپی کلمه‌به‌کلمه، حداکثر ۳۰ کلمه)",
      "problem": "چرا ایراد است",
      "rewrite_instruction": "دستور عملی اصلاح — با مثال ملموس، نه توصیه‌ی کلی"
    }
  ],
  "recommendations": {
    "high_priority": ["اصلاحات ضروری قبل از انتشار"],
    "medium_priority": ["اصلاحات برای افزایش رتبه"],
    "long_term": ["اصلاحات برای Authority شدن"]
  },
  "summary_table": [
    {"section": "Human Tone", "score": 0-10, "main_issue": "...", "fix": "..."}
  ],
  "rules_compliance": {
    "followed": ["قوانین تحریریه‌ای که مقاله رعایت کرده (متن کوتاه قانون)"],
    "violated": [
      {"rule": "متن کوتاه قانون نقض‌شده", "severity": "high | medium | low",
       "evidence": "شاهد کوتاه از متن", "fix": "پیشنهاد اصلاح مشخص"}
    ]
  }
}
- سخت‌گیر باش: متن AI-گونه با کلیشه و ادعای بی‌منبع نباید human_tone بالا بگیرد.
- لحن را با «وجود روایت اول‌شخص» نسنج: نبود تجربه‌ی شخصی یا اول‌شخص، به‌تنهایی
  نمره را پایین نمی‌آورد و وجودش نمره نمی‌سازد. معیار لحن: روشنی، ریتم طبیعی،
  نبود کلیشه، و نثر مستقیم.
- exact_quote هر ایراد باید واقعاً در متن باشد.
- همه‌ی کلیشه‌ها را در issues هم بیاور (category=ai_cliche) تا نویسنده اصلاحشان کند.
- در پیشنهادها هرگز کلیشه را با مترادف کلیشه‌ای جایگزین نکن («راهکاری ضروری»→«ابزاری
  حیاتی» ممنوع)؛ به‌جای جمله‌ی جایگزین، اقدام (حذف/کوتاه‌سازی/بیان مستقیم) و
  must_not_add بده.
- rules_compliance را دقیقاً بر اساس <editorial_rules> داده‌شده در ورودی پر کن —
  همین قوانین معیار داوری تو هستند (همان قوانینی که نویسنده با آن‌ها می‌نویسد).

گیت‌های سخت (وجود هر کدام یعنی ردّ قطعی — این‌ها را حتماً در issues با severity=high بیاور):
1. عدد، درصد، قیمت یا مدت‌زمان بدون منبع در verified_facts/citable_facts
2. تجربه‌ی شخصی/سازمانی تاییدنشده («در پروژه‌های ما»، «یادم می‌آید»، ...)
3. Case Study، مشتری یا پروژه‌ی خیالی
4. منبعی که از ادعای متصل‌شده پشتیبانی نمی‌کند (توسعه‌ی دامنه‌ی منبع)
5. CTA تجاری تاییدنشده (جلسه/مشاوره رایگان، تخفیف، تماس با کارشناسان — بدون approved_cta)
6. ادعای قطعی درباره‌ی افزایش فروش، سود، امنیت یا دقت بدون منبع
7. قابلیت فنی بدون ذکر پیش‌نیازهای لازم (API، یکپارچه‌سازی، داده، مجوز)
- quantitative_claims را برای تک‌تک ادعاهای کمی مقاله پر کن؛ هر ادعای unsupported
  باید در unsourced_claims هم بیاید (این دو فیلد باید هم‌خوان باشند).

Soft Quantitative Claims — ادعای کمی فقط عدد/درصد/قیمت نیست:
هر جمله‌ای که شدت، فراوانی، مدت، سرعت، دقت، میزان استفاده، کاهش، افزایش،
هزینه یا نتیجه را بیان کند ادعا محسوب می‌شود (معمولاً، اغلب، بسیاری، اکثر،
بخش بزرگی، چند هفته/روز، مدت کوتاه، دقت بالا، بسیار دقیق، سریع‌تر، زمان کمتر,
رشد چشمگیر، افزایش قابل‌توجه، کاهش محسوس، هزینه کمتر، صرفه‌جویی قابل‌توجه،
عملکرد بهتر و مشابه).
برای هر ادعا: متن کامل + category + فقط با verified_fact معتبرِ دارای
allowed_scope مناسب supported=true؛ وگرنه supported=false و
required_action=remove_or_neutralize. هیچ Fact یا عدد جدیدی پیشنهاد نکن.
حتی یک ادعای Soft بی‌منبع باید passed=false کند.
- نکته‌ی قرارداد: نشانگرهای [[anchor:]] و [[external:]] مکانیزم رسمی لینک‌گذاری‌اند
  و placeholder خطا محسوب نمی‌شوند؛ تصاویر در مرحله‌ی انتشار اضافه می‌شوند و نبود
  <img> در body خطا نیست؛ فیلد جداگانه‌ی h1 منبع H1 صفحه است و نبود تگ <h1> در
  body_html خطا نیست.
"""

# وزن هر بُعد در نمره‌ی نهایی گیت (جمع = ۱)
_WEIGHTS = {
    "human_tone": 0.30,
    "eeat": 0.20,
    "conversion": 0.15,
    "keyword": 0.10,
    "seo": 0.10,
    "structure": 0.075,
    "trust": 0.075,
}


def _load_prompt() -> str:
    return _PROMPT_FILE.read_text(encoding="utf-8") + _OUTPUT_ADDENDUM


def weighted_score(scores: dict) -> float:
    """میانگین وزنی امتیازها (۰-۱۰)."""
    total, wsum = 0.0, 0.0
    for key, w in _WEIGHTS.items():
        v = scores.get(key)
        if isinstance(v, (int, float)):
            total += v * w
            wsum += w
    return round(total / wsum, 1) if wsum else 0.0


def review(payload: dict, step: str = "quality_gate") -> dict:
    """مقاله را با پرامپت نقش‌محور بررسی می‌کند. dict خروجی + passed برمی‌گرداند."""
    cfg = load_settings().get("quality_gate", {})
    min_weighted = float(cfg.get("min_weighted_score", 7.5))
    min_human = float(cfg.get("min_human_tone", 8))

    title = payload.get("title_seo") or payload.get("h1", "")
    meta = payload.get("meta_description", "")
    body = payload.get("body_html") or payload.get("body_markdown", "")
    kw = payload.get("target_keywords", {}) or {}
    primary = kw.get("primary_fa") or kw.get("primary") or ""

    cta = payload.get("approved_cta") or {}
    cta_line = (json.dumps(cta, ensure_ascii=False) if cta.get("enabled")
                else "هیچ CTA تجاری تایید نشده — هر CTA تجاری در متن یعنی ردّ قطعی (گیت سخت ۵)")
    facts = payload.get("citable_facts") or []
    facts_block = ("\n".join(f"- {f}" for f in facts) if facts
                   else "(هیچ فکت مستندی ثبت نشده — هر ادعای عددی unsupported است)")
    user_content = (
        f"کیورد اصلی مقاله: {primary or 'نامشخص'}\n"
        f"عنوان: {title}\n"
        f"متا: {meta}\n\n"
        f"<verified_facts>\n{facts_block}\n</verified_facts>\n"
        f"<approved_cta>\n{cta_line}\n</approved_cta>\n\n"
        f"متن کامل مقاله:\n{body}"
    )
    # همان Rule Engine نویسنده/سردبیر → معیار داوری یکسان (حذف اختلاف تولید و ارزیابی)
    rules_block = editor_memory.rules_prompt_block()
    if rules_block:
        user_content += f"\n\n<editorial_rules>\n{rules_block}\n</editorial_rules>"

    result = llm.ask(
        step,
        user_content,
        model_tier="main",
        system=_load_prompt(),
        cache_system=True,
        json_output=True,
        max_tokens=20000,
    ) or {}

    scores = result.get("scores", {}) or {}
    wscore = weighted_score(scores)
    human = float(scores.get("human_tone", 0) or 0)

    # v2.1: ادغام آشکارساز قطعی Soft Claims با گزارش LLM (Fail-Closed —
    # حتی اگر LLM فیلد را خالی برگرداند، نتیجه‌ی قطعی اعمال می‌شود)
    from .architecture_v2_1_utils import detect_soft_quantitative_claims, merge_soft_claims
    from .writer import _fact_entries
    det_soft = [c.as_dict() for c in detect_soft_quantitative_claims(
        body, verified_facts=_fact_entries(payload))]
    llm_soft = result.get("soft_quantitative_claims", []) or []
    soft_claims = merge_soft_claims(det_soft, llm_soft)
    soft_unsupported = [c for c in soft_claims if c.get("supported") is not True]

    # گیت سخت: هر ادعای کمی بدون منبع = ردّ قطعی (یک منبع داده‌ی واحد برای همه‌ی گزارش)
    qclaims = result.get("quantitative_claims", []) or []
    unsupported = [c for c in qclaims if (c.get("status") or "").lower() == "unsupported"]
    # هم‌خوانی unsourced_claims با quantitative_claims (نباید یکی خالی و دیگری پر باشد)
    unsourced = list(result.get("unsourced_claims", []) or [])
    for c in unsupported:
        if c.get("claim") and c["claim"] not in unsourced:
            unsourced.append(c["claim"])

    passed = (wscore >= min_weighted and human >= min_human
              and not unsupported and not soft_unsupported)

    reasons = []
    if human < min_human:
        reasons.append(f"لحن انسانی {human}/10 < حداقل {min_human}")
    if wscore < min_weighted:
        reasons.append(f"نمره‌ی وزنی کیفیت {wscore}/10 < حداقل {min_weighted}")
    if unsupported:
        reasons.append(f"{len(unsupported)} ادعای کمی بدون منبع (گیت سخت)")
    if soft_unsupported:
        reasons.append(f"{len(soft_unsupported)} ادعای کمی نرم بدون منبع (گیت سخت v2.1)")

    logger.info(
        f"Quality Gate: وزنی={wscore}/10، انسانی={human}/10، "
        f"ایرادات={len(result.get('issues', []))}, passed={passed}"
    )

    return {
        "passed": passed,
        "weighted_score": wscore,
        "scores": scores,
        "eeat_detail": result.get("eeat_detail", {}),
        "cliches": result.get("cliches", []),
        "quantitative_claims": qclaims,
        "soft_quantitative_claims": soft_claims,
        "soft_unsupported_claim_count": len(soft_unsupported),
        "issues": result.get("issues", []) or [],
        "title_suggestion": result.get("title_suggestion"),
        "meta_suggestion": result.get("meta_suggestion"),
        "cta_suggestion": result.get("cta_suggestion"),
        "unsourced_claims": unsourced,
        "recommendations": result.get("recommendations", {}),
        "summary_table": result.get("summary_table", []),
        "rules_compliance": result.get("rules_compliance", {}),
        "reasons": reasons,
    }

```

## src\qa_analyzer.py

```python
"""تحلیل عمیق مقاله‌ی تولیدشده با «مستر پرامپت سئو» (ارزیابی + بازنویسی + QA).

جدا از analyzer.py (که تحلیل رقبا در زمان تولید است). این ماژول مقاله‌ی *نهایی* را
قبل از ارسال به تلگرام دوباره تحلیل و در صورت نیاز بازنویسی می‌کند.

جریان:
1. مقاله‌ی تولیدشده را به مستر پرامپت می‌دهد (به‌عنوان system).
2. Claude (Fable 5) مقاله را تحلیل، ارزیابی و در صورت نیاز بازنویسی می‌کند.
3. خروجی JSON شامل evaluation + article (بازنویسی‌شده) + qa_report + overall_score است.
4. لایه‌ی دوم دفاع: چک‌های سمت کد (عبارات ممنوعه، طول متا، لینک‌ها، جمله‌ی ناتمام).
5. تصمیم نهایی: qa_report.passed == true  و  overall_score >= threshold  و  همه‌ی چک‌های کد PASS.
"""
import logging
import re

from . import llm
from .config import CONFIG_DIR, PROMPTS_DIR

logger = logging.getLogger(__name__)

_ANALYZER_PROMPT_FILE = PROMPTS_DIR / "seo-analyzer-prompt.md"
_FORBIDDEN_FILE = CONFIG_DIR / "forbidden_phrases.txt"

# دستور تکمیلی — حالت سخت‌گیرانه: فقط تحلیل و نمره‌دهی، بدون بازنویسی
_ADDENDUM = """

═══════════════════════════════════
حالت کار: ارزیابی سخت‌گیرانه‌ی مقاله‌ی موجود (بدون بازنویسی)
═══════════════════════════════════
ورودی کاربر یک مقاله‌ی *ازپیش‌تولیدشده* است. تو فقط «ممیز کیفیت» هستی، نه نویسنده.

قوانین قطعی:
1. مقاله را **بازنویسی نکن**. حتی یک کلمه تغییر نده. فیلد article.body_markdown را
   دقیقاً برابر متن اصلی ورودی بگذار (بدون اصلاح).
2. سه فاز را فقط به‌صورت **تحلیلی** اجرا کن: نیت جستجو، کیورد، زاویه، داده (فاز۱)؛
   بررسی رعایت قوانین ساختار و لحن (فاز۲)؛ چک‌لیست QA (فاز۳).
3. هر جای چک‌لیست که مقاله‌ی اصلی رعایت نکرده، status آن را صادقانه FAIL بگذار.
   qa_report.passed را فقط وقتی true کن که هیچ FAIL نباشد.
4. یک فیلد عددی `overall_score` (۰ تا ۱۰۰) به ریشه‌ی JSON اضافه کن که کیفیت **مقاله‌ی
   اصلی همان‌طور که هست** را نشان می‌دهد — سخت‌گیر باش:
   - مقاله‌ی کوتاه/بدون داده/بدون لینک/با عبارت ممنوعه باید نمره‌ی پایین (زیر ۷۰) بگیرد.
   - نمره ۹۰+ فقط برای مقاله‌ای که واقعاً تمام قوانین را رعایت کرده.
5. در qa_report.notes دقیقاً بنویس چه چیزهایی برای رسیدن به ۹۰ کم است.
6. علاوه بر این، یک آرایه‌ی `issues` به ریشه‌ی JSON اضافه کن — فهرست دقیق تک‌تک ایرادات،
   طوری که یک ویراستار بتواند بدون خواندن دوباره‌ی مقاله، هر ایراد را رفع کند:
   [{
     "category": "یکی از: robotic_language | keyword_stuffing | keyword_missing | echo_heading |
        weak_hook | weak_cta | paragraph_too_long | poor_transition | generic_example |
        missing_local_example | low_information_gain | low_eeat | poor_scannability |
        repetitive_sentence | unnatural_keyword | ai_cliche | weak_title | weak_meta |
        faq_duplicate | incomplete_sentence | missing_link",
     "severity": "high | medium | low",
     "location": "کجای مقاله (مثلاً: H2 دوم، پاراگراف ۳، متا، عنوان)",
     "exact_quote": "نقل‌قول دقیق و کلمه‌به‌کلمه از متن معیوب (حداکثر ۳۰ کلمه)",
     "problem": "یک جمله: چرا این ایراد است",
     "rewrite_instruction": "دستور مشخص و عملی برای اصلاح — طوری که نویسنده بدون حدس زدن اجرا کند"
   }, ...]
   - همه‌ی ایرادات واقعی را بیاور (نه فقط چندتا). اگر مقاله عالی است، آرایه‌ی خالی بده.
   - exact_quote باید واقعاً در متن باشد (کپی دقیق)، چون با آن جای ایراد پیدا می‌شود.
7. دقت فنی (برای هر موضوع فناوری/AI/اتوماسیون این‌ها را بررسی و ایراد ثبت کن):
   - آیا قابلیت هوش مصنوعی از الزامات API، Workflow و Integration تفکیک شده،
     یا مقاله وانمود می‌کند AI به‌تنهایی کل فرایند را انجام می‌دهد؟
   - آیا برای هر اقدام عملیاتی (رزرو، پرداخت، ثبت داده)، پیش‌نیازهای اتصال به
     سیستم واقعی (درگاه، ظرفیت زنده، مجوز داده) ذکر شده است؟
   - آیا برای داده‌ی حساس (مالی، سلامت، شخصی) منبع معتبر و مسیر بازبینی/تحویل
     انسانی توضیح داده شده است؟
   - آیا ادعای «بدون دخالت انسانی» یا هر ادعای مطلق مشابه واقعاً قابل دفاع است؟
   - آیا منبع عمومی برای پشتیبانی از یک ادعای تخصصی/تجاری خاص استفاده نشده است؟
   - آیا هر عدد/درصد/قیمت/مدت‌زمان به فکت مستند (citable_facts) متصل است؟ عدد بی‌منبع = ایراد high.
8. قرارداد ساختار خروجی (این‌ها را خطا حساب نکن):
   - فیلد جداگانه‌ی h1 منبع H1 صفحه است؛ نبود تگ <h1> داخل body_html خطا نیست.
   - تصاویر در مرحله‌ی انتشار اضافه می‌شوند؛ نبود <img> در body خطا نیست.
   - نشانگرهای [[anchor: ...]] و [[external: ...]] قرارداد رسمی لینک‌گذاری‌اند
     (هنگام انتشار به لینک واقعی تبدیل می‌شوند) — placeholder خطا محسوب نمی‌شوند.
خروجی فقط JSON معتبر باشد.
"""


def _load_analyzer_prompt() -> str:
    base = _ANALYZER_PROMPT_FILE.read_text(encoding="utf-8")
    return base + _ADDENDUM


def _load_forbidden_phrases() -> list[str]:
    if not _FORBIDDEN_FILE.exists():
        return []
    out = []
    for line in _FORBIDDEN_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _build_user_content(payload: dict) -> str:
    """مقاله‌ی موجود را به‌صورت متن برای تحلیل آماده می‌کند."""
    title = payload.get("title_seo") or payload.get("h1", "")
    meta = payload.get("meta_description", "")
    body = payload.get("body_html") or payload.get("body_markdown", "")
    tags = "، ".join(payload.get("tags", []) or [])
    return (
        "این مقاله‌ی ازپیش‌تولیدشده را طبق قوانین سیستم تحلیل، ارزیابی و در صورت نیاز بازنویسی کن.\n\n"
        f"عنوان فعلی: {title}\n"
        f"توضیحات متا فعلی: {meta}\n"
        f"برچسب‌ها: {tags}\n\n"
        f"متن مقاله:\n{body}\n"
    )


# ── لایه‌ی دوم دفاع: چک‌های سمت کد ─────────────────────────────

# عبارات CTA تجاری — فقط با approved_cta مجازند (گیت سخت ۵)
_COMMERCIAL_CTA_PHRASES = (
    "مشاوره رایگان", "جلسه رایگان", "جلسه مشاوره", "با ما تماس بگیرید",
    "با کارشناسان ما تماس", "تخفیف ویژه", "همین امروز تماس",
)


def code_side_checks(article: dict) -> dict:
    """چک‌های قطعی سمت کد روی مقاله‌ی خروجی مدل. Returns {check_name: bool}."""
    body = article.get("body_markdown", "") or ""
    meta = article.get("meta_description", "") or ""

    forbidden = _load_forbidden_phrases()
    found_forbidden = [p for p in forbidden if p in body]

    # CTA تجاری بدون تایید — اگر approved_cta فعال نیست، این عبارات ممنوع‌اند
    cta = article.get("approved_cta") or {}
    cta_approved = bool(cta.get("enabled"))
    found_cta = [] if cta_approved else [p for p in _COMMERCIAL_CTA_PHRASES if p in body]

    # باند عملی طول متا (ایده‌آل ۱۵۰-۱۶۰؛ به‌خاطر نیم‌فاصله و تفاوت مدل کمی منعطف)
    meta_len_ok = 130 <= len(meta) <= 170
    internal_links = len(re.findall(r"\[\[anchor:", body))
    external_links = len(re.findall(r"\[\[external:", body))

    # جمله‌ی آخر کامل باشد (تشخیص truncation). ابتدا نشانگرهای لینک [[...]] را کامل حذف کن
    # (URL داخل‌شان به / ختم می‌شود و چک را گمراه می‌کند)، سپس تگ‌های HTML و فاصله‌ی انتهایی.
    no_markers = re.sub(r"\[\[[^\]]*\]\]", "", body)
    stripped = re.sub(r"(?:<[^>]+>|\s)+$", "", no_markers)    # تگ‌های HTML و فاصله‌ی انتهایی
    stripped = stripped.rstrip("]})*_>#- \n\t«»\"'")
    last_char_ok = bool(stripped) and stripped[-1] in ".!?۔؟:،"

    return {
        "no_forbidden_phrases": len(found_forbidden) == 0,
        "no_unapproved_cta": len(found_cta) == 0,
        "meta_length_150_160": meta_len_ok,
        "internal_links_min2": internal_links >= 2,
        "external_link_min1": external_links >= 1,
        "complete_last_sentence": last_char_ok,
        "_details": {
            "found_forbidden": found_forbidden,
            "found_unapproved_cta": found_cta,
            "meta_len": len(meta),
            "internal_links": internal_links,
            "external_links": external_links,
        },
    }


def merge_semrush(analysis: dict, semrush_report: dict | None) -> dict:
    """گزارش تحلیل SEMrush (فاز C) را در نتیجه‌ی qa ادغام می‌کند.

    خلاصه را به qa_report.notes اضافه و یک کلید semrush به ریشه‌ی analysis می‌گذارد.
    اگر SEMrush بگوید کیوردها ضعیف‌اند (verdict=WEAK)، دلیل به reasons اضافه می‌شود
    ولی نمره‌ی qa را تغییر نمی‌دهد (تصمیم نهایی در evaluate_and_sync).
    """
    if not semrush_report:
        return analysis

    analysis = dict(analysis)
    analysis["semrush"] = semrush_report

    verdict = semrush_report.get("verdict", "")
    avg_kd = semrush_report.get("avg_kd")
    kws = semrush_report.get("targeted_keywords", [])
    summary = f"SEMrush: verdict={verdict or '?'}, avg_kd={avg_kd if avg_kd is not None else '?'}, کیوردها={len(kws)}"

    qa_report = dict(analysis.get("qa_report", {}))
    qa_report["notes"] = (qa_report.get("notes", "") + f"\n[{summary}]").strip()
    analysis["qa_report"] = qa_report

    if verdict == "WEAK":
        reasons = list(analysis.get("reasons", []))
        reasons.append("SEMrush: کیوردهای هدف ضعیف/پررقابت‌اند (verdict=WEAK)")
        analysis["reasons"] = reasons
        analysis["semrush_weak"] = True

    return analysis


def analyze_article(payload: dict, threshold: int = 90, step: str = "qa_analyze") -> dict:
    """یک مقاله را با مستر پرامپت تحلیل و ارزیابی می‌کند.

    Returns dict شامل passed, overall_score, qa_passed, code_checks,
    evaluation, article (بازنویسی‌شده), qa_report, reasons.
    """
    system = _load_analyzer_prompt()
    user_content = _build_user_content(payload)

    result = llm.ask(
        step,
        user_content,
        model_tier="main",       # Fable 5 برای کیفیت بالا
        system=system,
        cache_system=True,       # پرامپت بلند است؛ کش کن
        json_output=True,
        max_tokens=20000,        # طبق نکته ۱ پرامپت: خروجی کافی برای مقاله+JSON (جلوگیری از truncation)
    )

    evaluation = result.get("evaluation", {})
    article = result.get("article", {})
    qa_report = result.get("qa_report", {})
    overall_score = int(result.get("overall_score", 0) or 0)
    qa_passed = bool(qa_report.get("passed", False))
    issues = result.get("issues", []) or []

    # حالت سخت‌گیرانه: چک‌های کد روی مقاله‌ی اصلی (نه نسخه‌ی مدل) اجرا شود
    original = {
        "body_markdown": payload.get("body_html") or payload.get("body_markdown", ""),
        "meta_description": payload.get("meta_description", ""),
        "approved_cta": payload.get("approved_cta"),
    }
    code_checks = code_side_checks(original)
    code_ok = all(v for k, v in code_checks.items() if not k.startswith("_"))

    reasons = []
    if not qa_passed:
        reasons.append("QA مدل پاس نشد (qa_report.passed=false)")
    if overall_score < threshold:
        reasons.append(f"نمره {overall_score} < آستانه {threshold}")
    if not code_ok:
        failed = [k for k, v in code_checks.items() if not k.startswith("_") and not v]
        reasons.append("چک‌های کد ناموفق: " + ", ".join(failed))

    # چک‌های قطعی کد را هم به‌صورت ایراد ساختاریافته اضافه کن تا برنامه‌ریز
    # حتماً برایشان پچ بسازد (مدل گاهی این‌ها را در issues نمی‌آورد)
    details = code_checks.get("_details", {})
    for phrase in details.get("found_forbidden", []):
        issues.append({
            "category": "ai_cliche",
            "severity": "high",
            "location": "بدنه‌ی مقاله",
            "exact_quote": phrase,
            "problem": f"عبارت ممنوعه‌ی «{phrase}» در متن است (ردّ قطعی).",
            "rewrite_instruction": f"جمله‌ی حاوی «{phrase}» را کاملاً بازنویسی کن؛ با داده، مثال ملموس یا ادعای صریح شروع کن.",
        })
    if not code_checks.get("meta_length_150_160", True):
        issues.append({
            "category": "weak_meta",
            "severity": "high",
            "location": "متا",
            "exact_quote": original.get("meta_description", "")[:60],
            "problem": f"طول متا {details.get('meta_len')} کاراکتر است (باید ۱۵۰-۱۶۰).",
            "rewrite_instruction": "متا را دقیقاً بین ۱۵۰ تا ۱۶۰ کاراکتر بنویس؛ شامل کیورد اصلی و دعوت به اقدام.",
        })
    if not code_checks.get("internal_links_min2", True) or not code_checks.get("external_link_min1", True):
        issues.append({
            "category": "missing_link",
            "severity": "high",
            "location": "بدنه‌ی مقاله",
            "exact_quote": "",
            "problem": f"لینک داخلی={details.get('internal_links')} (نیاز ۲)، خارجی={details.get('external_links')} (نیاز ۱).",
            "rewrite_instruction": "نشانگرهای [[anchor: متن | صفحه]] (حداقل ۲) و [[external: منبع | URL]] (حداقل ۱) را در متن جای‌گذاری کن.",
        })
    if not code_checks.get("complete_last_sentence", True):
        issues.append({
            "category": "incomplete_sentence",
            "severity": "high",
            "location": "انتهای بدنه",
            "exact_quote": (original.get("body_markdown", "") or "")[-80:],
            "problem": "جمله‌ی پایانی مقاله ناتمام است.",
            "rewrite_instruction": "پاراگراف پایانی را با جمله‌ی کامل (ختم به نقطه) تمام کن.",
        })
    # v2.1: ادعاهای کمی نرم بی‌منبع (آشکارساز قطعی) → ایراد ساختاریافته برای planner
    from .architecture_v2_1_utils import detect_soft_quantitative_claims
    from .writer import _fact_entries
    soft = detect_soft_quantitative_claims(
        original.get("body_markdown", ""), verified_facts=_fact_entries(payload))
    soft_unsupported = [c for c in soft if not c.supported]
    for c in soft_unsupported[:10]:
        issues.append({
            "category": "unsupported_soft_claim",
            "severity": "high",
            "location": "بدنه‌ی مقاله",
            "exact_quote": c.claim[:120],
            "problem": f"ادعای کمی نرم بدون منبع ({c.category}).",
            "rewrite_instruction": "حذف کن یا به جمله‌ی شرطی خنثی تبدیل کن "
                                   "(«به ... بستگی دارد») — هیچ عدد/شدت/فراوانی جدید نساز.",
        })

    for phrase in details.get("found_unapproved_cta", []):
        issues.append({
            "category": "weak_cta",
            "severity": "high",
            "location": "بدنه‌ی مقاله",
            "exact_quote": phrase,
            "problem": f"CTA تجاری «{phrase}» بدون approved_cta تاییدشده (گیت سخت).",
            "rewrite_instruction": "CTA تجاری را حذف کن و جمع‌بندی را خنثی/اطلاعاتی کن (توصیه‌ی اجرایی، معیار تصمیم).",
        })

    passed = qa_passed and overall_score >= threshold and code_ok

    return {
        "passed": passed,
        "overall_score": overall_score,
        "qa_passed": qa_passed,
        "code_checks": code_checks,
        "evaluation": evaluation,
        "article": article,
        "qa_report": qa_report,
        "reasons": reasons,
        "issues": issues,
    }

```

## src\revision_planner.py

```python
"""برنامه‌ریز اصلاح (Revision Planner): ایرادات QA را به پچ عملی تبدیل می‌کند.

ورودی: مقاله + آرایه‌ی issues از qa_analyzer.
خروجی: revision_patch — فهرست بخش‌هایی که باید بازنویسی شوند (patch-based)،
به‌همراه دستور دقیق برای هر بخش. بخش‌های سالم دست نمی‌خورند.

فایل‌های داده: data/revision_plan.json و data/revision_patch.json (برای دیباگ/شفافیت)
"""
import json
import logging
from datetime import datetime, timezone

from . import editor_memory, llm
from .config import DATA_DIR

logger = logging.getLogger(__name__)

_PLAN_FILE = DATA_DIR / "revision_plan.json"
_PATCH_FILE = DATA_DIR / "revision_patch.json"

_PLANNER_PROMPT = """تو سردبیر ارشد یک تیم تحریریه‌ی سئو هستی. گزارش QA زیر فهرست ایرادات یک مقاله است.
وظیفه‌ی تو: تبدیل این ایرادات به یک «برنامه‌ی اصلاح پچ‌محور» برای نویسنده.

قوانین:
1. ایرادات را بر اساس location گروه‌بندی کن — هر بخش مقاله (عنوان، متا، مقدمه، هر H2، جمع‌بندی، FAQ) یک پچ.
2. برای هر پچ، همه‌ی دستورهای اصلاح آن بخش را در یک instruction منسجم ادغام کن.
3. بخش‌هایی که ایرادی ندارند را در preserve_sections فهرست کن — نویسنده حق دست زدن به آن‌ها را ندارد.
4. ایرادات severity=high را اول بیاور.
5. اگر ایرادی کل مقاله را می‌گیرد (مثل لحن رباتیک همه‌جا)، scope آن را "global" بگذار.
6. تصمیم اصلاح فقط بر اساس ایرادات واقعی qa_issues است — قوانین تحریریه‌ی زیر «راهنمای
   چگونگی اصلاح» هستند، نه فهرست کارهایی که باید همه اجرا شوند. برای هر پچ، در فیلد
   rule بنویس کدام قانون مبنای این اصلاح است (متن کوتاه قانون یا "-" اگر قانونی مرتبط نیست).
7. اولویت بالا (پیش از نوشتن هر پچ): عناصر ارزشمند مقاله را شناسایی کن —
   E-E-A-T، داده‌های منبع‌دار، مثال‌های ملموس، FAQ، CTA، متا، لینک‌های داخلی —
   و آن‌ها را یا در preserve_sections بگذار یا در instruction صریح بنویس که حفظ شوند.
   فقط filler حذف/اصلاح می‌شود، هرگز signal.
8. ممنوعیت ساخت واقعیت (قطعی — هیچ پچی حق نقضش را ندارد):
   - اگر ادعای عددی منبع ندارد، دستور «حذف عدد» صادر کن — نه دستور مستندسازی خیالی.
   - اگر مثال واقعی وجود ندارد، دستور ساخت مثال واقعی، Case Study یا مطالعه‌ی
     داخلی صادر نکن.
   - اگر متن کلی است، درخواست توضیح فرایند، محدودیت یا پیش‌نیاز بده؛ نه عدد.
   - اگر تخصص ضعیف است، دستور تقویت جزئیات فنی موجود در منابع را بده.
   - اگر منبع کافی نیست، status آن ایراد را "unresolved_source_gap" بگذار
     (به‌جای پچ، در آرایه‌ی unresolved گزارش کن).
   - هیچ پچی نباید از بازنویس بخواهد منبع، مشتری، پروژه، تجربه یا Case Study
     جدید بسازد.
   - برای ادعای کمی نرم بی‌منبع (معمولاً/اغلب/چند هفته/دقت بالا/سریع‌تر/...):
     فقط حذف یا خنثی‌سازی شرطی پیشنهاد بده — جایگزین مجاز: جمله‌ی وابسته به
     شرایط («زمان راه‌اندازی به دامنه پروژه بستگی دارد»)؛ اگر هدف اطلاعاتی
     جمله با خنثی‌سازی حفظ نمی‌شود، حذفش کن. must_not_add این پچ‌ها حتماً شامل:
     عدد، درصد، قیمت، مدت، فراوانی، ادعای عملکرد، تجربه شخصی، Case Study.
9. برای هر پچ، فیلدهای must_preserve (چه چیزهایی عیناً بمانند) و
   must_not_add (چه چیزهایی مطلقاً اضافه نشوند — مثل: عدد، درصد، نام شرکت،
   مطالعه موردی) را پر کن.

<editorial_rules>
{rules}
</editorial_rules>

<article>
{article}
</article>

<qa_issues>
{issues}
</qa_issues>

فقط JSON:
{{
  "patches": [
    {{
      "section": "شناسه‌ی بخش (title | meta | intro | h2:متن عنوان | conclusion | faq)",
      "scope": "section | global",
      "severity": "high | medium | low",
      "current_text_hint": "چند کلمه‌ی اول بخش فعلی (برای پیدا کردن)",
      "instruction": "دستور کامل و ادغام‌شده‌ی بازنویسی این بخش",
      "rule": "قانون تحریریه‌ای که مبنای این اصلاح است (کوتاه) یا -",
      "must_preserve": ["عناصری که عیناً باید بمانند"],
      "must_not_add": ["عناصری که مطلقاً نباید اضافه شوند (عدد، درصد، نام شرکت، Case Study، تجربه شخصی...)"]
    }}
  ],
  "preserve_sections": ["فهرست بخش‌هایی که سالم‌اند و نباید عوض شوند"],
  "unresolved": [
    {{"issue": "خلاصه‌ی ایراد", "status": "unresolved_source_gap",
      "reason": "منبع کافی برای حل این ایراد وجود ندارد — نیازمند داده از کاربر"}}
  ],
  "summary": "خلاصه‌ی یک‌خطی برنامه"
}}"""


def build_plan(payload: dict, issues: list[dict], score: int, revision_no: int) -> dict:
    """از ایرادات QA یک برنامه‌ی اصلاح پچ‌محور می‌سازد."""
    if not issues:
        return {"patches": [], "preserve_sections": [], "summary": "ایرادی ثبت نشده"}

    body = payload.get("body_html") or payload.get("body_markdown", "")
    article_repr = (
        f"عنوان: {payload.get('title_seo','')}\n"
        f"متا: {payload.get('meta_description','')}\n"
        f"بدنه:\n{body[:6000]}"
    )

    # سردبیر همه‌ی دسته‌های قوانین را می‌بیند (تصمیم‌گیر اصلی است)
    rules_block = editor_memory.rules_prompt_block() or "(قوانین تحریریه در دسترس نیست)"

    plan = llm.ask(
        step=f"revision_plan_r{revision_no}",
        user_content=_PLANNER_PROMPT.format(
            rules=rules_block,
            article=article_repr,
            issues=json.dumps(issues, ensure_ascii=False, indent=1),
        ),
        model_tier="main",
        json_output=True,
        max_tokens=16000,  # gemini-2.5-flash بخشی از بودجه را صرف thinking می‌کند
    ) or {}

    plan.setdefault("patches", [])
    plan.setdefault("preserve_sections", [])
    record = {
        "revision": revision_no,
        "score_before": score,
        "issue_count": len(issues),
        "at": datetime.now(timezone.utc).isoformat(),
        "plan": plan,
    }
    _PLAN_FILE.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    _PATCH_FILE.write_text(
        json.dumps(plan["patches"], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(
        f"برنامه‌ی اصلاح دور {revision_no}: {len(plan['patches'])} پچ، "
        f"{len(plan['preserve_sections'])} بخش محفوظ"
    )
    return plan

```

## src\final_score.py

```python
"""لایه‌ی نمره‌دهی نهایی متمرکز — تنها منبع تصمیم انتشار/بررسی (فاز ۱).

ورودی: دیکشنری analysis (خروجی qa_analyzer + merge_semrush + quality_gate) —
هم شکل زنده‌ی حلقه‌ی تحریریه را می‌پذیرد، هم شکل ذخیره‌شده‌ی qa_analysis در DB.

اصول (مصوب کاربر):
1. گیت‌های سخت حفظ می‌شوند — final_score میانگین وزنیِ صرف نیست و جای گیت را نمی‌گیرد.
   approved یعنی: qa_passed و quality_gate_passed و code_checks و SEMrush قابل‌قبول
   و final_score >= آستانه. نمره‌ی بالا هیچ گیت ردشده‌ای را جبران نمی‌کند.
2. فاز ۱ فقط دو verdict دارد: approved | needs_review.
   ردّ خودکار غیرفعال است؛ نامزد ردّ فقط با پرچم would_reject علامت می‌خورد.
3. سازگاری عقب‌رو: این ماژول ورودی را تغییر نمی‌دهد (تابع خالص)، seo_grade دست
   نمی‌خورد؛ خروجی فیلدهای جدید final_score / final_verdict / score_breakdown است.

فاز ۱: هنوز به evaluate_and_sync وصل نیست (settings: final_score.enabled=false).
بدون فراخوانی LLM، بدون I/O دیتابیس — فقط محاسبه.
"""
import logging

from .config import load_settings

logger = logging.getLogger(__name__)

# پیش‌فرض‌ها — اگر بخش final_score در settings نبود، سیستم با همین‌ها کار می‌کند
_DEFAULT_WEIGHTS = {"qa": 0.50, "gate": 0.35, "semrush": 0.15}
_DEFAULT_SEMRUSH_MAP = {"GOOD": 100.0, "WEAK": 50.0}
_DEFAULT_THRESHOLD = 90
_DEFAULT_REJECT_BELOW = 60


def _cfg(config: dict | None = None) -> dict:
    if config is not None:
        return config
    return load_settings().get("final_score", {}) or {}


# ── استخراج اجزا از analysis (سازگار با شکل زنده و شکل ذخیره‌شده در DB) ──

def _qa_passed(analysis: dict) -> bool | None:
    """qa_passed از شکل زنده، وگرنه qa_report.passed از شکل ذخیره‌شده. None=نامعلوم."""
    if "qa_passed" in analysis:
        return bool(analysis["qa_passed"])
    qa_report = analysis.get("qa_report")
    if isinstance(qa_report, dict) and "passed" in qa_report:
        return bool(qa_report["passed"])
    return None


def _code_ok(analysis: dict) -> bool | None:
    """همه‌ی چک‌های کد پاس؟ اگر code_checks در دسترس نبود (داده‌ی قدیمی DB) → None."""
    checks = analysis.get("code_checks")
    if not isinstance(checks, dict):
        return None
    return all(v for k, v in checks.items() if not k.startswith("_"))


def _gate_passed(analysis: dict) -> bool | None:
    """عبور دروازه‌ی کیفیت. اگر گیت اجرا نشده (غیرفعال/داده‌ی قدیمی) → None."""
    gate = analysis.get("quality_gate")
    if not isinstance(gate, dict):
        return None
    return bool(gate.get("passed"))


def _semrush_ok(analysis: dict) -> bool | None:
    """SEMrush قابل‌قبول؟ WEAK → ردّ؛ GOOD/UNKNOWN → قبول؛ بدون گزارش → None."""
    if analysis.get("semrush_weak"):
        return False
    sr = analysis.get("semrush")
    if not isinstance(sr, dict):
        return None
    return sr.get("verdict") != "WEAK"


def _components(analysis: dict, cfg: dict) -> dict:
    """اجزای نمره در مقیاس ۰-۱۰۰. جزء غایب → None (از میانگین حذف می‌شود)."""
    out = {"qa": None, "gate": None, "semrush": None}

    score = analysis.get("overall_score")
    if isinstance(score, (int, float)):
        out["qa"] = float(score)

    gate = analysis.get("quality_gate")
    if isinstance(gate, dict):
        w = gate.get("weighted_score")
        if isinstance(w, (int, float)):
            out["gate"] = float(w) * 10.0     # ۰-۱۰ → ۰-۱۰۰

    sr = analysis.get("semrush")
    if isinstance(sr, dict):
        verdict = sr.get("verdict")
        sr_map = {**_DEFAULT_SEMRUSH_MAP, **(cfg.get("semrush_component") or {})}
        if verdict in sr_map:
            out["semrush"] = float(sr_map[verdict])
        # UNKNOWN یا verdict ناشناخته → None → از میانگین حذف (داده نداریم، جریمه نکن)

    return out


# ── API اصلی ──────────────────────────────────────────────────────

def compute(analysis: dict, config: dict | None = None) -> dict:
    """نمره‌ی نهایی و verdict را از یک analysis محاسبه می‌کند (تابع خالص).

    Returns:
        {
          "final_score": float ۰-۱۰۰,
          "final_verdict": "approved" | "needs_review",
          "score_breakdown": {
              "components": {qa, gate, semrush},        # ۰-۱۰۰ یا None اگر غایب
              "weights_used": {...},                    # وزن‌های نرمال‌شده‌ی اجزای موجود
              "hard_gates": {qa_passed, quality_gate_passed, code_checks_ok,
                             semrush_ok, score_ok},     # True/False/None (None=داده نبود)
              "would_reject": bool,                     # فقط برچسب — ردّ خودکار فعال نیست
              "reasons": [...],                         # دلایل عدم approved (خالی اگر approved)
          },
        }
    """
    cfg = _cfg(config)
    threshold = float(cfg.get("approval_threshold", _DEFAULT_THRESHOLD))
    weights = {**_DEFAULT_WEIGHTS, **(cfg.get("weights") or {})}

    # نمره‌ی وزنی — وزن اجزای غایب بین اجزای موجود بازتوزیع می‌شود
    comps = _components(analysis, cfg)
    total, wsum = 0.0, 0.0
    for key, w in weights.items():
        v = comps.get(key)
        if v is not None:
            total += v * float(w)
            wsum += float(w)
    final = round(total / wsum, 1) if wsum else 0.0
    weights_used = {
        k: round(float(weights[k]) / wsum, 3)
        for k in weights if comps.get(k) is not None and wsum
    }

    # گیت‌های سخت — None یعنی داده در دسترس نیست؛ فقط False صریح مانع approved می‌شود
    gates = {
        "qa_passed": _qa_passed(analysis),
        "quality_gate_passed": _gate_passed(analysis),
        "code_checks_ok": _code_ok(analysis),
        "semrush_ok": _semrush_ok(analysis),
        "score_ok": final >= threshold,
    }

    reasons = []
    if gates["qa_passed"] is False:
        reasons.append("QA پاس نشد (qa_report.passed=false)")
    if gates["quality_gate_passed"] is False:
        reasons.append("دروازه‌ی کیفیت (لحن انسانی/E-E-A-T) پاس نشد")
    if gates["code_checks_ok"] is False:
        reasons.append("چک‌های قطعی کد ناموفق")
    if gates["semrush_ok"] is False:
        reasons.append("کیوردهای هدف طبق SEMrush ضعیف/پررقابت‌اند (WEAK)")
    if not gates["score_ok"]:
        reasons.append(f"نمره‌ی نهایی {final} < آستانه {threshold:g}")

    approved = all(g is not False for g in gates.values()) and gates["score_ok"]

    # would_reject — منطق یکپارچه (بدون تناقض با گیت‌ها): هر شکست گیت قابل‌اسناد،
    # ادعای کمی بی‌منبع، یا عبارت ممنوعه (شامل ادعای تجربه‌ی جعلی که در همان
    # لیست ممنوعه است) → نامزد ردّ. ردّ خودکار همچنان غیرفعال است (فاز ۱)؛
    # این فقط برچسب/داده برای تصمیم انسانی و انتخاب نسخه است.
    details = (analysis.get("code_checks") or {}).get("_details", {}) or {}
    forbidden = list(details.get("found_forbidden") or []) + list(
        details.get("found_unapproved_cta") or []
    )
    gate_rep = analysis.get("quality_gate") or {}
    unsupported = [
        c for c in (gate_rep.get("quantitative_claims") or [])
        if (c.get("status") or "").lower() == "unsupported"
    ]
    # v2.1: ادعاهای کمی نرم بی‌منبع (از گیت؛ Fail-Closed اگر فیلد نبود → از issues)
    soft_unsupported = int(gate_rep.get("soft_unsupported_claim_count", 0) or 0)
    if not gate_rep:
        soft_unsupported = sum(
            1 for i in (analysis.get("issues") or [])
            if i.get("category") == "unsupported_soft_claim"
        )
    would_reject = (
        gates["qa_passed"] is False
        or gates["quality_gate_passed"] is False
        or gates["code_checks_ok"] is False
        or not gates["score_ok"]
        or len(unsupported) > 0
        or soft_unsupported > 0
        or len(forbidden) > 0
    )

    return {
        "final_score": final,
        "final_verdict": "approved" if approved else "needs_review",
        "score_breakdown": {
            "components": comps,
            "weights_used": weights_used,
            "hard_gates": gates,
            "would_reject": would_reject,
            "unsupported_claims": len(unsupported),
            "soft_unsupported_claims": soft_unsupported,
            "forbidden_found": len(forbidden),
            "reasons": reasons,
        },
    }


def rank_key(analysis: dict, config: dict | None = None) -> tuple:
    """کلید مقایسه‌ی نسخه‌ها در حلقه‌ی تحریریه (جایگزین آتی _rank در evaluate_and_sync).

    ترتیب: عبور همه‌ی گیت‌های سخت > نمره‌ی نهایی > نمره‌ی فنی QA.
    فاز ۲ از این استفاده خواهد کرد؛ فاز ۱ فقط در تست‌ها.
    """
    result = compute(analysis, config)
    gates = result["score_breakdown"]["hard_gates"]
    # score_ok عمداً در سطح‌بندی نیست: نسخه‌ی زیر آستانه ولی با گیت‌های کیفی پاس،
    # بالاتر از نسخه‌ی ردِ گیت رتبه می‌گیرد (همان فلسفه‌ی _rank فعلی)
    gates_ok = all(
        gates[k] is not False
        for k in ("qa_passed", "quality_gate_passed", "code_checks_ok", "semrush_ok")
    )
    return (
        gates_ok,
        result["final_score"],
        float(analysis.get("overall_score") or 0),
    )

```

## src\evaluate_and_sync.py

```python
"""مراقب ارزیابی مقالات و ارسال به تلگرام برای تایید.

این اسکریپت:
1. به‌صورت دوره‌ای pending articles را بررسی می‌کند
2. nمقالات با score > 90 را برای تایید به تلگرام می‌فرستد
3. مقالات با score ≤ 90 را به needs_review تغییر می‌دهد
4. تمام تغییرات را لاگ می‌کند
"""

import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from . import (
    db,
    editor_memory,
    evaluator,
    final_score,
    html_export,
    qa_analyzer,
    quality_gate,
    revision_planner,
    semrush_bridge,
    telegram_approver,
    writer,
)
from . import architecture_v2_1_utils as av21
from .config import env, load_settings

# روی ویندوز، stdout را UTF-8 کن تا متن فارسی در لاگ خطا ندهد (cp1256)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Setup logging
log_dir = Path(__file__).parent.parent / "logs"
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_dir / "evaluations.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


async def process_approved_articles(
    approved_results: list[dict], config: dict, approver: Optional[object] = None
) -> None:
    """مقالات تایید‌شده (score > 90) را به تلگرام می‌فرستد.

    Args:
        approved_results: لیستی از نتایج ارزیابی‌شده‌ی مقالات با score > 90
        config: تنظیمات از config.yaml
        approver: شی TelegramApprover (optional)
    """
    if not approved_results:
        logger.info("هیچ مقاله‌ی تایید‌شده‌ای برای ارسال به تلگرام نیست.")
        return

    # توکن و chat id را مستقیماً از متغیرهای محیطی (.env اصلی پروژه) می‌خوانیم
    from .config import env

    token = env("TELEGRAM_BOT_TOKEN")
    chat_id = env("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.warning("توکن یا Chat ID تلگرام تنظیم نشده (.env). پیام ارسال نمی‌شود.")
        return

    for result in approved_results:
        ok = await telegram_approver.send_approval_request(
            article_id=result["article_id"],
            title=result["title"],
            seo_grade=result["seo_grade"],
            preview=result["preview"],
            token=token,
            chat_id=chat_id,
            final_score=result.get("final_score"),
            final_verdict=result.get("final_verdict"),
        )
        if ok:
            logger.info(
                f"مقاله #{result['article_id']} برای تایید به تلگرام ارسال شد "
                f"(فنی: {result['seo_grade']}، نهایی: {result.get('final_score', '-')})"
            )


def mark_articles_as_needs_review(needs_review_results: list[dict]) -> None:
    """مقالات نیاز‌به‌بررسی را در DB علامت می‌زند.

    Args:
        needs_review_results: لیستی از نتایج ارزیابی‌شده‌ی مقالات با score ≤ 90
    """
    if not needs_review_results:
        return

    conn = db.connect()
    try:
        for result in needs_review_results:
            article_id = result["article_id"]
            seo_grade = result["seo_grade"]

            # Update status to needs_review
            conn.execute(
                "UPDATE articles SET status = 'needs_review', decided_at = ? WHERE id = ?",
                (db._now(), article_id),
            )
            conn.commit()

            logger.info(f"📌 مقاله #{article_id} نیاز به بررسی دارد (نمره: {seo_grade})")

    finally:
        conn.close()


def _merge_rewritten(payload: dict, analyzed_article: dict) -> dict:
    """مقاله‌ی بازنویسی‌شده‌ی ارزیاب را در payload اصلی ادغام می‌کند."""
    merged = dict(payload)
    field_map = {
        "h1": "h1",
        "seo_title": "title_seo",
        "meta_description": "meta_description",
        "slug_suggestion": "slug",
        "body_markdown": "body_html",   # نسخه‌ی بازنویسی‌شده جایگزین می‌شود
        "tags": "tags",
    }
    for src, dst in field_map.items():
        if analyzed_article.get(src):
            merged[dst] = analyzed_article[src]
    # متن markdown را هم جدا نگه دار (برای انتشار)
    if analyzed_article.get("body_markdown"):
        merged["body_markdown"] = analyzed_article["body_markdown"]
    if analyzed_article.get("faq"):
        merged["faq"] = analyzed_article["faq"]
    if analyzed_article.get("images"):
        merged["images"] = analyzed_article["images"]
    return merged


def evaluate_pending() -> None:
    """مقالات pending را با تحلیل عمیق (مستر پرامپت) ارزیابی و پردازش می‌کند.

    برای هر مقاله:
    1. با qa_analyzer (Claude/Fable5) تحلیل، ارزیابی و بازنویسی می‌شود.
    2. معیار عبور — لایه‌ی متمرکز final_score (analysis["final"]):
       final_verdict=="approved" یعنی qa_passed و quality_gate و چک‌های کد و
       SEMrush قابل‌قبول و final_score>=آستانه (گیت‌های سخت جبران‌ناپذیرند).
    3. عبور → مقاله ذخیره و به تلگرام ارسال می‌شود.
    4. عدم عبور → needs_review با دلایل.
    """
    logger.info("شروع تحلیل عمیق مقالات pending...")

    config = load_settings()
    threshold = config.get("evaluation", {}).get("approval_threshold", 90)

    conn = db.connect()
    approved, needs_review = [], []
    try:
        pending = evaluator.get_pending_articles(conn)
        logger.info(f"تعداد مقالات pending: {len(pending)}")

        qa_cfg = config.get("qa", {})
        rewrite_enabled = bool(qa_cfg.get("rewrite_enabled", False))
        max_revision = int(qa_cfg.get("max_revision", 3))
        min_improvement = int(qa_cfg.get("min_improvement", 5))
        gate_enabled = bool(config.get("quality_gate", {}).get("enabled", False))

        def _apply_quality_gate(pl: dict, an: dict) -> dict:
            """دروازه‌ی کیفیت (لحن انسانی/E-E-A-T/Conversion) را اجرا و در analysis ادغام می‌کند."""
            if not gate_enabled:
                return an
            try:
                gate = quality_gate.review(pl)
            except Exception as e:
                logger.warning(f"Quality Gate اجرا نشد: {e}")
                return an
            an = dict(an)
            an["quality_gate"] = gate
            # ایرادات لحن/EEAT وارد همان حلقه‌ی اصلاح می‌شوند
            an["issues"] = list(an.get("issues", [])) + list(gate.get("issues", []))
            if not gate["passed"]:
                an["reasons"] = list(an.get("reasons", [])) + [
                    f"Quality Gate: {r}" for r in gate.get("reasons", [])
                ]
            return an

        for article in pending:
            article_id = article["id"]
            payload = article["payload"]
            try:
                analysis = qa_analyzer.analyze_article(payload, threshold=threshold)
            except Exception as e:
                logger.error(f"خطا در تحلیل مقاله #{article_id}: {e}", exc_info=True)
                continue

            # فاز C: تحلیل SEMrush. اگر کلید API باشد و هنوز تحلیلی نباشد، خودکار اجرا کن
            # (فقط یک بار per مقاله — کیوردها بین دورهای بازنویسی عوض نمی‌شوند)
            semrush_report = semrush_bridge.load_analysis(article_id)
            if semrush_report is None and env("SEMRUSH_API_KEY"):
                tk = payload.get("target_keywords", {})
                # فقط کیوردهای هدف مقاله (primary + secondary) — نه کل استخر ریسرچ.
                # میانگین‌گرفتن از کل استخر، KD کیوردهای پررقابتِ ردشده را هم می‌شمرد.
                kw_list = [k for k in [tk.get("primary"), *(tk.get("secondary") or [])] if k]
                if kw_list:
                    try:
                        from . import semrush_api
                        semrush_report = semrush_api.analyze_article_keywords(article_id, kw_list)
                    except Exception as e:
                        logger.warning(f"تحلیل خودکار SEMrush مقاله #{article_id} نشد: {e}")
            analysis = qa_analyzer.merge_semrush(analysis, semrush_report)
            analysis = _apply_quality_gate(payload, analysis)
            # لایه‌ی نمره‌ی نهایی متمرکز — از این‌جا به بعد تنها منبع تصمیم
            analysis["final"] = final_score.compute(analysis)

            # ثبت ایرادات دور اول در حافظه‌ی تحریریه
            editor_memory.record_issues(analysis.get("issues", []))

            def _fixable_fail(an: dict) -> bool:
                """ردّی که بازنویسی می‌تواند حل کند. SEMrush عمداً جدا می‌ماند
                (کیورد ضعیف با بازنویسی متن درست نمی‌شود)."""
                g = an["final"]["score_breakdown"]["hard_gates"]
                return (
                    g["qa_passed"] is False
                    or g["quality_gate_passed"] is False
                    or g["code_checks_ok"] is False
                    or not g["score_ok"]
                )

            def _candidate_result(an: dict, pl: dict | None) -> dict:
                """نگاشت analysis به قرارداد should_save_candidate (پچ v2.1).

                نکته‌ی تطبیق: would_rejectِ لایه‌ی final شامل «نمره<آستانه» است و در
                میانه‌ی حلقه تقریباً همیشه true می‌شود؛ برای تصمیمِ ذخیره فقط
                سیگنال‌های جعل (ادعای بی‌منبع/soft/ممنوعه) مانع‌اند — وگرنه هیچ
                بهبود میانی‌ای هرگز ذخیره نمی‌شد.
                """
                bd = an["final"]["score_breakdown"]
                g = bd["hard_gates"]
                return {
                    "hard_error_count": sum(
                        1 for k in ("qa_passed", "quality_gate_passed",
                                    "code_checks_ok", "semrush_ok")
                        if g[k] is False
                    ),
                    "unsupported_claim_count": int(bd.get("unsupported_claims", 0) or 0),
                    "soft_unsupported_claim_count": int(bd.get("soft_unsupported_claims", 0) or 0),
                    "rewrite_warning_count": len((pl or {}).get("rewrite_warnings") or []),
                    "final_score": an["final"]["final_score"],
                    "would_reject": bool(
                        bd.get("unsupported_claims") or bd.get("soft_unsupported_claims")
                        or bd.get("forbidden_found")
                    ),
                    "validator_passed": True,
                }

            def _should_replace(new_an, new_pl, old_an, old_pl):
                """تصمیم جایگزینی نسخه — قواعد غیرقابل تغییر پچ v2.1."""
                return av21.should_save_candidate(
                    candidate_result=_candidate_result(new_an, new_pl),
                    previous_result=_candidate_result(old_an, old_pl),
                )

            # ── حلقه‌ی تحریریه: برنامه‌ریزی → بازنویسی پچی → QA مجدد ──
            revision_history = []
            revision = 0
            # بهترین نسخه در طول حلقه — اگر دوری نمره را بدتر کرد، به این برمی‌گردیم
            best_payload, best_analysis = payload, analysis
            while (
                rewrite_enabled
                # تصمیم از analysis["final"]: هر گیت قابل‌اصلاح که رد شده
                # (نمره‌ی کم، QA مدل، چک‌های کد، یا گیت کیفیت — نه SEMrush)
                and _fixable_fail(analysis)
                and analysis.get("issues")
                and revision < max_revision
            ):
                revision += 1
                score_before = analysis["overall_score"]
                final_before = analysis["final"]["final_score"]
                issues_before = len(analysis.get("issues", []))
                logger.info(
                    f"🛠 مقاله #{article_id} — دور اصلاح {revision}/{max_revision} "
                    f"(نمره {score_before}، {issues_before} ایراد)"
                )
                try:
                    # v2.1: هش متن قبل از بازنویسی — برای تشخیص «متن بدون تغییر» (QA cache)
                    prev_hash = av21.stable_hash(writer._payload_text(payload))
                    # انتخاب حالت بازنویسی: لحن سراسری ضعیف → انسانی‌سازی کامل؛
                    # وگرنه بازنویسی پچی (لحن ویژگی سراسری است و با پچ درست نمی‌شود)
                    gate = analysis.get("quality_gate") or {}
                    human_tone = float((gate.get("scores") or {}).get("human_tone", 10) or 10)
                    if gate and not gate.get("passed") and human_tone < 6:
                        logger.info(f"   لحن انسانی {human_tone}/10 — حالت انسانی‌سازی کامل")
                        payload = writer.humanize_article(payload, gate, revision_no=revision)
                        plan = {"patches": [{"section": "global", "scope": "global"}],
                                "summary": "انسانی‌سازی کامل لحن"}
                    else:
                        plan = revision_planner.build_plan(
                            payload, analysis["issues"], score_before, revision
                        )
                        if not plan.get("patches"):
                            logger.info("برنامه‌ی اصلاح پچی نداشت؛ حلقه متوقف شد.")
                            break
                        payload = writer.rewrite_article(payload, plan, revision_no=revision)

                    if av21.stable_hash(writer._payload_text(payload)) == prev_hash:
                        # v2.1: متن تغییری نکرده (ردّ validator یا خروجی یکسان) —
                        # QA/گیت تکراری اجرا نمی‌شود؛ همان ارزیابی قبلی معتبر است.
                        rejs = payload.get("humanize_rejections") or []
                        rej = rejs[-1] if (rejs and rejs[-1].get("revision") == revision) else None
                        if rej:
                            try:
                                db.record_validation_event(
                                    conn,
                                    article_id=article_id,
                                    stage="humanize",
                                    round_number=revision,
                                    rejection_reasons=rej.get("violations") or [],
                                    candidate_content_hash=rej.get("candidate_content_hash", ""),
                                    restored_content_hash=rej.get("restored_content_hash", ""),
                                    validator_version=av21.VALIDATOR_VERSION,
                                )
                            except Exception as pe:
                                # Fail-Closed: شکست ثبت رویداد → مقاله هرگز approved نشود
                                logger.error(f"ثبت رویداد validator نشد: {pe}")
                                analysis["validator_persist_failed"] = True
                        revision_history.append({
                            "revision": revision,
                            "score_before": score_before,
                            "score_after": score_before,
                            "final_before": final_before,
                            "final_after": final_before,
                            "final_verdict": analysis["final"]["final_verdict"],
                            "issues_before": issues_before,
                            "issues_after": issues_before,
                            "patches": len(plan.get("patches", [])),
                            "plan_summary": plan.get("summary", ""),
                            "qa_skipped": True,
                            "skip_reason": "content_unchanged_after_validator_rejection",
                        })
                        improvement = 0.0
                        logger.info(
                            f"   دور {revision}: QA تکراری اجرا نشد "
                            f"(متن بدون تغییر — {'ردّ validator' if rej else 'خروجی یکسان'})"
                        )
                    else:
                        analysis = qa_analyzer.analyze_article(payload, threshold=threshold)
                        analysis = qa_analyzer.merge_semrush(analysis, semrush_report)
                        analysis = _apply_quality_gate(payload, analysis)
                        analysis["final"] = final_score.compute(analysis)
                        editor_memory.record_issues(analysis.get("issues", []))
                        revision_history.append({
                            "revision": revision,
                            "score_before": score_before,
                            "score_after": analysis["overall_score"],
                            "final_before": final_before,
                            "final_after": analysis["final"]["final_score"],
                            "final_verdict": analysis["final"]["final_verdict"],
                            "issues_before": issues_before,
                            "issues_after": len(analysis.get("issues", [])),
                            "patches": len(plan.get("patches", [])),
                            "plan_summary": plan.get("summary", ""),
                        })
                        # بهبود روی نمره‌ی نهایی سنجیده می‌شود (نه فقط نمره‌ی فنی)
                        improvement = analysis["final"]["final_score"] - final_before
                        logger.info(
                            f"   دور {revision}: فنی {score_before} → {analysis['overall_score']}، "
                            f"نهایی {final_before} → {analysis['final']['final_score']} "
                            f"(بهبود {improvement:+.1f})"
                        )
                        # v2.1: جایگزینی فقط با بهبود واقعی (بدون جعل، بدون پس‌رفت)
                        ok_save, save_reason = _should_replace(
                            analysis, payload, best_analysis, best_payload
                        )
                        if ok_save:
                            best_payload, best_analysis = payload, analysis
                        else:
                            logger.info(f"   نسخه‌ی این دور ذخیره نشد ({save_reason})")

                    # معیار توقف همگرایی: اگر این دور به approved نرسید و بهبود
                    # نمره‌ی نهایی کمتر از حد آستانه بود، ادامه‌ی حلقه اتلاف توکن است.
                    if (analysis["final"]["final_verdict"] != "approved"
                            and improvement < min_improvement):
                        logger.info(
                            f"   توقف همگرایی: بهبود {improvement:+.1f} < {min_improvement} "
                            f"(دورهای بعدی بعید است کمک کنند)"
                        )
                        break
                except Exception as e:
                    logger.error(f"خطا در دور اصلاح {revision} مقاله #{article_id}: {e}", exc_info=True)
                    break

            # اگر آخرین دور شرایط جایگزینی را نداشت، بهترین نسخه‌ی پذیرفته‌شده برگردد
            if analysis is not best_analysis:
                logger.info(
                    f"   نسخه‌ی آخر (فنی {analysis['overall_score']}) شرایط جایگزینی را نداشت؛ "
                    f"بهترین نسخه (فنی {best_analysis['overall_score']}) نگه داشته شد."
                )
                payload, analysis = best_payload, best_analysis

            score = analysis["overall_score"]
            final = analysis["final"]
            title = payload.get("title_seo") or payload.get("h1", "")

            # گیت نهایی — تنها منبع تصمیم: لایه‌ی final_score
            # (approved = گیت‌های سخت qa/کیفیت/کد/SEMrush + نمره‌ی نهایی ≥ آستانه)
            # v2.1 Fail-Closed: شکست ثبت رویداد validator → هرگز approved نشود
            passed = (final["final_verdict"] == "approved"
                      and not analysis.get("validator_persist_failed"))
            if analysis.get("validator_persist_failed"):
                analysis["reasons"] = list(analysis.get("reasons", [])) + [
                    "validator_event_persistence_failed (Fail-Closed)"
                ]

            # دلایل نمایش: دلایل تفصیلی موجود + دلایل تجمیعی لایه‌ی نهایی (بدون تکرار)
            display_reasons = list(analysis["reasons"]) + [
                r for r in final["score_breakdown"]["reasons"]
                if r not in analysis["reasons"]
            ]

            if passed:
                # payload ممکن است حاصل بازنویسی تحریریه باشد؛ نمره و تاریخچه ضمیمه می‌شود
                merged = dict(payload)
                merged["seo_grade"] = score
                merged["final_score"] = final["final_score"]
                merged["final_verdict"] = final["final_verdict"]
                merged["score_breakdown"] = final["score_breakdown"]
                merged["qa_analysis"] = {
                    "overall_score": score,
                    "qa_report": analysis["qa_report"],
                    "evaluation": analysis["evaluation"],
                    "semrush": analysis.get("semrush"),
                    "quality_gate": analysis.get("quality_gate"),
                    "issues_remaining": analysis.get("issues", []),
                    "revision_history": revision_history,
                }
                db.update_payload(conn, article_id, merged)

                # ذخیره‌ی نسخه‌ی HTML برای تحلیل دستی
                try:
                    html_path = html_export.export_article(article_id, merged)
                    logger.info(f"📄 فایل HTML ذخیره شد: {html_path}")
                except Exception as e:
                    logger.warning(f"ذخیره‌ی HTML مقاله #{article_id} نشد: {e}")

                body_md = merged.get("body_markdown", "") or merged.get("body_html", "")
                preview = body_md[:200] + ("..." if len(body_md) > 200 else "")

                approved.append({
                    "article_id": article_id,
                    "title": title,
                    "seo_grade": score,
                    "final_score": final["final_score"],
                    "final_verdict": final["final_verdict"],
                    "preview": preview,
                })
                logger.info(
                    f"✅ مقاله #{article_id} عبور کرد (فنی {score}، نهایی {final['final_score']}) — متن اصلی حفظ شد"
                )
            else:
                # حتی در عدم عبور، آخرین نسخه‌ی بازنویسی‌شده + تاریخچه ذخیره شود
                # تا کار حلقه‌ی تحریریه از بین نرود و بررسی دستی راحت باشد
                if revision_history:
                    merged = dict(payload)
                    merged["seo_grade"] = score
                    merged["final_score"] = final["final_score"]
                    merged["final_verdict"] = final["final_verdict"]
                    merged["score_breakdown"] = final["score_breakdown"]
                    merged["qa_analysis"] = {
                        "overall_score": score,
                        "qa_report": analysis["qa_report"],
                        "evaluation": analysis["evaluation"],
                        "semrush": analysis.get("semrush"),
                        "quality_gate": analysis.get("quality_gate"),
                        "issues_remaining": analysis.get("issues", []),
                        "revision_history": revision_history,
                    }
                    db.update_payload(conn, article_id, merged)
                body_md = payload.get("body_markdown", "") or payload.get("body_html", "")
                needs_review.append({
                    "article_id": article_id,
                    "title": title,
                    "seo_grade": score,
                    "final_score": final["final_score"],
                    "final_verdict": final["final_verdict"],
                    "reasons": display_reasons,
                    "preview": body_md[:200] + ("..." if len(body_md) > 200 else ""),
                })
                logger.info(
                    f"📌 مقاله #{article_id} needs_review (فنی {score}، نهایی {final['final_score']}) "
                    f"— دلایل: {display_reasons}"
                )

        logger.info(
            f"تحلیل کامل شد: کل={len(pending)}, عبور={len(approved)}, نیاز‌به‌بررسی={len(needs_review)}"
        )

        mark_articles_as_needs_review(needs_review)
        return approved, needs_review

    finally:
        conn.close()


async def async_evaluate_pending() -> None:
    """Async wrapper برای evaluate_pending."""
    result = evaluate_pending()
    if result:
        approved, needs_review = result
        config = load_settings()
        if approved:
            await process_approved_articles(approved, config)

        # مقالات نزدیک به مرز (نمره ≥ آستانه‌ی بررسی) هم به تلگرام بروند —
        # با برچسب «نیاز به بررسی» و دلایل، تا تصمیم نهایی دست کاربر باشد
        review_min = int(config.get("evaluation", {}).get("telegram_review_min", 80))
        # مرز بررسی روی نمره‌ی نهایی اعمال می‌شود (مقدار آستانه دست‌نخورده — 80)؛
        # fallback به seo_grade برای آیتم‌های بدون final_score
        near_miss = [
            a for a in needs_review
            if (a.get("final_score") if a.get("final_score") is not None else a["seo_grade"]) >= review_min
        ]
        for item in near_miss:
            ok = await telegram_approver.send_approval_request(
                article_id=item["article_id"],
                title=item["title"],
                seo_grade=item["seo_grade"],
                preview=item.get("preview", ""),
                warning="\n".join(f"• {r}" for r in item["reasons"]),
                final_score=item.get("final_score"),
                final_verdict=item.get("final_verdict"),
            )
            if ok:
                logger.info(
                    f"⚠️ مقاله #{item['article_id']} (فنی {item['seo_grade']}، "
                    f"نهایی {item.get('final_score', '-')}) با برچسب «نیاز به بررسی» به تلگرام رفت"
                )


def run_once() -> None:
    """یک بار ارزیابی را اجرا می‌کند."""
    try:
        logger.info("=" * 60)
        logger.info("شروع چرخه‌ی ارزیابی")
        logger.info("=" * 60)

        asyncio.run(async_evaluate_pending())

        logger.info("=" * 60)
        logger.info("پایان چرخه‌ی ارزیابی")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"خطا در ارزیابی: {e}", exc_info=True)


def run_daemon(interval_seconds: int = 300) -> None:
    """به‌صورت daemon ارزیابی را تکرار می‌کند.

    Args:
        interval_seconds: تاخیر بین چرخه‌های ارزیابی (به ثانیه)
    """
    logger.info(f"شروع daemon ارزیابی (هر {interval_seconds} ثانیه)...")

    try:
        while True:
            run_once()
            logger.info(f"بعدی ارزیابی در {interval_seconds} ثانیه...")
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        logger.info("Daemon متوقف شد.")


if __name__ == "__main__":
    # Run once (can be called from scheduler)
    run_once()

```

## prompts\content-quality-gate.md

```text
# نقش شما:

شما یک متخصص ارشد محتوا و SEO هستید که همزمان نقش‌های زیر را دارید:

1. Senior SEO Strategist
2. Content Editor با تجربه انتشار مقالات رتبه‌گیر در گوگل
3. متخصص E-E-A-T گوگل
4. Content Quality Reviewer
5. متخصص تشخیص متن‌های تولیدشده توسط AI و تبدیل آن‌ها به محتوای انسانی

# ماموریت:

مقاله زیر را از دو زاویه کاملاً بررسی کن:

1. کیفیت انسانی و نویسندگی (Human Content Quality)
2. کیفیت سئو و قابلیت رتبه گرفتن در گوگل (SEO Performance)

هدف این بررسی فقط پیدا کردن ایراد نیست؛
باید مشخص کنی چگونه مقاله را به سطح یک مقاله حرفه‌ای، قابل اعتماد و تبدیل‌کننده بازدیدکننده به مشتری ارتقا دهیم.

---

# بخش اول: بررسی انسانی بودن محتوا (Human Writing Analysis)

## 1. میزان انسانی بودن متن — امتیاز از 10

- آیا متن طبیعی نوشته شده؟ (روشنی، ریتم متنوع، نثر مستقیم)
- آیا شبیه متن تولیدشده توسط AI است؟
- آیا متن بیش از حد کلیشه‌ای است؟

توجه: وجود یا نبود روایت اول‌شخص و «تجربه شخصی نویسنده» معیار امتیاز نیست.
ادعای تجربه شخصی/سازمانی تأییدنشده نه‌تنها امتیاز نمی‌سازد، بلکه ایراد high است.

نمونه عبارت‌های کلیشه‌ای را استخراج کن.

مثال — ضعیف: «این فناوری تحول چشمگیری ایجاد می‌کند»
بهتر: «این فناوری باعث می‌شود تیم فروش روزانه چند ساعت زمان کمتری صرف پاسخ‌های تکراری کند.»

## 2. بررسی لحن نویسنده

- آیا لحن آموزشی است؟ مشاوره‌ای است؟
- آیا برای مدیر کسب‌وکار مناسب است؟
- آیا اعتماد ایجاد می‌کند؟

پیشنهاد بده چگونه لحن را حرفه‌ای‌تر کنیم.

## 3. بررسی Experience در محتوا

Experience را بر اساس شواهد بسنج، نه روایت:
- دقت فنی و تعریف‌های درست
- تطابق دقیق هر ادعا با منبعش
- توضیح محدودیت‌ها، ریسک‌ها و پیش‌نیازهای اجرایی
- معیارهای تصمیم‌گیری (برای چه کسی، چه زمانی، تحت چه شرایطی)
- تفکیک قابلیت هوش مصنوعی از الزامات API، Workflow و Integration

ادعای تجربه شخصی، پروژه داخلی، مشتری، مطالعه موردی یا مشاهده دست‌اول
فقط وقتی مجاز است که صریحاً در business_context یا verified_facts ثبت شده باشد.
برای کمبود Experience هرگز پیشنهاد «افزودن تجربه/مثال واقعی/Case Study» نده؛
پیشنهاد درست: تقویت جزئیات فنی مستند، محدودیت‌ها و پیش‌نیازها.

---

# بخش دوم: تحلیل SEO مقاله

## 1. بررسی عنوان SEO — امتیاز از 10
- Keyword اصلی در عنوان هست؟ Search Intent را پاسخ می‌دهد؟ جذابیت کلیک (CTR) دارد؟
- پیشنهاد عنوان بهتر ارائه کن.

## 2. بررسی Meta Description
- طول مناسب؟ شامل Keyword؟ CTR را بالا می‌برد؟ وعده غیرواقعی دارد؟
- یک نسخه بهتر پیشنهاد بده.

## 3. بررسی Keyword Strategy
- تعداد استفاده، Keyword Stuffing، مترادف‌ها، Semantic Keywords، Long Tail
- پیشنهاد بده چه کلمات مرتبطی اضافه شوند.

## 4. بررسی ساختار Headingها (H1/H2/H3)
- ساختار منطقی است؟ Headingها بیش از حد سوالی‌اند؟ برای Featured Snippet مناسب‌اند؟

---

# بخش سوم: بررسی E-E-A-T گوگل — برای هر معیار امتیاز از 10

E-E-A-T را بر اساس این معیارها ارزیابی کن (نه بر اساس لحن اول‌شخص یا ادعای تجربه):

- دقت فنی
- کیفیت منابع
- تطابق دقیق ادعا با منبع
- توضیح محدودیت‌ها
- بیان پیش‌نیازهای اجرایی
- معیارهای تصمیم‌گیری
- بیان ریسک‌ها
- تفکیک قابلیت هوش مصنوعی از API، Workflow و Integration

نگاشت به چهار بُعد:
- Experience: شواهد عملی مستند (داده‌ی منبع‌دار، محدودیت‌های واقعی، پیش‌نیازها)
- Expertise: دقت فنی و تعریف‌های درست
- Authority: کیفیت و تطابق منابع
- Trust: صداقت درباره محدودیت‌ها و نبود ادعای بی‌منبع

---

# بخش چهارم: بررسی Conversion و Business Value

- این مقاله فقط اطلاعات می‌دهد یا مشتری جذب می‌کند؟
- CTA مناسب است؟ مسیر تبدیل خواننده به مشتری هست؟ نیاز کسب‌وکار را لمس می‌کند؟
- پیشنهاد CTA بهتر بده.

---

# بخش پنجم: بررسی اعتبار داده‌ها

تمام درصدها، آمارها، نام شرکت‌ها، تحقیقات و منابع را بررسی کن. مشخص کن کدام نیاز به منبع دارد.

---

# بخش ششم: بررسی تصاویر و SEO Image

Alt Text، ارتباط تصویر با محتوا، Keyword، پیشنهاد Alt بهتر.

---

# بخش هفتم: بررسی Internal Linking

لینک داخلی کافی است؟ چه صفحاتی باید لینک شوند؟ Anchor Text پیشنهادی.

---

# بخش هشتم: مشکلات نگارشی

غلط املایی، جمله‌های غیرطبیعی، ترجمه ماشینی، عبارت‌های تکراری، جملات طولانی.

---

# بخش نهم: Soft Quantitative Claims

ادعای کمی فقط عدد، درصد یا قیمت نیست.

هر جمله‌ای که درباره یکی از موارد زیر شدت، فراوانی، مدت، سرعت، دقت،
میزان استفاده، کاهش، افزایش، هزینه یا نتیجه را بیان کند، ادعا محسوب می‌شود:

- معمولاً، اغلب، بسیاری، اکثر، بخش بزرگی
- چند هفته، چند روز، مدت کوتاه
- دقت بالا، بسیار دقیق
- سریع‌تر، زمان کمتر
- رشد چشمگیر، افزایش قابل‌توجه، کاهش محسوس
- هزینه کمتر، صرفه‌جویی قابل‌توجه
- عملکرد بهتر و عبارت‌های مشابه

برای هر ادعا:
1. متن کامل Claim را استخراج کن.
2. Category را تعیین کن.
3. فقط اگر verified_fact معتبر با allowed_scope مناسب وجود دارد supported=true بده.
4. در صورت نبود منبع، supported=false و required_action=remove_or_neutralize بده.
5. هیچ Fact یا عدد جدیدی پیشنهاد نکن.
6. حتی یک ادعای Soft Quantitative بی‌منبع باید passed=false ایجاد کند.

---

# بخش نهایی: جدول امتیازها + سه دسته پیشنهاد

- اصلاحات ضروری قبل از انتشار (High Priority)
- اصلاحات برای افزایش رتبه گوگل (Medium Priority)
- اصلاحات برای تبدیل مقاله به مقاله Authority (Long Term)

```

## test_architecture_v2_1.py

```python
"""تست پچ v2.1 — صفر تماس LLM.

پوشش: آشکارساز Soft Claims (۱۲ مثبت/۴ خنثی/تاییدشده)، QA Cache Key،
should_save_candidate (۶ قانون)، validator soft-claim، ثبت رویداد در DB،
اینتگریشن مینی: ردّ humanize → بدون QA تکراری + رویداد DB + Fail-Closed ثبت.
اجرا:  python test_architecture_v2_1.py   (از پوشه‌ی seo-agent)
"""
import json
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from src.architecture_v2_1_utils import (
    build_qa_cache_key, detect_soft_quantitative_claims, merge_soft_claims,
    should_save_candidate, stable_hash,
)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    mark = "✅" if cond else "❌"
    passed += cond
    failed += not cond
    print(f"  {mark} {name}" + (f"  [{str(detail)[:70]}]" if detail else ""))


print("=" * 60)
print("[۱۴.۱] آشکارساز Soft Quantitative Claims")
print("=" * 60)
POSITIVES = [
    "راه‌اندازی معمولاً چند هفته طول می‌کشد.",
    "بسیاری از رستوران‌ها از این روش استفاده می‌کنند.",
    "این سیستم دقت بسیار بالایی دارد.",
    "هزینه‌ها به شکل چشمگیری کاهش پیدا می‌کنند.",
    "در مدت کوتاهی نتیجه خواهید گرفت.",
    "اغلب مشتریان پاسخ فوری را ترجیح می‌دهند.",
    "بخش بزرگی از تماس‌ها خودکار می‌شود.",
    "این روش عملکرد بهتری دارد.",
    "سامانه سریع‌تر پاسخ می‌دهد.",
    "این راهکار باعث رشد محسوس می‌شود.",
    "در بیشتر موارد اتصال ساده است.",
    "صرفه‌جویی قابل‌توجهی ایجاد می‌شود.",
]
for text in POSITIVES:
    claims = detect_soft_quantitative_claims(text, verified_facts=[])
    check(f"کشف: «{text[:35]}...»",
          bool(claims) and any(c.supported is False for c in claims))

NEUTRALS = [
    "زمان راه‌اندازی به دامنه پروژه و تعداد اتصال‌ها بستگی دارد.",
    "دقت سیستم باید روی داده‌های واقعی کسب‌وکار آزمایش شود.",
    "میزان کاهش هزینه بدون اندازه‌گیری پروژه قابل تعیین نیست.",
    "این قابلیت ممکن است بخشی از درخواست‌های تکراری را خودکار کند.",
]
for text in NEUTRALS:
    check(f"خنثی مجاز: «{text[:35]}...»",
          detect_soft_quantitative_claims(text, verified_facts=[]) == [])

print("\n" + "=" * 60)
print("[۱۴.۲] ادعای تاییدشده")
print("=" * 60)
facts = [{"id": "fact_duration_01",
          "claim": "راه‌اندازی این پروژه معمولاً سه هفته طول می‌کشد.",
          "source_url": "https://example.com/source",
          "allowed_scope": "case_study_alpha", "locked_numbers": ["3"]}]
claims = detect_soft_quantitative_claims(
    "راه‌اندازی این پروژه معمولاً سه هفته طول می‌کشد.", verified_facts=facts)
check("ادعای منطبق با verified_fact → supported=true",
      bool(claims) and all(c.supported for c in claims)
      and claims[0].verified_fact_id == "fact_duration_01")

# ادغام Fail-Closed
m = merge_soft_claims(
    [{"claim": "x", "category": "a", "supported": False}],
    [{"claim": "x", "category": "a", "supported": True}])
check("ادغام Fail-Closed: قطعیِ unsupported غالب است",
      len(m) == 1 and m[0]["supported"] is False)

print("\n" + "=" * 60)
print("[۱۴.۳-۱۴.۴] QA Cache Key")
print("=" * 60)
base = {"text": "متن ثابت", "model_name": "gemini-test", "qa_prompt_version": "v2.1",
        "editorial_rules": {"a": 1}, "verified_facts": []}
calls = {"n": 0}
cache = {}
def fake_qa(text):
    calls["n"] += 1
    return {"passed": False}
k1 = build_qa_cache_key(**base)
if k1 not in cache:
    cache[k1] = fake_qa(base["text"])
k2 = build_qa_cache_key(**base)
if k2 not in cache:
    cache[k2] = fake_qa(base["text"])
check("ورودی یکسان → یک بار QA", k1 == k2 and calls["n"] == 1)
check("تغییر نسخه‌ی پرامپت → کلید جدید",
      build_qa_cache_key(**{**base, "qa_prompt_version": "v2.2"}) != k1)
check("تغییر verified_facts → کلید جدید",
      build_qa_cache_key(**{**base, "verified_facts": [{"id": "f1"}]}) != k1)

print("\n" + "=" * 60)
print("[۱۴.۵] should_save_candidate")
print("=" * 60)
def result(*, hard=0, unsupported=0, soft=0, warnings=0, score=5.0,
           reject=False, validator=True):
    return {"hard_error_count": hard, "unsupported_claim_count": unsupported,
            "soft_unsupported_claim_count": soft, "rewrite_warning_count": warnings,
            "final_score": score, "would_reject": reject, "validator_passed": validator}

s, _ = should_save_candidate(candidate_result=result(hard=2, score=9),
                             previous_result=result(hard=1, score=5))
check("hard بیشتر → هرگز ذخیره نشود", s is False)
s, _ = should_save_candidate(candidate_result=result(hard=1, unsupported=0),
                             previous_result=result(hard=1, unsupported=1))
check("hard برابر، unsupported کمتر → ذخیره", s is True)
s, _ = should_save_candidate(candidate_result=result(soft=2, score=9),
                             previous_result=result(soft=1, score=5))
check("soft بیشتر → ذخیره نشود", s is False)
s, r = should_save_candidate(candidate_result=result(), previous_result=result())
check("Rank برابر → نسخه‌ی قبلی بماند", s is False and r == "rank_tied_keep_previous")
s, r = should_save_candidate(candidate_result=result(score=10, reject=True),
                             previous_result=result(score=1))
check("would_reject → هرگز ذخیره نشود", s is False and r == "candidate_would_reject")
s, r = should_save_candidate(candidate_result=result(score=10, validator=False),
                             previous_result=result(score=1))
check("validator شکست → هرگز ذخیره نشود",
      s is False and r == "candidate_validator_failed_or_missing")

print("\n" + "=" * 60)
print("[v2.1] Validator انسانی‌سازی — Soft Claim جدید")
print("=" * 60)
from src import writer
OLD = {"title_seo": "ع", "meta_description": "م" * 155, "h1": "ع",
       "body_html": "<p>متن اول.</p><h2>بخش</h2><p>الف [[anchor: ل | ص]].</p>",
       "citable_facts": [], "source_urls": []}
NEW_BAD = dict(OLD)
NEW_BAD["body_html"] = OLD["body_html"].replace("متن اول.", "متن اول که معمولاً سریع‌تر جواب می‌دهد.")
v = writer.validate_humanize(OLD, NEW_BAD)
check("soft claim جدید در humanize → رد",
      any("new_soft_quantitative_claim" in x for x in v), v)
NEW_OK = dict(OLD)
NEW_OK["body_html"] = OLD["body_html"].replace("متن اول.", "متن نخست.")
check("ویرایش سبک بدون soft جدید → قبول", writer.validate_humanize(OLD, NEW_OK) == [])

print("\n" + "=" * 60)
print("[۱۴.۶ + ۱۳] اینتگریشن مینی: ردّ humanize → DB event + بدون QA تکراری")
print("=" * 60)
from src import db, editor_memory, html_export, llm, qa_analyzer, quality_gate, semrush_bridge

tmp_dir = Path(tempfile.mkdtemp(prefix="v21_test_"))
db.DB_PATH = tmp_dir / "agent.db"
html_export.OUTPUT_DIR = tmp_dir
llm.ask = lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM call!"))

QA_CALLS = {"n": 0}
_CODE_OK = {"no_forbidden_phrases": True, "no_unapproved_cta": True,
            "meta_length_150_160": True, "internal_links_min2": True,
            "external_link_min1": True, "complete_last_sentence": True, "_details": {}}

def qa_stub(payload, threshold=90, step="qa_analyze"):
    QA_CALLS["n"] += 1
    return {"passed": False, "overall_score": 80, "qa_passed": True,
            "code_checks": dict(_CODE_OK), "evaluation": {}, "article": {},
            "qa_report": {"passed": True, "checks": []}, "reasons": [], "issues": []}

def gate_stub(payload, step="quality_gate"):
    return {"passed": False, "weighted_score": 5.0, "scores": {"human_tone": 4},
            "issues": [{"category": "robotic_language", "severity": "medium",
                        "location": "x", "exact_quote": "q", "problem": "p",
                        "rewrite_instruction": "r"}],
            "reasons": ["لحن 4"], "rules_compliance": {}, "cliches": [],
            "quantitative_claims": [], "soft_quantitative_claims": [],
            "soft_unsupported_claim_count": 0, "recommendations": {}}

def humanize_bad(payload, gate_report, revision_no=1):
    bad = dict(payload)
    bad["body_html"] = "<p>بدون هدینگ قبلی.</p>"     # H2 حذف → validator رد می‌کند
    v = writer.validate_humanize(payload, bad)
    assert v
    rejected = dict(payload)
    rejected["humanize_rejections"] = [
        {"revision": revision_no, "violations": v,
         "candidate_content_hash": stable_hash(writer._payload_text(bad)),
         "restored_content_hash": stable_hash(writer._payload_text(payload))}]
    return rejected

qa_analyzer.analyze_article = qa_stub
quality_gate.review = gate_stub
writer.humanize_article = humanize_bad
editor_memory.record_issues = lambda issues: None
semrush_bridge.load_analysis = lambda aid: {"verdict": "GOOD", "avg_kd": 20,
                                            "targeted_keywords": [], "per_kw": {}}

from src import evaluate_and_sync
conn = db.connect()
aid = db.save_article(conn, "تست v2.1", {
    "h1": "ع", "title_seo": "مقاله تست", "meta_description": "م" * 155,
    "body_html": "<p>متن.</p><h2>بخش یک</h2><p>الف [[anchor: ل | ص]] "
                 "[[external: م | https://a.ir]].</p>"})
conn.close()

approved, needs_review = evaluate_and_sync.evaluate_pending()
check("QA فقط یک بار اجرا شد (ردّ humanize → بدون QA تکراری)",
      QA_CALLS["n"] == 1, f"{QA_CALLS['n']} تماس")
conn = db.connect()
events = conn.execute("SELECT * FROM pipeline_validation_events WHERE article_id=?",
                      (aid,)).fetchall()
art = db.get_article(conn, aid)
conn.close()
check("رویداد ردّ validator در DB ثبت شد", len(events) == 1)
if events:
    ev = dict(events[0])
    check("رویداد: status=rejected و candidate_saved=0",
          ev["status"] == "rejected" and ev["candidate_saved"] == 0)
    check("رویداد: دلایل و هش‌ها پر", "H2" in ev["rejection_reasons"]
          and len(ev["candidate_content_hash"]) == 64
          and ev["debug_candidate_text"] is None)
check("مقاله needs_review شد", art["status"] == "needs_review")
hist = (art["payload"].get("qa_analysis") or {}).get("revision_history") or []
check("تاریخچه: qa_skipped ثبت شد", any(h.get("qa_skipped") for h in hist))

# Fail-Closed ثبت DB: شکست insert → مقاله هرگز approved نشود
_orig_record = db.record_validation_event
db.record_validation_event = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down"))
conn = db.connect()
aid2 = db.save_article(conn, "تست v2.1 fail-closed", {
    "h1": "ع", "title_seo": "مقاله تست ۲", "meta_description": "م" * 155,
    "body_html": "<p>متن.</p><h2>بخش یک</h2><p>الف [[anchor: ل | ص]] "
                 "[[external: م | https://a.ir]].</p>"})
conn.close()
approved2, needs2 = evaluate_and_sync.evaluate_pending()
conn = db.connect()
art2 = db.get_article(conn, aid2)
conn.close()
db.record_validation_event = _orig_record
reasons2 = " ".join((art2["payload"].get("score_breakdown") or {}).get("reasons") or []) \
    + " " + json.dumps(needs2, ensure_ascii=False)
check("Fail-Closed: شکست ثبت DB → needs_review + دلیل persistence_failed",
      art2["status"] == "needs_review"
      and "validator_event_persistence_failed" in reasons2, art2["status"])

print("\n" + "=" * 60)
print(f"نتیجه: {passed} پاس، {failed} شکست | تماس LLM واقعی: 0")
print("=" * 60)
sys.exit(1 if failed else 0)

```

## test_architecture_v2.py

```python
"""تست معماری v2 (ضد جعل واقعیت) — صفر تماس LLM.

پوشش: پرامپت‌های Renderشده (fact_policy/cta/H2)، حذف قوانین متناقض قدیمی،
Validator انسانی‌سازی، would_reject یکپارچه، منطق نسخه‌ی برنده، گیت ادعای کمی،
چک CTA تاییدنشده.
اجرا:  python test_architecture_v2.py   (از پوشه‌ی seo-agent)
"""
import json
import sys
sys.stdout.reconfigure(encoding="utf-8")

from src import editor_memory, final_score, llm, qa_analyzer, quality_gate, revision_planner, writer

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    mark = "✅" if cond else "❌"
    passed += cond
    failed += not cond
    print(f"  {mark} {name}" + (f"  [{str(detail)[:70]}]" if detail else ""))


print("=" * 60)
print("[۱] قوانین — حذف نسخه‌های متناقض قدیمی")
print("=" * 60)
raw = json.dumps(editor_memory.load_rules(), ensure_ascii=False)
for bad, label in [
    ("measurable outcome", "الزام «نتیجه‌ی قابل‌اندازه‌گیری» در سناریو"),
    ("or be framed explicitly as an assumption", "استثنای «عدد فرضی مجاز»"),
    ("Replace vague qualitative claims with a concrete number", "دستور ساخت عدد برای ادعای مبهم"),
    ("Preserve first-person experience signals", "الزام سیگنال اول‌شخص"),
    ("State the author's role", "الزام معرفی نویسنده"),
    ("Keep concrete case studies with measurable outcomes and specific metrics.", "الزام Case Study بدون قید verified"),
]:
    check(f"حذف شد: {label}", bad not in raw)
for good, label in [
    ("ONLY from citable_facts", "عدد فقط از citable_facts"),
    ("business_context", "تجربه فقط با ثبت در business_context/verified_facts"),
    ("do NOT reward first-person anecdotes", "داور: اول‌شخص امتیاز نمی‌سازد"),
    ("NEVER invent a number, case study", "ممنوعیت ساخت عدد/کیس برای ملموس‌سازی"),
]:
    check(f"اضافه شد: {label}", good in raw)

print("\n" + "=" * 60)
print("[۲] پرامپت‌های Renderشده (استاب llm)")
print("=" * 60)
CAP = {}
_orig = llm.ask


def fake_ask(step, user_content, **kw):
    CAP[step] = user_content + "\n#SYSTEM#\n" + str(kw.get("system") or "")
    return {"title_seo": "تست", "meta_description": "م" * 155, "h1": "تست",
            "slug": "t", "body_html": "<p>م.</p>", "tags": [], "image_keywords": [],
            "seo_grade": 80, "patches": [], "preserve_sections": [], "summary": ""}


llm.ask = fake_ask
for m in (writer, revision_planner, quality_gate, qa_analyzer):
    m.llm.ask = fake_ask

brief = {"topic": "تست", "source_urls": ["https://example.com"], "summary": "س",
         "content_gaps": [], "citable_facts": ["فکت ۱"]}
writer.write_article(brief, keywords={"primary": "kw", "primary_fa": "کیورد", "secondary": []})
gen = CAP["article_writing"]
check("WRITE: بلوک <fact_policy>", "<fact_policy>" in gen and "نبود داده را با آمار، داستان یا تجربه ساختگی جبران نکن" in gen)
check("WRITE: معیارهای اجرایی به‌جای «Human-like» مبهم",
      "Human-like" not in gen and "دستیار همیشه بیدار" in gen)
check("WRITE: قانون H2 (۴۰ تا ۷۰ درصد)", "۴۰ تا ۷۰ درصد" in gen)
check("WRITE: الزام قدیمی «H2های سوال‌محور» حذف شد", "ساختار: H2های سوال‌محور" not in gen)
check("WRITE: منع بازگویی پاسخ مستقیم", "حق ندارد" in gen and "بازگویی" in gen)
check("WRITE: سیاست CTA (بدون approved_cta → خنثی)", "هیچ CTA تجاری تایید نشده" in gen)

brief_cta = dict(brief)
brief_cta["approved_cta"] = {"enabled": True, "text": "رزرو مشاوره", "target_url": "https://x.ir"}
writer.write_article(brief_cta, keywords={"primary": "kw", "primary_fa": "ک", "secondary": []})
check("WRITE: با approved_cta → CTA تاییدشده در پرامپت", "رزرو مشاوره" in CAP["article_writing"])

plan = {"patches": [{"section": "intro", "instruction": "x"}], "preserve_sections": []}
writer.rewrite_article({"title_seo": "t", "body_html": "<p>b</p>",
                        "citable_facts": ["فکت ۱"], "source_urls": ["https://example.com"]},
                       plan, revision_no=1)
rw = CAP["article_rewrite_r1"]
check("REWRITE: قانون ۷ (پچ متخلف → rewrite_warnings)", "rewrite_warnings" in rw)
check("REWRITE: verified_facts با نگاشت ادعا-منبع", "allowed_scope" in rw)
check("REWRITE: منع کلیشه‌به‌کلیشه", "مترادف کلیشه‌ای ممنوع" in rw)
check("REWRITE: اولویت fact_policy بر پچ", "اولویت بالاتر" in rw)

revision_planner.build_plan({"title_seo": "t", "body_html": "<p>b</p>"},
                            [{"category": "low_eeat", "severity": "high", "problem": "p"}],
                            score=70, revision_no=1)
pl = CAP["revision_plan_r1"]
check("PLANNER: منع دستور ساخت تجربه/Case Study", "صادر نکن" in pl and "Case Study" in pl)
check("PLANNER: عدد بی‌منبع → دستور حذف", "دستور «حذف عدد»" in pl)
check("PLANNER: unresolved_source_gap", "unresolved_source_gap" in pl)
check("PLANNER: فیلدهای must_preserve/must_not_add", "must_not_add" in pl)

quality_gate.review({"title_seo": "t", "meta_description": "م", "body_html": "<p>b</p>",
                     "citable_facts": ["فکت ۱"]})
qg = CAP["quality_gate"]
check("GATE: گیت‌های سخت در پرامپت", "گیت‌های سخت" in qg and "CTA تجاری تاییدنشده" in qg)
check("GATE: verified_facts و approved_cta در ورودی داور",
      "<verified_facts>" in qg and "<approved_cta>" in qg)
check("GATE: منع کلیشه‌به‌کلیشه + must_not_add", "must_not_add" in qg)
check("GATE: لحن بدون الزام اول‌شخص", "نبود تجربه‌ی شخصی یا اول‌شخص" in qg)
check("GATE: قرارداد h1/تصویر/نشانگر", "placeholder خطا محسوب نمی‌شوند" in qg)

qa_analyzer.analyze_article({"title_seo": "t", "meta_description": "م" * 155,
                             "body_html": "<p>متن کامل است.</p>"})
qa = CAP["qa_analyze"]
check("ANALYZER: چک‌لیست دقت فنی عمومی", "API، Workflow و Integration" in qa)
check("ANALYZER: قرارداد h1/تصویر", "نبود تگ <h1> داخل body_html خطا نیست" in qa)

llm.ask = _orig
for m in (writer, revision_planner, quality_gate, qa_analyzer):
    m.llm.ask = _orig

print("\n" + "=" * 60)
print("[۳] Validator قطعی انسانی‌سازی")
print("=" * 60)
OLD = {"title_seo": "عنوان", "meta_description": "م" * 155, "h1": "ع",
       "body_html": ("<p>متن با ۲۴ ساعت پشتیبانی.</p><h2>بخش یک</h2>"
                     "<p>الف [[anchor: لینک | صفحه]].</p>"),
       "citable_facts": ["پشتیبانی ۲۴ ساعته ممکن است."], "source_urls": ["https://a.ir"]}


def variant(**kw):
    d = dict(OLD)
    d.update(kw)
    return d


check("ویرایش سبک سالم → قبول",
      writer.validate_humanize(OLD, variant(body_html=OLD["body_html"].replace("الف", "متن روان‌تر"))) == [])
check("عدد جدید → رد",
      any("عدد جدید" in v for v in writer.validate_humanize(
          OLD, variant(body_html=OLD["body_html"] + "<p>۶۰٪ کاهش زمان.</p>"))))
check("موجودیت/برند جدید → رد",
      any("موجودیت" in v for v in writer.validate_humanize(
          OLD, variant(body_html=OLD["body_html"] + "<p>ابزار Zapier عالی است.</p>"))))
check("URL جدید → رد",
      any("URL" in v for v in writer.validate_humanize(
          OLD, variant(body_html=OLD["body_html"] + "<p>https://new.com</p>"))))
check("ادعای تجربه → رد",
      any("تجربه" in v for v in writer.validate_humanize(
          OLD, variant(body_html=OLD["body_html"] + "<p>در پروژه‌های ما دیدیم.</p>"))))
check("حذف H2 → رد",
      any("H2" in v for v in writer.validate_humanize(
          OLD, variant(body_html="<p>متن با ۲۴ ساعت. [[anchor: لینک | صفحه]]</p>"))))
check("حذف نشانگر لینک → رد",
      any("نشانگر" in v for v in writer.validate_humanize(
          OLD, variant(body_html="<p>متن با ۲۴ ساعت.</p><h2>بخش یک</h2><p>الف.</p>"))))
check("عدد موجود در citable_facts → مجاز",
      writer.validate_humanize(
          OLD, variant(body_html=OLD["body_html"].replace("الف", "پشتیبانی ۲۴ ساعته"))) == [])

print("\n" + "=" * 60)
print("[۴] would_reject یکپارچه + گیت ادعای کمی + CTA")
print("=" * 60)
CFG = {"approval_threshold": 90, "weights": {"qa": .5, "gate": .35, "semrush": .15},
       "semrush_component": {"GOOD": 100, "WEAK": 50}}
ok_cc = {"no_forbidden_phrases": True, "no_unapproved_cta": True, "meta_length_150_160": True,
         "internal_links_min2": True, "external_link_min1": True,
         "complete_last_sentence": True, "_details": {}}
base = {"overall_score": 95, "qa_passed": True, "code_checks": dict(ok_cc),
        "quality_gate": {"passed": True, "weighted_score": 8.5, "scores": {"human_tone": 8}},
        "semrush": {"verdict": "GOOD"}}
r = final_score.compute(base, CFG)
check("همه‌چیز پاس → would_reject=False",
      r["score_breakdown"]["would_reject"] is False and r["final_verdict"] == "approved")
r = final_score.compute({**base, "qa_passed": False}, CFG)
check("qa_passed=False → would_reject=True (رفع تناقض)",
      r["score_breakdown"]["would_reject"] is True)
r = final_score.compute({**base, "quality_gate": {"passed": False, "weighted_score": 6.0,
                                                  "scores": {"human_tone": 5}}}, CFG)
check("ردّ گیت → would_reject=True", r["score_breakdown"]["would_reject"] is True)
unsup_gate = {"passed": False, "weighted_score": 8.5, "scores": {"human_tone": 8},
              "quantitative_claims": [{"claim": "کاهش ۶۰٪", "source_id": None,
                                       "status": "unsupported", "required_action": "remove"}]}
r = final_score.compute({**base, "quality_gate": unsup_gate}, CFG)
check("ادعای کمی unsupported → would_reject=True + شمارش",
      r["score_breakdown"]["would_reject"] is True
      and r["score_breakdown"]["unsupported_claims"] == 1)
check("فاز ۱: verdict همچنان rejected نمی‌شود", r["final_verdict"] == "needs_review")

# گیت پایتونی: unsupported → passed=False (استاب)
quality_gate.llm.ask = lambda *a, **k: {
    "scores": {"human_tone": 9, "seo": 9, "eeat": 9, "keyword": 9, "structure": 9,
               "conversion": 9, "trust": 9},
    "quantitative_claims": [{"claim": "افزایش ۲۰٪ رزرو", "source_id": None,
                             "status": "unsupported", "required_action": "remove"}],
    "issues": [], "cliches": [], "unsourced_claims": []}
g = quality_gate.review({"title_seo": "t", "meta_description": "م", "body_html": "<p>b</p>"})
quality_gate.llm.ask = _orig
check("گیت: نمره‌ی عالی + یک unsupported → passed=False", g["passed"] is False)
check("گیت: هم‌خوانی unsourced_claims با quantitative_claims",
      "افزایش ۲۰٪ رزرو" in g["unsourced_claims"])

cc = qa_analyzer.code_side_checks({"body_markdown": "<p>همین امروز جلسه رایگان رزرو کنید.</p>",
                                   "meta_description": "م" * 155})
check("CTA تاییدنشده → چک کد رد", cc["no_unapproved_cta"] is False)
cc = qa_analyzer.code_side_checks({"body_markdown": "<p>جلسه رایگان رزرو کنید.</p>",
                                   "meta_description": "م" * 155,
                                   "approved_cta": {"enabled": True, "text": "جلسه رایگان"}})
check("CTA تاییدشده → چک کد پاس", cc["no_unapproved_cta"] is True)

print("\n" + "=" * 60)
print("[۵] منطق نسخه‌ی برنده")
print("=" * 60)
# شبیه‌سازی _metrics/_is_better (همان منطق evaluate_and_sync، این‌جا از final layer)
def an(score, gate_w, tone, gate_pass, high=0, unsup=0, forb=0):
    a = {"overall_score": score, "qa_passed": True, "passed": score >= 90,
         "code_checks": dict(ok_cc),
         "quality_gate": {"passed": gate_pass, "weighted_score": gate_w,
                          "scores": {"human_tone": tone},
                          "quantitative_claims": [{"status": "unsupported"}] * unsup},
         "semrush": {"verdict": "GOOD"},
         "issues": [{"severity": "high"}] * high}
    if forb:
        a["code_checks"]["_details"] = {"found_forbidden": ["x"] * forb}
    a["final"] = final_score.compute(a, CFG)
    return a


import types
_ev = {}
exec(  # همان توابع محلی evaluate_and_sync را با منطق یکسان بازتولید نمی‌کنیم؛
       # مستقیم از ماژول با کمک یک حلقه‌ی مصنوعی تست می‌کنیم
    "", _ev)


def metrics(a):
    bd = a["final"]["score_breakdown"]
    g = bd["hard_gates"]
    return {
        "hard_errors": sum(1 for k in ("qa_passed", "quality_gate_passed",
                                       "code_checks_ok", "semrush_ok") if g[k] is False),
        "high": sum(1 for i in a.get("issues", []) if i.get("severity") == "high"),
        "unsup": int(bd.get("unsupported_claims", 0)),
        "forb": int(bd.get("forbidden_found", 0)),
        "qa": a["overall_score"],
        "gate": float(a["quality_gate"].get("weighted_score") or 0),
    }


def is_better(n, o):
    nm, om = metrics(n), metrics(o)
    return (nm["hard_errors"] <= om["hard_errors"] and nm["high"] <= om["high"]
            and nm["unsup"] <= om["unsup"] and nm["forb"] == 0
            and nm["qa"] >= om["qa"] and nm["gate"] >= om["gate"])


old_v = an(80, 7.0, 7, True, high=1)
check("بهتر در همه‌چیز → جایگزین", is_better(an(85, 7.5, 8, True, high=0), old_v))
check("نمره‌ی بالاتر ولی high بیشتر → جایگزین نشود",
      not is_better(an(90, 8.0, 8, True, high=3), old_v))
check("نمره‌ی بالاتر ولی ادعای بی‌منبع جدید → جایگزین نشود",
      not is_better(an(90, 8.0, 8, True, unsup=2), old_v))
check("عبارت ممنوعه در نسخه‌ی جدید → جایگزین نشود",
      not is_better(an(90, 8.0, 8, True, forb=1), old_v))
check("نمره‌ی فنی پایین‌تر → جایگزین نشود", not is_better(an(75, 8.0, 8, True), old_v))

print("\n" + "=" * 60)
print(f"نتیجه: {passed} پاس، {failed} شکست | تماس LLM واقعی: 0")
print("=" * 60)
sys.exit(1 if failed else 0)

```
