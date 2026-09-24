@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ══════════════════════════════════════
echo   إلغاء التثبيت بالكامل
echo ══════════════════════════════════════
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo ❌ لازم تشغله كمسؤول!
    pause
    exit /b 1
)

echo [1/5] إيقاف الخدمة...
if exist "dist\RemoteBot.exe" (
    cd /d "%~dp0dist"
    RemoteBot.exe stop >nul 2>&1
    timeout /t 3 /nobreak >nul
    RemoteBot.exe uninstall >nul 2>&1
)
sc stop RemoteBot >nul 2>&1
sc delete RemoteBot >nul 2>&1
taskkill /f /im bot.exe >nul 2>&1
echo      ✅ تم
echo.

echo [2/5] إيقاف المساعد...
taskkill /f /im wscript.exe >nul 2>&1
echo      ✅ تم
echo.

echo [3/5] حذف المساعد...
del /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\RemoteBot_Helper.vbs" >nul 2>&1
del /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\RemoteBot_LockHelper.vbs" >nul 2>&1
echo      ✅ تم
echo.

echo [4/5] حذف المهمة المجدولة...
schtasks /delete /tn "RemoteBot_Helper" /f >nul 2>&1
echo      ✅ تم
echo.

echo [5/5] تنظيف...
del /q "%~dp0dist\*.trigger" >nul 2>&1
del /q "%~dp0dist\heartbeat" >nul 2>&1
echo      ✅ تم
echo.

echo ══════════════════════════════════════
echo   ✅ تم الحذف بالكامل
echo ══════════════════════════════════════
echo.
pause