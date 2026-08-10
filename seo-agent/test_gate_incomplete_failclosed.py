"""تأیید Fail-Closed گیت ناقص/truncate (freeze v2.1.1) — صفر تماس LLM.

سناریوی حفره: گیت استثنا می‌دهد ولی QA پاس + کد پاس + SEMrush GOOD + نمره‌ی بالا.
بدون Fail-Closed این مقاله auto-publish می‌شد. تست ثابت می‌کند needs_review می‌ماند.
اجرا:  python test_gate_incomplete_failclosed.py   (از پوشه‌ی seo-agent)
"""
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from src import db, editor_memory, html_export, llm, qa_analyzer, quality_gate, semrush_bridge

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    mark = "✅" if cond else "❌"
    passed += cond
    failed += not cond
    print(f"  {mark} {name}" + (f"  [{str(detail)[:70]}]" if detail else ""))


tmp_dir = Path(tempfile.mkdtemp(prefix="failclosed_"))
db.DB_PATH = tmp_dir / "agent.db"
html_export.OUTPUT_DIR = tmp_dir
llm.ask = lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM call!"))

_CODE_OK = {"no_forbidden_phrases": True, "no_unapproved_cta": True,
            "meta_length_150_160": True, "internal_links_min2": True,
            "external_link_min1": True, "complete_last_sentence": True, "_details": {}}


def qa_stub_pass(payload, threshold=90, step="qa_analyze"):
    # QA کاملاً پاس با نمره‌ی بالا — تنها مانع باید گیتِ ناقص باشد
    return {"passed": True, "overall_score": 95, "qa_passed": True,
            "code_checks": dict(_CODE_OK), "evaluation": {}, "article": {},
            "qa_report": {"passed": True, "checks": []}, "reasons": [], "issues": []}


def gate_truncated(payload, step="quality_gate"):
    raise RuntimeError("پاسخ مدل truncate شد (MAX_TOKENS در step=quality_gate)")


qa_analyzer.analyze_article = qa_stub_pass
quality_gate.review = gate_truncated
editor_memory.record_issues = lambda issues: None
# SEMrush GOOD تا فقط گیت مانع باشد
semrush_bridge.load_analysis = lambda aid: {"verdict": "GOOD", "avg_kd": 20,
                                            "targeted_keywords": [], "per_kw": {}}

from src import evaluate_and_sync

conn = db.connect()
aid = db.save_article(conn, "تست fail-closed گیت", {
    "h1": "ع", "title_seo": "مقاله تست", "meta_description": "م" * 155,
    "body_html": "<p>متن کامل.</p><h2>بخش</h2><p>الف [[anchor: ل | ص]] "
                 "[[external: م | https://a.ir]].</p>"})
conn.close()

approved, needs_review = evaluate_and_sync.evaluate_pending()

conn = db.connect()
art = db.get_article(conn, aid)
conn.close()
p = art["payload"]

print("=" * 60)
print("تأیید Fail-Closed — گیت truncate با نمره‌ی بالا (حفره‌ی auto-publish)")
print("=" * 60)
check("مقاله auto-publish نشد (approved خالی)", approved == [], approved)
check("status = needs_review (نه approved/published)",
      art["status"] == "needs_review", art["status"])
check("final_verdict != approved یا نبود انتشار خودکار",
      p.get("final_verdict") != "approved" or art["status"] == "needs_review")
reasons = " ".join(
    (p.get("score_breakdown") or {}).get("reasons") or []) + " " + \
    " ".join(r for item in needs_review for r in item.get("reasons", []))
check("دلیل «quality_gate_incomplete_or_truncated» ثبت شد",
      "quality_gate_incomplete" in reasons or "gate_incomplete" in str(
          [i.get("reasons") for i in needs_review]) or
      "quality_gate_incomplete_or_truncated" in reasons, reasons[:80])

print(f"\n  approved={len(approved)} needs_review={len(needs_review)} | "
      f"status={art['status']} | final={p.get('final_score')} "
      f"({p.get('final_verdict')})")

print("\n" + "=" * 60)
print(f"نتیجه: {passed} پاس، {failed} شکست | تماس LLM واقعی: 0")
print("=" * 60)
sys.exit(1 if failed else 0)
