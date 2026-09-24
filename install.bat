@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ══════════════════════════════════════════════════
echo   تثبيت البوت كخدمة ويندوز - النسخة النهائية
echo ══════════════════════════════════════════════════
echo.

net session >nul 2>&1
if errorlevel 1 (
    echo ❌ لازم تشغله كمسؤول!
    echo    كليك يمين ^> تشغيل كمسؤول
    pause
    exit /b 1
)

:: التحقق
if not exist "dist\bot.exe"        ( echo ❌ bot.exe مش موجود! شغّل build.bat & pause & exit /b 1 )
if not exist "dist\RemoteBot.exe"  ( echo ❌ RemoteBot.exe مش موجود! & pause & exit /b 1 )
if not exist "dist\RemoteBot.xml"  ( echo ❌ RemoteBot.xml مش موجود! & pause & exit /b 1 )
if not exist "dist\.env"           ( echo ❌ .env مش موجود! & pause & exit /b 1 )

echo ✅ كل الملفات موجودة
echo.

set "WORK_DIR=%~dp0dist"
cd /d "%WORK_DIR%"

:: ═══════════════════════════════════════
::  1) إيقاف كل شي قديم
:: ═══════════════════════════════════════
echo [1/5] إيقاف القديم...
RemoteBot.exe stop >nul 2>&1
sc stop RemoteBot >nul 2>&1
taskkill /f /im bot.exe >nul 2>&1
taskkill /f /im wscript.exe >nul 2>&1
timeout /t 3 /nobreak >nul
RemoteBot.exe uninstall >nul 2>&1
sc delete RemoteBot >nul 2>&1
timeout /t 2 /nobreak >nul
echo      ✅ تم
echo.

if not exist "logs" mkdir "logs"

:: ═══════════════════════════════════════
::  2) تنظيف triggers قديمة
:: ═══════════════════════════════════════
echo [2/5] تنظيف...
del /q "*.trigger" >nul 2>&1
del /q "heartbeat" >nul 2>&1
echo      ✅ تم
echo.

:: ═══════════════════════════════════════
::  3) تثبيت الخدمة
:: ═══════════════════════════════════════
echo [3/5] تثبيت الخدمة...
RemoteBot.exe install
if errorlevel 1 (
    echo ❌ فشل التثبيت!
    pause
    exit /b 1
)
echo      ✅ تم
echo.

:: ═══════════════════════════════════════
::  4) إنشاء المساعد المحسّن
:: ═══════════════════════════════════════
echo [4/5] إنشاء المساعد...

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "HELPER=%STARTUP%\RemoteBot_Helper.vbs"

:: حذف القديم
del /q "%STARTUP%\RemoteBot_LockHelper.vbs" >nul 2>&1
del /q "%HELPER%" >nul 2>&1

:: إنشاء المساعد الجديد
> "%HELPER%" (
    echo ' ═══════════════════════════════════════
    echo ' RemoteBot Helper v2 - Lock + SignOut + Sleep
    echo ' يراقب ملفات trigger وينفذ الأوامر
    echo ' ═══════════════════════════════════════
    echo.
    echo On Error Resume Next
    echo.
    echo Set fso = CreateObject^("Scripting.FileSystemObject"^)
    echo Set shell = CreateObject^("WScript.Shell"^)
    echo.
    echo workDir = "%WORK_DIR%"
    echo lockFile = workDir ^& "\lock.trigger"
    echo signoutFile = workDir ^& "\signout.trigger"
    echo sleepFile = workDir ^& "\sleep.trigger"
    echo logFile = workDir ^& "\helper.log"
    echo.
    echo Sub WriteLog^(msg^)
    echo     On Error Resume Next
    echo     Set f = fso.OpenTextFile^(logFile, 8, True^)
    echo     f.WriteLine Now ^& " [HELPER] " ^& msg
    echo     f.Close
    echo     On Error GoTo 0
    echo End Sub
    echo.
    echo WriteLog "المساعد بدأ"
    echo.
    echo Do While True
    echo.
    echo     ' === قفل الشاشة ===
    echo     If fso.FileExists^(lockFile^) Then
    echo         fso.DeleteFile lockFile, True
    echo         WScript.Sleep 200
    echo         shell.Run "rundll32.exe user32.dll,LockWorkStation", 0, False
    echo         WriteLog "قفل الشاشة تم"
    echo     End If
    echo.
    echo     ' === تسجيل الخروج ===
    echo     If fso.FileExists^(signoutFile^) Then
    echo         fso.DeleteFile signoutFile, True
    echo         WScript.Sleep 200
    echo         shell.Run "shutdown /l /f", 0, False
    echo         WriteLog "تسجيل خروج تم"
    echo     End If
    echo.
    echo     ' === وضع النوم ===
    echo     If fso.FileExists^(sleepFile^) Then
    echo         fso.DeleteFile sleepFile, True
    echo         WScript.Sleep 200
    echo         shell.Run "rundll32.exe powrprof.dll,SetSuspendState 0,1,0", 0, False
    echo         WriteLog "وضع النوم تم"
    echo     End If
    echo.
    echo     WScript.Sleep 800
    echo.
    echo Loop
)

if exist "%HELPER%" (
    echo      ✅ تم إنشاء المساعد
) else (
    echo      ⚠️ فشل إنشاء المساعد!
    pause
    exit /b 1
)

:: إنشاء مهمة مجدولة كاحتياط (لو Startup معطل)
schtasks /delete /tn "RemoteBot_Helper" /f >nul 2>&1
schtasks /create ^
    /tn "RemoteBot_Helper" ^
    /tr "wscript.exe \"%HELPER%\"" ^
    /sc ONLOGON ^
    /rl LIMITED ^
    /f >nul 2>&1

if not errorlevel 1 (
    echo      ✅ مهمة احتياطية في الجدولة
) else (
    echo      ⚠️ المهمة الاحتياطية فشلت ^(مش مهم^)
)

:: تشغيل المساعد الآن
start "" wscript.exe "%HELPER%"
echo      ✅ المساعد شغال
echo.

:: ═══════════════════════════════════════
::  5) تشغيل الخدمة
:: ═══════════════════════════════════════
echo [5/5] تشغيل الخدمة...
RemoteBot.exe start
timeout /t 5 /nobreak >nul

sc query RemoteBot | find "RUNNING" >nul
if errorlevel 1 (
    echo ⚠️  الخدمة ما اشتغلت!
    echo    شوف: %WORK_DIR%\logs\
    RemoteBot.exe status
) else (
    echo      ✅ البوت شغال!
)

echo.
echo ══════════════════════════════════════════════════
echo   ✅ تم التثبيت بنجاح!
echo.
echo   ✅ البوت         : خدمة ويندوز 24/7
echo   ✅ المساعد       : Startup + مهمة مجدولة
echo   ✅ إعادة اتصال   : تلقائي
echo   ✅ إعادة تشغيل   : تلقائي لو وقع
echo.
echo   كلها تشتغل تلقائي مع الويندوز
echo.
echo   أوامر مفيدة ^(CMD كمسؤول^):
echo     sc query RemoteBot       الحالة
echo     sc stop RemoteBot        إيقاف
echo     sc start RemoteBot       تشغيل
echo ══════════════════════════════════════════════════
echo.
pause