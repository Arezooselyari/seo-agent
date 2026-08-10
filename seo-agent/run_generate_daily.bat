@echo off
REM تولیدِ روزانه‌ی یک مقاله: انتخابِ موضوع از RSS -> نگارش -> ذخیره به‌عنوان pending
cd /d "D:\prjcluade\seo-agent"
if not exist logs mkdir logs
set PYTHONIOENCODING=utf-8
REM Gemini در این منطقه مسدود است و به پروکسی نیاز دارد؛ Task Scheduler پروکسیِ
REM نشستِ کاربر را به ارث نمی‌برد. پروکسیِ محلی را صریح ست کن (اگر پورت عوض شد این خط را عوض کن).
REM پیش‌نیاز: برنامه‌ی VPN/پروکسی باید موقعِ اجرا روشن باشد (auto-start on boot).
set HTTPS_PROXY=http://127.0.0.1:10801
set HTTP_PROXY=http://127.0.0.1:10801
python -m src.generate_daily >> logs\scheduler_generate.log 2>&1
