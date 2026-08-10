@echo off
chcp 65001 >nul

echo ایجاد Task Scheduler...
echo.

REM حذف task اگر ماقبل وجود داشت
schtasks /delete /tn "PersianAI-CheckAndRun" /f >nul 2>&1

REM ایجاد task جدید
schtasks /create /tn "PersianAI-CheckAndRun" /tr "cd D:\prjcluade && python -m src.run_with_check" /sc daily /st 10:00 /ri 15 /du 01:00 /rl highest /f

if %errorlevel% equ 0 (
    echo.
    echo ✅ Task Scheduler تنظیم شد:
    echo    نام: PersianAI-CheckAndRun
    echo    شروع: هر روز ساعت 10:00 صبح
    echo    تکرار: هر 15 دقیقه برای 60 دقیقه
    echo    دستور: python -m src.run_with_check
) else (
    echo.
    echo ❌ خطا در تنظیم Task Scheduler
    echo    مطمئن شوید که به‌عنوان Administrator اجرا کردید
)

pause
