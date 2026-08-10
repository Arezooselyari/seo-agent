"""تست HUMANIZE_PROMPT نسخه‌ی ویراستار سبک — صفر تماس LLM.

اجرا:  python test_humanize_v2.py   (از پوشه‌ی seo-agent)
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from src import llm, writer

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    mark = "✅" if cond else "❌"
    passed += cond
    failed += not cond
    print(f"  {mark} {name}" + (f"  [{detail}]" if detail else ""))


CAPTURED = {}
_orig = llm.ask


def fake_ask(step, user_content, **kw):
    CAPTURED[step] = {"content": user_content, "kw": kw}
    return {"title_seo": "تست", "meta_description": "م" * 155, "h1": "تست",
            "slug": "test", "body_html": "<p>متن.</p>", "tags": ["x"],
            "image_keywords": ["y"], "seo_grade": 85}


llm.ask = fake_ask
writer.llm.ask = fake_ask

payload = {
    "title_seo": "عنوان تست",
    "meta_description": "م" * 155,
    "h1": "عنوان اصلی تست",
    "slug": "test-article",
    "body_html": ("<p>مقدمه. فرض کنید یک رستوران در تهران زمان پاسخ را ۶۰٪ کم کند.</p>"
                  "<h2>بخش اول چیست؟</h2><p>متن [[anchor: مشاوره | خدمات]] ادامه.</p>"
                  "<h2>بخش دوم چگونه؟</h2><p>پایان [[external: IBM | https://ibm.com]].</p>"),
    "tags": ["تست"],
    "target_keywords": {"primary": "test kw", "primary_fa": "کیورد تست"},
    "source_urls": ["https://example.com/a"],
    "citable_facts": ["فکت مستند شماره ۱ از بریف."],
    "topic": "موضوع تست",
}
gate_report = {"scores": {"human_tone": 4}, "cliches": [{"quote": "ق", "better": "ب"}],
               "issues": [{"category": "robotic_language", "problem": "p"}],
               "cta_suggestion": None}

out = writer.humanize_article(payload, gate_report, revision_no=1)
c = CAPTURED["article_humanize_r1"]["content"]
kwargs = CAPTURED["article_humanize_r1"]["kw"]

# [۱] پرامپت جدید و placeholderها
check("نقش جدید: ویراستار سبک و نثر", "ویراستار سبک و نثر فارسی" in c)
check("نقش قدیمی (مشاور/نویسنده باتجربه) حذف شد",
      "نویسنده‌ی باتجربه" not in c and "مشاور واقعی" not in c)
check("هیچ placeholder پرنشده‌ای نماند",
      "{verified_facts}" not in c and "{locked_elements}" not in c
      and "{article}" not in c and "{review}" not in c and "{lessons}" not in c)

# [۲] verified_facts
check("فکت بریف در verified_facts", "فکت مستند شماره ۱" in c)
check("source_urls در verified_facts", "example.com/a" in c)

# [۳] locked_elements
check("H2ها استخراج و قفل شدند", "بخش اول چیست؟" in c and "بخش دوم چگونه؟" in c)
check("نشانگرهای لینک قفل شدند", "[[anchor: مشاوره | خدمات]]" in c and "[[external: IBM" in c)
check("سناریوی موجود (فرض کنید) ثبت شد", "approved_scenario" in c and "فرض کنید یک رستوران" in c)
check("کیورد اصلی قفل شد", "کیورد تست" in c)

# [۴] قوانین کلیدی پرامپت کاربر
for probe in ("حق تغییر، توسعه یا تولید محتوای جدید نداری",
              "هیچ تجربه شخصی یا سازمانی نساز",
              "عدد جدید: صفر"):
    check(f"قانون: «{probe[:30]}...»", probe in c)

# [۵] عبارات ممنوعه ضمیمه، قوانین لحن تزریق نشده
check("عبارات ممنوعه ضمیمه شد", "<forbidden_phrases>" in c)
check("بلوک قوانین تحریریه تزریق نشده (فلسفه‌ی فقط-ویرایش)",
      "<editorial_rules>" not in c)

# [۶] پارامترها و حفظ فیلدها
check("temperature=0.3", kwargs.get("temperature") == 0.3, kwargs.get("temperature"))
check("citable_facts بین دورها حفظ می‌شود", out.get("citable_facts") == payload["citable_facts"])

# [۷] payload بدون سناریو/فکت → متن جایگزین امن
CAPTURED.clear()
bare = {k: v for k, v in payload.items() if k not in ("citable_facts", "source_urls")}
bare["body_html"] = "<p>متن ساده بدون سناریو.</p>"
writer.humanize_article(bare, gate_report, revision_no=2)
c2 = CAPTURED["article_humanize_r2"]["content"]
check("بدون فکت: پیام «هیچ ادعای جدیدی مجاز نیست»", "هیچ فکت تاییدشده‌ای ثبت نشده" in c2)
check("بدون سناریو: «سناریوی جدید هم مجاز نیست»", "سناریوی جدید هم مجاز نیست" in c2)

llm.ask = _orig
writer.llm.ask = _orig

print()
print("=" * 50)
print(f"نتیجه: {passed} پاس، {failed} شکست | تماس LLM واقعی: 0")
print("=" * 50)
sys.exit(1 if failed else 0)
