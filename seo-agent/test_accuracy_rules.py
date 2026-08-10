"""تست اتصال accuracy_rules — صفر تماس LLM.

بررسی: بارگذاری دسته‌ی جدید، رسیدن قوانین به generate/rewrite/humanize/گیت/planner،
و عمل‌کردن عبارات ممنوعه‌ی جدید در چک کد.
اجرا:  python test_accuracy_rules.py   (از پوشه‌ی seo-agent)
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from src import editor_memory, llm, qa_analyzer, writer

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    mark = "✅" if cond else "❌"
    passed += cond
    failed += not cond
    print(f"  {mark} {name}" + (f"  [{detail}]" if detail else ""))


# ── [۱] بارگذاری قوانین ──
rules = editor_memory.load_rules()
check("دسته‌ی accuracy_rules موجود است", "accuracy_rules" in rules)
check("۱۴ قانون دقت فنی (۱۲ + ۲ قانون soft-claim پچ v2.1)",
      len(rules.get("accuracy_rules", [])) == 14,
      len(rules.get("accuracy_rules", [])))
total = sum(len(v) for v in rules.values())
check("مجموع دسته‌ها/قوانین (۹ دسته، ۶۲ قانون)",
      len(rules) == 9 and total == 62, f"{len(rules)} دسته، {total} قانون")

block = editor_memory.rules_prompt_block(["accuracy_rules"])
check("عنوان فارسی دسته در بلوک پرامپت", "دقت فنی و اعتبار ادعاها" in block)
check("قانون کلیدی (تضمین ممنوع) در بلوک", "تضمین می" in block or "never 'guarantee'" in block.lower()
      or "Security wording" in block)

# ── [۲] استاب llm.ask و گرفتن پرامپت‌های واقعی هر سه مسیر ──
CAPTURED = {}
_orig = llm.ask


def fake_ask(step, user_content, **kw):
    CAPTURED[step] = user_content
    return {"title_seo": "تست", "meta_description": "م" * 155, "h1": "تست",
            "slug": "test", "body_html": "<p>متن.</p>", "tags": ["x"],
            "image_keywords": ["y"], "seo_grade": 85}


llm.ask = fake_ask
writer.llm.ask = fake_ask

brief = {"topic": "تست", "source_urls": ["https://example.com"], "summary": "خلاصه",
         "content_gaps": [], "citable_facts": []}
kw = {"primary": "test kw", "primary_fa": "کیورد تست", "secondary": [], "fa_map": {}}

writer.write_article(brief, keywords=kw)
gen = CAPTURED.get("article_writing", "")
check("generate: قوانین دقت در بلوک کامل <voice_spec>",
      "<voice_spec>" in gen and "دقت فنی و اعتبار ادعاها" in gen.split("<voice_spec>")[-1])
check("generate: Voice Spec همچنان در بلوک کامل",
      "مشخصات صدای نویسنده" in gen.split("<voice_spec>")[-1])
summary_part = gen.split("<voice_spec>")[0]
check("generate: بدون تکرار دسته‌ی دقت در بخش خلاصه",
      "دقت فنی و اعتبار ادعاها" not in summary_part)

plan = {"patches": [{"section": "intro", "scope": "section", "instruction": "x"}],
        "preserve_sections": [], "summary": "s"}
writer.rewrite_article({"title_seo": "t", "body_html": "<p>b</p>"}, plan, revision_no=1)
rw = CAPTURED.get("article_rewrite_r1", "")
check("rewrite: قوانین دقت می‌رسد", "دقت فنی و اعتبار ادعاها" in rw)

gate_report = {"scores": {"human_tone": 4}, "cliches": [], "issues": []}
writer.humanize_article({"title_seo": "t", "body_html": "<p>b</p>"}, gate_report, revision_no=1)
hm = CAPTURED.get("article_humanize_r1", "")
# طبق پرامپت مصوب کاربر (ویراستار سبک): humanize دیگر بلوک قوانین تحریریه نمی‌گیرد —
# فقط ویرایش بیان؛ محدودیت‌های محتوایی داخل خود پرامپت است + عبارات ممنوعه
check("humanize: بدون بلوک قوانین (فقط ویراستار سبک)", "<editorial_rules>" not in hm)
check("humanize: قواعد سخت‌گیرانه داخل پرامپت", "حق تغییر، توسعه یا تولید محتوای جدید نداری" in hm)

llm.ask = _orig
writer.llm.ask = _orig

# ── [۳] داور گیت و planner (هر دو همه‌ی دسته‌ها را می‌گیرند) ──
all_block = editor_memory.rules_prompt_block()
check("گیت/planner: دسته‌ی دقت در بلوک همه‌دسته‌ها", "دقت فنی و اعتبار ادعاها" in all_block)

# ── [۴] عبارات ممنوعه‌ی جدید در چک قطعی کد ──
bad = {"body_markdown": "<p>پاسخ قاطعانه بله است و در کسری از زمان انجام می‌شود.</p>",
       "meta_description": "م" * 155}
cc = qa_analyzer.code_side_checks(bad)
found = cc["_details"]["found_forbidden"]
check("چک کد: «پاسخ قاطعانه» و «در کسری از زمان» گیر می‌افتند",
      "پاسخ قاطعانه" in found and "در کسری از زمان" in found, found)
clean = {"body_markdown": "<p>پاسخ به این سوال «خیر» است؛ دقت به کیفیت سند بستگی دارد.</p>",
         "meta_description": "م" * 155}
cc2 = qa_analyzer.code_side_checks(clean)
check("چک کد: متن سالم ممنوعه ندارد", cc2["no_forbidden_phrases"] is True)

print()
print("=" * 50)
print(f"نتیجه: {passed} پاس، {failed} شکست | تماس LLM واقعی: 0")
print("=" * 50)
sys.exit(1 if failed else 0)
