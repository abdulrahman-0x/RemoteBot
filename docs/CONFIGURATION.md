# Configuration

All configuration lives in a single `.env` file in the bot's base directory
(`BASE_DIR`): the folder containing `bot.exe` when the bot is packaged, or the
folder containing `bot.py` when running from source.

The repository ships a **`.env.example`** template whose values are all empty; the
real `.env` is gitignored and is not committed. Copy the template, then add your
actual environment values to the copy:

```bat
copy .env.example .env
notepad .env
```

Everything below describes the `.env` you create — the bot never reads
`.env.example`, only `.env`.

> The bot **exits with code 1** if `.env` does not exist in `BASE_DIR`, if
> `DISCORD_BOT_TOKEN` is empty, or if `TRIGGER_WORD` is empty. There is no
> default token.
>
> Note: blank **numeric** keys crash *before* that check. `ALLOWED_CHANNEL_ID`
> and `SHUTDOWN_DELAY` are parsed with `int()`, so a key that is present but
> empty raises a `ValueError` at startup. Fill in real numbers or remove the
> lines — only an absent key falls back to the default. Because the parse
> happens first, an unmodified template produces a `ValueError` traceback
> rather than a clean exit-1.
>
> None of these startup failures are written to `bot.log`: logging is configured
> only after the config is parsed. They appear on the console, or in the WinSW
> `dist\logs\` for a service install.

> ⚠️ **`.env` wins over your real environment.** The loader writes each key into
> `os.environ` unconditionally, so a value in the file **overwrites** a
> same-named environment variable that is already set — including one injected
> by the service. Do not try to override configuration through the shell or the
> service environment; edit the file.

## `.env` format

The file is parsed by a small built-in loader in `bot.py`
(`load_env_file`, not `python-dotenv`):

- One `KEY=VALUE` pair per line. Lines without `=` are skipped silently.
- Only the **first** `=` on a line splits the pair, so a value may contain
  further `=` characters: `KEY=a=b` yields the key `KEY` and the value `a=b`.
- Both key and value are stripped of surrounding whitespace. A value that came
  from the file is therefore always stripped — a value inherited from a real
  environment variable is **not**, which matters for `TRIGGER_WORD`
  (see the reference table).
- Blank lines and lines whose first non-whitespace character is `#` are ignored.
  There is no `export` prefix support and no quote handling — a value keeps its
  surrounding quotes if you add them.
- A later key overrides an earlier one, and overrides the real environment.
- The file is read as UTF-8, so non-ASCII values (including an Arabic
  `TRIGGER_WORD`) work.

## Reference

| Key | Required | Default | Description |
|---|---|---|---|
| `DISCORD_BOT_TOKEN` | Yes | *(none)* | The bot token from the Discord Developer Portal. If empty or missing, the bot exits with code 1. |
| `ALLOWED_CHANNEL_ID` | No | `0` | Numeric Discord channel (snowflake) ID. When the key is absent (or `0`), the bot responds in **any** channel it can see. When set, only messages in that channel open the panel. A blank key is a startup `ValueError`. |
| `ALLOWED_USER_IDS` | No | *(empty)* | Comma-separated list of numeric Discord user IDs, e.g. `111111111111111111,222222222222222222`. Empty entries are skipped, so a trailing comma is harmless; a non-empty non-numeric entry is a startup `ValueError`. When empty, **any** user may issue commands (subject to the channel rule). When set, only those users can open the panel or press its buttons. |
| `SHUTDOWN_DELAY` | No | `10` | Seconds for the countdown shown before destructive actions (Shut Down, Restart, Sign Out, Sleep). Also displayed on the panel as the `⏳ مهلة` field. The confirmation view stays interactive for `SHUTDOWN_DELAY + 5` s. A value of `0` skips the countdown loop entirely and executes immediately. |
| `TRIGGER_WORD` | Yes | *(none)* | The exact word that opens the control panel. Required — if missing or empty, the bot exits with code 1 at startup. Matching is exact and **case-sensitive** after stripping whitespace from the message (`message.content.strip() == TRIGGER_WORD`). Only the message is stripped, so an unstripped trailing space in a real `TRIGGER_WORD` environment variable makes the trigger silently unmatchable. |

### Example

```dotenv
DISCORD_BOT_TOKEN=
ALLOWED_CHANNEL_ID=
ALLOWED_USER_IDS=
SHUTDOWN_DELAY=
TRIGGER_WORD=
```

The template shipped as `.env.example` (tracked in git; the `.env` you copy from
it is not) carries no values — every key is empty, and the file documents the
expected format for each. As shipped it is **not runnable**, and it fails twice
over:

- the blank `ALLOWED_CHANNEL_ID` / `SHUTDOWN_DELAY` values raise a `ValueError`
  at startup, and that happens *before* the emptiness checks, so you get a
  traceback rather than a clean exit;
- even once those are filled in, the empty `DISCORD_BOT_TOKEN` and
  `TRIGGER_WORD` would make the bot exit with code 1.

Replace every value before the first run.

```dotenv
DISCORD_BOT_TOKEN=YOUR_BOT_TOKEN_HERE
ALLOWED_CHANNEL_ID=987654321098765432
ALLOWED_USER_IDS=123456789012345678,234567890123456789
SHUTDOWN_DELAY=15
TRIGGER_WORD=pc
```

## Validation rules

Every rule below is enforced by `bot.py` at import time, with no error message
of its own — a violation surfaces as a raw Python `ValueError` traceback or a
bare exit code.

- `DISCORD_BOT_TOKEN` must be non-empty after the `.env` is loaded. Empty or
  missing → `sys.exit(1)`.
- `TRIGGER_WORD` must be non-empty. Empty or missing → `sys.exit(1)`.
- `ALLOWED_CHANNEL_ID` is parsed with `int()`. Absent → `0`. Present but blank
  or non-numeric → `ValueError`.
- Each non-blank entry of `ALLOWED_USER_IDS` is parsed with `int()`. Absent or
  all-blank → empty list. A non-numeric entry → `ValueError`.
- `SHUTDOWN_DELAY` is parsed with `int()`. Absent → `10`. Present but blank or
  non-numeric → `ValueError`. There is no upper bound and no minimum enforced;
  `0` means "no countdown".
- A key whose value is blank but which is **not** numeric-safe does not crash:
  `DISCORD_BOT_TOKEN=`, `ALLOWED_USER_IDS=`, and `TRIGGER_WORD=` are all read as
  empty strings.

There is no `.env` schema validation beyond the above — a misspelled key (say
`SHUTDOWN_DEALY`) is silently ignored and the default applies.

## Required Discord application setup

1. Create an application in the **Discord Developer Portal** and add a bot user.
2. Copy the **token** into `DISCORD_BOT_TOKEN`. Treat it as a secret — anyone
   with it can run the bot and receive the panel.

   > ⚠️ **`.env` is gitignored, so the token cannot be committed by accident.**
   > Only the blank `.env.example` is tracked. Note the caveat: `build.bat`
   > copies `.env` into `dist\`, and `dist\` is ignored as well — but a
   > `build.bat` that fails midway, or a manual copy, can still leave an
   > unprotected token on disk. Treat both `.env` and `dist\.env` as secrets.
3. Enable the **Message Content** privileged intent for the bot. `bot.py` sets
   `Intents.default()` plus `message_content = True`; without the intent the
   bot cannot read the trigger word and will never respond.
4. Invite the bot to your server with **Send Messages**, **View Channel**, and
   **Read Message History** in the control channel. The bot reads message
   content (needs the privileged intent from step 3), sends the panel embed,
   and edits both the panel and the countdown message.
5. Set `ALLOWED_CHANNEL_ID` to the ID of the channel you want (enable
   Developer Mode in Discord → right-click the channel → *Copy Channel ID*).
6. Set `ALLOWED_USER_IDS` to the Discord user IDs you trust (right-click the
   user → *Copy User ID*). Leaving both `ALLOWED_CHANNEL_ID` and
   `ALLOWED_USER_IDS` unset makes the panel reachable by **anyone** who can
   see the channel — the checks are skipped entirely, not defaulted to deny.
7. Set `TRIGGER_WORD` to something memorable — it is required (no default), and
   it appears verbatim in the bot's public "watching" presence
   (*اكتب: <TRIGGER_WORD>*), so anyone who can see the bot's status can
   discover it. Matching is case-sensitive.

There is no in-band confirmation when a message is rejected: a wrong channel, a
disallowed user, a wrong case, or a typo all produce silence.

## Configuration changes vs. rebuild

- **Running from source:** edit `.env` and restart `run_bot.bat` / the bot
  process.
- **Service install:** `build.bat` copies `.env` into `dist\`. To change
  configuration after install, edit **the copy inside `dist\`** (or rebuild) and
  restart the service (`sc stop RemoteBot` / `sc start RemoteBot`, see
  [Deployment](DEPLOYMENT.md)). Editing the root `.env` alone has no effect on
  an installed service.

The token is read once, at import. There is no reload path — changing `.env`
requires a process restart.