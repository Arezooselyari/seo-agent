"""تست چک‌لیستِ عواملِ رتبه‌ی گوگل + منطقِ ranking-aligned در final_score.
بدونِ LLM، بدونِ شبکه. اجرا:  python test_seo_checklist.py  (از پوشه‌ی seo-agent)
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from src import final_score, seo_checklist as sc

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    mark = "✅" if cond else "❌"
    passed += bool(cond); failed += (not cond)
    print(f"  {mark} {name}" + (f"  [{str(detail)[:70]}]" if detail else ""))


# ── نمونه‌ی مقاله‌ی کامل (همه‌ی عوامل) ──
KW = {"primary_fa": "هوش مصنوعی برای کسب و کار کوچک",
      "secondary": ["چت‌بات هوش مصنوعی", "اتوماسیون بازاریابی"]}
GOOD_BODY = (
    "<p>هوش مصنوعی برای کسب و کار کوچک دیگر یک انتخاب لوکس نیست. در این راهنما "
    "کاربردهای عملی را با آمار و منابع بررسی می‌کنیم. "
    + " ".join(["این ابزارها به تیم‌های کوچک کمک می‌کنند کارهای تکراری را بسپارند."] * 45)
    + "</p>"
    "<h2>هوش مصنوعی در بازاریابی کسب و کار کوچک</h2>"
    "<p>چت‌بات هوش مصنوعی پاسخ‌گویی را سریع‌تر می‌کند. [[anchor: راهنمای چت‌بات | /chatbot]] "
    + " ".join(["اتوماسیون بازاریابی فرایندها را ساده می‌کند."] * 35) + "</p>"
    "<h2>چالش‌های پیاده‌سازی</h2>"
    "<p>کیفیت داده مهم است. [[anchor: کیفیت داده | /data]] [[external: منبع IBM | https://ibm.com/ai]] "
    + " ".join(["پیش‌نیازها باید پیش از شروع بررسی شوند."] * 35) + "</p>"
    "<h2>جمع‌بندی هوش مصنوعی برای کسب و کار کوچک</h2>"
    "<p>با برنامه‌ریزی درست می‌توان شروع کرد.</p>"
    "<h3>هوش مصنوعی برای کسب و کار کوچک از کجا شروع شود؟</h3><p>از یک فرایند ساده.</p>"
    "<h3>هزینه چقدر است؟</h3><p>به ابزار بستگی دارد.</p>"
    "<h3>آیا به تیم فنی نیاز است؟</h3><p>لزوماً نه.</p>"
)
GOOD = {"title_seo": "هوش مصنوعی برای کسب و کار کوچک؛ راهنمای کامل ۲۰۲۶",
        "h1": "هوش مصنوعی برای کسب و کار کوچک",
        "meta_description": "هوش مصنوعی برای کسب و کار کوچک چه کاربردهایی دارد؟ از چت‌بات و بازاریابی تا چالش‌ها و نکات انتخاب ابزار مناسب را با آمار واقعی در این راهنمای کامل بخوانید.",
        "body_html": GOOD_BODY, "target_keywords": KW,
        "verified_facts": [{"stat": "۸۳٪", "source": "IBM"}], "image_keywords": ["ai", "business"]}

THIN = {"title_seo": "مقاله", "h1": "مقاله", "meta_description": "کوتاه",
        "body_html": "<p>متن کوتاه بدون داده و لینک.</p>", "target_keywords": KW}

print("=" * 62); print("[۱] چک‌لیستِ SEO — تشخیصِ عوامل"); print("=" * 62)
rg = sc.evaluate(GOOD, min_score=70)
check("مقاله‌ی کامل → passed", rg["passed"], f"seo_score={rg['seo_score']}")
check("مقاله‌ی کامل → نمره‌ی بالا", rg["seo_score"] >= 85, rg["seo_score"])
check("مقاله‌ی کامل → بدونِ شکستِ بحرانی", not rg["critical_misses"], rg["critical_misses"])
rt = sc.evaluate(THIN, min_score=70)
check("متنِ ضعیف → not passed", not rt["passed"], f"seo_score={rt['seo_score']}")
check("متنِ ضعیف → شکستِ بحرانی دارد", len(rt["critical_misses"]) >= 3, rt["critical_misses"])
check("کیورد در عنوان تشخیص داده شد", rg["factors"]["keyword_in_title"]["passed"])
check("E-E-A-T/داده تشخیص داده شد", rg["factors"]["data_citations_eeat"]["passed"])
check("۳ لینکِ داخلی+خارجی تشخیص داده شد",
      rg["factors"]["internal_links"]["passed"] and rg["factors"]["external_citation"]["passed"])

print("\n" + "=" * 62); print("[۲] final_score حالتِ ranking-aligned"); print("=" * 62)
RANK = {"approval_threshold": 70, "ranking_aligned_mode": True,
        "weights": {"seo": 1.0, "qa": 0.0, "gate": 0.0, "semrush": 0.0},
        "semrush_component": {"GOOD": 100, "WEAK": 50}}


def analysis(seo_pass=True, seo_score=92, **over):
    a = {"seo_checklist": {"seo_score": seo_score, "passed": seo_pass, "critical_misses": []},
         "overall_score": 55,           # QAِ سلیقه‌ای پایین
         "qa_passed": False,            # داورِ سلیقه‌ای رد
         "code_checks": {"no_forbidden_phrases": True, "meta_length_150_160": True,
                         "internal_links_min2": True, "external_link_min1": True,
                         "complete_last_sentence": True, "_details": {}},
         "quality_gate": {"passed": False, "weighted_score": 4.0, "scores": {"human_tone": 3}},
         "semrush": {"verdict": "GOOD"}}
    a.update(over); return a


r = final_score.compute(analysis(), RANK)
check("seo پاس + qa/gate سلیقه‌ای رد → approved", r["final_verdict"] == "approved",
      f"verdict={r['final_verdict']}, final={r['final_score']}")
check("نمره‌ی نهایی = نمره‌ی چک‌لیستِ SEO", r["final_score"] == 92, r["final_score"])

r2 = final_score.compute(analysis(seo_pass=False, seo_score=55,
      seo_checklist={"seo_score": 55, "passed": False, "critical_misses": ["word_count_adequate"]}), RANK)
check("seo رد (زیرِ آستانه) → needs_review", r2["final_verdict"] == "needs_review", r2["final_verdict"])

# آنتی‌جعل باید همچنان مسدود کند حتی با seo عالی
r3 = final_score.compute(analysis(quality_gate={"passed": False, "weighted_score": 8.0,
      "quantitative_claims": [{"status": "unsupported"}]}), RANK)
check("seo عالی ولی آمارِ بی‌منبع → needs_review (آنتی‌جعل)",
      r3["final_verdict"] == "needs_review" and r3["score_breakdown"]["hard_policy_reject"],
      f"verdict={r3['final_verdict']}, hard={r3['score_breakdown']['hard_policy_reject']}")

# high soft claim هم باید مسدود کند
r3b = final_score.compute(analysis(quality_gate={"passed": False, "weighted_score": 8.0,
      "high_confidence_soft_unsupported_count": 2}), RANK)
check("seo عالی ولی ۲ ادعای نرمِ high → needs_review",
      r3b["final_verdict"] == "needs_review", r3b["final_verdict"])

# چک‌های قطعیِ کد همچنان گیتِ سخت‌اند
r4 = final_score.compute(analysis(code_checks={"complete_last_sentence": False, "_details": {}}), RANK)
check("seo عالی ولی جمله‌ی ناتمام → needs_review", r4["final_verdict"] == "needs_review", r4["final_verdict"])

# SEMrush WEAK همچنان گیتِ سخت است
r5 = final_score.compute(analysis(semrush={"verdict": "WEAK"}), RANK)
check("seo عالی ولی SEMrush WEAK → needs_review", r5["final_verdict"] == "needs_review", r5["final_verdict"])

print("\n" + "=" * 62); print("[۳] سازگاریِ عقب‌رو — حالتِ قدیمی دست‌نخورده"); print("=" * 62)
OLD = {"approval_threshold": 90, "weights": {"qa": 0.5, "gate": 0.35, "semrush": 0.15},
       "semrush_component": {"GOOD": 100, "WEAK": 50}}
# حالتِ قدیمی (بدونِ پرچم): qa_passed=False باید مانعِ approved شود
r6 = final_score.compute(analysis(overall_score=95, qa_passed=False), OLD)
check("حالتِ قدیمی: qa_passed=False → needs_review", r6["final_verdict"] == "needs_review", r6["final_verdict"])

print("\n" + "=" * 62)
print(f"نتیجه: {passed} پاس، {failed} شکست | تماس LLM واقعی: 0")
print("=" * 62)
sys.exit(1 if failed else 0)
