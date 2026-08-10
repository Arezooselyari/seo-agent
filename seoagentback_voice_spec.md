# بکاپ قبل از Voice Spec (v1.1) — 2026-07-19

فایل‌های تغییریابنده: config/editorial_rules.json, config/forbidden_phrases.txt, src/writer.py, src/editor_memory.py


## config\editorial_rules.json

```json
{
  "human_tone_rules": [
    "Open with a concrete problem or situation, not a ceremonial address or greeting to the reader.",
    "Use at most one rhetorical question per section; convert the rest into declarative statements.",
    "Vary sentence length deliberately, mixing short and long sentences to break a uniform machine rhythm.",
    "Replace vague qualitative claims with a concrete number, example, or observation.",
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
    "Preserve first-person experience signals that show real, hands-on work with the subject.",
    "Keep concrete case studies with measurable outcomes and specific metrics.",
    "Back every quantitative claim with a cited, linked authoritative source.",
    "State the author's role, credentials, or expertise explicitly.",
    "Acknowledge real limitations and challenges honestly to build trust.",
    "Retain domain-specific or local context that demonstrates specialized knowledge."
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
  ]
}

```

## config\forbidden_phrases.txt

```text
# عبارات ممنوعه (لحن غیرانسانی/AI). هر خط یک عبارت. خطوط با # نادیده گرفته می‌شوند.
# طبق نکته ۴ پرامپت: هر fingerprint جدیدی دیدی همین‌جا اضافه کن (بدون نیاز به deploy).
راستش را بخواهید
جالب اینجاست که
جالب‌تر اینکه
احتمالاً شما هم
نکته اصلی اینجاست که
این یعنی چه برای کسب‌وکار شما؟
اینطور نیست؟
حسابی
در دنیای رقابتی امروز
در دنیای امروز
در دنیای پرشتاب
در عصر دیجیتال
در عصر حاضر
امروزه بیش از هر زمان دیگری
بیش از هر زمان دیگری
یکی از مهم‌ترین چالش‌ها
نقش بسزایی
غیرقابل انکار
انقلابی در
تحول شگرف
گام مهمی در جهت
در این مقاله به بررسی
با ما همراه باشید

```

## src\writer.py

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
1. **صدای نویسنده**: تجربه‌ی واقعی مشاوره را وارد کن — «در پروژه‌هایی که دیده‌ام»، قضاوت
   حرفه‌ای صریح («به نظرم برای فروشگاه زیر ۱۰۰۰ سفارش در ماه، این هزینه توجیه ندارد»)،
   و اعتراف به محدودیت‌ها («این ابزار برای فارسی هنوز لهجه‌ی محاوره را خوب نمی‌فهمد»).
2. **ملموس به‌جای انتزاعی**: هر جمله‌ی کلی («تحول چشمگیری ایجاد می‌کند») را با اثر مشخص
   جایگزین کن («تیم فروش روزانه ۲-۳ ساعت کمتر صرف پاسخ‌های تکراری می‌کند»).
3. **مثال‌های ایرانی واقعی‌نما**: صنف، شهر، موقعیت — فروشگاه اینترنتی پوشاک، کلینیک
   دندان‌پزشکی در مشهد، دفتر بیمه، شرکت پخش مواد غذایی.
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
    user_content += _context_blocks(rule_categories=None, max_rules_per_category=3)

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
    # قوانین مرتبط با بازنویسی پچی: ضد AI (اولویت بالا) + خوانایی + سئو
    extra = _context_blocks(
        rule_categories=["anti_ai_writing_rules", "readability_rules", "seo_rules"]
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

    # قوانین مرتبط با انسانی‌سازی: لحن انسانی + ضد AI (اولویت بالا) + E-E-A-T
    extra = _context_blocks(
        rule_categories=["human_tone_rules", "anti_ai_writing_rules", "eeat_rules"]
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

## src\editor_memory.py

```python
"""حافظه‌ی تحریریه: یادگیری از خطاهای تکراری در مقالات مختلف.

هر بار QA ایرادی پیدا می‌کند، دسته‌ی آن شمرده می‌شود. وقتی یک دسته به حد نصاب
(minimum_occurrence در settings.yaml) رسید، به‌عنوان «درس تحریریه» وارد پرامپت
نویسنده می‌شود تا از اول آن اشتباه را نکند.

فایل داده: data/editor_memory.json
{
  "counts": {"weak_meta": 4, "ai_cliche": 7, ...},
  "examples": {"weak_meta": ["نمونه ایراد...", ...]},   # حداکثر ۳ نمونه per دسته
  "updated_at": "..."
}
"""
import json
import logging
from datetime import datetime, timezone

from .config import CONFIG_DIR, DATA_DIR, load_settings

logger = logging.getLogger(__name__)

_MEMORY_FILE = DATA_DIR / "editor_memory.json"
_RULES_FILE = CONFIG_DIR / "editorial_rules.json"

# عنوان فارسی هر دسته‌ی قوانین (قوانین خودشان انگلیسی می‌مانند — ترجمه‌ی خودکار ریسک تحریف دارد)
_RULE_CATEGORY_TITLES = {
    "human_tone_rules": "قوانین لحن انسانی",
    "seo_rules": "قوانین سئو",
    "eeat_rules": "قوانین E-E-A-T",
    "search_intent_rules": "قوانین نیت جستجو",
    "conversion_rules": "قوانین تبدیل (Conversion)",
    "readability_rules": "قوانین خوانایی",
    "anti_ai_writing_rules": "قوانین ضد نگارش AI (اولویت بالا)",
}

# پیوند دسته‌ی ایراد QA → دسته‌ی قانون مرتبط (برای غنی‌کردن درس‌های آماری)
_ISSUE_TO_RULE_CATEGORY = {
    "ai_cliche": "anti_ai_writing_rules",
    "robotic_language": "anti_ai_writing_rules",
    "repetitive_sentence": "anti_ai_writing_rules",
    "low_information_gain": "anti_ai_writing_rules",
    "weak_hook": "human_tone_rules",
    "generic_example": "human_tone_rules",
    "missing_local_example": "eeat_rules",
    "low_eeat": "eeat_rules",
    "weak_title": "seo_rules",
    "weak_meta": "seo_rules",
    "keyword_missing": "seo_rules",
    "keyword_stuffing": "seo_rules",
    "unnatural_keyword": "seo_rules",
    "missing_link": "seo_rules",
    "echo_heading": "readability_rules",
    "paragraph_too_long": "readability_rules",
    "poor_scannability": "readability_rules",
    "poor_transition": "readability_rules",
    "weak_cta": "conversion_rules",
    "faq_duplicate": "search_intent_rules",
}

_rules_cache: dict | None = None

# توضیح فارسی هر دسته برای تزریق به پرامپت نویسنده
_CATEGORY_GUIDANCE = {
    "robotic_language": "از جملات قالبی و ماشینی پرهیز کن؛ مثل یک نویسنده‌ی باتجربه‌ی فارسی‌زبان بنویس.",
    "keyword_stuffing": "کیورد را طبیعی و کم‌تکرار به کار ببر؛ تکرار مصنوعی ممنوع.",
    "keyword_missing": "کیورد اصلی را حتماً در H1، صد کلمه‌ی اول، یک H2 و جمع‌بندی بیاور.",
    "echo_heading": "پاراگراف بعد از هر H2 نباید همان عنوان را طوطی‌وار تکرار کند؛ مستقیم پاسخ بده.",
    "weak_hook": "مقدمه را با داده، مثال ملموس یا ادعای صریح شروع کن، نه کلی‌گویی.",
    "weak_cta": "جمع‌بندی باید یک اقدام مشخص و عملی به خواننده بدهد.",
    "paragraph_too_long": "پاراگراف‌ها را کوتاه نگه دار (حداکثر ۴-۵ جمله).",
    "poor_transition": "بین بخش‌ها پیوند منطقی بساز؛ پرش ناگهانی نکن.",
    "generic_example": "مثال کلی نزن؛ اسم صنف، شهر یا موقعیت واقعی ایرانی بیاور.",
    "missing_local_example": "حداقل یک مثال ملموس از بازار ایران در بدنه بیاور.",
    "low_information_gain": "هر بخش باید حرف تازه‌ای بزند؛ تکرار همان مفاهیم ممنوع.",
    "low_eeat": "به منبع استناد کن و ادعای عددی را فقط از داده‌ی منبع بیاور.",
    "poor_scannability": "از لیست، جدول و بولد کردن نکات کلیدی استفاده کن.",
    "repetitive_sentence": "طول و ساختار جملات را متنوع کن؛ سه جمله‌ی هم‌ساختار پشت هم ننویس.",
    "unnatural_keyword": "کیورد را در جمله طوری بنشان که طبیعی خوانده شود.",
    "ai_cliche": "عبارات کلیشه‌ای AI (در دنیای امروز، جالب است بدانید، ...) ممنوع.",
    "weak_title": "عنوان باید مشخص، جذاب و شامل کیورد باشد؛ حداکثر ۶۰ کاراکتر.",
    "weak_meta": "متا باید ۱۵۰-۱۶۰ کاراکتر، شامل کیورد و دعوت به اقدام باشد.",
    "faq_duplicate": "سوالات FAQ نباید هم‌پوشانی داشته باشند؛ هر سوال یک نیاز واقعی متفاوت.",
    "incomplete_sentence": "جمله‌ی آخر هر پاراگراف را کامل تمام کن؛ متن ناتمام ممنوع.",
    "missing_link": "حداقل ۲ لینک داخلی [[anchor:]] و ۱ لینک خارجی [[external:]] در متن بگذار.",
}


def _load() -> dict:
    if _MEMORY_FILE.exists():
        try:
            return json.loads(_MEMORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("editor_memory.json خراب بود؛ از نو ساخته می‌شود.")
    return {"counts": {}, "examples": {}}


# ── Rule Engine: قوانین عمومی تحریریه (config/editorial_rules.json) ──────────

def load_rules() -> dict:
    """قوانین تحریریه را می‌خواند (با کش). اگر فایل نبود/خراب بود → {} (بدون fail).

    Backward compatible: با حذف فایل، همه‌ی مصرف‌کننده‌ها بلوک خالی می‌گیرند
    و سیستم دقیقاً مثل قبل کار می‌کند.
    """
    global _rules_cache
    if _rules_cache is not None:
        return _rules_cache
    try:
        data = json.loads(_RULES_FILE.read_text(encoding="utf-8"))
        _rules_cache = {k: v for k, v in data.items() if isinstance(v, list)}
        logger.info(
            f"قوانین تحریریه بارگذاری شد: {len(_rules_cache)} دسته، "
            f"{sum(len(v) for v in _rules_cache.values())} قانون"
        )
    except FileNotFoundError:
        _rules_cache = {}
    except Exception as e:
        logger.warning(f"editorial_rules.json قابل خواندن نبود ({e})؛ بدون قوانین ادامه می‌دهیم.")
        _rules_cache = {}
    return _rules_cache


def rules_prompt_block(
    categories: list[str] | None = None,
    max_rules_per_category: int | None = None,
) -> str:
    """قوانین را به بلوک پرامپت تبدیل می‌کند.

    categories: فقط این دسته‌ها (None = همه). فیلتر دسته مصرف توکن را کنترل می‌کند —
    هر ایجنت فقط قوانین مرتبط خودش را بگیرد.
    max_rules_per_category: سقف قانون در هر دسته (برای خلاصه‌ی تولید اولیه).
    """
    rules = load_rules()
    if not rules:
        return ""

    selected = categories or list(rules.keys())
    lines = [
        "قوانین تحریریه (راهنمای کیفیت — نه چک‌لیست؛ روح قوانین را در نگارش رعایت کن):"
    ]
    for cat in selected:
        items = rules.get(cat) or []
        if not items:
            continue
        if max_rules_per_category:
            items = items[:max_rules_per_category]
        title = _RULE_CATEGORY_TITLES.get(cat, cat)
        lines.append(f"\n[{title}]")
        lines.extend(f"- {r}" for r in items)
    return "\n".join(lines) if len(lines) > 1 else ""


def record_issues(issues: list[dict]) -> None:
    """ایرادات یک دور QA را در حافظه ثبت می‌کند."""
    if not issues:
        return
    mem = _load()
    for issue in issues:
        cat = issue.get("category", "").strip()
        if not cat:
            continue
        mem["counts"][cat] = mem["counts"].get(cat, 0) + 1
        ex = mem["examples"].setdefault(cat, [])
        quote = (issue.get("exact_quote") or "")[:120]
        if quote and quote not in ex:
            ex.append(quote)
            del ex[3:]  # حداکثر ۳ نمونه
    mem["updated_at"] = datetime.now(timezone.utc).isoformat()
    _MEMORY_FILE.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")


def lessons_prompt_block() -> str:
    """درس‌های تحریریه (دسته‌های پرتکرار) را برای تزریق به پرامپت نویسنده می‌سازد."""
    cfg = load_settings().get("editor_memory", {})
    if not cfg.get("enabled", True):
        return ""
    min_occ = int(cfg.get("minimum_occurrence", 3))

    mem = _load()
    frequent = [
        (cat, n) for cat, n in sorted(mem["counts"].items(), key=lambda x: -x[1])
        if n >= min_occ and cat in _CATEGORY_GUIDANCE
    ]
    if not frequent:
        return ""

    rules = load_rules()
    lines = ["درس‌های تحریریه از مقالات قبلی (این اشتباهات پرتکرار را از اول نکن):"]
    for cat, n in frequent[:8]:
        line = f"- ({cat}، {n} بار) {_CATEGORY_GUIDANCE[cat]}"
        # اگر قانون عمومی مرتبطی وجود دارد، اولین قانون آن دسته را ضمیمه کن
        rule_cat = _ISSUE_TO_RULE_CATEGORY.get(cat)
        related = (rules.get(rule_cat) or []) if rule_cat else []
        if related:
            line += f"\n  ↳ قانون مرتبط: {related[0]}"
        lines.append(line)
    return "\n".join(lines)


def stats() -> dict:
    """آمار حافظه برای گزارش HTML."""
    mem = _load()
    return {"counts": dict(mem.get("counts", {})), "updated_at": mem.get("updated_at")}

```
