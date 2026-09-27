# Deployment

There are two ways to run the bot, and they use **different** supervision — do
not run both at once, or you will have two copies competing to control the
machine and fight over the same `.exec_lock` and trigger files.

1. **Windows service (recommended, production)** — `build.bat` packages
   `bot.py` into `dist\bot.exe` and `install.bat` registers a WinSW service plus
   the VBS helper. Supervision is WinSW's restart-on-failure policy; the
   watchdog is *not* involved. Managed via `sc` and the WinSW CLI.
2. **Manual / development** — `run_bot.bat` loops `python bot.py`, optionally
   supervised by `watchdog.py` (launched hidden via `start_hidden.vbs`). No
   service, and no VBS helper unless `install.bat` has been run.

All lifecycle scripts `cd /d "%~dp0"` on their first executable line, so they
operate on their own folder no matter which directory you invoke them from.
`build.bat`, `install.bat`, and `uninstall.bat` additionally `chcp 65001` so
their Arabic output renders; `run_bot.bat` does not.

## Prerequisites

- Windows with administrator access for the install/uninstall scripts.
- Python 3.x with `discord.py` installed, plus `pyinstaller` for the build.
  (`build.bat` runs `pip install discord.py pyinstaller --quiet` itself, and
  installs them unpinned — whatever the index serves that day.) Verified
  working on **Python 3.13.8 / discord.py 2.7.1 / PyInstaller 6.22.2**.
- To run the test suite: `pytest` and `pytest-asyncio` (the latter because
  `pytest.ini` sets `asyncio_mode = auto`). Verified on **pytest 8.4.2 /
  pytest-asyncio 0.26.0**. The bot itself does not need them.
- A `RemoteBot.exe` — the WinSW wrapper binary. This file is **not** shipped in
  the repository; download the matching `WinSW` release and rename it to
  `RemoteBot.exe` in the project root before building. The service config
  `RemoteBot.xml` must sit next to it.
- A configured `.env` in the project root (see
  [Configuration](CONFIGURATION.md)).

## Production install (service mode)

### 1. Build — `build.bat`

**Run as a normal (non-administrator) user.** The script refuses to run as
administrator: it calls `net session` and bails out when that *succeeds*
(`build.bat:11-16`).

1. Verifies `bot.py` and `.env` exist in the project root, and refuses to
   continue otherwise.
2. Installs Python packages (`pip install discord.py pyinstaller --quiet`).
3. Removes any previous `dist\`, `build\`, and `*.spec` artifacts.
4. Runs PyInstaller with a set of `--hidden-import` flags covering discord.py's
   async dependency stack (`aiohttp`, `charset_normalizer`, `multidict`,
   `yarl`, `frozenlist`, `async_timeout`, `aiohappyeyeballs`) — needed because
   PyInstaller's static analysis cannot see them:

   ```
   pyinstaller --onefile --noconsole --name bot \
     --hidden-import discord --hidden-import aiohttp \
     --hidden-import charset_normalizer --hidden-import multidict \
     --hidden-import yarl --hidden-import frozenlist \
     --hidden-import async_timeout --hidden-import aiohappyeyeballs \
     bot.py
   ```

5. Copies `.env` into `dist\`, and copies `RemoteBot.exe` / `RemoteBot.xml` with
   `>nul 2>&1` — so a missing source file fails silently. It then re-checks and
   prints `❌ انسخه يدوي!` for whichever of the two is absent.

Expected result:

```
dist\
├── bot.exe          # the Discord bot, single-file, no console
├── RemoteBot.exe    # WinSW wrapper (copied from root)
├── RemoteBot.xml    # WinSW service config
└── .env             # runtime configuration
```

If `RemoteBot.exe` / `RemoteBot.xml` were missing in the root, the script prints
a warning telling you to copy them manually — and `install.bat` will then
refuse to run, so treat that warning as fatal rather than cosmetic.

Note the build **bakes your live token into `dist\.env`**. The copy is
unprotected, so treat `dist\.env` as a secret and delete the folder when done.

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
4. **Create the VBS helper** — writes `RemoteBot_Helper.vbs` to the Startup
   folder of the account running the script, registers a backup scheduled task
   `RemoteBot_Helper`
   (`schtasks /create /tn RemoteBot_Helper /tr wscript.exe <helper> /sc ONLOGON
   /rl LIMITED /f`), and starts it immediately via `start "" wscript.exe
   <helper>`. Failure to write the VBS is fatal (`exit /b 1`); failure to
   register the scheduled task is only a warning, and its output is sent to
   `nul`.
5. **Start the service** — `RemoteBot.exe start`, waits 5 s, then greps
   `sc query RemoteBot` for `RUNNING`. A miss prints a warning and calls
   `RemoteBot.exe status` but does **not** fail the install.

On success the script prints a summary and the useful service commands. Since
`%APPDATA%` resolves to the account running the script, installing as a
different administrator than the one who will log on puts the Startup entry in
the wrong profile.

> The helper VBS embeds the absolute `dist` folder as its working directory,
> so the trigger files and `helper.log` live in `dist\`. `heartbeat` is written
> by the bot, not the helper, and also lands in `dist\` because that is the
> bot's `BASE_DIR`. See [Architecture](ARCHITECTURE.md) for why `helper.log`
> is not a dependable diagnostic.

### 3. Verify

```bat
sc query RemoteBot          :: status
type dist\bot.log           :: bot diagnostics
type dist\logs\*.log        :: service lifecycle logs (WinSW)
```

`type` with a glob does not expand, so name the file explicitly
(`type dist\logs\RemoteBot.err.log`) or just open the folder. Note that startup
failures never reach `bot.log` — if the service starts and stops instantly,
read `dist\logs\` first.

In Discord, send the trigger word in the authorized channel; the panel should
appear. If it does not, remember that every rejection is silent — work through
[Operations — Troubleshooting](OPERATIONS.md#troubleshooting) in order.

### Service management

Run these from an **administrator** shell. `install.bat`'s own closing summary
labels them "useful commands (CMD as administrator)" and lists `sc query`
alongside the two that definitely require elevation; there is no non-elevated
path this project tests.

| Task | Command |
|---|---|
| Check status | `sc query RemoteBot` |
| Stop the bot | `sc stop RemoteBot` |
| Start the bot | `sc start RemoteBot` |
| Delete the service | `sc delete RemoteBot` |
| WinSW status | `dist\RemoteBot.exe status` |
| WinSW install / uninstall | `dist\RemoteBot.exe install` / `dist\RemoteBot.exe uninstall` |

Restart-on-failure behavior is defined in `RemoteBot.xml` (see the reference
table below): restart after 10 / 30 / 60 seconds, with the failure counter
resetting after 1 hour. This is WinSW's policy, not the bot's — `bot.py` has no
restart logic of its own. `sc stop`/`sc delete` do not wait for the service to
actually stop, so a `sc start` immediately afterwards can race the pending stop;
`uninstall.bat` inserts a 3 s `timeout` before uninstalling for this reason.

## Uninstall — `uninstall.bat` (run as **Administrator**)

1. Stops and uninstalls the service — the two `RemoteBot.exe` calls are guarded
   by `if exist "dist\RemoteBot.exe"`, so they are skipped if the wrapper is
   already gone, while `sc stop RemoteBot` / `sc delete RemoteBot` run
   unconditionally (`dist\RemoteBot.exe stop`,
   `dist\RemoteBot.exe uninstall`, `sc stop RemoteBot`, `sc delete RemoteBot`).
   It also kills stray `bot.exe` processes.
2. Kills `wscript.exe` (stops the helper).
3. Deletes the Startup helper files
   (`RemoteBot_Helper.vbs`, `RemoteBot_LockHelper.vbs`).
4. Deletes the scheduled task `RemoteBot_Helper`.
5. Cleans `dist\*.trigger` and `dist\heartbeat`.

Every step redirects to `nul` and none checks its exit code, so the script
prints ✅ regardless of what actually succeeded. It also does **not** remove
`bot.log`, `helper.log`, `.exec_lock`, or the WinSW `logs\` folder.

The `dist\` folder itself is left in place — including the `dist\.env` holding
your token. Delete it manually if the machine is being handed over.

## Manual / development mode

For local testing without the service:

- **`run_bot.bat`** — loops `python bot.py`, pausing 10 seconds between
  restarts. It `cd`s to its own folder, so it needs `.env` next to `bot.py`
  there. It appends **one** startup line to `bot_startup.log` before the loop;
  the per-restart start/stop lines are plain `echo` and go to the console only.
  Note that `timeout /t 10 /nobreak` needs an interactive console, so the
  10 s pause does not work when the script is piped or run non-interactively.
- **`start_hidden.vbs`** — launches `pythonw watchdog.py` with no console
  window, after pointing the working directory at its own folder. The watchdog
  in turn starts `bot.exe` if present, otherwise the same interpreter with
  `bot.py` — via `sys.executable`, which is `pythonw.exe` in this launch mode,
  so the bot also runs windowless — and restarts it on exit (see
  [Architecture](ARCHITECTURE.md#watchdogpy--optional-supervisor-manualdev-mode)).

  Note that the watchdog refuses to run if another watchdog instance is already
  active (named mutex `Global\RemoteBotWatchdog_Mutex`).

In manual mode there is no VBS helper unless `install.bat` has been run, so
`lock.trigger` and `signout.trigger` go unanswered. Lock still works through
the direct `LockWorkStation` call and sign-out through `logoff`; sleep depends
entirely on the `rundll32` suspend call, since its trigger branch is
effectively unreachable (see
[Architecture](ARCHITECTURE.md#botpy--the-discord-bot-main-process)).

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

`%BASE%` is WinSW's placeholder for the directory holding `RemoteBot.exe`.
After `build.bat` copies both files into `dist\`, that is `dist\` — which is
also the bot's `BASE_DIR`, so `bot.log`, `heartbeat`, and the trigger files all
land there.

Note that `PYTHONIOENCODING` does **not** reach the VBS helper: it is a child
process environment variable for `bot.exe` only. The helper is started by
Explorer / Task Scheduler via `wscript.exe` and has no such variable.

## Troubleshooting install

| Symptom | Likely cause / fix |
|---|---|
| `install.bat` refuses to run | You must run it as Administrator (right-click → *Run as administrator*). |
| `build.bat` refuses to run | It must **not** run as Administrator (it exits when `net session` succeeds). Start a normal prompt. |
| "bot.exe مش موجود!" (bot.exe missing) | Run `build.bat` first; it produces `dist\bot.exe`. |
| "RemoteBot.exe مش موجود!" | The WinSW binary was not placed in the project root before building (or not copied into `dist\`). Copy `RemoteBot.exe` into the root and rebuild, or copy it into `dist\` manually. |
| `.env` copied into `dist\` is empty/tokenless | The bot fails at startup. Blank numeric keys (`ALLOWED_CHANNEL_ID`, `SHUTDOWN_DELAY`) raise `ValueError` first, so you get a traceback; once those are filled, an empty `DISCORD_BOT_TOKEN` or `TRIGGER_WORD` exits with code 1. Neither reaches `bot.log` — check `dist\logs\`. Fill in every value before running `build.bat`. |
| Service stops instantly / never reaches `RUNNING` | Check `dist\logs\` (service logs) and `dist\bot.log`. A token error (`LoginFailure`) also makes the bot exit with code 1; see [Configuration](CONFIGURATION.md#required-discord-application-setup). |
| Helper never active (panel shows 🔴) | The helper runs as `wscript.exe`. Check the Startup folder entry and the `RemoteBot_Helper` scheduled task; both were created by `install.bat`. `install.bat` prints `⚠️ المهمة الاحتياطية فشلت` if the task registration failed — that is only a warning and does not stop the install. |
| `install.bat` printed `⚠️ فشل إنشاء المساعد!` | The VBS could not be written to `%APPDATA%\...\Startup` — `install.bat` writes it to a fixed path derived from the **installing** account's `%APPDATA%`, then `exit /b 1`. This is not fixed by re-running unelevated: the script requires Administrator (it checks `net session`) to register the service. Two supported routes: (1) run `install.bat` from the interactive user's own elevated prompt (UAC → *Run as administrator* on their session), so `%APPDATA%` points at the profile that will log on; or (2) if a different admin account must run the install, let it fail, then place the helper yourself — regenerate the VBS by running `install.bat` once from the target user's elevated prompt, and copy `%APPDATA%\...\Startup\RemoteBot_Helper.vbs` plus its `schtasks /create /tn RemoteBot_Helper /sc ONLOGON /rl LIMITED` registration into the intended profile. Re-verify with the 🟢/🔴 field on the panel. |
| Trigger files appear in `dist\` and nothing happens | No helper is consuming them. Confirm a `wscript.exe` process exists, and that the helper's embedded `workDir` still matches your `dist\` path (it is baked in at install time — reinstall after moving the folder). |
| `helper.log` exists but is empty | Expected, not a fault — see [Architecture](ARCHITECTURE.md). The generated VBS cannot write its Arabic messages through a single-byte stream. |
| Everything works after reinstalling, then breaks on next logon | The Startup entry and the scheduled task can both fire, leaving two helper instances racing on the same trigger files. Harmless for lock/sign-out, but expect duplicate command execution. |