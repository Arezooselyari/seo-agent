# استقرار روی VPS

## 1. آماده‌سازی سرور

```bash
sudo adduser --system --group chatbot
sudo mkdir -p /opt/chatbot
sudo chown chatbot:chatbot /opt/chatbot
```

نصب پیش‌نیازها: `python3.11`, `python3.11-venv`, `nginx`, `certbot`, `python3-certbot-nginx`.

## 2. انتقال کد

کل پوشه‌ی `chatbot/` (و فایل‌های هم‌سطح موردنیازش مثل `requirements.txt`) را به `/opt/chatbot` کپی کن، سپس:

```bash
cd /opt/chatbot
python3.11 -m venv venv
./venv/bin/pip install -r chatbot/requirements.txt
```

`.env` واقعی (با مقادیر کامل `GEMINI_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`,
`CHATBOT_TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `ADMIN_TELEGRAM_CHAT_ID`,
`WIDGET_ALLOWED_ORIGINS`, و `APP_BASE_URL=https://chatbot.sagharnazari.ir`) را
مستقیماً روی سرور در `chatbot/.env` بساز — هرگز از طریق git/کانال‌های عمومی منتقل نکن.

## 3. مایگریشن دیتابیس

محتوای `chatbot/migrations/002_chatbot.sql` را یک‌بار در Supabase SQL Editor اجرا کن.

## 4. DNS

یک رکورد A برای `chatbot.sagharnazari.ir` به‌سمت IP سرور بساز.

## 5. systemd

```bash
sudo cp chatbot/deploy/chatbot.service /etc/systemd/system/chatbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now chatbot
sudo systemctl status chatbot
```

## 6. Nginx + TLS

```bash
sudo cp chatbot/deploy/nginx_chatbot.conf /etc/nginx/sites-available/chatbot
sudo ln -s /etc/nginx/sites-available/chatbot /etc/nginx/sites-enabled/chatbot
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d chatbot.sagharnazari.ir
```

## 7. تنظیم webhook تلگرام

```bash
cd /opt/chatbot
./venv/bin/python -m chatbot.scripts.set_telegram_webhook set
```

بررسی با `getWebhookInfo` که هیچ خطای backlog نباشد.

## 8. بارگذاری اولیه RAG

```bash
./venv/bin/python -m chatbot.scripts.ingest_now
```

برای بروزرسانی دوره‌ای محتوا، یک cron job شبانه برای همین دستور اضافه کن:

```cron
0 3 * * * /opt/chatbot/venv/bin/python -m chatbot.scripts.ingest_now >> /var/log/chatbot_ingest.log 2>&1
```

## 9. تست نهایی

- `curl -I https://chatbot.sagharnazari.ir/chat` → باید 200 با TLS معتبر برگرداند
- پیام به بات تلگرام واقعی → باید پاسخ بدهد
- `/widget.js?site=sagharnazari` روی یک صفحه‌ی واقعی سایت تست شود
- `systemctl kill chatbot` → سرویس باید خودش دوباره بالا بیاید (`Restart=on-failure`)
