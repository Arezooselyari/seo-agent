# بکاپ قبل از پچ v2.1 — 2026-07-20


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


def _verified_facts_block(payload: dict) -> str:
    """فکت‌های مستند مقاله با نگاشت ادعا-منبع و دامنه‌ی مجاز (Claim–Source Mapping)."""
    facts = payload.get("citable_facts") or []
    urls = payload.get("source_urls") or []
    if not facts and not urls:
        return "(هیچ فکت تاییدشده‌ای ثبت نشده — بنابراین هیچ ادعای منبع‌دار یا عدد جدیدی مجاز نیست)"
    entries = []
    for i, fact in enumerate(facts, 1):
        entries.append({
            "id": f"fact_{i:02d}",
            "claim": fact,
            "source_url": urls[i - 1] if i - 1 < len(urls) else (urls[-1] if urls else None),
            "allowed_scope": "فقط همین ادعا — توسعه به نتایج تجاری/عددی دیگر ممنوع",
        })
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
        rejected = dict(payload)
        rejected["humanize_rejections"] = list(payload.get("humanize_rejections") or []) + [
            {"revision": revision_no, "violations": violations}
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

    # گیت سخت: هر ادعای کمی بدون منبع = ردّ قطعی (یک منبع داده‌ی واحد برای همه‌ی گزارش)
    qclaims = result.get("quantitative_claims", []) or []
    unsupported = [c for c in qclaims if (c.get("status") or "").lower() == "unsupported"]
    # هم‌خوانی unsourced_claims با quantitative_claims (نباید یکی خالی و دیگری پر باشد)
    unsourced = list(result.get("unsourced_claims", []) or [])
    for c in unsupported:
        if c.get("claim") and c["claim"] not in unsourced:
            unsourced.append(c["claim"])

    passed = wscore >= min_weighted and human >= min_human and not unsupported

    reasons = []
    if human < min_human:
        reasons.append(f"لحن انسانی {human}/10 < حداقل {min_human}")
    if wscore < min_weighted:
        reasons.append(f"نمره‌ی وزنی کیفیت {wscore}/10 < حداقل {min_weighted}")
    if unsupported:
        reasons.append(f"{len(unsupported)} ادعای کمی بدون منبع (گیت سخت)")

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
    would_reject = (
        gates["qa_passed"] is False
        or gates["quality_gate_passed"] is False
        or gates["code_checks_ok"] is False
        or not gates["score_ok"]
        or len(unsupported) > 0
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

            def _metrics(an: dict) -> dict:
                """متریک‌های مقایسه‌ی نسخه‌ها (همه از یک منبع: analysis + final)."""
                bd = an["final"]["score_breakdown"]
                g = bd["hard_gates"]
                gate_rep = an.get("quality_gate") or {}
                return {
                    "hard_errors": sum(
                        1 for k in ("qa_passed", "quality_gate_passed",
                                    "code_checks_ok", "semrush_ok")
                        if g[k] is False
                    ),
                    "high_issues": sum(
                        1 for i in an.get("issues", [])
                        if i.get("severity") == "high"
                    ),
                    "unsupported": int(bd.get("unsupported_claims", 0) or 0),
                    "forbidden": int(bd.get("forbidden_found", 0) or 0),
                    "qa_score": an["overall_score"],
                    "gate_score": float(gate_rep.get("weighted_score") or 0),
                }

            def _is_better(new: dict, old: dict) -> bool:
                """نسخه‌ی جدید فقط وقتی جایگزین می‌شود که هیچ بدترشدنی نداشته باشد:
                بدون خطای سخت جدید، ایرادات high و ادعای بی‌منبع بیشتر نشده،
                صفر عبارت ممنوعه، و نمره‌ی فنی و گیت هر دو ≥ قبلی."""
                n, o = _metrics(new), _metrics(old)
                return (
                    n["hard_errors"] <= o["hard_errors"]
                    and n["high_issues"] <= o["high_issues"]
                    and n["unsupported"] <= o["unsupported"]
                    and n["forbidden"] == 0
                    and n["qa_score"] >= o["qa_score"]
                    and n["gate_score"] >= o["gate_score"]
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
                    # جایگزینی فقط بدون هیچ پس‌رفتی (خطای سخت/ایراد high/ادعای بی‌منبع/ممنوعه)
                    if _is_better(analysis, best_analysis):
                        best_payload, best_analysis = payload, analysis

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
            passed = final["final_verdict"] == "approved"

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

## src\db.py

```python
"""SQLite: صف مقالات، تاریخچه و جلوگیری از پردازش تکراری.

وضعیت‌های جدول articles:
    pending   -> منتظر تأیید کاربر
    approved  -> تأییدشده، آماده‌ی انتشار ساعت ۱۲
    rejected  -> ردشده
    published -> منتشرشده در وردپرس
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone

from .config import DATA_DIR

# از دیتابیس اصلی پروژه استفاده کن (جایی که SEO-agent مقالات ذخیره می‌کند)
DB_PATH = DATA_DIR.parent / "agent.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_urls (
    url_hash TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    title_seo TEXT,
    payload TEXT NOT NULL,        -- JSON کامل مقاله‌ی تولیدی (متن، متا، تصاویر)
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    decided_at TEXT,
    published_at TEXT,
    wp_post_url TEXT
);
CREATE TABLE IF NOT EXISTS token_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    model TEXT NOT NULL,
    step TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def is_seen(conn: sqlite3.Connection, url: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM seen_urls WHERE url_hash = ?", (url_hash(url),)
    ).fetchone()
    return row is not None


def mark_seen(conn: sqlite3.Connection, url: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO seen_urls (url_hash, url, seen_at) VALUES (?, ?, ?)",
        (url_hash(url), url, _now()),
    )
    conn.commit()


def save_article(conn: sqlite3.Connection, topic: str, payload: dict) -> int:
    cur = conn.execute(
        "INSERT INTO articles (topic, title_seo, payload, status, created_at) "
        "VALUES (?, ?, ?, 'pending', ?)",
        (topic, payload.get("title_seo", ""), json.dumps(payload, ensure_ascii=False), _now()),
    )
    conn.commit()
    return cur.lastrowid


def update_payload(conn: sqlite3.Connection, article_id: int, payload: dict) -> None:
    """payload یک مقاله را به‌روزرسانی می‌کند (مثلاً بعد از بازنویسی توسط ارزیاب)."""
    conn.execute(
        "UPDATE articles SET payload = ?, title_seo = ? WHERE id = ?",
        (json.dumps(payload, ensure_ascii=False), payload.get("title_seo", ""), article_id),
    )
    conn.commit()


def set_status(conn: sqlite3.Connection, article_id: int, status: str) -> None:
    conn.execute(
        "UPDATE articles SET status = ?, decided_at = ? WHERE id = ?",
        (status, _now(), article_id),
    )
    conn.commit()


def mark_published(conn: sqlite3.Connection, article_id: int, post_url: str) -> None:
    conn.execute(
        "UPDATE articles SET status = 'published', published_at = ?, wp_post_url = ? WHERE id = ?",
        (_now(), post_url, article_id),
    )
    conn.commit()


def get_article(conn: sqlite3.Connection, article_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["payload"] = json.loads(d["payload"])
    return d


def approved_articles(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM articles WHERE status = 'approved'").fetchall()
    out = []
    for row in rows:
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        out.append(d)
    return out


def log_tokens(conn: sqlite3.Connection, model: str, step: str, usage) -> None:
    conn.execute(
        "INSERT INTO token_log (at, model, step, input_tokens, output_tokens, cache_read_tokens) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            _now(),
            model,
            step,
            getattr(usage, "input_tokens", 0),
            getattr(usage, "output_tokens", 0),
            getattr(usage, "cache_read_input_tokens", 0) or 0,
        ),
    )
    conn.commit()


def today_token_summary(conn: sqlite3.Connection) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    rows = conn.execute(
        "SELECT model, SUM(input_tokens) i, SUM(output_tokens) o, SUM(cache_read_tokens) c "
        "FROM token_log WHERE at LIKE ? GROUP BY model",
        (f"{today}%",),
    ).fetchall()
    lines = [f"{r['model']}: in={r['i']} out={r['o']} cached={r['c']}" for r in rows]
    return "\n".join(lines) if lines else "بدون مصرف توکن"


def pending_articles(conn: sqlite3.Connection) -> list[dict]:
    """تمام مقالات pending را برمی‌گرداند."""
    rows = conn.execute("SELECT * FROM articles WHERE status = 'pending' ORDER BY created_at DESC").fetchall()
    out = []
    for row in rows:
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        out.append(d)
    return out


def rejected_articles(conn: sqlite3.Connection) -> list[dict]:
    """تمام مقالات rejected را برمی‌گرداند."""
    rows = conn.execute("SELECT * FROM articles WHERE status = 'rejected' ORDER BY created_at DESC").fetchall()
    out = []
    for row in rows:
        d = dict(row)
        d["payload"] = json.loads(d["payload"])
        out.append(d)
    return out

```

## config\editorial_rules.json

```json
{
  "human_tone_rules": [
    "Open with a concrete problem or situation, not a ceremonial address or greeting to the reader.",
    "Use at most one rhetorical question per section; convert the rest into declarative statements.",
    "Vary sentence length deliberately, mixing short and long sentences to break a uniform machine rhythm.",
    "To fix a vague claim, follow this order: (1) use existing data from citable_facts, (2) explain the process precisely without numbers, (3) remove the claim if there is not enough information. NEVER invent a number, case study, experience, or business result to make text more concrete.",
    "Write in a direct, plain voice and avoid stacking emotional or dramatic adjectives.",
    "Prefer active voice and specific subjects over abstract, generic phrasing."
  ],
  "seo_rules": [
    "Place the primary keyword within the first 30 characters of the title and inside the H1.",
    "Use exactly one H1 and organize all remaining content under a logical H2/H3 hierarchy.",
    "Write short, topical, keyword-oriented headings instead of long rhetorical sentences.",
    "Always include a meta description of 120-155 characters containing keyword, benefit, and a call to action.",
    "Keep 2-3 internal links with descriptive anchor text and at least one external link to an authoritative source.",
    "Use a short, keyword-based slug.",
    "Preserve a structured FAQ section that can be mapped to FAQ schema."
  ],
  "eeat_rules": [
    "Judge expertise by technical precision: correct definitions, distinguishing an AI capability from its API/workflow/integration requirements, and exact claim-source matching — never by tone, first-person voice, or claimed experience.",
    "State limitations, prerequisites, and risks of any solution explicitly — honest constraints are a stronger E-E-A-T signal than confident claims.",
    "Back every quantitative claim with a cited, linked authoritative source from citable_facts; a case study, client story, or internal project may appear ONLY if recorded in verified_facts or business_context.",
    "Provide decision criteria (when it is worth it, for whom, under what conditions) instead of universal recommendations.",
    "Use sources precisely: a source only supports the exact claim it makes (allowed_scope) — never stretch a general source to back a specific commercial result.",
    "Retain domain-specific and local context that demonstrates specialized knowledge, without inventing local entities (cities, companies, clients) as evidence."
  ],
  "search_intent_rules": [
    "Match the title format to the query intent, using a question format for informational topics.",
    "Answer the core question directly and early, before secondary details.",
    "Cover the subtopics a reader with this intent expects, using distinct sections per subquestion.",
    "Use FAQ entries to capture long-tail and 'people also ask' style queries.",
    "Keep the content scope aligned with the query type and avoid drifting off-intent."
  ],
  "conversion_rules": [
    "End the conclusion with a single, specific, actionable call to action.",
    "Frame benefits as outcomes for the reader rather than product features.",
    "Keep one primary call to action and avoid competing conversion prompts.",
    "Include a soft in-body link to the relevant solution or service page as a conversion path.",
    "Write the meta description with a value promise and an explicit invitation to click."
  ],
  "readability_rules": [
    "Limit each paragraph to a single idea and split any paragraph longer than 3-4 lines.",
    "Insert a scannable visual element (table, bullet list, or numbered list) every 2-3 paragraphs.",
    "Convert any X-versus-Y comparison into a table instead of prose.",
    "Convert processes and step sequences into numbered lists.",
    "Use descriptive subheadings so the article can be understood by scanning alone.",
    "Cut filler content to raise the signal-to-noise ratio without removing depth."
  ],
  "anti_ai_writing_rules": [
    "Remove clichéd connective phrases and dramatic transitions typical of AI output.",
    "Delete repeated intensifier adverbs and keep any single intensifier to at most one use.",
    "Avoid ceremonial openers, filler reassurances, and empty summarizing sentences.",
    "Replace generic boilerplate with specific facts, data, or firsthand detail.",
    "Do not restate the same idea in multiple reworded sentences.",
    "Before editing, list the valuable existing elements (E-E-A-T, cited data, FAQ, CTA, meta, internal links) and remove only filler, never signal."
  ],
  "accuracy_rules": [
    "Before answering any yes/no question (in a heading or body), verify the polarity: a question like 'only for X?' takes 'No' as the expansive answer — a mismatched answer is a critical logic error.",
    "State capability claims conditionally, naming what results depend on (document quality, language, model, configuration) — never promise certainty about behavior that varies in practice.",
    "Banned certainty framing for capabilities: 'تضمین می‌کند', 'پاسخ قاطعانه', 'به‌درستی می‌خواند', 'بدون هیچ وقفه', 'یکپارچگی کامل' — replace with scoped, conditional statements.",
    "For AI/data systems, describe confidence scores and human-in-the-loop review for sensitive fields (financial, medical, legal) — never claim the system silently completes or corrects missing data.",
    "Distinguish detection from verification: detecting that something exists (a signature, a field) is not the same as reading, authenticating, or validating it — state the limit explicitly.",
    "Security wording: never 'guarantee' security; instead list what must be evaluated (encryption in transit/at rest, access control, data location and retention, deletion policy, audit logs).",
    "Any number, percentage, price, duration, growth/reduction rate, or quantitative result may come ONLY from citable_facts with a source_id; a hypothetical scenario may describe a process but may NOT contain any invented quantitative value or business outcome.",
    "Technology definitions must reflect real scope (e.g. IDP = OCR + layout detection + ML classification + NLP + validation + human review), not oversimplified equations like 'X is just A plus B'.",
    "The conclusion must be an actionable recommendation with decision criteria (when it is economically justified, how to start small, what to measure) — never a fear-based warning about competitors.",
    "For commercial-intent topics, include an implementation-oriented section: when the investment is justified (volume, error rate, cost), rollout steps, and success metrics (KPIs).",
    "The second half of the title must state concrete scope (کاربردها، مزایا، چالش‌ها یا محدوده‌ی فنی), and the meta must describe the article's actual contents — no generic benefit phrases.",
    "Use the primary keyword's natural Persian synonyms alongside it (e.g. 'ورود داده' با 'ورود اطلاعات' و 'خودکارسازی ورود اطلاعات') instead of repeating a single form."
  ],
  "voice_spec_rules": [
    "Voice: a professional Persian SEO copywriter producing a general blog post — direct, clear, warm; confident but never salesy. The article is NOT written in the site owner's or any specific person's personal voice.",
    "First person is permitted only as light editorial framing — it is never required, never rewarded, and never a substitute for evidence; its absence must not lower any score.",
    "Never claim personal or organizational experience ('تجربه به من نشان داده', 'در پروژه‌های ما', 'مشتریان ما', 'یادم می‌آید', 'در جلسه‌ای با مدیر') unless that exact experience is recorded in verified_facts or business_context.",
    "A hypothetical scenario may explain a process and must be marked with 'فرض کنید' or 'تصور کنید'; it must NOT contain numbers, percentages, prices, timeframes, or business outcomes, and must never read as a real client or project.",
    "Any number, percentage, price, duration, or quantitative result may come ONLY from citable_facts with a source — with no exception for illustrative examples.",
    "Show expertise through technical detail, limitations, prerequisites, and decision criteria — not through storytelling, dramatization, or claimed experience.",
    "For the reviewer: judge tone by clarity, rhythm, and natural prose; do NOT reward first-person anecdotes, do NOT penalize their absence, and treat fabricated experience or unsourced numbers as hard failures."
  ]
}

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

# بخش نهایی: جدول امتیازها + سه دسته پیشنهاد

- اصلاحات ضروری قبل از انتشار (High Priority)
- اصلاحات برای افزایش رتبه گوگل (Medium Priority)
- اصلاحات برای تبدیل مقاله به مقاله Authority (Long Term)

```
