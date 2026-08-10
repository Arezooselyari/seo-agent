@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title دموی وب — ایجنت تولید محتوا

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

:: پیدا کردن Python
set "PYTHON="
for %%p in (python py) do (
    if not defined PYTHON (
        %%p --version >nul 2>&1
        if !errorlevel! equ 0 set "PYTHON=%%~p"
    )
)
if not defined PYTHON (
    for %%p in (
        "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python312\python.exe"
        "C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python311\python.exe"
        "C:\Python312\python.exe"
    ) do (
        if not defined PYTHON if exist %%p set "PYTHON=%%~p"
    )
)
if not defined PYTHON (
    echo ❌ Python پیدا نشد.
    pause & exit /b 1
)

:: تنظیم پروکسی VPN (چون Gemini نیاز دارد)
set "PROXY="
for /f "tokens=2,*" %%a in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer 2>nul') do set "PROXY=%%b"
if defined PROXY (
    set "HTTP_PROXY=http://%PROXY%"
    set "HTTPS_PROXY=http://%PROXY%"
    set "NO_PROXY=localhost,127.0.0.1,::1,.local,*.supabase.co,supabase.co"
)

set PYTHONIOENCODING=utf-8
cd /d "%PROJECT_DIR%"

echo.
echo  ═══════════════════════════════════════════════════
echo    دموی وب در حال اجرا...
echo    آدرس:  http://localhost:8000
echo    برای توقف: Ctrl+C
echo  ═══════════════════════════════════════════════════
echo.

"%PYTHON%" -m uvicorn src.demo_api:app --host 0.0.0.0 --port 8000
pause
