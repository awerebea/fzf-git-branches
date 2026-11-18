"""Pickers and their actions, with a stub fzf that answers from a script."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from conftest import Stub, answer, commit_file, fgb, git, real, run


def header(stub: Stub, call: int = 0) -> str:
    args = stub.calls()[call]["args"]
    return str(args[args.index("--header") + 1])


def branch_exists(repo: Path, name: str) -> bool:
    return bool(git("branch", "--list", name, cwd=repo))


# -- picker arguments --------------------------------------------------------


def test_branch_manage_picker(
    plain: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(plain)
    assert run(capfd, "branch", "manage", "ma") == (0, "", "")
    call = stub.calls()[0]
    args = call["args"]
    assert args[:4] == ["--height", "80%", "--reverse", "--ansi"]
    assert "--multi" in args
    assert "--expect=ctrl-d,ctrl-alt-d,ctrl-o,alt-n" in args
    assert "--query=ma" in args
    assert header(stub).split("\n") == [
        "Manage Git Branches: ctrl-d:del, ctrl-alt-d:extended-del, ctrl-o:info, "
        "alt-n:fork, ctrl-y:accept, ctrl-t:toggle+down",
        "Branch      Author    Date",
    ]
    preview = args[args.index("--preview") + 1]
    assert preview.endswith(" _preview {1}")
    # The built-in options are run by sh whatever the user's shell is
    assert call["shell"] == "/bin/sh"
    rows = fgb.ANSI_ESCAPE.sub("", call["stdin"]).splitlines()
    assert [row.split(" ", 1)[0] for row in rows] == ["[locked]", "[main]", "[spaced]"]
    assert rows[1].startswith("[main]      test      (")


def test_worktree_pickers(
    plain: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(plain)
    monkeypatch.setenv("FGB_BINDKEY_DEL", "ctrl-x")
    run(capfd, "worktree", "manage")
    run(capfd, "worktree", "add")
    run(capfd, "worktree", "total")
    assert header(stub, 0).startswith(
        "Manage Git Worktrees: ctrl-x:del, ctrl-alt-d:extended-del, ctrl-o:info, "
    )
    assert header(stub, 0).split("\n")[1].startswith("Branch      WT ")
    keys = "ctrl-x:del, ctrl-alt-d:extended-del, ctrl-o:info, ctrl-v:verbose, "
    keys += "alt-n:fork, alt-N:fork-verbose"
    assert header(stub, 1).startswith(f"Add a Git Worktree: {keys}")
    assert " WT " not in header(stub, 1).split("\n")[1]
    assert header(stub, 2).startswith(f"Manage Git Worktrees (total): {keys}")
    assert (
        "--expect=ctrl-x,ctrl-alt-d,ctrl-o,ctrl-v,alt-n,alt-N"
        in stub.calls()[1]["args"]
    )
    # manage lists worktrees only; add lists branches without one
    manage_rows = fgb.ANSI_ESCAPE.sub("", stub.calls()[0]["stdin"])
    assert "[main]" in manage_rows
    assert "[spaced]" in manage_rows
    assert stub.calls()[1]["stdin"] == ""


def test_fzf_opts_replace_the_defaults(
    plain: Path,
    stub: Stub,
    isolated: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    (isolated / ".config").mkdir()
    (isolated / ".config" / "fgbrc").write_text(
        "FGB_FZF_OPTS=--ansi --bind 'ctrl-a:select-all' --border\n"
    )
    monkeypatch.setenv("SHELL", "/usr/bin/fish")
    monkeypatch.chdir(plain)
    run(capfd, "branch", "manage")
    call = stub.calls()[0]
    assert call["args"][3:6] == ["--ansi", "--bind", "ctrl-a:select-all"]
    assert "--preview" not in call["args"]
    assert header(stub).split("\n")[0].endswith("alt-n:fork, ctrl-a:select-all")
    # The user's own commands keep the user's shell
    assert call["shell"] == "/usr/bin/fish"


def test_preview_command(
    plain: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(plain)
    assert run(capfd, "-C", "never", "_preview", "[main]")[0] == 0
    out = capfd.readouterr().out if False else None
    assert out is None
    code, out, _ = run(capfd, "-C", "never", "_preview", "[main]")
    assert code == 0
    assert "add base" in out
    assert "\033[" not in out
    head = git("rev-parse", "--short=7", "HEAD", cwd=plain)
    assert "add base" in run(capfd, "_preview", f"{{{head}}}")[1]


def test_cancelled_picker(
    plain: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(plain)
    stub.respond("", rc=130)
    assert run(capfd, "worktree", "total") == (0, "", "")


def test_empty_list_prints_nothing(
    plain: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(plain)
    assert run(capfd, "branch", "list", "-r") == (0, "", "")


# -- golden listings -----------------------------------------------------------


def test_golden_listings(
    bare: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    git("branch", "feature/long-name", "main", cwd=bare)
    git(
        "worktree",
        "add",
        "-q",
        str(bare / "wt" / "feature"),
        "feature/long-name",
        cwd=bare,
    )
    git("branch", "no-wt", "main", cwd=bare)
    monkeypatch.chdir(bare / "wt" / "main")
    flags = ["-d", "committerdate:short", "-s", "refname"]
    assert run(capfd, "branch", "list", *flags)[1] == (
        "[feature/long-name]    test      (2024-01-02)\n"
        "[main]                 test      (2024-01-02)\n"
        "[no-wt]                test      (2024-01-02)\n"
    )
    assert run(capfd, "worktree", "list", *flags, "-p", "relative-gitdir")[1] == (
        "[feature/long-name]    ./wt/feature    test      (2024-01-02)\n"
        "[main]                 ./wt/main       test      (2024-01-02)\n"
    )
    assert run(capfd, "worktree", "list", *flags, "-p", "relative-cwd")[1] == (
        "[feature/long-name]    ../feature    test      (2024-01-02)\n"
        "[main]                 ./            test      (2024-01-02)\n"
    )
    home_rel = fgb.relative_path(str(tmp_path / "home"), real(bare))
    assert (
        run(capfd, "worktree", "list", *flags, "-p", "relative-home")[1]
        .split("\n")[1]
        .startswith(f"[main]                 {home_rel}/wt/main ")
    )
    assert run(capfd, "worktree", "list", *flags, "-p", "relative-wt-base")[1] == (
        "[feature/long-name]    ./feature    test      (2024-01-02)\n"
        "[main]                 ./main       test      (2024-01-02)\n"
    )


def test_narrow_terminal_drops_columns(
    bare: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(bare)
    # Expected lines checked against the shell version at the same widths
    flags = ["-d", "committerdate:short", "-p", "relative-repo"]
    for width, line in (
        ("36", "[main]   ./wt/main test   (2024-01-02)"),
        # The path column becomes a "+" flag first, then author and date go
        ("35", "[main]   + test   (2024-01-02)"),
        ("22", "[main]   + (2024-01-02)"),
        ("10", "[main]   +"),
    ):
        monkeypatch.setenv("COLUMNS", width)
        assert run(capfd, "worktree", "list", *flags)[1] == f"{line}\n"
    # The branch column is padded to its width, as before
    assert run(capfd, "branch", "list", "-d", "committerdate:short")[1] == "[main]  \n"


def test_long_author_names_are_shortened(
    plain: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(plain)
    out = run(capfd, "branch", "list", "-u", "%(authorname) / a very long team name")[1]
    assert "[main]      .../ a very long team name    (" in out


# -- branch manage actions ---------------------------------------------------


def test_switch_branch(
    plain: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    git("branch", "other", cwd=plain)
    monkeypatch.chdir(plain)
    stub.pick("[other]")
    assert run(capfd, "branch", "manage")[0] == 0
    assert git("branch", "--show-current", cwd=plain) == "other"


def test_switch_to_remote_branch(
    clone: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(clone)
    stub.pick("(origin/orphan)")
    assert run(capfd, "branch", "manage", "-r")[0] == 0
    assert git("branch", "--show-current", cwd=clone) == "orphan"


def test_switch_needs_a_worktree(
    bare: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(bare)
    stub.pick("[main]")
    code, _, err = run(capfd, "branch", "manage")
    assert code == fgb.EXIT_NO_REPO
    assert "Not inside a Git worktree" in err


def test_delete_branches(
    plain: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    for name in ("one", "two"):
        git("branch", name, cwd=plain)
    monkeypatch.chdir(plain)
    stub.pick("[one]", "[two]", key="ctrl-d")
    answer(monkeypatch, "yn")
    code, out, _ = run(capfd, "branch", "manage")
    assert code == 0
    assert "Delete local branch: `one'? (y|N): " in out
    assert "Deleted branch one" in out
    assert not branch_exists(plain, "one")
    assert branch_exists(plain, "two")


def test_force_skips_the_question(
    plain: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    git("branch", "one", cwd=plain)
    monkeypatch.chdir(plain)
    stub.pick("[one]", key="ctrl-d")
    code, out, _ = run(capfd, "branch", "manage", "-f")
    assert code == 0
    assert "(y|N)" not in out
    assert not branch_exists(plain, "one")


def test_unmerged_branch(
    plain: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    git("checkout", "-q", "-b", "feat.x", cwd=plain)
    commit_file(plain, "unmerged")
    git("checkout", "-q", "main", cwd=plain)
    monkeypatch.chdir(plain)
    stub.pick("[feat.x]", key="ctrl-d")
    # --force skips the first question, not the unmerged one
    answer(monkeypatch, "n")
    out = run(capfd, "branch", "manage", "-f")[1]
    assert "The branch 'feat.x' is not yet merged into the 'main' branch." in out
    assert branch_exists(plain, "feat.x")
    stub.pick("[feat.x]", key="ctrl-d")
    answer(monkeypatch, "y")
    run(capfd, "branch", "manage", "-f")
    assert not branch_exists(plain, "feat.x")


def test_extended_delete_local_then_remote(
    clone: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(clone)
    stub.pick("[stale]", key="ctrl-alt-d")
    answer(monkeypatch, "yyy")
    out = run(capfd, "branch", "manage")[1]
    assert "Delete branch: 'stale' from remote: origin?" in out
    assert not branch_exists(clone, "stale")
    assert not git("branch", "--list", "stale", cwd=tmp_path / "remote.git")


def test_extended_delete_remote_then_local(
    clone: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    # Deleting a remote branch with extended delete also offers its local
    # tracking branch (the shell version looked up a ref without the remote)
    monkeypatch.chdir(clone)
    stub.pick("(origin/stale)", key="ctrl-alt-d")
    answer(monkeypatch, "yyy")
    out = run(capfd, "branch", "manage", "-r")[1]
    assert "Delete local branch: `stale'?" in out
    assert not branch_exists(clone, "stale")
    assert not git("branch", "--list", "stale", cwd=tmp_path / "remote.git")


def test_remote_delete_declined(
    clone: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(clone)
    stub.pick("(origin/orphan)", key="ctrl-d")
    answer(monkeypatch, "n")
    # --force never skips deleting a remote branch
    run(capfd, "branch", "manage", "-r", "-f")
    assert git("branch", "--list", "orphan", cwd=tmp_path / "remote.git")


def test_info_action(
    plain: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(plain)
    stub.pick("[main]", key="ctrl-o")
    out = run(capfd, "branch", "manage")[1]
    assert out.startswith("branch        : main\n")
    assert "message       : add base" in out


def test_fork_branch(
    plain: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(plain)
    stub.pick("[main]", key="alt-n")
    stub.type("main-fork")
    code, out, _ = run(capfd, "branch", "manage")
    assert code == 0
    assert "Fork the branch `main' and switch to it." in out
    assert git("branch", "--show-current", cwd=plain) == "main-fork"
    prompt = stub.calls()[1]["args"]
    assert "--query=main-fork" in prompt
    assert "--prompt=Enter a name for the new branch: " in prompt
    assert "--disabled" in prompt
    assert "--no-separator" in prompt


def test_fork_rejects_bad_names(
    plain: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(plain)
    stub.pick("[main]", key="alt-n")
    stub.type("")
    code, _, err = run(capfd, "branch", "manage")
    assert code == 1
    assert "empty branch name, aborting" in err
    stub.pick("[main]", key="alt-n")
    stub.type("bad..name")
    code, _, err = run(capfd, "branch", "manage")
    assert code == 1
    assert "not a valid branch name: `bad..name'" in err
    stub.pick("[main]", key="alt-n")
    stub.respond("", rc=130)
    assert run(capfd, "branch", "manage")[0] == 0


def test_old_fzf_gets_no_new_options(
    plain: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("FGB_STUB_VERSION", "0.29.0")
    monkeypatch.chdir(plain)
    stub.pick("[main]", key="alt-n")
    stub.type("x")
    run(capfd, "branch", "manage")
    assert "--no-separator" not in stub.calls()[1]["args"]


# -- worktree actions --------------------------------------------------------


def test_jump_writes_the_cwd_file(
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(plain)
    cwd_file = tmp_path / "cwd"
    stub.pick("[spaced]")
    code, out, err = run(capfd, "--cwd-file", str(cwd_file), "worktree", "manage")
    target = real(tmp_path / "with space" / "wt")
    assert code == 0
    assert f"Jumped to worktree: {target}, for branch 'spaced'" in out
    assert cwd_file.read_text() == target
    assert err == ""


def test_jump_without_wrapper_prints_a_hint(
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(plain)
    stub.pick("[spaced]")
    _, _, err = run(capfd, "worktree", "manage")
    assert err.startswith(f"cd '{real(tmp_path / 'with space' / 'wt')}'")


def test_delete_current_worktree(
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    wt = tmp_path / "with space" / "wt"
    (wt / "sub").mkdir()
    monkeypatch.chdir(wt / "sub")
    cwd_file = tmp_path / "cwd"
    stub.pick("[spaced]", key="ctrl-d")
    answer(monkeypatch, "yn")
    code, out, _ = run(capfd, "--cwd-file", str(cwd_file), "worktree", "manage")
    assert code == 0
    assert f"Deleted worktree: {real(wt)} for branch 'spaced'" in out
    assert "Delete the corresponding 'spaced' branch as well?" in out
    assert not wt.exists()
    assert branch_exists(plain, "spaced")
    assert cwd_file.read_text() == real(plain)


def test_cancelled_delete_keeps_the_directory(
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    wt = tmp_path / "with space" / "wt"
    monkeypatch.chdir(wt)
    cwd_file = tmp_path / "cwd"
    stub.pick("[spaced]", key="ctrl-d")
    answer(monkeypatch, "n")
    run(capfd, "--cwd-file", str(cwd_file), "worktree", "manage")
    assert wt.exists()
    assert not cwd_file.exists()


def test_delete_dirty_worktree_and_branch(
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    wt = tmp_path / "with space" / "wt"
    (wt / "new.txt").write_text("x\n")
    monkeypatch.chdir(plain)
    stub.pick("[spaced]", key="ctrl-d")
    answer(monkeypatch, "yyy")
    out = run(capfd, "worktree", "manage")[1]
    assert "This will permanently reset/delete the following files:" in out
    assert "?? new.txt" in out
    assert not wt.exists()
    assert not branch_exists(plain, "spaced")


def test_delete_dirty_worktree_declined(
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    wt = tmp_path / "with space" / "wt"
    (wt / "new.txt").write_text("x\n")
    monkeypatch.chdir(wt)
    cwd_file = tmp_path / "cwd"
    stub.pick("[spaced]", key="ctrl-d")
    answer(monkeypatch, "n")
    out = run(capfd, "--cwd-file", str(cwd_file), "worktree", "manage", "-f")[1]
    assert "Delete the corresponding" not in out
    assert wt.exists()
    assert not cwd_file.exists()


def test_delete_locked_worktree_fails_cleanly(
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path / "plain-wt-locked")
    cwd_file = tmp_path / "cwd"
    stub.pick("[locked]", key="ctrl-d")
    code, out, err = run(capfd, "--cwd-file", str(cwd_file), "worktree", "manage", "-f")
    assert code != 0
    assert "locked" in err
    assert "Delete the corresponding" not in out
    assert not cwd_file.exists()


def test_delete_detached_worktree(
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    git("worktree", "add", "-q", "--detach", str(tmp_path / "det"), cwd=plain)
    head = git("rev-parse", "--short=7", "HEAD", cwd=plain)
    monkeypatch.chdir(plain)
    stub.pick(f"{{{head}}}", key="ctrl-d")
    code, out, _ = run(capfd, "worktree", "manage", "-f")
    assert code == 0
    assert f"for detached HEAD '{head}'" in out
    assert not (tmp_path / "det").exists()


def test_total_deletes_branch_without_worktree(
    plain: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    git("branch", "loose", cwd=plain)
    monkeypatch.chdir(plain)
    stub.pick("[loose]", key="ctrl-d")
    run(capfd, "worktree", "total")
    assert not branch_exists(plain, "loose")


def test_add_with_confirm(
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    git("branch", "feature", cwd=plain)
    monkeypatch.chdir(plain)
    cwd_file = tmp_path / "cwd"
    stub.pick("[feature]")
    code, out, _ = run(capfd, "--cwd-file", str(cwd_file), "worktree", "add", "-c")
    target = f"{real(plain)}/.git/wt/feature"
    assert code == 0
    assert f"Worktree {target} for branch 'feature' added successfully." in out
    assert cwd_file.read_text() == target
    assert len(stub.calls()) == 1


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("custom", "{base}/custom"),
        ("../out/x", "{plain}/.git/out/x"),
        ("/ABS", "{tmp}/abs"),
    ],
)
def test_add_with_path_prompt(
    typed: str,
    expected: str,
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    git("branch", "feature", cwd=plain)
    monkeypatch.chdir(plain)
    cwd_file = tmp_path / "cwd"
    base = f"{real(plain)}/.git/wt"
    if typed == "/ABS":
        typed = f"{real(tmp_path)}/abs"
    stub.pick("[feature]")
    stub.type(typed)
    code, out, _ = run(capfd, "--cwd-file", str(cwd_file), "worktree", "add")
    assert code == 0
    assert "Add a new worktree for 'feature'." in out
    assert f"Enter an absolute path or a path relative to: {base} " in out
    assert "(FGB_WT_BASE_PATH_REGULAR)" in out
    assert "--query=feature" in stub.calls()[1]["args"]
    want = expected.format(base=base, plain=real(plain), tmp=real(tmp_path))
    assert cwd_file.read_text() == want
    assert git("branch", "--show-current", cwd=want) == "feature"


def test_add_cancelled_prompt(
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    git("branch", "feature", cwd=plain)
    monkeypatch.chdir(plain)
    stub.pick("[feature]")
    stub.respond("", rc=130)
    assert run(capfd, "worktree", "add")[0] == fgb.FZF_CANCELLED
    assert not (plain / ".git" / "wt" / "feature").exists()


def test_add_failure_passes_git_code(
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    git("branch", "feature", cwd=plain)
    (plain / ".git" / "wt" / "feature").mkdir(parents=True)
    (plain / ".git" / "wt" / "feature" / "x").write_text("x")
    monkeypatch.chdir(plain)
    stub.pick("[feature]")
    code, _, err = run(capfd, "worktree", "add", "-c")
    assert code != 0
    assert "already exists" in err


def test_verbose_key_asks_despite_confirm(
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    git("branch", "feature", cwd=plain)
    monkeypatch.chdir(plain)
    stub.pick("[feature]", key="ctrl-v")
    stub.type("elsewhere")
    run(capfd, "worktree", "add", "-c")
    assert (plain / ".git" / "wt" / "elsewhere").is_dir()


def test_add_remote_branch_in_bare_repo(
    clone: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(clone)
    stub.pick("(origin/orphan)")
    stub.type("orphan")
    out = run(capfd, "worktree", "add", "-r")[1]
    assert "Add a new worktree for 'orphan' (remote branch: 'origin/orphan')." in out
    rows = stub.calls()[0]["stdin"]
    # Remote rows whose counterpart has a worktree are not offered
    assert "origin/linked" not in rows
    assert "origin/orphan" in rows
    assert "origin/HEAD" not in rows
    assert (
        git("branch", "--show-current", cwd=clone / ".git" / "wt" / "orphan")
        == "orphan"
    )


def test_add_offers_reset_of_stale_counterpart(
    clone: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(clone)
    stub.pick("(origin/stale)")
    answer(monkeypatch, "y")
    out = run(capfd, "worktree", "add", "-r", "-c")[1]
    assert "The new worktree checks out the local branch" in out
    assert (
        git("log", "-1", "--format=%s", cwd=clone / ".git" / "wt" / "stale")
        == "add stale"
    )


def test_fork_into_new_worktree_with_stash(
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    (plain / "base.txt").write_text("changed\n")
    monkeypatch.chdir(plain)
    cwd_file = tmp_path / "cwd"
    stub.pick("[main]", key="alt-n")
    stub.type("topic")
    answer(monkeypatch, "y")
    code, out, _ = run(capfd, "--cwd-file", str(cwd_file), "worktree", "total", "-c")
    target = f"{real(plain)}/.git/wt/topic"
    assert code == 0
    assert "Switched to a new branch 'topic'" in out
    assert "The current worktree has uncommitted changes:" in out
    assert cwd_file.read_text() == target
    assert (Path(target) / "base.txt").read_text() == "changed\n"
    assert (plain / "base.txt").read_text() == "base\n"
    assert git("stash", "list", cwd=plain) == ""
    assert git("branch", "--show-current", cwd=plain) == "main"


def test_fork_verbose_retries_existing_path(
    plain: Path,
    tmp_path: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    taken = plain / ".git" / "wt" / "topic"
    taken.mkdir(parents=True)
    (taken / "x").write_text("x")
    monkeypatch.chdir(plain)
    stub.pick("[main]", key="alt-n")
    stub.type("topic")
    stub.type("topic2")
    answer(monkeypatch, "y")
    code, out, _ = run(capfd, "worktree", "add", "-c")
    assert code == 0
    assert (
        f"The path '{taken.resolve()}' already exists."
        in out.replace(str(plain), real(plain))
        or "already exists." in out
    )
    assert (
        git("branch", "--show-current", cwd=plain / ".git" / "wt" / "topic2") == "topic"
    )


def test_fork_failure_offers_branch_removal(
    plain: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    taken = plain / ".git" / "wt" / "topic"
    taken.mkdir(parents=True)
    (taken / "x").write_text("x")
    monkeypatch.chdir(plain)
    stub.pick("[main]", key="alt-N")
    stub.type("topic")
    stub.type("topic")
    answer(monkeypatch, "ny")
    out = run(capfd, "worktree", "add")[1]
    assert "Would you like to enter another path?" in out
    assert not branch_exists(plain, "topic")


def test_query_reaches_worktree_pickers(
    plain: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(plain)
    run(capfd, "worktree", "total", "-c", "a", "b")
    assert "--query=a b" in stub.calls()[0]["args"]


def test_restore_stash_into_initial_worktree_on_failure(
    plain: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    # When the worktree could not be created, the stash goes back where it came
    # from, without the reset/clean that is only meant for the new worktree
    (plain / "base.txt").write_text("changed\n")
    (plain / "keep.txt").write_text("untracked\n")
    git("stash", "push", "-q", "-m", "x", cwd=plain)
    stash = git("rev-parse", "stash@{0}", cwd=plain)
    monkeypatch.chdir(plain)
    app = fgb.Fgb(fgb.Settings(), None)
    app.restore_stash(stash, str(plain), str(plain))
    assert (plain / "base.txt").read_text() == "changed\n"
    assert (plain / "keep.txt").exists()
    assert git("stash", "list", cwd=plain) == ""


# The real fzf, found before the stub goes first on PATH
REAL_FZF = shutil.which("fzf")


@pytest.mark.skipif(REAL_FZF is None, reason="fzf is not installed")
def test_real_fzf_accepts_the_arguments(
    clone: Path,
    stub: Stub,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Replay the recorded picker and prompt calls against the real fzf in
    --filter mode, which needs no terminal: unknown options fail there."""
    monkeypatch.chdir(clone)
    stub.pick("[main]", key="alt-n")
    stub.type("x")
    run(capfd, "worktree", "total", "-a", "query")
    calls = stub.calls()
    # The picker, the branch name prompt and the worktree path prompt
    assert len(calls) == len(["picker", "name", "path"])
    for call in calls:
        result = subprocess.run(
            [str(REAL_FZF), *call["args"], "--filter="],
            input=call["stdin"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert result.returncode in (0, 1), result.stderr
        assert result.stderr == ""
