"""مرحله‌ی انسانی‌سازی متن — پس از تولید مقاله.

ساختار (h2، tags، slug، meta_description، answer، faq) دست‌نخورده می‌ماند.
فقط بخش‌های روایی (intro، body هر بخش، conclusion) بازنویسی می‌شوند
تا لحن کاملاً انسانی، گرم و غیرماشینی داشته باشند.

این مرحله یک فراخوانی LLM اضافه است (۱ بار در هر مقاله).
"""
from __future__ import annotations

import copy
import json

from .config import Secrets, TenantConfig
from .generate import GeneratedArticle
from .llm import structured_call

_HUMANIZE_SCHEMA = {
    "type": "object",
    "properties": {
        "intro": {
            "type": "string",
            "description": "مقدمه‌ی بازنویسی‌شده‌ی دو جمله‌ای — انسانی و گرم",
        },
        "section_bodies": {
            "type": "array",
            "items": {"type": "string"},
            "description": "بدنه‌ی بازنویسی‌شده‌ی هر بخش — همان ترتیب ورودی",
        },
        "conclusion": {
            "type": "string",
            "description": "جمع‌بندی بازنویسی‌شده — مثل آخرِ یک گفتگوی واقعی",
        },
    },
    "required": ["intro", "section_bodies", "conclusion"],
}


def _build_prompt(article: GeneratedArticle) -> str:
    sections_text = "\n".join(
        f"[بخش {i + 1}]\n{s.get('body', '')}"
        for i, s in enumerate(article.sections)
    )
    return f"""تو یک ویراستار حرفه‌ای فارسی هستی — متخصص در نوشتن محتوای هوش مصنوعی
برای مدیران و صاحبان کسب‌وکار ایرانی.

یک مقاله‌ی فارسی دریافت کرده‌ای که خوب است ولی هنوز بوی ماشین می‌دهد.
وظیفه‌ات: متن روایی را بازنویسی کن تا مثل یک نویسنده‌ی واقعی به نظر برسد.

═══════════════════════════════════════════
قوانین بازنویسی (باید رعایت شوند)
═══════════════════════════════════════════

۱. ریتم جمله را بشکن: کوتاه، بلند، خیلی کوتاه، متوسط. هیچ‌وقت سه جمله‌ی یک‌شکل
   پشت‌سر‌هم نیاید.

۲. گاهی از این عبارات استفاده کن (نه همه‌شان، نه به اجبار — فقط آنجا که طبیعی است):
   - «ببینید» | «خب» | «راستش را بخواهید» | «بگذارید مستقیم باشم»
   - «جالب اینجاست که» | «نکته‌ی اصلی اینجاست» | «واقعاً جالبه»
   - «صادقانه بگویم» | «به نظرم» | «احتمالاً شما هم»
   - «پس چی؟» | «این یعنی چه برای کسب‌وکار شما؟»

۳. این عبارات ماشینی را پاک کن و جایگزین طبیعی بگذار:
   - «همچنین» → «و» یا «ضمناً»
   - «علاوه بر این» → حذف یا «اما»
   - «شایان ذکر است» → فقط بگو چیست
   - «به علاوه» → «یا»، «بلکه»
   - «در این راستا» → حذف
   - «از این رو» → «به همین دلیل»
   - «در دنیای پرشتاب امروز» → هرگز نگو این را
   - «به منظور» → «برای»
   - «در نتیجه‌گیری» → «خلاصه کنم»

۴. یک‌ سؤال بلاغی (که خودت جوابش را می‌دهی) به هر بخش اضافه کن — اگر جا داشت.
   مثال: «خب، این برای یک تیم ده‌نفره چه معنایی دارد؟»

۵. یک مثال ملموس روزمره اضافه کن که خواننده‌ی ایرانی باهاش ارتباط برقرار کند.
   مثال: «مثل اینکه یک کارمند ارشد داری که هرگز خسته نمی‌شود و هر شب جواب ایمیل‌هایت را می‌دهد.»

۶. گاهی خواننده را مستقیم خطاب کن: «اگر شما هم یک تیم فروش دارید...»،
   «احتمالاً الان دارید فکر می‌کنید...»

۷. پاراگراف‌ها ۲ تا ۴ جمله باشند — دیوار متن ممنوع.

═══════════════════════════════════════════
ممنوعات مطلق
═══════════════════════════════════════════
- هیچ اطلاعات، عدد، ادعا یا جزئیاتی را اضافه یا حذف نکن
- نام مدل‌ها (Claude، GPT-4، Gemini و...) را تغییر نده
- اصطلاحات تخصصی را حفظ کن
- طول نهایی تقریباً یکسان بماند (±۱۵٪ قابل قبول است)
- مقدمه (intro) همچنان دقیقاً دو جمله باشد

═══════════════════════════════════════════
متن ورودی
═══════════════════════════════════════════

### مقدمه
{article.intro}

### بخش‌های مقاله
{sections_text}

### جمع‌بندی
{article.conclusion}

═══════════════════════════════════════════

بازنویسی انسانی را از طریق قالب ساختاریافته تحویل بده.
تعداد آیتم‌های section_bodies باید دقیقاً {len(article.sections)} عدد باشد.
"""


def humanize_article(
    article: GeneratedArticle,
    cfg: TenantConfig | None = None,
    secrets: Secrets | None = None,
) -> GeneratedArticle:
    """متن روایی مقاله را بازنویسی می‌کند تا انسانی‌تر شود.

    یک فراخوانی LLM جداگانه است. در صورت خطا، مقاله‌ی اصلی (بدون تغییر) برمی‌گردد.
    """
    if not article.sections:
        return article

    prompt = _build_prompt(article)
    try:
        result = structured_call(
            prompt,
            _HUMANIZE_SCHEMA,
            cfg=cfg,
            secrets=secrets,
            tool_name="humanize_article",
            max_tokens=8192,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[humanize] خطا — مقاله‌ی اصلی برگردانده می‌شود: {e}")
        return article

    # ساخت نسخه‌ی جدید با متن انسانی‌شده
    humanized = copy.deepcopy(article)
    humanized.intro = result.get("intro") or article.intro
    humanized.conclusion = result.get("conclusion") or article.conclusion

    new_bodies = result.get("section_bodies") or []
    for i, section in enumerate(humanized.sections):
        if i < len(new_bodies) and new_bodies[i].strip():
            section["body"] = new_bodies[i]

    print(f"[humanize] ✅ متن انسانی‌سازی شد — {len(humanized.sections)} بخش")
    return humanized
