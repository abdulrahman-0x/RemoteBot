# RemoteBot — Discord Remote PC Control (Windows)

RemoteBot is a Windows utility that turns a Discord server into a remote control
for a PC. An authorized user sends a trigger word in an authorized channel, and
the bot replies with a button-based control panel that can **shut down**,
**restart**, **sign out**, **sleep**, or **lock the screen** of the machine the
bot runs on.

The bot runs as a 24/7 Windows service (packaged with PyInstaller and wrapped by
WinSW), with a VBS helper process that handles the low-level screen-lock /
sign-out / sleep actions when direct system calls fail.

> ⚠️ RemoteBot gives timed, authenticated access to power-controlling one
> Windows machine. It is intended for a personal machine you administer. Restrict
> the bot token, channel, and user IDs carefully (see
> [Configuration](docs/CONFIGURATION.md)).

---

## Features

- **Trigger-word interface** — send one configurable word (`TRIGGER_WORD`) to
  open the control panel. No slash commands, no prefixes.
- **Button control panel** — Shut Down, Restart, Sign Out, Sleep, Lock Screen,
  and Cancel, rendered as a Discord embed with buttons.
- **Countdown + confirmation** — destructive actions wait a configurable
  countdown (`SHUTDOWN_DELAY`, default 10 s) with **Execute now** and **Cancel**
  buttons. Lock Screen executes immediately.
- **Access control** — whitelist the channel and the Discord user IDs that may
  issue commands.
- **Duplicate-execution guard** — an in-memory set plus a `.exec_lock` file
  prevent an action from running twice (important for actions like sleep, where
  the command may otherwise fire repeatedly).
- **Resilience** — auto-reconnect with retry, a heartbeat file written every
  30 s, and a watchdog process that restarts the bot if it dies.
- **Power action fallback chains** — each action tries multiple methods
  (Win32 API, `shutdown`/`rundll32`/`schtasks`, PowerShell) before falling
  back; lock, sign-out, and sleep additionally write a `.trigger` file that
  the VBS helper picks up.

## Components at a glance

| Component | File | Role |
|---|---|---|
| Discord bot | `bot.py` | Connects to Discord, shows the control panel, executes power actions on the host. |
| Watchdog | `watchdog.py` | Optional supervisor; restarts `bot.exe`/`bot.py` if it exits (manual mode only). |
| Windows service | `RemoteBot.exe` + `RemoteBot.xml` | WinSW wrapper that runs `bot.exe` as an auto-start service with restart-on-failure. |
| VBS helper | generated `RemoteBot_Helper.vbs` | Polls `*.trigger` files and performs lock / sign-out / sleep as a last-resort mechanism. |
| Lifecycle scripts | `build.bat`, `install.bat`, `uninstall.bat`, `run_bot.bat`, `start_hidden.vbs` | Build, install, uninstall, and manual-run helpers. |

## Quick start

### 1. Prerequisites

- A **Windows** machine (Win32 APIs and Windows commands are used throughout).
- **Python 3.x** with `discord.py` for the source mode; `pyinstaller` only if
  you build the `.exe`.
- A **Discord bot token** with the **Message Content Intent** enabled in the
  Discord Developer Portal (`bot.py` sets `intents.message_content = True`).

### 2. Configure

Copy or edit `.env` in the project root:

```dotenv
DISCORD_BOT_TOKEN=your-bot-token-here
ALLOWED_CHANNEL_ID=123456789012345678
ALLOWED_USER_IDS=111111111111111111,222222222222222222
SHUTDOWN_DELAY=10
TRIGGER_WORD=pc
```

The bot **exits with code 1** if `.env` does not exist next to it, if
`DISCORD_BOT_TOKEN` is empty, or if `TRIGGER_WORD` is empty. Empty numeric
values (`ALLOWED_CHANNEL_ID`, `SHUTDOWN_DELAY`) crash instead (`ValueError`) —
fill them in or remove the lines. Full reference:
[Configuration](docs/CONFIGURATION.md).

### 3. Run

**Test/development (foreground):**

```bat
run_bot.bat
```

This runs `python bot.py` in an infinite loop (10 s pause between restarts) and
logs to `bot_startup.log`.

**Production (Windows service, recommended):**

```bat
build.bat        :: must NOT run as administrator; produces dist\bot.exe
install.bat      :: run as Administrator; installs the service + helper
```

See [Deployment](docs/DEPLOYMENT.md) for full details, including
[uninstall](docs/DEPLOYMENT.md#uninstall--uninstallbat-run-as-administrator).

### 4. Use

In Discord, send the configured trigger word (`TRIGGER_WORD` in `.env`) in the
authorized channel. The bot responds with the control panel:

| Button | Action | Confirmation |
|---|---|---|
| 🔴 إغلاق / Shut Down | Full power off | Countdown |
| 🔄 إعادة تشغيل / Restart | Restart the machine | Countdown |
| 🚪 تسجيل خروج / Sign Out | Log off the current session | Countdown |
| 💤 وضع النوم / Sleep | Suspend the machine | Countdown |
| 🔒 قفل الشاشة / Lock Screen | Lock the workstation | Immediate |
| ✖️ إلغاء / Cancel | Close the panel | — |

## Repository layout

```
RemoteBot/
├── bot.py              # Discord bot (main process)
├── watchdog.py         # Optional supervisor for manual mode
├── RemoteBot.exe       # WinSW service wrapper binary (bring your own)
├── RemoteBot.xml       # WinSW service configuration (must sit next to RemoteBot.exe)
├── .env                # Configuration (token, access rules, delays)
├── build.bat           # PyInstaller build → dist\bot.exe
├── install.bat         # Install as Windows service + VBS helper
├── uninstall.bat       # Remove service, helper, scheduled task
├── run_bot.bat         # Manual loop runner (python bot.py)
├── start_hidden.vbs    # Hidden launcher for watchdog.py (pythonw)
└── docs/               # Documentation (this set)
```

## Documentation index

- [Architecture](docs/ARCHITECTURE.md) — components, data flow, execution model, deployment layout
- [Configuration](docs/CONFIGURATION.md) — `.env` reference and Discord setup
- [Deployment](docs/DEPLOYMENT.md) — build, install, uninstall, service management
- [Operations](docs/OPERATIONS.md) — runtime files, logs, behavior reference, troubleshooting