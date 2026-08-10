# چک‌لیست ادغام سیستم ارزیابی

## ✅ ماژول‌های ایجادشده

- [x] **`src/evaluator.py`** — ارزیابی مقالات (۶۳ خط)
- [x] **`src/telegram_approver.py`** — ارسال پیام تلگرام (۱۵۰+ خط)
- [x] **`src/evaluate_and_sync.py`** — Scheduler اصلی (۱۸۰+ خط)
- [x] **`src/web_server.py`** — داشبورد وب (۳۰۰+ خط)
- [x] **`test_evaluation.py`** — اسکریپت تست

## 📋 مراحل ادغام

### مرحله 1️⃣: تنظیم .env

**فایل:** `config/.env`

```env
# تأیید کنید اینها موجود هستند:
TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN_HERE
TELEGRAM_CHAT_ID=YOUR_CHAT_ID_HERE
```

**چک کردن:**
```bash
cat config/.env | grep TELEGRAM
```

### مرحله 2️⃣: نصب وابستگی‌ها

**Flask** برای داشبورد:
```bash
pip install flask
```

**python-telegram-bot** برای تلگرام:
```bash
pip install python-telegram-bot
```

**تأیید:**
```bash
python -c "import flask, telegram; print('OK')"
```

### مرحله 3️⃣: تست سیستم

**تست 1: لیست مقالات pending**
```bash
python test_evaluation.py
```

**تست 2: داشبورد**
```bash
python -m src.web_server
# سپس به http://localhost:5000 بروید
```

**تست 3: Scheduler**
```bash
python -m src.evaluate_and_sync
# باید "شروع چرخه‌ی ارزیابی" نمایش دهد
```

### مرحله 4️⃣: ادغام خودکار (اختیاری)

اگر می‌خواهید ارزیابی **بعد از تولید مقاله** اجرا شود:

**فایل:** `src/main.py`

```python
# بعد از save_article:
import asyncio
from . import evaluate_and_sync

article_id = db.save_article(conn, topic, article)

# ✅ افزودن این خطوط:
print("[main] ارزیابی مقاله...")
asyncio.run(evaluate_and_sync.async_evaluate_pending())
```

### مرحله 5️⃣: Scheduler دوره‌ای (اختیاری)

برای بررسی منظم هر ۵ دقیقه:

**Windows Task Scheduler:**

```powershell
# PowerShell (باید Admin باشد)

$TaskName = "SEO-Evaluate-Articles"
$TaskPath = "\SEO-Agent\"
$Action = New-ScheduledTaskAction `
    -Execute "python" `
    -Argument "-m seo_agent.src.evaluate_and_sync" `
    -WorkingDirectory "D:\prjcluade\seo-agent"

$Trigger = New-ScheduledTaskTrigger -AtStartup
$Trigger.RepetitionInterval = (New-TimeSpan -Minutes 5)
$Trigger.RepetitionDuration = (New-TimeSpan -Days 999)

Register-ScheduledTask -TaskName $TaskName `
    -Action $Action -Trigger $Trigger `
    -RunLevel Highest
```

**تأیید:**
```powershell
Get-ScheduledTask -TaskName "SEO-Evaluate-Articles"
```

## 🔍 نقاط بررسی

### Database
- [ ] `articles` جدول موجود است
- [ ] `payload` جدول دارای `seo_grade` است
- [ ] `status` ستون دارای مقادیر: pending, approved, rejected, needs_review

```sql
-- بررسی:
SELECT id, title_seo, status, payload FROM articles LIMIT 1;
```

### Telegram
- [ ] Bot Token معتبر است
- [ ] Chat ID صحیح است
- [ ] Bot به chat اضافه شده است

```bash
# تست bot:
python -c "from src.config import env; print(f'Token: {env(\"TELEGRAM_BOT_TOKEN\")}')"
```

### فایل‌ها
- [ ] `logs/` پوشه موجود است (خودکار ایجاد می‌شود)
- [ ] `config/settings.yaml` دارای `telegram` و `evaluation` است
- [ ] `config/.env` موجود است

## 🚦 وضعیت‌ها

```
pending (تولید شده)
   ↓
   ├─→ score >= 90 → Telegram Alert → User Clicks → approved
   └─→ score < 90  → needs_review (منتظر کاربر)
```

## 📊 مثال جریان

```
1. SEO-Agent تولید مقاله
2. save_article() → status = 'pending'
3. [خودکار] evaluate_and_sync.py اجرا می‌شود
4. Score = 92 (> 90)
5. Telegram پیام ارسال: "مقاله #5 برای تایید آماده"
6. کاربر ✅ تایید کلیک می‌کند
7. status = 'approved' (DB)
8. [بعدی] WP integration برای انتشار
```

## 🐛 عیب‌یابی

| مسئله | سبب | راه حل |
|--------|------|----------|
| پیام تلگرام ارسال نمی‌شود | Token/ChatID نامعتبر | `.env` را بررسی کنید |
| Evaluator crash می‌شود | DB lock | `logs/evaluations.log` را بررسی کنید |
| Dashboard نمایش نمی‌دهد | Port 5000 مشغول | پورت دیگری را امتحان کنید |
| هیچ مقاله pending نیست | Generator نتولید کرده | `python -m src.main generate` اجرا کنید |

## 📚 فایل‌های راهنما

- **`EVALUATION_GUIDE.md`** — راهنمای کامل استفاده
- **`test_evaluation.py`** — اسکریپت تست سریع
- **`logs/evaluations.log`** — تاریخچه‌ی ارزیابی‌ها

## ✨ ویژگی‌های اضافی (آینده)

- [ ] Email notifications
- [ ] Slack integration
- [ ] Database history/analytics
- [ ] Feedback loop (بهبود score prediction)
- [ ] Batch re-evaluation tool
- [ ] API for external systems

---

## ✅ آزمایش نهایی

```bash
# مرحله‌ی ۱: Database بررسی
python test_evaluation.py

# مرحله‌ی ۲: Dashboard
python -m src.web_server &
# سپس http://localhost:5000 (Ctrl+C برای خروج)

# مرحله‌ی ۳: Scheduler
python -m src.evaluate_and_sync

# اگر مرحله‌ی ۱-۳ کار کردند ✅ نصب کامل است!
```

---

**بله! سیستم ارزیابی مقالات آماده است! 🎉**
