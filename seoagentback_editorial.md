# بکاپ قبل از Editorial Workflow Redesign

تاریخ: 2026-07-16T09:42:50.457677

برای بازگردانی: محتوای هر بخش را در مسیر ذکرشده کپی کنید.


---

## `seo-agent/src/writer.py`

```python
"""گام ۳ — تولید مقاله‌ی فارسی سئو شده با Fable 5.

پرامپت سیستم: prompts/seo-content-agent-prompt.xml (با Prompt Caching).
"""
import json

from . import llm, semrush_bridge
from .config import env, load_settings

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

    payload = llm.ask(
        step="article_writing",
        user_content=WRITE_PROMPT.format(
            brief=json.dumps(brief, ensure_ascii=False, indent=1),
            target_keywords=kw_block,
            min_words=cfg["min_words"],
            max_words=cfg["max_words"],
            min_faq=cfg["min_faq"],
        ),
        model_tier="main",
        system=llm.system_prompt_xml(),
        cache_system=True,
        max_tokens=12000,
    )
    payload["topic"] = brief["topic"]
    payload["source_urls"] = brief["source_urls"]
    if keywords:
        payload["target_keywords"] = keywords
    word_count = len(payload.get("body_html", "").split())
    print(f"[writer] ✓ مقاله تولید شد: «{payload.get('title_seo')}» (~{word_count} کلمه، نمره {payload.get('seo_grade')})")
    return payload

```


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

    # جمله‌ی آخر کامل باشد (تشخیص truncation). ابتدا تگ‌های HTML انتهایی (</p> و …)
    # و سپس نشانگرهای markdown و فاصله‌ها را حذف کن تا لینک/فرمت پایانی اشتباه شمرده نشود.
    stripped = re.sub(r"(?:<[^>]+>|\s)+$", "", body)          # تگ‌های HTML و فاصله‌ی انتهایی
    stripped = stripped.rstrip("]})*_>#- \n\t")
    last_char_ok = bool(stripped) and stripped[-1] in ".!?۔؟:"

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

from . import db, evaluator, html_export, qa_analyzer, semrush_bridge, telegram_approver
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

            logger.info(f"📌 مقاله #{article_id} نیاز به بررسی دارد (score: {seo_grade} < 90)")

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

        for article in pending:
            article_id = article["id"]
            payload = article["payload"]
            try:
                analysis = qa_analyzer.analyze_article(payload, threshold=threshold)
            except Exception as e:
                logger.error(f"خطا در تحلیل مقاله #{article_id}: {e}", exc_info=True)
                continue

            # فاز C: تحلیل SEMrush. اگر کلید API باشد و هنوز تحلیلی نباشد، خودکار اجرا کن
            semrush_report = semrush_bridge.load_analysis(article_id)
            if semrush_report is None and env("SEMRUSH_API_KEY"):
                tk = payload.get("target_keywords", {})
                kw_list = list((tk.get("per_kw") or {}).keys()) or (
                    [tk.get("primary")] if tk.get("primary") else []
                )
                if kw_list:
                    try:
                        from . import semrush_api
                        semrush_report = semrush_api.analyze_article_keywords(article_id, kw_list)
                    except Exception as e:
                        logger.warning(f"تحلیل خودکار SEMrush مقاله #{article_id} نشد: {e}")
            analysis = qa_analyzer.merge_semrush(analysis, semrush_report)

            score = analysis["overall_score"]
            title = payload.get("title_seo") or payload.get("h1", "")

            # گیت نهایی: qa پاس + نمره + (اگر SEMrush هست) کیوردها ضعیف نباشند
            passed = analysis["passed"] and not analysis.get("semrush_weak")

            if passed:
                # حالت سخت‌گیرانه: متن اصلی دست‌نخورده می‌ماند؛ فقط نمره و تحلیل اضافه می‌شود
                merged = dict(payload)
                merged["seo_grade"] = score
                merged["qa_analysis"] = {
                    "overall_score": score,
                    "qa_report": analysis["qa_report"],
                    "evaluation": analysis["evaluation"],
                    "semrush": analysis.get("semrush"),
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

## `seo-agent/src/semrush_api.py`

```python
"""کلاینت واقعی SEMrush Analytics API (خودکار — بدون نیاز به MCP/Claude).

از endpoint استاندارد https://api.semrush.com/ استفاده می‌کند. خروجی CSV با جداکننده‌ی «؛»
است. کلید در .env → SEMRUSH_API_KEY.

توابع سطح‌بالا خروجی را در قالبی می‌دهند که semrush_bridge انتظار دارد، پس بقیه‌ی سیستم
(writer / evaluate_and_sync) بدون تغییر کار می‌کند.

مستند API: https://developer.semrush.com/api/v3/analytics/
"""
import json
import logging
import urllib.parse
import urllib.request

from . import llm, semrush_bridge
from .config import env, load_settings

logger = logging.getLogger(__name__)

_BASE = "https://api.semrush.com/"

# ستون‌های خروجی: Ph=کیورد، Nq=حجم ماهانه، Cp=CPC، Co=رقابت، Nr=تعداد نتایج، Kd=سختی
_COLS_OVERVIEW = "Ph,Nq,Cp,Co,Nr"
_COLS_RELATED = "Ph,Nq,Cp,Co,Kd,Nr"
_COLS_QUESTIONS = "Ph,Nq,Kd"


def _market() -> str:
    return load_settings().get("semrush", {}).get("market", "us")


def _api_get(params: dict) -> list[dict]:
    """یک تماس به SEMrush می‌زند و ردیف‌های CSV را به list[dict] تبدیل می‌کند."""
    key = env("SEMRUSH_API_KEY", required=True)
    params = {**params, "key": key}
    url = _BASE + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as resp:
        text = resp.read().decode("utf-8", errors="replace").strip()

    # خطاهای SEMrush به‌صورت متن ساده برمی‌گردند (مثلاً "ERROR 50 :: NOTHING FOUND")
    if not text or text.upper().startswith("ERROR"):
        logger.warning(f"SEMrush پاسخ خالی/خطا: {text[:80]!r}")
        return []

    lines = text.split("\n")
    header = [h.strip() for h in lines[0].split(";")]
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        vals = line.split(";")
        rows.append(dict(zip(header, vals)))
    return rows


def _to_num(s: str, cast=float):
    try:
        return cast(s)
    except (ValueError, TypeError):
        return None


# ── فاز A: کیوردریسرچ ────────────────────────────────────────────

def research_keywords(topic: str, seed: str, limit: int = 15) -> dict:
    """برای یک seed، کیورد اصلی + پشتیبان + سوال‌های long-tail را از SEMrush می‌گیرد
    و در فایل واسط ذخیره می‌کند. dict ذخیره‌شده را برمی‌گرداند.
    """
    db = _market()
    kd_max = load_settings().get("semrush", {}).get("kd_max", 40)

    overview = _api_get({
        "type": "phrase_this", "phrase": seed, "database": db,
        "export_columns": _COLS_OVERVIEW,
    })
    related = _api_get({
        "type": "phrase_related", "phrase": seed, "database": db,
        "export_columns": _COLS_RELATED, "display_limit": limit,
        "display_sort": "nq_desc",
    })
    questions = _api_get({
        "type": "phrase_questions", "phrase": seed, "database": db,
        "export_columns": _COLS_QUESTIONS, "display_limit": 5,
        "display_sort": "nq_desc",
    })

    per_kw = {}
    for r in overview + related:
        ph = r.get("Keyword") or r.get("Ph")
        if not ph:
            continue
        per_kw[ph] = {
            "volume": _to_num(r.get("Search Volume") or r.get("Nq"), int),
            "kd": _to_num(r.get("Keyword Difficulty Index") or r.get("Kd"), float),
            "cpc": _to_num(r.get("CPC") or r.get("Cp"), float),
        }

    # انتخاب کیورد اصلی: ترجیحاً کیوردی با KD واقعیِ ≤ سقف و بیشترین حجم (قابل‌رنک).
    # این با گیت SEMrush (KD بالا → رد) هماهنگ است: از اول کیورد کم‌رقابت هدف می‌گیریم.
    winnable = [
        (ph, m) for ph, m in per_kw.items()
        if m["kd"] is not None and m["kd"] <= kd_max
    ]
    winnable.sort(key=lambda x: (x[1]["volume"] or 0), reverse=True)

    if winnable:
        candidates = winnable
    else:
        # هیچ کیورد کم‌رقابتی با KD معلوم نبود → آن‌هایی که KD نامعلوم دارند، بر حجم
        candidates = sorted(
            ((ph, m) for ph, m in per_kw.items() if m["kd"] is None),
            key=lambda x: (x[1]["volume"] or 0), reverse=True,
        )

    primary = seed if not candidates else candidates[0][0]
    secondary = [ph for ph, _ in candidates[1:4]]
    # اگر هیچ کیورد کم‌سختی نبود، کم‌سختی‌ترین‌های مرتبط را بردار (تا دست خالی نمانیم)
    if not secondary:
        by_kd = sorted(
            ((ph, m) for ph, m in per_kw.items() if ph != primary and m.get("kd") is not None),
            key=lambda x: x[1]["kd"],
        )
        secondary = [ph for ph, _ in by_kd[:3]]
    longtail = [r.get("Keyword") or r.get("Ph") for r in questions if (r.get("Keyword") or r.get("Ph"))][:3]

    data = {
        "primary": primary,
        "primary_fa": None,   # معادل فارسی: توسط نویسنده/مدل حین تولید ساخته می‌شود
        "secondary": secondary,
        "longtail": longtail,
        "per_kw": per_kw,
        "fa_map": {},
        "market": db,
        "note": f"داده از SEMrush API (دیتابیس {db}). معادل فارسی هنگام تولید ساخته می‌شود.",
    }
    semrush_bridge.save_keywords(topic, data)
    logger.info(f"SEMrush کیوردریسرچ «{topic}»: اصلی={primary}، {len(secondary)} پشتیبان، {len(longtail)} سوال")
    return data


# ── فاز C: تحلیل سئوی مقاله ──────────────────────────────────────

def analyze_article_keywords(article_id: int, keywords: list[str]) -> dict:
    """کیوردهای مقاله‌ی تولیدشده را با SEMrush چک می‌کند و گزارش را ذخیره می‌کند."""
    db = _market()
    kd_max = load_settings().get("semrush", {}).get("kd_max", 40)

    per_kw = {}
    for kw in keywords:
        rows = _api_get({
            "type": "phrase_this", "phrase": kw, "database": db,
            "export_columns": _COLS_RELATED,
        })
        if rows:
            r = rows[0]
            per_kw[kw] = {
                "volume": _to_num(r.get("Search Volume") or r.get("Nq"), int),
                "kd": _to_num(r.get("Keyword Difficulty Index") or r.get("Kd"), float),
                "competition": _to_num(r.get("Competition") or r.get("Co"), float),
            }

    # فقط KDهای واقعی (>0)؛ صفر یعنی داده‌ی معتبر نیست
    kds = [m["kd"] for m in per_kw.values() if m.get("kd")]
    avg_kd = round(sum(kds) / len(kds), 1) if kds else None
    if avg_kd is None:
        verdict = "UNKNOWN"      # داده‌ی KD نداریم → گیت را مسدود نکن
    elif avg_kd <= kd_max:
        verdict = "GOOD"
    else:
        verdict = "WEAK"

    report = {
        "targeted_keywords": keywords,
        "per_kw": per_kw,
        "avg_kd": avg_kd,
        "verdict": verdict,
        "notes": f"میانگین KD={avg_kd} (سقف {kd_max}). داده از SEMrush API دیتابیس {db}.",
    }
    semrush_bridge.save_analysis(article_id, report)
    logger.info(f"SEMrush تحلیل مقاله #{article_id}: verdict={verdict}, avg_kd={avg_kd}")
    return report


# ── ترجمه‌ی خودکار (فارسی ↔ انگلیسی) با Gemini ───────────────────

def derive_english_seed(topic_fa: str) -> str:
    """موضوع فارسی را به یک seed کیورد انگلیسی کوتاه تبدیل می‌کند (برای SEMrush)."""
    out = llm.ask(
        step="semrush_seed",
        user_content=(
            "این موضوع فارسی را به یک عبارت کلیدواژه‌ی انگلیسی کوتاه و پرجستجو "
            "(۲ تا ۴ کلمه، مناسب کیوردریسرچ) تبدیل کن.\n"
            f"موضوع: {topic_fa}\n"
            'فقط JSON: {"seed": "english keyword"}'
        ),
        model_tier="cheap",
        json_output=True,
        max_tokens=200,
    )
    seed = (out or {}).get("seed", "").strip()
    return seed or topic_fa


def _translate_keywords_to_fa(keywords: list[str]) -> dict:
    """برای فهرست کیوردهای انگلیسی، معادل فارسی طبیعی می‌سازد. dict{en: fa}."""
    kws = [k for k in keywords if k]
    if not kws:
        return {}
    out = llm.ask(
        step="semrush_kw_translate",
        user_content=(
            "برای هر کلیدواژه‌ی انگلیسی زیر، معادل فارسی طبیعی و رایج در جستجو بنویس "
            "(نه ترجمه‌ی تحت‌اللفظی).\n"
            + "\n".join(f"- {k}" for k in kws)
            + '\nفقط JSON: {"map": {"english": "فارسی", ...}}'
        ),
        model_tier="cheap",
        json_output=True,
        max_tokens=800,
    )
    return (out or {}).get("map", {}) or {}


def research_topic(topic_fa: str, limit: int = 12) -> dict:
    """فاز A کاملاً خودکار: موضوع فارسی → seed انگلیسی → کیوردریسرچ SEMrush →
    ساخت معادل فارسی → ذخیره در فایل واسط. dict نهایی را برمی‌گرداند.
    """
    seed = derive_english_seed(topic_fa)
    logger.info(f"seed انگلیسی برای «{topic_fa}»: {seed}")
    data = research_keywords(topic_fa, seed, limit=limit)

    # معادل فارسی برای کیورد اصلی + پشتیبان
    to_translate = [data["primary"]] + list(data.get("secondary", []))
    fa_map = _translate_keywords_to_fa(to_translate)
    data["fa_map"] = fa_map
    data["primary_fa"] = fa_map.get(data["primary"]) or data["primary"]
    semrush_bridge.save_keywords(topic_fa, data)
    logger.info(f"کیورد اصلی فارسی: {data['primary_fa']}")
    return data

```


---

## `seo-agent/src/semrush_bridge.py`

```python
"""پل بین SEMrush (کانکتور MCP، دست Claude) و کد پایتون.

نکته‌ی معماری: SEMrush یک تول MCP است و فقط وقتی Claude در جلسه حاضر است در
دسترس است. کد پایتونِ standalone نمی‌تواند مستقیماً SEMrush را صدا بزند. پس:

    Claude تماس SEMrush را می‌زند  →  نتیجه را اینجا در فایل JSON می‌ریزد
    کد پایتون (writer / evaluator)  →  همان فایل را می‌خواند

این ماژول فقط I/O فایل است؛ هیچ تماس شبکه‌ای/SEMrush ندارد.

فایل‌های واسط در DATA_DIR:
- semrush_keywords.json           → کیوردهای هدفِ همه‌ی موضوع‌ها (dict: topic → data)
- semrush_analysis_<article_id>.json → تحلیل سئوی SEMrush برای یک مقاله‌ی مشخص
"""
import json
from pathlib import Path

from .config import DATA_DIR

_KEYWORDS_FILE = DATA_DIR / "semrush_keywords.json"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── کیوردهای هدف (فاز A — قبل از تولید) ──────────────────────────

def save_keywords(topic: str, data: dict) -> None:
    """کیوردهای انتخاب‌شده‌ی یک موضوع را ذخیره می‌کند (Claude بعد از SEMrush صدا می‌زند).

    ساختار پیشنهادی data:
        {
          "primary": "AI automation",
          "primary_fa": "اتوماسیون هوش مصنوعی",
          "secondary": ["...", "..."],
          "longtail": ["how to ...?", "..."],
          "per_kw": {"AI automation": {"volume": 12000, "kd": 34, "cpc": 3.1}},
          "fa_map": {"AI automation": "اتوماسیون هوش مصنوعی"},
          "market": "us",
          "note": "کیوردها از دیتابیس انگلیسی SEMrush؛ معادل فارسی دستی."
        }
    """
    all_kw = _read_json(_KEYWORDS_FILE)
    all_kw[topic] = data
    _write_json(_KEYWORDS_FILE, all_kw)


def load_keywords(topic: str) -> dict | None:
    """کیوردهای هدف یک موضوع را برمی‌گرداند، یا None اگر هنوز ساخته نشده."""
    all_kw = _read_json(_KEYWORDS_FILE)
    return all_kw.get(topic)


def keywords_prompt_block(data: dict | None) -> str:
    """کیوردها را به یک بلوک متنی برای تزریق در پرامپت نویسنده تبدیل می‌کند."""
    if not data:
        return "کیورد هدف مشخصی تعیین نشده؛ کیورد اصلی را خودت از موضوع استخراج کن."

    primary = data.get("primary_fa") or data.get("primary", "")
    secondary = data.get("secondary", []) or []
    longtail = data.get("longtail", []) or []
    fa_map = data.get("fa_map", {}) or {}
    sec_fa = [fa_map.get(s, s) for s in secondary]

    lines = [
        f"- کیورد اصلی (باید در H1، ۱۰۰ کلمه‌ی اول، حداقل یک H2 و جمع‌بندی بیاید): «{primary}»",
    ]
    if sec_fa:
        lines.append("- کیوردهای پشتیبان (طبیعی در متن پخش شوند): " + "، ".join(f"«{s}»" for s in sec_fa))
    if longtail:
        lines.append("- سوال‌های long-tail (برای H2/FAQ استفاده شوند): " + "؛ ".join(longtail))
    return "\n".join(lines)


# ── تحلیل سئوی مقاله (فاز C — بعد از تولید) ──────────────────────

def _analysis_path(article_id: int) -> Path:
    return DATA_DIR / f"semrush_analysis_{article_id}.json"


def save_analysis(article_id: int, report: dict) -> None:
    """گزارش تحلیل SEMrush یک مقاله را ذخیره می‌کند (Claude بعد از SEMrush صدا می‌زند).

    ساختار پیشنهادی report:
        {
          "targeted_keywords": ["..."],
          "per_kw": {"kw": {"volume": .., "kd": .., "competition": ..}},
          "avg_kd": 38,
          "opportunities": ["کیوردهای کم‌رقابتی که مقاله جا انداخته"],
          "verdict": "GOOD | WEAK",
          "notes": "..."
        }
    """
    _write_json(_analysis_path(article_id), report)


def load_analysis(article_id: int) -> dict | None:
    """گزارش تحلیل SEMrush یک مقاله را برمی‌گرداند، یا None."""
    path = _analysis_path(article_id)
    if not path.exists():
        return None
    return _read_json(path)

```


---

## `seo-agent/src/llm.py`

```python
"""کلاینت مدل (Anthropic یا Gemini) با خروجی JSON و ثبت مصرف توکن.

ارائه‌دهنده با کلید `provider` در settings.yaml تعیین می‌شود: anthropic | gemini
هر دو از تابع ask() یکسان استفاده می‌کنند.
"""
import json
import re

from .config import PROMPTS_DIR, env, load_settings
from . import db

_client = None
_gemini_ready = False
_settings = load_settings()


def _provider() -> str:
    return (_settings.get("provider") or "anthropic").lower()


def client():
    """کلاینت Anthropic (فقط وقتی provider=anthropic)."""
    global _client
    if _client is None:
        from anthropic import Anthropic
        _client = Anthropic(api_key=env("ANTHROPIC_API_KEY", required=True))
    return _client


def _gemini():
    global _gemini_ready
    import google.generativeai as genai
    if not _gemini_ready:
        genai.configure(api_key=env("GEMINI_API_KEY", required=True))
        _gemini_ready = True
    return genai


def system_prompt_xml() -> str:
    return (PROMPTS_DIR / "seo-content-agent-prompt.xml").read_text(encoding="utf-8")


def _escape_unescaped_newlines(s: str) -> str:
    """newlineهای خام داخل رشته‌های JSON را escape می‌کند (خطای مدل رایج)."""
    out = []
    in_str = False
    escaped = False
    for ch in s:
        if in_str:
            if escaped:
                out.append(ch)
                escaped = False
                continue
            if ch == "\\":
                out.append(ch)
                escaped = True
                continue
            if ch == '"':
                in_str = False
                out.append(ch)
                continue
            if ch == "\n":
                out.append("\\n")
                continue
            if ch == "\r":
                out.append("\\r")
                continue
            if ch == "\t":
                out.append("\\t")
                continue
            out.append(ch)
        else:
            if ch == '"':
                in_str = True
            out.append(ch)
    return "".join(out)


def _extract_json(text: str):
    """JSON را از پاسخ مدل بیرون می‌کشد (با یا بدون بلوک کد، مقاوم به newline خام)."""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1)
    start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
    if start == -1:
        raise ValueError(f"پاسخ مدل JSON ندارد: {text[:200]}")
    candidate = text[start:]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        # لایه‌ی دوم: newlineهای خام داخل رشته‌ها را escape کن و دوباره تلاش کن
        return json.loads(_escape_unescaped_newlines(candidate))


def ask(
    step: str,
    user_content: str,
    *,
    model_tier: str = "cheap",
    system: str | None = None,
    cache_system: bool = False,
    json_output: bool = True,
    max_tokens: int = 4096,
):
    """یک فراخوانی مدل. model_tier: 'cheap' یا 'main'. ارائه‌دهنده از settings تعیین می‌شود."""
    if _provider() == "gemini":
        return _ask_gemini(
            step, user_content, model_tier=model_tier, system=system,
            json_output=json_output, max_tokens=max_tokens,
        )

    model = _settings["models"][model_tier]
    kwargs = {"model": model, "max_tokens": max_tokens}
    if system:
        if cache_system:
            kwargs["system"] = [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ]
        else:
            kwargs["system"] = system
    kwargs["messages"] = [{"role": "user", "content": user_content}]

    resp = client().messages.create(**kwargs)

    conn = db.connect()
    db.log_tokens(conn, model, step, resp.usage)
    conn.close()

    text = "".join(b.text for b in resp.content if b.type == "text")
    return _extract_json(text) if json_output else text


def _ask_gemini(
    step: str,
    user_content: str,
    *,
    model_tier: str = "cheap",
    system: str | None = None,
    json_output: bool = True,
    max_tokens: int = 4096,
):
    """فراخوانی Gemini با همان رابط ask()."""
    genai = _gemini()
    model_name = _settings["gemini_models"][model_tier]

    gen_config = {"max_output_tokens": max_tokens}
    if json_output:
        gen_config["response_mime_type"] = "application/json"

    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=system if system else None,
        generation_config=gen_config,
    )
    resp = model.generate_content(user_content)

    # ثبت مصرف توکن (اگر usage_metadata موجود بود)
    try:
        um = resp.usage_metadata
        conn = db.connect()
        db.log_tokens(conn, model_name, step, type("U", (), {
            "input_tokens": um.prompt_token_count,
            "output_tokens": um.candidates_token_count,
            "cache_read_input_tokens": 0,
        })())
        conn.close()
    except Exception:
        pass

    text = resp.text
    return _extract_json(text) if json_output else text

```


---

## `seo-agent/src/db.py`

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

# مدل‌ها (Gemini) — پلن رایگان
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

```
