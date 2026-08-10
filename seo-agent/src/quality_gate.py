"""دروازه‌ی کیفیت محتوا (Content Quality Gate) — بین Writer و گیت نهایی.

پرامپت نقش‌محور کاربر (prompts/content-quality-gate.md) را اجرا می‌کند:
لحن انسانی، E-E-A-T، استراتژی کیورد، Conversion، اعتبار داده‌ها.

خروجی JSON ساختاریافته شامل:
- scores: امتیاز ۰-۱۰ هر بُعد (human_tone, seo, eeat, keyword, structure, conversion, trust)
- cliches: عبارات کلیشه‌ای پیداشده (با پیشنهاد جایگزین)
- issues: در همان فرمت qa_analyzer (به حلقه‌ی اصلاح تزریق می‌شود)
- recommendations: سه دسته (high/medium/long_term)
گیت: میانگین وزنی scores باید ≥ آستانه‌ی settings باشد و human_tone حداقلش را رد نکند.
"""
import json
import logging

from . import editor_memory, llm
from .config import PROMPTS_DIR, load_settings

logger = logging.getLogger(__name__)

_PROMPT_FILE = PROMPTS_DIR / "content-quality-gate.md"

# دستور خروجی JSON برای pipeline (به انتهای پرامپت کاربر اضافه می‌شود)
_OUTPUT_ADDENDUM = """

═══════════════════════════════════
فرمت خروجی (فقط JSON معتبر، بدون متن اضافه)
═══════════════════════════════════
تمام تحلیل بخش‌های بالا را در این ساختار بده:
{
  "scores": {
    "human_tone": 0-10,
    "seo": 0-10,
    "eeat": 0-10,
    "keyword": 0-10,
    "structure": 0-10,
    "conversion": 0-10,
    "trust": 0-10
  },
  "eeat_detail": {"experience": 0-10, "expertise": 0-10, "authority": 0-10, "trust": 0-10},
  "cliches": [
    {"quote": "عبارت کلیشه‌ای دقیق از متن",
     "problem": "چرا کلیشه/تبلیغاتی است",
     "action": "دستور اصلاح (حذف، کوتاه‌کردن، یا بیان مستقیم‌تر) — نه جمله‌ی جایگزین کامل",
     "must_not_add": ["مترادف‌های کلیشه‌ای که نباید جایگزین شوند"]}
  ],
  "quantitative_claims": [
    {"claim": "متن دقیق هر ادعای عددی/درصدی/قیمتی/زمانی مقاله",
     "source_id": "شناسه یا نام منبع اگر در citable_facts/verified_facts پشتیبانی می‌شود، وگرنه null",
     "status": "supported | unsupported",
     "required_action": "keep | remove | qualify"}
  ],
  "soft_quantitative_claims": [
    {"claim": "عین جمله‌ی موجود در مقاله (کپی دقیق)",
     "exact_span": "عین بخش کوتاهی از متن که ادعای کمی نرم را می‌سازد — باید هم در claim و هم در مقاله عیناً وجود داشته باشد",
     "category": "duration_generalization | frequency_generalization | performance_generalization | cost_generalization | speed_generalization",
     "asserted_outcome": "معنای ادعایی منتقل‌شده — بدون افزودن Fact جدید",
     "supported": false,
     "verified_fact_id": null,
     "confidence": "high | medium | low",
     "required_action": "keep | remove | neutralize",
     "reason": "دلیل کوتاه"}
  ],
  "title_suggestion": "پیشنهاد عنوان بهتر (یا null اگر عنوان خوب است)",
  "meta_suggestion": "پیشنهاد متای بهتر (یا null)",
  "cta_suggestion": "پیشنهاد CTA بهتر (یا null)",
  "unsourced_claims": ["ادعاهای عددی/آماری بدون منبع"],
  "issues": [
    {
      "category": "ai_cliche | robotic_language | low_eeat | weak_cta | generic_example | missing_local_example | weak_title | weak_meta | unnatural_keyword | low_information_gain | repetitive_sentence",
      "severity": "high | medium | low",
      "location": "کجای مقاله",
      "exact_quote": "نقل‌قول دقیق از متن (کپی کلمه‌به‌کلمه، حداکثر ۳۰ کلمه)",
      "problem": "چرا ایراد است",
      "rewrite_instruction": "دستور عملی اصلاح — با مثال ملموس، نه توصیه‌ی کلی"
    }
  ],
  "recommendations": {
    "high_priority": ["اصلاحات ضروری قبل از انتشار"],
    "medium_priority": ["اصلاحات برای افزایش رتبه"],
    "long_term": ["اصلاحات برای Authority شدن"]
  },
  "summary_table": [
    {"section": "Human Tone", "score": 0-10, "main_issue": "...", "fix": "..."}
  ],
  "rules_compliance": {
    "followed": ["قوانین تحریریه‌ای که مقاله رعایت کرده (متن کوتاه قانون)"],
    "violated": [
      {"rule": "متن کوتاه قانون نقض‌شده", "severity": "high | medium | low",
       "evidence": "شاهد کوتاه از متن", "fix": "پیشنهاد اصلاح مشخص"}
    ]
  }
}
- سخت‌گیر باش: متن AI-گونه با کلیشه و ادعای بی‌منبع نباید human_tone بالا بگیرد.
- لحن را با «وجود روایت اول‌شخص» نسنج: نبود تجربه‌ی شخصی یا اول‌شخص، به‌تنهایی
  نمره را پایین نمی‌آورد و وجودش نمره نمی‌سازد. معیار لحن: روشنی، ریتم طبیعی،
  نبود کلیشه، و نثر مستقیم.
- exact_quote هر ایراد باید واقعاً در متن باشد.
- همه‌ی کلیشه‌ها را در issues هم بیاور (category=ai_cliche) تا نویسنده اصلاحشان کند.
- در پیشنهادها هرگز کلیشه را با مترادف کلیشه‌ای جایگزین نکن («راهکاری ضروری»→«ابزاری
  حیاتی» ممنوع)؛ به‌جای جمله‌ی جایگزین، اقدام (حذف/کوتاه‌سازی/بیان مستقیم) و
  must_not_add بده.
- rules_compliance را دقیقاً بر اساس <editorial_rules> داده‌شده در ورودی پر کن —
  همین قوانین معیار داوری تو هستند (همان قوانینی که نویسنده با آن‌ها می‌نویسد).

گیت‌های سخت (وجود هر کدام یعنی ردّ قطعی — این‌ها را حتماً در issues با severity=high بیاور):
1. عدد، درصد، قیمت یا مدت‌زمان بدون منبع در verified_facts/citable_facts
2. تجربه‌ی شخصی/سازمانی تاییدنشده («در پروژه‌های ما»، «یادم می‌آید»، ...)
3. Case Study، مشتری یا پروژه‌ی خیالی
4. منبعی که از ادعای متصل‌شده پشتیبانی نمی‌کند (توسعه‌ی دامنه‌ی منبع)
5. CTA تجاری تاییدنشده (جلسه/مشاوره رایگان، تخفیف، تماس با کارشناسان — بدون approved_cta)
6. ادعای قطعی درباره‌ی افزایش فروش، سود، امنیت یا دقت بدون منبع
7. قابلیت فنی بدون ذکر پیش‌نیازهای لازم (API، یکپارچه‌سازی، داده، مجوز)
- quantitative_claims را برای تک‌تک ادعاهای کمی مقاله پر کن؛ هر ادعای unsupported
  باید در unsourced_claims هم بیاید (این دو فیلد باید هم‌خوان باشند).

Soft Quantitative Claims — فقط Span واقعی مقاله را گزارش کن:
- claim باید عین جمله موجود در مقاله باشد.
- exact_span باید عیناً هم در claim و هم در مقاله وجود داشته باشد.
- asserted_outcome فقط معنای Claim را توضیح دهد و Fact تازه نسازد.
- confidence فقط high، medium یا low باشد.
- required_action فقط keep، remove یا neutralize باشد.
- Claim تکراری نساز.
- توصیف قابلیت بدون شدت، فراوانی، زمان، هزینه، دقت یا نتیجه را Soft Claim نشمار.
- high فقط برای ادعای روشن و قابل اشاره با Span دقیق.
- medium برای موارد وابسته به Context.
- low فقط برای موارد مشکوک و گزارشی.
- بدون verified_fact، supported=true ممنوع است.
حتی یک ادعای Soft بی‌منبع با confidence=high باید passed=false کند.
- نکته‌ی قرارداد: نشانگرهای [[anchor:]] و [[external:]] مکانیزم رسمی لینک‌گذاری‌اند
  و placeholder خطا محسوب نمی‌شوند؛ تصاویر در مرحله‌ی انتشار اضافه می‌شوند و نبود
  <img> در body خطا نیست؛ فیلد جداگانه‌ی h1 منبع H1 صفحه است و نبود تگ <h1> در
  body_html خطا نیست.
"""

# وزن هر بُعد در نمره‌ی نهایی گیت (جمع = ۱)
_WEIGHTS = {
    "human_tone": 0.30,
    "eeat": 0.20,
    "conversion": 0.15,
    "keyword": 0.10,
    "seo": 0.10,
    "structure": 0.075,
    "trust": 0.075,
}


def _load_prompt() -> str:
    return _PROMPT_FILE.read_text(encoding="utf-8") + _OUTPUT_ADDENDUM


def weighted_score(scores: dict) -> float:
    """میانگین وزنی امتیازها (۰-۱۰)."""
    total, wsum = 0.0, 0.0
    for key, w in _WEIGHTS.items():
        v = scores.get(key)
        if isinstance(v, (int, float)):
            total += v * w
            wsum += w
    return round(total / wsum, 1) if wsum else 0.0


def review(payload: dict, step: str = "quality_gate") -> dict:
    """مقاله را با پرامپت نقش‌محور بررسی می‌کند. dict خروجی + passed برمی‌گرداند."""
    cfg = load_settings().get("quality_gate", {})
    min_weighted = float(cfg.get("min_weighted_score", 7.5))
    min_human = float(cfg.get("min_human_tone", 8))

    title = payload.get("title_seo") or payload.get("h1", "")
    meta = payload.get("meta_description", "")
    body = payload.get("body_html") or payload.get("body_markdown", "")
    kw = payload.get("target_keywords", {}) or {}
    primary = kw.get("primary_fa") or kw.get("primary") or ""

    cta = payload.get("approved_cta") or {}
    cta_line = (json.dumps(cta, ensure_ascii=False) if cta.get("enabled")
                else "هیچ CTA تجاری تایید نشده — هر CTA تجاری در متن یعنی ردّ قطعی (گیت سخت ۵)")
    facts = payload.get("citable_facts") or []
    facts_block = ("\n".join(f"- {f}" for f in facts) if facts
                   else "(هیچ فکت مستندی ثبت نشده — هر ادعای عددی unsupported است)")
    user_content = (
        f"کیورد اصلی مقاله: {primary or 'نامشخص'}\n"
        f"عنوان: {title}\n"
        f"متا: {meta}\n\n"
        f"<verified_facts>\n{facts_block}\n</verified_facts>\n"
        f"<approved_cta>\n{cta_line}\n</approved_cta>\n\n"
        f"متن کامل مقاله:\n{body}"
    )
    # همان Rule Engine نویسنده/سردبیر → معیار داوری یکسان (حذف اختلاف تولید و ارزیابی)
    rules_block = editor_memory.rules_prompt_block()
    if rules_block:
        user_content += f"\n\n<editorial_rules>\n{rules_block}\n</editorial_rules>"

    result = llm.ask(
        step,
        user_content,
        model_tier="main",
        system=_load_prompt(),
        cache_system=True,
        json_output=True,
        max_tokens=20000,
    ) or {}

    scores = result.get("scores", {}) or {}
    wscore = weighted_score(scores)
    human = float(scores.get("human_tone", 0) or 0)

    # Calibration patch: ادغام اتحاد کنترل‌شده — قطعی مبنا؛ LLM فقط تایید/تنزل.
    # Span جعلیِ منفرد = فقط حذف Claim + warning (نه Schema Error، نه Hard Reject).
    from .architecture_v2_1_utils import (
        count_soft_by_confidence, detect_soft_quantitative_claims, merge_soft_claims,
    )
    from .writer import _fact_entries
    det_soft = [c.as_dict() for c in detect_soft_quantitative_claims(
        body, verified_facts=_fact_entries(payload))]
    llm_soft = result.get("soft_quantitative_claims", []) or []
    # schema_valid فقط وقتی false که کل ساختار soft خراب باشد (لیست نباشد) — نه Span منفرد
    schema_valid = isinstance(llm_soft, list)
    soft_claims, invalid_soft = merge_soft_claims(
        deterministic_claims=det_soft, llm_claims=llm_soft if schema_valid else [],
        article_text=body)
    if invalid_soft:
        logger.info(f"Quality Gate: {len(invalid_soft)} ادعای LLM با Span جعلی حذف شد "
                    f"(gate_claim_invalid_span — warning، نه ردّ مقاله)")
    conf_counts = count_soft_by_confidence(soft_claims)
    soft_unsupported = [c for c in soft_claims if c.get("supported") is not True]
    high_unsupported = conf_counts["high"]
    medium_unsupported = conf_counts["medium"]

    # گیت سخت: ادعای کمی صریح بدون منبع = ردّ قطعی
    qclaims = result.get("quantitative_claims", []) or []
    unsupported = [c for c in qclaims if (c.get("status") or "").lower() == "unsupported"]
    # هم‌خوانی unsourced_claims با quantitative_claims (نباید یکی خالی و دیگری پر باشد)
    unsourced = list(result.get("unsourced_claims", []) or [])
    for c in unsupported:
        if c.get("claim") and c["claim"] not in unsourced:
            unsourced.append(c["claim"])

    # Calibration patch: فقط soft-claim با confidence=high مستقیماً گیت سخت است.
    # medium → فقط warning (نه گیت سخت، نه unresolved_source_gap مسدودکننده)؛ low گزارشی.
    passed = (wscore >= min_weighted and human >= min_human
              and not unsupported and high_unsupported == 0 and schema_valid)

    reasons = []
    if human < min_human:
        reasons.append(f"لحن انسانی {human}/10 < حداقل {min_human}")
    if wscore < min_weighted:
        reasons.append(f"نمره‌ی وزنی کیفیت {wscore}/10 < حداقل {min_weighted}")
    if unsupported:
        reasons.append(f"{len(unsupported)} ادعای کمی بدون منبع (گیت سخت)")
    if high_unsupported:
        reasons.append(f"{high_unsupported} ادعای کمی نرم high بدون منبع (گیت سخت)")
    if medium_unsupported:
        reasons.append(f"{medium_unsupported} ادعای کمی نرم medium (warning — بدون ردّ)")
    if not schema_valid:
        reasons.append("خروجی soft_quantitative_claims گیت به‌کل نامعتبر (Schema Error — ردّ)")

    logger.info(
        f"Quality Gate: وزنی={wscore}/10، انسانی={human}/10، "
        f"ایرادات={len(result.get('issues', []))}, passed={passed}"
    )

    return {
        "passed": passed,
        "weighted_score": wscore,
        "scores": scores,
        "eeat_detail": result.get("eeat_detail", {}),
        "cliches": result.get("cliches", []),
        "quantitative_claims": qclaims,
        "soft_quantitative_claims": soft_claims,
        "soft_unsupported_claim_count": len(soft_unsupported),
        "high_confidence_soft_unsupported_count": high_unsupported,
        "medium_confidence_soft_unsupported_count": medium_unsupported,
        "low_confidence_soft_unsupported_count": conf_counts["low"],
        # Calibration patch: medium فقط warning است و مانع انتشار/ذخیره نمی‌شود
        "unresolved_source_gap": False,
        "schema_valid": schema_valid,
        "invalid_soft_claims": invalid_soft,
        "issues": result.get("issues", []) or [],
        "title_suggestion": result.get("title_suggestion"),
        "meta_suggestion": result.get("meta_suggestion"),
        "cta_suggestion": result.get("cta_suggestion"),
        "unsourced_claims": unsourced,
        "recommendations": result.get("recommendations", {}),
        "summary_table": result.get("summary_table", []),
        "rules_compliance": result.get("rules_compliance", {}),
        "reasons": reasons,
    }
