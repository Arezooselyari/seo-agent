# جاسازی صفحه‌ی رزرو تقویمی در وردپرس (sagharnazari.ir)

هدف: یک دکمه/لینک در سایت به نام «رزرو مشاوره» که کاربر را به صفحه‌ای می‌برد
با یک تقویم و ساعت‌های خالی — به‌جای گفت‌وگوی متنی فعلی با چت‌بات.

این صفحه بخشی از همان چت‌بات است (نه دیپلوی جدا روی Railway مثل دموی سئو):
موتورش روی همان سرور `chatbot.sagharnazari.ir` است، مسیر `/booking`.

پیش‌نیاز: مراحل ۱ تا ۳ فایل `chatbot/deploy/deploy_notes.md` باید انجام شده
باشد (چت‌بات روی سرور بالا باشد). علاوه بر آن:

1. مایگریشن جدید را یک‌بار در SQL Editor پروژه‌ی Supabase اجرا کن:
   `chatbot/migrations/003_booking.sql`
2. ساعات کاری واقعی ساغر را در `chatbot/config.yaml` بخش `booking.weekly_hours`
   ویرایش کن (الان یک مقدار پیش‌فرض placeholder است: شنبه تا چهارشنبه ۹ تا ۱۷).
3. کد جدید (`chatbot/app/...`, `chatbot/static/booking/`, `chatbot/static/fonts/`)
   را به همراه بقیه‌ی پوشه‌ی `chatbot/` روی سرور کپی کن و سرویس را ری‌استارت کن:
   ```bash
   sudo systemctl restart chatbot
   curl -I https://chatbot.sagharnazari.ir/booking   # باید 200 برگرداند
   ```

---

## گام ۱: ساخت صفحه‌ی رزرو در وردپرس

1. پیشخوان وردپرس → **برگه‌ها (Pages)** → **افزودن برگه**
2. عنوان: `رزرو مشاوره`
3. نامک (Slug/Permalink): `booking`
4. یک بلوک **HTML سفارشی (Custom HTML)** اضافه کن و این کد را بچسبان:

```html
<iframe
  src="https://chatbot.sagharnazari.ir/booking"
  style="width:100%;min-height:900px;border:0;border-radius:16px;"
  title="رزرو جلسه‌ی مشاوره"
  loading="lazy">
</iframe>
```

5. برگه را **منتشر (Publish)** کن. حالا آدرس `https://sagharnazari.ir/booking`
   صفحه‌ی رزرو را نشان می‌دهد.

## گام ۲: افزودن لینک به هدر

پیشخوان → **نمایش (Appearance)** → **فهرست‌ها (Menus)** → برگه‌ی «رزرو مشاوره»
را به منوی اصلی اضافه کن — دقیقاً مثل گام ۲ در `EMBED-WORDPRESS.md`.

## نکته‌ی موبایل

`min-height:900px` برای دسکتاپ خوب است؛ روی موبایل معمولاً ۷۰۰-۸۰۰ کافی است.

---

## توجه به چت‌بات فعلی

چت‌بات (`/chat`، ویجت `widget.js`) دست‌نخورده می‌ماند و همچنان می‌تواند لید
بگیرد (`capture_lead`) — فقط بدون تاریخ/ساعت. صفحه‌ی رزرو تقویمی یک مسیر
جدید و مکمل است، هر دو در همان جدول‌های `leads` / `consultation_requests`
ذخیره می‌شوند و در پنل ادمین/تلگرام قابل مشاهده‌اند.
