@echo off
REM تولیدِ روزانه‌ی یک مقاله: انتخابِ موضوع از RSS -> نگارش -> ذخیره به‌عنوان pending
cd /d "D:\prjcluade\seo-agent"
if not exist logs mkdir logs
set PYTHONIOENCODING=utf-8
REM Gemini/OpenRouter در این منطقه مسدودند و به پروکسی نیاز دارند؛ Task Scheduler
REM نشستِ تازه می‌سازد و پروکسیِ نشستِ کاربر را به ارث نمی‌برد. پورت را هاردکد نکن —
REM V2Ray هر بار ممکن است پورت دیگری بگیرد. از همان جای رجیستری بخوان که VPN می‌نویسد.
REM پیش‌نیاز: برنامه‌ی VPN/پروکسی باید موقعِ اجرا روشن باشد (auto-start on boot).
call "%~dp0set_proxy.bat"
python -m src.generate_daily >> logs\scheduler_generate.log 2>&1
