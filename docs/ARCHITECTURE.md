# Architecture

## Overview

RemoteBot is a two-process system on a Windows host:

1. **The bot** (`bot.py`, packaged as `bot.exe`) — a `discord.Client` that
   connects to Discord, renders a button control panel in a channel, and
   executes power actions on the host machine.
2. **The VBS helper** (`RemoteBot_Helper.vbs`, generated during install) — a
   `wscript.exe` process that polls *trigger files* and performs the
   machine-level action as a last-resort fallback, because some actions
   (lock, sign-out, sleep) are hard to trigger reliably from a background
   process without a console session.

Depending on how it is deployed, either a **Windows service** (WinSW, restart on
failure) or the optional **watchdog** (`watchdog.py`) keeps the bot alive.

```
                  ┌──────────────────────────────┐
                  │  Discord (authorized user)    │
                  │  sends trigger word / clicks  │
                  │  panel buttons                │
                  └──────────────┬───────────────┘
                                 │  gateway (wss)
                                 ▼
┌────────────────────────────────────────────────────────────────┐
│  bot.exe / bot.py  (BASE_DIR)                                  │
│                                                                │
│  on_message  →  access checks → control-panel embed + buttons  │
│  button      →  confirm view (countdown)  →  execute_action()  │
│                                                                │
│  • direct Win32 API / Windows commands                         │
│  • writes *.trigger files when direct methods fail             │
│  • writes heartbeat every 30 s                                 │
│  • logs to bot.log, .exec_lock guard, cleanup on connect       │
└──────┬───────────────────────────────┬─────────────────────────┘
       │                               │
       │ process supervision           │ trigger files
       ▼                               ▼
┌──────────────────────────┐  ┌──────────────────────────────────┐
│ WinSW service (prod)     │  │ VBS helper (wscript.exe)         │
│ RemoteBot.exe + .xml     │  │ Startup + scheduled task         │
│ restart-on-failure       │  │ polls lock/signout/sleep triggers│
│                                every ~800 ms, executes action  │
└──────────────────────────┘  └──────────────────────────────────┘
       │
       ▼  (manual/dev mode only)
┌──────────────────────────┐
│ watchdog.py (optional)   │
│ restarts bot, cooldown   │
└──────────────────────────┘
```

## Components

### bot.py — the Discord bot (main process)

**Startup.** The bot resolves `BASE_DIR` (the folder of `bot.exe` when frozen
with PyInstaller, otherwise the folder of `bot.py`), reads `.env` from there,
and exits with code 1 if the file is missing, `DISCORD_BOT_TOKEN` is empty, or
`TRIGGER_WORD` is empty.
On Windows it reconfigures stdout/stderr to UTF-8. Logging goes to
`bot.log` (rotating, 5 MB × 3) plus the console when one exists.

**Intents.** `Intents.default()` with `message_content = True`. The Message
Content privileged intent must be enabled for the bot application in Discord.

**Message handling.** For every message, the bot requires:

- author is not a bot,
- the message matches the configured channel (`ALLOWED_CHANNEL_ID`) when one is
  set,
- the author's ID is in `ALLOWED_USER_IDS` when the list is non-empty,
- the message content (stripped) equals the trigger word (`TRIGGER_WORD`)
  exactly.

When all checks pass, the bot sends the *control panel*: a blue embed titled
`🎛️ لوحة التحكم عن بُعد` (Remote Control Panel) with status fields (system,
uptime, ping, connection counter, helper status, timeout) and a
`MainMenuView` with six buttons.

**Buttons and the countdown flow.** Buttons are row-indexed:

| Row | Button | Style |
|---|---|---|
| 0 | 🔴 إغلاق (Shut Down) | danger |
| 0 | 🔄 إعادة تشغيل (Restart) | primary |
| 1 | 🚪 تسجيل خروج (Sign Out) | secondary |
| 1 | 💤 وضع النوم (Sleep) | secondary |
| 2 | 🔒 قفل الشاشة (Lock Screen) | secondary |
| 3 | ✖️ إلغاء (Cancel) | secondary |

- **Lock Screen** runs immediately (no countdown): it disables the menu,
  shows a *executing…* embed, and runs `execute_action("lock")` in a thread
  executor.
- **Everything else** opens a `ConfirmView` with the Arabic label plus English
  name, a countdown field ("executes within N seconds"), and two buttons:
  **⚡ تنفيذ الآن (Execute now)** and **❌ إلغاء (Cancel)**. The countdown ticks
  every second and refreshes the embed every 3 seconds (or whenever ≤ 3 seconds
  remain). When the countdown finishes (or **Execute now** is pressed), the
  action runs. **Cancel** stops the flow and swaps the embed to a green
  "cancelled" state.
- The `MainMenuView` times out after **30 s**; the `ConfirmView` after
  `SHUTDOWN_DELAY + 5` s.
- **Only the requesting user** can press the buttons (`interaction_check`); any
  other user gets an ephemeral rejection message.
- If an action fails, the bot sends a red failure embed reporting whether the
  helper (`wscript.exe`) is running and advising to reboot the machine.

**Duplicate-execution guard.** Before running an action it checks the
`.exec_lock` file and an in-memory set (`_executing`, checked by
`is_locked`). If the same action is already in flight, it is ignored (a trump
guard against e.g. sleep firing twice). Otherwise `set_exec_lock` writes the
lock file, the action function runs, and the lock is cleared:

- `lock` clears the lock immediately after success;
- `sleep` keeps the lock until `on_resumed()` runs `cleanup_triggers()`
  after the machine wakes;
- `shutdown`/`restart`/`signout` never clear the lock — the machine or
  session is expected to end, and any stale lock is removed by the next
  `cleanup_triggers()`.

**Power action fallback chains** (each behaves the way it is written in
`ACTION_FUNC`):

| Action | Methods tried, in order |
|---|---|
| Shutdown | `shutdown /s /f /t 0` → `powershell Stop-Computer -Force` |
| Restart | `shutdown /r /f /t 0` → `powershell Restart-Computer -Force` |
| Sign out | `logoff <active session ID>` (from `WTSGetActiveConsoleSessionId`/`query session`) → write `signout.trigger` → `shutdown /l /f` → PowerShell `(Get-WmiObject Win32_OperatingSystem).Win32Shutdown(4)` |
| Sleep | `powercfg -h off` (disable hibernation), then `rundll32.exe powrprof.dll,SetSuspendState 0,1,0` fired without waiting (`fire_and_forget`) → write `sleep.trigger` |
| Lock | `LockWorkStation` via `ctypes` → write `lock.trigger` → one-shot scheduled task running `rundll32.exe user32.dll,LockWorkStation` → `tsdiscon` |

Notes:

- `fire_and_forget` uses `subprocess.Popen` with `CREATE_NO_WINDOW` and
  discarded output; used for sleep so the command does not block the bot while
  the machine suspends.
- `run_cmd` waits up to 10 s (15 s for the PowerShell sign-out fallback) for a
  command.
- Sign-out resolves the *active console session ID* using
  `WTSGetActiveConsoleSessionId` first, falling back to parsing `query session`.

**Trigger files.** `lock.trigger`, `signout.trigger`, and `sleep.trigger` in
`BASE_DIR`. Written only as a fallback. The VBS helper deletes them after
acting; the bot also removes them (and `.exec_lock`) on startup, on every
`on_ready`, and on `on_resumed` (`cleanup_triggers`).

**Heartbeat.** A `heartbeat` file in `BASE_DIR` is rewritten with the current
ISO timestamp every 30 seconds by a background asyncio task.

**Reconnect loop.** `run_forever()` runs the client in an infinite loop. On a
failure (`LoginFailure` exits with code 1; connection/network errors are
logged), the bot closes the client, waits `backoff + jitter` seconds, and
retries. The backoff doubles up to 300 s but is reset to 5 s whenever more than
one attempt has happened, so in practice the delay after the first retry is
~5 s and ~10 s after the second. `KeyboardInterrupt` breaks the loop, and
`SIGBREAK` is ignored on Windows.

### watchdog.py — optional supervisor (manual/dev mode)

The watchdog is **not** used by the service install — the WinSW service has its
own restart-on-failure policy. It is used when running the bot from source.

- Finds `bot.exe` or `bot.py` in `BASE_DIR` (in that order) and starts it as a
  `subprocess.Popen` with `CREATE_NO_WINDOW`; panics if neither exists.
- Polls every **30 s** (`HEALTH_CHECK_INTERVAL`) and logs the uptime once per
  full hour.
- When the bot exits, logs the return code, run duration, and restart count,
  then waits **5 s** and restarts it.
- Fast-restart protection: if **5** restarts happen within **60 s**
  (`MAX_FAST_RESTARTS`, `COOLDOWN`), it waits a full 60 s before starting the
  bot again.
- Single-instance guard: a named kernel mutex `Global\RemoteBotWatchdog_Mutex`;
  a second watchdog exits immediately.
- Logs to `watchdog.log` (rotating, 2 MB × 2).

Launch it hidden with `start_hidden.vbs` (`pythonw watchdog.py`).

### WinSW service — production supervision

`RemoteBot.exe` (the WinSW wrapper binary, renamed) + `RemoteBot.xml` (the
matching service config — WinSW loads `RemoteBot.xml` for an executable named
`RemoteBot.exe` from the same folder). Behavior defined in the XML:

- Runs `%BASE%\bot.exe` as the service executable.
- **Auto-start** with delayed start; restarts on failure after 10 / 30 / 60
  seconds; the failure counter resets after 1 hour.
- Stop timeout 15 s; log roll-by-size at 5120 KB keeping 3 files in
  `%BASE%\logs`; `PYTHONIOENCODING=utf-8`.

Because `bot.exe` is built `--noconsole`, the WinSW log directory mostly records
service lifecycle events; the bot's own diagnostics live in `bot.log`.

### VBS helper — `RemoteBot_Helper.vbs` (generated)

Created by `install.bat`, written to:

- the **Startup** folder
  (`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\RemoteBot_Helper.vbs`), and
- a **scheduled task** `RemoteBot_Helper` (ONLOGON) as a backup, and
- started immediately during install.

It embeds `BASE_DIR` (the `dist` folder) as its working directory and:

- polls every **800 ms** for `lock.trigger`, `signout.trigger`, and
  `sleep.trigger`;
- on finding one, deletes it, waits 200 ms, then runs the matching command
  hidden (`rundll32.exe user32.dll,LockWorkStation`,
  `shutdown /l /f`, `rundll32.exe powrprof.dll,SetSuspendState 0,1,0`);
- appends a timestamped line to `helper.log`.

Because it is registered both in Startup and as a scheduled task, two helper
instances can run at the same time after a logon; trigger handling is idempotent
(delete file, run command), so this is harmless. The bot reports the helper's
"running" status simply by checking whether **any** `wscript.exe` process exists
(`tasklist`).

## Data flow: a command from trigger word to power action

1. Authorized user sends the exact trigger word in the authorized channel.
2. `on_message` validates and sends the control panel embed + `MainMenuView`.
3. User clicks a button (only the requesting user is accepted).
4. For non-immediate actions, a `ConfirmView` countdown starts
   (`SHUTDOWN_DELAY` s); **Execute now** / countdown-elapsed triggers the action;
   **Cancel** aborts.
5. `execute_action(action)`:
   - `is_locked(action)` → if locked, ignore (and clean up triggers);
   - writes `.exec_lock`, calls the action function from `ACTION_FUNC`;
   - lock clears the lock on success; sleep keeps it until `on_resumed`.
6. The action tries direct Windows methods; on failure writes a `.trigger` file.
7. The VBS helper (if running) deletes the trigger and performs the action in
   the interactive session.

## Files produced at runtime (BASE_DIR)

| File | Writer | Purpose |
|---|---|---|
| `bot.log` | bot | Rotating log (5 MB × 3). |
| `watchdog.log` | watchdog | Rotating log (2 MB × 2); watchdog mode only. |
| `helper.log` | VBS helper | Append-only helper activity log. |
| `heartbeat` | bot | ISO timestamp, rewritten every 30 s. |
| `lock.trigger`, `signout.trigger`, `sleep.trigger` | bot | Helper command files (fallback path). |
| `.exec_lock` | bot | Duplicate-execution guard. |
| `bot_startup.log` | `run_bot.bat` | Manual-mode start timestamps. |
| `logs\` | WinSW service | Service lifecycle logs (roll-by-size 5120 KB, keep 3). |

See [Operations](OPERATIONS.md) for monitoring and troubleshooting.