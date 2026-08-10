# تنظیم Task Scheduler برای ایجنت ارزیابی مقالات (با schtasks — سازگار با همه ویندوزها)
# این اسکریپت را به‌عنوان Administrator اجرا کنید.

$base = "D:\prjcluade\seo-agent"

# ============================================================
# Task 0: تولیدِ روزانه‌ی یک مقاله (انتخابِ موضوع از RSS -> ذخیره‌ی pending)
# روزانه 10:00 صبح — قبل از مرحله‌ی ارزیابی (10:10)
# ============================================================
schtasks /Create /TN "SEO-Generate-Daily" `
    /TR "`"$base\run_generate_daily.bat`"" `
    /SC DAILY /ST 10:00 `
    /RL HIGHEST /F

# ============================================================
# Task 1: ارزیابی + ارسال به تلگرام
# روزانه 10:10 صبح، هر 15 دقیقه به مدت 1 ساعت
# (10 دقیقه بعد از تولید — تا مقاله‌ی امروز آماده‌ی ارزیابی باشد)
# ============================================================
schtasks /Create /TN "SEO-Eval-Sync" `
    /TR "`"$base\run_eval_sync.bat`"" `
    /SC DAILY /ST 10:10 /RI 15 /DU 0001:00 `
    /RL HIGHEST /F

# ============================================================
# Task 2: پردازش کلیک‌های تایید/ردّ — هر 5 دقیقه، تمام روز
# ============================================================
schtasks /Create /TN "SEO-Eval-Approvals" `
    /TR "`"$base\run_process_approvals.bat`"" `
    /SC MINUTE /MO 5 `
    /RL HIGHEST /F

Write-Host ""
Write-Host "هر دو Task تنظیم شدند. برای دیدن:" -ForegroundColor Cyan
Write-Host "  schtasks /Query /TN SEO-Eval-Sync" -ForegroundColor Cyan
Write-Host "  schtasks /Query /TN SEO-Eval-Approvals" -ForegroundColor Cyan
