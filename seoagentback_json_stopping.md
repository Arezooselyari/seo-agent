# بکاپ قبل از JSON repair + stopping criteria
تاریخ: 2026-07-18T23:46:55.442427


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
    temperature: float = 0,
):
    """یک فراخوانی مدل. model_tier: 'cheap' یا 'main'. ارائه‌دهنده از settings تعیین می‌شود."""
    if _provider() == "gemini":
        try:
            return _ask_gemini(
                step, user_content, model_tier=model_tier, system=system,
                json_output=json_output, max_tokens=max_tokens, temperature=temperature,
            )
        except (json.JSONDecodeError, ValueError):
            # JSON خراب گاه‌به‌گاه مدل — یک بار دیگر تلاش کن
            return _ask_gemini(
                step, user_content, model_tier=model_tier, system=system,
                json_output=json_output, max_tokens=max_tokens, temperature=temperature,
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
    temperature: float = 0,
):
    """فراخوانی Gemini با همان رابط ask()."""
    genai = _gemini()
    model_name = _settings["gemini_models"][model_tier]

    # پیش‌فرض temperature=0 → خروجی قطعی (حیاتی برای ارزیاب: نمره نباید نوسان کند).
    # نویسندگی/انسانی‌سازی temperature بالاتر می‌فرستند تا متن قالبی نشود.
    gen_config = {"max_output_tokens": max_tokens, "temperature": temperature}
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

    # چک truncation: اگر پاسخ به سقف توکن خورده باشد، JSON ناقص است (طبق نکته‌ی مستر پرامپت)
    try:
        finish = resp.candidates[0].finish_reason
        # 2 == MAX_TOKENS در google.generativeai
        if getattr(finish, "name", str(finish)) in ("MAX_TOKENS", "2"):
            raise RuntimeError(
                f"پاسخ مدل truncate شد (MAX_TOKENS در step={step}, سقف={max_tokens}). "
                "max_tokens را بالاتر ببر."
            )
    except (IndexError, AttributeError):
        pass

    text = resp.text
    return _extract_json(text) if json_output else text

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

            # ثبت ایرادات دور اول در حافظه‌ی تحریریه
            editor_memory.record_issues(analysis.get("issues", []))

            def _gate_ok(an: dict) -> bool:
                g = an.get("quality_gate")
                return g is None or bool(g.get("passed"))

            def _rank(an: dict) -> tuple:
                """کلید مقایسه‌ی نسخه‌ها: عبور از گیت > کیفیت وزنی > نمره‌ی فنی."""
                g = an.get("quality_gate") or {}
                return (
                    _gate_ok(an),
                    float(g.get("weighted_score", 0) or 0),
                    an["overall_score"],
                )

            # ── حلقه‌ی تحریریه: برنامه‌ریزی → بازنویسی پچی → QA مجدد ──
            revision_history = []
            revision = 0
            # بهترین نسخه در طول حلقه — اگر دوری نمره را بدتر کرد، به این برمی‌گردیم
            best_payload, best_analysis = payload, analysis
            while (
                rewrite_enabled
                # هر دلیل ردّ قابل‌اصلاح: نمره‌ی کم، QA مدل، چک‌های کد، یا گیت کیفیت
                # (analysis["passed"] = qa_passed و نمره و code_ok — semrush جدا می‌ماند چون با بازنویسی حل نمی‌شود)
                and (not analysis["passed"] or not _gate_ok(analysis))
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
                    # بهترین = اول عبور از گیت، بعد کیفیت وزنی (لحن)، بعد نمره‌ی فنی
                    if _rank(analysis) > _rank(best_analysis):
                        best_payload, best_analysis = payload, analysis
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
            title = payload.get("title_seo") or payload.get("h1", "")

            # گیت نهایی: qa پاس + نمره + کیوردها ضعیف نباشند + دروازه‌ی کیفیت (لحن انسانی)
            passed = analysis["passed"] and not analysis.get("semrush_weak") and _gate_ok(analysis)

            if passed:
                # payload ممکن است حاصل بازنویسی تحریریه باشد؛ نمره و تاریخچه ضمیمه می‌شود
                merged = dict(payload)
                merged["seo_grade"] = score
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
                    "reasons": analysis["reasons"],
                    "preview": body_md[:200] + ("..." if len(body_md) > 200 else ""),
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
        config = load_settings()
        if approved:
            await process_approved_articles(approved, config)

        # مقالات نزدیک به مرز (نمره ≥ آستانه‌ی بررسی) هم به تلگرام بروند —
        # با برچسب «نیاز به بررسی» و دلایل، تا تصمیم نهایی دست کاربر باشد
        review_min = int(config.get("evaluation", {}).get("telegram_review_min", 80))
        near_miss = [a for a in needs_review if a["seo_grade"] >= review_min]
        for item in near_miss:
            ok = await telegram_approver.send_approval_request(
                article_id=item["article_id"],
                title=item["title"],
                seo_grade=item["seo_grade"],
                preview=item.get("preview", ""),
                warning="\n".join(f"• {r}" for r in item["reasons"]),
            )
            if ok:
                logger.info(
                    f"⚠️ مقاله #{item['article_id']} (نمره {item['seo_grade']}) "
                    f"با برچسب «نیاز به بررسی» به تلگرام رفت"
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
