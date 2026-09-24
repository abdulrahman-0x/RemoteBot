@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ══════════════════════════════════════
echo   تحويل bot.py إلى bot.exe
echo ══════════════════════════════════════
echo.

net session >nul 2>&1
if not errorlevel 1 (
    echo ⚠️  لا تشغله كمسؤول! دبل كليك عادي
    pause
    exit /b 1
)

if not exist "bot.py" (
    echo ❌ bot.py مش موجود!
    pause
    exit /b 1
)

if not exist ".env" (
    echo ❌ .env مش موجود!
    pause
    exit /b 1
)

echo [1/4] تثبيت المكتبات...
pip install discord.py pyinstaller --quiet
echo      ✅ تم
echo.

echo [2/4] تنظيف...
if exist "dist" rmdir /s /q "dist"
if exist "build" rmdir /s /q "build"
del /q *.spec >nul 2>&1
echo      ✅ تم
echo.

echo [3/4] بناء bot.exe ... (دقيقة تقريباً)
pyinstaller ^
    --onefile ^
    --noconsole ^
    --name bot ^
    --hidden-import discord ^
    --hidden-import aiohttp ^
    --hidden-import charset_normalizer ^
    --hidden-import multidict ^
    --hidden-import yarl ^
    --hidden-import frozenlist ^
    --hidden-import async_timeout ^
    --hidden-import aiohappyeyeballs ^
    bot.py

if errorlevel 1 (
    echo ❌ فشل البناء!
    pause
    exit /b 1
)
echo      ✅ bot.exe جاهز
echo.

echo [4/4] نسخ الملفات لمجلد dist...
copy /y ".env"           "dist\.env"           >nul
copy /y "RemoteBot.exe"  "dist\RemoteBot.exe"  >nul 2>&1
copy /y "RemoteBot.xml"  "dist\RemoteBot.xml"  >nul 2>&1
echo      ✅ تم
echo.

rmdir /s /q "build" >nul 2>&1
del /q *.spec >nul 2>&1

echo ══════════════════════════════════════
echo   ✅ تم البناء!
echo.
echo   dist\
echo     bot.exe         ✅
if exist "dist\RemoteBot.exe" (
    echo     RemoteBot.exe   ✅
) else (
    echo     RemoteBot.exe   ❌ انسخه يدوي!
)
if exist "dist\RemoteBot.xml" (
    echo     RemoteBot.xml   ✅
) else (
    echo     RemoteBot.xml   ❌ انسخه يدوي!
)
if exist "dist\.env" (
    echo     .env            ✅
)
echo.
echo   الخطوة التالية:
echo   install.bat كليك يمين ^> تشغيل كمسؤول
echo ══════════════════════════════════════
echo.
pause