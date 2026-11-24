"""-L/--log-level: what goes to stderr besides the results."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import Stub, git, new_app, real, run

BAD_CONFIG = "FGB_BOGUS=1\n"


def config_file(home: Path, text: str) -> None:
    (home / ".config").mkdir(exist_ok=True)
    (home / ".config" / "fgbrc").write_text(text)


@pytest.mark.parametrize(
    ("argv", "env", "config", "shown"),
    [
        ([], "", "", True),
        (["-L", "error"], "", "", False),
        (["--log-level=error"], "", "", False),
        (["-Lerror"], "", "", False),
        ([], "error", "", False),
        # The config file's own level applies to the problems in it
        ([], "", "FGB_LOG_LEVEL=error\n", False),
        (["-L", "warning"], "error", "", True),
    ],
)
def test_warnings_follow_the_level(
    argv: list[str],
    env: str,
    config: str,
    shown: bool,
    plain: Path,
    isolated: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    config_file(isolated, BAD_CONFIG + config)
    if env:
        monkeypatch.setenv("FGB_LOG_LEVEL", env)
    monkeypatch.chdir(plain)
    code, out, err = run(capfd, *argv, "branch", "list")
    assert code == 0
    assert "main" in out
    assert ("ignoring unknown key 'FGB_BOGUS'" in err) is shown


def test_option_after_the_command(
    plain: Path,
    isolated: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    config_file(isolated, BAD_CONFIG)
    monkeypatch.chdir(plain)
    assert run(capfd, "branch", "list", "-L", "error")[2] == ""


def test_errors_are_always_shown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    code, _, err = run(capfd, "-L", "error", "branch", "list")
    assert code == 128
    assert err == "Error: Not inside a Git repository\n"


def test_info_shows_settings_and_steps(
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(plain)
    assert run(capfd, "branch", "list")[2] == ""
    code, out, err = run(capfd, "-L", "info", "branch", "list", "-s", "refname")
    assert code == 0
    assert "main" in out
    assert "Config file: " in err
    assert "FGB_SORT_ORDER=refname (command line (-s))" in err
    assert "FGB_LOG_LEVEL=info (command line (-L))" in err
    assert "debug:" not in err
    cwd_file = tmp_path / "cwd"
    stub.pick("[spaced]")
    _, _, err = run(
        capfd, "--cwd-file", str(cwd_file), "worktree", "manage", "-L", "info"
    )
    target = real(tmp_path / "with space" / "wt")
    assert f"Repository: regular, main worktree {real(plain)}" in err
    assert "Picked [spaced] with enter" in err
    assert f"Changing to {target} (through the fgb function)" in err
    _, _, err = run(capfd, "worktree", "manage", "-L", "info")
    assert "Nothing picked in fzf" in err


def test_debug_shows_the_commands(
    plain: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    for number in range(12):
        git("branch", f"b{number:02}", cwd=plain)
    monkeypatch.chdir(plain)
    code, out, err = run(capfd, "-L", "debug", "branch", "list")
    assert code == 0
    assert "b11" in out
    assert "debug: run: git rev-parse --git-dir\n" in err
    assert "debug: exit 0\n" in err
    # The unit separator of git's format strings is shown escaped
    assert "%(refname)\\x1f" in err
    assert "\x1f" not in err
    assert "more lines)\n" in err
    stub.pick("[main]")
    _, _, err = run(capfd, "-L", "debug", "worktree", "manage")
    assert "debug: run: SHELL=/bin/sh fzf --height 80% --reverse" in err
    assert "Picked [main] with enter" in err


def test_invalid_levels(
    plain: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(plain)
    code, _, err = run(capfd, "-L", "verbose", "branch", "list")
    assert code == 2
    assert "invalid choice: 'verbose'" in err
    monkeypatch.setenv("FGB_LOG_LEVEL", "loud")
    code, _, err = run(capfd, "branch", "list")
    assert code == 1
    assert "FGB_LOG_LEVEL must be one of: error, warning, notice, info, debug" in err
    # The report still runs, and marks the value
    code, out, _ = run(capfd, "config")
    assert code == 0
    assert "loud (invalid: one of error, warning, notice, info, debug)" in out


def test_report_shows_the_source(
    plain: Path,
    isolated: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(plain)
    out = run(capfd, "config")[1]
    assert "FGB_LOG_LEVEL" in out
    assert "notice" in out
    out = run(capfd, "-L", "debug", "worktree", "list", "--show-config")[1]
    assert "command line (-L)" in out
    # A bad config line is still reported with the report's level
    config_file(isolated, BAD_CONFIG + "FGB_LOG_LEVEL=error\n")
    assert run(capfd, "config")[2] == ""
    assert "unknown key" in run(capfd, "config", "-L", "warning")[2]


def test_keep_subdir_warning_is_a_warning(
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    (plain / "src").mkdir()
    monkeypatch.chdir(plain / "src")
    stub.pick("[spaced]")
    cwd_file = tmp_path / "cwd"
    argv = ["--cwd-file", str(cwd_file), "worktree", "manage", "-k", "-L", "error"]
    code, out, err = run(capfd, *argv)
    assert code == 0
    assert cwd_file.read_text() == real(tmp_path / "with space" / "wt")
    assert out == err == ""


@pytest.mark.parametrize(
    ("argv", "env", "shown"),
    [
        ([], "", True),
        (["-L", "notice"], "", True),
        (["-L", "warning"], "", False),
        ([], "warning", False),
        (["-L", "info"], "warning", True),
    ],
)
def test_outcomes_are_notices(
    argv: list[str],
    env: str,
    shown: bool,
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    if env:
        monkeypatch.setenv("FGB_LOG_LEVEL", env)
    monkeypatch.chdir(plain)
    cwd_file = tmp_path / "cwd"
    stub.pick("[spaced]")
    code, out, err = run(
        capfd, "--cwd-file", str(cwd_file), *argv, "worktree", "manage"
    )
    target = real(tmp_path / "with space" / "wt")
    assert code == 0
    assert out == ""
    # Without a label, unlike the warnings
    assert (
        f"\nJumped to worktree: {target}, for branch 'spaced'\n" in f"\n{err}"
    ) is shown
    assert (err == "") is not shown
    assert cwd_file.read_text() == target


def test_stash_failures_are_logged(
    plain: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(plain)
    missing = "0" * 40
    new_app().restore_stash(missing, str(plain), str(plain))
    out, err = capfd.readouterr()
    assert out == ""
    assert err.startswith(
        f"Error: failed to restore the stash to the initial worktree: {real(plain)}\n"
    )
    assert f"Your changes are still saved as: {missing}" in err
