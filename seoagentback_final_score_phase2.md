# بکاپ قبل از فاز ۲ لایه‌ی final_score — 2026-07-19

فایل‌های تغییریابنده در فاز ۲: evaluate_and_sync.py, html_export.py, telegram_approver.py
برای بازگردانی: محتوای هر بخش را در فایل مربوطه بگذار.


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
                    improvement = analysis["overall_score"] - score_before
                    logger.info(
                        f"   دور {revision}: نمره {score_before} → {analysis['overall_score']} "
                        f"(بهبود {improvement:+d})"
                    )
                    # بهترین = اول عبور از گیت، بعد کیفیت وزنی (لحن)، بعد نمره‌ی فنی
                    if _rank(analysis) > _rank(best_analysis):
                        best_payload, best_analysis = payload, analysis

                    # معیار توقف همگرایی: اگر این دور نمره را به هدف نرساند و بهبودش
                    # کمتر از حد آستانه بود، ادامه‌ی حلقه اتلاف توکن است.
                    if analysis["overall_score"] < minimum_score and improvement < min_improvement:
                        logger.info(
                            f"   توقف همگرایی: بهبود {improvement:+d} < {min_improvement} "
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

## src\html_export.py

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

    # دروازه‌ی کیفیت محتوا (لحن انسانی / E-E-A-T / Conversion)
    gate_html = ""
    gate = qa.get("quality_gate")
    if gate:
        s = gate.get("scores", {}) or {}
        score_rows = "\n".join(
            f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v))}/10</td></tr>"
            for k, v in s.items()
        )
        cliche_items = "\n".join(
            f"<li>«{html.escape(str(c.get('quote','')))}» ← <em>{html.escape(str(c.get('better','')))}</em></li>"
            for c in (gate.get("cliches") or [])[:10]
        )
        recs = gate.get("recommendations", {}) or {}
        rec_html = ""
        for key, label in [("high_priority", "ضروری قبل از انتشار"),
                           ("medium_priority", "برای افزایش رتبه"),
                           ("long_term", "برای Authority شدن")]:
            items = recs.get(key) or []
            if items:
                lis = "\n".join(f"<li>{html.escape(str(i))}</li>" for i in items)
                rec_html += f"<h3>{label}</h3><ul>{lis}</ul>"
        gate_html = (
            f"<section class='qa'><h2>دروازه‌ی کیفیت محتوا "
            f"({'✔ عبور' if gate.get('passed') else '✘ ردّ'} — وزنی {gate.get('weighted_score','-')}/10)</h2>"
            f"<table><tr><th>بُعد</th><th>امتیاز</th></tr>{score_rows}</table>"
            + (f"<h3>کلیشه‌های یافت‌شده</h3><ul>{cliche_items}</ul>" if cliche_items else "")
            + rec_html
            + "</section>"
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
  {gate_html}
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

## src\telegram_approver.py

```python
"""ارسال پیام‌های تایید به تلگرام و پردازش کلیک دکمه‌ها.

این ماژول دو بخش دارد:
1. send_approval_request() — یک پیام تکی با دکمه می‌فرستد (یک‌بار، با telegram.Bot)
2. run_listener() — فرآیند دائمی که کلیک دکمه‌ها را می‌گیرد و DB را به‌روزرسانی می‌کند

برای کارکردن دکمه‌ها، listener باید همیشه در حال اجرا باشد (polling).
"""

import logging

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackContext, CallbackQueryHandler

from . import db
from .config import env

logger = logging.getLogger(__name__)


def _build_keyboard(article_id: int) -> InlineKeyboardMarkup:
    """دکمه‌های inline تایید/ردّ/لغو را می‌سازد."""
    keyboard = [
        [
            InlineKeyboardButton("✅ تایید", callback_data=f"approval_approve_{article_id}"),
            InlineKeyboardButton("❌ ردّ", callback_data=f"approval_reject_{article_id}"),
        ],
        [
            InlineKeyboardButton("⊗ لغو", callback_data=f"approval_cancel_{article_id}"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def _build_message(title: str, seo_grade: int, preview: str, warning: str | None = None) -> str:
    """متن پیام تایید را می‌سازد (متن ساده — بدون Markdown تا entity نشکند).

    warning: اگر مقاله از گیت خودکار عبور نکرده ولی نزدیک بوده، دلایل اینجا می‌آید.
    """
    header = "📝 مقاله جدید برای تایید" if not warning else "⚠️ مقاله نزدیک به مرز — نیاز به بررسی شما"
    msg = (
        f"{header}\n\n"
        f"📌 عنوان: {title}\n"
        f"⭐ نمره‌ی SEO: {seo_grade}/100\n"
    )
    if warning:
        msg += f"\n🔎 دلایل عدم تایید خودکار:\n{warning}\n"
    msg += (
        f"\n📖 پیش‌نمایش:\n{preview}\n\n"
        f"🔗 لطفاً تصمیم بگیرید:"
    )
    return msg


async def send_approval_request(
    article_id: int, title: str, seo_grade: int, preview: str,
    token: str | None = None, chat_id: str | None = None,
    warning: str | None = None,
) -> bool:
    """یک پیام تایید را به تلگرام می‌فرستد (با telegram.Bot، بدون نیاز به Application).

    Returns:
        True اگر موفق بود.
    """
    token = token or env("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or env("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.warning("توکن یا Chat ID تلگرام تنظیم نشده.")
        return False

    bot = Bot(token=token)
    try:
        async with bot:
            await bot.send_message(
                chat_id=chat_id,
                text=_build_message(title, seo_grade, preview, warning),
                reply_markup=_build_keyboard(article_id),
            )
        logger.info(f"پیام تایید برای مقاله #{article_id} ارسال شد.")
        return True
    except Exception as e:
        logger.error(f"خطا در ارسال پیام تلگرام: {e}")
        return False


async def _handle_button(update: Update, context: CallbackContext) -> None:
    """کلیک دکمه‌ی تایید/ردّ/لغو را پردازش می‌کند."""
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")  # "approval_<action>_<id>"
    if len(parts) < 3:
        return
    action = parts[1]
    try:
        article_id = int(parts[2])
    except ValueError:
        return

    conn = db.connect()
    try:
        article = db.get_article(conn, article_id)
        if not article:
            await query.edit_message_text(f"❌ مقاله #{article_id} یافت نشد.")
            return

        if action == "approve":
            db.set_status(conn, article_id, "approved")
            status_text = "✅ تایید شد — آماده‌ی انتشار"
        elif action == "reject":
            db.set_status(conn, article_id, "rejected")
            status_text = "❌ ردّ شد"
        elif action == "cancel":
            status_text = "⊗ لغو شد (وضعیت تغییر نکرد)"
        else:
            return

        new_text = (query.message.text or "") + f"\n\n✔️ *تصمیم:* {status_text}"
        await query.edit_message_text(new_text, parse_mode="Markdown")
        logger.info(f"مقاله #{article_id}: {action.upper()}")
    except Exception as e:
        logger.error(f"خطا در پردازش دکمه: {e}")
    finally:
        conn.close()


def run_listener(token: str | None = None) -> None:
    """فرآیند دائمی که کلیک دکمه‌ها را می‌گیرد (polling).

    این را در یک پنجره‌ی جدا اجرا کن و باز نگه دار:
        python -m src.telegram_approver
    """
    token = token or env("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN تنظیم نشده است.")

    app = Application.builder().token(token).build()
    app.add_handler(CallbackQueryHandler(_handle_button, pattern="^approval_"))
    logger.info("شنونده‌ی تلگرام شروع شد — منتظر کلیک دکمه‌ها... (Ctrl+C برای توقف)")
    app.run_polling()


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    run_listener()

```
