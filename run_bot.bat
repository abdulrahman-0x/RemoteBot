@echo off
title Discord PC Control Bot
cd /d "%~dp0"

echo [%date% %time%] تشغيل بوت ديسكورد... >> bot_startup.log

:loop
echo [%date% %time%] محاولة تشغيل البوت...
python bot.py
echo [%date% %time%] البوت توقف — إعادة التشغيل بعد 10 ثواني...
timeout /t 10 /nobreak
goto loop
