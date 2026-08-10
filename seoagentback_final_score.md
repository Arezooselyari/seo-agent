# بکاپ قبل از فاز ۱ لایه‌ی final_score — ۲۹ تیر ۱۴۰۵ (2026-07-19)

فاز ۱ فقط این تغییرات را دارد:
- **تغییر:** `config/settings.yaml` (افزودن بخش `final_score:`)
- **جدید:** `src/final_score.py`، `test_final_score.py`، `compare_final_score.py`

هیچ فایل دیگری (evaluate_and_sync.py، qa_analyzer.py، quality_gate.py، llm.py، db.py، html_export.py، telegram_approver.py، پرامپت‌ها) در فاز ۱ تغییر نکرده است.

برای بازگردانی: محتوای زیر را در `config/settings.yaml` بگذار و سه فایل جدید را حذف کن.

## config/settings.yaml (نسخه‌ی قبل از تغییر)

```yaml
# تنظیمات عمومی ایجنت

# ارائه‌دهنده‌ی مدل: anthropic | gemini
provider: "gemini"

# مدل‌ها (Anthropic)
models:
  cheap: "claude-haiku-4-5-20251001"   # فیلتر و استخراج
  main: "claude-fable-5"               # تولید مقاله‌ی نهایی

# مدل‌ها (Gemini) — کلید شخصی (paid tier)
gemini_models:
  cheap: "gemini-flash-lite-latest"    # فیلتر و استخراج و ترجمه (ارزان و سریع، alias پایدار)
  main: "gemini-2.5-flash"             # تولید و تحلیل نهایی

# SEMrush (کیوردریسرچ قبل از تولید + تحلیل سئو بعد از تولید)
# نکته: تماس‌های SEMrush را Claude با کانکتور MCP می‌زند (نیمه‌دستی)؛ کد فقط فایل واسط را می‌خواند.
semrush:
  enabled: true
  market: "us"      # دیتابیس کیورد (جهانی/انگلیسی — پوشش فارسی SEMrush ضعیف است)
  kd_max: 40        # حداکثر سختی کیورد (Keyword Difficulty) قابل‌قبول برای انتخاب

# جمع‌آوری
collect:
  max_per_source: 15        # حداکثر مقاله‌ی اخیر از هر منبع
  max_age_days: 7           # فقط مقالات یک هفته‌ی اخیر
  top_n_articles: 4         # چند مقاله‌ی برتر تحلیل عمیق شوند
  min_relevance: 6          # حداقل امتیاز ارتباط (۰ تا ۱۰)
  request_delay_seconds: 2  # تأخیر بین درخواست‌ها

# مقاله‌ی خروجی
article:
  language: "fa"
  min_words: 800
  max_words: 1200
  min_faq: 5

# تصاویر
images:
  featured: 1
  inline: 2

# انتشار
publish:
  hour: 12                  # ساعت انتشار
  default_status: "publish" # publish | draft
  category_ids: []          # شناسه‌ی دسته‌های وردپرس (بعد از اتصال پر کن)

# کانال تأیید: telegram | email | both
approval_channel: "telegram"

# تلگرام
telegram:
  bot_token: "${TELEGRAM_BOT_TOKEN}"  # از .env می‌خوانده می‌شود
  chat_id: "${TELEGRAM_CHAT_ID}"      # از .env می‌خوانده می‌شود

# ارزیابی SEO
evaluation:
  approval_threshold: 90              # حداقل امتیاز برای تایید خودکار
  approval_interval_seconds: 300      # بررسی‌ی هر N ثانیه (۵ دقیقه)
  telegram_review_min: 80             # مقالات needs_review با نمره ≥ این هم به تلگرام می‌روند (با برچسب هشدار)

# گردش کار تحریریه (Editorial Workflow) — حلقه‌ی اصلاح خودکار
qa:
  minimum_score: 90        # هدف حلقه‌ی اصلاح (توقف اگر نمره ≥ این)
  max_revision: 3          # حداکثر چرخه‌ی بازنویسی برای هر مقاله
  min_improvement: 5       # توقف اگر یک دور کمتر از این مقدار نمره را بالا برد (همگرایی)
  rewrite_enabled: true    # اگر false، رفتار قدیمی: ردشده → needs_review

writer:
  humanize: true
  preserve_good_sections: true   # بخش‌های سالم دست نمی‌خورند
  patch_rewrite: true            # فقط بخش‌های معیوب بازنویسی می‌شوند

editor_memory:
  enabled: true
  minimum_occurrence: 3    # الگوی خطا بعد از N بار تکرار وارد حافظه می‌شود

# دروازه‌ی کیفیت محتوا (پرامپت نقش‌محور: لحن انسانی + E-E-A-T + Conversion)
quality_gate:
  enabled: true
  min_human_tone: 7        # حداقل امتیاز انسانی‌بودن (۰-۱۰) — داور سخت‌گیر است؛ ۷ یعنی لحن واقعاً خوب
  min_weighted_score: 7.5  # حداقل میانگین وزنی ۷ بُعد (۰-۱۰)
```
