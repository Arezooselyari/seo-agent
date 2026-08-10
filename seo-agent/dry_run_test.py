"""Dry run — بررسی اتصال pipeline و صحت داده بدون هیچ تماس Gemini.

llm.ask با یک stub جایگزین می‌شود که تماس‌ها را ثبت و داده‌ی ساختگی برمی‌گرداند.
هیچ API call واقعی زده نمی‌شود.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from src import db, editor_memory, revision_planner, writer, quality_gate
from src import llm as llm_module

# ── stub برای llm.ask: هیچ تماس واقعی، فقط ثبت + داده‌ی ساختگی ──
CALLS = []

def fake_ask(step, user_content, **kwargs):
    CALLS.append({"step": step, "user_content": user_content, "kwargs": kwargs})
    # پاسخ ساختگی بسته به نوع step
    if "revision_plan" in step:
        return {
            "patches": [{
                "section": "intro", "scope": "section", "severity": "high",
                "current_text_hint": "چت‌بات...",
                "instruction": "مقدمه را با داده‌ی مشخص شروع کن",
                "rule": "Open with a concrete problem, not a ceremonial greeting",
            }],
            "preserve_sections": ["faq", "conclusion"],
            "summary": "اصلاح مقدمه",
        }
    if "humanize" in step or "rewrite" in step or "writing" in step:
        return {"title_seo": "تست", "meta_description": "x"*155, "h1": "تست",
                "slug": "test", "body_html": "<p>متن ساختگی</p>", "tags": ["x"],
                "image_keywords": ["y"], "seo_grade": 85}
    if "quality_gate" in step:
        return {
            "scores": {"human_tone": 7, "seo": 8, "eeat": 7, "keyword": 8,
                       "structure": 9, "conversion": 8, "trust": 7},
            "issues": [], "cliches": [], "recommendations": {},
            "rules_compliance": {"followed": ["..."], "violated": []},
        }
    return {}

llm_module.ask = fake_ask
# ماژول‌هایی که llm را import کرده‌اند هم به همین اشاره کنند
revision_planner.llm.ask = fake_ask
writer.llm.ask = fake_ask
quality_gate.llm.ask = fake_ask

print("=" * 60)
print("DRY RUN — بدون تماس Gemini")
print("=" * 60)

# ── چک ۱: load مقاله #6 ──
print("\n[۱] load مقاله #6:")
conn = db.connect()
article = db.get_article(conn, 6)
conn.close()
if article:
    p = article["payload"]
    body = p.get("body_html", "")
    print(f"  ✓ load شد | status={article['status']} | کلمات={len(body.split())}")
    print(f"    عنوان: {p.get('title_seo','')[:50]}")
    print(f"    anchor={body.count('[[anchor:')} external={body.count('[[external:')} متا={len(p.get('meta_description',''))}")
else:
    print("  ✗ مقاله #6 یافت نشد!")
    sys.exit(1)

# ── چک ۲: editorial_rules توسط همه consumer ها ──
print("\n[۲] خواندن editorial_rules.json توسط consumer ها:")
rules = editor_memory.load_rules()
print(f"  ✓ editor_memory.load_rules(): {len(rules)} دسته، {sum(len(v) for v in rules.values())} قانون")
# writer: سه مسیر با دسته‌های مختلف
w_gen = editor_memory.rules_prompt_block(None, max_rules_per_category=3)
w_rewrite = editor_memory.rules_prompt_block(["anti_ai_writing_rules","readability_rules","seo_rules"])
w_human = editor_memory.rules_prompt_block(["human_tone_rules","anti_ai_writing_rules","eeat_rules"])
print(f"  ✓ writer.generate  → {len(w_gen)} کاراکتر (همه، ۳/دسته)")
print(f"  ✓ writer.rewrite   → {len(w_rewrite)} کاراکتر (anti_ai+readability+seo)")
print(f"  ✓ writer.humanize  → {len(w_human)} کاراکتر (human_tone+anti_ai+eeat)")
rp = editor_memory.rules_prompt_block()
print(f"  ✓ revision_planner → {len(rp)} کاراکتر (همه)")
qg = editor_memory.rules_prompt_block()
print(f"  ✓ quality_gate     → {len(qg)} کاراکتر (همه)")

# ── چک ۳: QA output → revision_planner ──
print("\n[۳] رسیدن QA output به revision_planner:")
fake_qa_issues = [
    {"category": "ai_cliche", "severity": "high", "location": "مقدمه",
     "exact_quote": "در دنیای امروز", "problem": "کلیشه",
     "rewrite_instruction": "با داده شروع کن"},
    {"category": "weak_cta", "severity": "medium", "location": "جمع‌بندی",
     "exact_quote": "با ما تماس بگیرید", "problem": "CTA ضعیف",
     "rewrite_instruction": "CTA مشخص بده"},
]
CALLS.clear()
plan = revision_planner.build_plan(p, fake_qa_issues, score=81, revision_no=1)
last = CALLS[-1]
sent_issues = "ai_cliche" in last["user_content"] and "weak_cta" in last["user_content"]
print(f"  ✓ build_plan اجرا شد | issues به پرامپت رسید: {sent_issues}")
print(f"  ✓ خروجی: {len(plan.get('patches',[]))} پچ، {len(plan.get('preserve_sections',[]))} بخش محفوظ")
print(f"  ✓ editorial_rules در پرامپت planner: {'<editorial_rules>' in last['user_content']}")

# ── چک ۴: patch instruction شامل rule reference ──
print("\n[۴] rule reference در patch:")
patch = plan["patches"][0]
has_rule = "rule" in patch
print(f"  ✓ فیلد 'rule' در پچ: {has_rule}")
if has_rule:
    print(f"    مقدار: «{patch['rule'][:60]}»")
# تأیید در template
tmpl_has_rule = '"rule":' in revision_planner._PLANNER_PROMPT
print(f"  ✓ فیلد rule در schema template: {tmpl_has_rule}")

# ── چک ۵: quality_gate → rules_compliance ──
print("\n[۵] تولید rules_compliance توسط quality_gate:")
CALLS.clear()
gate = quality_gate.review(p)
gq = CALLS[-1]
print(f"  ✓ review اجرا شد | editorial_rules در پرامپت: {'<editorial_rules>' in gq['user_content']}")
print(f"  ✓ rules_compliance در schema: {'rules_compliance' in quality_gate._OUTPUT_ADDENDUM}")
print(f"  ✓ rules_compliance در خروجی: {'rules_compliance' in gate}")
print(f"    محتوا: followed={len(gate.get('rules_compliance',{}).get('followed',[]))}, violated={len(gate.get('rules_compliance',{}).get('violated',[]))}")

# ── چک ۶: revision loop termination ──
print("\n[۶] منطق توقف revision loop:")
from src.config import load_settings
cfg = load_settings()
qa_cfg = cfg.get("qa", {})
print(f"  ✓ rewrite_enabled={qa_cfg.get('rewrite_enabled')} | max_revision={qa_cfg.get('max_revision')} | minimum_score={qa_cfg.get('minimum_score')}")
gate_cfg = cfg.get("quality_gate", {})
print(f"  ✓ min_human_tone={gate_cfg.get('min_human_tone')} | min_weighted={gate_cfg.get('min_weighted_score')}")
# شبیه‌سازی شرط توقف
def loop_would_continue(passed, gate_ok, has_issues, revision, maxr):
    return (not passed or not gate_ok) and has_issues and revision < maxr
print("  شبیه‌سازی شرط ادامه:")
print(f"    passed=True, gate_ok=True  → ادامه؟ {loop_would_continue(True, True, True, 0, 3)} (باید False)")
print(f"    passed=False, gate_ok=True → ادامه؟ {loop_would_continue(False, True, True, 0, 3)} (باید True)")
print(f"    passed=True, gate_ok=False → ادامه؟ {loop_would_continue(True, False, True, 0, 3)} (باید True)")
print(f"    revision=3, max=3          → ادامه؟ {loop_would_continue(False, False, True, 3, 3)} (باید False)")
print(f"    بدون issue                 → ادامه؟ {loop_would_continue(False, False, False, 0, 3)} (باید False)")

print("\n" + "=" * 60)
print(f"مجموع تماس‌های Gemini واقعی زده‌شده: 0 (همه stub بودند)")
print("=" * 60)
