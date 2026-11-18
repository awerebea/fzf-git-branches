"""Command line parsing, settings precedence, config file and exit codes."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import SCRIPT, Stub, fgb, run

VERSION_LINE = f"fzf-git-branches {fgb.__version__}\n"


def test_version_command_ignores_the_rest(capfd: pytest.CaptureFixture[str]) -> None:
    assert run(capfd, "version", "--bogus", "x") == (0, VERSION_LINE, "")


@pytest.mark.parametrize(
    "argv",
    [
        ["--version"],
        ["branch", "--version"],
        ["branch", "list", "--version"],
        ["worktree", "total", "--version"],
        ["init", "--version"],
    ],
)
def test_version_option_everywhere(
    argv: list[str], capfd: pytest.CaptureFixture[str]
) -> None:
    assert run(capfd, *argv) == (0, VERSION_LINE, "")


def test_help_command(capfd: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capfd, "help", "whatever")
    assert code == 0
    assert "FGB_SORT_ORDER" in out
    assert "branch" in out
    assert "worktree" in out


def test_help_outside_a_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    code, out, _ = run(capfd, "branch", "list", "-h")
    assert code == 0
    assert "--remotes" in out
    code, out, _ = run(capfd, "worktree", "add", "--help")
    assert code == 0
    assert "relative-wt-base" in out
    assert "ctrl-alt-d" in out
    assert "FGB_WT_BASE_PATH_BARE" in out


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["bogus"],
        ["-x"],
        ["branch"],
        ["worktree"],
        ["branch", "bogus"],
        ["branch", "list", "query"],
        ["branch", "list", "--", "query"],
        ["branch", "list", "-f"],
        ["branch", "list", "-p", "absolute"],
        ["worktree", "list", "query"],
        ["worktree", "list", "--", "x"],
        ["worktree", "list", "-f"],
        ["worktree", "list", "-r"],
        ["worktree", "manage", "-a"],
        ["worktree", "manage", "-c"],
        ["branch", "list", "--sor=refname"],
        ["branch", "list", "-s=refname"],
        ["branch", "list", "-rs=refname"],
        ["branch", "list", "-s"],
        ["worktree", "list", "-p", "bogus"],
        ["-C", "rainbow", "branch", "list"],
        ["init", "tcsh"],
        ["completion", "nu"],
    ],
)
def test_usage_errors(
    argv: list[str],
    plain: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(plain)
    code, out, err = run(capfd, *argv)
    assert code == 2
    assert out == ""
    assert "usage:" in err


def test_wrapper_shows_fgb_in_usage(
    capfd: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, _, err = run(capfd, "--cwd-file", str(tmp_path / "f"), "bogus")
    assert code == 2
    assert err.startswith("usage: fgb ")


def test_not_in_a_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    for argv in (["branch", "list"], ["worktree", "list"]):
        code, out, err = run(capfd, *argv)
        assert code == fgb.EXIT_NO_REPO
        assert out == ""
        assert "Not inside a Git repository" in err


def test_submodule_refused(
    submodule: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(submodule / "sub")
    code, _, err = run(capfd, "worktree", "list")
    assert code == 1
    assert "is a submodule of" in err
    assert "not supported for submodules" in err
    # branch commands still work there
    assert run(capfd, "branch", "list")[0] == 0


@pytest.mark.parametrize("fixture", ["submodule", "plain", "bare"])
def test_other_repositories_not_refused(
    fixture: str,
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(request.getfixturevalue(fixture))
    code, _, err = run(capfd, "worktree", "list")
    assert code == 0
    assert "submodule" not in err


# -- argument preprocessing --------------------------------------------------


def test_attach_values() -> None:
    assert fgb.attach_values(["branch", "list", "-s", "-committerdate"]) == [
        "branch",
        "list",
        "-s-committerdate",
    ]
    assert fgb.attach_values(["--sort", "-x", "-ra", "-p", "absolute"]) == [
        "--sort=-x",
        "-ra",
        "-pabsolute",
    ]
    assert fgb.attach_values(["-rs", "-x", "--", "-s", "y"]) == [
        "-rs-x",
        "--",
        "-s",
        "y",
    ]
    assert fgb.attach_values(["-sx", "y"]) == ["-sx", "y"]


def test_reject_short_equals() -> None:
    fgb.reject_short_equals(["-s", "-s=x"])  # the value of -s, not an option
    fgb.reject_short_equals(["--sort=x", "--", "-s=x"])
    with pytest.raises(fgb.AppError):
        fgb.reject_short_equals(["-ras=x"])


def test_command_path() -> None:
    assert fgb.command_path(["-C", "never", "worktree", "-x", "add", "q"]) == (
        2,
        "worktree add",
    )
    assert fgb.command_path(["--config", "branch", "init"]) == (2, "init")
    assert fgb.command_path(["--", "branch"]) == (None, "")


# -- options reach git and fzf -----------------------------------------------


def branch_names(out: str) -> list[str]:
    return [line.split(" ", 1)[0] for line in out.splitlines()]


@pytest.fixture
def three_branches(plain: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name, date in (("b-old", "2020"), ("c-mid", "2022"), ("a-new", "2025")):
        monkeypatch.setenv("GIT_COMMITTER_DATE", f"{date}-01-01T00:00:00+00:00")
        subprocess.run(
            ["git", "checkout", "-q", "-b", name, "main"], cwd=plain, check=True
        )
        subprocess.run(
            ["git", "commit", "-q", "--allow-empty", "-m", name], cwd=plain, check=True
        )
    subprocess.run(["git", "checkout", "-q", "main"], cwd=plain, check=True)
    monkeypatch.chdir(plain)
    return plain


@pytest.mark.parametrize(
    ("argv", "env", "expected"),
    [
        # Equal dates (the fixture's other branches) are ordered by name
        ([], {}, ["[a-new]", "[locked]", "[main]", "[spaced]", "[c-mid]", "[b-old]"]),
        (["-s", "refname"], {}, ["[a-new]", "[b-old]", "[c-mid]"]),
        (["--sort=-refname"], {}, ["[spaced]", "[main]", "[locked]"]),
        (["-srefname"], {"FGB_SORT_ORDER": "-refname"}, ["[a-new]", "[b-old]"]),
        ([], {"FGB_SORT_ORDER": "refname"}, ["[a-new]", "[b-old]", "[c-mid]"]),
    ],
)
def test_sort_order(
    argv: list[str],
    env: dict[str, str],
    expected: list[str],
    three_branches: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    code, out, _ = run(capfd, "branch", "list", *argv)
    assert code == 0
    assert branch_names(out)[: len(expected)] == expected


def test_bad_sort_key_is_reported(
    plain: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(plain)
    code, _, err = run(capfd, "branch", "list", "-s", "nosuchfield")
    assert code != 0
    assert "nosuchfield" in err


def test_formats(
    plain: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(plain)
    code, out, _ = run(
        capfd, "branch", "list", "-d", "committerdate:short", "-u", "authoremail"
    )
    assert code == 0
    assert "(2024-01-02)" in out
    assert "<test@example.com>" in out
    code, out, _ = run(
        capfd,
        "branch",
        "list",
        "--date-format=%(committerdate:short) %(authordate:format:%H:%M)",
        "--author-format=%(authorname)/%(committername)",
    )
    assert "(2024-01-02 03:04)" in out
    assert "test/test" in out


def test_query_words(
    plain: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(plain)
    assert run(capfd, "branch", "manage", "foo", "-r", "bar", "--", "-baz")[0] == 0
    assert "--query=foo bar -baz" in stub.calls()[0]["args"]


# -- settings ----------------------------------------------------------------


def write_config(home: Path, text: str) -> None:
    (home / ".config").mkdir(exist_ok=True)
    (home / ".config" / "fgbrc").write_text(text)


def test_config_value_parsing() -> None:
    assert fgb.config_value("refname # comment") == "refname"
    assert (
        fgb.config_value("committerdate:format:%Y#%m") == "committerdate:format:%Y#%m"
    )
    assert fgb.config_value('"quoted value"  # c') == "quoted value"
    assert fgb.config_value("'single'") == "single"
    assert fgb.config_value("#all comment") == ""


def test_config_file(
    isolated: Path,
    plain: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    write_config(
        isolated,
        "# comment\n"
        "  FGB_DATE_FORMAT=committerdate:short   # trailing\n"
        "export FGB_AUTHOR_FORMAT=authoremail\n"
        "FGB_UNKNOWN=1\n"
        "not a setting\n",
    )
    monkeypatch.chdir(plain)
    code, out, err = run(capfd, "branch", "list")
    assert code == 0
    assert "(2024-01-02)" in out
    assert "<test@example.com>" in out
    assert "unknown key 'FGB_UNKNOWN'" in err
    assert "fgbrc:5: ignoring invalid line" in err


def test_precedence(
    isolated: Path,
    plain: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    write_config(isolated, "FGB_DATE_FORMAT=committerdate:short\n")
    monkeypatch.chdir(plain)
    assert "(2024-01-02)" in run(capfd, "branch", "list")[1]
    monkeypatch.setenv("FGB_DATE_FORMAT", "committerdate:iso")
    assert "(2024-01-02 03:04:05 +0000)" in run(capfd, "branch", "list")[1]
    # An empty variable counts as unset, as ${VAR:-default} did
    monkeypatch.setenv("FGB_DATE_FORMAT", "")
    assert "(2024-01-02)" in run(capfd, "branch", "list")[1]
    monkeypatch.setenv("FGB_DATE_FORMAT", "committerdate:iso")
    out = run(capfd, "branch", "list", "-d", "committerdate:raw")[1]
    assert "(1704164645 +0000)" in out


def test_explicit_config_file(
    tmp_path: Path,
    plain: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "other.conf"
    config.write_text("FGB_DATE_FORMAT=committerdate:short\n")
    monkeypatch.chdir(plain)
    assert "(2024-01-02)" in run(capfd, "branch", "list", "--config", str(config))[1]
    assert "(2024-01-02)" in run(capfd, "--config", str(config), "branch", "list")[1]
    monkeypatch.setenv("FGB_CONFIG", str(config))
    assert "(2024-01-02)" in run(capfd, "branch", "list")[1]
    code, _, err = run(capfd, "branch", "list", "--config", str(tmp_path / "missing"))
    assert code == 1
    assert "config file not found" in err


def test_invalid_display_mode_setting(
    plain: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(plain)
    monkeypatch.setenv("FGB_WT_PATH_DISPLAY", "bogus-mode")
    code, _, err = run(capfd, "worktree", "list")
    assert code == 1
    assert "FGB_WT_PATH_DISPLAY must be one of" in err


# -- colors ------------------------------------------------------------------


def test_color_modes(
    plain: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(plain)
    # Not a terminal: auto means no colors
    assert "\033[" not in run(capfd, "branch", "list")[1]
    assert "\033[1;33mmain\033[0m" in run(capfd, "branch", "list", "-C", "always")[1]
    assert "\033[" in run(capfd, "--color=always", "branch", "list")[1]
    monkeypatch.setenv("FGB_COLOR", "always")
    assert "\033[" in run(capfd, "branch", "list")[1]
    assert "\033[" not in run(capfd, "branch", "list", "--color", "never")[1]
    monkeypatch.setenv("FGB_COLOR", "sometimes")
    assert run(capfd, "branch", "list")[0] == 1


needs_help_colors = pytest.mark.skipif(
    sys.version_info < (3, 14), reason="argparse colors help since Python 3.14"
)


@needs_help_colors
@pytest.mark.parametrize(
    "argv",
    [
        ["help", "--color", "never"],
        ["help", "-Cnever"],
        ["-C", "never", "help"],
        ["--color=never", "branch", "list", "-h"],
        ["worktree", "add", "-fC", "never", "--help"],
    ],
)
def test_help_without_colors(
    argv: list[str], monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    # Forced on for Python itself, still off when fgb says never
    monkeypatch.setenv("PYTHON_COLORS", "1")
    code, out, _ = run(capfd, *argv)
    assert code == 0
    assert "usage:" in out
    assert "\033[" not in out


@needs_help_colors
def test_help_colors_follow_the_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    # Not a terminal: auto means no colors, always colors anyway
    assert "\033[" not in run(capfd, "help")[1]
    assert "\033[" in run(capfd, "help", "-C", "always")[1]
    assert "\033[" in run(capfd, "branch", "list", "--color=always", "-h")[1]
    monkeypatch.setenv("FGB_COLOR", "always")
    assert "\033[" in run(capfd, "help")[1]
    assert "\033[" not in run(capfd, "help", "-C", "never")[1]
    monkeypatch.delenv("FGB_COLOR")
    config = tmp_path / "fgbrc"
    config.write_text("FGB_COLOR=always\nBOGUS=1\n")
    code, out, err = run(capfd, "--config", str(config), "help")
    assert code == 0
    assert "\033[" in out
    # The bad line is reported when a command runs, not by the help
    assert err == ""
    # Usage errors follow the same setting
    assert "\033[" in run(capfd, "-C", "always", "branch", "list", "--bogus")[2]
    assert "\033[" not in run(capfd, "-C", "never", "branch", "list", "--bogus")[2]
    assert "PYTHON_COLORS" not in os.environ


@pytest.mark.parametrize(
    ("argv", "env", "mode"),
    [
        (["help"], {}, "auto"),
        (["help", "-C", "always"], {}, "always"),
        (["-Calways", "help", "--color", "never"], {}, "never"),
        (["help", "--", "-C", "always"], {}, "auto"),
        (["branch", "list", "-s", "-C"], {}, "auto"),
        (["help"], {"FGB_COLOR": "never"}, "never"),
        (["help", "-C", "sometimes"], {"FGB_COLOR": "never"}, "never"),
        (["help"], {"FGB_COLOR": "sometimes"}, "auto"),
        (["help"], {"FGB_CONFIG": "/nonexistent/fgbrc"}, "auto"),
    ],
)
def test_early_color(
    argv: list[str],
    env: dict[str, str],
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    assert fgb.early_color(argv) == mode


def test_no_color_disables_fzf_colors_too(
    plain: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(plain)
    run(capfd, "-C", "never", "branch", "manage")
    call = stub.calls()[0]
    assert "--no-color" in call["args"]
    assert "\033[" not in call["stdin"]
    run(capfd, "branch", "manage")
    call = stub.calls()[1]
    assert "--no-color" not in call["args"]
    assert "\033[1;33mmain" in call["stdin"]
    monkeypatch.setenv("NO_COLOR", "1")
    run(capfd, "branch", "manage")
    assert "\033[" not in stub.calls()[2]["stdin"]


def test_fzf_version_requirement(
    plain: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(plain)
    monkeypatch.setenv("FGB_STUB_VERSION", "0.26.1 (old)")
    code, _, err = run(capfd, "branch", "manage")
    assert code == 1
    assert "fzf 0.27.0 or newer is required" in err
    # list commands do not need fzf
    assert run(capfd, "branch", "list")[0] == 0


def test_runs_as_a_script(plain: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "branch", "list"],
        cwd=plain,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "[main]" in result.stdout


def test_broken_pipe(plain: Path) -> None:
    result = subprocess.run(
        f"{sys.executable} -I {SCRIPT} completion zsh | head -1",
        shell=True,
        cwd=plain,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.stderr == ""
