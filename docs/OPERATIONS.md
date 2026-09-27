# Operations

This guide covers what the bot creates at runtime, how to monitor it, and how to
diagnose common problems. All runtime files are written to the bot's base
directory (`BASE_DIR`): the folder of `bot.exe` in a service install (`dist\`),
or the folder of `bot.py` when running from source.

Three things to internalize before reading the tables below, because they change
how you should read the evidence:

- **Startup failures are not in `bot.log`.** Logging is configured after the
  config is parsed, so a `ValueError` or an exit-1 never reaches it.
- **A green "✅ تم التنفيذ!" is not proof of anything** for Shut Down and
  Restart, which return success unconditionally.
- **An empty `helper.log` is not proof of an idle helper** — its writes fail
  silently by design of the generated script.

## Runtime files

| File / folder | Written by | Details |
|---|---|---|
| `bot.log` | `bot.py` | Rotating log, 5 MB per file, 3 backups, INFO level. UTF-8. |
| `watchdog.log` | `watchdog.py` | Rotating log, 2 MB per file, 2 backups, records bot restarts and crash return codes. Only present when the watchdog is used. |
| `helper.log` | VBS helper | Intended as an append-only log of `[HELPER] …` lines, but the writes fail silently on a machine whose ANSI codepage cannot represent the Arabic messages — the file is created and stays 0 bytes. An empty `helper.log` means *no information*, not "helper was idle". See [Architecture](ARCHITECTURE.md). |
| `heartbeat` | `bot.py` | Plain-text ISO timestamp, rewritten every 30 seconds by a background task. Only written while connected — the task starts in `setup_hook` and is cancelled in `close`. Its presence/freshness indicates the bot is connected. |
| `lock.trigger`, `signout.trigger` | `bot.py` | Command files for the VBS helper, written only when the direct method for lock / sign-out fails. Deleted by the helper after acting, and by the bot on startup / connect / resume. In normal operation they should be absent. |
| `sleep.trigger` | `bot.py` | Effectively never written: the suspend command is fired with `fire_and_forget`, which reports success as soon as the process is spawned, so the fallback branch is not reached. Do not expect to find this file or the helper acting on it. |
| `.exec_lock` | `bot.py` | Duplicate-execution guard, containing the action name while an action is in flight. Removed when `lock` returns (success or failure), on exception for any action, and at wake-up / next startup for the rest. |
| `bot_startup.log` | `run_bot.bat` | A single startup timestamp, written once before the loop. The per-restart lines go to the console, not this file. Manual loop mode only. |
| `logs\` | WinSW service | Service lifecycle logs (roll-by-size, 5120 KB, 3 files). Mostly service events; the bot's own logging goes to `bot.log`. |

## How to check the bot is healthy

1. **Discord presence** — the bot shows a "watching" status of the trigger word
   (`اكتب: <TRIGGER_WORD>`).
2. **Panel status fields** — sending the trigger word shows an embed with:
   - `⏱️ التشغيل` — uptime of the current Discord **client session**, not of the
     OS process. `run_forever` builds a new client on every reconnect, so this
     resets to `0h 0m 0s` on a process that has been up for days.
   - `📡 البنج` — gateway latency in ms, or `N/A` when not connected.
   - `🔗 اتصالات` — how many times the current client has connected. Rendered
     with no space, e.g. `1x`. Resets with the client, like uptime.
   - `🤖 المساعد` — 🟢 if **any** `wscript.exe` process is running, else 🔴.
     This is a `tasklist` substring match, so an unrelated Windows Script host
     also reads as 🟢.
   - `⏳ مهلة` — the configured `SHUTDOWN_DELAY`.
3. **Heartbeat** — while connected, `heartbeat` should be no more than ~30–60
   seconds old. A stale timestamp with a fresh file mtime is not possible (the
   file is rewritten in place), so use the *contents*, not the mtime. A missing
   file means no heartbeat has been written in this process. That is what the
   absence of the file tells you — not *why*. The write is best-effort: the loop
   body swallows every exception (`except Exception: pass`), so a `BASE_DIR` that
   is not writable produces the same symptom as a bot that never connected.
   Check connection state and `bot.log` to tell them apart.
4. **Logs** — `bot.log` for the bot, `logs\` for the WinSW service,
   `watchdog.log` for watchdog restarts.

## Behavior reference

### Trigger handling

- Messages from bots are always ignored.
- Matching is an exact, **case-sensitive**, whitespace-stripped comparison with
  `TRIGGER_WORD` — `pc` will not match `PC`.
- Channel and user restrictions apply as configured (see
  [Configuration](CONFIGURATION.md)). Restrictions are checked *before* the
  trigger word, but the bot silently ignores non-matching messages either way.
  There is no feedback in-channel when a message is rejected, so a
  non-responsive bot looks identical to a typo.

### Button behavior

- Only the user who opened the panel may click its buttons. A `View` times out
  after 30 s (the panel shows a "time's up — send the trigger word again"
  message, but only if the panel was never clicked — a click stops the view
  first) and the confirmation view after `SHUTDOWN_DELAY + 5` s.
- Lock Screen has no countdown and runs immediately.
- Shut Down, Restart, Sign Out, and Sleep show a countdown embed
  (`SHUTDOWN_DELAY` seconds) with **Execute now** and **Cancel**. The countdown
  refresh updates the embed every 3 s, and every second below 3 s remaining.
- If an action's execution reports failure, a red embed is sent showing the
  helper status (🟢/🔴) and advising a machine reboot. This is reachable for
  lock, sign-out, and sleep only: `do_shutdown` and `do_restart` end in an
  unconditional `return True`, so they always report success.

### Execution

- Each action runs in a thread executor so the Discord gateway stays
  responsive.
- The duplicate guard blocks a request only when **both** the in-memory set and
  `.exec_lock` name the same action; a lock on `sleep` does not block
  `shutdown`. When it trips, the bot logs a warning, runs `cleanup_triggers()`
  — which deletes `.exec_lock` and clears the in-memory set — and **returns
  success**, so the user sees "✅ تم التنفيذ!" for an action that never ran.
  Treat a second identical click as *not confirmed*, not as a second success.
- Action methods and fallback order are listed under "Power action fallback
  chains" in [Architecture](ARCHITECTURE.md#botpy--the-discord-bot-main-process).
  In short: direct Windows commands first; `.trigger` files as a fallback for
  **lock** and **sign-out** only, with the VBS helper performing the
  machine-level act.

### Reconnect and startup cleanup

- The bot reconnects automatically. The wait is `backoff + up to 30 %` jitter.
  Because the backoff is reset to 5 s as soon as a second attempt has been
  made, the observed waits are ~5 s after the first attempt, 10–13 s after the
  second, and 5–6.5 s from the third attempt onward — the 300 s cap is never
  reached. A wrong token is a terminal error (`LoginFailure` → exit code 1).
- On startup (`setup_hook`), on every `on_ready`, and on `on_resumed`, the bot
  deletes any leftover `.trigger` files and `.exec_lock`, and clears the
  in-memory `_executing` set. This covers the wake-from-sleep case: the sleep
  action keeps the lock until the machine resumes and `on_resumed` clears it.
- `on_disconnect` only logs a warning — no cleanup and no state change.

### Logging

- `bot.log` and `watchdog.log` are written as UTF-8. The bot reconfigures its
  stdout/stderr to UTF-8 on Windows, and the service sets
  `PYTHONIOENCODING=utf-8`. `bot_startup.log` is written by `run_bot.bat`,
  which does not `chcp 65001`, so it lands in the console codepage.
  `helper.log` is opened by the generated VBS as a **single-byte** stream, and
  its messages are Arabic — on a machine whose ANSI codepage cannot represent
  them, every write fails and `On Error Resume Next` hides it, so expect the
  file to exist and be empty.
- `bot.log` records connection events, reconnects, action execution,
  cancellations, and failures — search for `تنفيذ` (execute) and `خطأ` (error).
  The failure wording (`فشل`) appears only in the channel embed, never in the
  log. Note that a bad token logs `التوكن غلط!`: the string `LoginFailure` is
  the exception class name and is never written to the log.

## Troubleshooting

| Symptom | Checks / fix |
|---|---|
| Bot does not respond to the trigger word at all | 1) `DISCORD_BOT_TOKEN` non-empty. 2) Message Content intent enabled (see [Configuration](CONFIGURATION.md)). 3) Message sent in the configured channel, and author in `ALLOWED_USER_IDS` if set. 4) Bot invited with permissions to view/send in that channel. 5) The message matches exactly, including case — `TRIGGER_WORD` is not case-folded. Because every rejection is silent, work through this list in order. |
| Bot exits immediately at startup (code 1) | `.env` missing from `BASE_DIR` (create it with `copy .env.example .env`), `DISCORD_BOT_TOKEN` or `TRIGGER_WORD` empty, or a blank numeric key (`ALLOWED_CHANNEL_ID`, `SHUTDOWN_DELAY`) raising `ValueError` at startup. A `ValueError` fires *before* the exit-1 checks, so a traceback in the console / `dist\logs\` means a blank numeric key, not a missing token. Neither the traceback nor the exit message reaches `bot.log` — logging is configured after these checks. In a service install, `BASE_DIR` is `dist\` — edit the `.env` copy there. |
| `التوكن غلط!` in `bot.log` | Token is wrong or the bot was regenerated. Correct `DISCORD_BOT_TOKEN` and restart. |
| Helper shows 🔴 on the panel | Two causes, because `is_helper_running` returns `False` for both: either no `wscript.exe` is running, **or** the `tasklist` check itself failed (5 s timeout, `tasklist` unavailable, or any other exception — the whole body is wrapped in `except Exception: return False`). So 🔴 does **not** prove that no such process is running; confirm with `tasklist /fi "imagename eq wscript.exe"` by hand. Re-run the helper from the Startup folder, or reinstall (`install.bat`). The check matches *any* `wscript.exe`, so 🟢 is not proof the helper is healthy either. |
| Nothing happens after the countdown; red "فشل" embed | The power action failed, and the action was one of lock / sign-out / sleep. Check `bot.log` for the failing step and whether the helper is running. Reboot the machine and retry as advised by the message. Note that a *green* "تم التنفيذ!" for Shut Down or Restart proves nothing — those two always report success. |
| Bot keeps restarting quickly | In service mode, `RemoteBot.xml` restarts after 10/30/60 s. In watchdog mode the fast-restart guard pauses for 60 s after 5 restarts within 60 s (`watchdog.log`). Look for the underlying crash in `bot.log`. |
| Sleep does not work | The bot disables hibernation (`powercfg -h off`) and suspends via a fire-and-forget `rundll32` call. Because that call reports success as soon as the process spawns, there is effectively **no** trigger fallback for sleep and the helper is not involved. Suspend from a `rundll32` launched out of session 0 is the usual failure; test manually. |
| Lock does not work | The bot tries `LockWorkStation` → `lock.trigger` → a one-shot scheduled task → `tsdiscon`. Each step relies on an interactive session; check `bot.log` for the `>>> قفل` attempt. Do **not** rely on `helper.log` to confirm the trigger ran — it will be empty. |
| Garbled/non-UTF8 log output | The encoding overrides are automatic on Windows; in manual mode ensure the console codepage (chcp 65001) if you run the scripts in `cmd`. Note `helper.log` cannot be fixed this way — it is written by the VBS helper through a single-byte stream, so its Arabic lines are simply lost. |
| Trigger files accumulate | `cleanup_triggers()` removes them on startup/connect/resume; a leftover file usually means the bot stopped while one was pending, or that no helper is running to consume it. Deleting them manually is safe. `sleep.trigger` in particular indicates an unexpected spawn failure, since that branch is otherwise unreachable. |
| `ValueError` on startup | A numeric key is present but blank: `ALLOWED_CHANNEL_ID`, `SHUTDOWN_DELAY`, or any entry of `ALLOWED_USER_IDS`. Fill in real numbers or delete the line. |
| `watchdog.log` says the bot is running for 0 minutes, repeatedly | The watchdog resolves `bot.exe`/`bot.py` at import time and restarts it in a loop; combined with a bot that exits immediately, it will log a long run duration only if the process actually stayed up. Check `bot.log` for the real cause. |