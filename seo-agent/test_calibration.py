"""تست Calibration Patch (کاهش False Positive soft claims) — صفر تماس LLM.

طبق بند ۸ اسپک: باید-high / نباید-high / LLM span / Cleanup targeting.
اجرا:  python test_calibration.py   (از پوشه‌ی seo-agent)
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from src.architecture_v2_1_utils import (
    collect_cleanup_targets, detect_soft_quantitative_claims, merge_soft_claims,
)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    mark = "✅" if cond else "❌"
    passed += cond
    failed += not cond
    print(f"  {mark} {name}" + (f"  [{str(detail)[:66]}]" if detail else ""))


def conf_of(text):
    """بالاترین confidence آشکارشده برای یک جمله (None اگر هیچ)."""
    cs = detect_soft_quantitative_claims(text, [])
    if not cs:
        return None
    order = {"high": 3, "medium": 2, "low": 1}
    return max(cs, key=lambda c: order[c.confidence]).confidence


print("=" * 62)
print("[۱] باید HIGH شوند (تعمیم + نتیجه‌ی سنجش‌پذیر)")
print("=" * 62)
MUST_HIGH = [
    "راه‌اندازی این سیستم معمولاً چند هفته طول می‌کشد.",
    "هزینه‌ها به‌طور چشمگیری کاهش می‌یابد.",
    "اغلب مشتریان دوباره خرید می‌کنند.",
    "بخش بزرگی از تماس‌ها خودکار می‌شود.",
    "این سامانه دقت بسیار بالایی دارد.",
]
for t in MUST_HIGH:
    check(f"HIGH: «{t[:40]}»", conf_of(t) == "high", conf_of(t))

print("\n" + "=" * 62)
print("[۲] نباید HIGH شوند (تعمیم بدون نتیجه / شرطی)")
print("=" * 62)
MUST_NOT_HIGH = [
    "بسیاری از مدیران با این مسئله روبه‌رو هستند.",
    "معمولاً ابتدا نیازهای پروژه بررسی می‌شود.",
    "اغلب ابزارها امکان اتصال دارند.",
    "این قابلیت می‌تواند برای بعضی کسب‌وکارها مفید باشد.",
    "زمان اجرا به دامنه پروژه بستگی دارد.",
    "دقت باید روی داده واقعی آزمایش شود.",
    "بسیاری از رستوران‌ها به پاسخ‌گویی سریع اهمیت می‌دهند.",
]
for t in MUST_NOT_HIGH:
    c = conf_of(t)
    check(f"NOT-HIGH: «{t[:40]}»", c != "high", c)

print("\n" + "=" * 62)
print("[۳] تک‌واژه‌ی trigger به‌تنهایی high نیست")
print("=" * 62)
for w, sent in [("بسیاری", "بسیاری از شرکت‌ها این موضوع را مطرح می‌کنند."),
                ("اغلب", "اغلب سازمان‌ها به این نکته توجه دارند."),
                ("معمولاً", "معمولاً این موضوع در جلسات بررسی می‌شود.")]:
    c = conf_of(sent)
    check(f"«{w}» تنها → high نیست", c != "high", c)

print("\n" + "=" * 62)
print("[۴] LLM Span / Merge")
print("=" * 62)
ART = "این سامانه دقت بسیار بالایی دارد و بسیاری از کاربران از آن استفاده می‌کنند."
det = [c.as_dict() for c in detect_soft_quantitative_claims(ART, [])]
# LLM span جعلی → حذف، نه schema-fatal
m, invalid = merge_soft_claims(
    deterministic_claims=det,
    llm_claims=[{"claim": "چیزی که در مقاله نیست", "exact_span": "غیرواقعی",
                 "category": "performance_generalization", "confidence": "high",
                 "required_action": "neutralize"}],
    article_text=ART)
check("Span جعلی → Claim حذف شد", all(x.get("exact_span") != "غیرواقعی" for x in m))
check("Span جعلی → در invalid با code درست",
      len(invalid) == 1 and invalid[0]["code"] == "gate_claim_invalid_span")
check("Span جعلی → hard reject نمی‌سازد (فقط حذف)",
      not any(x.get("confidence") == "high" and x.get("source") == "llm" for x in m))

# LLM-only claim با span واقعی → حداکثر medium
m2, _ = merge_soft_claims(
    deterministic_claims=[],
    llm_claims=[{"claim": "بسیاری از کاربران از آن استفاده می‌کنند.",
                 "exact_span": "بسیاری از", "category": "frequency_generalization",
                 "confidence": "high", "required_action": "neutralize"}],
    article_text=ART)
check("LLM-only high → تنزل به medium", len(m2) == 1 and m2[0]["confidence"] == "medium"
      and m2[0]["source"] == "llm", m2[0]["confidence"] if m2 else "-")

# deterministic high + تایید LLM → high می‌ماند
det_high = [c.as_dict() for c in detect_soft_quantitative_claims(
    "این سامانه دقت بسیار بالایی دارد.", [])]
m3, _ = merge_soft_claims(
    deterministic_claims=det_high,
    llm_claims=[{"claim": det_high[0]["claim"], "exact_span": det_high[0]["exact_span"],
                 "category": det_high[0]["category"], "confidence": "high",
                 "required_action": "neutralize"}],
    article_text="این سامانه دقت بسیار بالایی دارد.")
check("deterministic high + تایید LLM → high می‌ماند",
      any(x["confidence"] == "high" for x in m3))

# LLM تنزل deterministic high → medium
m4, _ = merge_soft_claims(
    deterministic_claims=det_high,
    llm_claims=[{"claim": det_high[0]["claim"], "exact_span": det_high[0]["exact_span"],
                 "category": det_high[0]["category"], "confidence": "medium",
                 "required_action": "neutralize"}],
    article_text="این سامانه دقت بسیار بالایی دارد.")
check("LLM می‌تواند deterministic high را به medium تنزل دهد",
      all(x["confidence"] != "high" for x in m4))

print("\n" + "=" * 62)
print("[۵] Cleanup targeting — فقط high قطعی")
print("=" * 62)
soft_mixed = [
    {"exact_span": "دقت بسیار بالا", "category": "performance_generalization",
     "confidence": "high", "supported": False, "source": "deterministic",
     "exact_span_valid": True, "required_action": "neutralize"},
    {"exact_span": "بسیاری از", "category": "frequency_generalization",
     "confidence": "medium", "supported": False, "source": "deterministic",
     "exact_span_valid": True, "required_action": "neutralize"},
    {"exact_span": "چیزی", "category": "x", "confidence": "high", "supported": False,
     "source": "llm", "exact_span_valid": True, "required_action": "neutralize"},
]
tg = collect_cleanup_targets({"soft_quantitative_claims": soft_mixed})
check("فقط high قطعیِ deterministic هدف Cleanup است (۱ مورد)",
      len(tg) == 1 and tg[0]["exact_span"] == "دقت بسیار بالا", len(tg))
check("medium هدف Cleanup نیست", all(t["confidence"] == "high" for t in tg))
check("high با source=llm هدف Cleanup نیست",
      all(t.get("source") != "llm" for t in tg))
tg0 = collect_cleanup_targets({"soft_quantitative_claims": [soft_mixed[1]]})  # فقط medium
check("نبود high → صفر هدف Cleanup", tg0 == [])

print("\n" + "=" * 62)
print(f"نتیجه: {passed} پاس، {failed} شکست | تماس LLM واقعی: 0")
print("=" * 62)
sys.exit(1 if failed else 0)
