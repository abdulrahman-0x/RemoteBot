"""Discord-facing access control: who may open the panel and who may confirm
a destructive action.

The Discord client and gateway are stubbed with minimal fakes (that is an
external boundary -- Rule 2); what is asserted is observable behavior: whether
a panel message was sent, whether a stranger is rejected, and what rejection
reply/flag they get.
"""
import pytest

import bot


class _User:
    def __init__(self, user_id, is_bot=False):
        self.id = user_id
        self.bot = is_bot


class _SentMessage:
    async def edit(self, **kwargs):
        pass


class _Channel:
    def __init__(self, channel_id):
        self.id = channel_id
        self.sent = []

    async def send(self, *, embed=None, view=None, **kwargs):
        sent = _SentMessage()
        self.sent.append((embed, view))
        return sent


class _Message:
    def __init__(self, author, channel, content):
        self.author = author
        self.channel = channel
        self.content = content


def _make_bot():
    return bot.RemoteBot(intents=bot.intents)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(bot, "ALLOWED_CHANNEL_ID", 123)
    monkeypatch.setattr(bot, "ALLOWED_USER_IDS", [111, 222, 333])
    monkeypatch.setattr(bot, "is_helper_running", lambda: True)


@pytest.fixture
def no_latency(monkeypatch):
    # Unconnected client: make the latency read return a falsy value so the
    # embed falls back to "N/A" instead of touching the gateway connection.
    monkeypatch.setattr(bot.RemoteBot, "latency", property(lambda self: None))


async def test_trigger_word_opens_panel_for_allowed_user_in_allowed_channel(configured, no_latency):
    bot_instance = _make_bot()
    channel = _Channel(123)
    await bot_instance.on_message(_Message(_User(111), channel, "pc"))

    assert len(channel.sent) == 1
    embed, view = channel.sent[0]
    assert embed.title == "🎛️ لوحة التحكم عن بُعد"
    assert view.user_id == 111
    assert view.message is not None


@pytest.mark.parametrize(
    ("user_id", "channel_id", "content"),
    [
        (999, 123, "pc"),          # user not whitelisted
        (111, 456, "pc"),          # channel not whitelisted
        (111, 123, "PC"),          # case matters, trigger is exact
        (111, 123, "hello"),       # wrong word
        (111, 123, ""),            # empty message
    ],
)
async def test_trigger_ignored_when_not_authorized(user_id, channel_id, content, configured, no_latency):
    bot_instance = _make_bot()
    channel = _Channel(channel_id)
    await bot_instance.on_message(_Message(_User(user_id), channel, content))
    assert channel.sent == []


async def test_trigger_ignored_for_bot_messages(configured, no_latency):
    bot_instance = _make_bot()
    channel = _Channel(123)
    await bot_instance.on_message(_Message(_User(111, is_bot=True), channel, "pc"))
    assert channel.sent == []


async def test_trigger_works_anywhere_when_no_whitelist_configured(monkeypatch, no_latency):
    # Documented open-by-default behavior: empty user/channel settings allow anyone.
    monkeypatch.setattr(bot, "ALLOWED_CHANNEL_ID", 0)
    monkeypatch.setattr(bot, "ALLOWED_USER_IDS", [])
    monkeypatch.setattr(bot, "is_helper_running", lambda: True)

    bot_instance = _make_bot()
    channel = _Channel(999)
    await bot_instance.on_message(_Message(_User(1), channel, "pc"))

    assert len(channel.sent) == 1


# ------------------------------------------------------- confirm buttons ---


class _TestResponse:
    def __init__(self):
        self.sent = []

    async def send_message(self, content=None, **kwargs):
        self.sent.append((content, kwargs))


class _TestInteraction:
    def __init__(self, user_id):
        self.user = _User(user_id)
        self.response = _TestResponse()


async def test_confirm_view_rejects_unrelated_user_with_ephemeral_note():
    view = bot.ConfirmView("shutdown", user_id=111)
    interaction = _TestInteraction(999)

    assert await view.interaction_check(interaction) is False
    assert len(interaction.response.sent) == 1
    content, kwargs = interaction.response.sent[0]
    assert content == "❌ مش ليك!"
    assert kwargs.get("ephemeral") is True


async def test_confirm_view_accepts_owner_without_sending_anything():
    view = bot.ConfirmView("shutdown", user_id=111)
    interaction = _TestInteraction(111)

    assert await view.interaction_check(interaction) is True
    assert interaction.response.sent == []