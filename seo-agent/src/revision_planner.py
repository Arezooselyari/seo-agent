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


def build_mandatory_cleanup_plan(payload: dict, cleanup_targets: list[dict]) -> dict:
    """پلن پاک‌سازی اجباری (v2.1.1) — قطعی و بدون LLM: هر هدفِ دارای exact_span
    یک پچ حذف/خنثی‌سازی می‌شود. Planner حق ساخت replacement غیرخنثی ندارد.
    """
    patches = []
    for t in cleanup_targets:
        action = ("neutralize"
                  if t.get("required_action") in ("neutralize", "remove_or_neutralize")
                  else "remove")
        patches.append({
            "section": "global",
            "scope": "span",
            "severity": "high",
            "exact_span": t.get("exact_span"),
            "category": t.get("category"),
            "action": action,
            "current_text_hint": (t.get("claim") or t.get("exact_span") or "")[:60],
            "instruction": (
                f"عبارت «{t.get('exact_span')}» یک ادعای کمی/ممنوعه‌ی بی‌منبع است: "
                "یا جمله‌ی حامل آن را حذف کن، یا به بیان شرطیِ وابسته به شرایط پروژه و "
                "غیرکمی تبدیل کن (مثل «به دامنه پروژه بستگی دارد»). اتصال دستوری بعد از "
                "حذف را اصلاح کن. اگر حذف/خنثی‌سازی امن نیست، unresolved گزارش کن."
            ),
            "rule": "fact_policy / soft_quantitative_claim_policy",
            "must_preserve": ["h2_structure", "link_markers", "verified_facts",
                              "locked_numbers"],
            "must_not_add": ["number", "percentage", "price", "duration",
                             "frequency_claim", "performance_claim",
                             "first_person_experience", "case_study", "cta",
                             "brand", "url", "entity"],
        })
    return {
        "mode": "mandatory_cleanup",
        "patches": patches,
        "preserve_sections": ["تمام بخش‌های خارج از spanهای هدف — کلمه‌به‌کلمه"],
        "summary": f"پاک‌سازی اجباری {len(patches)} ادعای بی‌منبع/عبارت ممنوعه",
    }


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
