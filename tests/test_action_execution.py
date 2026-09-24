"""Power-action fallback chains and the execute_action duplicate guard.

The OS commands themselves are mocked (running `shutdown`/`logoff`/
`rundll32`/lock APIs would power down the test machine), but every assertion
targets an observable outcome -- the boolean result and which trigger file was
or was not written -- not which internal helper was called. The trigger files
are real, so a regression in the fallback ordering shows up as the wrong file
existing.
"""
import types

import pytest

import bot


# ---------------------------------------------------------------- guards ---


def test_execute_action_skips_locked_action_and_cleans_up(tmp_path, monkeypatch, patch_state):
    (patch_state.tmp / "lock.trigger").write_text("lock", encoding="utf-8")
    patch_state.lockfile.write_text("sleep", encoding="utf-8")

    calls = []
    monkeypatch.setattr(bot, "ACTION_FUNC", {"sleep": lambda: calls.append("ran") or True})

    result = bot.execute_action("sleep")

    assert result is True
    assert calls == []  # the action must NOT run while locked
    assert not patch_state.lockfile.exists()          # lock cleaned up
    assert not (patch_state.tmp / "lock.trigger").exists()  # triggers cleaned up


def test_execute_action_keeps_lock_after_countdown_action(tmp_path, monkeypatch, patch_state):
    monkeypatch.setattr(bot, "ACTION_FUNC", {"sleep": lambda: True})
    assert bot.execute_action("sleep") is True
    # sleep keeps its lock until the machine wakes (on_resumed clears it).
    assert patch_state.lockfile.exists()


def test_execute_action_clears_lock_after_immediate_action(tmp_path, monkeypatch, patch_state):
    monkeypatch.setattr(bot, "ACTION_FUNC", {"lock": lambda: True})
    assert bot.execute_action("lock") is True
    assert not patch_state.lockfile.exists()
    assert bot.is_locked("lock") is False


def test_execute_action_error_clears_lock_and_reports_failure(tmp_path, monkeypatch, patch_state):
    def boom():
        raise RuntimeError("intentional test failure")

    monkeypatch.setattr(bot, "ACTION_FUNC", {"shutdown": boom})
    assert bot.execute_action("shutdown") is False
    assert not patch_state.lockfile.exists()
    assert bot.is_locked("shutdown") is False


# ----------------------------------------------------------------- lock ---


def _stub_ctypes(lock_workstation=1, raise_on_call=False):
    class _User32:
        def LockWorkStation(self):
            if raise_on_call:
                raise OSError("no user32 on this system")
            return lock_workstation

    return types.SimpleNamespace(windll=types.SimpleNamespace(user32=_User32()))


def test_do_lock_locks_immediately_via_win32_api(tmp_path, monkeypatch, patch_state):
    monkeypatch.setattr(bot, "ctypes", _stub_ctypes())
    assert bot.do_lock() is True
    assert not (patch_state.tmp / "lock.trigger").exists()


def test_do_lock_falls_back_to_trigger_when_api_returns_zero(tmp_path, monkeypatch, patch_state):
    monkeypatch.setattr(bot, "ctypes", _stub_ctypes(lock_workstation=0))
    assert bot.do_lock() is True
    assert (patch_state.tmp / "lock.trigger").read_text(encoding="utf-8") == "lock"


def test_do_lock_falls_back_to_trigger_when_api_unavailable(tmp_path, monkeypatch, patch_state):
    monkeypatch.setattr(bot, "ctypes", _stub_ctypes(raise_on_call=True))
    assert bot.do_lock() is True
    assert (patch_state.tmp / "lock.trigger").exists()


# -------------------------------------------------------------- signout ---


def test_do_signout_logs_off_active_session_without_trigger(tmp_path, monkeypatch, patch_state):
    monkeypatch.setattr(bot, "get_active_session_id", lambda: 7)
    monkeypatch.setattr(bot, "run_cmd", lambda *a, **kw: True)
    assert bot.do_signout() is True
    assert not (patch_state.tmp / "signout.trigger").exists()


def test_do_signout_falls_back_to_trigger_file(tmp_path, monkeypatch, patch_state):
    monkeypatch.setattr(bot, "get_active_session_id", lambda: None)
    monkeypatch.setattr(bot, "run_cmd", lambda *a, **kw: False)
    assert bot.do_signout() is True
    assert (patch_state.tmp / "signout.trigger").read_text(encoding="utf-8") == "signout"


# ---------------------------------------------------------------- sleep ---


def test_do_sleep_dispatches_suspend_without_trigger(tmp_path, monkeypatch, patch_state):
    monkeypatch.setattr(bot, "fire_and_forget", lambda cmd: True)
    assert bot.do_sleep() is True
    assert not (patch_state.tmp / "sleep.trigger").exists()


def test_do_sleep_falls_back_to_trigger_file(tmp_path, monkeypatch, patch_state):
    monkeypatch.setattr(bot, "fire_and_forget", lambda cmd: False)
    assert bot.do_sleep() is True
    assert (patch_state.tmp / "sleep.trigger").exists()


# ------------------------------------------------------------- shutdown ---


@pytest.mark.parametrize("func_name", ["do_shutdown", "do_restart"])
def test_power_off_actions_succeed_when_command_succeeds(func_name, tmp_path, monkeypatch, patch_state):
    monkeypatch.setattr(bot, "run_cmd", lambda *a, **kw: True)
    assert getattr(bot, func_name)() is True