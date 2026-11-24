"""Repository state: identity, base path templates, worktree parsing,
remote counterparts and the reset offer."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import answer, commit_file, fgb, git, new_app, real


def test_ordinary_repo(plain: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(plain)
    app = new_app()
    assert app.root == real(plain)
    assert app.common_dir == real(plain / ".git")
    assert not app.is_bare


def test_bare_repo(bare: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(bare)
    app = new_app()
    assert app.is_bare
    assert app.root == real(bare)
    assert app.common_dir == real(bare)
    assert app.wt_paths == {"refs/heads/main": real(bare / "wt" / "main")}


def test_bare_repo_from_a_worktree(bare: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(bare / "wt" / "main")
    app = new_app()
    assert app.is_bare
    assert app.root == real(bare)


def test_separate_git_dir(
    sepgitdir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(sepgitdir)
    app = new_app()
    assert app.common_dir == real(tmp_path / "sep.gitdir")
    assert app.root == real(sepgitdir)
    assert app.wt_paths["refs/heads/main"] == real(sepgitdir)


@pytest.mark.parametrize(
    ("template", "fixture", "expected"),
    [
        ("./wt", "plain", "{plain}/.git/wt"),
        ("../wt", "plain", "{plain}/wt"),
        ("/abs/wt", "plain", "/abs/wt"),
        ("../w/{repo_name}", "plain", "{plain}/w/plain"),
        ("../w/{repo_name}", "bare", "{tmp}/w/hub.git"),
        ("../w/{repo_name_short}", "bare", "{tmp}/w/hub"),
        ("~/worktrees", "plain", "{home}/worktrees"),
        ("~", "plain", "{home}"),
        ("$FGB_TEST_VAR/w", "plain", "/srv/wt/w"),
        ("${FGB_TEST_VAR}/{repo_name}", "plain", "/srv/wt/plain"),
    ],
)
def test_base_path_templates(
    template: str,
    fixture: str,
    expected: str,
    request: pytest.FixtureRequest,
    tmp_path: Path,
    isolated: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = request.getfixturevalue(fixture)
    monkeypatch.setenv("FGB_TEST_VAR", "/srv/wt")
    monkeypatch.chdir(repo)
    app = new_app(wt_base_bare=template, wt_base_regular=template)
    want = expected.format(
        plain=real(tmp_path / "plain"), tmp=real(tmp_path), home=str(isolated)
    )
    assert app.wt_base == want


def test_porcelain_parsing(
    plain: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(plain)
    app = new_app()
    assert app.wt_paths["refs/heads/spaced"] == real(tmp_path / "with space" / "wt")
    assert app.wt_paths["refs/heads/locked"] == real(tmp_path / "plain-wt-locked")
    assert app.wt_paths["refs/heads/main"] == real(plain)


def test_detached_worktree(
    plain: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    head = git("rev-parse", "HEAD", cwd=plain)
    git("worktree", "add", "-q", "--detach", str(tmp_path / "det"), cwd=plain)
    monkeypatch.chdir(plain)
    app = new_app()
    ref = f"detached/heads/{head[:7]}"
    assert app.wt_paths[ref] == real(tmp_path / "det")
    rows = app.detached_rows()
    assert [row.name for row in rows] == [head[:7]]
    assert rows[0].author == "test"
    assert rows[0].date


def test_detached_row_formats(
    plain: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    git("worktree", "add", "-q", "--detach", str(tmp_path / "det"), cwd=plain)
    monkeypatch.chdir(plain)
    app = new_app(
        date_format="committerdate:short",
        author_format="%(authorname) %(authoremail)",
    )
    row = app.detached_rows()[0]
    assert row.date == "2024-01-02"
    assert row.author == "test <test@example.com>"


# -- remote branches ---------------------------------------------------------


def test_remote_counterparts(
    clone: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(clone)
    app = new_app()
    assert app.remote_wt["refs/remotes/origin/linked"] == (
        real(tmp_path / "wt-linked"),
        "linked",
    )
    assert "refs/remotes/origin/stale" not in app.remote_wt
    assert "refs/remotes/origin/orphan" not in app.remote_wt


def test_remote_tie_break(
    clone: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(clone)
    key = "refs/remotes/origin/twin"
    assert new_app().remote_wt[key] == (real(tmp_path / "wt-twin"), "twin")
    git("worktree", "remove", "--force", str(tmp_path / "wt-twin"), cwd=clone)
    assert new_app().remote_wt[key][1] == "aaa-twin"
    git("worktree", "remove", "--force", str(tmp_path / "wt-aaa-twin"), cwd=clone)
    assert new_app().remote_wt[key][1] == "zzz-twin"
    git("worktree", "remove", "--force", str(tmp_path / "wt-zzz-twin"), cwd=clone)
    assert key not in new_app().remote_wt


def test_jump_to_remote_counterpart(
    clone: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(clone)
    app = new_app()
    assert app.jump_or_add("(origin/linked)") == 0
    assert app.new_cwd == real(tmp_path / "wt-linked")
    assert "Jumped" in capfd.readouterr().err


def test_jump_reports_stale_counterpart(
    clone: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    wt = tmp_path / "wt-linked"
    git("reset", "-q", "--hard", "origin/linked~1", cwd=wt)
    monkeypatch.chdir(clone)

    answer(monkeypatch, "n")
    new_app().jump_or_add("(origin/linked)")
    out, err = capfd.readouterr()
    assert "1 commit behind" in out
    assert "has it checked out" in out
    assert "Jumped" in err
    assert git("log", "-1", "--format=%s", "linked", cwd=clone) == "add base"

    answer(monkeypatch, "y")
    new_app().jump_or_add("(origin/linked)")
    assert git("log", "-1", "--format=%s", "linked", cwd=clone) == "add linked"
    capfd.readouterr()

    answer(monkeypatch, "n")
    new_app().jump_or_add("(origin/linked)")
    assert "commit behind" not in capfd.readouterr().out


def test_jump_lists_uncommitted_changes(
    clone: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    wt = tmp_path / "wt-linked"
    git("reset", "-q", "--hard", "origin/linked~1", cwd=wt)
    (wt / "base.txt").write_text("dirty\n")
    (wt / "untracked.txt").write_text("new\n")
    monkeypatch.chdir(clone)
    answer(monkeypatch, "n")
    new_app().jump_or_add("(origin/linked)")
    out = capfd.readouterr().out
    assert "discards these uncommitted changes" in out
    assert "base.txt" in out
    assert "untracked.txt" in out
    assert len(git("status", "--short", cwd=wt).splitlines()) == 2


def test_no_reset_offer_for_local_rows(
    clone: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(clone)
    new_app().jump_or_add("[linked]")
    assert "commit behind" not in capfd.readouterr().out


def test_offer_reset_before_creating(
    clone: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(clone)
    app = new_app()
    answer(monkeypatch, "n")
    app.offer_reset_to_remote("origin/stale", "stale")
    assert "1 commit behind" in capfd.readouterr().out
    assert git("log", "-1", "--format=%s", "stale", cwd=clone) == "add base"
    answer(monkeypatch, "y")
    app.offer_reset_to_remote("origin/stale", "stale")
    assert git("log", "-1", "--format=%s", "stale", cwd=clone) == "add stale"
    capfd.readouterr()
    answer(monkeypatch, "y")
    app.offer_reset_to_remote("origin/stale", "stale")
    app.offer_reset_to_remote("origin/orphan", "orphan")
    app.offer_reset_to_remote("", "stale")
    assert capfd.readouterr().out == ""


def test_offer_reset_when_ahead_too(
    clone: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    wt = tmp_path / "wt-stale"

    def commit_on_stale(name: str) -> None:
        git("worktree", "add", "-q", str(wt), "stale", cwd=clone)
        commit_file(wt, name)
        git("worktree", "remove", "--force", str(wt), cwd=clone)

    monkeypatch.chdir(clone)
    commit_on_stale("ahead1")
    answer(monkeypatch, "n")
    new_app().offer_reset_to_remote("origin/stale", "stale")
    assert "1 local commit that is not on the remote" in capfd.readouterr().out
    assert git("log", "-1", "--format=%s", "stale", cwd=clone) == "add ahead1"

    commit_on_stale("ahead2")
    answer(monkeypatch, "n")
    new_app().offer_reset_to_remote("origin/stale", "stale")
    assert "2 local commits that are not on the remote" in capfd.readouterr().out

    git("branch", "-f", "stale", "origin/stale", cwd=clone)
    commit_on_stale("onlyahead")
    answer(monkeypatch, "y")
    new_app().offer_reset_to_remote("origin/stale", "stale")
    assert capfd.readouterr().out == ""
    assert git("log", "-1", "--format=%s", "stale", cwd=clone) == "add onlyahead"


def test_listing_shows_resolved_worktrees(
    clone: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(clone)
    app = new_app(wt_path_display="absolute")
    app.rows = app.git_branch_list("all")
    app.set_widths(app.rows)
    lines = [fgb.ANSI_ESCAPE.sub("", line) for line in app.worktree_lines()]
    listing = "\n".join(lines)
    assert "[linked]" in listing
    assert "(origin/linked)" in listing
    assert git(
        "for-each-ref", "--format=%(refname)", "refs/remotes/origin/HEAD", cwd=clone
    )
    assert "origin/HEAD" not in listing

    def line_of(token: str) -> str:
        return next(line for line in lines if line.startswith(token))

    assert real(tmp_path / "wt-linked") in line_of("(origin/linked)")
    assert real(tmp_path / "wt-twin") in line_of("(origin/twin)")
    assert "/wt-" not in line_of("(origin/stale)")


def test_branch_info(
    clone: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(clone)
    app = new_app()
    app.print_branch_info("linked")
    assert real(tmp_path / "wt-linked") in capfd.readouterr().out
    app.print_branch_info("origin/linked")
    out = capfd.readouterr().out
    assert real(tmp_path / "wt-linked") in out
    assert "(linked)" not in out
    app.print_branch_info("origin/stale")
    assert "worktree" not in capfd.readouterr().out

    git("branch", "-q", "alias", "origin/orphan", cwd=clone)
    git("branch", "-q", "--set-upstream-to=origin/orphan", "alias", cwd=clone)
    git("worktree", "add", "-q", str(tmp_path / "wt-alias"), "alias", cwd=clone)
    new_app().print_branch_info("origin/orphan")
    assert "(alias)" in capfd.readouterr().out


def test_branch_info_layout(
    plain: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    (plain / "f.txt").write_text("x\n")
    git("add", "f.txt", cwd=plain)
    git("commit", "-q", "-m", "subject", "-m", "line two\nline three", cwd=plain)
    monkeypatch.chdir(plain)
    new_app().print_branch_info("main")
    out = capfd.readouterr().out
    head = git("rev-parse", "HEAD", cwd=plain)
    assert out == (
        "branch        : main\n"
        f"worktree      : {real(plain)}\n"
        "author        : test <test@example.com>\n"
        "authordate    : 2024-01-02 03:04:05 +0000\n"
        "committer     : test <test@example.com>\n"
        "committerdate : 2024-01-02 03:04:05 +0000\n"
        f"HEAD          : {head}\n"
        "message       : subject\n"
        "                \n"
        "                line two\n"
        "                line three\n"
    )


def test_wt_path_width_counts_all_worktrees(
    clone: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(clone)
    app = new_app(wt_path_display="absolute")
    assert app.wt_path_width == max(len(path) for path in app.wt_paths.values())


def test_load_worktrees_outside_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(fgb.AppError):
        new_app()
