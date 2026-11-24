"""-k/--keep-subdir: landing in the same subdirectory of another worktree."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import Stub, answer, commit_file, git, real, run


def spaced(tmp_path: Path) -> str:
    return real(tmp_path / "with space" / "wt")


def jump(
    capfd: pytest.CaptureFixture[str], tmp_path: Path, stub: Stub, *argv: str
) -> tuple[int, str, str, str]:
    """Pick the `spaced` worktree; return (code, stdout, stderr, new cwd)."""
    cwd_file = tmp_path / "cwd"
    stub.pick("[spaced]")
    code, out, err = run(capfd, "--cwd-file", str(cwd_file), "worktree", *argv)
    return code, out, err, cwd_file.read_text() if cwd_file.exists() else ""


@pytest.mark.parametrize("command", ["manage", "total"])
def test_jump_keeps_the_subdirectory(
    command: str,
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    (plain / "src" / "app").mkdir(parents=True)
    Path(spaced(tmp_path), "src", "app").mkdir(parents=True)
    monkeypatch.chdir(plain / "src" / "app")
    code, out, err, cwd = jump(capfd, tmp_path, stub, command, "-k")
    assert out == ""
    assert code == 0
    assert cwd == f"{spaced(tmp_path)}/src/app"
    assert (
        f"Jumped to worktree: {spaced(tmp_path)} (subdirectory: src/app), "
        "for branch 'spaced'"
    ) in err
    assert "Warning" not in err


@pytest.mark.parametrize(
    ("existing", "landing", "instead"),
    [
        ("src", "/src", "'src'"),
        ("", "", "the worktree root"),
    ],
)
def test_missing_subdirectory_falls_back_to_the_nearest_parent(
    existing: str,
    landing: str,
    instead: str,
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    (plain / "src" / "app").mkdir(parents=True)
    if existing:
        Path(spaced(tmp_path), existing).mkdir()
    monkeypatch.chdir(plain / "src" / "app")
    code, _, err, cwd = jump(capfd, tmp_path, stub, "manage", "--keep-subdir")
    assert code == 0
    assert cwd == f"{spaced(tmp_path)}{landing}"
    assert err.startswith(
        f"Warning: 'src/app' does not exist in this worktree; using {instead}\n"
    )


def test_a_file_is_not_a_directory_to_land_in(
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    (plain / "docs").mkdir()
    Path(spaced(tmp_path), "docs").write_text("a file\n")
    monkeypatch.chdir(plain / "docs")
    _, _, err, cwd = jump(capfd, tmp_path, stub, "manage", "-k")
    assert cwd == spaced(tmp_path)
    assert "'docs' does not exist in this worktree" in err


@pytest.mark.parametrize(
    ("argv", "env", "config", "kept"),
    [
        ([], "", "", False),
        (["-k"], "", "", True),
        ([], "yes", "", True),
        ([], "", "FGB_KEEP_SUBDIR=On", True),
        (["--no-keep-subdir"], "true", "", False),
        (["-k"], "0", "", True),
        ([], "off", "FGB_KEEP_SUBDIR=true", False),
    ],
)
def test_setting_precedence(
    argv: list[str],
    env: str,
    config: str,
    kept: bool,
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    isolated: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    (plain / "src").mkdir()
    Path(spaced(tmp_path), "src").mkdir()
    (isolated / ".config").mkdir()
    (isolated / ".config" / "fgbrc").write_text(f"{config}\n")
    if env:
        monkeypatch.setenv("FGB_KEEP_SUBDIR", env)
    monkeypatch.chdir(plain / "src")
    cwd = jump(capfd, tmp_path, stub, "manage", *argv)[3]
    assert cwd == f"{spaced(tmp_path)}/src" if kept else spaced(tmp_path)


def test_invalid_setting_is_an_error(
    plain: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(plain)
    monkeypatch.setenv("FGB_KEEP_SUBDIR", "maybe")
    code, _, err = run(capfd, "worktree", "manage")
    assert code == 1
    assert "FGB_KEEP_SUBDIR must be true or false" in err


def test_jump_to_the_current_worktree_stays_put(
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    (plain / "src").mkdir()
    monkeypatch.chdir(plain / "src")
    cwd_file = tmp_path / "cwd"
    stub.pick("[main]")
    _, _, err = run(capfd, "--cwd-file", str(cwd_file), "worktree", "manage", "-k")
    assert cwd_file.read_text() == f"{real(plain)}/src"
    assert "Warning" not in err


def test_outside_a_worktree_lands_in_the_root(
    bare: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(bare / "refs")
    cwd_file = tmp_path / "cwd"
    stub.pick("[main]")
    _, _, err = run(capfd, "--cwd-file", str(cwd_file), "worktree", "manage", "-k")
    assert cwd_file.read_text() == f"{real(bare)}/wt/main"
    assert "Warning" not in err


def test_added_worktree_keeps_the_subdirectory(
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    (plain / "src").mkdir()
    commit_file(plain / "src", "module")
    git("branch", "feature", cwd=plain)
    monkeypatch.chdir(plain / "src")
    cwd_file = tmp_path / "cwd"
    stub.pick("[feature]")
    code, _, err = run(
        capfd, "--cwd-file", str(cwd_file), "worktree", "add", "-c", "-k"
    )
    target = f"{real(plain)}/.git/wt/feature"
    assert code == 0
    assert "Jumped there (subdirectory: src)." in err
    assert cwd_file.read_text() == f"{target}/src"


def test_fork_with_stash_keeps_the_subdirectory(
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    (plain / "src").mkdir()
    commit_file(plain / "src", "module")
    (plain / "base.txt").write_text("changed\n")
    monkeypatch.chdir(plain / "src")
    cwd_file = tmp_path / "cwd"
    stub.pick("[main]", key="alt-n")
    stub.type("topic")
    answer(monkeypatch, "y")
    code, _, _ = run(
        capfd, "--cwd-file", str(cwd_file), "worktree", "total", "-c", "-k"
    )
    target = f"{real(plain)}/.git/wt/topic"
    assert code == 0
    assert cwd_file.read_text() == f"{target}/src"
    # The stash applies to the whole worktree, not only the subdirectory
    assert (Path(target) / "base.txt").read_text() == "changed\n"
    assert git("stash", "list", cwd=plain) == ""


def test_report(
    plain: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    (plain / "src").mkdir()
    monkeypatch.chdir(plain / "src")
    out = run(capfd, "config", "-k")[1]
    assert "FGB_KEEP_SUBDIR" in out
    assert "true" in out
    assert "command line (-k)" in out
    assert "subdirectory            src, kept on switching" in out
    out = run(capfd, "worktree", "manage", "--no-keep-subdir", "--show-config")[1]
    assert "command line (--no-keep-subdir)" in out
    assert "src, not kept on switching" in out
    monkeypatch.setenv("FGB_KEEP_SUBDIR", "maybe")
    code, out, _ = run(capfd, "config")
    assert code == 0
    assert "maybe (invalid: one of true, false, 1, 0, yes, no, on, off)" in out
    monkeypatch.chdir(plain / ".git")
    assert (
        "subdirectory            none (not inside a worktree)"
        in run(capfd, "config")[1]
    )
