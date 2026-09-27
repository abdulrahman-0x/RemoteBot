"""Configuration loading.

The README documents these behaviors: the bot exits with code 1 when ``.env``
is missing, the token is empty, or the trigger word is empty; empty numeric
values crash with ``ValueError`` instead. We verify them against a real copy
of bot.py in a throwaway directory, because the module-level guards are the
subject under test.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import bot

ENV_VARIANTS = {
    "missing": None,
    "empty_token": "DISCORD_BOT_TOKEN=\nALLOWED_CHANNEL_ID=123\nTRIGGER_WORD=pc\n",
    "empty_trigger": "DISCORD_BOT_TOKEN=token\nALLOWED_CHANNEL_ID=123\nTRIGGER_WORD=\n",
    "valid": (
        "DISCORD_BOT_TOKEN=test-token\n"
        "ALLOWED_CHANNEL_ID=123\n"
        "ALLOWED_USER_IDS=111,222\n"
        "SHUTDOWN_DELAY=10\n"
        "TRIGGER_WORD=pc\n"
    ),
}


def _copy_bot_to(tmp_path: Path) -> Path:
    dst = tmp_path / "bot.py"
    shutil.copyfile(Path(bot.__file__), dst)
    return dst


def _run_bot_import(tmp_path: Path, env: str | None, statement: str) -> subprocess.CompletedProcess:
    if env is not None:
        (tmp_path / ".env").write_text(env, encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-c", f"import bot; {statement}"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


@pytest.mark.parametrize("variant", ["missing", "empty_token", "empty_trigger"])
def test_import_exits_with_code_1_on_missing_or_incomplete_env(tmp_path, variant):
    _copy_bot_to(tmp_path)
    proc = _run_bot_import(tmp_path, ENV_VARIANTS[variant], "pass")
    assert proc.returncode == 1, proc.stderr


def test_import_crashes_with_value_error_on_empty_numeric_value(tmp_path):
    _copy_bot_to(tmp_path)
    proc = _run_bot_import(
        tmp_path,
        "DISCORD_BOT_TOKEN=token\nALLOWED_CHANNEL_ID=\nTRIGGER_WORD=pc\n",
        "pass",
    )
    assert proc.returncode != 0
    assert "ValueError" in proc.stderr


def test_import_loads_valid_config_and_exposes_values(tmp_path):
    _copy_bot_to(tmp_path)
    proc = _run_bot_import(
        tmp_path,
        ENV_VARIANTS["valid"],
        "print(bot.BOT_TOKEN, bot.TRIGGER_WORD, bot.SHUTDOWN_DELAY, "
        "bot.ALLOWED_CHANNEL_ID, bot.ALLOWED_USER_IDS)",
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().endswith("test-token pc 10 123 [111, 222]")


def test_load_env_file_returns_false_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(bot, "BASE_DIR", str(tmp_path))
    assert bot.load_env_file() is False


def test_load_env_file_loads_values_from_present_file():
    # BASE_DIR still points at the project dir; conftest serves a synthetic .env
    # there, so this holds whether or not a real .env exists on disk.
    assert bot.load_env_file() is True
    assert os.environ.get("DISCORD_BOT_TOKEN") == "test-token"
    assert os.environ.get("TRIGGER_WORD") == "pc"