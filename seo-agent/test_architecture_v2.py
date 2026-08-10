"""تست معماری v2 (ضد جعل واقعیت) — صفر تماس LLM.

پوشش: پرامپت‌های Renderشده (fact_policy/cta/H2)، حذف قوانین متناقض قدیمی،
Validator انسانی‌سازی، would_reject یکپارچه، منطق نسخه‌ی برنده، گیت ادعای کمی،
چک CTA تاییدنشده.
اجرا:  python test_architecture_v2.py   (از پوشه‌ی seo-agent)
"""
import json
import sys
sys.stdout.reconfigure(encoding="utf-8")

from src import editor_memory, final_score, llm, qa_analyzer, quality_gate, revision_planner, writer

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    mark = "✅" if cond else "❌"
    passed += cond
    failed += not cond
    print(f"  {mark} {name}" + (f"  [{str(detail)[:70]}]" if detail else ""))


print("=" * 60)
print("[۱] قوانین — حذف نسخه‌های متناقض قدیمی")
print("=" * 60)
raw = json.dumps(editor_memory.load_rules(), ensure_ascii=False)
for bad, label in [
    ("measurable outcome", "الزام «نتیجه‌ی قابل‌اندازه‌گیری» در سناریو"),
    ("or be framed explicitly as an assumption", "استثنای «عدد فرضی مجاز»"),
    ("Replace vague qualitative claims with a concrete number", "دستور ساخت عدد برای ادعای مبهم"),
    ("Preserve first-person experience signals", "الزام سیگنال اول‌شخص"),
    ("State the author's role", "الزام معرفی نویسنده"),
    ("Keep concrete case studies with measurable outcomes and specific metrics.", "الزام Case Study بدون قید verified"),
]:
    check(f"حذف شد: {label}", bad not in raw)
for good, label in [
    ("ONLY from citable_facts", "عدد فقط از citable_facts"),
    ("business_context", "تجربه فقط با ثبت در business_context/verified_facts"),
    ("do NOT reward first-person anecdotes", "داور: اول‌شخص امتیاز نمی‌سازد"),
    ("NEVER invent a number, case study", "ممنوعیت ساخت عدد/کیس برای ملموس‌سازی"),
]:
    check(f"اضافه شد: {label}", good in raw)

print("\n" + "=" * 60)
print("[۲] پرامپت‌های Renderشده (استاب llm)")
print("=" * 60)
CAP = {}
_orig = llm.ask


def fake_ask(step, user_content, **kw):
    CAP[step] = user_content + "\n#SYSTEM#\n" + str(kw.get("system") or "")
    return {"title_seo": "تست", "meta_description": "م" * 155, "h1": "تست",
            "slug": "t", "body_html": "<p>م.</p>", "tags": [], "image_keywords": [],
            "seo_grade": 80, "patches": [], "preserve_sections": [], "summary": ""}


llm.ask = fake_ask
for m in (writer, revision_planner, quality_gate, qa_analyzer):
    m.llm.ask = fake_ask

brief = {"topic": "تست", "source_urls": ["https://example.com"], "summary": "س",
         "content_gaps": [], "citable_facts": ["فکت ۱"]}
writer.write_article(brief, keywords={"primary": "kw", "primary_fa": "کیورد", "secondary": []})
gen = CAP["article_writing"]
check("WRITE: بلوک <fact_policy>", "<fact_policy>" in gen and "نبود داده را با آمار، داستان یا تجربه ساختگی جبران نکن" in gen)
check("WRITE: معیارهای اجرایی به‌جای «Human-like» مبهم",
      "Human-like" not in gen and "دستیار همیشه بیدار" in gen)
check("WRITE: قانون H2 (۴۰ تا ۷۰ درصد)", "۴۰ تا ۷۰ درصد" in gen)
check("WRITE: الزام قدیمی «H2های سوال‌محور» حذف شد", "ساختار: H2های سوال‌محور" not in gen)
check("WRITE: منع بازگویی پاسخ مستقیم", "حق ندارد" in gen and "بازگویی" in gen)
check("WRITE: سیاست CTA (بدون approved_cta → خنثی)", "هیچ CTA تجاری تایید نشده" in gen)

brief_cta = dict(brief)
brief_cta["approved_cta"] = {"enabled": True, "text": "رزرو مشاوره", "target_url": "https://x.ir"}
writer.write_article(brief_cta, keywords={"primary": "kw", "primary_fa": "ک", "secondary": []})
check("WRITE: با approved_cta → CTA تاییدشده در پرامپت", "رزرو مشاوره" in CAP["article_writing"])

plan = {"patches": [{"section": "intro", "instruction": "x"}], "preserve_sections": []}
writer.rewrite_article({"title_seo": "t", "body_html": "<p>b</p>",
                        "citable_facts": ["فکت ۱"], "source_urls": ["https://example.com"]},
                       plan, revision_no=1)
rw = CAP["article_rewrite_r1"]
check("REWRITE: قانون ۷ (پچ متخلف → rewrite_warnings)", "rewrite_warnings" in rw)
check("REWRITE: verified_facts با نگاشت ادعا-منبع", "allowed_scope" in rw)
check("REWRITE: منع کلیشه‌به‌کلیشه", "مترادف کلیشه‌ای ممنوع" in rw)
check("REWRITE: اولویت fact_policy بر پچ", "اولویت بالاتر" in rw)

revision_planner.build_plan({"title_seo": "t", "body_html": "<p>b</p>"},
                            [{"category": "low_eeat", "severity": "high", "problem": "p"}],
                            score=70, revision_no=1)
pl = CAP["revision_plan_r1"]
check("PLANNER: منع دستور ساخت تجربه/Case Study", "صادر نکن" in pl and "Case Study" in pl)
check("PLANNER: عدد بی‌منبع → دستور حذف", "دستور «حذف عدد»" in pl)
check("PLANNER: unresolved_source_gap", "unresolved_source_gap" in pl)
check("PLANNER: فیلدهای must_preserve/must_not_add", "must_not_add" in pl)

quality_gate.review({"title_seo": "t", "meta_description": "م", "body_html": "<p>b</p>",
                     "citable_facts": ["فکت ۱"]})
qg = CAP["quality_gate"]
check("GATE: گیت‌های سخت در پرامپت", "گیت‌های سخت" in qg and "CTA تجاری تاییدنشده" in qg)
check("GATE: verified_facts و approved_cta در ورودی داور",
      "<verified_facts>" in qg and "<approved_cta>" in qg)
check("GATE: منع کلیشه‌به‌کلیشه + must_not_add", "must_not_add" in qg)
check("GATE: لحن بدون الزام اول‌شخص", "نبود تجربه‌ی شخصی یا اول‌شخص" in qg)
check("GATE: قرارداد h1/تصویر/نشانگر", "placeholder خطا محسوب نمی‌شوند" in qg)

qa_analyzer.analyze_article({"title_seo": "t", "meta_description": "م" * 155,
                             "body_html": "<p>متن کامل است.</p>"})
qa = CAP["qa_analyze"]
check("ANALYZER: چک‌لیست دقت فنی عمومی", "API، Workflow و Integration" in qa)
check("ANALYZER: قرارداد h1/تصویر", "نبود تگ <h1> داخل body_html خطا نیست" in qa)

llm.ask = _orig
for m in (writer, revision_planner, quality_gate, qa_analyzer):
    m.llm.ask = _orig

print("\n" + "=" * 60)
print("[۳] Validator قطعی انسانی‌سازی")
print("=" * 60)
OLD = {"title_seo": "عنوان", "meta_description": "م" * 155, "h1": "ع",
       "body_html": ("<p>متن با ۲۴ ساعت پشتیبانی.</p><h2>بخش یک</h2>"
                     "<p>الف [[anchor: لینک | صفحه]].</p>"),
       "citable_facts": ["پشتیبانی ۲۴ ساعته ممکن است."], "source_urls": ["https://a.ir"]}


def variant(**kw):
    d = dict(OLD)
    d.update(kw)
    return d


check("ویرایش سبک سالم → قبول",
      writer.validate_humanize(OLD, variant(body_html=OLD["body_html"].replace("الف", "متن روان‌تر"))) == [])
check("عدد جدید → رد",
      any("عدد جدید" in v for v in writer.validate_humanize(
          OLD, variant(body_html=OLD["body_html"] + "<p>۶۰٪ کاهش زمان.</p>"))))
check("موجودیت/برند جدید → رد",
      any("موجودیت" in v for v in writer.validate_humanize(
          OLD, variant(body_html=OLD["body_html"] + "<p>ابزار Zapier عالی است.</p>"))))
check("URL جدید → رد",
      any("URL" in v for v in writer.validate_humanize(
          OLD, variant(body_html=OLD["body_html"] + "<p>https://new.com</p>"))))
check("ادعای تجربه → رد",
      any("تجربه" in v for v in writer.validate_humanize(
          OLD, variant(body_html=OLD["body_html"] + "<p>در پروژه‌های ما دیدیم.</p>"))))
check("حذف H2 → رد",
      any("H2" in v for v in writer.validate_humanize(
          OLD, variant(body_html="<p>متن با ۲۴ ساعت. [[anchor: لینک | صفحه]]</p>"))))
check("حذف نشانگر لینک → رد",
      any("نشانگر" in v for v in writer.validate_humanize(
          OLD, variant(body_html="<p>متن با ۲۴ ساعت.</p><h2>بخش یک</h2><p>الف.</p>"))))
check("عدد موجود در citable_facts → مجاز",
      writer.validate_humanize(
          OLD, variant(body_html=OLD["body_html"].replace("الف", "پشتیبانی ۲۴ ساعته"))) == [])

print("\n" + "=" * 60)
print("[۴] would_reject یکپارچه + گیت ادعای کمی + CTA")
print("=" * 60)
CFG = {"approval_threshold": 90, "weights": {"qa": .5, "gate": .35, "semrush": .15},
       "semrush_component": {"GOOD": 100, "WEAK": 50}}
ok_cc = {"no_forbidden_phrases": True, "no_unapproved_cta": True, "meta_length_150_160": True,
         "internal_links_min2": True, "external_link_min1": True,
         "complete_last_sentence": True, "_details": {}}
base = {"overall_score": 95, "qa_passed": True, "code_checks": dict(ok_cc),
        "quality_gate": {"passed": True, "weighted_score": 8.5, "scores": {"human_tone": 8}},
        "semrush": {"verdict": "GOOD"}}
r = final_score.compute(base, CFG)
check("همه‌چیز پاس → would_reject=False",
      r["score_breakdown"]["would_reject"] is False and r["final_verdict"] == "approved")
r = final_score.compute({**base, "qa_passed": False}, CFG)
check("qa_passed=False → would_reject=True (رفع تناقض)",
      r["score_breakdown"]["would_reject"] is True)
r = final_score.compute({**base, "quality_gate": {"passed": False, "weighted_score": 6.0,
                                                  "scores": {"human_tone": 5}}}, CFG)
check("ردّ گیت → would_reject=True", r["score_breakdown"]["would_reject"] is True)
unsup_gate = {"passed": False, "weighted_score": 8.5, "scores": {"human_tone": 8},
              "quantitative_claims": [{"claim": "کاهش ۶۰٪", "source_id": None,
                                       "status": "unsupported", "required_action": "remove"}]}
r = final_score.compute({**base, "quality_gate": unsup_gate}, CFG)
check("ادعای کمی unsupported → would_reject=True + شمارش",
      r["score_breakdown"]["would_reject"] is True
      and r["score_breakdown"]["unsupported_claims"] == 1)
check("فاز ۱: verdict همچنان rejected نمی‌شود", r["final_verdict"] == "needs_review")

# گیت پایتونی: unsupported → passed=False (استاب)
quality_gate.llm.ask = lambda *a, **k: {
    "scores": {"human_tone": 9, "seo": 9, "eeat": 9, "keyword": 9, "structure": 9,
               "conversion": 9, "trust": 9},
    "quantitative_claims": [{"claim": "افزایش ۲۰٪ رزرو", "source_id": None,
                             "status": "unsupported", "required_action": "remove"}],
    "issues": [], "cliches": [], "unsourced_claims": []}
g = quality_gate.review({"title_seo": "t", "meta_description": "م", "body_html": "<p>b</p>"})
quality_gate.llm.ask = _orig
check("گیت: نمره‌ی عالی + یک unsupported → passed=False", g["passed"] is False)
check("گیت: هم‌خوانی unsourced_claims با quantitative_claims",
      "افزایش ۲۰٪ رزرو" in g["unsourced_claims"])

cc = qa_analyzer.code_side_checks({"body_markdown": "<p>همین امروز جلسه رایگان رزرو کنید.</p>",
                                   "meta_description": "م" * 155})
check("CTA تاییدنشده → چک کد رد", cc["no_unapproved_cta"] is False)
cc = qa_analyzer.code_side_checks({"body_markdown": "<p>جلسه رایگان رزرو کنید.</p>",
                                   "meta_description": "م" * 155,
                                   "approved_cta": {"enabled": True, "text": "جلسه رایگان"}})
check("CTA تاییدشده → چک کد پاس", cc["no_unapproved_cta"] is True)

print("\n" + "=" * 60)
print("[۵] منطق نسخه‌ی برنده")
print("=" * 60)
# شبیه‌سازی _metrics/_is_better (همان منطق evaluate_and_sync، این‌جا از final layer)
def an(score, gate_w, tone, gate_pass, high=0, unsup=0, forb=0):
    a = {"overall_score": score, "qa_passed": True, "passed": score >= 90,
         "code_checks": dict(ok_cc),
         "quality_gate": {"passed": gate_pass, "weighted_score": gate_w,
                          "scores": {"human_tone": tone},
                          "quantitative_claims": [{"status": "unsupported"}] * unsup},
         "semrush": {"verdict": "GOOD"},
         "issues": [{"severity": "high"}] * high}
    if forb:
        a["code_checks"]["_details"] = {"found_forbidden": ["x"] * forb}
    a["final"] = final_score.compute(a, CFG)
    return a


from src import architecture_v2_1_utils as av21


def to_result(a):
    """همان نگاشت production (_candidate_result در evaluate_and_sync) — v2.1.1."""
    bd = a["final"]["score_breakdown"]
    g = bd["hard_gates"]
    return {
        "hard_error_count": sum(1 for k in ("qa_passed", "quality_gate_passed",
                                            "code_checks_ok", "semrush_ok")
                                if g[k] is False),
        "unsupported_claim_count": int(bd.get("unsupported_claims", 0) or 0),
        "high_confidence_soft_unsupported_count": int(
            bd.get("high_confidence_soft_unsupported_count", 0) or 0),
        "medium_confidence_soft_unsupported_count": int(
            bd.get("medium_confidence_soft_unsupported_count", 0) or 0),
        "rewrite_warning_count": 0,
        "final_score": a["final"]["final_score"],
        "hard_policy_reject": bool(bd.get("hard_policy_reject", False)),
        "validator_passed": True,
    }


def is_better(n, o):
    ok, _ = av21.should_save_candidate(candidate_result=to_result(n),
                                       previous_result=to_result(o))
    return ok


old_v = an(80, 7.0, 7, True, high=1)
check("بهتر در همه‌چیز → جایگزین", is_better(an(85, 7.5, 8, True, high=0), old_v))
check("نمره‌ی بالاتر ولی hard error بیشتر → جایگزین نشود",
      not is_better(an(90, 8.0, 8, False, high=3), old_v))
check("نمره‌ی بالاتر ولی ادعای بی‌منبع (hard policy) → جایگزین نشود",
      not is_better(an(90, 8.0, 8, True, unsup=2), old_v))
check("عبارت ممنوعه در نسخه‌ی جدید (hard policy) → جایگزین نشود",
      not is_better(an(90, 8.0, 8, True, forb=1), old_v))
check("Rank برابر → جایگزین نشود", not is_better(an(80, 7.0, 7, True, high=1), old_v))

print("\n" + "=" * 60)
print(f"نتیجه: {passed} پاس، {failed} شکست | تماس LLM واقعی: 0")
print("=" * 60)
sys.exit(1 if failed else 0)
