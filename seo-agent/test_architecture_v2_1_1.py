"""تست پچ v2.1.1 — صفر تماس LLM.

پوشش: Rejection Semantics (hard/publish/alias)، Span و Schema، رفتار Confidence،
Mandatory Cleanup (اینتگریشن مینی: دقیقاً یک بار، خنثی‌سازی، ردّ، عدم تکرار)،
رویداد DB با stage=mandatory_cleanup.
اجرا:  python test_architecture_v2_1_1.py   (از پوشه‌ی seo-agent)
"""
import json
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from src.architecture_v2_1_utils import (
    apply_rejection_semantics, collect_cleanup_targets, count_soft_by_confidence,
    detect_soft_quantitative_claims, merge_soft_claims, should_save_candidate,
    stable_hash, validate_llm_soft_claim,
)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    mark = "✅" if cond else "❌"
    passed += cond
    failed += not cond
    print(f"  {mark} {name}" + (f"  [{str(detail)[:70]}]" if detail else ""))


print("=" * 60)
print("[۱] Rejection Semantics")
print("=" * 60)


def result(*, hard=0, unsupported=0, soft_high=0, soft_med=0, warnings=0,
           score=5.0, hard_policy=False, validator=True, **extra):
    return {"hard_error_count": hard, "unsupported_claim_count": unsupported,
            "high_confidence_soft_unsupported_count": soft_high,
            "medium_confidence_soft_unsupported_count": soft_med,
            "rewrite_warning_count": warnings, "final_score": score,
            "hard_policy_reject": hard_policy, "validator_passed": validator, **extra}


s, _ = should_save_candidate(
    candidate_result=result(score=4.0, unsupported=1, publish_reject=True),
    previous_result=result(score=3.0, unsupported=2))
check("نسخه‌ی میانی کم‌امتیاز بدون تخلف سخت → ذخیره می‌شود", s is True)

s, r = should_save_candidate(
    candidate_result=result(score=10.0, hard_policy=True),
    previous_result=result(score=4.0))
check("امتیاز بالا با تخلف سخت → هرگز ذخیره نشود",
      s is False and r == "candidate_hard_policy_reject")

ev = apply_rejection_semantics(
    {"validator_passed": True, "schema_valid": True,
     "validator_event_persisted": True, "unsupported_claim_count": 0,
     "high_confidence_soft_unsupported_count": 0, "final_score": 4.0,
     "unresolved_source_gap": False},
    publish_threshold=7.0)
check("would_reject = alias دقیق publish_reject",
      ev["hard_policy_reject"] is False and ev["publish_reject"] is True
      and ev["would_reject"] is True and ev["passed"] is False)

ev2 = apply_rejection_semantics(
    {"validator_passed": True, "schema_valid": True,
     "validator_event_persisted": True, "unsupported_claim_count": 0,
     "high_confidence_soft_unsupported_count": 1, "final_score": 9.0,
     "unresolved_source_gap": False},
    publish_threshold=7.0)
check("soft high بی‌منبع → hard_policy_reject حتی با امتیاز بالا",
      ev2["hard_policy_reject"] is True and ev2["publish_reject"] is True)

print("\n" + "=" * 60)
print("[۲] Schema و Span")
print("=" * 60)
ok, err = validate_llm_soft_claim(
    item={"claim": "بسیاری از فرایندها خودکار می‌شوند",
          "exact_span": "بسیاری از فرایندها",
          "confidence": "high", "required_action": "neutralize"},
    article_text="متن مقاله هیچ چنین عبارتی ندارد.")
check("exact_span باید در مقاله باشد", ok is False and err == "exact_span_not_in_article")

text = "بسیاری از فرایندها خودکار می‌شوند."
claims = detect_soft_quantitative_claims(text, [])
check("Detector قطعی Span واقعی می‌دهد",
      bool(claims) and claims[0].exact_span == "بسیاری از"
      and claims[0].exact_span in text and claims[0].confidence == "high")

art = "راه‌اندازی معمولاً چند هفته طول می‌کشد."
det = [c.as_dict() for c in detect_soft_quantitative_claims(art, [])]
llm_dup = [dict(det[0])]
merged, invalid = merge_soft_claims(deterministic_claims=det, llm_claims=llm_dup,
                                    article_text=art)
spans = [(m["claim"], m["exact_span"], m["category"]) for m in merged]
check("Claim تکراری (قطعی+LLM) → deduplicate", len(spans) == len(set(spans))
      and invalid == [])

print("\n" + "=" * 60)
print("[۳] رفتار Confidence")
print("=" * 60)
from src import quality_gate, llm
_orig_ask = llm.ask


def gate_llm_stub(step, user_content, **kw):
    return {"scores": {"human_tone": 9, "seo": 9, "eeat": 9, "keyword": 9,
                       "structure": 9, "conversion": 9, "trust": 9},
            "quantitative_claims": [], "issues": [], "cliches": [],
            "unsourced_claims": [],
            "soft_quantitative_claims": [
                {"claim": "متن نمونه برای بررسی است.",
                 "exact_span": "متن نمونه",
                 "category": "performance_generalization",
                 "asserted_outcome": "x", "supported": False,
                 "verified_fact_id": None, "confidence": "medium",
                 "required_action": "neutralize", "reason": "r"}]}


# متن با یک عبارت خنثی (بدون trigger قطعی) — LLM-only claim را می‌سنجیم
NEUTRAL_BODY = "<p>متن نمونه برای بررسی است.</p>"
# متن با یک high قطعی deterministic
HIGH_BODY = "<p>این سامانه دقت بسیار بالایی دارد.</p>"

llm.ask = gate_llm_stub
quality_gate.llm.ask = gate_llm_stub
g = quality_gate.review({"title_seo": "t", "meta_description": "م", "body_html": NEUTRAL_BODY})
check("medium (LLM-only) → گیت پاس می‌ماند، فقط warning، بدون source_gap",
      g["passed"] is True and g["unresolved_source_gap"] is False
      and g["medium_confidence_soft_unsupported_count"] == 1)


def gate_llm_high(step, user_content, **kw):
    out = gate_llm_stub(step, user_content, **kw)
    out["soft_quantitative_claims"][0]["confidence"] = "high"
    return out


# LLM-only high → طبق calibration به medium تنزل → گیت سخت نمی‌شود
llm.ask = gate_llm_high
quality_gate.llm.ask = gate_llm_high
g2 = quality_gate.review({"title_seo": "t", "meta_description": "م", "body_html": NEUTRAL_BODY})
check("LLM-only high → تنزل به medium (LLM حق high مستقل ندارد) → passed=true",
      g2["passed"] is True and g2["high_confidence_soft_unsupported_count"] == 0
      and g2["medium_confidence_soft_unsupported_count"] == 1)

# high واقعی = deterministic → گیت سخت
llm.ask = lambda s, u, **k: {"scores": {"human_tone": 9, "seo": 9, "eeat": 9, "keyword": 9,
                                        "structure": 9, "conversion": 9, "trust": 9},
                             "quantitative_claims": [], "issues": [], "cliches": [],
                             "unsourced_claims": [], "soft_quantitative_claims": []}
quality_gate.llm.ask = llm.ask
g_det = quality_gate.review({"title_seo": "t", "meta_description": "م", "body_html": HIGH_BODY})
check("high قطعی (deterministic «دقت بسیار بالا») → passed=false (گیت سخت)",
      g_det["passed"] is False and g_det["high_confidence_soft_unsupported_count"] == 1)


def gate_llm_low(step, user_content, **kw):
    out = gate_llm_stub(step, user_content, **kw)
    out["soft_quantitative_claims"][0]["confidence"] = "low"
    return out


llm.ask = gate_llm_low
quality_gate.llm.ask = gate_llm_low
g3 = quality_gate.review({"title_seo": "t", "meta_description": "م", "body_html": NEUTRAL_BODY})
check("low فقط گزارشی → passed=true و بدون source gap",
      g3["passed"] is True and g3["unresolved_source_gap"] is False)


def gate_llm_fake_span(step, user_content, **kw):
    out = gate_llm_stub(step, user_content, **kw)
    out["soft_quantitative_claims"][0]["exact_span"] = "عبارت جعلی ناموجود"
    out["soft_quantitative_claims"][0]["claim"] = "جمله‌ی جعلی با عبارت جعلی ناموجود"
    return out


# calibration: Span جعلیِ منفرد → فقط حذف Claim + warning، نه schema_valid=false، نه ردّ
llm.ask = gate_llm_fake_span
quality_gate.llm.ask = gate_llm_fake_span
g4 = quality_gate.review({"title_seo": "t", "meta_description": "م", "body_html": NEUTRAL_BODY})
check("Span جعلی → حذف Claim + warning، schema_valid=true، مقاله ردّ نمی‌شود",
      g4["schema_valid"] is True and g4["passed"] is True
      and len(g4["invalid_soft_claims"]) == 1
      and g4["high_confidence_soft_unsupported_count"] == 0)
llm.ask = _orig_ask
quality_gate.llm.ask = _orig_ask

print("\n" + "=" * 60)
print("[۴] Mandatory Cleanup — اینتگریشن مینی (DB موقت، صفر LLM)")
print("=" * 60)
from src import db, editor_memory, html_export, qa_analyzer, semrush_bridge, writer

tmp_dir = Path(tempfile.mkdtemp(prefix="v211_test_"))
db.DB_PATH = tmp_dir / "agent.db"
html_export.OUTPUT_DIR = tmp_dir
llm.ask = lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM call!"))

QA_CALLS = {"n": 0}
CLEANUP_CALLS = {"n": 0}
_CODE_OK = {"no_forbidden_phrases": True, "no_unapproved_cta": True,
            "meta_length_150_160": True, "internal_links_min2": True,
            "external_link_min1": True, "complete_last_sentence": True, "_details": {}}
BAD_SOFT_SENT = "راه‌اندازی معمولاً چند هفته طول می‌کشد."
BODY = ("<p>متن. " + BAD_SOFT_SENT + "</p><h2>بخش یک</h2>"
        "<p>الف [[anchor: ل | ص]] [[external: م | https://a.ir]].</p>")


def qa_stub(payload, threshold=90, step="qa_analyze"):
    QA_CALLS["n"] += 1
    return {"passed": False, "overall_score": 80, "qa_passed": True,
            "code_checks": dict(_CODE_OK), "evaluation": {}, "article": {},
            "qa_report": {"passed": True, "checks": []}, "reasons": [], "issues": []}


def gate_stub(payload, step="quality_gate"):
    body = payload.get("body_html", "")
    det = [c.as_dict() for c in detect_soft_quantitative_claims(
        body, verified_facts=[])]
    high = sum(1 for c in det if not c["supported"])
    return {"passed": False, "weighted_score": 5.0, "scores": {"human_tone": 4},
            "issues": [{"category": "robotic_language", "severity": "medium",
                        "location": "x", "exact_quote": "q", "problem": "p",
                        "rewrite_instruction": "r"}],
            "reasons": ["لحن 4"], "rules_compliance": {}, "cliches": [],
            "quantitative_claims": [], "soft_quantitative_claims": det,
            "soft_unsupported_claim_count": high,
            "high_confidence_soft_unsupported_count": high,
            "medium_confidence_soft_unsupported_count": 0,
            "low_confidence_soft_unsupported_count": 0,
            "unresolved_source_gap": False, "schema_valid": True,
            "invalid_soft_claims": [], "recommendations": {}}


def humanize_bad(payload, gate_report, revision_no=1):
    bad = dict(payload)
    bad["body_html"] = payload["body_html"] + "<p>این روش عملکرد بهتری دارد.</p>"
    v = writer.validate_humanize(payload, bad)
    assert v, "باید soft جدید را بگیرد"
    rejected = dict(payload)
    rejected["humanize_rejections"] = list(payload.get("humanize_rejections") or []) + [
        {"revision": revision_no, "violations": v,
         "candidate_content_hash": stable_hash(writer._payload_text(bad)),
         "restored_content_hash": stable_hash(writer._payload_text(payload))}]
    return rejected


def cleanup_stub(payload, cleanup_plan):
    CLEANUP_CALLS["n"] += 1
    out = dict(payload)
    out["body_html"] = out["body_html"].replace(
        BAD_SOFT_SENT,
        "زمان راه‌اندازی به دامنه پروژه، تعداد اتصال‌ها و وضعیت زیرساخت بستگی دارد.")
    return out


qa_analyzer.analyze_article = qa_stub
quality_gate.review = gate_stub
writer.humanize_article = humanize_bad
writer.cleanup_article = cleanup_stub
editor_memory.record_issues = lambda issues: None
semrush_bridge.load_analysis = lambda aid: {"verdict": "GOOD", "avg_kd": 20,
                                            "targeted_keywords": [], "per_kw": {}}

from src import evaluate_and_sync
conn = db.connect()
aid = db.save_article(conn, "تست cleanup", {
    "h1": "ع", "title_seo": "مقاله تست cleanup", "meta_description": "م" * 155,
    "body_html": BODY})
conn.close()

approved, needs_review = evaluate_and_sync.evaluate_pending()

conn = db.connect()
art = db.get_article(conn, aid)
events = conn.execute(
    "SELECT stage, status, candidate_saved FROM pipeline_validation_events "
    "WHERE article_id=?", (aid,)).fetchall()
conn.close()
p = art["payload"]
hist = (p.get("qa_analysis") or {}).get("revision_history") or []

check("QA تکراری بعد از ردّ humanize اجرا نشد (۱ اولیه + ۱ برای cleanup)",
      QA_CALLS["n"] == 2, f"{QA_CALLS['n']}")
check("Mandatory Cleanup دقیقاً یک بار اجرا شد", CLEANUP_CALLS["n"] == 1,
      CLEANUP_CALLS["n"])
check("state: mandatory_cleanup_attempted=True",
      p.get("mandatory_cleanup_attempted") is True)
check("خنثی‌سازی ادعای مدت: «معمولاً چند هفته» حذف و جمله‌ی شرطی آمد",
      "معمولاً چند هفته" not in p.get("body_html", "")
      and "به دامنه پروژه" in p.get("body_html", ""))
check("نسخه‌ی cleanup ذخیره شد (کم‌امتیاز ولی بدون تخلف سخت)",
      p.get("mandatory_cleanup_completed") is True)
check("رویداد humanize در DB", any(e["stage"] == "humanize" for e in events))
check("تاریخچه شامل دور mandatory_cleanup",
      any(h.get("mode") == "mandatory_cleanup" for h in hist))
check("مقاله needs_review (امتیاز زیر آستانه)", art["status"] == "needs_review")

# — عدم اجرای Cleanup دوم در همان مقاله —
QA_CALLS["n"] = 0
CLEANUP_CALLS["n"] = 0
conn = db.connect()
conn.execute("UPDATE articles SET status='pending' WHERE id=?", (aid,))
conn.commit()
conn.close()
evaluate_and_sync.evaluate_pending()
check("Cleanup دوم برای همان مقاله اجرا نشد", CLEANUP_CALLS["n"] == 0,
      CLEANUP_CALLS["n"])

# — ردّ Cleanup توسط validator → رویداد stage=mandatory_cleanup + حفظ نسخه —
def cleanup_bad(payload, cleanup_plan):
    CLEANUP_CALLS["n"] += 1
    out = dict(payload)
    out["body_html"] = out["body_html"].replace(
        BAD_SOFT_SENT, "راه‌اندازی ۹۹٪ سریع انجام می‌شود.")   # عدد جدید → رد
    return out


writer.cleanup_article = cleanup_bad
QA_CALLS["n"] = 0
CLEANUP_CALLS["n"] = 0
conn = db.connect()
aid2 = db.save_article(conn, "تست cleanup rejected", {
    "h1": "ع", "title_seo": "مقاله تست ردّ cleanup", "meta_description": "م" * 155,
    "body_html": BODY})
conn.close()
evaluate_and_sync.evaluate_pending()
conn = db.connect()
art2 = db.get_article(conn, aid2)
ev2_rows = conn.execute(
    "SELECT stage, status, candidate_saved FROM pipeline_validation_events "
    "WHERE article_id=?", (aid2,)).fetchall()
conn.close()
p2 = art2["payload"]
check("Cleanup ناموفق → متن قبلی حفظ شد",
      BAD_SOFT_SENT in p2.get("body_html", ""))
cl_ev = [e for e in ev2_rows if e["stage"] == "mandatory_cleanup"]
check("رویداد stage=mandatory_cleanup ثبت شد (rejected, saved=0)",
      len(cl_ev) == 1 and cl_ev[0]["status"] == "rejected"
      and cl_ev[0]["candidate_saved"] == 0)
check("وضعیت needs_review و completed=False",
      art2["status"] == "needs_review"
      and p2.get("mandatory_cleanup_completed") is False)
check("QA بعد از ردّ cleanup اجرا نشد", QA_CALLS["n"] == 1, QA_CALLS["n"])

print("\n" + "=" * 60)
print(f"نتیجه: {passed} پاس، {failed} شکست | تماس LLM واقعی: 0")
print("=" * 60)
sys.exit(1 if failed else 0)
