# راهنمای سیستم ارزیابی و تایید مقالات

## 📖 نمای کلی

سیستم ارزیابی مقالات SEO دو مورد انجام می‌دهد:

1. **خودکار:** پس از تولید مقاله، اگر امتیاز ≥ 90، به تلگرام ارسال می‌شود
2. **دستی:** داشبورد وب‌ای برای دیدن و تایید مقالات

## ⚙️ تنظیمات

### 1. متغیرهای محیطی (.env)

اطمینان حاصل کنید که `config/.env` دارای موارد زیر است:

```env
# Claude API (قبلاً تنظیم شده)
ANTHROPIC_API_KEY=sk-ant-...

# تلگرام (لازم برای اطلاع‌رسانی)
TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN_HERE
TELEGRAM_CHAT_ID=YOUR_CHAT_ID_HERE
```

**چگونه bot token و chat ID را کسب کنم؟**

1. `@BotFather` را در تلگرام پیدا کنید
2. `/newbot` درخواست کنید و یک bot جدید بسازید
3. Token را کپی کنید و در .env قرار دهید
4. Bot خود را شروع کنید و `@userinfobot` را پیام دهید تا Chat ID شما را بفهمید

### 2. تنظیمات config

`config/settings.yaml` حاوی:

```yaml
evaluation:
  approval_threshold: 90          # حداقل امتیاز برای تایید
  approval_interval_seconds: 300  # بررسی هر 5 دقیقه
```

## 🚀 راه‌اندازی

### گزینه 1: اجرای یک‌بار (تست)

```bash
cd D:\prjcluade\seo-agent
python test_evaluation.py
```

خروجی:
```
🆔 مقاله #1
   📌 عنوان: درباره‌ی...
   ⭐ امتیاز SEO: 92/100
   🎯 توصیه: approve
   ✅ آماده برای ارسال به تلگرام

📊 نتایج ارزیابی:
   ✅ تایید شده: 1
   ⚠️ نیاز به بررسی: 0
```

### گزینه 2: اجرای برای صورت بندی (Scheduled)

Windows Task Scheduler یا APScheduler استفاده کنید:

```bash
# منظم اجرا کنید:
python -m seo_agent.src.evaluate_and_sync
```

یا یک Task ایجاد کنید:

```powershell
$TaskName = "SEO-Evaluate-Articles"
$Action = New-ScheduledTaskAction -Execute "python" `
    -Argument "-m seo_agent.src.evaluate_and_sync" `
    -WorkingDirectory "D:\prjcluade\seo-agent"
$Trigger = New-ScheduledTaskTrigger -AtStartup
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger
```

### گزینه 3: داشبورد وب (تایید دستی)

```bash
cd D:\prjcluade\seo-agent
python -m src.web_server
```

سپس به `http://localhost:5000` بروید و:

- 📊 تمام مقالات pending را ببینید
- ⭐ امتیاز SEO برای هر کدام را مشاهده کنید
- ✅ دکمه‌های Approve/Reject/Cancel را کلیک کنید

## 🔄 جریان کاری

### جریان کاری خودکار:

```
SEO-Agent تولید مقاله
        ↓
Evaluator ارزیابی می‌کند
        ↓
  score >= 90?
   /         \
  YES        NO
  ↓          ↓
Telegram   needs_review
 Alert     (وضعیت DB)
  ↓
User clicks
 Approve/Reject
  ↓
DB Updated
```

### جریان کاری دستی:

```
Open Dashboard
(http://localhost:5000)
        ↓
View pending articles
        ↓
Review score & preview
        ↓
Click Approve/Reject
        ↓
DB Updated
```

## 📊 وضعیت‌های مقاله

| وضعیت | معنی | عمل |
|--------|------|------|
| `pending` | منتظر اولین ارزیابی | سیستم بررسی می‌کند |
| `approved` | تایید برای انتشار | آماده برای WP |
| `rejected` | ردّ شده توسط کاربر | نیاز به بازنویسی |
| `needs_review` | امتیاز < 90 | منتظر بهبود یا تایید دستی |
| `published` | منتشر شده در WP | نهایی |

## 📝 لاگ‌ها

ارزیابی‌های انجام‌شده در `logs/evaluations.log` ذخیره می‌شوند:

```
2024-12-01 10:30:45 - evaluator - INFO - [2024-12-01T10:30:45...] Article #1: score=92, action=approve
2024-12-01 10:31:12 - evaluator - INFO - [2024-12-01T10:31:12...] Article #2: score=78, action=needs_review
```

## 🐛 تشخیص خرابی

### مشکل: پیام تلگرام ارسال نمی‌شود

**راه حل:**
1. `TELEGRAM_BOT_TOKEN` و `TELEGRAM_CHAT_ID` را در `.env` بررسی کنید
2. اطمینان حاصل کنید bot به chat اضافه شده است
3. `logs/evaluations.log` را برای errors بررسی کنید

### مشکل: dashboard کار نمی‌کند

**راه حل:**
```bash
pip install flask
python -m src.web_server
```

سپس مرورگر را به `http://localhost:5000` ببرید.

### مشکل: هیچ مقاله برای ارزیابی وجود ندارد

**راه حل:**
اولاً مطمئن شوید SEO-Agent مقالات تولید کرده است:

```bash
python test_evaluation.py
```

اگر خالی است، تیغه generator را اجرا کنید:

```bash
python -m src.main generate
```

## 🔌 ادغام با SEO-Agent

برای اجرای خودکار بعد از تولید مقاله:

**src/main.py میں تغییر:**

```python
from . import evaluate_and_sync

# ... after writing article ...
article = writer.write_article(brief)
article_id = db.save_article(conn, topic, article)

# ✅ خط جدید: سیستم ارزیابی را شروع کنید
import asyncio
asyncio.run(evaluate_and_sync.async_evaluate_pending())
```

## 📚 ماژول‌ها

### `evaluator.py`
- `get_pending_articles()` - لیست مقالات pending
- `evaluate_article()` - ارزیابی یک مقاله
- `should_approve()` - تصمیم: تایید یا خیر?

### `telegram_approver.py`
- `TelegramApprover` - کلاس برای ارسال/دریافت پیام‌های تلگرام
- `send_approval_message()` - اطلاع‌رسانی کاربر

### `evaluate_and_sync.py`
- `evaluate_pending()` - ارزیابی تمام مقالات
- `run_once()` - یک بار اجرا
- `run_daemon()` - اجرای مرتب

### `web_server.py`
- داشبورد وب برای دیدن/تایید مقالات
- API endpoints برای درخواست‌های AJAX

## ✅ آزمایش

```bash
# 1. تست ارزیابی
python test_evaluation.py

# 2. تست داشبورد
python -m src.web_server

# 3. تست Telegram (اگر bot تنظیم شده است)
python -m src.evaluate_and_sync
```

## ❓ سوال‌های متداول

**س: آیا مقالات با score < 90 تایید می‌شوند؟**  
ج: خیر. آن‌ها به `needs_review` تغییر می‌کنند. شما می‌توانید از داشبورد دستی تایید کنید.

**س: آیا می‌توانم threshold را تغییر دهم؟**  
ج: بله! `config/settings.yaml` میں `approval_threshold` را تغییر دهید.

**س: آیا می‌توانم Telegram را غیرفعال کنم؟**  
ج: بله! `config/.env` میں `TELEGRAM_BOT_TOKEN` و `TELEGRAM_CHAT_ID` را خالی کنید. سیستم با تنبیہات داشبورد کار خواهد کرد.

**س: آیا سیستم وردپرس‌را مباشرتا انتشار می‌دهد؟**  
ج: خیر. مقالات `approved` شده، آماده‌ی انتشار هستند، ولی انتشار توسط یک سرویس دیگر انجام می‌شود.

---

**نسخه:** 1.0  
**آخرین بروزرسانی:** 2024-12-01
