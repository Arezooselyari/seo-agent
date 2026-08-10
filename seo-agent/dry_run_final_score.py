"""Dry run فاز ۲ — عبور جریان واقعی evaluate_pending از لایه‌ی final_score، صفر تماس LLM.

- DB موقت (دیتابیس و editor_memory واقعی دست نمی‌خورند؛ HTML به پوشه‌ی موقت می‌رود)
- qa_analyzer / quality_gate / revision_planner استاب می‌شوند؛ llm.ask شمارنده دارد
- سناریو A: مقاله‌ی سالم → باید approved شود (تصمیم از analysis["final"])
- سناریو B: ردّ گیت کیفیت → ورود به حلقه (plan بدون پچ → توقف) → needs_review
اجرا:  python dry_run_final_score.py   (از پوشه‌ی seo-agent)
"""
import json
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from src import (
    db, editor_memory, html_export, llm, qa_analyzer, quality_gate,
    revision_planner, semrush_bridge, telegram_approver,
)

# ── ایزوله‌سازی: DB و خروجی HTML موقت ──────────────────────────
tmp_dir = Path(tempfile.mkdtemp(prefix="dryrun_final_"))
db.DB_PATH = tmp_dir / "agent.db"
html_export.OUTPUT_DIR = tmp_dir

# ── استاب‌ها (صفر تماس واقعی) ─────────────────────────────────
LLM_CALLS = []
llm.ask = lambda *a, **k: LLM_CALLS.append((a, k)) or {}

_CODE_OK = {"no_forbidden_phrases": True, "meta_length_150_160": True,
            "internal_links_min2": True, "external_link_min1": True,
            "complete_last_sentence": True, "_details": {}}


def qa_stub(payload, threshold=90, step="qa_analyze"):
    good = payload.get("h1") == "A"
    score = 95 if good else 92
    return {
        "passed": score >= threshold,      # فنی: هر دو سناریو پاس
        "overall_score": score,
        "qa_passed": True,
        "code_checks": dict(_CODE_OK),
        "evaluation": {}, "article": {},
        "qa_report": {"passed": True, "checks": []},
        "reasons": [], "issues": [],
    }


def gate_stub(payload, step="quality_gate"):
    good = payload.get("h1") == "A"
    if good:
        return {"passed": True, "weighted_score": 8.5,
                "scores": {"human_tone": 8}, "issues": [], "reasons": [],
                "rules_compliance": {}, "cliches": [], "recommendations": {}}
    return {"passed": False, "weighted_score": 7.6,
            "scores": {"human_tone": 6},
            "issues": [{"category": "robotic_language", "severity": "medium",
                        "location": "بدنه", "exact_quote": "متن",
                        "problem": "لحن ماشینی", "rewrite_instruction": "انسانی کن"}],
            "reasons": ["لحن انسانی 6.0/10 < حداقل 7.0"],
            "rules_compliance": {}, "cliches": [], "recommendations": {}}


qa_analyzer.analyze_article = qa_stub
quality_gate.review = gate_stub
revision_planner.build_plan = lambda *a, **k: {"patches": [], "summary": ""}
editor_memory.record_issues = lambda issues: None
semrush_bridge.load_analysis = lambda aid: {"verdict": "GOOD", "avg_kd": 30,
                                            "targeted_keywords": ["x"], "per_kw": {}}

# evaluate_and_sync بعد از استاب‌ها import شود (ماژول‌ها همان شیء مشترک‌اند)
from src import evaluate_and_sync

# ── داده‌ی تست در DB موقت ─────────────────────────────────────
conn = db.connect()
BODY = "<p>" + "متن آزمایشی. " * 30 + "</p>"
id_a = db.save_article(conn, "سناریو A", {
    "h1": "A", "title_seo": "مقاله‌ی سالم A", "meta_description": "م" * 155,
    "body_html": BODY, "slug": "test-a"})
id_b = db.save_article(conn, "سناریو B", {
    "h1": "B", "title_seo": "مقاله‌ی ردِ گیت B", "meta_description": "م" * 155,
    "body_html": BODY, "slug": "test-b"})
conn.close()

# ── اجرای جریان واقعی ─────────────────────────────────────────
approved, needs_review = evaluate_and_sync.evaluate_pending()

# ── راستی‌آزمایی ──────────────────────────────────────────────
passed_count = failed = 0


def check(name, cond, detail=""):
    global passed_count, failed
    mark = "✅" if cond else "❌"
    passed_count += cond
    failed += not cond
    print(f"  {mark} {name}" + (f"  [{detail}]" if detail else ""))


print("\n" + "=" * 60)
print("راستی‌آزمایی dry run فاز ۲")
print("=" * 60)

check("صفر تماس LLM", len(LLM_CALLS) == 0, f"{len(LLM_CALLS)} تماس")

# سناریو A — approved
check("A: یک مقاله approved شد", len(approved) == 1 and approved[0]["article_id"] == id_a)
a = approved[0] if approved else {}
check("A: verdict=approved", a.get("final_verdict") == "approved")
check("A: final_score≈92.2 (0.5×95+0.35×85+0.15×100)",
      abs(a.get("final_score", 0) - 92.2) < 0.15, a.get("final_score"))
check("A: seo_grade فنی دست‌نخورده (95)", a.get("seo_grade") == 95)

conn = db.connect()
rec_a = db.get_article(conn, id_a)
rec_b = db.get_article(conn, id_b)
conn.close()
pa = rec_a["payload"]
check("A: فیلدهای جدید در payload ذخیره شد",
      "final_score" in pa and "final_verdict" in pa and "score_breakdown" in pa)
check("A: seo_grade در DB همچنان 95", pa.get("seo_grade") == 95)

html_files = list(tmp_dir.glob("article-*.html"))
html_ok = False
if html_files:
    content = html_files[0].read_text(encoding="utf-8")
    html_ok = "نمره‌ی نهایی" in content and "گیت‌های سخت" in content and "92.2" in content
check("A: بخش «نمره‌ی نهایی» در HTML", html_ok,
      html_files[0].name if html_files else "فایلی نیست")

# سناریو B — needs_review + ورود به حلقه از مسیر final
check("B: یک مقاله needs_review شد",
      len(needs_review) == 1 and needs_review[0]["article_id"] == id_b)
b = needs_review[0] if needs_review else {}
check("B: verdict=needs_review", b.get("final_verdict") == "needs_review")
check("B: final_score≈87.6 (0.5×92+0.35×76+0.15×100)",
      abs(b.get("final_score", 0) - 87.6) < 0.15, b.get("final_score"))
check("B: دلیل ردّ گیت در reasons",
      any("دروازه" in r or "Quality Gate" in r for r in b.get("reasons", [])),
      "; ".join(b.get("reasons", []))[:80])
check("B: وضعیت DB = needs_review", rec_b["status"] == "needs_review")

# مرز تلگرام (telegram_review_min=80 دست‌نخورده) روی نمره‌ی نهایی
review_min = 80
near = (b.get("final_score") or 0) >= review_min
check("B: نمره‌ی نهایی 87.6 ≥ 80 → کاندید near-miss تلگرام", near)

# پیام تلگرام — بدون ارسال واقعی (تابع خالص)
msg_new = telegram_approver._build_message(
    "تست", 92, "پیش‌نمایش", warning="• دلیل",
    final_score=b.get("final_score"), final_verdict=b.get("final_verdict"))
check("پیام تلگرام: خط «🎯 نمره‌ی نهایی» + وضعیت",
      "🎯 نمره‌ی نهایی" in msg_new and "نیاز به بررسی" in msg_new)
msg_old = telegram_approver._build_message("تست", 92, "پیش‌نمایش")
check("پیام تلگرام بدون final (داده‌ی قدیمی): مثل قبل", "🎯" not in msg_old)

print("\n" + "=" * 60)
print(f"نتیجه: {passed_count} پاس، {failed} شکست | تماس LLM واقعی: 0")
print(f"DB و HTML موقت: {tmp_dir}")
print("=" * 60)
sys.exit(1 if failed else 0)
