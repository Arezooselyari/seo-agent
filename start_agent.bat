@echo off
:: ایجنت تولید محتوای فارسی AI
:: برای اجرای خودکار: این فایل را در Startup folder ویندوز کپی کن
:: آدرس Startup: shell:startup را در Run بزن

cd /d D:\prjcluade
set PYTHONIOENCODING=utf-8

echo [%date% %time%] ایجنت شروع شد >> logs\startup.log

"C:\Users\ASUS\AppData\Local\Programs\Python\Python312\pythonw.exe" -m src.scheduler
