# دیپلوی دموی وب روی Railway

این راهنما دموی نسخه‌ی آزمایشی (`src/demo_api.py` + `demo/index.html`) را روی
Railway بالا می‌آورد — جایی خارج از ایران که به Gemini دسترسی دارد.

فایل‌های آماده‌شده:
- `Procfile` — دستور اجرا: uvicorn روی پورت Railway
- `nixpacks.toml` — فقط وابستگی‌های سبک (`requirements-demo.txt`) نصب می‌شود
- `requirements-demo.txt` — FastAPI + Gemini (بدون supabase/trafilatura)
- `.railwayignore` — جلوگیری از آپلود `.env`، venv و فایل‌های سنگین

---

## مرحله ۱: ورود به Railway (یک‌بار)

```powershell
railway login
```
مرورگر باز می‌شود؛ با حساب گوگل یا گیت‌هاب وارد شو. (ثبت‌نام رایگان است.)

## مرحله ۲: ساخت پروژه

در پوشه‌ی `D:\prjcluade` این را بزن:
```powershell
railway init
```
یک نام برای پروژه بگذار (مثلاً `content-demo`).

## مرحله ۳: تنظیم کلید Gemini (مهم)

دمو فقط به کلید Gemini نیاز دارد. آن را به‌صورت متغیر محیطی روی Railway بگذار
(نه در فایل — فایل `.env` آپلود نمی‌شود):
```powershell
railway variables --set "GEMINI_API_KEY=کلید_واقعی_شما"
```
> کلید را از `.env` محلی‌ات بردار و جای «کلید_واقعی_شما» بگذار.

## مرحله ۴: دیپلوی

```powershell
railway up
```
Railway کد را آپلود، build و اجرا می‌کند (حدود ۱ تا ۲ دقیقه).

## مرحله ۵: گرفتن آدرس عمومی

```powershell
railway domain
```
یک آدرس مثل `https://content-demo-production.up.railway.app` می‌دهد.
همین لینک را به مشتری‌ها می‌فرستی.

---

## به‌روزرسانی بعدی

هر وقت `demo/index.html` یا کد را عوض کردی، فقط دوباره:
```powershell
railway up
```

## نکته‌ی هزینه

پلن رایگان Railway برای شروع کافی است. اگر ترافیک بالا رفت، پلن Hobby
(حدود ۵ دلار/ماه) کفایت می‌کند. سقف ۳ درخواست در روز برای هر IP در کد فعال است
تا مصرف Gemini کنترل شود.
