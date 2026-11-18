"""The settings report: the config command and --show-config."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from conftest import Stub, fgb, real, run


def setting_line(out: str, setting: str) -> str:
    return next(line for line in out.splitlines() if line.startswith(f"  {setting} "))


def source_of(out: str, setting: str) -> tuple[str, str]:
    """(value, source) of a row of the Settings table."""
    fields = re.split(r"\s{2,}", setting_line(out, setting).strip())
    return fields[1], fields[2]


def row(out: str, name: str) -> str:
    """The value of a Command line or Runtime row."""
    line = next(line for line in out.splitlines() if line.startswith(f"  {name}  "))
    return line[len(f"  {name}") :].strip()


def write_config(home: Path, text: str) -> Path:
    (home / ".config").mkdir(exist_ok=True)
    path = home / ".config" / "fgbrc"
    path.write_text(text)
    return path


def test_defaults(
    tmp_path: Path,
    isolated: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    code, out, err = run(capfd, "config")
    assert code == 0
    assert err == ""
    config = isolated / ".config" / "fgbrc"
    assert f"Config file: {config} (default location, not found)" in out
    assert source_of(out, "FGB_SORT_ORDER") == ("-committerdate", "default")
    assert source_of(out, "FGB_BINDKEY_NEW_BRANCH_VERBOSE") == ("alt-N", "default")
    assert source_of(out, "FGB_FZF_OPTS") == ("(built-in options)", "default")
    assert source_of(out, "FGB_COLOR") == ("auto", "default")
    # Every setting is listed
    for setting in fgb.SETTING_OPTIONS:
        assert setting_line(out, setting)
    # config shows no command line section, and outside a repo no repo rows
    assert "Command line" not in out
    assert row(out, "repository") == "none (not inside a Git repository)"


def test_every_source(
    plain: Path,
    isolated: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    write_config(
        isolated,
        "# settings\n"
        "FGB_DATE_FORMAT=committerdate:short\n"
        "FGB_AUTHOR_FORMAT=authoremail\n"
        "FGB_BINDKEY_INFO=\n"
        "FGB_SORT_ORDER=refname\n",
    )
    monkeypatch.setenv("FGB_AUTHOR_FORMAT", "committeremail")
    monkeypatch.setenv("FGB_SORT_ORDER", "")
    monkeypatch.setenv("FGB_WT_PATH_DISPLAY", "")
    monkeypatch.chdir(plain)
    out = run(capfd, "config", "-d", "authordate:iso")[1]
    assert source_of(out, "FGB_DATE_FORMAT") == ("authordate:iso", "command line (-d)")
    assert source_of(out, "FGB_AUTHOR_FORMAT") == ("committeremail", "environment")
    assert source_of(out, "FGB_SORT_ORDER") == (
        "refname",
        "config file (fgbrc:5) (empty in the environment)",
    )
    assert source_of(out, "FGB_BINDKEY_INFO") == (
        "ctrl-o",
        "default (empty in fgbrc:4)",
    )
    assert source_of(out, "FGB_WT_PATH_DISPLAY") == (
        "tilde",
        "default (empty in the environment)",
    )


def test_explicit_config_file(
    tmp_path: Path,
    plain: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    other = tmp_path / "other.conf"
    other.write_text("FGB_COLOR=never\n")
    monkeypatch.chdir(plain)
    out = run(capfd, "config", "--config", str(other))[1]
    assert f"Config file: {other} (--config, found)" in out
    assert source_of(out, "FGB_COLOR") == ("never", "config file (other.conf:1)")
    monkeypatch.setenv("FGB_CONFIG", str(other))
    assert f"({fgb.ENV_CONFIG}, found)" in run(capfd, "config")[1]


def test_invalid_values_are_shown_not_fatal(
    plain: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FGB_WT_PATH_DISPLAY", "bogus")
    monkeypatch.setenv("FGB_COLOR", "rainbow")
    monkeypatch.chdir(plain)
    code, out, _ = run(capfd, "config")
    assert code == 0
    assert "bogus (invalid: one of tilde, absolute" in out
    assert "rainbow (invalid: one of auto, always, never)" in out
    # while the real commands still refuse them
    assert run(capfd, "worktree", "list")[0] == 1


def test_show_config_on_a_full_command(
    plain: Path,
    stub: Stub,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(plain)
    code, out, _ = run(
        capfd,
        "worktree",
        "add",
        "-a",
        "-c",
        "-s",
        "-refname",
        "my",
        "query",
        "--show-config",
    )
    assert code == 0
    # Nothing ran: no picker, no worktree
    assert stub.calls() == []
    assert source_of(out, "FGB_SORT_ORDER") == ("-refname", "command line (-s)")
    assert row(out, "command").endswith(" worktree add")
    assert row(out, "branches") == "all (-a)"
    assert row(out, "worktree path") == "derived (-c)"
    assert row(out, "delete") == "asks first"
    assert row(out, "fzf query") == "my query"


@pytest.mark.parametrize(
    "argv",
    [
        ["--show-config", "branch", "list"],
        ["branch", "list", "--show-config"],
        ["branch", "manage", "-f", "--show-config", "--", "-x"],
        ["init", "zsh", "--show-config"],
    ],
)
def test_show_config_anywhere(
    argv: list[str],
    plain: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(plain)
    code, out, _ = run(capfd, *argv)
    assert code == 0
    assert out.startswith(f"fzf-git-branches {fgb.__version__}\n")
    assert "Command line" in out
    assert stub.calls() == []


def test_show_config_works_outside_a_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    code, out, _ = run(capfd, "worktree", "manage", "--show-config")
    assert code == 0
    assert row(out, "repository") == "none (not inside a Git repository)"


def test_runtime_rows(
    bare: Path,
    stub: Stub,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("COLUMNS", "123")
    monkeypatch.setenv("FGB_WT_BASE_PATH_BARE", "../w/{repo_name_short}")
    monkeypatch.chdir(bare / "wt" / "main")
    out = run(capfd, "--cwd-file", str(tmp_path / "cwd"), "config")[1]
    assert row(out, "terminal width") == "123 columns (COLUMNS)"
    assert row(out, "colors") == "off for output (stdout is not a terminal), on in fzf"
    assert row(out, "fzf").endswith(" 0.75.0")
    assert row(out, "fzf runs commands with") == "/bin/sh (built-in options)"
    assert row(out, "directory changes") == "by the fgb shell function"
    assert row(out, "repository") == "bare"
    assert row(out, "main worktree") == real(bare)
    assert row(out, "worktree base") == (
        f"{real(tmp_path)}/w/hub (from FGB_WT_BASE_PATH_BARE=../w/{{repo_name_short}})"
    )
    assert row(out, "worktrees") == "1"
    assert not (tmp_path / "cwd").exists()


def test_runtime_rows_variants(
    plain: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("FGB_FZF_OPTS", "--ansi")
    monkeypatch.setenv("SHELL", "/usr/bin/fish")
    # git but no fzf on PATH
    only_git = tmp_path / "only-git"
    only_git.mkdir()
    (only_git / "git").symlink_to(shutil.which("git") or "git")
    monkeypatch.setenv("PATH", str(only_git))
    monkeypatch.chdir(plain)
    out = run(capfd, "config")[1]
    assert row(out, "colors") == "off (NO_COLOR is set)"
    assert row(out, "fzf").startswith("not found")
    assert (
        row(out, "fzf runs commands with")
        == "$SHELL (/usr/bin/fish), as FGB_FZF_OPTS is set"
    )
    assert row(out, "directory changes") == "printed as a cd hint (not run through fgb)"
    assert row(out, "repository") == "regular"
    assert row(out, "worktree base").startswith(f"{real(plain)}/.git/wt ")


def test_submodule_row(
    submodule: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(submodule / "sub")
    out = run(capfd, "config")[1]
    assert row(out, "repository").startswith("submodule of ")
    assert row(out, "worktree commands") == "refused for submodules"


def test_colored_sources(
    plain: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FGB_COLOR", "always")
    monkeypatch.chdir(plain)
    out = run(capfd, "config", "-s", "refname")[1]
    assert "\033[32mcommand line (-s)\033[0m" in out
    assert "\033[33menvironment\033[0m" in out
    assert "\033[1mSettings\033[0m" in out


def test_config_usage_errors(
    plain: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(plain)
    assert run(capfd, "config", "-r")[0] == 2
    assert run(capfd, "config", "query")[0] == 2
    assert "--show-config" in run(capfd, "worktree", "total", "--help")[1]
    assert "--show-config" in run(capfd, "config", "--help")[1]
