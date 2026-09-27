"""
الحارس - يراقب bot.exe ويعيد تشغيله لو وقع.

This is the MANUAL/DEV supervisor only. The production Windows service is
WinSW (RemoteBot.exe + RemoteBot.xml), which has its own restart-on-failure
policy and does NOT launch this file. Start it with start_hidden.vbs
(`pythonw watchdog.py`).
"""
import subprocess
import sys
import os
import time
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

# ============================================================
#                    تحديد المسارات
# ============================================================
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ── اكتشاف تلقائي: bot.exe أو bot.py ──
BOT_EXE = os.path.join(BASE_DIR, "bot.exe")
BOT_PY  = os.path.join(BASE_DIR, "bot.py")

if os.path.exists(BOT_EXE):
    BOT_CMD = [BOT_EXE]
    BOT_NAME = "bot.exe"
elif os.path.exists(BOT_PY):
    BOT_CMD = [sys.executable, BOT_PY]
    BOT_NAME = "bot.py"
else:
    print(f"[ERROR] لا يوجد bot.exe ولا bot.py في {BASE_DIR}")
    input("اضغط Enter...")
    sys.exit(1)

# ============================================================
#                    الإعدادات
# ============================================================
RESTART_WAIT       = 5      # ثواني قبل إعادة التشغيل
MAX_FAST_RESTARTS  = 5      # أقصى عدد إعادات في دقيقة
COOLDOWN           = 60     # انتظار طويل لو كثير إعادات
HEALTH_CHECK_INTERVAL = 30  # فحص كل 30 ثانية

# ============================================================
#                       Logging
# ============================================================
LOG_FILE = os.path.join(BASE_DIR, "watchdog.log")

log_handlers = [
    RotatingFileHandler(LOG_FILE, encoding="utf-8", maxBytes=2*1024*1024, backupCount=2),
]
if sys.stdout:
    log_handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [WATCHDOG] %(message)s",
    handlers=log_handlers,
)
log = logging.getLogger("watchdog")

# ============================================================
#             منع تشغيل نسختين من الحارس
# ============================================================
def check_single_instance():
    """يتأكد إن مافي حارس ثاني شغال."""
    import ctypes

    # محاولة إنشاء Mutex فريد
    mutex_name = "Global\\RemoteBotWatchdog_Mutex"
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
    last_error = ctypes.windll.kernel32.GetLastError()

    if last_error == 183:  # ERROR_ALREADY_EXISTS
        log.warning("الحارس شغال بالفعل! إغلاق النسخة الجديدة.")
        sys.exit(0)

    return mutex  # لازم نحتفظ بالمرجع عشان ما ينحذف


# ============================================================
#                    تشغيل البوت
# ============================================================
def start_bot():
    """يشغل البوت كـ subprocess."""
    log.info(f"تشغيل: {BOT_NAME}")

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.CREATE_NO_WINDOW

    process = subprocess.Popen(
        BOT_CMD,
        cwd=BASE_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        creationflags=creation_flags,
    )

    log.info(f"البوت شغال - PID: {process.pid}")
    return process


def is_running(process):
    """يتحقق إذا البوت لسا شغال."""
    return process.poll() is None


# ============================================================
#                    الحلقة الرئيسية
# ============================================================
def main():
    log.info("=" * 50)
    log.info("  الحارس شغال - يراقب البوت 24/7")
    log.info(f"  البوت: {BOT_NAME}")
    log.info(f"  المسار: {BASE_DIR}")
    log.info("=" * 50)

    # منع نسخ مكررة
    if sys.platform == "win32":
        try:
            mutex = check_single_instance()
        except Exception:
            pass

    restart_times = []
    total_restarts = 0

    while True:
        # ── تشغيل البوت ──
        process = start_bot()
        start_time = time.time()
        total_restarts += 1

        # ── مراقبة البوت ──
        while is_running(process):
            time.sleep(HEALTH_CHECK_INTERVAL)
            uptime_mins = (time.time() - start_time) / 60
            if int(uptime_mins) % 60 == 0 and int(uptime_mins) > 0:
                log.info(f"البوت شغال من {int(uptime_mins)} دقيقة")

        # ── البوت وقع ──
        return_code = process.returncode
        run_duration = time.time() - start_time
        log.warning(
            f"البوت وقع! كود: {return_code} | "
            f"مدة التشغيل: {int(run_duration)}s | "
            f"إعادات: {total_restarts}"
        )

        # ── حماية من الإعادات السريعة ──
        now = time.time()
        restart_times.append(now)
        restart_times = [t for t in restart_times if now - t < COOLDOWN]

        if len(restart_times) >= MAX_FAST_RESTARTS:
            log.error(
                f"{MAX_FAST_RESTARTS} إعادات في دقيقة! "
                f"انتظار {COOLDOWN}s..."
            )
            time.sleep(COOLDOWN)
            restart_times.clear()
        else:
            log.info(f"إعادة التشغيل بعد {RESTART_WAIT}s...")
            time.sleep(RESTART_WAIT)


if __name__ == "__main__":
    main()