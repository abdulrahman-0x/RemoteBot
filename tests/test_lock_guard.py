"""Duplicate-execution guard and trigger files.

These are the bot's core safety mechanism: an in-memory set plus a lock file
prevent a power action (notably sleep) from firing twice, and persisted
trigger files survive a process restart. All state lives in real files, so the
tests operate on real files in a temp directory.
"""
import bot


def test_write_trigger_creates_file_with_action_name(tmp_path, monkeypatch, patch_state):
    assert bot.write_trigger("sleep") is True
    assert (patch_state.tmp / "sleep.trigger").read_text(encoding="utf-8") == "sleep"
    assert bot.write_trigger("lock") is True
    assert (patch_state.tmp / "lock.trigger").read_text(encoding="utf-8") == "lock"


def test_write_trigger_unknown_action_returns_false(tmp_path, monkeypatch, patch_state):
    assert bot.write_trigger("nonsense") is False


def test_write_trigger_unwritable_path_returns_false(tmp_path, monkeypatch, patch_state):
    monkeypatch.setattr(bot, "TRIGGERS", {"lock": str(patch_state.tmp / "no_such_dir" / "x.trigger")})
    assert bot.write_trigger("lock") is False


def test_is_locked_follows_in_memory_state(tmp_path, monkeypatch, patch_state):
    assert bot.is_locked("shutdown") is False
    bot._executing.add("shutdown")
    assert bot.is_locked("shutdown") is True
    assert bot.is_locked("sleep") is False


def test_is_locked_survives_restart_via_lock_file(tmp_path, monkeypatch, patch_state):
    # Sleep/wake scenario: the in-memory set is gone but the lock file remains.
    patch_state.lockfile.write_text("sleep", encoding="utf-8")
    assert bot.is_locked("sleep") is True
    assert bot.is_locked("shutdown") is False


def test_lock_file_must_match_exact_action(tmp_path, monkeypatch, patch_state):
    patch_state.lockfile.write_text("shutdown", encoding="utf-8")
    assert bot.is_locked("sleep") is False
    assert bot.is_locked("shutdown") is True


def test_clear_exec_lock_removes_file_and_memory(tmp_path, monkeypatch, patch_state):
    bot.set_exec_lock("lock")
    assert patch_state.lockfile.exists()
    assert bot.is_locked("lock") is True

    bot.clear_exec_lock("lock")

    assert not patch_state.lockfile.exists()
    assert bot.is_locked("lock") is False


def test_cleanup_triggers_removes_all_persisted_state(tmp_path, monkeypatch, patch_state):
    for name in ("lock", "signout", "sleep"):
        bot.write_trigger(name)
        assert (patch_state.tmp / f"{name}.trigger").exists()
    bot.set_exec_lock("sleep")
    assert patch_state.lockfile.exists()

    bot.cleanup_triggers()

    for name in ("lock", "signout", "sleep"):
        assert not (patch_state.tmp / f"{name}.trigger").exists()
    assert not patch_state.lockfile.exists()
    assert bot.is_locked("sleep") is False