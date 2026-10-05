# version1 — بکاپ وضعیت پروژه (۱۳ تیر ۱۴۰۵ / 2026-07-13)

اسنپ‌شات کاملِ کارهای انجام‌شده تا این نقطه. اگر چیزی خراب شد، این سند
مرجعِ «چه چیزهایی ساخته شد و کجاست».

---

## ۱. ایجنت اصلی (بدون تغییر منطق)
موتور تولید مقاله‌ی فارسی SEO که هر روز خودکار اجرا می‌شود:
`ingest → rank → extract → research → generate → humanize → render → telegram`
- دیتابیس: Supabase (ابری)، جدول‌های `sources/topics/research_briefs/articles/publishing`
- زمان‌بندی: Windows Task Scheduler (`PersianAI-Agent` / `PersianAI-CheckAndRun`)
- خروجی مقاله: صفحه‌ی HTML کامل با استایل «vlumis» — `src/render.py`

## ۲. بسته‌ی نصب برای مشتری (bat)
- `setup_wizard.bat` — نصب اولیه: Python، کلیدها، config، Task Scheduler
  (اکنون `requirements-agent.txt` را نصب می‌کند، نه `requirements.txt`)
- `launcher.bat` — اجرای دستیِ مرئی با پنجره‌ی رنگی
- `agent_status.bat` — داشبورد وضعیت (زمان اجرا، لاگ، لیست مقالات)
- `config_editor.bat` + `src/config_editor_cli.py` — منوی تعاملیِ تنظیمات
  (سایت، منابع RSS، کلیدواژه‌های حوزه، زمان‌بندی، کلیدهای API، راهنمای دیتابیس)

## ۳. دموی وب (نسخه‌ی آزمایشیِ SaaS)
- `src/demo_api.py` — بک‌اند FastAPI: صفحه‌ی `/` + `/api/demo`
- `demo/index.html` — صفحه‌ی فرود فارسی RTL با انتخاب حوزه + تولید نمونه
- `run_demo.bat` — اجرای محلی سرور
- محافظت: سقف ۳ درخواست/IP در روز؛ CORS باز برای جاسازی در سایت
- **وضعیت: در حال ارتقا** — مقاله‌ی دمو باید «عین مقاله‌ی تلگرام» شود
  (استفاده از همان `persian_writer.md` + `render.py`)

## ۴. دیپلوی روی Railway ✅ زنده
- CLI: `@railway/cli` نصب شد؛ لاگین: `<حساب Railway شما>`
- پروژه: `seo-demo` (id: 40da1d2b-355b-48b4-b1f8-b1de7d6d5bbf)
- **آدرس عمومی: https://seo-demo-production.up.railway.app**
- متغیر محیطی: `GEMINI_API_KEY` روی سرویس ست شده
- بیلدر: railpack (نه nixpacks) — از `requirements.txt` ریشه نصب می‌کند
- **درسِ مهم:** railpack فایل `requirements.txt` ریشه را نصب می‌کند؛ باید
  سبک بماند تا تضاد نسخه (supabase/realtime ↔ pydantic) build را نشکند
- دیپلوی مجدد: `railway up --detach` (پروکسی VPN را در env ست کن)

## ۵. فایل‌های دیپلوی
- `requirements.txt` — سبکِ دمو (fastapi, uvicorn, google-generativeai,
  pydantic, pydantic-settings, PyYAML, httpx) ← همین را Railway نصب می‌کند
- `requirements-agent.txt` — وابستگی‌های کاملِ ایجنت (اجرای محلی)
- `requirements-demo.txt` — نسخه‌ی سبک (نگه‌داری‌شده برای مرجع)
- `Procfile` — `web: uvicorn src.demo_api:app --host 0.0.0.0 --port $PORT`
- `nixpacks.toml` — (railpack نادیده می‌گیرد؛ بی‌اثر ولی بی‌ضرر)
- `.railwayignore` — `.env`، venv، `*.bat`، `*.zip` آپلود نمی‌شوند
- `DEPLOY-RAILWAY.md` — راهنمای دیپلوی
- `EMBED-WORDPRESS.md` — راهنمای جاسازی در وردپرس

## ۶. جاسازی در سایت (sagharnazari.ir)
- روش: iframe به `https://seo-demo-production.up.railway.app` در یک برگه
- لینک هدر: «دموی تولید مقاله سئو» → برگه‌ی `/seo-demo`
- **نکته‌ی باز:** آیا Railway از ایرانِ بدون VPN باز می‌شود؟ (باید با گوشی تست شود؛
  اگر بلاک بود → VPS اروپایی)

## ۷. کشفِ آدرس ورود وردپرس
- `/wp-admin/` و `/wp-login.php` توسط افزونه‌ی امنیتی مخفی شده‌اند
- **آدرس واقعی ورود: https://sagharnazari.ir/login → /nitlogin/**
- مشکل VPN نبود (با IP ایران و خارجی یکسان بود)

## ۸. کارهای باز
- [ ] ارتقای مقاله‌ی دمو به «عین مقاله‌ی تلگرام» (در حال انجام)
- [ ] آیدی اینستاگرام برای دکمه‌ی «دریافت نسخه‌ی کامل» در `demo/index.html`
- [ ] تست باز شدن دمو از ایرانِ بدون VPN
- [ ] فعال‌سازی Billing جمینای (برای دموی عمومی — سقف رایگان ۲۰/روز کم است)
- [ ] بخش multi-tenant برای مشتری‌های متعدد (تلگرام هر مشتری از دیتابیس)

## قراردادهای امنیتی (تغییرناپذیر)
- فایل `.env` هرگز نمایش داده نشود
- مقاله‌ی قدیمی‌تر از ۵ روز تولید نشود
- مقاله پیش از ارسال به تلگرام اعتبارسنجی شود
- کلید Gemini فقط در `.env`/متغیر محیطی — هرگز چاپ نشود
