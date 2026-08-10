"""تست خط‌لوله‌ی فکتِ معتبر (fact_research) — گاردِ ضدجعل. صفر تماس LLM واقعی.

llm.ask را کنترل‌شده جایگزین می‌کنیم تا فقط منطقِ «فکت باید عیناً در منبع باشد» تست شود.
اجرا:  python test_fact_research.py   (از پوشه‌ی seo-agent)
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from src import fact_research, llm

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    cond = bool(cond)
    print(("  ✅ " if cond else "  ❌ ") + name + (f"  [{str(detail)[:66]}]" if detail else ""))
    passed += cond
    failed += not cond


_FILLER = ("هوش مصنوعی در سال‌های اخیر به یکی از فناوری‌های مهم کسب‌وکار تبدیل شده و "
           "شرکت‌های بسیاری از آن برای بهبود فرایندها بهره می‌گیرند. ") * 2
SOURCE = {
    "url": "https://example.com/report",
    "title": "گزارش",
    "text": _FILLER + "طبق گزارش رسمی، ۸۳ درصد از مدیران قصد سرمایه‌گذاری دارند. "
            "این عدد در سال ۲۰۲۳ ثبت شد. " + _FILLER,
}

_orig_ask = llm.ask


def fake_ask(*args, **kw):
    return {"facts": [
        # واقعی — جمله عیناً در منبع هست → باید بماند
        {"stat": "۸۳٪ مدیران قصد سرمایه‌گذاری دارند.",
         "verbatim_snippet": "۸۳ درصد از مدیران قصد سرمایه‌گذاری دارند", "number": "83%"},
        # جعلی — این جمله در منبع نیست → باید حذف شود (ضدجعل)
        {"stat": "فروش ۲۴۰٪ رشد کرد.",
         "verbatim_snippet": "فروش شرکت‌ها ۲۴۰ درصد افزایش یافت", "number": "240%"},
        # بدون عدد → حذف
        {"stat": "بهبودِ چشمگیر در عملکرد.",
         "verbatim_snippet": "عملکرد بهبود یافت", "number": ""},
        # عددِ واقعی ولی جمله‌ی دستکاری‌شده که در منبع نیست → حذف
        {"stat": "۹۹٪ مدیران قصد سرمایه‌گذاری دارند.",
         "verbatim_snippet": "۹۹ درصد از مدیران قصد سرمایه‌گذاری دارند", "number": "99%"},
    ]}


print("=" * 62)
print("گاردِ ضدجعلِ fact_research (بدون LLM واقعی)")
print("=" * 62)
llm.ask = fake_ask
try:
    res = fact_research.research_facts("t", [SOURCE])
finally:
    llm.ask = _orig_ask

claims = [f["claim"] for f in res["verified_facts"]]
check("فکتِ واقعی (۸۳٪) نگه داشته شد", any("۸۳" in c for c in claims), claims)
check("فکتِ جعلی (۲۴۰٪ که در متن نیست) حذف شد", not any("۲۴۰" in c for c in claims))
check("ادعای بدونِ عدد حذف شد", not any("چشمگیر" in c for c in claims))
check("عددِ دستکاری‌شده (۹۹٪ که در منبع نیست) حذف شد", not any("۹۹" in c for c in claims))
check("فقط ۱ فکتِ معتبر ماند", res["count"] == 1, res["count"])
check("منبعِ فکت درست نگاشت شد",
      res["verified_facts"] and res["verified_facts"][0]["source_url"] == "https://example.com/report")

# منبعِ کوتاه‌تر از ۲۰۰ کاراکتر → استخراج نمی‌شود (ضد نویز)
llm.ask = fake_ask
try:
    short = fact_research.research_facts("t", [{"url": "u", "title": "t", "text": "۸۳ درصد."}])
finally:
    llm.ask = _orig_ask
check("منبعِ خیلی کوتاه نادیده گرفته شد", short["count"] == 0, short["count"])

print("\n" + "=" * 62)
print(f"نتیجه: {passed} پاس، {failed} شکست | تماس LLM واقعی: 0")
print("=" * 62)
sys.exit(1 if failed else 0)
