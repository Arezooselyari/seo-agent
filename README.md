# ایجنت تمام‌خودکار تولید محتوای فارسی AI

هر روز از منابع معتبر AI خبر می‌گیرد، بهترین موضوع را با LLM انتخاب می‌کند،
روی متن کامل منبع تحقیق می‌کند، مقاله را **مستقیماً فارسی** (نه ترجمه) با
ساختار سئو/GEO و لینک داخلی می‌نویسد، به‌صورت پیش‌نویس در وردپرس می‌گذارد و
در تلگرام خبر می‌دهد. بازبینی و دکمه‌ی Publish در خود ادیتور وردپرس است.

## معماری

```
Daily Scheduler (APScheduler / Windows Task Scheduler)
  → sync       همگام‌سازی انتشارهای دستی قبلی از وردپرس
  → ingest     خواندن RSS منابع (جدول sources در Supabase)
  → rank       امتیازدهی همه‌ی کاندیدها و انتخاب موضوع روز   [LLM ۱]
  → extract    استخراج متن کامل منبع (trafilatura)
  → research   Research Brief با ادعاهای مستند (ضد هالوسینیشن) [LLM ۲]
  → links      کاندیدهای لینک داخلی از سایت‌مپ (rule-based)
  → generate   نوشتن مقاله‌ی فارسی سئو/GEO + لینک داخلی        [LLM ۳]
  → publish    ارسال به وردپرس با status=draft
  → notify     پیام تلگرام با لینک ویرایش
  → [انسان]    بازبینی و Publish در ادیتور وردپرس
```

فقط ۳ فراخوانی LLM در هر اجرا — SEO و استراتژی محتوای فارسی، بخش ثابت
prompt نویسنده هستند ([prompts/persian_writer.md](prompts/persian_writer.md))، نه ایجنت جدا.

```
src/
  config.py          تنظیمات (config.yaml) + secrets (.env)
  db.py              لایه‌ی Supabase — sources, topics, research_briefs, articles, publishing
  llm.py             فراخوانی structured مشترک (openrouter / gemini / claude)
  ingest.py          خواندن RSS + dedup
  rank.py            Topic Selector — امتیازدهی LLM            [LLM ۱]
  extract.py         استخراج متن تمیز (trafilatura)
  research.py        Research Brief از متن کامل                 [LLM ۲]
  internal_links.py  سایت‌مپ → کاندیدهای لینک داخلی (بدون LLM)
  generate.py        Persian Writer — مقاله‌ی فارسی سئو/GEO     [LLM ۳]
  publish.py         انتشار در وردپرس (پشت interface قابل‌توسعه)
  notify.py          نوتیفیکیشن تلگرام (پیش‌نویس آماده / خطا)
  sync.py            همگام‌سازی وضعیت انتشار از وردپرس
  pipeline.py        اجرای end-to-end
  scheduler.py       اجرای روزانه (APScheduler)
prompts/
  topic_selector.md  امتیازدهی موضوع‌ها
  research_brief.md  تحقیق ضد هالوسینیشن
  persian_writer.md  نویسنده‌ی فارسی + SEO/GEO + لینک داخلی
migrations/
  001_init.sql       schema دیتابیس Supabase
```

## راه‌اندازی

```bash
pip install -r requirements.txt
copy .env.example .env      # سپس مقادیر را پر کن
```

1. **Supabase:** یک پروژه بساز، `migrations/001_init.sql` را در SQL Editor اجرا کن،
   و `SUPABASE_URL` + `SUPABASE_KEY` را از Project Settings → API در `.env` بگذار.
2. **وردپرس:** داشبورد → Users → Profile → «Application Passwords» → یک رمز بساز
   و در `WP_APP_PASSWORD` بگذار.
3. **تلگرام:** با @BotFather یک بات بساز (`TELEGRAM_BOT_TOKEN`)، به بات پیام بده،
   و chat id خودت را در `TELEGRAM_CHAT_ID` بگذار.

## اجرا (مرحله به مرحله برای تست)

```bash
# ۱) فقط جمع‌آوری موضوع‌ها (نیاز به Supabase، بدون کلید LLM)
python -m src.ingest

# ۲) امتیازدهی و انتخاب موضوع روز (نیاز به کلید LLM)
python -m src.rank

# ۳) استخراج متن یک مقاله
python -m src.extract <url>

# ۴) تست Research Brief
python -m src.research <url> "نام منبع"

# ۵) تست کاندیدهای لینک داخلی
python -m src.internal_links "موضوع تست"

# ۶) تولید مقاله‌ی فارسی end-to-end برای یک URL
python -m src.generate <url> "نام منبع"

# ۷) اجرای کامل موتور (روزانه همین اجرا می‌شود)
python -m src.pipeline

# ۸) همگام‌سازی دستی وضعیت انتشار
python -m src.sync
```

> روی ویندوز اگر کاراکتر فارسی در خروجی خراب شد:
> `set PYTHONUTF8=1` قبل از اجرا.

## اجرای خودکار روزانه

**گزینه‌ی ۱ — APScheduler (پروسه‌ی همیشه‌روشن):**
```bash
python -m src.scheduler
```
ساعت اجرا از `run_time` در `config.yaml` می‌آید.

**گزینه‌ی ۲ — Windows Task Scheduler (پیشنهادی روی ویندوز):**
```powershell
schtasks /Create /TN "ai-content-agent" /SC DAILY /ST 09:00 `
  /TR "pythonw -m src.pipeline" /F
```
(یا از Task Scheduler GUI با Start in = مسیر پروژه)

## چرخه‌ی بازبینی و انتشار

1. هر روز یک پیش‌نویس در وردپرس ساخته می‌شود (`status=draft` — چیزی روی سایت زنده نمی‌رود).
2. پیام تلگرام با عنوان، متا، امتیاز موضوع و **لینک ویرایش** می‌رسد.
3. مقاله را در ادیتور وردپرس می‌خوانی، اصلاح می‌کنی و **Publish** می‌زنی.
4. اجرای بعدی (یا `python -m src.sync`)، وضعیت را در Supabase به `published` می‌برد.

## وضعیت
- ✅ موتور کامل: ingest → select → extract → research → links → write → WP draft → telegram
- ✅ دیتابیس Supabase + state machine موضوع/مقاله/انتشار
- ✅ زمان‌بندی روزانه (APScheduler / Task Scheduler)
