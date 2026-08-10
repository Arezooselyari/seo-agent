@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo حذف task قدیم...
schtasks /delete /tn "PersianAI-CheckAndRun" /f 2>nul

echo ایجاد task جدید...
schtasks /create /tn "PersianAI-CheckAndRun" /tr "C:\Users\ASUS\AppData\Local\Programs\Python\Python312\python.exe -m src.run_with_check" /sc daily /st 10:00 /ri 15 /du 01:00 /rl highest /f /it

if %errorlevel% equ 0 (
    echo.
    echo ✅ Task ایجاد شد:
    echo    زمان: هر روز 10:00 صبح
    echo    تکرار: هر 15 دقیقه برای 60 دقیقه
    echo    دستور: python -m src.run_with_check
) else (
    echo ❌ خطا: این فایل را با "Run as Administrator" اجرا کنید
)

pause
