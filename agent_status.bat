@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
title ایجنت هوش مصنوعی — وضعیت

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
        if not defined PYTHON (
            if exist %%p set "PYTHON=%%~p"
        )
    )
)

color 0E
cls
echo.
echo  ╔══════════════════════════════════════════════════════════════╗
echo  ║           ایجنت هوش مصنوعی — داشبورد وضعیت                ║
echo  ╚══════════════════════════════════════════════════════════════╝
echo.

:: تاریخ و ساعت
for /f "tokens=1-3 delims=/ " %%a in ("%date%") do set "TODAY=%%a/%%b/%%c"
for /f "tokens=1-2 delims=: " %%a in ("%time%") do set "NOW=%%a:%%b"
echo  تاریخ: %TODAY%    ساعت: %NOW%
echo.
echo  ─────────────────────────────────────────────────────────────

:: وضعیت Task Scheduler
echo.
echo  [زمانبندی خودکار]
schtasks /query /tn "PersianAI-Agent" /fo LIST 2>nul | findstr /i "Next Run Time Status"
if !errorlevel! neq 0 (
    schtasks /query /tn "PersianAI-CheckAndRun" /fo LIST 2>nul | findstr /i "Next Run Time Status"
    if !errorlevel! neq 0 echo   ⚠️  Task Scheduler تنظیم نشده — setup_wizard.bat را اجرا کنید
)

:: لاگ آخرین اجرا
echo.
echo  ─────────────────────────────────────────────────────────────
echo  [آخرین اجرا — ۲۰ خط آخر لاگ]
echo.
if exist "%PROJECT_DIR%\agent_log.txt" (
    powershell -Command "Get-Content '%PROJECT_DIR%\agent_log.txt' -Tail 20"
) else (
    echo   هنوز هیچ اجرایی انجام نشده.
)

:: پوشه outputs
echo.
echo  ─────────────────────────────────────────────────────────────
echo  [مقالات تولیدشده]
if exist "%PROJECT_DIR%\outputs\" (
    set "COUNT=0"
    for %%f in ("%PROJECT_DIR%\outputs\*.html") do set /a COUNT+=1
    echo   تعداد مقالات HTML: !COUNT! فایل
    echo.
    echo   ۵ مقاله آخر:
    dir "%PROJECT_DIR%\outputs\*.html" /b /o-d 2>nul | findstr "." | powershell -Command "$input | Select-Object -First 5 | ForEach-Object { '   • ' + $_ }"
) else (
    echo   پوشه outputs وجود ندارد.
)

:: حجم دیسک
echo.
echo  ─────────────────────────────────────────────────────────────
echo  [فضای مصرفی پروژه]
powershell -Command ^
  "$size = (Get-ChildItem '%PROJECT_DIR%' -Recurse -ErrorAction SilentlyContinue | " ^
  "Where-Object {$_.FullName -notmatch 'venv|__pycache__'} | " ^
  "Measure-Object -Property Length -Sum).Sum; " ^
  "Write-Host ('   ' + [math]::Round($size/1MB, 1) + ' MB')"

echo.
echo  ─────────────────────────────────────────────────────────────
echo.
echo  دکمه‌ها:
echo    [L] اجرای دستی همین الان    [Q] خروج
echo.
choice /c LQ /n /m "  انتخاب: "
if !errorlevel! equ 1 (
    call "%PROJECT_DIR%\launcher.bat"
) else (
    exit /b 0
)
