@echo off
REM ارزیابی مقالات pending و ارسال آن‌هایی با نمره >= 90 به تلگرام
cd /d "D:\prjcluade\seo-agent"
if not exist logs mkdir logs
set PYTHONIOENCODING=utf-8
REM مدل/تلگرام در این منطقه به پروکسی نیاز دارند؛ Task Scheduler آن را از نشستِ کاربر به ارث نمی‌برد.
call "%~dp0set_proxy.bat"
python -m src.evaluate_and_sync >> logs\scheduler_eval.log 2>&1
