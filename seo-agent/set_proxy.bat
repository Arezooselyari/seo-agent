@echo off
REM ---------------------------------------------------------------------------
REM پروکسیِ محلیِ VPN را برای فرزندانِ این اسکریپت ست می‌کند — *فقط اگر واقعاً
REM روشن باشد*.
REM
REM چرا وجود دارد: VPN روی این سیستم از نوع پروکسیِ محلی است (V2Ray) و پورتش
REM ثابت نیست. سه اسکریپتِ زمان‌بندی‌شده قبلاً پورت را هاردکد کرده بودند؛ وقتی
REM پورت از ۱۰۸۰۱ به ۱۰۸۰۸ عوض شد، هر سه بی‌صدا شکست خوردند (ConnectError).
REM پس به‌جای هاردکد، از همان کلیدِ رجیستری می‌خوانیم که خودِ VPN می‌نویسد.
REM
REM چرا fallbackِ هاردکد حذف شد: وقتی VPN خاموش است، اتصالِ مستقیم کار می‌کند
REM (OpenRouter و فیدهای RSS از اینجا مستقیم جواب می‌دهند). ولی fallbackِ قبلی
REM به‌زور پورتِ ۱۰۸۰۸ را ست می‌کرد که کسی رویش گوش نمی‌داد، و هر سه تسک را با
REM ConnectError می‌خواباند — یعنی دقیقاً همان باگی که قرار بود حل کند، فقط با
REM علامتِ عکس. حالا: پروکسی فقط وقتی ست می‌شود که رجیستری آن را روشن اعلام کند
REM *و* چیزی واقعاً روی آن پورت گوش بدهد.
REM
REM با «call» صدا زده شود، نه اجرای مستقیم:  call "%~dp0set_proxy.bat"
REM ---------------------------------------------------------------------------

set "PROXY="

REM ۱) آیا ویندوز اصلاً پروکسی را فعال می‌داند؟ (VPN خاموش → ProxyEnable=0x0)
set "PROXY_ON="
for /f "tokens=3" %%a in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyEnable 2^>nul') do set "PROXY_ON=%%a"
if /i "%PROXY_ON%"=="0x1" (
    REM ۲) آدرسِ پروکسی را از همان جایی بخوان که VPN می‌نویسد
    for /f "tokens=2,*" %%a in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer 2^>nul') do set "PROXY=%%b"
)

REM ۳) رجیستری ممکن است کهنه باشد (VPN بسته شده ولی مقدار مانده). پس قبل از
REM    اعتماد، مطمئن شو کسی واقعاً روی آن پورت گوش می‌دهد.
if defined PROXY (
    netstat -an | findstr /C:"LISTENING" | findstr /C:"%PROXY%" >nul 2>&1
    if errorlevel 1 (
        echo [set_proxy] هشدار: پروکسیِ %PROXY% در رجیستری هست ولی کسی روی آن گوش نمی‌دهد — مستقیم می‌رویم.
        set "PROXY="
    )
)

if defined PROXY (
    set "HTTP_PROXY=http://%PROXY%"
    set "HTTPS_PROXY=http://%PROXY%"
    set "GRPC_PROXY=http://%PROXY%"
    REM سایتِ مقصدِ انتشار باید *بیرونِ* پروکسی بماند: میزبانِ ایرانی، ترافیکِ آمده از
    REM IPِ خارجیِ VPN را دور می‌اندازد. علامتش «Read timed out» موقعِ انتشار است، در
    REM حالی که همان آدرس بدونِ پروکسی ۲۰۰ می‌دهد. (اگر WP_URL عوض شد، اینجا را هم عوض کن.)
    set "NO_PROXY=localhost,127.0.0.1,::1,.local,sagharnazari.ir,www.sagharnazari.ir"
) else (
    REM هیچ پروکسیِ زنده‌ای نیست → مستقیم. متغیرهای احتمالیِ به‌ارث‌رسیده پاک
    REM شوند، وگرنه فرزندان به یک پروکسیِ مرده وصل می‌شوند.
    set "HTTP_PROXY="
    set "HTTPS_PROXY="
    set "GRPC_PROXY="
    set "NO_PROXY="
)

REM ردِ تشخیصی: وقتی دوباره چیزی شکست، اول اینجا را نگاه کن.
if exist logs (
    if defined PROXY (
        echo [%date% %time%] proxy=%PROXY% >> logs\proxy.log
    ) else (
        echo [%date% %time%] proxy=none ^(direct^) >> logs\proxy.log
    )
)
