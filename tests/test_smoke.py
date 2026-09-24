"""Cheap import smoke tests and cross-map consistency checks.

These fail loudly the moment the package layout or the action/trigger/handler
maps drift apart. Everything else worth testing lives in the sibling test
files.
"""
import os

import bot
import watchdog


def test_bot_imports_with_expected_test_configuration():
    assert bot.BOT_TOKEN == "test-token"
    assert bot.TRIGGER_WORD == "pc"
    assert bot.SHUTDOWN_DELAY == 10
    assert bot.ALLOWED_CHANNEL_ID == 123
    assert bot.ALLOWED_USER_IDS == [111, 222, 333]


def test_watchdog_resolves_to_bot_py_in_source_layout():
    assert watchdog.BOT_NAME == "bot.py"
    assert os.path.basename(watchdog.BOT_CMD[-1]) == "bot.py"


def test_every_action_has_a_handler_and_known_triggers():
    # Prevents a new ACTIONS entry from silently doing nothing.
    assert set(bot.ACTIONS) == set(bot.ACTION_FUNC)
    assert {"lock", "signout", "sleep"} <= set(bot.TRIGGERS)