# SEMrush Flow — راهنمای اجرای دو فاز کیوردریسرچ و تحلیل سئو

این جریان **نیمه‌دستی** است: تماس‌های SEMrush را **Claude با کانکتور MCP** می‌زند (نه کد پایتون
و نه Task Scheduler). کد پایتون فقط فایل‌های واسط (`data/semrush_*.json`) را می‌خواند/می‌نویسد.

پل بین دو دنیا: `src/semrush_bridge.py`.

---

## چرا نیمه‌دستی؟

SEMrush یک تول MCP است و فقط وقتی Claude در جلسه‌ی تعاملی حاضر است در دسترس است.
اجرای خودکار (cron/schtasks) به آن دسترسی ندارد. برای خودکارسازی کامل در آینده،
باید کلید API واقعی SEMrush گرفت و `semrush_bridge` را به یک کلاینت HTTP تبدیل کرد.

---

## فاز A — کیوردریسرچ (قبل از تولید)

**Claude این مراحل را اجرا می‌کند:**

1. الگوی سه‌مرحله‌ای SEMrush:
   - `keyword_research` → لیست گزارش‌های موجود
   - `get_report_schema` → پارامترهای گزارش (مثلاً phrase/related/broad match, questions)
   - `execute_report` → اجرای گزارش برای seed keyword موضوع، دیتابیس `us` (طبق settings.yaml → semrush.market)
2. از خروجی استخراج کن: `keyword, volume, keyword difficulty (KD), cpc, related/phrase questions`.
3. **معیار انتخاب:**
   - کیورد اصلی: بیشترین حجم که `KD ≤ kd_max` (پیش‌فرض ۴۰ از settings.yaml) و با نیت موضوع هم‌راستا.
   - ۲–۴ کیورد پشتیبان (secondary).
   - ۱–۲ سوال long-tail (از گزارش questions).
4. **معادل فارسی:** چون دیتابیس انگلیسی است، برای هر کیورد یک معادل فارسی طبیعی بنویس
   (حجم/KD مربوط به نسخه‌ی انگلیسی است — این را در note ذکر کن).
5. ذخیره در فایل واسط:
   ```python
   from src import semrush_bridge
   semrush_bridge.save_keywords("موضوع دقیق مقاله", {
       "primary": "AI automation for small business",
       "primary_fa": "اتوماسیون هوش مصنوعی برای کسب‌وکار کوچک",
       "secondary": ["...", "..."],
       "longtail": ["how can AI reduce costs?", "..."],
       "per_kw": {"AI automation for small business": {"volume": 8100, "kd": 33, "cpc": 4.2}},
       "fa_map": {"AI automation for small business": "اتوماسیون هوش مصنوعی برای کسب‌وکار کوچک"},
       "market": "us",
       "note": "حجم/KD از دیتابیس انگلیسی SEMrush؛ معادل فارسی دستی.",
   })
   ```
   > `موضوع` باید **دقیقاً** برابر `brief["topic"]` باشد تا writer آن را پیدا کند.

---

## فاز B — تولید (کد پایتون)

`writer.write_article(brief)` خودکار فایل واسط را برای `brief["topic"]` می‌خواند و بلوک
کیوردها را در پرامپت تزریق می‌کند (کیورد اصلی در H1/۱۰۰ کلمه‌ی اول/یک H2/جمع‌بندی).
سپس مقاله در `agent.db` با `status=pending` ذخیره می‌شود.

اگر فایل واسط برای آن موضوع نباشد، writer بدون کیورد هدف کار می‌کند (fallback بی‌خطر).

---

## فاز C — تحلیل سئوی مقاله (بعد از تولید)

**Claude این مراحل را اجرا می‌کند، برای `article_id` مشخص:**

1. کیوردهای واقعی مقاله‌ی تولیدشده را دربیاور (از `db.get_article`).
2. با SEMrush (`keyword_research → get_report_schema → execute_report`) برای آن کیوردها:
   حجم، KD، رقابت و SERP را چک کن.
3. قضاوت کن: آیا مقاله کیوردهای رقابت‌پذیر و ارزشمند را هدف گرفته؟ (`GOOD` یا `WEAK`)
4. ذخیره در فایل واسط:
   ```python
   from src import semrush_bridge
   semrush_bridge.save_analysis(article_id, {
       "targeted_keywords": ["...", "..."],
       "per_kw": {"kw": {"volume": 5400, "kd": 29, "competition": 0.3}},
       "avg_kd": 31,
       "opportunities": ["کیوردهای کم‌رقابتی که مقاله می‌توانست هدف بگیرد"],
       "verdict": "GOOD",
       "notes": "...",
   })
   ```

---

## فاز D — ارزیابی و انتشار (کد موجود)

```bash
cd D:\prjcluade\seo-agent
set PYTHONIOENCODING=utf-8
python -m src.evaluate_and_sync
```

- `qa_analyzer.analyze_article` (حالت سخت‌گیرانه) نمره می‌دهد.
- `merge_semrush` گزارش فاز C را ادغام می‌کند.
- **گیت نهایی:** qa پاس **و** نمره ≥ آستانه **و** SEMrush verdict ≠ WEAK → تلگرام + HTML.
- HTML خروجی (`output/article-<id>-*.html`) بخش «تحلیل SEMrush» را دارد.

---

## خلاصه‌ی نقش‌ها

| فاز | مجری | ابزار |
|-----|------|-------|
| A کیوردریسرچ | **Claude** | SEMrush MCP → `save_keywords` |
| B تولید | پایتون | `writer.write_article` |
| C تحلیل سئو | **Claude** | SEMrush MCP → `save_analysis` |
| D ارزیابی/انتشار | پایتون | `evaluate_and_sync` |
