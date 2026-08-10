# بکاپ قبل از Content Quality Gate
تاریخ: 2026-07-17T08:27:09.991972


---

## `seo-agent/src/qa_analyzer.py`

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


---

## `seo-agent/src/evaluate_and_sync.py`

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
    html_export,
    qa_analyzer,
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
        )
        if ok:
            logger.info(f"مقاله #{result['article_id']} برای تایید به تلگرام ارسال شد (نمره: {result['seo_grade']})")


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
    2. معیار عبور: qa_report.passed==true  و  overall_score>=threshold  و  چک‌های کد.
    3. عبور → مقاله‌ی بازنویسی‌شده ذخیره و به تلگرام ارسال می‌شود.
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
        minimum_score = int(qa_cfg.get("minimum_score", threshold))

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

            # ثبت ایرادات دور اول در حافظه‌ی تحریریه
            editor_memory.record_issues(analysis.get("issues", []))

            # ── حلقه‌ی تحریریه: برنامه‌ریزی → بازنویسی پچی → QA مجدد ──
            revision_history = []
            revision = 0
            # بهترین نسخه در طول حلقه — اگر دوری نمره را بدتر کرد، به این برمی‌گردیم
            best_payload, best_analysis = payload, analysis
            while (
                rewrite_enabled
                and analysis["overall_score"] < minimum_score
                and analysis.get("issues")
                and revision < max_revision
            ):
                revision += 1
                score_before = analysis["overall_score"]
                issues_before = len(analysis.get("issues", []))
                logger.info(
                    f"🛠 مقاله #{article_id} — دور اصلاح {revision}/{max_revision} "
                    f"(نمره {score_before}، {issues_before} ایراد)"
                )
                try:
                    plan = revision_planner.build_plan(
                        payload, analysis["issues"], score_before, revision
                    )
                    if not plan.get("patches"):
                        logger.info("برنامه‌ی اصلاح پچی نداشت؛ حلقه متوقف شد.")
                        break
                    payload = writer.rewrite_article(payload, plan, revision_no=revision)
                    analysis = qa_analyzer.analyze_article(payload, threshold=threshold)
                    analysis = qa_analyzer.merge_semrush(analysis, semrush_report)
                    editor_memory.record_issues(analysis.get("issues", []))
                    revision_history.append({
                        "revision": revision,
                        "score_before": score_before,
                        "score_after": analysis["overall_score"],
                        "issues_before": issues_before,
                        "issues_after": len(analysis.get("issues", [])),
                        "patches": len(plan.get("patches", [])),
                        "plan_summary": plan.get("summary", ""),
                    })
                    logger.info(
                        f"   دور {revision}: نمره {score_before} → {analysis['overall_score']}"
                    )
                    if analysis["overall_score"] > best_analysis["overall_score"]:
                        best_payload, best_analysis = payload, analysis
                except Exception as e:
                    logger.error(f"خطا در دور اصلاح {revision} مقاله #{article_id}: {e}", exc_info=True)
                    break

            # اگر آخرین دور بدتر از بهترین بود، بهترین نسخه را برگردان
            if best_analysis["overall_score"] > analysis["overall_score"]:
                logger.info(
                    f"   نسخه‌ی آخر ({analysis['overall_score']}) بدتر از بهترین ({best_analysis['overall_score']}) بود؛ بهترین نگه داشته شد."
                )
                payload, analysis = best_payload, best_analysis

            score = analysis["overall_score"]
            title = payload.get("title_seo") or payload.get("h1", "")

            # گیت نهایی: qa پاس + نمره + (اگر SEMrush هست) کیوردها ضعیف نباشند
            passed = analysis["passed"] and not analysis.get("semrush_weak")

            if passed:
                # payload ممکن است حاصل بازنویسی تحریریه باشد؛ نمره و تاریخچه ضمیمه می‌شود
                merged = dict(payload)
                merged["seo_grade"] = score
                merged["qa_analysis"] = {
                    "overall_score": score,
                    "qa_report": analysis["qa_report"],
                    "evaluation": analysis["evaluation"],
                    "semrush": analysis.get("semrush"),
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
                    "preview": preview,
                })
                logger.info(f"✅ مقاله #{article_id} عبور کرد (نمره {score}) — متن اصلی حفظ شد")
            else:
                # حتی در عدم عبور، آخرین نسخه‌ی بازنویسی‌شده + تاریخچه ذخیره شود
                # تا کار حلقه‌ی تحریریه از بین نرود و بررسی دستی راحت باشد
                if revision_history:
                    merged = dict(payload)
                    merged["seo_grade"] = score
                    merged["qa_analysis"] = {
                        "overall_score": score,
                        "qa_report": analysis["qa_report"],
                        "evaluation": analysis["evaluation"],
                        "semrush": analysis.get("semrush"),
                        "issues_remaining": analysis.get("issues", []),
                        "revision_history": revision_history,
                    }
                    db.update_payload(conn, article_id, merged)
                needs_review.append({
                    "article_id": article_id,
                    "title": title,
                    "seo_grade": score,
                    "reasons": analysis["reasons"],
                })
                logger.info(f"📌 مقاله #{article_id} needs_review — دلایل: {analysis['reasons']}")

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
        if approved:
            config = load_settings()
            await process_approved_articles(approved, config)


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


---

## `seo-agent/src/html_export.py`

```python
"""ذخیره‌ی مقاله‌ی نهایی (بازنویسی‌شده) به‌صورت فایل HTML برای تحلیل دستی.

هر مقاله‌ی عبورکرده در پوشه‌ی output/ به‌صورت article-<id>-<slug>.html ذخیره می‌شود.
شامل عنوان، متا، نمره، بدنه، FAQ و گزارش QA است.
"""
import html
import re

from .config import OUTPUT_DIR


def _md_to_html(text: str) -> str:
    """تبدیل ساده‌ی markdown به HTML (اگر متن قبلاً HTML باشد دست‌نخورده می‌ماند)."""
    if "<p>" in text or "<h2" in text:
        return text  # قبلاً HTML است

    # نشانگرهای لینک داخلی/خارجی پرامپت را قابل‌خواندن کن
    text = re.sub(r"\[\[anchor:\s*([^|\]]+)\|([^\]]+)\]\]", r"<a href='#'>\1</a> <small>(لینک داخلی: \2)</small>", text)
    text = re.sub(r"\[\[external:\s*([^|\]]+)\|([^\]]+)\]\]", r"<a href='\2'>\1</a>", text)

    lines = text.split("\n")
    out = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.startswith("### "):
            out.append(f"<h3>{s[4:]}</h3>")
        elif s.startswith("## "):
            out.append(f"<h2>{s[3:]}</h2>")
        elif s.startswith("# "):
            out.append(f"<h1>{s[2:]}</h1>")
        else:
            out.append(f"<p>{s}</p>")
    return "\n".join(out)


def export_article(article_id: int, payload: dict) -> str:
    """مقاله را به یک فایل HTML می‌نویسد و مسیر آن را برمی‌گرداند."""
    title = payload.get("title_seo") or payload.get("h1", "بدون عنوان")
    meta = payload.get("meta_description", "")
    slug = payload.get("slug", f"article-{article_id}")
    score = payload.get("seo_grade", "-")
    body_raw = payload.get("body_markdown") or payload.get("body_html", "")
    body_html = _md_to_html(body_raw)

    faq = payload.get("faq", [])
    faq_html = ""
    if faq:
        items = "\n".join(
            f"<details><summary>{html.escape(f.get('q',''))}</summary><p>{html.escape(f.get('a',''))}</p></details>"
            for f in faq
        )
        faq_html = f"<section class='faq'><h2>پرسش‌های متداول</h2>{items}</section>"

    qa = payload.get("qa_analysis", {})

    # بخش تحلیل SEMrush (فاز C) — اگر موجود باشد
    semrush_html = ""
    sr = qa.get("semrush")
    if sr:
        per = sr.get("per_kw", {}) or {}
        rows = "\n".join(
            f"<tr><td>{html.escape(str(k))}</td><td>{html.escape(str(v.get('volume','-')))}</td>"
            f"<td>{html.escape(str(v.get('kd','-')))}</td></tr>"
            for k, v in per.items()
        )
        semrush_html = (
            f"<section class='semrush'><h2>تحلیل SEMrush</h2>"
            f"<p><strong>نتیجه:</strong> {html.escape(str(sr.get('verdict','-')))} "
            f"&nbsp;|&nbsp; <strong>میانگین سختی (KD):</strong> {html.escape(str(sr.get('avg_kd','-')))}</p>"
            f"<table><tr><th>کیورد</th><th>حجم</th><th>KD</th></tr>{rows}</table>"
            f"<p><small>{html.escape(str(sr.get('notes','')))}</small></p></section>"
        )

    # تاریخچه‌ی ویرایش تحریریه (حلقه‌ی اصلاح)
    revision_html = ""
    history = qa.get("revision_history") or []
    remaining = qa.get("issues_remaining") or []
    if history or remaining:
        hist_rows = "\n".join(
            f"<tr><td>{h.get('revision','-')}</td>"
            f"<td>{h.get('score_before','-')} → {h.get('score_after','-')}</td>"
            f"<td>{h.get('issues_before','-')} → {h.get('issues_after','-')}</td>"
            f"<td>{h.get('patches','-')}</td>"
            f"<td>{html.escape(str(h.get('plan_summary','')))}</td></tr>"
            for h in history
        )
        remain_items = "\n".join(
            f"<li><strong>{html.escape(str(i.get('category','')))}</strong> "
            f"({html.escape(str(i.get('severity','')))}) — "
            f"{html.escape(str(i.get('problem','')))}</li>"
            for i in remaining
        )
        remain_block = (
            f"<h3>ایرادات باقی‌مانده ({len(remaining)})</h3><ul>{remain_items}</ul>"
            if remaining else "<p>✔ هیچ ایراد بازی نمانده است.</p>"
        )
        revision_html = (
            f"<section class='qa'><h2>تاریخچه‌ی ویرایش تحریریه</h2>"
            f"<p><strong>تعداد دورهای اصلاح:</strong> {len(history)} "
            f"&nbsp;|&nbsp; <strong>نمره‌ی نهایی:</strong> {score}</p>"
            + (
                f"<table><tr><th>دور</th><th>نمره</th><th>ایرادات</th>"
                f"<th>پچ‌ها</th><th>خلاصه</th></tr>{hist_rows}</table>"
                if history else ""
            )
            + remain_block
            + "</section>"
        )

    qa_html = ""
    if qa:
        checks = qa.get("qa_report", {}).get("checks", [])
        rows = "\n".join(
            f"<tr><td>{html.escape(c.get('check',''))}</td><td>{html.escape(str(c.get('status','')))}</td></tr>"
            for c in checks
        )
        qa_html = (
            f"<section class='qa'><h2>گزارش QA (نمره: {score})</h2>"
            f"<table><tr><th>چک</th><th>وضعیت</th></tr>{rows}</table></section>"
        )

    doc = f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(meta)}">
<style>
  body {{ font-family: Tahoma, Vazirmatn, sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; line-height: 1.9; color: #1a1a1a; }}
  .meta-box {{ background: #f5f5f5; border-right: 4px solid #2a9d5c; padding: 1rem; margin-bottom: 2rem; font-size: .9rem; }}
  h1 {{ color: #1a5c38; }}
  h2 {{ color: #2a9d5c; border-bottom: 1px solid #ddd; padding-bottom: .3rem; }}
  .qa table {{ border-collapse: collapse; width: 100%; }}
  .qa td, .qa th {{ border: 1px solid #ccc; padding: .4rem .8rem; text-align: right; }}
  details {{ margin: .5rem 0; }}
  summary {{ cursor: pointer; font-weight: bold; }}
</style>
</head>
<body>
  <div class="meta-box">
    <strong>عنوان سئو:</strong> {html.escape(title)} ({len(title)} کاراکتر)<br>
    <strong>متا:</strong> {html.escape(meta)} ({len(meta)} کاراکتر)<br>
    <strong>Slug:</strong> {html.escape(slug)} &nbsp;|&nbsp; <strong>نمره:</strong> {score}
  </div>
  <article>
    {body_html}
  </article>
  {faq_html}
  {semrush_html}
  {revision_html}
  {qa_html}
</body>
</html>
"""
    safe_slug = re.sub(r"[^a-zA-Z0-9\-]", "-", slug)[:50]
    path = OUTPUT_DIR / f"article-{article_id}-{safe_slug}.html"
    path.write_text(doc, encoding="utf-8")
    return str(path)

```


---

## `seo-agent/config/settings.yaml`

```yaml
# تنظیمات عمومی ایجنت

# ارائه‌دهنده‌ی مدل: anthropic | gemini
provider: "gemini"

# مدل‌ها (Anthropic)
models:
  cheap: "claude-haiku-4-5-20251001"   # فیلتر و استخراج
  main: "claude-fable-5"               # تولید مقاله‌ی نهایی

# مدل‌ها (Gemini) — کلید شخصی (paid tier)
gemini_models:
  cheap: "gemini-flash-lite-latest"    # فیلتر و استخراج و ترجمه (ارزان و سریع، alias پایدار)
  main: "gemini-2.5-flash"             # تولید و تحلیل نهایی

# SEMrush (کیوردریسرچ قبل از تولید + تحلیل سئو بعد از تولید)
# نکته: تماس‌های SEMrush را Claude با کانکتور MCP می‌زند (نیمه‌دستی)؛ کد فقط فایل واسط را می‌خواند.
semrush:
  enabled: true
  market: "us"      # دیتابیس کیورد (جهانی/انگلیسی — پوشش فارسی SEMrush ضعیف است)
  kd_max: 40        # حداکثر سختی کیورد (Keyword Difficulty) قابل‌قبول برای انتخاب

# جمع‌آوری
collect:
  max_per_source: 15        # حداکثر مقاله‌ی اخیر از هر منبع
  max_age_days: 7           # فقط مقالات یک هفته‌ی اخیر
  top_n_articles: 4         # چند مقاله‌ی برتر تحلیل عمیق شوند
  min_relevance: 6          # حداقل امتیاز ارتباط (۰ تا ۱۰)
  request_delay_seconds: 2  # تأخیر بین درخواست‌ها

# مقاله‌ی خروجی
article:
  language: "fa"
  min_words: 800
  max_words: 1200
  min_faq: 5

# تصاویر
images:
  featured: 1
  inline: 2

# انتشار
publish:
  hour: 12                  # ساعت انتشار
  default_status: "publish" # publish | draft
  category_ids: []          # شناسه‌ی دسته‌های وردپرس (بعد از اتصال پر کن)

# کانال تأیید: telegram | email | both
approval_channel: "telegram"

# تلگرام
telegram:
  bot_token: "${TELEGRAM_BOT_TOKEN}"  # از .env می‌خوانده می‌شود
  chat_id: "${TELEGRAM_CHAT_ID}"      # از .env می‌خوانده می‌شود

# ارزیابی SEO
evaluation:
  approval_threshold: 90              # حداقل امتیاز برای تایید خودکار
  approval_interval_seconds: 300      # بررسی‌ی هر N ثانیه (۵ دقیقه)

# گردش کار تحریریه (Editorial Workflow) — حلقه‌ی اصلاح خودکار
qa:
  minimum_score: 90        # هدف حلقه‌ی اصلاح (هم‌راستا با approval_threshold)
  max_revision: 3          # حداکثر چرخه‌ی بازنویسی برای هر مقاله
  rewrite_enabled: true    # اگر false، رفتار قدیمی: ردشده → needs_review

writer:
  humanize: true
  preserve_good_sections: true   # بخش‌های سالم دست نمی‌خورند
  patch_rewrite: true            # فقط بخش‌های معیوب بازنویسی می‌شوند

editor_memory:
  enabled: true
  minimum_occurrence: 3    # الگوی خطا بعد از N بار تکرار وارد حافظه می‌شود

```
