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
    seo_checklist,
    telegram_approver,
    writer,
)
from . import architecture_v2_1_utils as av21
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
            # متنِ کاملِ مقاله را هم بفرست تا پیش از تایید قابلِ خواندن باشد
            # (هم‌رفتار با مسیرِ needs_review — کاربر باید کامل ببیند و بعد تایید کند)
            if result.get("body_html"):
                await telegram_approver.send_article_document(
                    article_id=result["article_id"],
                    title=result["title"],
                    body_html=result["body_html"],
                    meta=result.get("meta_description", ""),
                    featured_url=result.get("featured_image_url", ""),
                    featured_alt=result.get("featured_image_alt", ""),
                    token=token,
                    chat_id=chat_id,
                )
            _mark_notified(result["article_id"])
            logger.info(
                f"مقاله #{result['article_id']} برای تایید به تلگرام ارسال شد "
                f"(فنی: {result['seo_grade']}، نهایی: {result.get('final_score', '-')})"
            )


def _mark_notified(article_id: int) -> None:
    """مقاله را «فرستاده‌شده» علامت می‌زند تا اجرای فردا دوباره برش ندارد."""
    conn = db.connect()
    try:
        db.mark_notified(conn, article_id)
    except Exception as e:  # noqa: BLE001 — پیام رفته؛ نبودِ علامت نباید چرخه را بکُشد
        logger.warning(f"علامت‌زدنِ ارسالِ مقاله #{article_id} نشد: {e}")
    finally:
        conn.close()


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
        fs_cfg = config.get("final_score", {}) or {}
        seo_min = float(fs_cfg.get("seo_checklist_min", 70))

        def _apply_quality_gate(pl: dict, an: dict) -> dict:
            """چک‌لیستِ عینیِ عواملِ رتبه‌ی گوگل + دروازه‌ی کیفیتِ سلیقه‌ای (advisory)."""
            an = dict(an)
            # چک‌لیستِ SEO همیشه اجرا می‌شود (قطعی، بی‌LLM) — گیتِ اصلیِ رتبه
            an["seo_checklist"] = seo_checklist.evaluate(pl, min_score=seo_min)
            if not gate_enabled:
                return an
            try:
                gate = quality_gate.review(pl)
            except Exception as e:
                # Fail-Closed (freeze v2.1.1): گیتِ enabledِ ناقص/truncate/غیرقابل‌parse
                # نباید به auto-publish منجر شود. فقط لاگ + پرچم؛ بدون Retry/Chunking/Schema.
                logger.warning(f"Quality Gate اجرا نشد (ناقص/truncate) — Fail-Closed: {e}")
                an = dict(an)
                an["gate_incomplete"] = True
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

            def _candidate_result(an: dict, pl: dict | None) -> dict:
                """نگاشت analysis به قرارداد should_save_candidate (v2.1.1).

                Adapter قبلیِ بازتفسیر would_reject حذف شد — تصمیمِ ذخیره فقط بر
                اساس hard_policy_reject لایه‌ی final است (تخلف سیاستی، نه امتیاز)؛
                نسخه‌ی میانی کم‌امتیاز ولی بهتر، قابل ذخیره است.
                """
                bd = an["final"]["score_breakdown"]
                g = bd["hard_gates"]
                return {
                    "hard_error_count": sum(
                        1 for k in ("qa_passed", "quality_gate_passed",
                                    "code_checks_ok", "semrush_ok")
                        if g[k] is False
                    ),
                    "unsupported_claim_count": int(bd.get("unsupported_claims", 0) or 0),
                    "high_confidence_soft_unsupported_count": int(
                        bd.get("high_confidence_soft_unsupported_count", 0) or 0),
                    "medium_confidence_soft_unsupported_count": int(
                        bd.get("medium_confidence_soft_unsupported_count", 0) or 0),
                    "rewrite_warning_count": len((pl or {}).get("rewrite_warnings") or []),
                    "final_score": an["final"]["final_score"],
                    "hard_policy_reject": bool(bd.get("hard_policy_reject", False)),
                    "validator_passed": True,
                }

            def _should_replace(new_an, new_pl, old_an, old_pl):
                """تصمیم جایگزینی نسخه — قواعد غیرقابل تغییر پچ v2.1."""
                return av21.should_save_candidate(
                    candidate_result=_candidate_result(new_an, new_pl),
                    previous_result=_candidate_result(old_an, old_pl),
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
                    # v2.1: هش متن قبل از بازنویسی — برای تشخیص «متن بدون تغییر» (QA cache)
                    prev_hash = av21.stable_hash(writer._payload_text(payload))
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

                    if av21.stable_hash(writer._payload_text(payload)) == prev_hash:
                        # v2.1: متن تغییری نکرده (ردّ validator یا خروجی یکسان) —
                        # QA/گیت تکراری اجرا نمی‌شود؛ همان ارزیابی قبلی معتبر است.
                        rejs = payload.get("humanize_rejections") or []
                        rej = rejs[-1] if (rejs and rejs[-1].get("revision") == revision) else None
                        if rej:
                            try:
                                db.record_validation_event(
                                    conn,
                                    article_id=article_id,
                                    stage="humanize",
                                    round_number=revision,
                                    rejection_reasons=rej.get("violations") or [],
                                    candidate_content_hash=rej.get("candidate_content_hash", ""),
                                    restored_content_hash=rej.get("restored_content_hash", ""),
                                    validator_version=av21.VALIDATOR_VERSION,
                                )
                            except Exception as pe:
                                # Fail-Closed: شکست ثبت رویداد → مقاله هرگز approved نشود
                                logger.error(f"ثبت رویداد validator نشد: {pe}")
                                analysis["validator_persist_failed"] = True
                        revision_history.append({
                            "revision": revision,
                            "score_before": score_before,
                            "score_after": score_before,
                            "final_before": final_before,
                            "final_after": final_before,
                            "final_verdict": analysis["final"]["final_verdict"],
                            "issues_before": issues_before,
                            "issues_after": issues_before,
                            "patches": len(plan.get("patches", [])),
                            "plan_summary": plan.get("summary", ""),
                            "qa_skipped": True,
                            "skip_reason": "content_unchanged_after_validator_rejection",
                        })
                        improvement = 0.0
                        logger.info(
                            f"   دور {revision}: QA تکراری اجرا نشد "
                            f"(متن بدون تغییر — {'ردّ validator' if rej else 'خروجی یکسان'})"
                        )

                        # ── v2.1.1: Mandatory Cleanup — حداکثر یک بار per مقاله ──
                        gate_rep = analysis.get("quality_gate") or {}
                        cc_det = (analysis.get("code_checks") or {}).get("_details", {}) or {}
                        cleanup_targets = av21.collect_cleanup_targets({
                            "unsupported_claims": [
                                {**c, "exact_span": c.get("claim"),
                                 "confidence": "high",
                                 "required_action": c.get("required_action") or "remove"}
                                for c in (gate_rep.get("quantitative_claims") or [])
                                if (c.get("status") or "").lower() == "unsupported"
                                and (c.get("claim") or "") in writer._payload_text(payload)
                            ],
                            "soft_quantitative_claims":
                                gate_rep.get("soft_quantitative_claims") or [],
                            "forbidden_phrase_issues": [
                                {"exact_span": ph, "category": "forbidden_phrase",
                                 "confidence": "high", "required_action": "remove"}
                                for ph in (list(cc_det.get("found_forbidden") or [])
                                           + list(cc_det.get("found_unapproved_cta") or []))
                            ],
                        })
                        if rej and cleanup_targets and not payload.get("mandatory_cleanup_attempted"):
                            payload = dict(payload)
                            payload["mandatory_cleanup_attempted"] = True
                            payload["mandatory_cleanup_reason"] = \
                                "humanize_rejected_with_unresolved_cleanup_targets"
                            payload["mandatory_cleanup_completed"] = False
                            logger.info(f"   🧹 Cleanup اجباری: {len(cleanup_targets)} هدف دارای exact_span")
                            plan_c = revision_planner.build_mandatory_cleanup_plan(
                                payload, cleanup_targets)
                            candidate = writer.cleanup_article(payload, plan_c)
                            c_violations = writer.validate_humanize(payload, candidate)
                            if c_violations:
                                logger.info(f"   ⛔ Cleanup توسط validator رد شد: {c_violations}")
                                try:
                                    db.record_validation_event(
                                        conn, article_id=article_id,
                                        stage="mandatory_cleanup", round_number=revision,
                                        rejection_reasons=c_violations,
                                        candidate_content_hash=av21.stable_hash(
                                            writer._payload_text(candidate)),
                                        restored_content_hash=av21.stable_hash(
                                            writer._payload_text(payload)),
                                        validator_version=av21.VALIDATOR_VERSION,
                                    )
                                except Exception as pe:
                                    logger.error(f"ثبت رویداد cleanup نشد: {pe}")
                                    analysis["validator_persist_failed"] = True
                            else:
                                c_analysis = qa_analyzer.analyze_article(
                                    candidate, threshold=threshold)
                                c_analysis = qa_analyzer.merge_semrush(
                                    c_analysis, semrush_report)
                                c_analysis = _apply_quality_gate(candidate, c_analysis)
                                c_analysis["final"] = final_score.compute(c_analysis)
                                editor_memory.record_issues(c_analysis.get("issues", []))
                                candidate["mandatory_cleanup_attempted"] = True
                                candidate["mandatory_cleanup_reason"] = \
                                    payload["mandatory_cleanup_reason"]
                                ok_c, c_reason = _should_replace(
                                    c_analysis, candidate, analysis, payload)
                                revision_history.append({
                                    "revision": revision,
                                    "mode": "mandatory_cleanup",
                                    "score_before": score_before,
                                    "score_after": c_analysis["overall_score"],
                                    "final_before": final_before,
                                    "final_after": c_analysis["final"]["final_score"],
                                    "final_verdict": c_analysis["final"]["final_verdict"],
                                    "issues_before": issues_before,
                                    "issues_after": len(c_analysis.get("issues", [])),
                                    "patches": len(plan_c.get("patches", [])),
                                    "plan_summary": plan_c.get("summary", ""),
                                    "cleanup_saved": ok_c,
                                    "cleanup_save_reason": c_reason,
                                })
                                if ok_c:
                                    candidate["mandatory_cleanup_completed"] = True
                                    payload, analysis = candidate, c_analysis
                                    improvement = analysis["final"]["final_score"] - final_before
                                    logger.info(
                                        f"   ✅ Cleanup ذخیره شد: نهایی {final_before} → "
                                        f"{analysis['final']['final_score']}"
                                    )
                                    if _should_replace(analysis, payload,
                                                       best_analysis, best_payload)[0]:
                                        best_payload, best_analysis = payload, analysis
                                else:
                                    payload["mandatory_cleanup_completed"] = False
                                    logger.info(f"   Cleanup ذخیره نشد ({c_reason})")
                    else:
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
                        # v2.1: جایگزینی فقط با بهبود واقعی (بدون جعل، بدون پس‌رفت)
                        ok_save, save_reason = _should_replace(
                            analysis, payload, best_analysis, best_payload
                        )
                        if ok_save:
                            best_payload, best_analysis = payload, analysis
                        else:
                            logger.info(f"   نسخه‌ی این دور ذخیره نشد ({save_reason})")

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
            # v2.1 Fail-Closed: شکست ثبت رویداد validator → هرگز approved نشود
            # v2.1.1 freeze Fail-Closed: گیت ناقص/truncate → هرگز approved نشود
            passed = (final["final_verdict"] == "approved"
                      and not analysis.get("validator_persist_failed")
                      and not analysis.get("gate_incomplete"))
            if analysis.get("validator_persist_failed"):
                analysis["reasons"] = list(analysis.get("reasons", [])) + [
                    "validator_event_persistence_failed (Fail-Closed)"
                ]
            if analysis.get("gate_incomplete"):
                analysis["reasons"] = list(analysis.get("reasons", [])) + [
                    "quality_gate_incomplete_or_truncated (Fail-Closed)"
                ]

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
                    "seo_checklist": analysis.get("seo_checklist"),
                    "issues_remaining": analysis.get("issues", []),
                    "revision_history": revision_history,
                }
                merged["seo_checklist_score"] = (analysis.get("seo_checklist") or {}).get("seo_score")
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
                    # متنِ کامل + تصویر، تا فایلِ خواندنی هم به تلگرام برود (مثلِ مسیرِ needs_review)
                    "body_html": body_md,
                    "meta_description": merged.get("meta_description", ""),
                    "featured_image_url": merged.get("featured_image_url", ""),
                    "featured_image_alt": merged.get("featured_image_alt", ""),
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
                    "body_html": body_md,
                    "meta_description": payload.get("meta_description", ""),
                    "featured_image_url": payload.get("featured_image_url", ""),
                    "featured_image_alt": payload.get("featured_image_alt", ""),
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
                # متنِ کاملِ مقاله را هم به‌صورت فایلِ HTMLِ خوانا بفرست تا کاربر پیش از تایید بخواند
                await telegram_approver.send_article_document(
                    article_id=item["article_id"],
                    title=item["title"],
                    body_html=item.get("body_html", ""),
                    meta=item.get("meta_description", ""),
                    featured_url=item.get("featured_image_url", ""),
                    featured_alt=item.get("featured_image_alt", ""),
                )
                _mark_notified(item["article_id"])
                logger.info(
                    f"⚠️ مقاله #{item['article_id']} (فنی {item['seo_grade']}، "
                    f"نهایی {item.get('final_score', '-')}) با برچسب «نیاز به بررسی» + فایلِ کامل به تلگرام رفت"
                )


def run_once() -> None:
    """یک بار ارزیابی را اجرا می‌کند."""
    from . import alerts
    with alerts.watch("ارزیابی روزانه"):
        _run_once_inner()


def _run_once_inner() -> None:
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
