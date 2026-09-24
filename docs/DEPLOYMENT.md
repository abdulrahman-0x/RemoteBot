# Deployment

There are two ways to run the bot:

1. **Windows service (recommended, production)** — `build.bat` packages
   `bot.py` into `dist\bot.exe` and `install.bat` registers a WinSW service plus
   the VBS helper. Managed via `sc` and the WinSW CLI.
2. **Manual / development** — `run_bot.bat` loops `python bot.py`, optionally
   supervised by `watchdog.py` (launched hidden via `start_hidden.vbs`).

All lifecycle scripts assume they are run from the project root (`%~dp0`).

## Prerequisites

- Windows with administrator access for the install/uninstall scripts.
- Python 3.x with `discord.py` installed, plus `pyinstaller` for the build.
  (`build.bat` runs `pip install discord.py pyinstaller --quiet` itself.)
- A `RemoteBot.exe` — the WinSW wrapper binary. This file is **not** shipped in
  the repository; download the matching `WinSW` release and rename it to
  `RemoteBot.exe` in the project root before building. The service config
  `RemoteBot.xml` must sit next to it.
- A configured `.env` in the project root (see
  [Configuration](CONFIGURATION.md)).

## Production install (service mode)

### 1. Build — `build.bat`

**Run as a normal (non-administrator) user.** The script refuses to run as
administrator.

1. Verifies `bot.py` and `.env` exist in the project root.
2. Installs Python packages (`pip install discord.py pyinstaller --quiet`).
3. Removes any previous `dist\`, `build\`, and `*.spec` artifacts.
4. Runs PyInstaller:

   ```
   pyinstaller --onefile --noconsole --name bot \
     --hidden-import discord --hidden-import aiohttp \
     --hidden-import charset_normalizer --hidden-import multidict \
     --hidden-import yarl --hidden-import frozenlist \
     --hidden-import async_timeout --hidden-import aiohappyeyeballs \
     bot.py
   ```

5. Copies `.env`, and — if they exist in the root — `RemoteBot.exe` and
   `RemoteBot.xml`, into `dist\`.

Expected result:

```
dist\
├── bot.exe          # the Discord bot, single-file, no console
├── RemoteBot.exe    # WinSW wrapper (copied from root)
├── RemoteBot.xml    # WinSW service config
└── .env             # runtime configuration
```

If `RemoteBot.exe` / `RemoteBot.xml` were missing in the root, the script prints
a warning telling you to copy them manually.

### 2. Install — `install.bat` (run as **Administrator**)

The script checks for administrator rights (`net session`), verifies that
`dist\bot.exe`, `dist\RemoteBot.exe`, `dist\RemoteBot.xml`, and `dist\.env`
exist, then works inside `dist\`:

1. **Stop and remove old state** — stops/uninstalls any existing `RemoteBot`
   service (`RemoteBot.exe stop`, `sc stop RemoteBot`, `RemoteBot.exe
   uninstall`, `sc delete RemoteBot`), kills stray `bot.exe` and `wscript.exe`
   processes, and creates a `logs\` folder.
2. **Clean stale artifacts** — deletes `*.trigger` and `heartbeat` files.
3. **Install the service** — `RemoteBot.exe install` registers the WinSW
   service from `RemoteBot.xml` (service name `RemoteBot`, display name
   *Remote Control Bot*, autostart with delayed start).
4. **Create the VBS helper** — writes `RemoteBot_Helper.vbs` to the user's
   Startup folder, creates a backup scheduled task `RemoteBot_Helper`
   (`schtasks /create /tn RemoteBot_Helper /tr wscript.exe <helper> /sc ONLOGON
   /rl LIMITED /f`), and starts it immediately via `start "" wscript.exe
   <helper>`.
5. **Start the service** — `RemoteBot.exe start`, then verifies with
   `sc query RemoteBot` that it is `RUNNING`.

On success the script prints a summary and the useful service commands.

> The helper VBS embeds the `dist` folder as its working directory, so the
> trigger files, `heartbeat`, and `helper.log` all live in `dist\`.

### 3. Verify

```bat
sc query RemoteBot          :: status
type dist\bot.log           :: bot diagnostics
type dist\logs\*.log        :: service lifecycle logs (WinSW)
```

In Discord, send the trigger word in the authorized channel; the panel should
appear.

### Service management

Commands (`sc stop/start/delete` require an administrator shell; `sc query`
does not):

| Task | Command |
|---|---|
| Check status | `sc query RemoteBot` |
| Stop the bot | `sc stop RemoteBot` |
| Start the bot | `sc start RemoteBot` |
| Delete the service | `sc delete RemoteBot` |
| WinSW status | `dist\RemoteBot.exe status` |
| WinSW install / uninstall | `dist\RemoteBot.exe install` / `dist\RemoteBot.exe uninstall` |

Restart-on-failure behavior (defined in `RemoteBot.xml`): restart after
10 / 30 / 60 seconds, with the failure counter resetting after 1 hour.

## Uninstall — `uninstall.bat` (run as **Administrator**)

1. Stops and uninstalls the service (`dist\RemoteBot.exe stop`,
   `dist\RemoteBot.exe uninstall`, `sc stop RemoteBot`, `sc delete RemoteBot`),
   and kills stray `bot.exe` processes.
2. Kills `wscript.exe` (stops the helper).
3. Deletes the Startup helper files
   (`RemoteBot_Helper.vbs`, `RemoteBot_LockHelper.vbs`).
4. Deletes the scheduled task `RemoteBot_Helper`.
5. Cleans `dist\*.trigger` and `dist\heartbeat`.

The `dist\` folder itself is left in place.

## Manual / development mode

For local testing without the service:

- **`run_bot.bat`** — loops `python bot.py`, appending start/stop timestamps to
  `bot_startup.log` and pausing 10 seconds between restarts. Run from the
  project root; requires `.env` next to `bot.py`.
- **`start_hidden.vbs`** — launches `pythonw watchdog.py` with no console
  window. The watchdog in turn starts `bot.exe` if present, otherwise
  `python bot.py`, and restarts it on exit (see
  [Architecture](ARCHITECTURE.md#watchdogpy--optional-supervisor-manualdev-mode))

  Note that the watchdog refuses to run if another watchdog instance is already
  active (named mutex `Global\RemoteBotWatchdog_Mutex`).

In manual mode there is no VBS helper unless `install.bat` has been run; the bot
still works for lock (direct `LockWorkStation`) and sign-out (`logoff`), and the
trigger/`Sleep`-related fallbacks simply go unanswered if no helper is running.

## Service configuration reference (`RemoteBot.xml`)

| Setting | Value | Meaning |
|---|---|---|
| `<id>` | `RemoteBot` | Service identifier |
| `<name>` | `Remote Control Bot` | Display name |
| `<description>` | `Discord Remote Control Bot - 24/7` | Description |
| `<executable>` | `%BASE%\bot.exe` | Program run by the service (`%BASE%` = folder of `RemoteBot.exe`, i.e. `dist\`) |
| `<onfailure>` | restart, delay 10 / 30 / 60 sec | Restart policy on crash |
| `<resetfailure>` | `1 hour` | Failure counter reset window |
| `<startmode>` | `Automatic` | Start with Windows |
| `<delayedAutoStart>` | `true` | Delayed auto-start |
| `<log mode="roll-by-size">` | threshold 5120 KB, keep 3 | Service log rotation |
| `<logpath>` | `%BASE%\logs` | Service log folder |
| `<priority>` | `Normal` | Process priority |
| `<stoptimeout>` | `15 sec` | Grace period on service stop |
| `<env>` | `PYTHONIOENCODING=utf-8` | Environment variable for the child process |

## Troubleshooting install

| Symptom | Likely cause / fix |
|---|---|
| `install.bat` refuses to run | You must run it as Administrator (right-click → *Run as administrator*). |
| `build.bat` refuses to run | It must **not** run as Administrator (it exits when `net session` succeeds). Start a normal prompt. |
| "bot.exe مش موجود!" (bot.exe missing) | Run `build.bat` first; it produces `dist\bot.exe`. |
| "RemoteBot.exe مش موجود!" | The WinSW binary was not placed in the project root before building (or not copied into `dist\`). Copy `RemoteBot.exe` into the root and rebuild, or copy it into `dist\` manually. |
| `.env` copied into `dist\` is empty/tokenless | The bot fails at startup: code 1 when `DISCORD_BOT_TOKEN` is empty, or a `ValueError` traceback from blank numeric keys (`ALLOWED_CHANNEL_ID`, `SHUTDOWN_DELAY`). Fill in every value in `.env` before running `build.bat`. |
| Service stops instantly / never reaches `RUNNING` | Check `dist\logs\` (service logs) and `dist\bot.log`. A token error (`LoginFailure`) also makes the bot exit with code 1; see [Configuration](CONFIGURATION.md#required-discord-application-setup). |
| Helper never active (panel shows 🔴) | The helper runs as `wscript.exe`. Check the Startup folder entry and the `RemoteBot_Helper` scheduled task; both were created by `install.bat`. |