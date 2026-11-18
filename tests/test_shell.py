"""Shell integration: the `fgb` wrapper in every installed shell, completion
scripts, and the single-key confirmation on a real terminal."""

from __future__ import annotations

import contextlib
import os
import pty
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import SCRIPT, Stub, fgb, real

# How each shell loads the wrapper ({init} is a file holding `init` output),
# then runs {body}, prints the exit code and the physical working directory
SHELLS = {
    "bash": (["bash", "--norc", "--noprofile", "-c"], "bash"),
    "zsh": (["zsh", "-f", "-c"], "zsh"),
    "dash": (["dash", "-c"], "sh"),
    "ksh": (["ksh", "-c"], "ksh"),
    "fish": (["fish", "--no-config", "-c"], "fish"),
    "nu": (["nu", "-n", "-c"], "nu"),
    "pwsh": (["pwsh", "-NoProfile", "-NonInteractive", "-Command"], "pwsh"),
}
POSIX_SCRIPT = '. "{init}"; cd "{repo}" || exit 9; {body}; echo "rc=$?"; pwd -P'
SCRIPTS = {
    "fish": 'source "{init}"; cd "{repo}"; {body}; echo "rc=$status"; pwd -P',
    "nu": (
        'source "{init}"; cd "{repo}"; {body}; '
        'print $"rc=($env.LAST_EXIT_CODE)"; print (pwd)'
    ),
    "pwsh": (
        '. "{init}"; Set-Location -LiteralPath "{repo}"; {body}; '
        '"rc=$LASTEXITCODE"; (Get-Location).Path'
    ),
}


@pytest.fixture
def installed(stub: Stub, tmp_path: Path) -> Path:
    """fzf-git-branches on PATH (next to the stub fzf), as a symlink."""
    link = tmp_path / "bin" / "fzf-git-branches"
    link.symlink_to(SCRIPT)
    return link


def run_shell(shell: str, repo: Path, body: str, tmp_path: Path) -> tuple[int, str]:
    """Run `body` with the wrapper loaded; return (fgb's exit code, cwd after)."""
    command, init_name = SHELLS[shell]
    if shutil.which(command[0]) is None:
        pytest.skip(f"{command[0]} is not installed")
    # PowerShell only dot-sources .ps1 files
    init = tmp_path / ("init.ps1" if shell == "pwsh" else f"init.{shell}")
    init.write_text(fgb.init_script(init_name))
    script = SCRIPTS.get(shell, POSIX_SCRIPT).format(init=init, repo=repo, body=body)
    result = subprocess.run(
        [*command, script],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
        check=False,
    )
    lines = result.stdout.strip().splitlines()
    assert len(lines) >= 2, result.stdout + result.stderr
    code_line = next(line for line in lines if line.startswith("rc="))
    return int(code_line[3:]), real(lines[-1])


@pytest.mark.parametrize("shell", list(SHELLS))
def test_wrapper_changes_directory(
    shell: str, installed: Path, plain: Path, stub: Stub, tmp_path: Path
) -> None:
    stub.pick("[spaced]")
    code, cwd = run_shell(shell, plain, "fgb worktree manage", tmp_path)
    assert code == 0
    assert cwd == real(tmp_path / "with space" / "wt")


@pytest.mark.parametrize("shell", list(SHELLS))
def test_wrapper_keeps_directory_and_exit_code(
    shell: str, installed: Path, plain: Path, tmp_path: Path
) -> None:
    code, cwd = run_shell(shell, plain, "fgb worktree bogus", tmp_path)
    assert code == 2
    assert cwd == real(plain)


@pytest.mark.parametrize("shell", ["bash", "zsh", "dash", "ksh", "fish", "nu"])
def test_wrapper_passes_double_dash(
    shell: str, installed: Path, plain: Path, stub: Stub, tmp_path: Path
) -> None:
    run_shell(shell, plain, "fgb branch manage -- -x", tmp_path)
    assert "--query=-x" in stub.calls()[0]["args"]


def test_pwsh_passes_quoted_double_dash(
    installed: Path, plain: Path, stub: Stub, tmp_path: Path
) -> None:
    run_shell("pwsh", plain, "fgb branch manage '--' -x", tmp_path)
    assert "--query=-x" in stub.calls()[0]["args"]


@pytest.mark.parametrize(
    ("shell", "setup"),
    [
        ("bash", "shopt -s expand_aliases"),
        ("zsh", ":"),
        ("ksh", ":"),
    ],
)
def test_wrapper_ignores_user_aliases(
    shell: str,
    setup: str,
    installed: Path,
    plain: Path,
    stub: Stub,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Aliases such as rm=trash-put or cat=bat are expanded when a function is
    defined; the wrapper must call the real commands anyway."""
    command, init_name = SHELLS[shell]
    if shutil.which(command[0]) is None:
        pytest.skip(f"{command[0]} is not installed")
    tmpdir = tmp_path / "tmpdir"
    tmpdir.mkdir()
    monkeypatch.setenv("TMPDIR", str(tmpdir))
    init = tmp_path / f"init.{shell}"
    init.write_text(fgb.init_script(init_name))
    aliases = " ".join(
        f"alias {name}='echo ALIAS-{name} >&2; false';"
        for name in ("rm", "cat", "mktemp", "cd", "command")
    )
    stub.pick("[spaced]")
    result = subprocess.run(
        [
            *command,
            f'{setup}; {aliases}\n. "{init}"\n'
            f'\\cd "{plain}"; fgb worktree manage; echo "rc=$?"; pwd -P',
        ],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=60,
        check=False,
    )
    assert "ALIAS-" not in result.stderr
    lines = result.stdout.strip().splitlines()
    assert lines[-2:] == ["rc=0", real(tmp_path / "with space" / "wt")]
    assert list(tmpdir.iterdir()) == []


def test_nu_wrapper_never_trashes(installed: Path) -> None:
    assert "rm --force --permanent $tmp" in fgb.init_script("nu")


def test_wrapper_leaves_no_variables(
    installed: Path, plain: Path, tmp_path: Path
) -> None:
    init = tmp_path / "init.sh"
    init.write_text(fgb.init_script("bash"))
    result = subprocess.run(
        ["bash", "--norc", "-c", f'. "{init}"; cd "{plain}"; fgb version; compgen -v'],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "__fgb_" not in result.stdout


def test_wrapper_uses_absolute_path_when_not_on_path(
    stub: Stub, plain: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Hide any installed fzf-git-branches, such as ~/.local/bin's
    path = [
        entry
        for entry in os.environ["PATH"].split(os.pathsep)
        if not (Path(entry) / "fzf-git-branches").exists()
    ]
    monkeypatch.setenv("PATH", os.pathsep.join(path))
    text = fgb.init_script("bash")
    assert f"command {real(SCRIPT)} --cwd-file" in text
    stub.pick("[spaced]")
    code, cwd = run_shell("bash", plain, "fgb worktree manage", tmp_path)
    assert (code, cwd) == (0, real(tmp_path / "with space" / "wt"))


def test_wrapper_uses_name_when_on_path(installed: Path) -> None:
    assert "command fzf-git-branches --cwd-file" in fgb.init_script("zsh")
    assert "^fzf-git-branches --cwd-file" in fgb.init_script("nu")


def test_init_command(installed: Path, capfd: pytest.CaptureFixture[str]) -> None:
    assert fgb.main(["init", "fish"]) == 0
    out = capfd.readouterr().out
    assert out.startswith("# fzf-git-branches shell integration for fish")
    assert "complete -c fzf-git-branches" in out


# -- completion --------------------------------------------------------------


def syntax_check(command: list[str], script: Path) -> None:
    if shutil.which(command[0]) is None:
        pytest.skip(f"{command[0]} is not installed")
    result = subprocess.run(
        [*command, str(script)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("shell", "command"),
    [
        ("bash", ["bash", "-n"]),
        ("zsh", ["zsh", "-n"]),
        ("fish", ["fish", "--no-execute"]),
        ("nu", ["nu", "--ide-check", "10"]),
    ],
)
def test_init_scripts_parse(shell: str, command: list[str], tmp_path: Path) -> None:
    script = tmp_path / f"init.{shell}"
    script.write_text(fgb.init_script(shell))
    syntax_check(command, script)


def bash_complete(tmp_path: Path, *words: str) -> list[str]:
    script = tmp_path / "complete.bash"
    script.write_text(fgb.completion_script("bash"))
    line = " ".join(words)
    result = subprocess.run(
        [
            "bash",
            "--norc",
            "-c",
            f'. "{script}"; COMP_WORDS=({line}); '
            f"COMP_CWORD=$(( ${{#COMP_WORDS[@]}} - 1 )); "
            '_fzf_git_branches_complete; printf "%s\\n" "${COMPREPLY[@]}"',
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.split()


def test_bash_completion(tmp_path: Path) -> None:
    assert bash_complete(tmp_path, "fgb", "wor") == ["worktree"]
    assert bash_complete(tmp_path, "fgb", "worktree", "'t'") == ["total"]
    assert "--wt-path-display" in bash_complete(
        tmp_path, "fgb", "worktree", "list", "--"
    )
    assert "--remotes" not in bash_complete(tmp_path, "fgb", "worktree", "list", "--")
    assert bash_complete(tmp_path, "fgb", "worktree", "list", "-p", "relative-h") == [
        "relative-home"
    ]
    assert bash_complete(tmp_path, "fgb", "-C", "ne") == ["never"]
    assert bash_complete(tmp_path, "fgb", "init", "pw") == ["pwsh"]


def test_fish_completion(tmp_path: Path) -> None:
    if shutil.which("fish") is None:
        pytest.skip("fish is not installed")
    script = tmp_path / "init.fish"
    script.write_text(fgb.init_script("fish"))

    def complete(line: str) -> list[str]:
        result = subprocess.run(
            ["fish", "--no-config", "-c", f'source "{script}"; complete -C "{line}"'],
            capture_output=True,
            text=True,
            check=True,
        )
        return [row.split("\t")[0] for row in result.stdout.splitlines()]

    assert "worktree" in complete("fzf-git-branches w")
    assert complete("fzf-git-branches worktree t") == ["total"]
    assert "relative-home" in complete("fzf-git-branches worktree list -p ")
    assert "--remotes" in complete("fgb branch manage --rem")


def test_zsh_completion_registers(tmp_path: Path) -> None:
    if shutil.which("zsh") is None:
        pytest.skip("zsh is not installed")
    script = tmp_path / "init.zsh"
    script.write_text(fgb.init_script("zsh"))
    result = subprocess.run(
        [
            "zsh",
            "-f",
            "-c",
            f'autoload -Uz compinit; compinit -u -D; . "{script}"; '
            'print -r -- "$_comps[fgb] $_comps[fzf-git-branches]"',
        ],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "ZDOTDIR": str(tmp_path)},
    )
    assert result.stdout.strip() == "_fzf_git_branches _fzf_git_branches"


# -- a real terminal ---------------------------------------------------------

CONFIRM_DRIVER = """\
import sys
sys.path.insert(0, {repo!r})
import fzf_git_branches as fgb
answer = fgb.confirm("Proceed?")
import select
left = select.select([sys.stdin], [], [], 0.5)[0]
print("ANSWER=yes" if answer else "ANSWER=no")
print("BUFFER=leftover" if left else "BUFFER=empty")
print("DONE-MARKER")
"""


def in_terminal(keys: bytes, tmp_path: Path) -> str:
    """Run confirm() on a pseudo-terminal, typing `keys` (watchdog: 10 s)."""
    driver = tmp_path / "confirm.py"
    driver.write_text(CONFIRM_DRIVER.format(repo=str(SCRIPT.parent)))
    pid, fd = pty.fork()
    if pid == 0:
        os.execv(sys.executable, [sys.executable, "-I", str(driver)])
    output = b""
    sent = False
    try:
        deadline = time.time() + 10
        while time.time() < deadline and b"DONE-MARKER" not in output:
            # Type only once the prompt is up: a key that arrives before the
            # terminal leaves line mode waits for an Enter that never comes
            if not sent and b"(y|N): " in output:
                time.sleep(0.2)
                os.write(fd, keys)
                sent = True
            ready, _, _ = select.select([fd], [], [], 0.3)
            if not ready:
                continue
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            output += chunk
    finally:
        with contextlib.suppress(OSError):
            os.kill(pid, 9)
        os.waitpid(pid, 0)
        os.close(fd)
    return output.decode(errors="replace").replace("\r", "")


@pytest.mark.parametrize(
    ("keys", "expected"),
    [
        (b"y", "ANSWER=yes"),
        (b"Y", "ANSWER=yes"),
        (b"n", "ANSWER=no"),
        (b"\n", "ANSWER=no"),
    ],
)
def test_single_keypress(keys: bytes, expected: str, tmp_path: Path) -> None:
    output = in_terminal(keys, tmp_path)
    assert "Proceed? (y|N): " in output
    assert expected in output
    # No Enter needed, and nothing left behind for the shell to read
    assert "BUFFER=empty" in output
