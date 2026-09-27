"""Shared test setup for RemoteBot.

bot.py has import-time side effects: it reads ``.env`` from its base directory
and calls ``sys.exit(1)`` when the file is missing or the token / trigger word
is empty. A plain ``import bot`` would therefore kill the test process.

To make the module importable under test we synthesise both halves of that
check -- ``os.path.exists`` and ``open`` -- for the project's own ``.env`` path
only; every other file access is untouched. Nothing here depends on a real
``.env`` existing on disk, so the suite runs on a fresh clone where the shipped
template is ``.env.example`` and the developer's ``.env`` is untracked.
"""
import builtins
import os
import types
from io import StringIO
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ENV = os.fspath(PROJECT_ROOT / ".env")

TEST_ENV = (
    "DISCORD_BOT_TOKEN=test-token\n"
    "ALLOWED_CHANNEL_ID=123\n"
    "ALLOWED_USER_IDS=111,222,333\n"
    "SHUTDOWN_DELAY=10\n"
    "TRIGGER_WORD=pc\n"
)

_real_open = builtins.open
_real_exists = os.path.exists


def _env_aware_open(name, *args, **kwargs):
    try:
        path = os.fspath(name)
    except TypeError:
        path = str(name)
    if path == PROJECT_ENV:
        return StringIO(TEST_ENV)
    return _real_open(name, *args, **kwargs)


def _env_aware_exists(path):
    try:
        candidate = os.fspath(path)
    except TypeError:
        candidate = str(path)
    if candidate == PROJECT_ENV:
        return True
    return _real_exists(path)


# Installed before `import bot` below so the module never reads the real .env.
builtins.open = _env_aware_open
os.path.exists = _env_aware_exists

import pytest

import bot


@pytest.fixture
def patch_state(tmp_path, monkeypatch):
    """Point every trigger/lock path at a throwaway directory.

    The trigger files and the duplicate-execution lock file are plain files on
    disk, so tests exercise the real filesystem in a temp dir (state objects /
    mechanisms are real, never mocked -- a missing fixture file here would be a
    genuine test failure, not a mock slip).
    """
    monkeypatch.setattr(
        bot,
        "TRIGGERS",
        {k: str(tmp_path / f"{k}.trigger") for k in ("lock", "signout", "sleep")},
    )
    lockfile = tmp_path / ".exec_lock"
    monkeypatch.setattr(bot, "EXEC_LOCK_FILE", str(lockfile))
    monkeypatch.setattr(bot, "_executing", set())
    return types.SimpleNamespace(tmp=tmp_path, lockfile=lockfile)