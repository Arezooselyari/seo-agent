"""تست واحد لایه‌ی final_score — بدون LLM، بدون شبکه، بدون نوشتن در DB.

بخش ۱: سناریوهای مصنوعی (منطق گیت سخت + وزن‌دهی + verdict).
بخش ۲: داده‌ی واقعی qa_analysis مقالات موجود در agent.db (فقط خواندن).
اجرا:  python test_final_score.py   (از پوشه‌ی seo-agent)
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from src import db, final_score

# config ثابت برای تست (مستقل از settings.yaml تا تست قطعی بماند)
CFG = {
    "approval_threshold": 90,
    "weights": {"qa": 0.50, "gate": 0.35, "semrush": 0.15},
    "semrush_component": {"GOOD": 100, "WEAK": 50},
    "reject_below": 60,
}

passed_count = failed = 0


def check(name, cond, detail=""):
    global passed_count, failed
    mark = "✅" if cond else "❌"
    if cond:
        passed_count += 1
    else:
        failed += 1
    print(f"  {mark} {name}" + (f"  [{detail}]" if detail else ""))


def full_analysis(**over):
    """یک analysis کامل و سالم (شکل زنده‌ی حلقه) که همه‌چیز را پاس می‌کند."""
    a = {
        "overall_score": 95,
        "qa_passed": True,
        "code_checks": {"no_forbidden_phrases": True, "meta_length_150_160": True,
                        "internal_links_min2": True, "external_link_min1": True,
                        "complete_last_sentence": True, "_details": {}},
        "quality_gate": {"passed": True, "weighted_score": 8.5,
                         "scores": {"human_tone": 8}},
        "semrush": {"verdict": "GOOD", "avg_kd": 30},
    }
    a.update(over)
    return a


print("=" * 60)
print("بخش ۱ — سناریوهای مصنوعی")
print("=" * 60)

# [1] مقاله‌ی کامل → approved؛ نمره = 0.5*95 + 0.35*85 + 0.15*100 = 92.25 → 92.2/92.3
r = final_score.compute(full_analysis(), CFG)
check("مقاله‌ی کامل → approved", r["final_verdict"] == "approved", r["final_verdict"])
check("نمره‌ی ترکیبی درست (92.2)", abs(r["final_score"] - 92.2) < 0.15, r["final_score"])

# [2] گیت لحن رد → needs_review حتی با QA=95 (گیت سخت جبران‌ناپذیر است)
r = final_score.compute(full_analysis(
    quality_gate={"passed": False, "weighted_score": 7.6, "scores": {"human_tone": 6}}), CFG)
check("ردّ گیت کیفیت → needs_review (با QA=95)", r["final_verdict"] == "needs_review")
check("نمره پایین‌تر از QA خام", r["final_score"] < 95, r["final_score"])
check("دلیل ردّ گیت ثبت شده",
      any("دروازه" in x for x in r["score_breakdown"]["reasons"]))

# [3] بدون گیت و SEMrush (داده‌ی قدیمی) → بازتوزیع وزن → نمره = خود QA
r = final_score.compute({"overall_score": 95, "qa_passed": True,
                         "code_checks": full_analysis()["code_checks"]}, CFG)
check("بازتوزیع وزن اجزای غایب (نمره=95)", r["final_score"] == 95.0, r["final_score"])
check("غایب‌ها مانع approved نیستند (None≠False)", r["final_verdict"] == "approved")

# [4] SEMrush WEAK → گیت سخت رد + جزء نمره 50
r = final_score.compute(full_analysis(semrush={"verdict": "WEAK", "avg_kd": 70}), CFG)
check("SEMrush WEAK → needs_review", r["final_verdict"] == "needs_review")
check("جزء semrush=50", r["score_breakdown"]["components"]["semrush"] == 50.0)

# [5] شکست چک کد → needs_review
cc = dict(full_analysis()["code_checks"]); cc["no_forbidden_phrases"] = False
cc["_details"] = {"found_forbidden": ["در دنیای رقابتی امروز"]}
r = final_score.compute(full_analysis(code_checks=cc), CFG)
check("شکست چک کد → needs_review", r["final_verdict"] == "needs_review")
check("عبارت ممنوعه → would_reject=True", r["score_breakdown"]["would_reject"] is True)

# [6] qa_passed=False → needs_review
r = final_score.compute(full_analysis(qa_passed=False), CFG)
check("qa_passed=False → needs_review", r["final_verdict"] == "needs_review")

# [7] مرز آستانه: دقیقاً 90 → approved؛ کمتر → needs_review
# بدون semrush → بازتوزیع: (0.5*90 + 0.35*90) / 0.85 = 90.0
a90 = full_analysis(overall_score=90,
                    quality_gate={"passed": True, "weighted_score": 9.0})
del a90["semrush"]
r90 = final_score.compute(a90, CFG)
check("دقیقاً روی آستانه (90.0) → approved", r90["final_verdict"] == "approved",
      r90["final_score"])
# (0.5*87 + 0.35*90) / 0.85 = 88.2 → زیر آستانه
a88 = full_analysis(overall_score=87,
                    quality_gate={"passed": True, "weighted_score": 9.0})
del a88["semrush"]
r88 = final_score.compute(a88, CFG)
check("زیر آستانه (88.2) → needs_review", r88["final_verdict"] == "needs_review",
      r88["final_score"])

# [8] شکل ذخیره‌شده‌ی DB (qa_report.passed به‌جای qa_passed، بدون code_checks)
stored = {
    "overall_score": 92,
    "qa_report": {"passed": True},
    "quality_gate": {"passed": False, "weighted_score": 7.6, "scores": {"human_tone": 6}},
    "semrush": {"verdict": "GOOD"},
}
r = final_score.compute(stored, CFG)
check("شکل DB: qa_report.passed خوانده شد",
      r["score_breakdown"]["hard_gates"]["qa_passed"] is True)
check("شکل DB: code_checks غایب → None (نه False)",
      r["score_breakdown"]["hard_gates"]["code_checks_ok"] is None)
check("شکل DB: ردّ گیت → needs_review", r["final_verdict"] == "needs_review")

# [9] نمره‌ی خیلی پایین → would_reject ولی verdict همچنان needs_review (فاز ۱ ردّ ندارد)
r = final_score.compute({"overall_score": 40, "qa_passed": False}, CFG)
check("نمره 40 → would_reject=True", r["score_breakdown"]["would_reject"] is True)
check("فاز ۱: هرگز verdict=rejected", r["final_verdict"] == "needs_review")

# [10] rank_key: عبور گیت‌ها بر نمره‌ی فنی بالاتر مقدم است
low_but_clean = full_analysis(overall_score=85)
high_but_gated = full_analysis(
    quality_gate={"passed": False, "weighted_score": 7.0, "scores": {"human_tone": 5}})
check("rank_key: گیت‌پاس (85) > گیت‌رد (95)",
      final_score.rank_key(low_but_clean, CFG) > final_score.rank_key(high_but_gated, CFG))

# [11] خالص‌بودن: ورودی تغییر نمی‌کند و seo_grade دست نمی‌خورد
a = full_analysis(); a["seo_grade"] = 95
before = repr(sorted(a.keys())) + repr(a["seo_grade"])
final_score.compute(a, CFG)
check("تابع خالص: ورودی دست‌نخورده", repr(sorted(a.keys())) + repr(a["seo_grade"]) == before)

# [12] بدون config → از settings.yaml می‌خواند و خطا نمی‌دهد
r = final_score.compute(full_analysis())
check("خواندن config از settings.yaml", r["final_verdict"] in ("approved", "needs_review"),
      f"score={r['final_score']}")

print()
print("=" * 60)
print("بخش ۲ — داده‌ی واقعی qa_analysis از agent.db (فقط خواندن)")
print("=" * 60)

conn = db.connect()
rows = conn.execute("SELECT id, status, payload FROM articles ORDER BY id").fetchall()
conn.close()

import json
real = 0
for row in rows:
    payload = json.loads(row["payload"])
    qa = payload.get("qa_analysis")
    if not qa:
        continue
    real += 1
    r = final_score.compute(qa, CFG)
    ok_shape = (
        isinstance(r["final_score"], float)
        and 0 <= r["final_score"] <= 100
        and r["final_verdict"] in ("approved", "needs_review")
        and "hard_gates" in r["score_breakdown"]
    )
    check(f"مقاله #{row['id']} (وضعیت={row['status']}): خروجی سالم", ok_shape,
          f"final={r['final_score']}, verdict={r['final_verdict']}")
check("حداقل یک مقاله‌ی واقعی تست شد", real >= 1, f"{real} مقاله")

print()
print("=" * 60)
print(f"نتیجه: {passed_count} پاس، {failed} شکست")
print("=" * 60)
sys.exit(1 if failed else 0)
