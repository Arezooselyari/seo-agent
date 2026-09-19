"""گام ۳ — تولید مقاله‌ی فارسی سئو شده (Generate Mode + Rewrite Mode).

پرامپت سیستم: prompts/seo-content-agent-prompt.xml (با Prompt Caching).
Rewrite Mode: فقط بخش‌های فهرست‌شده در revision_patch بازنویسی می‌شوند؛
بخش‌های سالم (preserve_sections) کلمه‌به‌کلمه حفظ می‌شوند.
"""
import json
import re

from . import editor_memory, llm, semrush_bridge
from .config import CONFIG_DIR, env, load_settings

_FORBIDDEN_FILE = CONFIG_DIR / "forbidden_phrases.txt"


def _forbidden_block() -> str:
    """لیست عبارات ممنوعه را برای تزریق به پرامپت‌ها می‌سازد."""
    if not _FORBIDDEN_FILE.exists():
        return ""
    phrases = [
        ln.strip() for ln in _FORBIDDEN_FILE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    if not phrases:
        return ""
    return (
        "عبارات ممنوعه (استفاده از هر کدام = ردّ قطعی مقاله؛ هرگز به کار نبر):\n"
        + "\n".join(f"- {p}" for p in phrases)
    )


def _context_blocks(rule_categories: list[str] | None = None,
                    max_rules_per_category: int | None = None) -> str:
    """بلوک‌های مشترک context برای هر سه مسیر نویسنده:
    درس‌های تحریریه + قوانین تحریریه (فیلترشده بر دسته) + عبارات ممنوعه.
    قوانین «راهنمای کیفیت»اند نه چک‌لیست — این در خود بلوک قوانین تصریح شده.
    """
    out = ""
    lessons = editor_memory.lessons_prompt_block()
    if lessons:
        out += f"\n\n<editorial_lessons>\n{lessons}\n</editorial_lessons>"
    rules = editor_memory.rules_prompt_block(rule_categories, max_rules_per_category)
    if rules:
        out += f"\n\n<editorial_rules>\n{rules}\n</editorial_rules>"
    forbidden = _forbidden_block()
    if forbidden:
        out += f"\n\n<forbidden_phrases>\n{forbidden}\n</forbidden_phrases>"
    return out

WRITE_PROMPT = """بر اساس بریف رقابتی زیر، یک مقاله‌ی کامل فارسی و سئو شده تولید کن.

<brief>
{brief}
</brief>

<target_keywords>
کیوردهای هدف (از تحلیل SEMrush — رعایت این‌ها برای رنکینگ حیاتی است):
{target_keywords}
</target_keywords>

<fact_policy>
- فقط از اطلاعات موجود در brief.citable_facts استفاده کن.
- هیچ عدد، درصد، قیمت، مدت‌زمان، نام مشتری، نام شرکت،
  Case Study یا نتیجه تجاری خارج از citable_facts تولید نکن.
- مثال فرضی فقط برای توضیح فرایند مجاز است.
- مثال فرضی نباید شامل عدد، درصد، قیمت، حجم فروش، نرخ رشد،
  نرخ کاهش، صرفه‌جویی زمانی یا نتیجه تجاری باشد.
- نبود داده را با آمار، داستان یا تجربه ساختگی جبران نکن.
- اگر داده کافی نیست، محدودیت اطلاعات را صادقانه بیان کن.
- هر منبع فقط از ادعایی پشتیبانی می‌کند که واقعاً در آن منبع آمده —
  منبع عمومی را به ادعای تخصصی/تجاری وصل نکن.
</fact_policy>

<soft_quantitative_claim_policy>
هر عبارت درباره زمان، هزینه، سرعت، دقت، فراوانی، میزان استفاده، نتیجه یا عملکرد،
حتی اگر عدد صریح نداشته باشد، ادعای کمی محسوب می‌شود.

بدون verified_fact مجاز نیستی عبارت‌هایی مانند موارد زیر یا معادل معنایی آن‌ها را تولید کنی:
«معمولاً»، «اغلب»، «بسیاری»، «اکثر»، «بخش بزرگی»، «چندین»،
«چند هفته»، «در مدت کوتاه»، «سریع‌تر»، «دقت بالا»، «بسیار دقیق»،
«رشد چشمگیر»، «افزایش قابل‌توجه»، «کاهش محسوس»، «هزینه کمتر»،
«عملکرد بهتر» و عبارت‌های مشابه.

اگر Fact تأییدشده وجود ندارد:
- ادعا را حذف کن؛
- یا آن را به توضیح شرطی و خنثی تبدیل کن؛
- هیچ عدد، بازه، شدت، فراوانی، مدت یا نتیجه جدیدی نساز.

نمونه مجاز:
«زمان راه‌اندازی به دامنه پروژه، تعداد اتصال‌ها و وضعیت زیرساخت بستگی دارد.»

نمونه غیرمجاز بدون verified_fact:
«راه‌اندازی معمولاً چند هفته طول می‌کشد.»
</soft_quantitative_claim_policy>

<cta_policy>
{cta_policy}
</cta_policy>

<requirements>
- زبان: فارسی روان و انسانی با این معیارهای اجرایی:
  * نثر مستقیم، روشن و حرفه‌ای باشد.
  * از تشبیه‌های کلیشه‌ای مانند «دستیار همیشه بیدار» استفاده نکن.
  * از عبارت‌های «در دنیای امروز»، «دیگر یک انتخاب نیست»،
    «راهکاری ضروری»، «تحول چشمگیر» و ساختارهای مشابه استفاده نکن.
  * هر پاراگراف باید حداقل یک نکته جدید اضافه کند.
  * یک مفهوم را با عبارت‌های متفاوت تکرار نکن.
  * تخصص باید از جزئیات فنی، محدودیت‌ها و پیش‌نیازها مشخص شود؛
    نه از لحن نمایشی یا ادعای تجربه.
- طول: {min_words} تا {max_words} کلمه
- ساختار هدینگ: بین ۴۰ تا ۷۰ درصد H2ها می‌توانند سوال‌محور باشند؛
  سایر H2ها باید توصیفی، مقایسه‌ای، فرایندمحور یا تصمیم‌محور باشند.
  ساختار هدینگ را بر اساس Search Intent انتخاب کن.
- بلافاصله پس از هر H2 یک پاسخ مستقیم ۱-۲ جمله‌ای بده. پاراگراف بعدی حق ندارد
  همان پاسخ را بازگویی کند؛ باید جزئیات، شرایط، محدودیت، پیش‌نیاز یا داده‌ی
  مستند جدید اضافه کند. اگر پاسخ مستقیم کافی است، مقدمه‌ی تکراری تولید نکن.
- بخش FAQ با حداقل {min_faq} سوال (H3 + پاسخ کوتاه)
- خلأهای محتوای رقبا (content_gaps) را پوشش بده — این مزیت رقابتی ماست
- از آمار واقعی بریف (citable_facts / verified_facts) تا حدِ ممکن استفاده کن تا مقاله
  عمومی و بی‌آمار نباشد: هر عدد را با استناد به «منبعِ همان فکت» (source_url در verified_facts)
  بیاور. اگر citable_facts خالی بود، هیچ عددی نساز و مقاله را کیفی/خنثی بنویس
  (مقاله‌ی بی‌آمار بهتر از آمارِ جعلی است).
- کلیدواژه‌های LSI/پشتیبان را **فقط اگر در جمله‌ای کاملاً طبیعی جا می‌شوند** بیاور.
  هرگز آن‌ها را به‌صورتِ پرانتزی («که در X مطرح می‌شود»)، توضیحِ اضافه‌شده به آخرِ جمله،
  یا در قالبِ عنوانِ ساختگی («آموزش X cowork»، «آموزش X design») نچپان.
  پوششِ ناقصِ LSI همیشه بهتر از جمله‌ی مصنوعی/تبلیغاتی‌نمای سئوست — اگر یک کیوردِ
  پشتیبان به‌سختی جا می‌شود، از آن صرف‌نظر کن.
- **کیوردِ اصلی را فقط در H1 عیناً بیاور.** در صد کلمه‌ی اول، یک H2 و جمع‌بندی هم باید
  حاضر باشد، ولی با **جمله‌بندیِ طبیعی و هر بار متفاوت** — نه تکرارِ عینِ همان عبارت.
  تکرارِ یک عبارتِ ثابت در چند پاراگراف متن را ماشینی و ترجمه‌ای نشان می‌دهد؛ نویسنده‌ی
  فارسی‌زبان همان مفهوم را هر بار به شکلی دیگر می‌گوید:
    کیورد «خطرات هوش مصنوعی»      → «هوش مصنوعی چه خطراتی دارد؟»، «خطرهایی که این فناوری
                                     به همراه دارد»، «تهدیدهای هوش مصنوعی»
    کیورد «ساخت ویدیو با هوش مصنوعی» → «چطور با هوش مصنوعی ویدیو بسازیم؟»، «تولیدِ ویدیو
                                     به کمکِ این ابزارها»
  (ارزیابِ سئو واژه‌های کیورد را جداجدا می‌سنجد، پس این تنوع نمره را پایین نمی‌آورد.)
- سرفصل را با قالبِ کلیشه‌ایِ «X چیست؟» نساز مگر موضوع واقعاً تعریفِ یک اصطلاح باشد؛
  سوالی بپرس که یک خواننده‌ی واقعی می‌پرسد («هوش مصنوعی چه خطراتی دارد؟» به‌جای
  «خطرات هوش مصنوعی چیست؟»).
- در FAQ و سایرِ H2ها عبارتِ عینِ کیورد را نیاور.
- زبانِ انگلیسیِ ترجمه‌نشده فقط برای **نامِ محصول/برند/مدل/برچسبِ دقیقِ رابطِ کاربری**
  مجاز است (مثلاً «Opus 5»، دکمه‌ی «New Notebook»). مفاهیمِ عمومی همیشه فارسی: «هوش
  مصنوعی» نه «artificial intelligence»، «حلِ مسئله» نه «problem solving». هیچ واژه‌ی
  انگلیسیِ غیربرندی وسطِ جمله‌ی فارسی نگذار.
- هیچ جمله‌ای که به کمک/پشتیبانی/متخصص/خدمتی اشاره کند بدونِ گفتنِ دقیقِ چه‌کسی/چگونه
  ننویس (مثلِ «می‌توانید از کمک بگیرید» بدونِ گفتنِ از کجا) — این نوع جمله‌ی معلق را
  اصلاً تولید نکن، نه اینکه بعداً حذفش کنی.
- لینک داخلی (اجباری، حداقل ۲): در متن، ۲ عبارت را با این نشانه علامت بزن:
  [[anchor: متن لینک | صفحه‌ی مقصد پیشنهادی]] — مثلاً [[anchor: مشاوره اتوماسیون | صفحه خدمات]]
- لینک خارجی (اجباری، حداقل ۱): منبع اصلی را یک بار با این نشانه بیاور:
  [[external: نام منبع | URL]] — از source_urls بریف استفاده کن
- جمله‌ی آخر بدنه باید کامل و با نقطه تمام شود (بدون جمله‌ی ناتمام)
</requirements>

{content_type_block}

فقط JSON با این ساختار برگردان (body_html با تگ‌های HTML کامل و نشانگرهای لینک [[anchor:]] و [[external:]] داخل متن):
{{
  "title_seo": "حداکثر ۶۰ کاراکتر، شامل کلیدواژه‌ی اصلی",
  "meta_description": "دقیقاً بین ۱۵۰ تا ۱۶۰ کاراکتر، شامل کیورد اصلی و یک دعوت به اقدام",
  "h1": "...",
  "slug": "english-url-slug",
  "body_html": "<p>مقدمه... [[anchor: متن | صفحه]] ...</p><h2>...</h2><p>... [[external: منبع | URL]] ...</p>...<h2>سوالات متداول</h2><h3>...</h3><p>...</p>",
  "tags": ["برچسب‌های فارسی"],
  "image_keywords": ["2-3 English keywords for stock photo search"],
  "seo_grade": 85
}}"""

_TUTORIAL_BLOCK = """<content_type_tutorial>
این یک «راهنمای آموزشیِ عملی» است — نه مقاله‌ی تحلیلی، نه گزارشِ خبری.
خواننده آمده تا **کاری را انجام دهد**، نه اینکه درباره‌ی ابزار بخواند.

معیارِ موفقیت: کسی که تا حالا این ابزار را باز نکرده، بعد از خواندنِ مقاله بتواند
واقعاً از آن استفاده کند. اگر متن فقط «توضیح می‌دهد» و «تحلیل می‌کند»، شکست خورده است.

ساختارِ الزامی (این ترتیب را رعایت کن):
1. مقدمه‌ی کوتاه (حداکثر ۳ جمله): این ابزار چه کاری برای تو انجام می‌دهد.
   ممنوع: تاریخچه‌ی شرکت، اخبارِ سرمایه‌گذاری، تحلیلِ بازار، آمارِ کاربران.
2. یک H2 «پیش‌نیازها» یا «قبل از شروع»: چه چیزی لازم است (حساب کاربری، نسخه، هزینه).
3. **دستِ‌کم دو H2 از نوعِ «چگونه ... کنیم»** که هرکدام شاملِ یک لیستِ شماره‌دار
   (`<ol><li>`) از گام‌های عملی باشد. هر گام باید یک **فعلِ امری** داشته باشد
   («باز کن»، «انتخاب کن»، «بنویس»، «کلیک کن») — نه توصیفِ منفعل.
4. یک H2 «مثالِ عملی»: یک نمونه‌ی واقعیِ ورودی/پرامپت که خواننده بتواند عیناً
   کپی کند، و توضیحِ اینکه چه خروجی‌ای می‌گیرد.
5. یک H2 «اشتباهاتِ رایج» یا «نکاتِ کاربردی» به‌صورتِ لیست (`<ul>`).
6. یک H2 «محدودیت‌ها» — صادقانه بگو چه کاری را خوب انجام نمی‌دهد.
7. FAQ و جمع‌بندیِ عملی (قدمِ بعدیِ مشخص).

قواعدِ لحن و محتوا:
- دومِ‌شخص بنویس («می‌توانی»، «باز کن») — نه سومِ‌شخصِ اداری («کاربران می‌توانند»).
- جمله‌های کوتاه. هر گام یک کار.
- **ممنوعِ مطلق**: بندهایی درباره‌ی اخبارِ شرکت، مقایسه‌ی سهمِ بازار، اعلامیه‌های
  محصول، سرمایه‌گذاری، یا هر چیزی که از فیدِ خبری آمده و به «چگونه استفاده کنم»
  ربطی ندارد. این‌ها مقاله را از آموزشی به خبری تبدیل می‌کنند.
- اگر جزئیاتِ دقیقِ رابطِ کاربری (نامِ دقیقِ دکمه/منو) در منابع مستند نیست، حدس نزن؛
  همان گام را در سطحِ کارکردی بنویس («وارد بخشِ تنظیماتِ مربوط به صدا شو»).
- هیچ عدد/آمارِ بی‌منبع نساز (fact_policy همچنان حاکم است).

فکت‌های خبری (قیمت، سیاستِ شرکت، تاریخِ انتشار، درصدِ ایمنی و مشابه) را **فقط در حدِ
یک یا دو جمله‌ی کوتاه، جدا از جریانِ اصلیِ گام‌ها** بیاور — مثلاً یک جمله‌ی مستقل بعد از
گام‌های «چگونه شروع کنیم» که هزینه را می‌گوید، نه اینکه کل بخشِ «پیش‌نیازها» را با
تحلیلِ قیمت‌گذاری/سیاستِ داده/مقایسه با رقبا پر کنی. اگر فکت‌های بریف عمدتاً خبری‌اند
(نه دستورالعملی)، این یعنی منبع برای تولیدِ ستونِ فقراتِ آموزش کافی نیست — گام‌ها را
از دانشِ عمومیِ نحوه‌ی کارِ این‌جور ابزارها بنویس (سطحِ مفهومی، بدونِ حدسِ جزئیات) و
فکت‌های خبری را فقط به‌عنوانِ نکته‌ی حاشیه‌ای اضافه کن. **ستونِ فقراتِ هر بخش باید
عملِ خودِ کاربر باشد (باز کردن، نوشتن، کلیک کردن)، نه تحلیلِ محصول.**
</content_type_tutorial>"""

REWRITE_PROMPT = """تو ویراستار ارشد تحریریه هستی. مقاله‌ی زیر در بازبینی QA ایراداتی داشت.
سردبیر یک «برنامه‌ی اصلاح پچ‌محور» نوشته. وظیفه‌ی تو اجرای دقیق آن است.

<article>
{article}
</article>

<revision_patches>
{patches}
</revision_patches>

<preserve_sections>
این بخش‌ها سالم‌اند و باید کلمه‌به‌کلمه، بدون هیچ تغییری، در خروجی حفظ شوند:
{preserve}
</preserve_sections>

<verified_facts>
{verified_facts}
</verified_facts>

{lessons}

قوانین اجرا:
1. فقط بخش‌های فهرست‌شده در پچ‌ها را بازنویسی کن — دقیقاً طبق instruction هر پچ.
2. بخش‌های preserve را عیناً کپی کن. حتی یک کلمه‌ی آن‌ها را عوض نکن.
3. پچ scope=global را روی کل متن اعمال کن ولی ساختار و بخش‌های سالم را نگه دار.
4. نشانگرهای لینک [[anchor: ...]] و [[external: ...]] موجود را حفظ کن (مگر پچ صریحاً بگوید).
5. متا باید ۱۵۰-۱۶۰ کاراکتر، عنوان ≤ ۶۰ کاراکتر، و جمله‌ی آخر بدنه کامل باشد.
6. هیچ Patch اجازه‌ی تولید واقعیت جدید ندارد.
7. اگر یک Patch درخواست عدد، مثال، Case Study، تجربه شخصی، منبع، قیمت، شهر،
   شرکت یا نتیجه‌ی جدیدی دارد که در verified_facts نیست، آن بخش را تولید نکن
   و در rewrite_warnings گزارش بده.
8. ادعای بدون منبع را با جزئیات بیشتر معتبر جلوه نده.
   آن را حذف یا به بیان کیفی محتاطانه تبدیل کن.
9. جایگزینی کلیشه با مترادف کلیشه‌ای ممنوع است.
   جمله باید کوتاه‌تر، مستقیم‌تر یا اطلاعاتی‌تر شود.
10. هیچ URL، برند، ابزار، شهر، شخص یا موجودیت جدیدی اضافه نکن.
11. اگر Patch با fact_policy یا accuracy_rules تضاد داشت،
    fact_policy و accuracy_rules اولویت بالاتر دارند.

خروجی: همان JSON کامل مقاله (title_seo, meta_description, h1, slug, body_html, tags,
image_keywords, seo_grade) — بدنه‌ی کامل با بخش‌های اصلاح‌شده + بخش‌های محفوظ.
در صورت ردّ یک پچ، فیلد اختیاری rewrite_warnings را هم اضافه کن:
"rewrite_warnings": [{{"patch_id": "شناسه/بخش پچ", "reason": "دلیل ردّ"}}]"""

HUMANIZE_PROMPT = """تو ویراستار سبک و نثر فارسی هستی. وظیفه‌ات فقط طبیعی‌تر کردن بیان مقاله است.
حق تغییر، توسعه یا تولید محتوای جدید نداری.

<article>
{article}
</article>

<quality_review>
{review}
</quality_review>

<verified_facts>
{verified_facts}
</verified_facts>

<locked_elements>
{locked_elements}
</locked_elements>

قوانین قطعی:

1. فقط سبک جمله‌بندی، ریتم، انتخاب واژه، طول جمله‌ها و تکرارهای زبانی را اصلاح کن.

2. هیچ اطلاعات، تحلیل، نتیجه‌گیری، توصیه، مثال، سناریو، شهر، شرکت،
   ابزار، قابلیت، عدد، درصد، مبلغ، قیمت، زمان یا ادعای جدیدی اضافه نکن.

3. هیچ تجربه شخصی یا سازمانی نساز. عبارت‌هایی مانند:
   «من دیده‌ام»، «در پروژه‌های ما»، «تجربه نشان داده»، «مشتریان ما»،
   «یادم می‌آید»، «در جلسه‌ای با مدیر...» و هر روایت دست‌اول تأییدنشده ممنوع است.

4. اگر جمله‌ای کلی است، آن را ساده‌تر و مستقیم‌تر کن؛
   برای ملموس‌کردن آن، عدد یا مثال جدید نساز.

5. سناریوی فرضی جدید اضافه نکن.
   سناریوی موجود را فقط در صورتی حفظ کن که در locked_elements ثبت شده باشد.

6. هیچ عدد، درصد، قیمت، مدت‌زمان، نرخ رشد، نرخ کاهش یا نتیجه کمی جدیدی مجاز نیست؛
   حتی داخل مثال فرضی.

7. منابع، URLها، اعداد، نام ابزارها و ادعاهای موجود را توسعه نده.
   هر منبع فقط از ادعایی پشتیبانی می‌کند که در verified_facts ثبت شده است.

8. H1، H2، H3، ساختار مقاله و نشانگرهای لینک را حفظ کن،
   مگر اینکه quality_review صریحاً تغییر ساختار را خواسته باشد.

9. عبارت‌های تبلیغاتی مطلق مانند «ضروری»، «حیاتی»، «تحول‌آفرین»،
   «افزایش چشمگیر فروش»، «بهترین راهکار» و «رشد تضمینی» را خنثی کن،
   مگر اینکه پشتوانه مستند داشته باشند.

10. قبل از تحویل بررسی کن:
    - عدد جدید: صفر
    - موجودیت جدید: صفر
    - مثال جدید: صفر
    - تجربه شخصی جدید: صفر
    - URL جدید: صفر
    - ادعای تجاری جدید: صفر

<soft_claim_preservation_policy>
در انسانی‌سازی:
- هیچ عبارت کمی نرم جدید درباره زمان، هزینه، سرعت، دقت، فراوانی یا عملکرد نساز.
- ادعای خنثی را به «معمولاً»، «اغلب»، «دقت بالا»، «رشد چشمگیر» یا عبارات مشابه تبدیل نکن.
- حق نداری برای طبیعی‌تر کردن متن، شدت یا فراوانی به جمله اضافه کنی.
- verified_facts و locked_numbers را فقط در allowed_scope همان Fact استفاده کن.
</soft_claim_preservation_policy>

خروجی همان JSON کامل مقاله باشد
(title_seo, meta_description, h1, slug, body_html, tags, image_keywords, seo_grade)."""


def write_article(brief: dict, keywords: dict | None = None, content_type: str = "news") -> dict:
    """مقاله را تولید می‌کند.

    keywords: dict کیوردهای هدف (خروجی semrush_bridge). اگر None باشد، از فایل واسط
    برای همین موضوع خوانده می‌شود (فاز A باید قبلاً توسط Claude اجرا شده باشد).
    content_type: "tutorial" (آموزشی/معرفیِ ابزار، ساختارِ قدم‌به‌قدم) | "news" (خبری، پیش‌فرض).
    """
    cfg = load_settings()["article"]
    if keywords is None:
        keywords = semrush_bridge.load_keywords(brief["topic"])
    # منبعِ کیورد طبقِ settings: free (Google Autocomplete، رایگان) یا semrush
    if keywords is None:
        kw_provider = (load_settings().get("keywords", {}) or {}).get("provider", "free")
        if kw_provider == "free":
            try:
                from . import keyword_free
                keywords = keyword_free.research_topic(brief["topic"])
            except Exception as e:
                print(f"[writer] هشدار: کیوردِ رایگان (Autocomplete) نشد: {e}")
        elif env("SEMRUSH_API_KEY") and load_settings().get("semrush", {}).get("enabled"):
            try:
                from . import semrush_api
                keywords = semrush_api.research_topic(brief["topic"])
            except Exception as e:
                print(f"[writer] هشدار: کیوردریسرچ خودکار SEMrush نشد: {e}")
    kw_block = semrush_bridge.keywords_prompt_block(keywords)

    # سیاست CTA: فقط CTA تاییدشده‌ی بریف مجاز است؛ وگرنه CTA خنثی/اطلاعاتی
    cta = brief.get("approved_cta") or {}
    if cta.get("enabled") and cta.get("text"):
        cta_policy = (
            "CTA تجاری تاییدشده (فقط همین، بدون تغییر پیشنهاد):\n"
            + json.dumps(cta, ensure_ascii=False, indent=1)
        )
    else:
        cta_policy = (
            "هیچ CTA تجاری تایید نشده است. هیچ جلسه رایگان، مشاوره رایگان، تخفیف، "
            "«تماس با کارشناسان»، خدمت یا پیشنهاد تجاری اختراع نکن. "
            "این محدودیت فقط جمع‌بندی نیست — در **هیچ‌جای متن** جمله‌ای شبیهِ CTA "
            "ننویس (مثلِ «می‌توانید کمک بگیرید»، «برای رفعِ این چالش از X کمک بگیرید»، "
            "«با کارشناسان تماس بگیرید») که ارجاعش به شخص/خدمتِ نامشخص باشد. "
            "جمع‌بندی باید خنثی و اطلاعاتی باشد: فقط قدمِ عملیِ خودِ کاربر (کاری که خودش "
            "با همین ابزار انجام می‌دهد)، نه ارجاع به کمکِ ثالث."
        )

    user_content = WRITE_PROMPT.format(
        brief=json.dumps(brief, ensure_ascii=False, indent=1),
        target_keywords=kw_block,
        min_words=cfg["min_words"],
        max_words=cfg["max_words"],
        min_faq=cfg["min_faq"],
        cta_policy=cta_policy,
        content_type_block=_TUTORIAL_BLOCK if content_type == "tutorial" else "",
    )
    # خلاصه‌ی قوانین همه‌ی دسته‌ها (۳ قانون اول هر دسته) — تولید بهتر از ابتدا، حلقه‌ی کوتاه‌تر
    _core = ("voice_spec_rules", "accuracy_rules")
    other_cats = [c for c in editor_memory.load_rules() if c not in _core]
    user_content += _context_blocks(rule_categories=other_cats or None, max_rules_per_category=3)
    # Voice Spec + قوانین دقت فنی — کامل (نه خلاصه)؛ داور کیفیت هم با همین‌ها قضاوت می‌کند
    core = editor_memory.rules_prompt_block(list(_core))
    if core:
        user_content += f"\n\n<voice_spec>\n{core}\n</voice_spec>"

    payload = llm.ask(
        step="article_writing",
        user_content=user_content,
        model_tier="main",
        system=llm.system_prompt_xml(),
        cache_system=True,
        max_tokens=20000,
        temperature=0.7,  # نویسندگی خلاق — با temp=0 متن قالبی می‌شود
    )
    payload["topic"] = brief["topic"]
    payload["source_urls"] = brief["source_urls"]
    payload["content_type"] = content_type
    if brief.get("source_titles"):
        payload["source_titles"] = brief["source_titles"]   # برای بخشِ خوانای «منابع»
    # فکت‌های مستند بریف در payload می‌مانند تا ویراستار سبک (humanize) بداند
    # کدام ادعاها پشتوانه دارند (verified_facts)
    if brief.get("citable_facts"):
        payload["citable_facts"] = brief["citable_facts"]
    if brief.get("verified_facts"):
        payload["verified_facts"] = brief["verified_facts"]   # نگاشتِ دقیقِ claim↔source
    if brief.get("approved_cta"):
        payload["approved_cta"] = brief["approved_cta"]
    if keywords:
        payload["target_keywords"] = keywords

    # v2.1: پیش‌فیلتر قطعی Soft Quantitative Claims — فقط کشف و ثبت (بدون بازنویسی خودکار)
    from .architecture_v2_1_utils import detect_soft_quantitative_claims
    soft = detect_soft_quantitative_claims(_payload_text(payload),
                                           verified_facts=_fact_entries(payload))
    payload["soft_quantitative_claims"] = [c.as_dict() for c in soft]
    # Calibration patch: فقط high قطعی (نتیجه‌ی سنجش‌پذیر) گیت سخت است
    high_ct = sum(1 for c in soft if not c.supported and c.confidence == "high")
    med_ct = sum(1 for c in soft if not c.supported and c.confidence == "medium")
    payload["soft_unsupported_claim_count"] = high_ct
    if high_ct or med_ct:
        print(f"[writer] ⚠ ادعای کمی نرم در پیش‌نویس: {high_ct} high (گیت سخت) "
              f"+ {med_ct} medium (فقط warning)")

    word_count = len(payload.get("body_html", "").split())
    print(f"[writer] ✓ مقاله تولید شد: «{payload.get('title_seo')}» (~{word_count} کلمه، نمره {payload.get('seo_grade')})")
    return payload


def rewrite_article(payload: dict, revision_plan: dict, revision_no: int = 1) -> dict:
    """Rewrite Mode: فقط بخش‌های معیوب را طبق برنامه‌ی اصلاح بازنویسی می‌کند.

    payload: مقاله‌ی فعلی. revision_plan: خروجی revision_planner.build_plan.
    خروجی: payload جدید (فیلدهای غیرمتنی مثل topic/source_urls/target_keywords حفظ می‌شوند).
    """
    patches = revision_plan.get("patches", [])
    if not patches:
        return payload

    article_repr = json.dumps(
        {
            "title_seo": payload.get("title_seo", ""),
            "meta_description": payload.get("meta_description", ""),
            "h1": payload.get("h1", ""),
            "slug": payload.get("slug", ""),
            "body_html": payload.get("body_html", ""),
            "tags": payload.get("tags", []),
        },
        ensure_ascii=False,
        indent=1,
    )
    # قوانین مرتبط با بازنویسی پچی: ضد AI (اولویت بالا) + خوانایی + سئو + Voice Spec + دقت فنی
    extra = _context_blocks(
        rule_categories=["anti_ai_writing_rules", "readability_rules", "seo_rules",
                         "voice_spec_rules", "accuracy_rules"]
    )

    new_payload = llm.ask(
        step=f"article_rewrite_r{revision_no}",
        user_content=REWRITE_PROMPT.format(
            article=article_repr,
            patches=json.dumps(patches, ensure_ascii=False, indent=1),
            preserve=json.dumps(revision_plan.get("preserve_sections", []), ensure_ascii=False),
            verified_facts=_verified_facts_block(payload),
            lessons=extra,
        ),
        model_tier="main",
        system=llm.system_prompt_xml(),
        cache_system=True,
        max_tokens=32000,  # بازنویسی کل مقاله + JSON + thinking — سقف بالا تا truncate نشود
        temperature=0.7,
    )
    new_payload = _as_payload(new_payload, "rewrite")

    if new_payload.get("rewrite_warnings"):
        print(f"[writer] ⚠ پچ‌های ردشده توسط fact_policy: "
              f"{json.dumps(new_payload['rewrite_warnings'], ensure_ascii=False)}")

    # هر کلیدی که ویراستار برنگردانده از نسخه‌ی اصلی حفظ می‌شود. لیستِ سفیدِ ثابت
    # قبلاً content_type و featured_image_url را جا می‌انداخت: مقاله بدون تصویرِ شاخص
    # منتشر می‌شد و انتخابگرِ نسبتِ آموزشی/خبری نوعِ مقاله را گم می‌کرد.
    for key, value in payload.items():
        if key not in new_payload:
            new_payload[key] = value

    word_count = len(new_payload.get("body_html", "").split())
    print(f"[writer] ✎ بازنویسی دور {revision_no}: «{new_payload.get('title_seo')}» (~{word_count} کلمه، {len(patches)} پچ)")
    return new_payload


# ── استخراج‌گرهای قطعی (برای verified_facts و validator) ─────────
_NUM_RE = re.compile(r"[0-9۰-۹٠-٩][0-9۰-۹٠-٩,.،٫/]*")
_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_URL_RE = re.compile(r"https?://[^\s\"'<>\]\)]+")
_LATIN_ENTITY_RE = re.compile(r"[A-Za-z][A-Za-z0-9.+&-]{2,}")
# ادعای تجربه‌ی دست‌اول تاییدنشده — الگوهای قطعی
_EXPERIENCE_PATTERNS = (
    "تجربه به من نشان", "در پروژه‌های ما", "مشتریان ما", "یادم می‌آید",
    "در جلسه‌ای با", "من دیده‌ام", "من خودم دیده", "در پروژه‌هایی که دیده",
    "تجربه نشان داده", "در پروژه اخیر", "در پروژه‌های بسیاری",
)


def _extract_numbers(text: str) -> set:
    out = set()
    for m in _NUM_RE.findall(text or ""):
        n = m.translate(_DIGIT_MAP).strip(",.،٫/")
        if n:
            out.add(n)
    return out


def _extract_urls(text: str) -> set:
    return set(_URL_RE.findall(text or ""))


def _extract_latin_entities(text: str) -> set:
    return set(_LATIN_ENTITY_RE.findall(text or ""))


def _payload_text(p: dict) -> str:
    """متن قابل‌انتشار payload برای مقایسه/اعتبارسنجی."""
    parts = [p.get("title_seo", ""), p.get("meta_description", ""),
             p.get("h1", ""), p.get("body_html", "") or p.get("body_markdown", "")]
    if p.get("faq"):
        parts.append(json.dumps(p["faq"], ensure_ascii=False))
    return " ".join(str(x) for x in parts)


def _h2_list(p: dict) -> list:
    body = p.get("body_html", "") or ""
    return [re.sub(r"<[^>]+>|\s+", " ", h).strip()
            for h in re.findall(r"<h2[^>]*>(.*?)</h2>", body, re.DOTALL)]


def _link_markers(p: dict) -> list:
    return sorted(re.findall(r"\[\[(?:anchor|external):[^\]]*\]\]",
                             p.get("body_html", "") or ""))


def _fact_entries(payload: dict) -> list[dict]:
    """فهرست ساخت‌یافته‌ی فکت‌های تاییدشده (برای پرامپت‌ها و آشکارساز soft claim).

    اگر خط‌لوله‌ی فکت `verified_facts` (نگاشتِ دقیقِ claim↔source) را ساخته باشد، از همان
    استفاده می‌کند (استنادِ درست). وگرنه به منطقِ موقعیتیِ قبلی (citable_facts/source_urls) برمی‌گردد.
    """
    verified = payload.get("verified_facts")
    if isinstance(verified, list) and verified:
        entries = []
        for i, vf in enumerate(verified, 1):
            claim = vf.get("claim") if isinstance(vf, dict) else str(vf)
            if not claim:
                continue
            entries.append({
                "id": f"fact_{i:02d}",
                "claim": claim,
                "source_url": vf.get("source_url") if isinstance(vf, dict) else None,
                "allowed_scope": "فقط همین ادعا — توسعه به نتایج تجاری/عددی دیگر ممنوع",
            })
        if entries:
            return entries

    facts = payload.get("citable_facts") or []
    urls = payload.get("source_urls") or []
    entries = []
    for i, fact in enumerate(facts, 1):
        entries.append({
            "id": f"fact_{i:02d}",
            "claim": fact,
            "source_url": urls[i - 1] if i - 1 < len(urls) else (urls[-1] if urls else None),
            "allowed_scope": "فقط همین ادعا — توسعه به نتایج تجاری/عددی دیگر ممنوع",
        })
    return entries


def _verified_facts_block(payload: dict) -> str:
    """فکت‌های مستند مقاله با نگاشت ادعا-منبع و دامنه‌ی مجاز (Claim–Source Mapping)."""
    facts = payload.get("citable_facts") or []
    urls = payload.get("source_urls") or []
    if not facts and not urls:
        return "(هیچ فکت تاییدشده‌ای ثبت نشده — بنابراین هیچ ادعای منبع‌دار یا عدد جدیدی مجاز نیست)"
    entries = _fact_entries(payload)
    data = {
        "verified_facts": entries,
        "source_urls": urls,
        "locked_numbers": sorted(_extract_numbers(" ".join(str(f) for f in facts))),
        "approved_cta": payload.get("approved_cta") or "(هیچ CTA تجاری تایید نشده)",
    }
    return json.dumps(data, ensure_ascii=False, indent=1)


def validate_humanize(old_payload: dict, new_payload: dict) -> list[str]:
    """اعتبارسنجی قطعی خروجی Humanizer — ویراستار سبک حق تولید واقعیت جدید ندارد.

    برمی‌گرداند: فهرست تخلف‌ها (خالی = معتبر).
    """
    violations = []
    old_t, new_t = _payload_text(old_payload), _payload_text(new_payload)

    facts_text = " ".join(str(f) for f in (old_payload.get("citable_facts") or []))
    allowed_nums = _extract_numbers(old_t) | _extract_numbers(facts_text)
    extra_nums = _extract_numbers(new_t) - allowed_nums
    if extra_nums:
        violations.append(f"عدد جدید: {sorted(extra_nums)}")

    allowed_urls = _extract_urls(old_t) | set(old_payload.get("source_urls") or [])
    extra_urls = _extract_urls(new_t) - allowed_urls
    if extra_urls:
        violations.append(f"URL جدید: {sorted(extra_urls)}")

    allowed_ents = (_extract_latin_entities(old_t)
                    | _extract_latin_entities(facts_text)
                    | _extract_latin_entities(" ".join(old_payload.get("source_urls") or [])))
    extra_ents = _extract_latin_entities(new_t) - allowed_ents
    if extra_ents:
        violations.append(f"موجودیت/برند جدید: {sorted(extra_ents)}")

    new_exp = [pat for pat in _EXPERIENCE_PATTERNS if pat in new_t and pat not in old_t]
    if new_exp:
        violations.append(f"ادعای تجربه‌ی جدید: {new_exp}")

    if _h2_list(old_payload) != _h2_list(new_payload):
        violations.append("ساختار H2 تغییر کرده")
    if _link_markers(old_payload) != _link_markers(new_payload):
        violations.append("نشانگرهای لینک تغییر کرده")

    # Calibration patch: فقط ادعای کمی نرمِ جدیدِ confidence=high (نتیجه‌ی سنجش‌پذیر)
    # ردّ می‌شود؛ افزودن medium/low در ویرایش سبک مانع نیست (کاهش False Positive).
    from .architecture_v2_1_utils import detect_soft_quantitative_claims
    facts = _fact_entries(old_payload)
    before_soft = {(c.claim, c.category)
                   for c in detect_soft_quantitative_claims(old_t, verified_facts=facts)
                   if c.confidence == "high"}
    after_soft = {(c.claim, c.category)
                  for c in detect_soft_quantitative_claims(new_t, verified_facts=facts)
                  if c.confidence == "high"}
    new_soft = sorted(after_soft - before_soft)
    if new_soft:
        violations.append("new_soft_quantitative_claim_high: "
                          + "; ".join(c[0][:60] for c in new_soft[:3]))

    return violations


def _locked_elements_block(payload: dict) -> str:
    """عناصر قفل‌شده‌ی مقاله: H1/H2ها، کیورد اصلی، نشانگرهای لینک و سناریوی علامت‌گذاری‌شده‌ی موجود."""
    body = payload.get("body_html", "") or ""
    tk = payload.get("target_keywords") or {}
    scenario = None
    m = re.search(r"[^.!?؟\n<>]*(?:فرض کنید|تصور کنید)[^.!?؟]*[.!?؟]?", body)
    if m:
        scenario = re.sub(r"<[^>]+>", "", m.group(0)).strip()[:250]
    locked = {
        "h1": payload.get("h1", ""),
        "h2_headings": [
            re.sub(r"<[^>]+>", "", h).strip()
            for h in re.findall(r"<h2[^>]*>(.*?)</h2>", body, re.DOTALL)
        ],
        "primary_keyword": tk.get("primary_fa") or tk.get("primary") or "",
        "link_markers": re.findall(r"\[\[(?:anchor|external):[^\]]*\]\]", body),
        "approved_scenario": scenario or "(سناریوی علامت‌گذاری‌شده‌ای در متن نیست — سناریوی جدید هم مجاز نیست)",
    }
    return json.dumps(locked, ensure_ascii=False, indent=1)


_CLEANUP_MODE_BLOCK = """<mandatory_cleanup_mode>
این مرحله فقط برای حذف یا خنثی‌سازی موارد مشخص‌شده در cleanup_targets است.

فقط روی exact_spanهای داده‌شده تغییر ایجاد کن.

مجاز:
- حذف جمله یا بخش ادعایی
- تبدیل ادعا به جمله شرطی، وابسته به پروژه و غیرکمی
- اصلاح اتصال دستوری بعد از حذف

ممنوع:
- ساخت عدد، درصد، قیمت، بازه زمانی یا نتیجه جدید
- ساخت تجربه اول‌شخص یا Case Study
- افزودن CTA، برند، URL یا موجودیت جدید
- جایگزینی Claim با یک ادعای کمی نرم دیگر
- تغییر H2، لینک، Marker، verified_fact یا locked_numbers
- بازنویسی بخش‌های خارج از cleanup_targets

اگر حذف یا خنثی‌سازی امن نیست، آن Target را unresolved گزارش کن؛ Fact جدید نساز.
</mandatory_cleanup_mode>"""


def _as_payload(result, step: str) -> dict:
    """پاسخِ ویراستار را به شیءِ مقاله تبدیل می‌کند.

    استخراجگرِ JSON هر کدام از «{» یا «[» که اول بیاید را می‌پذیرد، و مدل گاهی مقاله را
    در یک لیستِ تک‌عضوی می‌پیچد («[{...}]»). کدِ پایین‌دست شیء فرض می‌کرد و با
    «list indices must be integers or slices, not str» می‌ترکید — دورِ بازنویسی با
    مدلِ گران هدر می‌رفت (مقاله‌ی #۵۸ در ۱۰ سپتامبر و #۶۲ در ۱۷ سپتامبر).
    """
    if isinstance(result, list) and len(result) == 1 and isinstance(result[0], dict):
        return result[0]
    if isinstance(result, dict):
        return result
    raise ValueError(f"{step}: پاسخِ مدل شیءِ مقاله نبود ({type(result).__name__})")


def cleanup_article(payload: dict, cleanup_plan: dict) -> dict:
    """Mandatory Cleanup (v2.1.1): فقط spanهای هدف حذف/خنثی می‌شوند — هیچ چیز دیگری."""
    patches = cleanup_plan.get("patches", [])
    if not patches:
        return payload
    article_repr = json.dumps(
        {"title_seo": payload.get("title_seo", ""),
         "meta_description": payload.get("meta_description", ""),
         "h1": payload.get("h1", ""), "slug": payload.get("slug", ""),
         "body_html": payload.get("body_html", ""), "tags": payload.get("tags", [])},
        ensure_ascii=False, indent=1,
    )
    user_content = REWRITE_PROMPT.format(
        article=article_repr,
        patches=json.dumps(patches, ensure_ascii=False, indent=1),
        preserve=json.dumps(cleanup_plan.get("preserve_sections", []), ensure_ascii=False),
        verified_facts=_verified_facts_block(payload),
        lessons="",
    ) + "\n\n" + _CLEANUP_MODE_BLOCK
    new_payload = llm.ask(
        step="article_cleanup",
        user_content=user_content,
        model_tier="main",
        system=llm.system_prompt_xml(),
        cache_system=True,
        max_tokens=32000,
        temperature=0.3,   # پاک‌سازی محافظه‌کارانه — وفاداری بالا
    )
    new_payload = _as_payload(new_payload, "article_cleanup")
    # هر کلیدی که ویراستار برنگردانده از نسخه‌ی اصلی حفظ می‌شود. لیستِ سفیدِ ثابت
    # قبلاً content_type و featured_image_url را جا می‌انداخت: مقاله بدون تصویرِ شاخص
    # منتشر می‌شد و انتخابگرِ نسبتِ آموزشی/خبری نوعِ مقاله را گم می‌کرد.
    for key, value in payload.items():
        if key not in new_payload:
            new_payload[key] = value
    word_count = len(new_payload.get("body_html", "").split())
    print(f"[writer] 🧹 پاک‌سازی اجباری: «{new_payload.get('title_seo')}» (~{word_count} کلمه، {len(patches)} پچ)")
    return new_payload


def humanize_article(payload: dict, gate_report: dict, revision_no: int = 1) -> dict:
    """Humanize Mode: ویراستار سبک و نثر — فقط بیان طبیعی‌تر، بدون هیچ محتوای جدید.

    طبق پرامپت مصوب کاربر: تغییر فقط در جمله‌بندی/ریتم/واژه‌ها؛ عدد، مثال، سناریو،
    موجودیت یا ادعای جدید مطلقاً ممنوع. verified_facts و locked_elements از payload
    ساخته و به پرامپت تزریق می‌شوند.
    gate_report: خروجی quality_gate.review (کلیشه‌ها + ایرادات لحن به مدل داده می‌شود).
    """
    article_repr = json.dumps(
        {
            "title_seo": payload.get("title_seo", ""),
            "meta_description": payload.get("meta_description", ""),
            "h1": payload.get("h1", ""),
            "slug": payload.get("slug", ""),
            "body_html": payload.get("body_html", ""),
            "tags": payload.get("tags", []),
        },
        ensure_ascii=False,
        indent=1,
    )
    review_repr = json.dumps(
        {
            "scores": gate_report.get("scores", {}),
            "cliches": gate_report.get("cliches", []),
            "issues": [
                i for i in gate_report.get("issues", [])
                if i.get("category") in ("ai_cliche", "robotic_language", "generic_example",
                                          "missing_local_example", "repetitive_sentence", "low_eeat")
            ],
            "cta_suggestion": gate_report.get("cta_suggestion"),
        },
        ensure_ascii=False,
        indent=1,
    )

    user_content = HUMANIZE_PROMPT.format(
        article=article_repr,
        review=review_repr,
        verified_facts=_verified_facts_block(payload),
        locked_elements=_locked_elements_block(payload),
    )
    # فقط لیست عبارات ممنوعه ضمیمه می‌شود (هم‌راستا با قانون ۹)؛ قوانین لحن/سناریو
    # عمداً تزریق نمی‌شوند تا با فلسفه‌ی «فقط ویرایش سبک، بدون محتوای جدید» تضاد نکنند.
    forbidden = _forbidden_block()
    if forbidden:
        user_content += f"\n\n<forbidden_phrases>\n{forbidden}\n</forbidden_phrases>"

    new_payload = llm.ask(
        step=f"article_humanize_r{revision_no}",
        user_content=user_content,
        model_tier="main",
        system=llm.system_prompt_xml(),
        cache_system=True,
        max_tokens=32000,
        temperature=0.3,  # ویراستار سبک: وفاداری به متن مهم‌تر از خلاقیت است (قبلاً 0.9 برای بازنویسی خلاق)
    )
    new_payload = _as_payload(new_payload, "humanize")

    # هر کلیدی که ویراستار برنگردانده از نسخه‌ی اصلی حفظ می‌شود. لیستِ سفیدِ ثابت
    # قبلاً content_type و featured_image_url را جا می‌انداخت: مقاله بدون تصویرِ شاخص
    # منتشر می‌شد و انتخابگرِ نسبتِ آموزشی/خبری نوعِ مقاله را گم می‌کرد.
    for key, value in payload.items():
        if key not in new_payload:
            new_payload[key] = value

    # Validator قطعی: اگر ویراستار واقعیت جدید ساخته، خروجی این دور رد و نسخه‌ی قبلی حفظ می‌شود
    violations = validate_humanize(payload, new_payload)
    if violations:
        print(f"[writer] ⛔ خروجی انسانی‌سازی دور {revision_no} توسط validator رد شد: {violations}")
        from .architecture_v2_1_utils import stable_hash
        rejected = dict(payload)
        rejected["humanize_rejections"] = list(payload.get("humanize_rejections") or []) + [
            {"revision": revision_no, "violations": violations,
             "candidate_content_hash": stable_hash(_payload_text(new_payload)),
             "restored_content_hash": stable_hash(_payload_text(payload))}
        ]
        return rejected

    word_count = len(new_payload.get("body_html", "").split())
    print(f"[writer] ♻ انسانی‌سازی دور {revision_no}: «{new_payload.get('title_seo')}» (~{word_count} کلمه)")
    return new_payload
