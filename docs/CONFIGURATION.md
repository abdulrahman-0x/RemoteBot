# Configuration

All configuration lives in a single `.env` file in the bot's base directory
(`BASE_DIR`): the folder containing `bot.exe` when the bot is packaged, or the
folder containing `bot.py` when running from source.

> The bot **exits with code 1** if `.env` does not exist in `BASE_DIR`, if
> `DISCORD_BOT_TOKEN` is empty, or if `TRIGGER_WORD` is empty. There is no
> default token.
>
> Note: blank **numeric** keys crash before that check. `ALLOWED_CHANNEL_ID`
> and `SHUTDOWN_DELAY` are parsed with `int()`, so a key that is present but
> empty raises a `ValueError` at startup. Fill in real numbers or remove the
> lines — only an absent key falls back to the default.

## `.env` format

The file is parsed by a small built-in loader in `bot.py` (not `python-dotenv`):

- One `KEY=VALUE` pair per line.
- The first `=` in a line separates key from value; both sides are stripped of
  surrounding whitespace. Values may not contain unquoted `=` in the key part —
  `KEY=a=b` yields the value `a=b`.
- Blank lines and lines starting with `#` are ignored.
- A later key overrides an earlier one.
- The file is read as UTF-8.

## Reference

| Key | Required | Default | Description |
|---|---|---|---|
| `DISCORD_BOT_TOKEN` | Yes | *(none)* | The bot token from the Discord Developer Portal. If empty or missing, the bot exits with code 1. |
| `ALLOWED_CHANNEL_ID` | No | `0` | Numeric Discord channel (snowflake) ID. When the key is absent (or `0`), the bot responds in **any** channel it can see. When set, only messages in that channel open the panel. A blank key is a startup `ValueError`. |
| `ALLOWED_USER_IDS` | No | *(empty)* | Comma-separated list of numeric Discord user IDs, e.g. `111111111111111111,222222222222222222`. When empty, **any** user may issue commands (subject to the channel rule). When set, only those users can open the panel or press its buttons. |
| `SHUTDOWN_DELAY` | No | `10` | Seconds for the countdown shown before destructive actions (Shut Down, Restart, Sign Out, Sleep). Also displayed on the panel as the timeout. The confirmation view stays interactive for `SHUTDOWN_DELAY + 5` s. |
| `TRIGGER_WORD` | Yes | *(none)* | The exact word that opens the control panel. Required — if missing or empty, the bot exits with code 1 at startup. Matching is exact after stripping whitespace from the message (`message.content.strip() == TRIGGER_WORD`). |

### Example

```dotenv
DISCORD_BOT_TOKEN=
ALLOWED_CHANNEL_ID=
ALLOWED_USER_IDS=
SHUTDOWN_DELAY=
TRIGGER_WORD=
```

The template shipped in the repository. As shipped it is **not runnable**: the
blank `ALLOWED_CHANNEL_ID` / `SHUTDOWN_DELAY` values raise a `ValueError` at
startup. Replace every value before the first run.

```dotenv
DISCORD_BOT_TOKEN=MTk4NzY1NDMyMTA5ODc2NTQzMjEwOTg3NjU0MzIxMA
ALLOWED_CHANNEL_ID=987654321098765432
ALLOWED_USER_IDS=123456789012345678,234567890123456789
SHUTDOWN_DELAY=15
TRIGGER_WORD=pc
```

## Validation rules

- `ALLOWED_CHANNEL_ID` and each entry of `ALLOWED_USER_IDS` are parsed with
  `int()`. Non-numeric values cause a startup crash (Python `ValueError`), so
  keep them numeric.
- `SHUTDOWN_DELAY` is parsed with `int()`.
- `TRIGGER_WORD` is required: if missing or empty, the bot exits with code 1
  at startup.
- If `ALLOWED_CHANNEL_ID` is `0`, the channel check is skipped entirely.
- If `ALLOWED_USER_IDS` is empty, the user check is skipped entirely.

## Required Discord application setup

1. Create an application in the **Discord Developer Portal** and add a bot user.
2. Copy the **token** into `DISCORD_BOT_TOKEN`. Treat it as a secret — anyone
   with it can run the bot and receive the panel.
3. Enable the **Message Content** privileged intent for the bot. `bot.py` sets
   `Intents.default()` plus `message_content = True`; without the intent the
   bot cannot read the trigger word and will never respond.
4. Invite the bot to your server with at least **Send Messages** and **View
   Channel** permissions in the control channel (it sends embeds with buttons
   and edits them).
5. Set `ALLOWED_CHANNEL_ID` to the ID of the channel you want (enable
   Developer Mode in Discord → right-click the channel → *Copy Channel ID*).
6. Set `ALLOWED_USER_IDS` to the Discord user IDs you trust (right-click the
   user → *Copy User ID*).
7. Set `TRIGGER_WORD` to something memorable — it is required (no default).
   It also appears in the bot's "watching" presence text (*اكتب:
   <TRIGGER_WORD>*).

## Configuration changes vs. rebuild

- **Running from source:** edit `.env` and restart `run_bot.bat` / the bot
  process.
- **Service install:** `.env` is copied into `dist\` by `build.bat`. To change
  configuration after install, edit the copy inside `dist\` (or rebuild) and
  restart the service (`sc stop RemoteBot` / `sc start RemoteBot`, see
  [Deployment](DEPLOYMENT.md)).