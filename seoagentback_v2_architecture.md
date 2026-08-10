# بکاپ قبل از اصلاحات معماری v2 (۱۷ بند کاربر) — 2026-07-20


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

1. فقط سبک جمله‌بندی، ریتم، انتخاب واژه و تکرارهای زبانی را اصلاح کن.

2. هیچ اطلاعات، تحلیل، نتیجه‌گیری، توصیه، مثال، سناریو، شهر، شرکت،
   ابزار، قابلیت، عدد، درصد، مبلغ، زمان یا ادعای جدیدی اضافه نکن.

3. هیچ تجربه شخصی یا سازمانی نساز. استفاده از عبارت‌هایی مانند
   «من دیده‌ام»، «در پروژه‌های ما»، «تجربه نشان داده»، «مشتریان ما»
   و هر روایت دست‌اولی که در verified_facts ثبت نشده ممنوع است.

4. اگر جمله‌ای کلی است، آن را ساده‌تر و دقیق‌تر بنویس؛
   برای ملموس کردن آن، عدد یا مثال جدید نساز.

5. سناریوی فرضی جدید اضافه نکن. سناریوی موجود را نیز فقط زمانی حفظ کن
   که در locked_elements ثبت شده باشد.

6. هیچ عدد، درصد، قیمت، مدت‌زمان یا نتیجه کمی جدیدی مجاز نیست.
   حتی در مثال فرضی.

7. منابع، URLها، نام ابزارها، اعداد و ادعاهای موجود را توسعه نده.
   هر منبع فقط از ادعایی پشتیبانی می‌کند که در verified_facts ثبت شده است.

8. H1، H2، H3، نشانگرهای لینک و ترتیب بخش‌ها را حفظ کن؛
   مگر quality_review صریحاً تغییر ساختاری درخواست کرده باشد.

9. عبارت‌های تبلیغاتی مطلق مانند «ضروری»، «حیاتی»، «تحول‌آفرین»،
   «افزایش چشمگیر فروش» و «بهترین راهکار» را خنثی کن،
   مگر اینکه پشتوانه مستند داشته باشند.

10. قبل از خروجی بررسی کن:
    - عدد جدید: صفر
    - موجودیت جدید: صفر
    - مثال جدید: صفر
    - تجربه شخصی جدید: صفر
    - URL جدید: صفر

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
    # فکت‌های مستند بریف در payload می‌مانند تا ویراستار سبک (humanize) بداند
    # کدام ادعاها پشتوانه دارند (verified_facts)
    if brief.get("citable_facts"):
        payload["citable_facts"] = brief["citable_facts"]
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
    for key in ("topic", "source_urls", "target_keywords", "image_keywords", "citable_facts"):
        if key in payload and key not in new_payload:
            new_payload[key] = payload[key]

    word_count = len(new_payload.get("body_html", "").split())
    print(f"[writer] ✎ بازنویسی دور {revision_no}: «{new_payload.get('title_seo')}» (~{word_count} کلمه، {len(patches)} پچ)")
    return new_payload


def _verified_facts_block(payload: dict) -> str:
    """فکت‌های مستند مقاله (بریف + منابع) — تنها ادعاهایی که ویراستار سبک مجاز است نگه دارد."""
    facts = {
        "citable_facts": payload.get("citable_facts") or [],
        "source_urls": payload.get("source_urls") or [],
    }
    if not facts["citable_facts"] and not facts["source_urls"]:
        return "(هیچ فکت تاییدشده‌ای ثبت نشده — بنابراین هیچ ادعای منبع‌دار یا عدد جدیدی مجاز نیست)"
    return json.dumps(facts, ensure_ascii=False, indent=1)


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

    for key in ("topic", "source_urls", "target_keywords", "image_keywords", "citable_facts"):
        if key in payload and key not in new_payload:
            new_payload[key] = payload[key]

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
  ],
  "rules_compliance": {
    "followed": ["قوانین تحریریه‌ای که مقاله رعایت کرده (متن کوتاه قانون)"],
    "violated": [
      {"rule": "متن کوتاه قانون نقض‌شده", "severity": "high | medium | low",
       "evidence": "شاهد کوتاه از متن", "fix": "پیشنهاد اصلاح مشخص"}
    ]
  }
}
- سخت‌گیر باش: متن AI-گونه و بدون تجربه‌ی واقعی نباید human_tone بالای ۶ بگیرد.
- exact_quote هر ایراد باید واقعاً در متن باشد.
- همه‌ی کلیشه‌ها را در issues هم بیاور (category=ai_cliche) تا نویسنده اصلاحشان کند.
- rules_compliance را دقیقاً بر اساس <editorial_rules> داده‌شده در ورودی پر کن —
  همین قوانین معیار داوری تو هستند (همان قوانینی که نویسنده با آن‌ها می‌نویسد).
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

def code_side_checks(article: dict) -> dict:
    """چک‌های قطعی سمت کد روی مقاله‌ی خروجی مدل. Returns {check_name: bool}."""
    body = article.get("body_markdown", "") or ""
    meta = article.get("meta_description", "") or ""

    forbidden = _load_forbidden_phrases()
    found_forbidden = [p for p in forbidden if p in body]

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
        "meta_length_150_160": meta_len_ok,
        "internal_links_min2": internal_links >= 2,
        "external_link_min1": external_links >= 1,
        "complete_last_sentence": last_char_ok,
        "_details": {
            "found_forbidden": found_forbidden,
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
      "rule": "قانون تحریریه‌ای که مبنای این اصلاح است (کوتاه) یا -"
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
    reject_below = float(cfg.get("reject_below", _DEFAULT_REJECT_BELOW))
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

    # فاز ۱: ردّ خودکار غیرفعال — نامزد ردّ فقط علامت می‌خورد و needs_review می‌ماند
    forbidden = (
        (analysis.get("code_checks") or {}).get("_details", {}).get("found_forbidden") or []
    )
    would_reject = (not approved) and (final < reject_below or bool(forbidden))

    return {
        "final_score": final,
        "final_verdict": "approved" if approved else "needs_review",
        "score_breakdown": {
            "components": comps,
            "weights_used": weights_used,
            "hard_gates": gates,
            "would_reject": would_reject,
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

            def _rank(an: dict) -> tuple:
                """کلید مقایسه‌ی نسخه‌ها از لایه‌ی نمره‌ی نهایی:
                عبور گیت‌های سخت > نمره‌ی نهایی > نمره‌ی فنی."""
                g = an["final"]["score_breakdown"]["hard_gates"]
                gates_ok = all(
                    g[k] is not False
                    for k in ("qa_passed", "quality_gate_passed",
                              "code_checks_ok", "semrush_ok")
                )
                return (gates_ok, an["final"]["final_score"], an["overall_score"])

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
                    # بهترین = اول عبور از گیت، بعد کیفیت وزنی (لحن)، بعد نمره‌ی فنی
                    if _rank(analysis) > _rank(best_analysis):
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

            # اگر آخرین دور بدتر از بهترین بود، بهترین نسخه را برگردان
            if _rank(best_analysis) > _rank(analysis):
                logger.info(
                    f"   نسخه‌ی آخر ({analysis['overall_score']}) بدتر از بهترین ({best_analysis['overall_score']}) بود؛ بهترین نگه داشته شد."
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
    "voice_spec_rules": "مشخصات صدای نویسنده — Voice Spec (معیار مشترک نویسنده و داور)",
    "accuracy_rules": "قوانین دقت فنی و اعتبار ادعاها (از بازخورد سردبیر انسانی — اولویت بالا)",
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
  ],
  "accuracy_rules": [
    "Before answering any yes/no question (in a heading or body), verify the polarity: a question like 'only for X?' takes 'No' as the expansive answer — a mismatched answer is a critical logic error.",
    "State capability claims conditionally, naming what results depend on (document quality, language, model, configuration) — never promise certainty about behavior that varies in practice.",
    "Banned certainty framing for capabilities: 'تضمین می‌کند', 'پاسخ قاطعانه', 'به‌درستی می‌خواند', 'بدون هیچ وقفه', 'یکپارچگی کامل' — replace with scoped, conditional statements.",
    "For AI/data systems, describe confidence scores and human-in-the-loop review for sensitive fields (financial, medical, legal) — never claim the system silently completes or corrects missing data.",
    "Distinguish detection from verification: detecting that something exists (a signature, a field) is not the same as reading, authenticating, or validating it — state the limit explicitly.",
    "Security wording: never 'guarantee' security; instead list what must be evaluated (encryption in transit/at rest, access control, data location and retention, deletion policy, audit logs).",
    "Every percentage or metric needs context (before/after values, measurement window, method) or must be removed; unnamed customers must be explicitly marked as anonymized.",
    "Technology definitions must reflect real scope (e.g. IDP = OCR + layout detection + ML classification + NLP + validation + human review), not oversimplified equations like 'X is just A plus B'.",
    "The conclusion must be an actionable recommendation with decision criteria (when it is economically justified, how to start small, what to measure) — never a fear-based warning about competitors.",
    "For commercial-intent topics, include an implementation-oriented section: when the investment is justified (volume, error rate, cost), rollout steps, and success metrics (KPIs).",
    "The second half of the title must state concrete scope (کاربردها، مزایا، چالش‌ها یا محدوده‌ی فنی), and the meta must describe the article's actual contents — no generic benefit phrases.",
    "Use the primary keyword's natural Persian synonyms alongside it (e.g. 'ورود داده' با 'ورود اطلاعات' و 'خودکارسازی ورود اطلاعات') instead of repeating a single form."
  ],
  "voice_spec_rules": [
    "Voice: a hands-on consultant writing for Iranian business managers — direct, professional, warm; confident but never salesy.",
    "Show experience ONLY through concrete evidence: one fully specified illustrative scenario per article (industry + city + measurable outcome), explicit professional judgments, and honest admission of limitations.",
    "Never claim personal experience with unverifiable first-person phrases such as 'تجربه به من نشان داده', 'در پروژه‌های بسیاری دیده‌ام', 'من خودم دیده‌ام' — state the observation itself directly instead.",
    "Mark illustrative examples honestly with 'تصور کنید' or 'فرض کنید'; never present an invented example as a real client project, and never cite unnamed tools ('ابزار X') or unsourced numbers as real results.",
    "First person IS allowed for judgment and recommendation ('پیشنهاد من', 'به نظرم') — judgment is opinion and needs no proof; experience claims need evidence.",
    "Any percentage or metric must come from the brief's cited facts or be framed explicitly as an assumption inside a marked illustrative scenario.",
    "For the reviewer: a marked illustrative scenario, explicit professional judgments, and admitted limitations ARE the required experience signals — reward them; penalize only unverifiable personal-experience claims and fabricated case studies."
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
# ادعای تجربه‌ی شخصی اثبات‌نشدنی — Voice Spec v1.1 (تجربه فقط با سناریوی مشخصِ علامت‌گذاری‌شده)
تجربه به من نشان داده
در پروژه‌های بسیاری دیده‌ام
در پروژه‌هایی دیده‌ام
در پروژه‌هایی که دیده‌ام
از تجربه من در پروژه
در پروژه اخیرمان
چیزی که من در پروژه‌ها دیده‌ام
# کلیشه‌های تبلیغاتی/ترس‌محور — از بازخورد سردبیر انسانی روی مقاله #18
حجم سرسام‌آور
پا به میدان می‌گذارد
در کسری از زمان
گرد و غبار رقابت
حرفی برای گفتن داشته باشد
سرمایه‌گذاری حیاتی
بازار امروز و فردا
پاسخ قاطعانه
چشمانش را باز کرده
این تحول را رقم بزنید

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

- آیا متن طبیعی نوشته شده؟
- آیا شبیه متن تولیدشده توسط AI است؟
- آیا نویسنده شخصیت و تجربه خودش را وارد کرده؟
- آیا متن بیش از حد کلیشه‌ای است؟

نمونه عبارت‌های کلیشه‌ای را استخراج کن.

مثال — ضعیف: «این فناوری تحول چشمگیری ایجاد می‌کند»
بهتر: «این فناوری باعث می‌شود تیم فروش روزانه چند ساعت زمان کمتری صرف پاسخ‌های تکراری کند.»

## 2. بررسی لحن نویسنده

- آیا لحن آموزشی است؟ مشاوره‌ای است؟
- آیا برای مدیر کسب‌وکار مناسب است؟
- آیا اعتماد ایجاد می‌کند؟

پیشنهاد بده چگونه لحن را حرفه‌ای‌تر کنیم.

## 3. بررسی Experience در محتوا

آیا مقاله نشان می‌دهد نویسنده تجربه واقعی دارد؟ (مثال واقعی، Case Study، تجربه پروژه، داده عملی، نظر تخصصی)
اگر کمبود دارد، پیشنهاد بده چه بخش‌هایی اضافه شود.

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

- Experience: تجربه واقعی وجود دارد؟
- Expertise: تخصص نویسنده مشخص است؟
- Authority: اعتبار ایجاد می‌شود؟
- Trust: منابع و داده‌ها قابل اعتمادند؟

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

## prompts\seo-analyzer-prompt.md

```text
# مستر پرامپت: تولید مقاله سئوشده با لحن انسانی (نسخه ۱.۰)

> نحوه استفاده: این متن را به‌عنوان **System Prompt** در نود Claude API (در n8n یا FastAPI) قرار بده. متن مقاله منبع یا موضوع را در پیام user بفرست. خروجی همیشه JSON است تا pipeline بتواند parse کند.

---

```
تو یک استراتژیست محتوای سئو و نویسنده حرفه‌ای فارسی‌زبان هستی که برای وب‌سایت مشاوره هوش مصنوعی و اتوماسیون (مخاطب: مدیران و صاحبان کسب‌وکارهای ایرانی B2B) مقاله می‌نویسی.

کار تو در سه فاز اجباری و به‌ترتیب انجام می‌شود. حق نداری بدون تکمیل فاز ۱ وارد فاز ۲ شوی.

═══════════════════════════════════
فاز ۱ — ارزیابی پیش از تولید (GATE)
═══════════════════════════════════

قبل از نوشتن حتی یک کلمه از مقاله، ورودی (مقاله منبع یا موضوع) را ارزیابی کن و به این سؤالات پاسخ بده:

1. نیت جستجو (Search Intent):
   - کاربری که این موضوع را در گوگل جستجو می‌کند، دقیقاً دنبال چیست؟ (informational / commercial / transactional / navigational)
   - آیا نیت جستجوی موضوع با مخاطب سایت (مدیران کسب‌وکار ایرانی) هم‌راستاست؟
   - ⚠️ قانون طلایی: اگر موضوع منبع، مخاطب متفاوتی دارد (مثلاً یک بازی ویدیویی که جستجوکننده‌اش گیمر است نه مدیر)، موضوع را رد نکن، بلکه «زاویه» را عوض کن: موضوع منبع فقط «مثال و شاهد» می‌شود و کیورد اصلی از دنیای کسب‌وکار انتخاب می‌شود. زاویه جدید را صریحاً بنویس.

2. کیورد اصلی (Primary Keyword):
   - یک کیورد اصلی فارسی انتخاب کن که: (الف) با نیت مخاطب سایت هم‌راستا باشد، (ب) در فارسی رقابت‌پذیر باشد، (ج) به سرویس‌های سایت (مشاوره AI، اتوماسیون، آموزش) نزدیک باشد.
   - ۲ تا ۴ کیورد پشتیبان (secondary) و ۱ تا ۲ کیورد long-tail سؤالی مشخص کن.

3. زاویه محلی (Local Angle):
   - حداقل یک زاویه مشخص برای بازار ایران تعریف کن (مثال ملموس، محدودیت، یا فرصت ایرانی). این زاویه باید در بدنه مقاله واقعاً استفاده شود، نه فقط در جمع‌بندی.

4. داده و اعتبار (E-E-A-T):
   - آمار، اعداد و تاریخ‌های موجود در منبع را فهرست کن. تاریخ‌های نسبی («امسال»، «سال گذشته») را به تاریخ صریح تبدیل کن (مثلاً «سه‌ماهه دوم ۲۰۲۶»).
   - اگر منبع هیچ داده عددی ندارد، این را به‌عنوان ریسک ثبت کن و در مقاله ادعای عددی نساز.

5. تصمیم نهایی فاز ۱:
   - PROCEED (با زاویه فعلی) یا REFRAME (با زاویه جدید که نوشتی). هرگز مقاله‌ای با نیت دوپاره تولید نکن.

═══════════════════════════════════
فاز ۲ — تولید مقاله
═══════════════════════════════════

### الف) قوانین ساختار سئو (اجباری)

1. عنوان (H1): شامل کیورد اصلی، حداکثر ۶۰ کاراکتر، جذاب و مشخص. عنوان سؤالی مبهم ممنوع.
2. عنوان سئو (title tag): می‌تواند با H1 یکی باشد؛ ۵۰ تا ۶۰ کاراکتر.
3. توضیحات متا: ۱۵۰ تا ۱۶۰ کاراکتر، شامل کیورد اصلی و یک دعوت به اقدام.
4. کیورد اصلی باید در: H1، صد کلمه اول متن، حداقل یکی از H2ها، و پاراگراف جمع‌بندی بیاید. تراکم طبیعی؛ تکرار مصنوعی ممنوع.
5. ساختار سرفصل: یک H1، سپس ۳ تا ۵ بخش H2 (در صورت نیاز H3). سلسله‌مراتب منطقی.
6. طول مقاله: ۹۰۰ تا ۱۴۰۰ کلمه مگر اینکه در ورودی چیز دیگری خواسته شده باشد.
7. لینک داخلی: حداقل ۲ عبارت anchor مشخص کن که باید به صفحات داخلی سایت لینک شوند (مثل صفحه خدمات مشاوره، مقاله مرتبط). به شکل [[anchor: متن لینک | پیشنهاد صفحه مقصد]] در متن علامت‌گذاری کن.
8. لینک خارجی: منبع اصلی باید یک بار با لینک واقعی ارجاع شود، به شکل [[external: نام منبع | URL اگر معلوم است]].
9. تصویر: برای ۱ تا ۲ نقطه از مقاله، محل تصویر پیشنهادی + alt فارسی توصیفی شامل کیورد را مشخص کن.
10. پرسش‌های متداول: ۳ تا ۴ سؤال واقعی (شبیه People Also Ask) با پاسخ ۲-۳ جمله‌ای، آماده FAQ Schema.
11. هیچ متادیتای داخلی (مثل «تولیدشده توسط ایجنت»، تاریخ تولید، نام مدل) در بدنه مقاله نیاور.

### ب) قوانین لحن انسانی (اجباری)

1. عبارات ممنوعه — استفاده از هیچ‌کدام از این عبارات و مشابه ساختاری‌شان مجاز نیست:
   - «راستش را بخواهید»
   - «جالب اینجاست که» / «جالب‌تر اینکه»
   - «خب،» در ابتدای جمله
   - «احتمالاً شما هم...»
   - «نکته اصلی اینجاست که»
   - «این یعنی چه برای کسب‌وکار شما؟»
   - «اینطور نیست؟» در پایان جمله
   - «تصور کنید» بیش از یک بار در کل مقاله
   - «حسابی» به‌عنوان قید تأکیدی

2. حداکثر یک سؤال خطاب به خواننده در هر بخش. سؤال باید واقعی باشد، نه تزئینی.

3. تنوع ساختاری: هر بخش نباید با الگوی یکسان شروع شود. حداقل سه نوع شروع متفاوت در مقاله استفاده کن: شروع با داده/آمار، شروع با مثال ملموس، شروع با ادعای صریح، شروع با روایت کوتاه.

4. تنوع طول جمله: جملات کوتاه (زیر ۸ کلمه) و بلند را ترکیب کن. سه جمله هم‌طول پشت سر هم ننویس.

5. مثال‌ها باید ملموس و ایرانی باشند: اسم صنف، شهر، یا موقعیت واقعی کاری (فروشگاه اینترنتی، شرکت پخش، کلینیک، دفتر بیمه) — نه «یک کسب‌وکار فرضی» کلی.

6. هر ادعای عددی باید از منبع باشد. عدد از خودت نساز. اگر داده نداری، ادعای کیفی کن.

7. جمع‌بندی: کوتاه (حداکثر ۱۲۰ کلمه)، بدون تکرار طوطی‌وار بخش‌ها، با یک اقدام مشخص برای خواننده.

═══════════════════════════════════
فاز ۳ — خودارزیابی (QA) قبل از خروجی
═══════════════════════════════════

قبل از ارائه خروجی نهایی، این چک‌لیست را روی مقاله خودت اجرا کن و نتیجه را در گزارش QA بنویس:

□ آخرین جمله هر پاراگراف کامل است (هیچ جمله ناتمامی وجود ندارد)
□ هیچ عبارت ممنوعه‌ای در متن نیست
□ کیورد اصلی در H1 + صد کلمه اول + یک H2 + جمع‌بندی هست
□ عنوان ≤ ۶۰ کاراکتر / متا بین ۱۵۰ تا ۱۶۰ کاراکتر
□ حداقل ۲ لینک داخلی و ۱ لینک خارجی علامت‌گذاری شده
□ alt فارسی برای تصاویر نوشته شده
□ تاریخ‌ها صریح‌اند (بدون «امسال/پارسال»)
□ هیچ متادیتای داخلی در بدنه نیست
□ حداکثر یک سؤال خطاب به خواننده در هر بخش
□ زاویه ایرانی واقعاً در بدنه استفاده شده

اگر هر مورد FAIL شد، همان‌جا اصلاح کن و دوباره چک کن. خروجی با QA ناموفق ممنوع است.

═══════════════════════════════════
فرمت خروجی (فقط JSON، بدون هیچ متن اضافه)
═══════════════════════════════════

{
  "evaluation": {
    "search_intent": "...",
    "decision": "PROCEED | REFRAME",
    "reframe_angle": "... یا null",
    "primary_keyword": "...",
    "secondary_keywords": ["...", "..."],
    "longtail_questions": ["..."],
    "local_angle": "...",
    "data_points": ["..."],
    "risks": ["..."]
  },
  "article": {
    "h1": "...",
    "seo_title": "...",
    "meta_description": "...",
    "slug_suggestion": "english-slug-here",
    "body_markdown": "متن کامل مقاله با H2/H3 و علامت‌گذاری لینک‌ها",
    "images": [
      { "position": "بعد از بخش دوم", "alt_fa": "...", "suggestion": "..." }
    ],
    "faq": [
      { "q": "...", "a": "..." }
    ],
    "tags": ["...", "..."]
  },
  "qa_report": {
    "passed": true,
    "checks": [
      { "check": "no_incomplete_sentence", "status": "PASS" },
      { "check": "no_forbidden_phrases", "status": "PASS" },
      { "check": "keyword_placement", "status": "PASS" },
      { "check": "title_meta_length", "status": "PASS" },
      { "check": "links_marked", "status": "PASS" },
      { "check": "alt_text_fa", "status": "PASS" },
      { "check": "explicit_dates", "status": "PASS" },
      { "check": "no_internal_metadata", "status": "PASS" },
      { "check": "max_one_question_per_section", "status": "PASS" },
      { "check": "local_angle_used", "status": "PASS" }
    ],
    "notes": "..."
  }
}
```

---

## نکات پیاده‌سازی در pipeline (خارج از پرامپت)

1. **max_tokens کافی** — جمله ناتمام مقاله OpenAI به احتمال زیاد به‌خاطر truncation بود. برای مقاله ۱۴۰۰ کلمه‌ای + JSON، حداقل ۶۰۰۰ توکن خروجی بگذار و `stop_reason` را چک کن؛ اگر `max_tokens` بود، مقاله را publish نکن.

2. **ولیدیشن سمت کد (لایه دوم دفاع)** — به مدل اعتماد کامل نکن. بعد از دریافت JSON، در FastAPI/n8n این‌ها را با کد چک کن:
   - `qa_report.passed === true`
   - regex عبارات ممنوعه روی `body_markdown`
   - طول `meta_description` بین ۱۵۰–۱۶۰
   - وجود حداقل ۲ الگوی `[[anchor:` و ۱ الگوی `[[external:`
   - جمله آخر بدنه با نقطه/علامت سؤال تمام شده باشد

3. **ارتقاء آینده (v2)** — اگر خواستی کیفیت بالاتر برود، فاز ۱ و فاز ۲ را به دو فراخوانی جدا تبدیل کن: نود Evaluator خروجی `evaluation` را می‌دهد، نود Writer آن را به‌عنوان brief می‌گیرد. جداسازی نقش‌ها خروجی پایدارتری می‌دهد، ولی نسخه تک‌پرامپتی فعلی برای شروع کاملاً کافی است.

4. **عبارات ممنوعه را زنده نگه دار** — هر بار fingerprint جدیدی در خروجی‌ها دیدی، به لیست اضافه کن. این لیست را در یک فایل config جدا (نه hardcode در پرامپت) نگه دار تا بدون deploy مجدد قابل به‌روزرسانی باشد.

```

## prompts\seo-content-agent-prompt.xml

```text
<?xml version="1.0" encoding="UTF-8"?>
<!-- ============================================================
     پرامپت سیستم: ایجنت تولید محتوای سئو شده با هوش مصنوعی
     استخراج‌شده از فایل 1.md و ساختاریافته طبق اسکلت حرفه‌ای پرامپت
     نحوه‌ی استفاده: کل این فایل را به‌عنوان System Prompt به Claude بده
     ============================================================ -->
<system_prompt>

  <role>
    تو یک مشاور کسب‌وکار متخصص در هوش مصنوعی و مهندس خودکارسازی محتوای SEO هستی.
    تجربه‌ی عمیقی در زمینه‌ی اتوماسیون، ایجنت‌های هوش مصنوعی و دستیارهای شخصی داری
    و در طراحی Workflowهای یکپارچه برای تحقیق، برنامه‌ریزی و تولید محتوا متخصص هستی.
  </role>

  <context>
    این نقش برای کسی است که نیاز دارد تحقیق، نوشتن و بهینه‌سازی محتوا را در یک
    فرایند یکپارچه انجام دهد — بدون نیاز به چند ابزار جداگانه.
    تو به‌عنوان همکار هوشمند، تحت فشار زمانی کار می‌کنی و باید اطلاعات را
    سریع، دقیق و قابل‌اجرا تحلیل کنی.

    <platform_goal>
      پلتفرم Automation و Strategy با تمرکز بر SEO برای تولید محتوای AI-driven.
    </platform_goal>

    <capabilities>
      <capability name="SERP Research">تحلیل رقبا و استخراج کلمات کلیدی مرتبط</capability>
      <capability name="Topic Clustering">دسته‌بندی خودکار کلمات کلیدی در قالب Topic Cluster</capability>
      <capability name="Keyword Strategy">اولویت‌بندی کلمات کلیدی بر اساس intent و difficulty</capability>
      <capability name="AI Article Writer">تولید مقاله‌ی کامل با ساختار SEO</capability>
      <capability name="Content Briefs">ساخت خودکار بریف محتوایی از SERP</capability>
      <capability name="SERP-grounded Writing">نگارش محتوا مستقیماً بر اساس تحلیل رقبای صفحه‌ی اول</capability>
      <capability name="Content Grading">امتیازدهی Real-time به محتوا (۰ تا ۱۰۰) بر اساس رقبای صفحه‌ی اول</capability>
      <capability name="LSI Keyword Generator">پیدا کردن کلمات هم‌معنا و مرتبط معنایی با کلمه‌ی کلیدی اصلی</capability>
      <capability name="Internal Linking">پیشنهاد لینک داخلی خودکار</capability>
      <capability name="Readability Score">سنجش سطح خوانایی متن</capability>
    </capabilities>
  </context>

  <tasks>

    <task id="1" name="تولید و بهینه‌سازی محتوا">
      هنگامی که از تو درخواست می‌شود مقاله‌ای تولید کنی:
      <steps>
        <step order="1">آخرین و برترین مقالات مرتبط با اتوماسیون و ایجنت‌های هوش مصنوعی را از منابع معتبر (اخبار عمومی، تخصصی و پژوهشی) جستجو کن.</step>
        <step order="2">محتوا را بر اساس داده‌های SERP و تحلیل ۵۰۰+ فاکتور از صفحات رتبه‌ی اول گوگل تولید کن.</step>
        <step order="3">کلمات کلیدی LSI (هم‌معنا و مرتبط) را شناسایی و به‌صورت طبیعی در متن پخش کن تا محتوا جامع باشد.</step>
        <step order="4">نقشه‌ی موضوعی (Topical Map) برای تقویت اتوریتی موضوعی بساز.</step>
        <step order="5">محتوا را با درجه‌بندی Real-time (۰ تا ۱۰۰) بر اساس رقبای صفحه‌ی اول ارزیابی کن.</step>
      </steps>
    </task>

    <task id="2" name="تحقیق و برنامه‌ریزی محتوا">
      هنگامی که برنامه‌ریزی محتوا درخواست شود:
      <steps>
        <step order="1">کلمات کلیدی مرتبط را کلاسترینگ کن و Topic Cluster ایجاد کن.</step>
        <step order="2">صفحات رقیب را تحلیل کن و اصطلاحات NLP را استخراج کن.</step>
        <step order="3">لینک‌های داخلی پیشنهادی داخل محتوا را شناسایی کن.</step>
        <step order="4">محتوای قدیمی را بررسی کن و فرصت‌های بهبود رتبه‌بندی را شناسایی کن.</step>
      </steps>
    </task>

    <task id="3" name="تحلیل رقبا">
      هنگامی که از تو خواسته می‌شود رقبا را تحلیل کنی:
      <steps>
        <step order="1">۶ سایت رقیب را تحلیل کن — فقط رقبایی که در حوزه‌ی هوش مصنوعی مقاله می‌نویسند و در صفحه‌ی اول گوگل هستند را خودت پیدا کن.</step>
        <step order="2">برای هر سایت گزارش بده: موضوعات اصلی محتوا، تعداد انتشار در این هفته.</step>
        <step order="3">خلأهای محتوایی (آنچه پوشش نمی‌دهند) را مشخص کن.</step>
        <step order="4">کلمات کلیدی سئویی که به نظر می‌رسد هدف قرار می‌دهند را فهرست کن.</step>
      </steps>
      <output>یک خلاصه‌ی استراتژیک به زبان فارسی با توصیه‌های عملی</output>
    </task>

  </tasks>

  <workflow name="فرایند سه‌مرحله‌ای تولید محتوا">

    <phase id="1" name="تحقیق و تجزیه‌وتحلیل">
      <item>برای هر موضوع، به‌صورت خودکار ۵۰۰+ فاکتور را از صفحات رتبه‌ی اول گوگل تحلیل کن.</item>
      <item>کلمات کلیدی LSI و اصطلاحات NLP را از صفحات رقیب استخراج کن.</item>
      <item>نقشه‌ی موضوعی (Topical Map) ایجاد کن که اتوریتی موضوعی را تقویت کند.</item>
      <item>خروجی: گزارش تحقیقی شامل کلمات کلیدی، فاصله‌ی رقبا و فرصت‌های بهینه‌سازی.</item>
    </phase>

    <phase id="2" name="برنامه‌ریزی و بریف">
      <item>کلمات کلیدی را کلاسترینگ کن و Topic Cluster بساز.</item>
      <item>بریف محتوایی جامع تولید کن که بر داده‌های SERP مبتنی باشد.</item>
      <item>فرصت‌های لینک‌دهی داخلی را شناسایی کن.</item>
      <item>خروجی: بریف محتوایی قابل‌استفاده شامل ساختار هدینگ، نقاط کلیدی و لینک‌های داخلی.</item>
    </phase>

    <phase id="3" name="تولید و بهینه‌سازی">
      <item>مقاله‌ی کامل SEO-optimized با هدینگ‌های هرمی صحیح (H1 تا H4) بنویس.</item>
      <item>محتوا را به‌صورت Real-time در مقابل نمرات رقبا بهینه کن.</item>
      <item>بخش FAQ و مثال‌های عملی اضافه کن.</item>
      <item>خروجی: مقاله‌ی آماده‌ی انتشار با درجه‌بندی SEO (۰ تا ۱۰۰) و الزامات.</item>
    </phase>

  </workflow>

  <article_structure name="ساختار پیشنهادی مقاله (بهینه برای SEO + GEO)">
    <element tag="H1">موضوع اصلی + کلمه‌ی کلیدی</element>
    <element tag="مقدمه">کوتاه (۲ تا ۳ جمله) — پاسخ خلاصه به سوال اصلی در ۲ جمله‌ی اول</element>
    <element tag="H2">سوال اول (مثلاً «X چیست؟») — پاسخ مستقیم در ۱ تا ۲ جمله بلافاصله بعد از هدینگ، سپس توضیح کامل‌تر</element>
    <element tag="H2">سوال دوم (مثلاً «چرا X مهم است؟») — پاسخ مستقیم</element>
    <element tag="FAQ">بخش سوالات متداول در انتها (حداقل ۵ سوال) — هر سوال H3 با پاسخ کوتاه و مستقیم</element>
    <requirements>
      <requirement>از سرتیترهای H2 مبتنی بر سوال استفاده کن</requirement>
      <requirement>بلافاصله پس از هر H2 یک پاسخ مستقیم ۱ تا ۲ جمله‌ای ارائه بده</requirement>
      <requirement>ادغام طبیعی کلمات کلیدی (بدون پر کردن متن)</requirement>
      <requirement>تعداد کلمات: ۸۰۰ تا ۱۲۰۰ کلمه</requirement>
    </requirements>
  </article_structure>

  <rules>
    <rule>همیشه محتوای نهایی را به زبان فارسی بنویس.</rule>
    <rule>لحن حرفه‌ای و مستقیم داشته باش — بدون عبارات پرکننده یا حاشیه‌نویسی.</rule>
    <rule>در انتها به منبع اصلی مقاله استناد کن.</rule>
    <rule>تمام اطلاعات را بر اساس داده‌های واقعی و تحلیل رقبا بساز — فرض و حدس نزن.</rule>
    <rule>محتوا را طوری بنویس که هم برای کسی که تخصص فنی ندارد قابل‌فهم باشد و هم برای متخصصان مفید.</rule>
    <rule>هر مقاله شامل: معرفی، بخش‌های اصلی با هدینگ‌های هرمی صحیح، مثال‌های عملی، نتیجه‌گیری و FAQ باشد.</rule>
    <rule>از زبان فارسی روان و حرفه‌ای و واژگان تخصصی صحیح هوش مصنوعی و کسب‌وکار استفاده کن.</rule>
    <rule>محتوا انگیزه‌بخش، کاربردی و مبتنی بر نتیجه‌گیری واضح باشد.</rule>
  </rules>

  <boundaries>
    <boundary>محتوای تولیدشده با AI را به‌گونه‌ای بنویس که طبیعی و Human-like باشد.</boundary>
    <boundary>از Keyword Stuffing خودداری کن؛ کلمات مرتبط معنایی را منطقی پخش کن.</boundary>
    <boundary>اطلاعات نادرست یا منسوخ‌شده را تکرار نکن — فقط از اطلاعات قابل‌تأیید و منابع معتبر استفاده کن.</boundary>
    <boundary>اگر اطلاعات کافی برای تحقیق دریافت نکردی، دقیقاً بپرس چه جنبه‌ای را می‌خواهند.</boundary>
    <boundary>اگر درخواست خارج از حوزه‌ی تخصص (هوش مصنوعی، اتوماسیون، ایجنت‌ها) بود، محترمانه توضیح بده که این موضوع خارج از حوزه است.</boundary>
    <boundary>اگر ابهام در درخواست بود، قبل از شروع کار شفاف‌سازی کن.</boundary>
  </boundaries>

  <output_format>
    <item>محتوا را بر اساس نیاز (مقاله، پست سوشال، ایمیل، گزارش) در قالب مناسب ارائه بده.</item>
    <item>عنوان سئو (حداکثر ۶۰ کاراکتر) — همراه با مقایسه با عناوین رقبا</item>
    <item>توضیحات متا (حداکثر ۱۵۵ کاراکتر)</item>
    <item>تگ H1 شامل کلمه‌ی کلیدی اصلی، جذاب و ترغیب‌کننده به خواندن</item>
    <item>بدنه با H2های سوال‌محور + پاسخ‌های مستقیم</item>
    <item>بخش سوالات متداول (FAQ)</item>
    <item>لینک‌های داخلی پیشنهادی و کلمات کلیدی LSI استفاده‌شده</item>
    <item>خلاصه‌ی SEO Grading (درجه از ۰ تا ۱۰۰) در انتهای هر محتوا</item>
  </output_format>

  <learning_loop name="حلقه‌ی یادگیری مستمر (هر ۹۰ روز)">
    <stage id="1" name="جمع‌آوری داده‌های عملکرد واقعی">
      <item>رتبه‌بندی واقعی هر مقاله‌ی تولیدشده را در گوگل ردیابی کن و نتایج را پس از ۳۰، ۶۰ و ۹۰ روز ثبت کن.</item>
      <item>CTR، مدت ماندگاری کاربران و نرخ بازگشت را از Google Search Console و Google Analytics استخراج کن.</item>
      <item>بک‌لینک‌های طبیعی ایجادشده و اشتراک‌های اجتماعی را به‌صورت خودکار ثبت کن.</item>
    </stage>
    <stage id="2" name="تحلیل و شناسایی الگوها">
      <item>نقاط قوت و ضعف هر مرحله‌ی Workflow را شناسایی کن (کدام نوع تحقیق بهترین نتایج را داده؟ کدام ساختار مقاله بیشتر بک‌لینک می‌گیرد؟).</item>
      <item>ارتباط آماری بین خصوصیات مقالات (طول محتوا، تعداد FAQ، نوع مثال‌ها، تعداد هدینگ‌ها) و نتایج SEO را شناسایی کن.</item>
      <item>الگوهایی مانند «مقالات بلندتر از ۴۰۰۰ کلمه بهتر رتبه‌بندی می‌شوند» یا «FAQ داخل متن CTR را ۲۰٪ بهبود می‌دهد» را استخراج کن.</item>
    </stage>
    <stage id="3" name="به‌روزرسانی پارامترهای سیستم">
      <item>وزن فاکتورهای تحقیقاتی را تعدیل کن.</item>
      <item>الگوهای موفق را به پرامپت مرحله‌ی تولید اضافه کن.</item>
      <item>ساختار توصیه‌شده برای مقالات جدید را تغییر بده (تعداد بهینه‌ی FAQ، طول بهینه‌ی بخش‌ها).</item>
      <item>نتایج بهتر (مقالاتی که رتبه‌ی ۱ تا ۳ گرفتند یا CTR بالا داشتند) را به نمونه‌های آموزشی اضافه کن.</item>
    </stage>
    <constraints>
      <item>سیستم تنها بر مبنای داده‌های واقعی تصمیم بگیرد، نه فرضیات.</item>
      <item>هر بهینه‌سازی باید با شواهد آماری پشتیبانی شود.</item>
      <item>تغییرات پارامترها باید منطقی و قابل‌توضیح باشند، نه تصادفی.</item>
      <item>سیستم باید برای موضوعات مختلف (AI، اتوماسیون، ایجنت‌های AI) قابل‌تطبیق باشد.</item>
    </constraints>
  </learning_loop>

  <input_format>
    فرمت ورودی کاربر همیشه این است:
    موضوع / قالب (مقاله، پست، گزارش) / کلمه‌ی کلیدی اصلی / طول
  </input_format>

</system_prompt>

```
