# خلاصه: سیستم ارزیابی و تایید مقالات SEO

## 🎯 چه ساخت‌وساز شد؟

یک سیستم **خودکار + دستی** برای ارزیابی مقالات تولید‌شده‌ی SEO-agent:

### 1. خودکار (Telegram)
```
مقاله تولید → Score > 90? → تلگرام ارسال → کاربر کلیک → DB تغییر
```

### 2. دستی (Dashboard)
```
داشبورد وب → لیست مقالات → Review → تایید/ردّ → DB تغییر
```

## 📁 فایل‌های جدید

```
D:\prjcluade\seo-agent\
├── src/
│   ├── evaluator.py              (۶۳ خط)  ارزیابی‌کننده
│   ├── telegram_approver.py       (۱۵۰+ خط) تلگرام integration
│   ├── evaluate_and_sync.py       (۱۸۰+ خط) scheduler اصلی
│   ├── web_server.py              (۳۰۰+ خط) داشبورد وب
│   └── db.py                      (+۳۰ خط)  helper functions
│
├── config/
│   ├── settings.yaml              (+۴ خط)  تنظیمات evaluation
│   └── .env                       (موجود)  Telegram tokens
│
├── logs/
│   └── evaluations.log            (خودکار ایجاد)
│
└── EVALUATION_GUIDE.md            راهنمای کامل
```

## ⚙️ چگونه کار می‌کند؟

### سناریو ۱: Score >= 90 (Approved)
```
✅ Writer: سئو گریڈ = 92
   ↓
✅ Evaluator: چک می‌کند → 92 >= 90
   ↓
✅ Telegram: "مقاله برای تایید آماده" + ✅ Approve btn + ❌ Reject btn
   ↓
✅ User: ✅ کلیک می‌کند
   ↓
✅ Database: status = 'approved' ✓
```

### سناریو ۲: Score < 90 (Needs Review)
```
⚠️ Writer: سئو گریڈ = 75
   ↓
⚠️ Evaluator: چک می‌کند → 75 < 90
   ↓
⚠️ Dashboard: "نیاز به بررسی" بخش میں نمایش
   ↓
⚠️ User: می‌تواند دستی تایید کند یا ردّ کند
   ↓
⚠️ Database: status = 'approved' / 'rejected' (انتخاب کاربر)
```

## 🚀 شروع سریع

### 1️⃣ تنظیم (۲ دقیقه)

```bash
# Telegram tokens را در config/.env قرار دهید:
TELEGRAM_BOT_TOKEN=1234567890:ABCdEfGhIjKlMnOpQrStUvWxYz...
TELEGRAM_CHAT_ID=123456789
```

### 2️⃣ نصب وابستگی‌ها

```bash
pip install flask python-telegram-bot
```

### 3️⃣ تست

```bash
# مقالات موجود را بررسی کنید:
python test_evaluation.py

# داشبورد را باز کنید:
python -m src.web_server
# سپس http://localhost:5000
```

## 🔌 Telegram + Dashboard

### Telegram (برای notification)
```
از صورت‌بندی شامل:
- 📌 عنوان مقاله
- ⭐ نمره‌ی SEO (92/100)
- 📖 پیش‌نمایش متن
- 3 دکمه: ✅ تایید | ❌ ردّ | ⊗ لغو
```

### Dashboard (برای دیدن و تایید)
```
از صورت‌بندی شامل:
- 📊 آمار (pending, approved, needs_review)
- 📋 لیست تمام مقالات
- 🎯 هر کدام:
  - عنوان
  - نمره‌ی SEO
  - پیش‌نمایش
  - 3 دکمه
```

## 📊 Database

تغییری **نیست**. سیستم از ستون‌های موجود استفاده می‌کند:

```
articles جدول:
- id            (موجود)
- title_seo     (موجود)
- payload       (موجود → شامل seo_grade)
- status        (موجود → pending/approved/rejected/needs_review)
- created_at    (موجود)
- decided_at    (موجود)
```

## 🎛️ تنظیمات

در `config/settings.yaml`:

```yaml
evaluation:
  approval_threshold: 90          # حداقل برای تایید
  approval_interval_seconds: 300  # بررسی هر 5 دقیقه

telegram:
  bot_token: "${TELEGRAM_BOT_TOKEN}"
  chat_id: "${TELEGRAM_CHAT_ID}"
```

## 📝 استفاده

### خودکار (بعد از تولید مقاله)

اگر `src/main.py` میں این اضافه کنید:

```python
import asyncio
from . import evaluate_and_sync

article_id = db.save_article(conn, topic, article)
asyncio.run(evaluate_and_sync.async_evaluate_pending())
```

### Scheduler دوره‌ای

```bash
# ۵ دقیقه یک بار:
python -m src.evaluate_and_sync
```

یا Windows Task Scheduler (راهنما در `INTEGRATION_CHECKLIST.md`)

### داشبورد

```bash
python -m src.web_server
# http://localhost:5000
```

## 🔍 لاگ‌ها

تمام ارزیابی‌ها در `logs/evaluations.log` ثبت می‌شوند:

```
[2024-12-01T10:30:45] Article #1: score=92, action=approve
[2024-12-01T10:31:12] Article #2: score=78, action=needs_review
[2024-12-01T10:31:45] مقاله #1 برای تایید ارسال شد (تلگرام)
[2024-12-01T10:35:20] مقاله #1: APPROVED توسط user_id (تلگرام)
```

## 🎯 معیار موفقیت

✅ **سیستم موفق است اگر:**

1. **Evaluator کار می‌کند**
   ```bash
   python test_evaluation.py
   # → لیست مقالات + نمرات
   ```

2. **Dashboard کار می‌کند**
   ```bash
   python -m src.web_server
   # → http://localhost:5000 ← دکمه‌ها کار می‌کنند
   ```

3. **Telegram کار می‌کند**
   ```bash
   python -m src.evaluate_and_sync
   # → پیام تلگرام دریافت می‌شود ✅
   # → دکمه کلیک کردن DB را تغییر می‌دهد ✅
   ```

## 📚 راهنما‌ها

1. **`EVALUATION_GUIDE.md`** ← راهنمای کامل (جای‌گاه‌های خاص + troubleshooting)
2. **`INTEGRATION_CHECKLIST.md`** ← چک‌لیست تکمیل (۵ مرحله)
3. **`test_evaluation.py`** ← تست سریع

## 🎉 نتیجه

شما اکنون یک سیستم ارزیابی دارید که:

- ✅ **خودکار** مقالات را کنترل می‌کند
- ✅ **Telegram** کاربر را اطلاع می‌دهد
- ✅ **Dashboard** دیدن/تایید دستی را فراهم می‌کند
- ✅ **Database** را به‌روزرسانی می‌کند
- ✅ **Logs** کل تاریخچه را ثبت می‌کند

**آیا می‌خواهید هر یک از این ماژول‌ها را تست کنید؟ یا پرسشی دارید؟** 🚀
