# بکاپ قبل از جایگزینی HUMANIZE_PROMPT با نسخه‌ی کاربر (ویراستار سبک) — 2026-07-20

## src/writer.py

```python
"""گام ۳ — تولید مقاله‌ی فارسی سئو شده (Generate Mode + Rewrite Mode).

پرامپت سیستم: prompts/seo-content-agent-prompt.xml (با Prompt Caching).
Rewrite Mode: فقط بخش‌های فهرست‌شده در revision_patch بازنویسی می‌شوند؛
بخش‌های سالم (preserve_sections) کلمه‌به‌کلمه حفظ می‌شوند.
"""
import json

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

<requirements>
- زبان: فارسی روان و Human-like (غیرقابل‌تشخیص به‌عنوان بازنویسی یا محتوای ماشینی)
- طول: {min_words} تا {max_words} کلمه
- ساختار: H2های سوال‌محور + پاسخ مستقیم ۱-۲ جمله‌ای بلافاصله بعد از هر H2
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

{lessons}

قوانین اجرا:
1. فقط بخش‌های فهرست‌شده در پچ‌ها را بازنویسی کن — دقیقاً طبق instruction هر پچ.
2. بخش‌های preserve را عیناً کپی کن. حتی یک کلمه‌ی آن‌ها را عوض نکن.
3. پچ scope=global را روی کل متن اعمال کن ولی ساختار و بخش‌های سالم را نگه دار.
4. نشانگرهای لینک [[anchor: ...]] و [[external: ...]] موجود را حفظ کن (مگر پچ صریحاً بگوید).
5. متا باید ۱۵۰-۱۶۰ کاراکتر، عنوان ≤ ۶۰ کاراکتر، و جمله‌ی آخر بدنه کامل باشد.

خروجی: همان JSON کامل مقاله (title_seo, meta_description, h1, slug, body_html, tags,
image_keywords, seo_grade) — بدنه‌ی کامل با بخش‌های اصلاح‌شده + بخش‌های محفوظ."""

HUMANIZE_PROMPT = """تو یک نویسنده‌ی باتجربه‌ی فارسی‌زبان هستی که سال‌ها برای مدیران کسب‌وکار ایرانی
مقاله نوشته‌ای. مقاله‌ی زیر از نظر فنی (سئو، ساختار، لینک) سالم است، اما بازبین کیفیت
گفته لحنش ماشینی و AI-گونه است. وظیفه‌ی تو: **بازنویسی کامل با لحن انسانی** — طوری که
انگار یک مشاور واقعی دارد تجربه‌اش را برای یک مدیر تعریف می‌کند.

<article>
{article}
</article>

<quality_review>
گزارش بازبین کیفیت (کلیشه‌ها و ایرادات لحن — همه باید رفع شوند):
{review}
</quality_review>

{lessons}

قوانین بازنویسی انسانی:
1. **صدای نویسنده (طبق Voice Spec)**: تجربه را فقط با شواهد نشان بده — قضاوت حرفه‌ای
   صریح («به نظرم برای فروشگاه زیر ۱۰۰۰ سفارش در ماه، این هزینه توجیه ندارد») و
   اعتراف به محدودیت‌ها («این ابزار برای فارسی هنوز لهجه‌ی محاوره را خوب نمی‌فهمد»).
   **ادعای تجربه‌ی شخصی اثبات‌نشدنی مطلقاً ممنوع**: «تجربه به من نشان داده»،
   «در پروژه‌هایی که دیده‌ام»، «من خودم دیده‌ام»، «در پروژه اخیرمان» — به‌جای ادعا،
   خودِ مشاهده را مستقیم و بی‌واسطه بیان کن.
2. **ملموس به‌جای انتزاعی**: هر جمله‌ی کلی («تحول چشمگیری ایجاد می‌کند») را با اثر مشخص
   جایگزین کن («تیم فروش روزانه ۲-۳ ساعت کمتر صرف پاسخ‌های تکراری می‌کند»).
3. **مثال ایرانی ملموس و صادق**: حداکثر یک سناریوی کاملاً مشخص (صنف + شهر + نتیجه) که
   صادقانه با «تصور کنید» یا «فرض کنید» علامت‌گذاری شده — نه روایت پروژه‌ی واقعیِ ساختگی
   و نه ابزار بی‌نام («ابزار X»).
4. **ریتم انسانی**: جمله‌ی کوتاه کنار جمله‌ی بلند. گاهی جمله‌ی ۳ کلمه‌ای. بدون الگوی تکراری
   در شروع پاراگراف‌ها.
5. **حفظ اسکلت سئو (دست نزن)**: کیوردهای موجود در H1/H2ها، نشانگرهای [[anchor:]] و
   [[external:]]، ساختار سرفصل‌ها، FAQ، آمار و اعداد منبع‌دار — همه سر جایشان بمانند.
6. متا ۱۵۰-۱۶۰ کاراکتر، عنوان ≤ ۶۰ کاراکتر، جمله‌ی آخر کامل.
7. ادعای عددی جدید نساز — فقط عددهای موجود مقاله.
8. هیچ بخش متادیتا اضافه نکن: «درباره نویسنده»، تاریخ تولید، نام تیم/آژانس، امضا —
   صدای نویسنده باید در خود متن باشد، نه در جعبه‌ی جداگانه.

خروجی: همان JSON کامل مقاله (title_seo, meta_description, h1, slug, body_html, tags,
image_keywords, seo_grade)."""


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

    user_content = WRITE_PROMPT.format(
        brief=json.dumps(brief, ensure_ascii=False, indent=1),
        target_keywords=kw_block,
        min_words=cfg["min_words"],
        max_words=cfg["max_words"],
        min_faq=cfg["min_faq"],
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
            lessons=extra,
        ),
        model_tier="main",
        system=llm.system_prompt_xml(),
        cache_system=True,
        max_tokens=32000,  # بازنویسی کل مقاله + JSON + thinking — سقف بالا تا truncate نشود
        temperature=0.7,
    )

    # فیلدهای زمینه‌ای که مدل برنمی‌گرداند را از payload قبلی حفظ کن
    for key in ("topic", "source_urls", "target_keywords", "image_keywords"):
        if key in payload and key not in new_payload:
            new_payload[key] = payload[key]

    word_count = len(new_payload.get("body_html", "").split())
    print(f"[writer] ✎ بازنویسی دور {revision_no}: «{new_payload.get('title_seo')}» (~{word_count} کلمه، {len(patches)} پچ)")
    return new_payload


def humanize_article(payload: dict, gate_report: dict, revision_no: int = 1) -> dict:
    """Humanize Mode: بازنویسی کامل با لحن انسانی (وقتی لحن سراسری ضعیف است).

    برخلاف rewrite_article که پچی است، کل متن با صدای نویسنده‌ی واقعی بازنویسی
    می‌شود ولی اسکلت سئو (کیوردها، لینک‌ها، ساختار، آمار) حفظ می‌شود.
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

    # قوانین مرتبط با انسانی‌سازی: لحن انسانی + ضد AI (اولویت بالا) + E-E-A-T + Voice Spec + دقت فنی
    extra = _context_blocks(
        rule_categories=["human_tone_rules", "anti_ai_writing_rules", "eeat_rules",
                         "voice_spec_rules", "accuracy_rules"]
    )

    new_payload = llm.ask(
        step=f"article_humanize_r{revision_no}",
        user_content=HUMANIZE_PROMPT.format(
            article=article_repr, review=review_repr, lessons=extra,
        ),
        model_tier="main",
        system=llm.system_prompt_xml(),
        cache_system=True,
        max_tokens=32000,
        temperature=0.9,  # انسانی‌سازی به بیشترین خلاقیت نیاز دارد
    )

    for key in ("topic", "source_urls", "target_keywords", "image_keywords"):
        if key in payload and key not in new_payload:
            new_payload[key] = payload[key]

    word_count = len(new_payload.get("body_html", "").split())
    print(f"[writer] ♻ انسانی‌سازی دور {revision_no}: «{new_payload.get('title_seo')}» (~{word_count} کلمه)")
    return new_payload

```
