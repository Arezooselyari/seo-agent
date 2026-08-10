@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title ایجنت هوش مصنوعی — نصب و راه‌اندازی

:: ============================================================
::  ایجنت تولید محتوای SEO فارسی — ویزارد نصب اولیه
::  این فایل را یک‌بار اجرا کن تا همه‌چیز تنظیم شود.
:: ============================================================

color 0B
echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║     ایجنت تولید محتوای SEO فارسی — نصب اولیه      ║
echo  ╚══════════════════════════════════════════════════════╝
echo.

:: ----------------------------------------------------------
:: ۱) پیدا کردن Python
:: ----------------------------------------------------------
echo  [1/6] بررسی Python ...
set "PYTHON="
for %%p in (
    python
    py
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\python.exe"
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\python.exe"
    "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python310\python.exe"
) do (
    if not defined PYTHON (
        %%p --version >nul 2>&1
        if !errorlevel! equ 0 set "PYTHON=%%~p"
    )
)

if not defined PYTHON (
    echo.
    echo  ❌ Python پیدا نشد!
    echo     لطفاً Python 3.10 یا بالاتر را از python.org نصب کنید.
    echo     سپس این فایل را دوباره اجرا کنید.
    echo.
    pause
    exit /b 1
)
echo     ✅ Python یافت شد: %PYTHON%

:: ----------------------------------------------------------
:: ۲) تنظیم پوشه پروژه
:: ----------------------------------------------------------
echo.
echo  [2/6] تنظیم مسیر پروژه ...
set "PROJECT_DIR=%~dp0"
:: حذف backslash انتهایی
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
echo     ✅ مسیر پروژه: %PROJECT_DIR%

:: ----------------------------------------------------------
:: ۳) دریافت اطلاعات از کاربر
:: ----------------------------------------------------------
echo.
echo  [3/6] اطلاعات سایت و API
echo  ─────────────────────────────────────────────────
echo.

set /p "SITE_NAME=  نام سایت شما (مثلاً: علی احمدی): "
set /p "SITE_URL=  آدرس سایت (مثلاً: https://example.ir): "
set /p "SITE_CATEGORY=  آدرس دسته‌بندی هوش مصنوعی (مثلاً: https://example.ir/category/ai): "
echo.
set /p "GEMINI_KEY=  کلید Gemini API (از ai.google.dev): "
echo.
set /p "TELEGRAM_TOKEN=  توکن ربات تلگرام (از @BotFather): "
set /p "TELEGRAM_CHAT=  Chat ID تلگرام (از @userinfobot): "
echo.
set /p "PEXELS_KEY=  کلید Pexels API (از pexels.com/api — رایگان): "
echo.
set /p "SUPABASE_URL=  آدرس Supabase (از داشبورد supabase.com): "
set /p "SUPABASE_KEY=  کلید Supabase (service_role key): "
echo.
set /p "ARTICLES_PER_DAY=  چند مقاله در روز؟ (پیشنهاد: 1 یا 2): "
if "!ARTICLES_PER_DAY!"=="" set "ARTICLES_PER_DAY=1"
set /p "RUN_HOUR=  ساعت اجرای روزانه؟ (مثلاً: 09:00): "
if "!RUN_HOUR!"=="" set "RUN_HOUR=09:00"

:: ----------------------------------------------------------
:: ۴) ساخت فایل .env
:: ----------------------------------------------------------
echo.
echo  [4/6] ساخت فایل تنظیمات ...

(
echo GEMINI_API_KEY=!GEMINI_KEY!
echo TELEGRAM_BOT_TOKEN=!TELEGRAM_TOKEN!
echo TELEGRAM_CHAT_ID=!TELEGRAM_CHAT!
echo PEXELS_API_KEY=!PEXELS_KEY!
echo SUPABASE_URL=!SUPABASE_URL!
echo SUPABASE_KEY=!SUPABASE_KEY!
) > "%PROJECT_DIR%\.env"

:: به‌روزرسانی config.yaml
powershell -Command ^
  "$cfg = Get-Content '%PROJECT_DIR%\config.yaml' -Raw; " ^
  "$cfg = $cfg -replace 'site_name:.*', 'site_name: \"!SITE_NAME!\"'; " ^
  "$cfg = $cfg -replace 'site_url:.*', 'site_url: \"!SITE_URL!\"'; " ^
  "$cfg = $cfg -replace 'site_category_url:.*', 'site_category_url: \"!SITE_CATEGORY!\"'; " ^
  "$cfg = $cfg -replace 'articles_per_run:.*', 'articles_per_run: !ARTICLES_PER_DAY!'; " ^
  "$cfg = $cfg -replace 'run_time:.*', 'run_time: \"!RUN_HOUR!\"'; " ^
  "Set-Content '%PROJECT_DIR%\config.yaml' $cfg -Encoding UTF8"

echo     ✅ فایل .env ساخته شد
echo     ✅ config.yaml به‌روز شد

:: ----------------------------------------------------------
:: ۵) نصب کتابخانه‌های Python
:: ----------------------------------------------------------
echo.
echo  [5/6] نصب کتابخانه‌های مورد نیاز ...
echo     (ممکن است چند دقیقه طول بکشد)
echo.

"%PYTHON%" -m pip install -r "%PROJECT_DIR%\requirements-agent.txt" --quiet
if !errorlevel! neq 0 (
    echo  ❌ خطا در نصب کتابخانه‌ها. لطفاً اینترنت را بررسی کنید.
    pause
    exit /b 1
)
echo     ✅ همه کتابخانه‌ها نصب شدند

:: ----------------------------------------------------------
:: ۶) تنظیم Task Scheduler
:: ----------------------------------------------------------
echo.
echo  [6/6] تنظیم اجرای خودکار روزانه ...

:: ساخت bat اجرایی برای این مشتری (با مسیر و Python درست)
(
echo @echo off
echo chcp 65001 ^>nul
echo cd /d "%PROJECT_DIR%"
echo set PYTHONIOENCODING=utf-8
echo.
echo :: پروکسی VPN -- اگر VPN دارید این خطوط فعال بمانند
echo set "PROXY="
echo for /f "tokens=2,*" %%%%a in ^('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer 2^^^>nul'^) do set "PROXY=%%%%b"
echo if defined PROXY ^(
echo     set "HTTP_PROXY=http://%%PROXY%%"
echo     set "HTTPS_PROXY=http://%%PROXY%%"
echo     set "NO_PROXY=localhost,127.0.0.1,::1,.local,*.supabase.co,supabase.co"
echo ^)
echo.
echo "%PYTHON%" -m src.run_with_check ^>^> "%PROJECT_DIR%\agent_log.txt" 2^>^&1
) > "%PROJECT_DIR%\run_agent.bat"

:: حذف task قدیمی
schtasks /delete /tn "PersianAI-Agent" /f >nul 2>&1

:: ایجاد task جدید
schtasks /create ^
  /tn "PersianAI-Agent" ^
  /tr "\"%PROJECT_DIR%\run_agent.bat\"" ^
  /sc daily /st %RUN_HOUR% ^
  /ri 15 /du 01:00 ^
  /rl highest /f >nul 2>&1

if !errorlevel! equ 0 (
    echo     ✅ Task Scheduler تنظیم شد: هر روز ساعت !RUN_HOUR!
) else (
    echo     ⚠️  Task Scheduler نیاز به دسترسی Admin دارد.
    echo        فایل setup_wizard.bat را راست‌کلیک کرده و "Run as administrator" بزنید.
)

:: ----------------------------------------------------------
:: پایان
:: ----------------------------------------------------------
echo.
echo  ╔══════════════════════════════════════════════════════╗
echo  ║              ✅ نصب با موفقیت انجام شد              ║
echo  ╠══════════════════════════════════════════════════════╣
echo  ║                                                      ║
echo  ║  • اجرای دستی:   launcher.bat را دابل‌کلیک کنید     ║
echo  ║  • اجرای خودکار: هر روز ساعت !RUN_HOUR! به‌طور خودکار  ║
echo  ║  • وضعیت:        agent_status.bat                    ║
echo  ║  • مقالات در:    تلگرام شما                          ║
echo  ║                                                      ║
echo  ╚══════════════════════════════════════════════════════╝
echo.
pause
