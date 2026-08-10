@echo off
chcp 65001 >nul
title ایجنت هوش مصنوعی — تنظیمات

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

:: پیدا کردن Python
set "PYTHON="
for %%p in (python py) do (
    if not defined PYTHON (
        %%p --version >nul 2>&1
        if errorlevel 0 if not errorlevel 1 set "PYTHON=%%~p"
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

if not defined PYTHON (
    echo ❌ Python پیدا نشد. ابتدا setup_wizard.bat را اجرا کنید.
    pause
    exit /b 1
)

set PYTHONIOENCODING=utf-8
cd /d "%PROJECT_DIR%"
"%PYTHON%" -m src.config_editor_cli
