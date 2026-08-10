"""تست پچ v2.1 — صفر تماس LLM.

پوشش: آشکارساز Soft Claims (۱۲ مثبت/۴ خنثی/تاییدشده)، QA Cache Key،
should_save_candidate (۶ قانون)، validator soft-claim، ثبت رویداد در DB،
اینتگریشن مینی: ردّ humanize → بدون QA تکراری + رویداد DB + Fail-Closed ثبت.
اجرا:  python test_architecture_v2_1.py   (از پوشه‌ی seo-agent)
"""
import json
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from src.architecture_v2_1_utils import (
    build_qa_cache_key, detect_soft_quantitative_claims, merge_soft_claims,
    should_save_candidate, stable_hash,
)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    mark = "✅" if cond else "❌"
    passed += cond
    failed += not cond
    print(f"  {mark} {name}" + (f"  [{str(detail)[:70]}]" if detail else ""))


print("=" * 60)
print("[۱۴.۱] آشکارساز Soft Quantitative Claims")
print("=" * 60)
POSITIVES = [
    "راه‌اندازی معمولاً چند هفته طول می‌کشد.",
    "بسیاری از رستوران‌ها از این روش استفاده می‌کنند.",
    "این سیستم دقت بسیار بالایی دارد.",
    "هزینه‌ها به شکل چشمگیری کاهش پیدا می‌کنند.",
    "در مدت کوتاهی نتیجه خواهید گرفت.",
    "اغلب مشتریان پاسخ فوری را ترجیح می‌دهند.",
    "بخش بزرگی از تماس‌ها خودکار می‌شود.",
    "این روش عملکرد بهتری دارد.",
    "سامانه سریع‌تر پاسخ می‌دهد.",
    "این راهکار باعث رشد محسوس می‌شود.",
    "در بیشتر موارد اتصال ساده است.",
    "صرفه‌جویی قابل‌توجهی ایجاد می‌شود.",
]
for text in POSITIVES:
    claims = detect_soft_quantitative_claims(text, verified_facts=[])
    check(f"کشف: «{text[:35]}...»",
          bool(claims) and any(c.supported is False for c in claims))

NEUTRALS = [
    "زمان راه‌اندازی به دامنه پروژه و تعداد اتصال‌ها بستگی دارد.",
    "دقت سیستم باید روی داده‌های واقعی کسب‌وکار آزمایش شود.",
    "میزان کاهش هزینه بدون اندازه‌گیری پروژه قابل تعیین نیست.",
    "این قابلیت ممکن است بخشی از درخواست‌های تکراری را خودکار کند.",
]
for text in NEUTRALS:
    check(f"خنثی مجاز: «{text[:35]}...»",
          detect_soft_quantitative_claims(text, verified_facts=[]) == [])

print("\n" + "=" * 60)
print("[۱۴.۲] ادعای تاییدشده")
print("=" * 60)
facts = [{"id": "fact_duration_01",
          "claim": "راه‌اندازی این پروژه معمولاً سه هفته طول می‌کشد.",
          "source_url": "https://example.com/source",
          "allowed_scope": "case_study_alpha", "locked_numbers": ["3"]}]
claims = detect_soft_quantitative_claims(
    "راه‌اندازی این پروژه معمولاً سه هفته طول می‌کشد.", verified_facts=facts)
check("ادعای منطبق با verified_fact → supported=true",
      bool(claims) and all(c.supported for c in claims)
      and claims[0].verified_fact_id == "fact_duration_01")

# ادغام Fail-Closed (API جدید v2.1.1: اتحاد کنترل‌شده + Span Validation)
art = "متن مقاله شامل بسیاری از فرایندها است."
m, invalid = merge_soft_claims(
    deterministic_claims=[{"claim": "بسیاری از فرایندها است.", "exact_span": "بسیاری از",
                           "category": "a", "supported": False, "confidence": "high"}],
    llm_claims=[{"claim": "بسیاری از فرایندها است.", "exact_span": "بسیاری از",
                 "category": "a", "supported": True, "confidence": "high",
                 "required_action": "keep"}],
    article_text=art)
check("ادغام Fail-Closed: قطعیِ unsupported غالب است",
      len(m) == 1 and m[0]["supported"] is False and invalid == [])
m2, invalid2 = merge_soft_claims(
    deterministic_claims=[],
    llm_claims=[{"claim": "جمله‌ای که در مقاله نیست", "exact_span": "نیست",
                 "category": "a", "supported": False, "confidence": "high",
                 "required_action": "remove"}],
    article_text=art)
check("Span جعلی LLM → invalid (وارد نتیجه نمی‌شود)",
      m2 == [] and len(invalid2) == 1
      and invalid2[0]["error"] == "exact_span_not_in_article")

print("\n" + "=" * 60)
print("[۱۴.۳-۱۴.۴] QA Cache Key")
print("=" * 60)
base = {"text": "متن ثابت", "model_name": "gemini-test", "qa_prompt_version": "v2.1",
        "editorial_rules": {"a": 1}, "verified_facts": []}
calls = {"n": 0}
cache = {}
def fake_qa(text):
    calls["n"] += 1
    return {"passed": False}
k1 = build_qa_cache_key(**base)
if k1 not in cache:
    cache[k1] = fake_qa(base["text"])
k2 = build_qa_cache_key(**base)
if k2 not in cache:
    cache[k2] = fake_qa(base["text"])
check("ورودی یکسان → یک بار QA", k1 == k2 and calls["n"] == 1)
check("تغییر نسخه‌ی پرامپت → کلید جدید",
      build_qa_cache_key(**{**base, "qa_prompt_version": "v2.2"}) != k1)
check("تغییر verified_facts → کلید جدید",
      build_qa_cache_key(**{**base, "verified_facts": [{"id": "f1"}]}) != k1)

print("\n" + "=" * 60)
print("[۱۴.۵] should_save_candidate")
print("=" * 60)
def result(*, hard=0, unsupported=0, soft_high=0, soft_med=0, warnings=0, score=5.0,
           hard_policy=False, validator=True, **extra):
    return {"hard_error_count": hard, "unsupported_claim_count": unsupported,
            "high_confidence_soft_unsupported_count": soft_high,
            "medium_confidence_soft_unsupported_count": soft_med,
            "rewrite_warning_count": warnings, "final_score": score,
            "hard_policy_reject": hard_policy, "validator_passed": validator, **extra}

s, _ = should_save_candidate(candidate_result=result(hard=2, score=9),
                             previous_result=result(hard=1, score=5))
check("hard بیشتر → هرگز ذخیره نشود", s is False)
s, _ = should_save_candidate(candidate_result=result(hard=1, unsupported=0),
                             previous_result=result(hard=1, unsupported=1))
check("hard برابر، unsupported کمتر → ذخیره", s is True)
s, _ = should_save_candidate(candidate_result=result(soft_high=2, score=9),
                             previous_result=result(soft_high=1, score=5))
check("soft high بیشتر → ذخیره نشود", s is False)
s, r = should_save_candidate(candidate_result=result(), previous_result=result())
check("Rank برابر → نسخه‌ی قبلی بماند", s is False and r == "rank_tied_keep_previous")
s, r = should_save_candidate(candidate_result=result(score=10, hard_policy=True),
                             previous_result=result(score=1))
check("hard_policy_reject → هرگز ذخیره نشود",
      s is False and r == "candidate_hard_policy_reject")
s, r = should_save_candidate(candidate_result=result(score=10, validator=False),
                             previous_result=result(score=1))
check("validator شکست → هرگز ذخیره نشود",
      s is False and r == "candidate_validator_failed_or_missing")
# v2.1.1: نسخه‌ی میانی کم‌امتیاز (publish_reject) ولی بدون تخلف سخت → قابل ذخیره
s, _ = should_save_candidate(
    candidate_result=result(score=4.0, unsupported=1, publish_reject=True),
    previous_result=result(score=3.0, unsupported=2))
check("کم‌امتیاز ولی بهتر و بدون تخلف سخت → ذخیره می‌شود", s is True)

print("\n" + "=" * 60)
print("[v2.1] Validator انسانی‌سازی — Soft Claim جدید")
print("=" * 60)
from src import writer
OLD = {"title_seo": "ع", "meta_description": "م" * 155, "h1": "ع",
       "body_html": "<p>متن اول.</p><h2>بخش</h2><p>الف [[anchor: ل | ص]].</p>",
       "citable_facts": [], "source_urls": []}
NEW_BAD = dict(OLD)
NEW_BAD["body_html"] = OLD["body_html"].replace("متن اول.", "متن اول که معمولاً سریع‌تر جواب می‌دهد.")
v = writer.validate_humanize(OLD, NEW_BAD)
check("soft claim جدید در humanize → رد",
      any("new_soft_quantitative_claim" in x for x in v), v)
NEW_OK = dict(OLD)
NEW_OK["body_html"] = OLD["body_html"].replace("متن اول.", "متن نخست.")
check("ویرایش سبک بدون soft جدید → قبول", writer.validate_humanize(OLD, NEW_OK) == [])

print("\n" + "=" * 60)
print("[۱۴.۶ + ۱۳] اینتگریشن مینی: ردّ humanize → DB event + بدون QA تکراری")
print("=" * 60)
from src import db, editor_memory, html_export, llm, qa_analyzer, quality_gate, semrush_bridge

tmp_dir = Path(tempfile.mkdtemp(prefix="v21_test_"))
db.DB_PATH = tmp_dir / "agent.db"
html_export.OUTPUT_DIR = tmp_dir
llm.ask = lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM call!"))

QA_CALLS = {"n": 0}
_CODE_OK = {"no_forbidden_phrases": True, "no_unapproved_cta": True,
            "meta_length_150_160": True, "internal_links_min2": True,
            "external_link_min1": True, "complete_last_sentence": True, "_details": {}}

def qa_stub(payload, threshold=90, step="qa_analyze"):
    QA_CALLS["n"] += 1
    return {"passed": False, "overall_score": 80, "qa_passed": True,
            "code_checks": dict(_CODE_OK), "evaluation": {}, "article": {},
            "qa_report": {"passed": True, "checks": []}, "reasons": [], "issues": []}

def gate_stub(payload, step="quality_gate"):
    return {"passed": False, "weighted_score": 5.0, "scores": {"human_tone": 4},
            "issues": [{"category": "robotic_language", "severity": "medium",
                        "location": "x", "exact_quote": "q", "problem": "p",
                        "rewrite_instruction": "r"}],
            "reasons": ["لحن 4"], "rules_compliance": {}, "cliches": [],
            "quantitative_claims": [], "soft_quantitative_claims": [],
            "soft_unsupported_claim_count": 0, "recommendations": {}}

def humanize_bad(payload, gate_report, revision_no=1):
    bad = dict(payload)
    bad["body_html"] = "<p>بدون هدینگ قبلی.</p>"     # H2 حذف → validator رد می‌کند
    v = writer.validate_humanize(payload, bad)
    assert v
    rejected = dict(payload)
    rejected["humanize_rejections"] = [
        {"revision": revision_no, "violations": v,
         "candidate_content_hash": stable_hash(writer._payload_text(bad)),
         "restored_content_hash": stable_hash(writer._payload_text(payload))}]
    return rejected

qa_analyzer.analyze_article = qa_stub
quality_gate.review = gate_stub
writer.humanize_article = humanize_bad
editor_memory.record_issues = lambda issues: None
semrush_bridge.load_analysis = lambda aid: {"verdict": "GOOD", "avg_kd": 20,
                                            "targeted_keywords": [], "per_kw": {}}

from src import evaluate_and_sync
conn = db.connect()
aid = db.save_article(conn, "تست v2.1", {
    "h1": "ع", "title_seo": "مقاله تست", "meta_description": "م" * 155,
    "body_html": "<p>متن.</p><h2>بخش یک</h2><p>الف [[anchor: ل | ص]] "
                 "[[external: م | https://a.ir]].</p>"})
conn.close()

approved, needs_review = evaluate_and_sync.evaluate_pending()
check("QA فقط یک بار اجرا شد (ردّ humanize → بدون QA تکراری)",
      QA_CALLS["n"] == 1, f"{QA_CALLS['n']} تماس")
conn = db.connect()
events = conn.execute("SELECT * FROM pipeline_validation_events WHERE article_id=?",
                      (aid,)).fetchall()
art = db.get_article(conn, aid)
conn.close()
check("رویداد ردّ validator در DB ثبت شد", len(events) == 1)
if events:
    ev = dict(events[0])
    check("رویداد: status=rejected و candidate_saved=0",
          ev["status"] == "rejected" and ev["candidate_saved"] == 0)
    check("رویداد: دلایل و هش‌ها پر", "H2" in ev["rejection_reasons"]
          and len(ev["candidate_content_hash"]) == 64
          and ev["debug_candidate_text"] is None)
check("مقاله needs_review شد", art["status"] == "needs_review")
hist = (art["payload"].get("qa_analysis") or {}).get("revision_history") or []
check("تاریخچه: qa_skipped ثبت شد", any(h.get("qa_skipped") for h in hist))

# Fail-Closed ثبت DB: شکست insert → مقاله هرگز approved نشود
_orig_record = db.record_validation_event
db.record_validation_event = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down"))
conn = db.connect()
aid2 = db.save_article(conn, "تست v2.1 fail-closed", {
    "h1": "ع", "title_seo": "مقاله تست ۲", "meta_description": "م" * 155,
    "body_html": "<p>متن.</p><h2>بخش یک</h2><p>الف [[anchor: ل | ص]] "
                 "[[external: م | https://a.ir]].</p>"})
conn.close()
approved2, needs2 = evaluate_and_sync.evaluate_pending()
conn = db.connect()
art2 = db.get_article(conn, aid2)
conn.close()
db.record_validation_event = _orig_record
reasons2 = " ".join((art2["payload"].get("score_breakdown") or {}).get("reasons") or []) \
    + " " + json.dumps(needs2, ensure_ascii=False)
check("Fail-Closed: شکست ثبت DB → needs_review + دلیل persistence_failed",
      art2["status"] == "needs_review"
      and "validator_event_persistence_failed" in reasons2, art2["status"])

print("\n" + "=" * 60)
print(f"نتیجه: {passed} پاس، {failed} شکست | تماس LLM واقعی: 0")
print("=" * 60)
sys.exit(1 if failed else 0)
