@echo off
cd /d D:\prjcluade
set PYTHONIOENCODING=utf-8

REM --- تزریق پروکسیِ VPN (مهم) ---------------------------------------------
REM VPN روی این سیستم از نوع پروکسیِ محلی است (V2Ray). Task Scheduler نشستِ
REM تازه می‌سازد که متغیرهای پروکسیِ نشستِ کاربر را ندارد؛ بدون این، Gemini
REM مستقیم و بدون VPN می‌رود و خطای 403 می‌گیرد. اینجا پروکسی را از همان جایی
REM که VPN در رجیستری ست می‌کند می‌خوانیم تا اگر پورت عوض شد هم درست بماند.
set "PROXY="
for /f "tokens=2,*" %%a in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer 2^>nul') do set "PROXY=%%b"
if defined PROXY (
    set "HTTP_PROXY=http://%PROXY%"
    set "HTTPS_PROXY=http://%PROXY%"
    set "GRPC_PROXY=http://%PROXY%"
    set "NO_PROXY=localhost,127.0.0.1,::1,.local,*.supabase.co,supabase.co"
)
REM ------------------------------------------------------------------------

"C:\Users\ASUS\AppData\Local\Programs\Python\Python312\python.exe" -m src.run_with_check >> "D:\prjcluade\agent_log.txt" 2>&1
