import discord
from discord.ui import View, Button
import os
import sys
import asyncio
import logging
from logging.handlers import RotatingFileHandler
import signal
import subprocess
import ctypes
import time as _time
import random
from datetime import datetime

# ============================================================
#              تحديد المسار
# ============================================================
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
#                    إصلاح الترميز
# ============================================================
if sys.platform == "win32":
    try:
        if sys.stdout:
            sys.stdout.reconfigure(encoding='utf-8')
        if sys.stderr:
            sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

# ============================================================
#              تحميل .env
# ============================================================
def load_env_file():
    env_path = os.path.join(BASE_DIR, ".env")
    if not os.path.exists(env_path):
        return False
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, value = line.split("=", 1)
                os.environ[key.strip()] = value.strip()
    return True

if not load_env_file():
    sys.exit(1)

# ============================================================
#                    الإعدادات
# ============================================================
BOT_TOKEN          = os.getenv("DISCORD_BOT_TOKEN", "")
ALLOWED_CHANNEL_ID = int(os.getenv("ALLOWED_CHANNEL_ID", "0"))
ALLOWED_USER_IDS   = [
    int(uid.strip())
    for uid in os.getenv("ALLOWED_USER_IDS", "").split(",")
    if uid.strip()
]
SHUTDOWN_DELAY = int(os.getenv("SHUTDOWN_DELAY", "10"))
TRIGGER_WORD   = os.getenv("TRIGGER_WORD", "")

if not BOT_TOKEN:
    sys.exit(1)

if not TRIGGER_WORD:
    sys.exit(1)

# ============================================================
#                       Logging
# ============================================================
LOG_FILE = os.path.join(BASE_DIR, "bot.log")

log_handlers = [
    RotatingFileHandler(
        LOG_FILE, encoding="utf-8",
        maxBytes=5 * 1024 * 1024, backupCount=3,
    ),
]
if sys.stdout:
    log_handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=log_handlers,
)
log = logging.getLogger(__name__)

# ============================================================
#                    إعداد البوت
# ============================================================
intents = discord.Intents.default()
intents.message_content = True

# ============================================================
#                    معلومات الأوامر
# ============================================================
ACTIONS = {
    "shutdown": {
        "emoji": "🔴", "label": "إغلاق", "en": "Shut Down",
        "countdown": True,
    },
    "restart": {
        "emoji": "🔄", "label": "إعادة تشغيل", "en": "Restart",
        "countdown": True,
    },
    "signout": {
        "emoji": "🚪", "label": "تسجيل خروج", "en": "Sign Out",
        "countdown": True,
    },
    "sleep": {
        "emoji": "💤", "label": "وضع النوم", "en": "Sleep",
        "countdown": True,
    },
    "lock": {
        "emoji": "🔒", "label": "قفل الشاشة", "en": "Lock Screen",
        "countdown": False,
    },
}

# ============================================================
#                ملفات Trigger + حماية التكرار
# ============================================================
TRIGGERS = {
    "lock":    os.path.join(BASE_DIR, "lock.trigger"),
    "signout": os.path.join(BASE_DIR, "signout.trigger"),
    "sleep":   os.path.join(BASE_DIR, "sleep.trigger"),
}

# ✅ ملف قفل لمنع تكرار الأوامر
EXEC_LOCK_FILE = os.path.join(BASE_DIR, ".exec_lock")

# ✅ الأوامر قيد التنفيذ (في الذاكرة)
_executing = set()


def cleanup_triggers():
    """ينظّف ملفات trigger + ملف القفل عند بدء التشغيل أو الاستيقاظ."""
    for name, path in TRIGGERS.items():
        try:
            if os.path.exists(path):
                os.remove(path)
                log.info(f"تنظيف trigger: {name}")
        except Exception:
            pass

    # تنظيف ملف القفل
    try:
        if os.path.exists(EXEC_LOCK_FILE):
            os.remove(EXEC_LOCK_FILE)
            log.info("تنظيف ملف القفل")
    except Exception:
        pass

    _executing.clear()


def write_trigger(action: str) -> bool:
    path = TRIGGERS.get(action)
    if not path:
        return False
    try:
        with open(path, "w") as f:
            f.write(action)
        return True
    except Exception:
        return False


def set_exec_lock(action: str):
    """يكتب ملف قفل قبل تنفيذ الأمر."""
    try:
        with open(EXEC_LOCK_FILE, "w") as f:
            f.write(action)
        _executing.add(action)
    except Exception:
        pass


def clear_exec_lock(action: str):
    """يحذف ملف القفل بعد تنفيذ الأمر."""
    try:
        if os.path.exists(EXEC_LOCK_FILE):
            os.remove(EXEC_LOCK_FILE)
    except Exception:
        pass
    _executing.discard(action)


def is_locked(action: str) -> bool:
    """يتحقق إذا الأمر قيد التنفيذ (حماية من التكرار)."""
    # فحص الذاكرة
    if action in _executing:
        return True

    # فحص الملف (يغطي حالة النوم/الاستيقاظ)
    try:
        if os.path.exists(EXEC_LOCK_FILE):
            with open(EXEC_LOCK_FILE, "r") as f:
                locked_action = f.read().strip()
            if locked_action == action:
                return True
    except Exception:
        pass

    return False


# ============================================================
#              دوال مساعدة
# ============================================================
def get_active_session_id():
    try:
        sid = ctypes.windll.kernel32.WTSGetActiveConsoleSessionId()
        if sid != 0xFFFFFFFF:
            return sid
    except Exception:
        pass
    try:
        r = subprocess.run(
            'query session', shell=True,
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            for line in r.stdout.split('\n'):
                if 'Active' in line:
                    for part in line.split():
                        if part.isdigit():
                            return int(part)
    except Exception:
        pass
    return None


def is_helper_running():
    try:
        r = subprocess.run(
            'tasklist /fi "imagename eq wscript.exe" /fo csv /nh',
            shell=True, capture_output=True, text=True, timeout=5,
        )
        return 'wscript.exe' in r.stdout.lower()
    except Exception:
        return False


def run_cmd(cmd, timeout=10):
    """يشغّل أمر وينتظر النتيجة."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, timeout=timeout)
        return r.returncode == 0
    except Exception:
        return False


def fire_and_forget(cmd):
    """✅ يشغّل أمر بدون انتظار (مهم للنوم!)."""
    try:
        subprocess.Popen(
            cmd,
            shell=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


# ============================================================
#                    تنفيذ الأوامر
# ============================================================

# ── إغلاق (ما يتكرر - الجهاز بيقفل) ──
def do_shutdown():
    log.warning(">>> إغلاق")
    if run_cmd('shutdown /s /f /t 0'):
        return True
    run_cmd('powershell -Command "Stop-Computer -Force"')
    return True


# ── إعادة تشغيل (ما يتكرر - الجهاز بيعمل restart) ──
def do_restart():
    log.warning(">>> إعادة تشغيل")
    if run_cmd('shutdown /r /f /t 0'):
        return True
    run_cmd('powershell -Command "Restart-Computer -Force"')
    return True


# ── تسجيل خروج (ممكن يتكرر لو trigger ما اتحذف) ──
def do_signout():
    log.warning(">>> تسجيل خروج")

    # طريقة 1: logoff بـ Session ID (آمنة - تنفّذ في Session 0)
    sid = get_active_session_id()
    if sid is not None:
        if run_cmd(f'logoff {sid}'):
            return True

    # طريقة 2: trigger (المساعد ينفّذ)
    if write_trigger("signout"):
        return True

    # طريقة 3: shutdown /l
    if run_cmd('shutdown /l /f'):
        return True

    # طريقة 4: PowerShell
    if run_cmd('powershell -Command "(Get-WmiObject Win32_OperatingSystem).Win32Shutdown(4)"', 15):
        return True

    return False


# ✅ ── وضع النوم (مُصلّح - fire_and_forget بدل run_cmd) ──
def do_sleep():
    log.warning(">>> نوم")

    # تعطيل Hibernate
    fire_and_forget('powercfg -h off')
    _time.sleep(0.5)

    # ✅ طريقة 1: fire_and_forget (ما ينتظر = ما يتكرر!)
    if fire_and_forget('rundll32.exe powrprof.dll,SetSuspendState 0,1,0'):
        log.info("نوم: أمر مباشر أُرسل (fire_and_forget)")
        return True

    # طريقة 2: trigger فقط كاحتياط
    if write_trigger("sleep"):
        log.info("نوم: trigger")
        return True

    return False


# ── قفل الشاشة (فوري - ما يتكرر عادةً) ──
def do_lock():
    log.warning(">>> قفل")

    try:
        if ctypes.windll.user32.LockWorkStation():
            return True
    except Exception:
        pass

    if write_trigger("lock"):
        return True

    task = "_RemoteBot_Lock"
    run_cmd(f'schtasks /delete /tn "{task}" /f')
    if run_cmd(f'schtasks /create /tn "{task}" /tr "rundll32.exe user32.dll,LockWorkStation" /sc once /st 00:00 /f /rl HIGHEST'):
        run_cmd(f'schtasks /run /tn "{task}"')
        run_cmd(f'schtasks /delete /tn "{task}" /f')
        return True

    if run_cmd('tsdiscon'):
        return True

    return False


ACTION_FUNC = {
    "shutdown": do_shutdown,
    "restart":  do_restart,
    "signout":  do_signout,
    "sleep":    do_sleep,
    "lock":     do_lock,
}


def execute_action(action: str) -> bool:
    """✅ ينفّذ أمر مع حماية من التكرار."""

    # ✅ فحص القفل (حماية من التكرار)
    if is_locked(action):
        log.warning(f"تجاهل {action}: الأمر قيد التنفيذ بالفعل (حماية تكرار)")
        cleanup_triggers()
        return True

    # ✅ تفعيل القفل
    set_exec_lock(action)

    func = ACTION_FUNC.get(action)
    if func:
        try:
            result = func()

            # ✅ للأوامر اللي ما بتقفل الجهاز: شيل القفل بعد ثوانٍ
            if action in ("lock",):
                clear_exec_lock(action)
            # sleep: القفل يتشال في on_resumed بعد الاستيقاظ
            # shutdown/restart: الجهاز بيقفل فمش مهم
            # signout: الجلسة بتنتهي

            return result
        except Exception as e:
            log.error(f"خطأ {action}: {e}")
            clear_exec_lock(action)
            return False

    clear_exec_lock(action)
    return False


# ============================================================
#           أزرار التأكيد (تنفيذ الآن + إلغاء)
# ============================================================
class ConfirmView(View):
    def __init__(self, action: str, user_id: int):
        super().__init__(timeout=SHUTDOWN_DELAY + 5)
        self.action      = action
        self.user_id     = user_id
        self.cancelled   = False
        self.execute_now = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ مش ليك!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="تنفيذ الآن", emoji="⚡", style=discord.ButtonStyle.success)
    async def execute_now_btn(self, interaction: discord.Interaction, button: Button):
        self.execute_now = True
        self.stop()

        info = ACTIONS[self.action]
        embed = discord.Embed(
            title=f"{info['emoji']} {info['label']}",
            description="⚡ **جاري التنفيذ الفوري...**",
            color=discord.Color.dark_red(),
            timestamp=datetime.now(),
        )
        embed.set_footer(text=f"طلب من: {interaction.user}")

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        log.info(f"تنفيذ فوري: {self.action} بواسطة {interaction.user}")

    @discord.ui.button(label="إلغاء", emoji="❌", style=discord.ButtonStyle.danger)
    async def cancel_btn(self, interaction: discord.Interaction, button: Button):
        self.cancelled = True
        self.stop()

        info = ACTIONS[self.action]
        embed = discord.Embed(
            title="✅ تم الإلغاء",
            description=f"تم إلغاء **{info['emoji']} {info['label']}**",
            color=discord.Color.green(),
        )
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)
        log.info(f"إلغاء: {self.action} بواسطة {interaction.user}")


# ============================================================
#                    القائمة الرئيسية
# ============================================================
class MainMenuView(View):
    def __init__(self, user_id: int, bot_ref):
        super().__init__(timeout=30)
        self.user_id = user_id
        self.bot_ref = bot_ref
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ مش ليك!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="إغلاق", emoji="🔴", style=discord.ButtonStyle.danger, row=0)
    async def shutdown_btn(self, i, b): await self._do(i, "shutdown")

    @discord.ui.button(label="إعادة تشغيل", emoji="🔄", style=discord.ButtonStyle.primary, row=0)
    async def restart_btn(self, i, b): await self._do(i, "restart")

    @discord.ui.button(label="تسجيل خروج", emoji="🚪", style=discord.ButtonStyle.secondary, row=1)
    async def signout_btn(self, i, b): await self._do(i, "signout")

    @discord.ui.button(label="وضع النوم", emoji="💤", style=discord.ButtonStyle.secondary, row=1)
    async def sleep_btn(self, i, b): await self._do(i, "sleep")

    @discord.ui.button(label="قفل الشاشة", emoji="🔒", style=discord.ButtonStyle.secondary, row=2)
    async def lock_btn(self, i, b): await self._do(i, "lock")

    @discord.ui.button(label="إلغاء", emoji="✖️", style=discord.ButtonStyle.secondary, row=3)
    async def cancel_btn(self, interaction, button):
        self.stop()
        embed = discord.Embed(title="✖️ تم إغلاق القائمة", color=discord.Color.light_grey())
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

    async def _do(self, interaction, action):
        self.stop()
        info = ACTIONS[action]

        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

        # ── تنفيذ فوري (قفل الشاشة) ──
        if not info["countdown"]:
            embed = discord.Embed(
                title=f"{info['emoji']} {info['label']}",
                description="⏳ **جاري التنفيذ...**",
                color=discord.Color.orange(),
                timestamp=datetime.now(),
            )
            embed.set_footer(text=f"طلب من: {interaction.user}")
            status_msg = await interaction.channel.send(embed=embed)

            success = await asyncio.get_event_loop().run_in_executor(
                None, execute_action, action
            )

            if success:
                embed.description = "✅ **تم التنفيذ!**"
                embed.color = discord.Color.green()
            else:
                helper_status = "🟢 شغال" if is_helper_running() else "🔴 مش شغال"
                embed.description = (
                    "❌ **فشل!**\n"
                    f"المساعد: {helper_status}\n"
                    "أعد تشغيل الجهاز"
                )
                embed.color = discord.Color.red()

            try:
                await status_msg.edit(embed=embed)
            except Exception:
                pass
            return

        # ── عد تنازلي مع زرين ──
        confirm = ConfirmView(action, self.user_id)
        embed = discord.Embed(
            title=f"{info['emoji']} {info['label']} ({info['en']})",
            color=discord.Color.orange(),
            timestamp=datetime.now(),
        )
        embed.add_field(
            name="⏳ العد التنازلي",
            value=f"التنفيذ خلال **{SHUTDOWN_DELAY}** ثانية",
            inline=False,
        )
        embed.add_field(
            name="🎮 الخيارات",
            value="⚡ **تنفيذ الآن** - بدون انتظار\n❌ **إلغاء** - إلغاء العملية",
            inline=False,
        )
        embed.set_footer(text=f"طلب من: {interaction.user}")

        msg = await interaction.channel.send(embed=embed, view=confirm)
        log.info(f"أمر: {info['label']} من {interaction.user}")

        for remaining in range(SHUTDOWN_DELAY, 0, -1):
            await asyncio.sleep(1)

            if confirm.cancelled:
                return

            if confirm.execute_now:
                break

            if remaining % 3 == 0 or remaining <= 3:
                embed.set_field_at(0, name="⏳ العد التنازلي",
                    value=f"التنفيذ خلال **{remaining - 1}** ثانية", inline=False)
                try:
                    await msg.edit(embed=embed)
                except Exception:
                    return

        if not confirm.cancelled:
            confirm.stop()
            for item in confirm.children:
                item.disabled = True

            if not confirm.execute_now:
                embed.color = discord.Color.dark_red()
                embed.set_field_at(0, name="⏳",
                    value="**جاري التنفيذ...**", inline=False)
                if len(embed.fields) > 1:
                    embed.remove_field(1)
                try:
                    await msg.edit(embed=embed, view=confirm)
                except Exception:
                    pass

            log.warning(f"تنفيذ: {action}")
            await asyncio.sleep(0.5)

            success = await asyncio.get_event_loop().run_in_executor(
                None, execute_action, action
            )

            if not success:
                try:
                    helper_status = "🟢 شغال" if is_helper_running() else "🔴 مش شغال"
                    fail_embed = discord.Embed(
                        title=f"❌ فشل {info['label']}",
                        description=f"المساعد: {helper_status}\nأعد تشغيل الجهاز",
                        color=discord.Color.red(),
                    )
                    await msg.channel.send(embed=fail_embed)
                except Exception:
                    pass

    async def on_timeout(self):
        if self.message:
            embed = discord.Embed(
                title="⏰ انتهى الوقت",
                description=f"اكتب **{TRIGGER_WORD}** مرة ثانية",
                color=discord.Color.light_grey(),
            )
            for item in self.children:
                item.disabled = True
            try:
                await self.message.edit(embed=embed, view=self)
            except Exception:
                pass


# ============================================================
#                    البوت الرئيسي
# ============================================================
class RemoteBot(discord.Client):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.boot_time  = datetime.now()
        self._connects  = 0
        self._heartbeat_task = None

    async def setup_hook(self):
        # ✅ تنظيف عند بدء التشغيل
        cleanup_triggers()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def _heartbeat_loop(self):
        heartbeat_file = os.path.join(BASE_DIR, "heartbeat")
        while True:
            try:
                with open(heartbeat_file, "w") as f:
                    f.write(datetime.now().isoformat())
            except Exception:
                pass
            await asyncio.sleep(30)

    async def on_ready(self):
        self._connects += 1
        status = "اتصال أول" if self._connects == 1 else f"إعادة اتصال #{self._connects}"
        log.info(f"{status}: {self.user}")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"اكتب: {TRIGGER_WORD}",
            )
        )
        # ✅ تنظيف بعد كل اتصال (يشمل الاستيقاظ من النوم)
        cleanup_triggers()

    async def on_disconnect(self):
        log.warning("انقطع الاتصال...")

    async def on_resumed(self):
        log.info("تم الاستئناف ✅")
        # ✅ تنظيف بعد الاستيقاظ من النوم
        cleanup_triggers()

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if ALLOWED_CHANNEL_ID and message.channel.id != ALLOWED_CHANNEL_ID:
            return
        if ALLOWED_USER_IDS and message.author.id not in ALLOWED_USER_IDS:
            return
        if message.content.strip() != TRIGGER_WORD:
            return

        uptime = datetime.now() - self.boot_time
        h, rem = divmod(int(uptime.total_seconds()), 3600)
        m, s = divmod(rem, 60)
        helper = "🟢" if is_helper_running() else "🔴"
        latency = f"{round(self.latency * 1000)}ms" if self.latency else "N/A"

        embed = discord.Embed(
            title="🎛️ لوحة التحكم عن بُعد",
            description="اختر العملية:",
            color=discord.Color.blue(),
            timestamp=datetime.now(),
        )
        embed.add_field(name="💻 النظام",   value="`Windows`",            inline=True)
        embed.add_field(name="⏱️ التشغيل", value=f"`{h}h {m}m {s}s`",    inline=True)
        embed.add_field(name="📡 البنج",    value=f"`{latency}`",         inline=True)
        embed.add_field(name="🔗 اتصالات",  value=f"`{self._connects}x`", inline=True)
        embed.add_field(name="🤖 المساعد",  value=f"{helper}",            inline=True)
        embed.add_field(name="⏳ مهلة",     value=f"`{SHUTDOWN_DELAY}s`",  inline=True)
        embed.set_footer(text=f"طلب من: {message.author}")

        view = MainMenuView(user_id=message.author.id, bot_ref=self)
        sent = await message.channel.send(embed=embed, view=view)
        view.message = sent

    async def close(self):
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        await super().close()


# ============================================================
#          التشغيل الدائم
# ============================================================
async def run_forever():
    backoff = 5
    attempt = 0

    while True:
        attempt += 1
        bot = RemoteBot(intents=intents)

        try:
            log.info(f"تشغيل... (#{attempt})")
            await bot.start(BOT_TOKEN, reconnect=True)

        except discord.LoginFailure:
            log.error("التوكن غلط!")
            sys.exit(1)

        except KeyboardInterrupt:
            break

        except (discord.ConnectionClosed, discord.GatewayNotFound) as e:
            log.error(f"Discord: {e}")

        except (OSError, ConnectionError, TimeoutError) as e:
            log.error(f"شبكة: {e}")

        except Exception as e:
            log.error(f"خطأ: {type(e).__name__}: {e}")

        finally:
            try:
                if not bot.is_closed():
                    await bot.close()
            except Exception:
                pass

        jitter = random.uniform(0, backoff * 0.3)
        wait = backoff + jitter
        log.info(f"إعادة اتصال بعد {wait:.1f}s")
        await asyncio.sleep(wait)
        backoff = min(backoff * 2, 300)
        if attempt > 1:
            backoff = 5


def main():
    if sys.platform == "win32":
        try:
            signal.signal(signal.SIGBREAK, signal.SIG_IGN)
        except Exception:
            pass

    log.info("=" * 50)
    log.info("  بوت التحكم - 24/7")
    log.info(f"  المسار: {BASE_DIR}")
    log.info("=" * 50)

    try:
        asyncio.run(run_forever())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()