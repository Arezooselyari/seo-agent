@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title ایجنت هوش مصنوعی — در حال اجرا...

:: ============================================================
::  ایجنت تولید محتوای SEO فارسی — اجرای دستی مرئی
::  برای اجرای فوری، این فایل را دابل‌کلیک کنید.
:: ============================================================

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

:: پیدا کردن Python
set "PYTHON="
for %%p in (python py "%PROJECT_DIR%\venv\Scripts\python.exe") do (
    if not defined PYTHON (
        %%p --version >nul 2>&1
        if !errorlevel! equ 0 set "PYTHON=%%~p"
    )
)
:: fallback به مسیرهای رایج
if not defined PYTHON (
    for %%p in (
        "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\python.exe"
        "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\python.exe"
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
    ) do (
        if not defined PYTHON (
            if exist %%p set "PYTHON=%%~p"
        )
    )
)

if not defined PYTHON (
    color 0C
    echo.
    echo  ❌ Python پیدا نشد. لطفاً ابتدا setup_wizard.bat را اجرا کنید.
    pause
    exit /b 1
)

color 0B
cls
echo.
echo  ╔══════════════════════════════════════════════════════════════╗
echo  ║           ایجنت تولید محتوای SEO فارسی                     ║
echo  ╚══════════════════════════════════════════════════════════════╝
echo.

:: نمایش وقت شروع
for /f "tokens=1-3 delims=/ " %%a in ("%date%") do set "TODAY=%%a/%%b/%%c"
for /f "tokens=1-2 delims=: " %%a in ("%time%") do set "NOW=%%a:%%b"
echo  ► شروع اجرا:  %TODAY%  ساعت %NOW%
echo  ► مسیر پروژه: %PROJECT_DIR%
echo.
echo  ─────────────────────────────────────────────────────────────
echo.

:: تنظیم پروکسی VPN
set "PROXY="
for /f "tokens=2,*" %%a in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer 2>nul') do set "PROXY=%%b"
if defined PROXY (
    set "HTTP_PROXY=http://%PROXY%"
    set "HTTPS_PROXY=http://%PROXY%"
    set "NO_PROXY=localhost,127.0.0.1,::1,.local,*.supabase.co,supabase.co"
    echo  ✓ VPN/Proxy شناسایی شد: %PROXY%
    echo.
)

set PYTHONIOENCODING=utf-8
cd /d "%PROJECT_DIR%"

echo  در حال اجرا... (این پنجره را نبندید)
echo.
echo  ─────────────────────────────────────────────────────────────

:: اجرای pipeline مستقیم (نه run_with_check) تا همیشه اجرا شود
"%PYTHON%" -m src.pipeline

set EXIT_CODE=!errorlevel!
echo.
echo  ─────────────────────────────────────────────────────────────

if !EXIT_CODE! equ 0 (
    color 0A
    echo.
    echo  ✅ اجرا با موفقیت به پایان رسید!
    echo     مقالات در تلگرام شما ارسال شدند.
) else (
    color 0C
    echo.
    echo  ❌ خطایی رخ داد ^(کد: !EXIT_CODE!^)
    echo     برای جزئیات، فایل agent_log.txt را بررسی کنید.
)

echo.
for /f "tokens=1-2 delims=: " %%a in ("%time%") do set "END_TIME=%%a:%%b"
echo  ► پایان اجرا: ساعت %END_TIME%
echo.
echo  برای بستن پنجره Enter بزنید...
pause >nul
