# بکاپ قبل از Editorial Rules Engine
تاریخ: 2026-07-18T06:20:21.152208


---

## `seo-agent/src/editor_memory.py`

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

from .config import DATA_DIR, load_settings

logger = logging.getLogger(__name__)

_MEMORY_FILE = DATA_DIR / "editor_memory.json"

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

    lines = ["درس‌های تحریریه از مقالات قبلی (این اشتباهات پرتکرار را از اول نکن):"]
    for cat, n in frequent[:8]:
        lines.append(f"- ({cat}، {n} بار) {_CATEGORY_GUIDANCE[cat]}")
    return "\n".join(lines)


def stats() -> dict:
    """آمار حافظه برای گزارش HTML."""
    mem = _load()
    return {"counts": dict(mem.get("counts", {})), "updated_at": mem.get("updated_at")}

```


---

## `seo-agent/src/revision_planner.py`

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

from . import llm
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
      "instruction": "دستور کامل و ادغام‌شده‌ی بازنویسی این بخش"
    }}
  ],
  "preserve_sections": ["فهرست بخش‌هایی که سالم‌اند و نباید عوض شوند"],
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

    plan = llm.ask(
        step=f"revision_plan_r{revision_no}",
        user_content=_PLANNER_PROMPT.format(
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


---

## `seo-agent/src/writer.py`

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

    # درس‌های تحریریه از خطاهای پرتکرار مقالات قبلی
    lessons = editor_memory.lessons_prompt_block()
    user_content = WRITE_PROMPT.format(
        brief=json.dumps(brief, ensure_ascii=False, indent=1),
        target_keywords=kw_block,
        min_words=cfg["min_words"],
        max_words=cfg["max_words"],
        min_faq=cfg["min_faq"],
    )
    if lessons:
        user_content += f"\n\n<editorial_lessons>\n{lessons}\n</editorial_lessons>"
    forbidden = _forbidden_block()
    if forbidden:
        user_content += f"\n\n<forbidden_phrases>\n{forbidden}\n</forbidden_phrases>"

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
    lessons = editor_memory.lessons_prompt_block()

    forbidden = _forbidden_block()
    extra = ""
    if lessons:
        extra += f"<editorial_lessons>\n{lessons}\n</editorial_lessons>\n"
    if forbidden:
        extra += f"<forbidden_phrases>\n{forbidden}\n</forbidden_phrases>"

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

    lessons = editor_memory.lessons_prompt_block()
    forbidden = _forbidden_block()
    extra = ""
    if lessons:
        extra += f"<editorial_lessons>\n{lessons}\n</editorial_lessons>\n"
    if forbidden:
        extra += f"<forbidden_phrases>\n{forbidden}\n</forbidden_phrases>"

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


---

## `seo-agent/src/quality_gate.py`

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
import logging

from . import llm
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
    {"quote": "عبارت کلیشه‌ای دقیق از متن", "better": "نسخه‌ی انسانی و ملموس پیشنهادی"}
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
  ]
}
- سخت‌گیر باش: متن AI-گونه و بدون تجربه‌ی واقعی نباید human_tone بالای ۶ بگیرد.
- exact_quote هر ایراد باید واقعاً در متن باشد.
- همه‌ی کلیشه‌ها را در issues هم بیاور (category=ai_cliche) تا نویسنده اصلاحشان کند.
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

    user_content = (
        f"کیورد اصلی مقاله: {primary or 'نامشخص'}\n"
        f"عنوان: {title}\n"
        f"متا: {meta}\n\n"
        f"متن کامل مقاله:\n{body}"
    )

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
    passed = wscore >= min_weighted and human >= min_human

    reasons = []
    if human < min_human:
        reasons.append(f"لحن انسانی {human}/10 < حداقل {min_human}")
    if wscore < min_weighted:
        reasons.append(f"نمره‌ی وزنی کیفیت {wscore}/10 < حداقل {min_weighted}")

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
        "issues": result.get("issues", []) or [],
        "title_suggestion": result.get("title_suggestion"),
        "meta_suggestion": result.get("meta_suggestion"),
        "cta_suggestion": result.get("cta_suggestion"),
        "unsourced_claims": result.get("unsourced_claims", []),
        "recommendations": result.get("recommendations", {}),
        "summary_table": result.get("summary_table", []),
        "reasons": reasons,
    }

```
