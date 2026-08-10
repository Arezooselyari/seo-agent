@echo off
cd /d D:\prjcluade
set PYTHONIOENCODING=utf-8
set "PROXY="
for /f "tokens=2,*" %%a in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings" /v ProxyServer 2^>nul') do set "PROXY=%%b"
if defined PROXY (
    set "HTTP_PROXY=http://%PROXY%"
    set "HTTPS_PROXY=http://%PROXY%"
    set "GRPC_PROXY=http://%PROXY%"
    set "NO_PROXY=localhost,127.0.0.1,::1,.local"
)
"C:\Users\ASUS\AppData\Local\Programs\Python\Python312\python.exe" preflight.py
