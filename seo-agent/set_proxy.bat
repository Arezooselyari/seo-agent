@echo off
REM ---------------------------------------------------------------------------
REM پروکسیِ محلیِ VPN را برای فرزندانِ این اسکریپت ست می‌کند.
REM
REM چرا وجود دارد: VPN روی این سیستم از نوع پروکسیِ محلی است (V2Ray) و پورتش
REM ثابت نیست. سه اسکریپتِ زمان‌بندی‌شده قبلاً پورت را هاردکد کرده بودند؛ وقتی
REM پورت از ۱۰۸۰۱ به ۱۰۸۰۸ عوض شد، هر سه بی‌صدا شکست خوردند (ConnectError).
REM پس به‌جای هاردکد، از همان کلیدِ رجیستری می‌خوانیم که خودِ VPN می‌نویسد.
REM
REM با «call» صدا زده شود، نه اجرای مستقیم:  call "%~dp0set_proxy.bat"
REM ---------------------------------------------------------------------------

set "PROXY="
for /f "tokens=2,*" %%a in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer 2^>nul') do set "PROXY=%%b"

REM اگر VPN خاموش بود یا رجیستری چیزی نداشت، آخرین پورتِ شناخته‌شده را امتحان کن.
if not defined PROXY set "PROXY=127.0.0.1:10808"

set "HTTP_PROXY=http://%PROXY%"
set "HTTPS_PROXY=http://%PROXY%"
set "GRPC_PROXY=http://%PROXY%"
REM سایتِ مقصدِ انتشار باید *بیرونِ* پروکسی بماند: میزبانِ ایرانی، ترافیکِ آمده از
REM IPِ خارجیِ VPN را دور می‌اندازد. علامتش «Read timed out» موقعِ انتشار است، در
REM حالی که همان آدرس بدونِ پروکسی ۲۰۰ می‌دهد. (اگر WP_URL عوض شد، اینجا را هم عوض کن.)
set "NO_PROXY=localhost,127.0.0.1,::1,.local,sagharnazari.ir,www.sagharnazari.ir"

REM ردِ تشخیصی: وقتی دوباره چیزی شکست، اول اینجا را نگاه کن.
if exist logs echo [%date% %time%] proxy=%PROXY% >> logs\proxy.log
