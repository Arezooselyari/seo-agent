"""حافظه‌ی تحریریه: یادگیری از خطاهای تکراری در مقالات مختلف.

هر بار QA ایرادی پیدا می‌کند، دسته‌ی آن شمرده می‌شود. وقتی یک دسته به حد نصاب
(minimum_occurrence در settings.yaml) رسید، به‌عنوان «درس تحریریه» وارد پرامپت
نویسنده می‌شود تا از اول آن اشتباه را نکند.

فایل داده: data/editor_memory.json
{
  "counts": {"weak_meta": 4, "ai_cliche": 7, ...},
  "examples": {"weak_meta": ["نمونه ایراد...", ...]},   # حداکثر ۳ نمونه per دسته
  "updated_at": "..."
}
"""
import json
import logging
from datetime import datetime, timezone

from .config import CONFIG_DIR, DATA_DIR, load_settings

logger = logging.getLogger(__name__)

_MEMORY_FILE = DATA_DIR / "editor_memory.json"
_RULES_FILE = CONFIG_DIR / "editorial_rules.json"

# عنوان فارسی هر دسته‌ی قوانین (قوانین خودشان انگلیسی می‌مانند — ترجمه‌ی خودکار ریسک تحریف دارد)
_RULE_CATEGORY_TITLES = {
    "human_tone_rules": "قوانین لحن انسانی",
    "seo_rules": "قوانین سئو",
    "eeat_rules": "قوانین E-E-A-T",
    "search_intent_rules": "قوانین نیت جستجو",
    "conversion_rules": "قوانین تبدیل (Conversion)",
    "readability_rules": "قوانین خوانایی",
    "anti_ai_writing_rules": "قوانین ضد نگارش AI (اولویت بالا)",
    "voice_spec_rules": "مشخصات صدای نویسنده — Voice Spec (معیار مشترک نویسنده و داور)",
    "accuracy_rules": "قوانین دقت فنی و اعتبار ادعاها (از بازخورد سردبیر انسانی — اولویت بالا)",
}

# پیوند دسته‌ی ایراد QA → دسته‌ی قانون مرتبط (برای غنی‌کردن درس‌های آماری)
_ISSUE_TO_RULE_CATEGORY = {
    "ai_cliche": "anti_ai_writing_rules",
    "robotic_language": "anti_ai_writing_rules",
    "repetitive_sentence": "anti_ai_writing_rules",
    "low_information_gain": "anti_ai_writing_rules",
    "weak_hook": "human_tone_rules",
    "generic_example": "human_tone_rules",
    "missing_local_example": "eeat_rules",
    "low_eeat": "eeat_rules",
    "weak_title": "seo_rules",
    "weak_meta": "seo_rules",
    "keyword_missing": "seo_rules",
    "keyword_stuffing": "seo_rules",
    "unnatural_keyword": "seo_rules",
    "missing_link": "seo_rules",
    "echo_heading": "readability_rules",
    "paragraph_too_long": "readability_rules",
    "poor_scannability": "readability_rules",
    "poor_transition": "readability_rules",
    "weak_cta": "conversion_rules",
    "faq_duplicate": "search_intent_rules",
}

_rules_cache: dict | None = None

# توضیح فارسی هر دسته برای تزریق به پرامپت نویسنده
_CATEGORY_GUIDANCE = {
    "robotic_language": "از جملات قالبی و ماشینی پرهیز کن؛ مثل یک نویسنده‌ی باتجربه‌ی فارسی‌زبان بنویس.",
    "keyword_stuffing": "کیورد را طبیعی و کم‌تکرار به کار ببر؛ تکرار مصنوعی ممنوع.",
    "keyword_missing": "کیورد اصلی را حتماً در H1، صد کلمه‌ی اول، یک H2 و جمع‌بندی بیاور.",
    "echo_heading": "پاراگراف بعد از هر H2 نباید همان عنوان را طوطی‌وار تکرار کند؛ مستقیم پاسخ بده.",
    "weak_hook": "مقدمه را با داده، مثال ملموس یا ادعای صریح شروع کن، نه کلی‌گویی.",
    "weak_cta": "جمع‌بندی باید یک اقدام مشخص و عملی به خواننده بدهد.",
    "paragraph_too_long": "پاراگراف‌ها را کوتاه نگه دار (حداکثر ۴-۵ جمله).",
    "poor_transition": "بین بخش‌ها پیوند منطقی بساز؛ پرش ناگهانی نکن.",
    "generic_example": "مثال کلی نزن؛ اسم صنف، شهر یا موقعیت واقعی ایرانی بیاور.",
    "missing_local_example": "حداقل یک مثال ملموس از بازار ایران در بدنه بیاور.",
    "low_information_gain": "هر بخش باید حرف تازه‌ای بزند؛ تکرار همان مفاهیم ممنوع.",
    "low_eeat": "به منبع استناد کن و ادعای عددی را فقط از داده‌ی منبع بیاور.",
    "poor_scannability": "از لیست، جدول و بولد کردن نکات کلیدی استفاده کن.",
    "repetitive_sentence": "طول و ساختار جملات را متنوع کن؛ سه جمله‌ی هم‌ساختار پشت هم ننویس.",
    "unnatural_keyword": "کیورد را در جمله طوری بنشان که طبیعی خوانده شود.",
    "ai_cliche": "عبارات کلیشه‌ای AI (در دنیای امروز، جالب است بدانید، ...) ممنوع.",
    "weak_title": "عنوان باید مشخص، جذاب و شامل کیورد باشد؛ حداکثر ۶۰ کاراکتر.",
    "weak_meta": "متا باید ۱۵۰-۱۶۰ کاراکتر، شامل کیورد و دعوت به اقدام باشد.",
    "faq_duplicate": "سوالات FAQ نباید هم‌پوشانی داشته باشند؛ هر سوال یک نیاز واقعی متفاوت.",
    "incomplete_sentence": "جمله‌ی آخر هر پاراگراف را کامل تمام کن؛ متن ناتمام ممنوع.",
    "missing_link": "حداقل ۲ لینک داخلی [[anchor:]] و ۱ لینک خارجی [[external:]] در متن بگذار.",
}


def _load() -> dict:
    if _MEMORY_FILE.exists():
        try:
            return json.loads(_MEMORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("editor_memory.json خراب بود؛ از نو ساخته می‌شود.")
    return {"counts": {}, "examples": {}}


# ── Rule Engine: قوانین عمومی تحریریه (config/editorial_rules.json) ──────────

def load_rules() -> dict:
    """قوانین تحریریه را می‌خواند (با کش). اگر فایل نبود/خراب بود → {} (بدون fail).

    Backward compatible: با حذف فایل، همه‌ی مصرف‌کننده‌ها بلوک خالی می‌گیرند
    و سیستم دقیقاً مثل قبل کار می‌کند.
    """
    global _rules_cache
    if _rules_cache is not None:
        return _rules_cache
    try:
        data = json.loads(_RULES_FILE.read_text(encoding="utf-8"))
        _rules_cache = {k: v for k, v in data.items() if isinstance(v, list)}
        logger.info(
            f"قوانین تحریریه بارگذاری شد: {len(_rules_cache)} دسته، "
            f"{sum(len(v) for v in _rules_cache.values())} قانون"
        )
    except FileNotFoundError:
        _rules_cache = {}
    except Exception as e:
        logger.warning(f"editorial_rules.json قابل خواندن نبود ({e})؛ بدون قوانین ادامه می‌دهیم.")
        _rules_cache = {}
    return _rules_cache


def rules_prompt_block(
    categories: list[str] | None = None,
    max_rules_per_category: int | None = None,
) -> str:
    """قوانین را به بلوک پرامپت تبدیل می‌کند.

    categories: فقط این دسته‌ها (None = همه). فیلتر دسته مصرف توکن را کنترل می‌کند —
    هر ایجنت فقط قوانین مرتبط خودش را بگیرد.
    max_rules_per_category: سقف قانون در هر دسته (برای خلاصه‌ی تولید اولیه).
    """
    rules = load_rules()
    if not rules:
        return ""

    selected = categories or list(rules.keys())
    lines = [
        "قوانین تحریریه (راهنمای کیفیت — نه چک‌لیست؛ روح قوانین را در نگارش رعایت کن):"
    ]
    for cat in selected:
        items = rules.get(cat) or []
        if not items:
            continue
        if max_rules_per_category:
            items = items[:max_rules_per_category]
        title = _RULE_CATEGORY_TITLES.get(cat, cat)
        lines.append(f"\n[{title}]")
        lines.extend(f"- {r}" for r in items)
    return "\n".join(lines) if len(lines) > 1 else ""


def record_issues(issues: list[dict]) -> None:
    """ایرادات یک دور QA را در حافظه ثبت می‌کند."""
    if not issues:
        return
    mem = _load()
    for issue in issues:
        cat = issue.get("category", "").strip()
        if not cat:
            continue
        mem["counts"][cat] = mem["counts"].get(cat, 0) + 1
        ex = mem["examples"].setdefault(cat, [])
        quote = (issue.get("exact_quote") or "")[:120]
        if quote and quote not in ex:
            ex.append(quote)
            del ex[3:]  # حداکثر ۳ نمونه
    mem["updated_at"] = datetime.now(timezone.utc).isoformat()
    _MEMORY_FILE.write_text(json.dumps(mem, ensure_ascii=False, indent=2), encoding="utf-8")


def lessons_prompt_block() -> str:
    """درس‌های تحریریه (دسته‌های پرتکرار) را برای تزریق به پرامپت نویسنده می‌سازد."""
    cfg = load_settings().get("editor_memory", {})
    if not cfg.get("enabled", True):
        return ""
    min_occ = int(cfg.get("minimum_occurrence", 3))

    mem = _load()
    frequent = [
        (cat, n) for cat, n in sorted(mem["counts"].items(), key=lambda x: -x[1])
        if n >= min_occ and cat in _CATEGORY_GUIDANCE
    ]
    if not frequent:
        return ""

    rules = load_rules()
    lines = ["درس‌های تحریریه از مقالات قبلی (این اشتباهات پرتکرار را از اول نکن):"]
    for cat, n in frequent[:8]:
        line = f"- ({cat}، {n} بار) {_CATEGORY_GUIDANCE[cat]}"
        # اگر قانون عمومی مرتبطی وجود دارد، اولین قانون آن دسته را ضمیمه کن
        rule_cat = _ISSUE_TO_RULE_CATEGORY.get(cat)
        related = (rules.get(rule_cat) or []) if rule_cat else []
        if related:
            line += f"\n  ↳ قانون مرتبط: {related[0]}"
        lines.append(line)
    return "\n".join(lines)


def stats() -> dict:
    """آمار حافظه برای گزارش HTML."""
    mem = _load()
    return {"counts": dict(mem.get("counts", {})), "updated_at": mem.get("updated_at")}
