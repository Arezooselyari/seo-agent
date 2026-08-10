@echo off
REM ارزیابی مقالات pending و ارسال آن‌هایی با نمره >= 90 به تلگرام
cd /d "D:\prjcluade\seo-agent"
if not exist logs mkdir logs
set PYTHONIOENCODING=utf-8
REM Gemini/تلگرام در این منطقه به پروکسی نیاز دارند؛ Task Scheduler آن را از نشستِ کاربر به ارث نمی‌برد.
set HTTPS_PROXY=http://127.0.0.1:10801
set HTTP_PROXY=http://127.0.0.1:10801
python -m src.evaluate_and_sync >> logs\scheduler_eval.log 2>&1
