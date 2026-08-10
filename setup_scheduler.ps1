# PowerShell Script — Task Scheduler تنظیم کن
# این اسکریپت را به‌عنوان Admin اجرا کنید

$taskName = "PersianAI-CheckAndRun"
$scriptPath = "D:\prjcluade"

# ۱) Action: اسکریپت Python را اجرا کن
$action = New-ScheduledTaskAction `
    -Execute "python" `
    -Argument "-m src.run_with_check" `
    -WorkingDirectory $scriptPath

# ۲) Trigger: هر روز ساعت ۱۰ شروع شود، هر ۱۵ دقیقه ادامه یابد (برای ۱ ساعت)
$trigger = New-ScheduledTaskTrigger `
    -Daily `
    -At "10:00 AM"

# تنظیم Repetition: هر ۱۵ دقیقه، تا ۶۰ دقیقه
$trigger.Repetition = New-ScheduledTaskTriggerRepetition `
    -Interval (New-TimeSpan -Minutes 15) `
    -Duration (New-TimeSpan -Hours 1) `
    -StopAtDurationEnd $false

# ۳) Settings: همیشه اجرا شود (حتی اگر سیستم بیدار نبود)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RunOnlyIfNetworkAvailable

# ۴) اگر task ماقبل وجود دارد، حذف کن
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# ۵) Task جدید را ثبت کن
Register-ScheduledTask `
    -TaskName $taskName `
    -Description "هر ۱۵ دقیقه بین ۱۰ و ۱۱ صبح: چک کن و مقاله‌ها را ارسال کن" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -RunLevel Highest `
    -Force

Write-Host "✅ Task Scheduler تنظیم شد:" -ForegroundColor Green
Write-Host "   نام: $taskName" -ForegroundColor Green
Write-Host "   زمان: هر روز ۱۰:۰۰ صبح" -ForegroundColor Green
Write-Host "   تکرار: هر ۱۵ دقیقه برای ۶۰ دقیقه" -ForegroundColor Green
Write-Host "   دستور: python -m src.run_with_check" -ForegroundColor Green
