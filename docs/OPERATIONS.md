# Operations

This guide covers what the bot creates at runtime, how to monitor it, and how to
diagnose common problems. All runtime files are written to the bot's base
directory (`BASE_DIR`): the folder of `bot.exe` in a service install (`dist\`),
or the folder of `bot.py` when running from source.

## Runtime files

| File / folder | Written by | Details |
|---|---|---|
| `bot.log` | `bot.py` | Rotating log, 5 MB per file, 3 backups, INFO level. UTF-8. |
| `watchdog.log` | `watchdog.py` | Rotating log, 2 MB per file, 2 backups, records bot restarts and crash return codes. Only present when the watchdog is used. |
| `helper.log` | VBS helper | Append-only, timestamped lines like `[HELPER] ...`, in `BASE_DIR` (the `dist\` folder for a service install). |
| `heartbeat` | `bot.py` | Plain-text ISO timestamp, rewritten every 30 seconds by a background task. Its presence/freshness indicates the bot process is alive. |
| `lock.trigger`, `signout.trigger`, `sleep.trigger` | `bot.py` | Command files for the VBS helper. Created only when direct execution fails. Deleted by the helper after acting, and by the bot on startup / connect / resume. In normal operation they should be absent. |
| `.exec_lock` | `bot.py` | Duplicate-execution guard. Contains the action name while an action is in flight; removed after the action completes (`lock`), otherwise at wake-up / the next startup. |
| `bot_startup.log` | `run_bot.bat` | Start/stop timestamps, only in manual loop mode. |
| `logs\` | WinSW service | Service lifecycle logs (roll-by-size, 5120 KB, 3 files). Mostly service events; the bot's own logging goes to `bot.log`. |

## How to check the bot is healthy

1. **Discord presence** — the bot shows a "watching" status of the trigger word
   (`اكتب: <TRIGGER_WORD>`).
2. **Panel status fields** — sending the trigger word shows an embed with:
   - `⏱️ التشغيل` — uptime of the bot process,
   - `📡 البنج` — gateway latency in ms,
   - `🔗 اتصالات` — how many times the client has connected (`Nx`),
   - `🤖 المساعد` — 🟢 if any `wscript.exe` process is running, else 🔴,
   - `⏳ مهلة` — the configured `SHUTDOWN_DELAY`.
3. **Heartbeat** — `heartbeat` should be no more than ~30–60 seconds old.
4. **Logs** — `bot.log` for the bot, `logs\` for the WinSW service,
   `watchdog.log` for watchdog restarts.

## Behavior reference

### Trigger handling

- Messages from bots are always ignored.
- Matching is an exact, whitespace-stripped comparison with `TRIGGER_WORD`.
- Channel and user restrictions apply as configured (see
  [Configuration](CONFIGURATION.md)). Restrictions are checked *before* the
  trigger word, but the bot silently ignores non-matching messages either way.

### Button behavior

- Only the user who opened the panel may click its buttons. A `View` times out
  after 30 s (the panel shows a "time's up — send the trigger word again"
  message) and the confirmation view after `SHUTDOWN_DELAY + 5` s.
- Lock Screen has no countdown and runs immediately.
- Shut Down, Restart, Sign Out, and Sleep show a countdown embed
  (`SHUTDOWN_DELAY` seconds) with **Execute now** and **Cancel**. The countdown
  refresh updates the embed every 3 s, and every second below 3 s remaining.
- If an action's execution reports failure, a red embed is sent showing the
  helper status (🟢/🔴) and advising a machine reboot.

### Execution

- Each action runs in a thread executor so the Discord gateway stays
  responsive.
- The duplicate guard ignores an action if the same one is already in flight
  (in-memory set and/or `.exec_lock`). When the guard trips, the bot also runs
  `cleanup_triggers()`.
- Action methods and fallback order are listed in
  [Architecture — Power action fallback chains](ARCHITECTURE.md#botpy--the-discord-bot-main-process).
  In short: direct Windows commands first, `.trigger` files as fallback, with
  the VBS helper performing the machine-level act.

### Reconnect and startup cleanup

- The bot reconnects automatically. On connection/network errors it waits ~5 s
  (with jitter) and retries; after the second failure the delay settles at ~5 s.
  A wrong token is a terminal error (`LoginFailure` → exit code 1).
- On startup, on every `on_ready`, and on `on_resumed`, the bot deletes any
  leftover `.trigger` files and `.exec_lock`. This covers the wake-from-sleep
  case: the sleep action keeps the lock until the machine resumes and
  `on_resumed` clears it.

### Logging

- `bot.log` and `watchdog.log` are written as UTF-8. The bot reconfigures its
  stdout/stderr to UTF-8 on Windows, and the service sets
  `PYTHONIOENCODING=utf-8`. `helper.log` and `bot_startup.log` are written with
  the system ANSI / console codepage — the VBS helper and `run_bot.bat` do not
  set an encoding.
- `bot.log` records connection events, reconnects, action execution, cancellations,
  and failures — search for `تنفيذ` (execute) and `خطأ` (error); the failure
  wording (`فشل`) appears in the channel embed, not the log.

## Troubleshooting

| Symptom | Checks / fix |
|---|---|
| Bot does not respond to the trigger word at all | 1) `DISCORD_BOT_TOKEN` non-empty. 2) Message Content intent enabled (see [Configuration](CONFIGURATION.md)). 3) Message sent in the configured channel, and author in `ALLOWED_USER_IDS` if set. 4) Bot invited with permissions to view/send in that channel. |
| Bot exits immediately at startup (code 1) | `.env` missing from `BASE_DIR`, `DISCORD_BOT_TOKEN` or `TRIGGER_WORD` empty, or a blank numeric key (`ALLOWED_CHANNEL_ID`, `SHUTDOWN_DELAY`) raising `ValueError` at startup — the traceback goes to the console / `dist\logs\`, not `bot.log`. In a service install, `BASE_DIR` is `dist\` — edit the `.env` copy there. |
| `LoginFailure` in `bot.log` | Token is wrong or the bot was regenerated. Correct `DISCORD_BOT_TOKEN` and restart. |
| Helper shows 🔴 on the panel | No `wscript.exe` running. Re-run the helper from the Startup folder, or reinstall (`install.bat`). |
| Nothing happens after the countdown; red "فشل" embed | The power action failed. Check `bot.log` for the failing step and whether the helper is running. Reboot the machine and retry as advised by the message. |
| Bot keeps restarting quickly | In service mode, `RemoteBot.xml` restarts after 10/30/60 s. In watchdog mode the fast-restart guard pauses for 60 s after 5 restarts in a minute (`watchdog.log`). Look for the underlying crash in `bot.log`. |
| Sleep does not work | The bot disables hibernation (`powercfg -h off`) and suspends via `rundll32` fire-and-forget; if that fails it writes `sleep.trigger` for the helper. Make sure the helper runs and check `helper.log`. |
| Lock does not work | The bot tries `LockWorkStation` → `lock.trigger` → a one-shot scheduled task → `tsdiscon`. Each step relies on an interactive session; check `bot.log` for the `>>> قفل` attempt, and `helper.log` if the trigger path ran. |
| Garbled/non-UTF8 log output | The encoding overrides are automatic on Windows; in manual mode ensure the console codepage (chcp 65001) if you run the scripts in `cmd`. |
| Trigger files accumulate | `cleanup_triggers()` removes them on startup/connect/resume; a leftover file usually means the bot stopped while one was pending. Deleting them manually is safe. |