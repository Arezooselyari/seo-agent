@echo off
REM خواندن کلیک‌های تایید/ردّ از تلگرام و به‌روزرسانی دیتابیس
cd /d "D:\prjcluade\seo-agent"
if not exist logs mkdir logs
set PYTHONIOENCODING=utf-8
REM تلگرام در این منطقه به پروکسی نیاز دارد؛ Task Scheduler آن را از نشستِ کاربر به ارث نمی‌برد.
set HTTPS_PROXY=http://127.0.0.1:10801
set HTTP_PROXY=http://127.0.0.1:10801
python -m src.process_approvals >> logs\scheduler_approvals.log 2>&1
