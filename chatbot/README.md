# چت‌بات هوشمند فارسی

هسته‌ی مرکزی (RAG + حافظه + ابزار) برای سه کانال: تلگرام (webhook)، صفحه‌ی
`/chat`، و ویجت قابل‌جاسازی. مستقل از پایپ‌لاین تولید محتوای موجود در `src/`
(کانفیگ، `.env`، و دیتابیس Supabase جدا — هرچند در همان پروژه‌ی Supabase).

## راه‌اندازی محلی

```bash
cd chatbot
python -m venv venv
./venv/Scripts/activate   # ویندوز
pip install -r requirements.txt
```

`.env.example` را به `.env` کپی کن و مقادیر زیر را پر کن:

- `GEMINI_API_KEY`
- `SUPABASE_URL` / `SUPABASE_KEY` (سرویس‌رول، همان پروژه‌ی Supabase موجود)
- `CHATBOT_TELEGRAM_BOT_TOKEN` (بات عمومی جدید، جدا از بات ادمین در `src/bot.py`)
- `TELEGRAM_WEBHOOK_SECRET`
- `ADMIN_TELEGRAM_CHAT_ID` (برای اطلاع‌رسانی لید جدید)
- `WIDGET_ALLOWED_ORIGINS` (دامنه‌هایی که اجازه‌ی استفاده از ویجت دارند)
- `APP_BASE_URL`

سپس محتوای `migrations/002_chatbot.sql` را یک‌بار در Supabase SQL Editor اجرا کن.

## بارگذاری اولیه‌ی محتوای RAG

```bash
python -m chatbot.scripts.ingest_now
```

## اجرای سرور

```bash
uvicorn chatbot.app.main:app --reload
```

- صفحه‌ی چت: `http://localhost:8000/chat`
- ویجت: `<script src="http://localhost:8000/widget.js?site=sagharnazari"></script>`
- وب‌هوک تلگرام: `POST /webhook/telegram`

برای تست تلگرام به‌صورت محلی از `ngrok` استفاده کن، سپس:

```bash
python -m chatbot.scripts.set_telegram_webhook set
```

## استقرار

به `deploy/deploy_notes.md` مراجعه کن (systemd + nginx + TLS روی VPS).

## ساختار

- `app/brain.py` — نقطه‌ی ورود مرکزی، هر سه کانال آن را صدا می‌زنند
- `app/llm_chat.py` — حلقه‌ی مکالمه + function calling با Gemini
- `app/rag.py` / `app/ingest_wp.py` — بازیابی و بارگذاری محتوای وردپرس
- `app/memory.py` — حافظه‌ی کوتاه‌مدت (پیام‌های اخیر) و بلندمدت (خلاصه‌ی رولینگ)
- `app/tools/` — گرفتن لید و استعلام وضعیت درخواست مشاوره
- `app/channels/` — تلگرام، صفحه‌ی چت، ویجت
