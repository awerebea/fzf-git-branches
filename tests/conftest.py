"""Fixtures for the fzf-git-branches test suite.

Everything runs against throwaway git repositories in a temporary directory,
with a fake HOME and git configuration, and a stub fzf on PATH that records
its arguments and answers with scripted output.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

REPO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_DIR))

import fzf_git_branches as fgb  # noqa: E402

SCRIPT = REPO_DIR / "fzf_git_branches.py"

STUB_FZF = """\
#!{python}
import json, os, sys
state = os.environ["FGB_STUB_DIR"]
if sys.argv[1:] == ["--version"]:
    print(os.environ.get("FGB_STUB_VERSION", "0.75.0 (stub)"))
    sys.exit(0)
calls = sorted(name for name in os.listdir(state) if name.startswith("call"))
record = {{
    "args": sys.argv[1:],
    "stdin": sys.stdin.read(),
    "shell": os.environ.get("SHELL", ""),
}}
with open(os.path.join(state, "call%03d.json" % len(calls)), "w") as f:
    json.dump(record, f)
queue_file = os.path.join(state, "queue.json")
with open(queue_file) as f:
    queue = json.load(f)
answer = queue.pop(0) if queue else {{"out": "", "rc": 130}}
with open(queue_file, "w") as f:
    json.dump(queue, f)
sys.stdout.write(answer["out"])
sys.exit(answer["rc"])
"""


@dataclass
class Stub:
    """The fake fzf: queue answers with respond(), read calls with calls()."""

    state: Path

    def respond(self, out: str, rc: int = 0) -> None:
        queue_file = self.state / "queue.json"
        queue = json.loads(queue_file.read_text())
        queue.append({"out": out, "rc": rc})
        queue_file.write_text(json.dumps(queue))

    def pick(self, *rows: str, key: str = "") -> None:
        """Answer a picker: the pressed --expect key and the chosen rows."""
        self.respond("".join(f"{line}\n" for line in (key, *rows)))

    def type(self, text: str) -> None:
        """Answer a prompt_text() line editor."""
        self.respond(f"{text}\n")

    def calls(self) -> list[dict[str, Any]]:
        return [
            json.loads(path.read_text())
            for path in sorted(self.state.glob("call*.json"))
        ]


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A fake HOME, no user git config, no FGB_* settings, a fixed width."""
    home = tmp_path / "home"
    home.mkdir()
    for name in list(os.environ):
        if name.startswith("FGB_") or name in (
            "NO_COLOR",
            "FZF_DEFAULT_OPTS",
            "PYTHON_COLORS",
            "FORCE_COLOR",
        ):
            monkeypatch.delenv(name)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.com")
        monkeypatch.setenv(f"GIT_{role}_DATE", "2024-01-02T03:04:05+00:00")
    monkeypatch.setenv("COLUMNS", "200")
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    fgb.COLOR.mode = "auto"
    fgb.LOG.setLevel(fgb.LOG_LEVELS[fgb.DEFAULT_LOG_LEVEL])
    yield home


@pytest.fixture
def stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Stub:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state = tmp_path / "fzf-state"
    state.mkdir()
    (state / "queue.json").write_text("[]")
    fzf = bin_dir / "fzf"
    fzf.write_text(STUB_FZF.format(python=sys.executable))
    fzf.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("FGB_STUB_DIR", str(state))
    return Stub(state)


def answer(monkeypatch: pytest.MonkeyPatch, keys: str) -> None:
    """Keys typed at the y/N confirmations, one character each."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(keys))


def git(*args: str, cwd: Path | str | None = None) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def real(path: Path | str) -> str:
    return os.path.realpath(path)


def commit_file(repo: Path, name: str) -> None:
    (repo / f"{name}.txt").write_text(f"{name}\n")
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", f"add {name}", cwd=repo)


@pytest.fixture
def plain(tmp_path: Path) -> Path:
    """An ordinary repo with a worktree whose path has a space and a locked one."""
    repo = tmp_path / "plain"
    git("init", "-q", "-b", "main", str(repo))
    commit_file(repo, "base")
    git("branch", "spaced", cwd=repo)
    git("branch", "locked", cwd=repo)
    git(
        "worktree", "add", "-q", str(tmp_path / "with space" / "wt"), "spaced", cwd=repo
    )
    git("worktree", "add", "-q", str(tmp_path / "plain-wt-locked"), "locked", cwd=repo)
    git("worktree", "lock", str(tmp_path / "plain-wt-locked"), cwd=repo)
    return repo


@pytest.fixture
def bare(tmp_path: Path) -> Path:
    """A bare repo with its main branch checked out in hub.git/wt/main."""
    seed = tmp_path / "seed"
    git("init", "-q", "-b", "main", str(seed))
    commit_file(seed, "base")
    hub = tmp_path / "hub.git"
    git("init", "-q", "--bare", str(hub))
    git("remote", "add", "origin", str(hub), cwd=seed)
    git("push", "-q", "-u", "origin", "main", cwd=seed)
    git("symbolic-ref", "HEAD", "refs/heads/main", cwd=hub)
    git("worktree", "add", "-q", str(hub / "wt" / "main"), "main", cwd=hub)
    return hub


@pytest.fixture
def sepgitdir(tmp_path: Path) -> Path:
    work = tmp_path / "sepwork"
    git(
        "init",
        "-q",
        "-b",
        "main",
        f"--separate-git-dir={tmp_path / 'sep.gitdir'}",
        str(work),
    )
    commit_file(work, "base")
    return work


@pytest.fixture
def submodule(tmp_path: Path, plain: Path) -> Path:
    super_repo = tmp_path / "super"
    git("init", "-q", "-b", "main", str(super_repo))
    commit_file(super_repo, "base")
    git(
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        str(plain),
        "sub",
        cwd=super_repo,
    )
    git("commit", "-q", "-m", "add submodule", cwd=super_repo)
    return super_repo


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """A clone with remote-tracking branches:

    linked  local counterpart holding a worktree (wt-linked)
    stale   local counterpart with no worktree, one commit behind its remote
    orphan  remote branch with no local counterpart
    twin    tracked by twin, aaa-twin and zzz-twin, each with a worktree
    """
    seed = tmp_path / "rseed"
    git("init", "-q", "-b", "main", str(seed))
    commit_file(seed, "base")
    remote = tmp_path / "remote.git"
    git("init", "-q", "--bare", str(remote))
    git("remote", "add", "origin", str(remote), cwd=seed)
    git("push", "-q", "-u", "origin", "main", cwd=seed)
    for branch in ("linked", "stale", "orphan", "twin"):
        git("checkout", "-q", "-b", branch, "main", cwd=seed)
        commit_file(seed, branch)
        git("push", "-q", "-u", "origin", branch, cwd=seed)
    git("checkout", "-q", "main", cwd=seed)
    git("symbolic-ref", "HEAD", "refs/heads/main", cwd=remote)
    repo = tmp_path / "clone"
    git("clone", "-q", str(remote), str(repo))
    git("branch", "-q", "linked", "origin/linked", cwd=repo)
    git("worktree", "add", "-q", str(tmp_path / "wt-linked"), "linked", cwd=repo)
    git("branch", "-q", "stale", "origin/stale~1", cwd=repo)
    git("branch", "-q", "--set-upstream-to=origin/stale", "stale", cwd=repo)
    for branch in ("twin", "aaa-twin", "zzz-twin"):
        git("branch", "-q", branch, "origin/twin", cwd=repo)
        git("branch", "-q", "--set-upstream-to=origin/twin", branch, cwd=repo)
        git("worktree", "add", "-q", str(tmp_path / f"wt-{branch}"), branch, cwd=repo)
    return repo


def run(capfd: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    """Run main() in-process; return (exit code, stdout, stderr)."""
    try:
        code = fgb.main(list(argv))
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 1
    out, err = capfd.readouterr()
    return code, out, err


def new_app(**settings: Any) -> fgb.Fgb:
    """An Fgb for the current directory, with worktree state loaded."""
    app = fgb.Fgb(fgb.Settings(**settings), None)
    app.load_worktrees()
    return app
