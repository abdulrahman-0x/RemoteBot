# RemoteBot — Discord Remote PC Control (Windows)

RemoteBot is a Windows utility that turns a Discord server into a remote control
for a PC. An authorized user sends a trigger word in an authorized channel, and
the bot replies with a button-based control panel that can **shut down**,
**restart**, **sign out**, **sleep**, or **lock the screen** of the machine the
bot runs on.

In production it runs as a Windows service (`bot.py` packaged with PyInstaller
into `bot.exe`, wrapped by the WinSW `RemoteBot.exe` service), with a generated
VBS helper that performs screen-lock and sign-out in the interactive session
when the direct system calls fail.

> ⚠️ RemoteBot gives timed, authenticated access to power-controlling one
> Windows machine. It is intended for a personal machine you administer. Restrict
> the bot token, channel, and user IDs carefully (see
> [Configuration](docs/CONFIGURATION.md)).
>
> Two behaviours to know before you rely on it: leaving `ALLOWED_CHANNEL_ID`
> and `ALLOWED_USER_IDS` unset opens the panel to **anyone** who can see the
> channel, and **Shut Down** / **Restart** always report success to the user
> whether or not the command worked. See
> [Architecture](docs/ARCHITECTURE.md#botpy--the-discord-bot-main-process).

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
  stop the *same* action from starting twice. Note that a request the guard
  suppresses still reports success to the user, and it clears the guard state
  on its way out — see
  [Architecture](docs/ARCHITECTURE.md#botpy--the-discord-bot-main-process).
- **Resilience** — auto-reconnect with retry, a heartbeat file written every
  30 s once connected, and a watchdog process that restarts the bot if it dies.
- **Power action fallback chains** — each action tries multiple methods
  (Win32 API, `shutdown`/`rundll32`/`schtasks`, PowerShell). **Lock** and
  **sign-out** fall back to a `.trigger` file that the VBS helper picks up;
  **shut down** and **restart** have no helper fallback at all. Full table:
  [Architecture](docs/ARCHITECTURE.md#botpy--the-discord-bot-main-process).

## Components at a glance

| Component | File | Role |
|---|---|---|
| Discord bot | `bot.py` | Connects to Discord, shows the control panel, executes power actions on the host. |
| Watchdog | `watchdog.py` | Optional supervisor; restarts `bot.exe`/`bot.py` if it exits (manual mode only). |
| Windows service | `RemoteBot.exe` + `RemoteBot.xml` | WinSW wrapper that runs `bot.exe` as an auto-start service with restart-on-failure. |
| VBS helper | generated `RemoteBot_Helper.vbs` | Polls `*.trigger` files and performs lock / sign-out in the interactive session. Its `helper.log` is not a usable diagnostic — see [Architecture](docs/ARCHITECTURE.md). |
| Lifecycle scripts | `build.bat`, `install.bat`, `uninstall.bat`, `run_bot.bat`, `start_hidden.vbs` | Build, install, uninstall, and manual-run helpers. |

## Quick start

### 1. Prerequisites

- A **Windows** machine (Win32 APIs and Windows commands are used throughout).
- **Python 3.x** with `discord.py` for the source mode; `pyinstaller` only if
  you build the `.exe`. Verified on Python 3.13.8 / discord.py 2.7.1.
- A **Discord bot token** with the **Message Content Intent** enabled in the
  Discord Developer Portal (`bot.py` sets `intents.message_content = True`).
- For the production route: the **WinSW** binary, which is *not* in this
  repository — see [Deployment](docs/DEPLOYMENT.md#prerequisites).

### 2. Configure

Copy the template, then add your own values to the copy. `.env` is gitignored,
so your token stays out of version control:

```bat
copy .env.example .env
notepad .env
```

`.env` then looks like this — substitute your real values:

```dotenv
DISCORD_BOT_TOKEN=your-bot-token-here
ALLOWED_CHANNEL_ID=123456789012345678
ALLOWED_USER_IDS=111111111111111111,222222222222222222
SHUTDOWN_DELAY=10
TRIGGER_WORD=pc
```

> ⚠️ Only `.env.example` is tracked. `.env` is listed in `.gitignore`, so it
> cannot be committed by accident — but `build.bat` copies it into `dist\`, so a
> second copy of the token is created on every build. See
> [Configuration](docs/CONFIGURATION.md#required-discord-application-setup).

The bot **exits with code 1** if `.env` does not exist next to it, if
`DISCORD_BOT_TOKEN` is empty, or if `TRIGGER_WORD` is empty. Empty numeric
values (`ALLOWED_CHANNEL_ID`, `SHUTDOWN_DELAY`) raise a `ValueError` first —
fill them in or remove the lines. Neither kind of failure is recorded in
`bot.log`, because logging starts after config parsing. Full reference:
[Configuration](docs/CONFIGURATION.md).

### 3. Run

**Test/development (foreground):**

```bat
run_bot.bat
```

This runs `python bot.py` in an infinite loop (10 s pause between restarts).
`run_bot.bat` writes a single startup line to `bot_startup.log`; the
per-restart start/stop lines go to the console only.

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

| Button | Action | Confirmation | Reports failure? |
|---|---|---|---|
| 🔴 إغلاق / Shut Down | Full power off | Countdown | No — always reports success |
| 🔄 إعادة تشغيل / Restart | Restart the machine | Countdown | No — always reports success |
| 🚪 تسجيل خروج / Sign Out | Log off the current session | Countdown | Yes |
| 💤 وضع النوم / Sleep | Suspend the machine | Countdown | Yes, but see the sleep note below |
| 🔒 قفل الشاشة / Lock Screen | Lock the workstation | Immediate | Yes |
| ✖️ إلغاء / Cancel | Close the panel | — | — |

Only the user who sent the trigger word can press these buttons. Sleep has no
working helper fallback: the suspend command is fired without waiting, so the
bot cannot tell whether it worked and never asks the VBS helper for help.

## Repository layout

```
RemoteBot/
├── bot.py              # Discord bot (main process)
├── watchdog.py         # Optional supervisor for manual mode
├── RemoteBot.exe       # WinSW service wrapper binary (bring your own)
├── RemoteBot.xml       # WinSW service configuration (must sit next to RemoteBot.exe)
├── .env.example        # Config template, tracked; all values empty. Copy to .env
├── .env                # Your real config — gitignored, never committed
├── .gitignore          # Ignores .env and runtime artifacts
├── build.bat           # PyInstaller build → dist\bot.exe
├── install.bat         # Install as Windows service + VBS helper
├── uninstall.bat       # Remove service, helper, scheduled task
├── run_bot.bat         # Manual loop runner (python bot.py)
├── start_hidden.vbs    # Hidden launcher for watchdog.py (pythonw)
├── pytest.ini          # Test configuration (asyncio auto mode, testpaths=tests)
├── tests/              # Test suite (41 tests, runs offline)
└── docs/               # Documentation (this set)
```

### Tests

```bat
python -m pytest
```

Requires `pytest` and `pytest-asyncio` (see
[Deployment — Prerequisites](docs/DEPLOYMENT.md#prerequisites)). The suite
stubs the Discord gateway and mocks every OS command, so it runs offline and
never touches the machine's power state. `tests/conftest.py` synthesises both
`os.path.exists` and `open` for the project's `.env` path, so the suite runs on
a fresh clone with no `.env` at all and never reads a real one.

## Documentation index

- [Architecture](docs/ARCHITECTURE.md) — components, data flow, execution model, deployment layout
- [Configuration](docs/CONFIGURATION.md) — `.env` reference, `.env.example` template, Discord setup
- [Deployment](docs/DEPLOYMENT.md) — build, install, uninstall, service management
- [Operations](docs/OPERATIONS.md) — runtime files, logs, behavior reference, troubleshooting