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

**Startup order** (all at import time, before `main()`): resolve `BASE_DIR` →
reconfigure stdout/stderr to UTF-8 on Windows → read `.env` from `BASE_DIR`
(the gitignored runtime file, copied from the tracked `.env.example`) →
parse config → exit 1 if `DISCORD_BOT_TOKEN` or `TRIGGER_WORD` is empty →
configure logging.

Two consequences worth knowing:

- A blank numeric key (`ALLOWED_CHANNEL_ID`, `SHUTDOWN_DELAY`, or any
  `ALLOWED_USER_IDS` entry) raises `ValueError` during parsing, *before* the two
  emptiness checks, so an unedited `.env` copied from `.env.example` crashes with
  a traceback rather than exiting cleanly.
- Logging is configured **after** those checks, so neither the `ValueError`
  traceback nor the exit-1 condition is ever written to `bot.log`. Startup
  failures are only visible on the console or in `dist\logs\`.

`BASE_DIR` is the folder of `bot.exe` when frozen with PyInstaller, otherwise
the folder of `bot.py`. Once running, logging goes to `bot.log` (rotating,
5 MB × 3, UTF-8) plus a console handler when one exists — a `--noconsole`
build has `sys.stdout is None`, so no console handler is attached.

**Intents.** `Intents.default()` with `message_content = True`. The Message
Content privileged intent must be enabled for the bot application in Discord.

**Message handling.** For every message, the bot requires:

- author is not a bot,
- the message is in `ALLOWED_CHANNEL_ID` when that value is non-zero,
- the author's ID is in `ALLOWED_USER_IDS` when the list is non-empty,
- the message content, stripped, equals `TRIGGER_WORD` exactly (case-sensitive).

Every rejection is silent — nothing is sent back into the channel — so a
misconfigured whitelist looks identical to a typo in the trigger word.

When all checks pass, the bot sends the *control panel*: a blue embed titled
`🎛️ لوحة التحكم عن بُعد` (Remote Control Panel) with six status fields
(system, uptime, ping, connection counter, helper status, timeout) and a
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
  `SHUTDOWN_DELAY + 5` s. The countdown loop itself calls `confirm.stop()`
  when it finishes, so the ConfirmView timeout only fires if the loop is
  interrupted. A button press also calls `stop()` immediately, so the
  `MainMenuView`'s 30 s timeout only applies when nobody clicks anything.
- **Only the requesting user** can press the buttons (`interaction_check`); any
  other user gets an ephemeral `❌ مش ليك!` and the press is discarded.
- If an action fails, the bot sends a red failure embed reporting whether the
  helper (`wscript.exe`) is running and advising to reboot the machine. This
  path is reachable for **lock**, **sign-out**, and **sleep** only —
  `do_shutdown` and `do_restart` end in an unconditional `return True`, so
  they always report success even when both of their methods fail.
- A request suppressed by the duplicate guard (below) is also reported as
  success, because `execute_action` returns `True` on that branch.

**Duplicate-execution guard.** Before running an action it checks the
`.exec_lock` file and an in-memory set (`_executing`, checked by
`is_locked`). Both must name the *same* action to block it — a lock on `sleep`
does not stop `shutdown`. If the same action is already in flight it is
ignored, the bot logs a warning, and it calls `cleanup_triggers()`, which
deletes `.exec_lock` and clears `_executing`. So the guard fires once per
in-flight action, and the state it was protecting is discarded when it fires.
Otherwise `set_exec_lock` writes the lock file, the action function runs, and
the lock is released as follows:

- `lock` clears the lock as soon as the function returns — success or failure.
  It does not need the `on_resumed` path, because the machine does not suspend.
- `sleep` keeps the lock until `on_resumed()` runs `cleanup_triggers()` after
  the machine wakes. This is the case the lock file exists for: the in-memory
  set does not survive the suspend, but the file does.
- `shutdown`/`restart`/`signout` keep the lock in the normal case, on the
  assumption that the machine or session ends; any stale lock is removed by the
  next `cleanup_triggers()`.
- **any** action clears the lock if its function raises, because the `except`
  handler in `execute_action` calls `clear_exec_lock`.

A lock therefore survives a process restart (`is_locked` reads the file) but
never survives `cleanup_triggers`, which runs on every `on_ready`.

**Power action fallback chains** (each behaves the way it is written in
`ACTION_FUNC`; the last column is whether the chain can reach the VBS helper):

| Action | Methods tried, in order | Helper trigger |
|---|---|---|
| Shutdown | `shutdown /s /f /t 0` → `powershell Stop-Computer -Force` | none |
| Restart | `shutdown /r /f /t 0` → `powershell Restart-Computer -Force` | none |
| Sign out | `logoff <active session ID>` (from `WTSGetActiveConsoleSessionId`/`query session`) → write `signout.trigger` → `shutdown /l /f` → PowerShell `(Get-WmiObject Win32_OperatingSystem).Win32Shutdown(4)` | `signout.trigger` (2nd) |
| Sleep | `powercfg -h off` (disable hibernation), then `rundll32.exe powrprof.dll,SetSuspendState 0,1,0` fired without waiting (`fire_and_forget`) → write `sleep.trigger` | `sleep.trigger` — effectively unreachable, see below |
| Lock | `LockWorkStation` via `ctypes` → write `lock.trigger` → one-shot scheduled task running `rundll32.exe user32.dll,LockWorkStation` → `tsdiscon` | `lock.trigger` (2nd) |

Notes:

- **The sleep trigger is dead code in practice.** `fire_and_forget` returns
  `True` whenever `subprocess.Popen` does not raise — it never checks whether
  the machine actually suspended. So the `sleep.trigger` branch runs only if
  the process cannot be spawned at all, which is not a failure mode the rest of
  the chain can detect. Do not expect the helper to be involved in sleep.
- **Shutdown and restart always report success.** Both end in an unconditional
  `return True`, so the caller shows the success embed even when the
  `shutdown` command and the PowerShell fallback both failed. A red failure
  embed can only appear for lock, sign-out, and sleep.
- `fire_and_forget` uses `subprocess.Popen` with `CREATE_NO_WINDOW` and
  discarded output; used for sleep so the command does not block the bot while
  the machine suspends.
- `run_cmd` waits up to 10 s (15 s for the PowerShell sign-out fallback) for a
  command.
- Sign-out resolves the *active console session ID* using
  `WTSGetActiveConsoleSessionId` first, falling back to parsing `query session`.

**Trigger files.** `lock.trigger`, `signout.trigger`, and `sleep.trigger` in
`BASE_DIR`, each containing the action name. Written only as a fallback, and
`sleep.trigger` in practice never (see above). The VBS helper deletes the file
before running the command; the bot removes any leftovers (and `.exec_lock`) in
`cleanup_triggers`, which runs in `setup_hook`, on every `on_ready`, and on
`on_resumed`.

There is a race here worth knowing about: the helper deletes the trigger file
*before* launching the command, and both helper instances (Startup entry and
scheduled task) poll the same directory every 800 ms. Two instances can
therefore both pass the existence check for the same file and both run the
command. Idempotency is assumed, not enforced — for lock and sign-out that
assumption holds in practice.

**Heartbeat.** A `heartbeat` file in `BASE_DIR` is rewritten with the current
ISO timestamp every 30 seconds by a background asyncio task. The task is
created in `setup_hook` and cancelled in `close`, so no heartbeat is written
while the bot is disconnected.

**Reconnect loop.** `run_forever()` runs the client in an infinite loop. On a
failure (`LoginFailure` exits with code 1; connection/network errors are
logged), the bot closes the client, waits `backoff + jitter` seconds, and
retries. The backoff doubles up to a 300 s cap, but it is reset to 5 s as soon
as `attempt > 1`, so the cap is never reached. Simulating the loop gives waits
of roughly 5 s after the first attempt, 10–13 s after the second, and 5–6.5 s
after every attempt from the third onward. `KeyboardInterrupt` breaks the loop,
and `SIGBREAK` is ignored on Windows.

Note that each attempt constructs a **new** `RemoteBot`, so `boot_time` (the
uptime shown on the panel) and `_connects` (the connection counter) reset on
every reconnect.

### watchdog.py — optional supervisor (manual/dev mode)

The watchdog is **not** used by the service install — the WinSW service has its
own restart-on-failure policy. It is used when running the bot from source.

- Finds `bot.exe` or `bot.py` in `BASE_DIR` (in that order) at **import time**
  and starts the winner as a `subprocess.Popen` with `CREATE_NO_WINDOW`. If
  neither exists it prints an error, calls `input()` to wait for Enter, and
  exits 1. That check runs before logging is configured, so the message goes to
  the console and not to `watchdog.log`; launched via `start_hidden.vbs`
  (`pythonw`, no console) the `input()` raises `EOFError` instead, so the
  watchdog dies with a traceback rather than a prompt.
- Polls every **30 s** (`HEALTH_CHECK_INTERVAL`) and logs the uptime when
  `int(uptime_minutes) % 60 == 0`. At a 30 s poll interval that predicate is
  true twice per hour — at 60.0 and 60.5 minutes — so the hourly line is
  written **twice**, not once.
- When the bot exits, logs the return code, run duration, and restart count,
  then waits **5 s** (`RESTART_WAIT`) and restarts it. The restart counter
  starts at 1 for the *first* launch, so the log's "إعادات" (restarts) is
  really "launches".
- Fast-restart protection: if **5** launches happen within **60 s**
  (`MAX_FAST_RESTARTS`, `COOLDOWN`), it waits a full 60 s before starting the
  bot again. The check is `>= MAX_FAST_RESTARTS` on a list pruned to the last
  60 s, so the cooldown triggers on the fifth qualifying launch, not the sixth.
- The watchdog pipes the bot's stdout/stderr into `subprocess.PIPE` and never
  reads it. The bot logs to `bot.log` itself, so nothing is lost here, but a
  bot that wrote heavily to stdout could eventually block on a full pipe.
- Single-instance guard: a named kernel mutex `Global\RemoteBotWatchdog_Mutex`;
  a second watchdog exits immediately. The check is guarded by a bare
  `except Exception: pass` on Windows, so a failed mutex call lets a second
  instance through rather than stopping it.
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

Created by `install.bat`, written to the **Startup** folder
(`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\RemoteBot_Helper.vbs`),
registered as a **scheduled task** `RemoteBot_Helper` (ONLOGON) as a backup, and
started immediately during install.

Two details about the install script: the scheduled-task registration is
redirected to `nul` and its failure is explicitly downgraded to a warning
("مش مهم"), so a missing backup task does not fail the install; and the
scheduled task runs the helper under whatever account is logged on, not under
the installing administrator, because `/rl LIMITED` is used.

It embeds the install-time `dist` folder as its working directory and:

- polls every **800 ms** for `lock.trigger`, `signout.trigger`, and
  `sleep.trigger`;
- on finding one, deletes it, waits 200 ms, then runs the matching command
  hidden (`rundll32.exe user32.dll,LockWorkStation`,
  `shutdown /l /f`, `rundll32.exe powrprof.dll,SetSuspendState 0,1,0`);
- tries to append a timestamped `[HELPER] ...` line to `helper.log`.

> **`helper.log` is not reliable.** The generated `WriteLog` opens the file as
> a single-byte stream and wraps the write in `On Error Resume Next`. Its
> messages are Arabic, and a single-byte stream on a machine whose ANSI
> codepage cannot represent those characters raises an error that the handler
> swallows. Reproduced on this project: the helper creates `helper.log` and it
> stays **0 bytes**, and a failed write leaves the stream unusable for the
> lines after it. Treat an empty or missing `helper.log` as *no information*,
> not as evidence that the helper was idle. Trigger handling itself does not
> depend on logging and works regardless.

Because it is registered both in Startup and as a scheduled task, two helper
instances can run at the same time after a logon. Trigger handling is
*effectively* idempotent (delete the file, then run the command) but not
atomically so: both instances can pass the existence check before either
deletes, and then both run the command. The bot reports the helper's "running"
status with `tasklist` filtered on `imagename eq wscript.exe` plus a substring
test on the output — so it shows 🟢 for **any** `wscript.exe` on the machine,
not specifically this helper, and 🔴 if the check itself raises.

## Data flow: a command from trigger word to power action

1. Authorized user sends the exact, case-sensitive trigger word in the
   authorized channel.
2. `on_message` validates and sends the control panel embed + `MainMenuView`.
3. User clicks a button (only the requesting user is accepted; anyone else gets
   a silent ephemeral rejection).
4. **Lock** runs immediately in an executor. Everything else opens a
   `ConfirmView` countdown for `SHUTDOWN_DELAY` s; **Execute now** or
   countdown-elapsed triggers the action, **Cancel** aborts.
5. `execute_action(action)`:
   - `is_locked(action)` → if locked, log, run `cleanup_triggers()`, and return
     `True` (so the user sees success even though nothing ran);
   - writes `.exec_lock`, calls the action function from `ACTION_FUNC`;
   - the lock clears on return for `lock`, on exception for any action, and on
     `on_resumed` for `sleep`.
6. The action tries direct Windows methods. Only **lock** and **sign-out** have
   a reachable `.trigger` fallback; sleep's branch is effectively unreachable.
7. The VBS helper (if running) deletes the trigger and performs the action in
   the interactive session.

Steps 4–7 all run off the gateway thread — the countdowns are `asyncio.sleep`
and the action bodies run in the default thread executor — so the bot stays
responsive while an action is in flight.

## Files produced at runtime (BASE_DIR)

| File | Writer | Purpose |
|---|---|---|
| `bot.log` | bot | Rotating log (5 MB × 3). |
| `watchdog.log` | watchdog | Rotating log (2 MB × 2); watchdog mode only. |
| `helper.log` | VBS helper | Intended as an append-only activity log, but writes fail silently — see the helper section above. |
| `heartbeat` | bot | ISO timestamp, rewritten every 30 s once connected. |
| `lock.trigger`, `signout.trigger`, `sleep.trigger` | bot | Helper command files (fallback path; `sleep.trigger` is effectively never written). |
| `.exec_lock` | bot | Duplicate-execution guard. |
| `bot_startup.log` | `run_bot.bat` | One startup timestamp, written once before the loop. Per-restart lines go to the console. |
| `logs\` | WinSW service | Service lifecycle logs (roll-by-size 5120 KB, keep 3). |

See [Operations](OPERATIONS.md) for monitoring and troubleshooting.