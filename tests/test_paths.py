"""Path helpers: normalizing, ~, relative paths, $VAR expansion."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from conftest import fgb


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/a/b/../c", "/a/c"),
        ("/a/./b//c", "/a/b/c"),
        ("/a/b/../..", "/"),
        ("/a/../../b", "/b"),
        ("/x/r/.git/../wt", "/x/r/wt"),
        ("../../x", "../../x"),
        ("a/../..", ".."),
        ("/with space/wt", "/with space/wt"),
        (".", "."),
        ("", "."),
    ],
)
def test_normalize_path(path: str, expected: str) -> None:
    assert fgb.normalize_path(path) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/home/ann/proj", "~/proj"),
        ("/home/ann", "~"),
        ("/home/annabel/proj", "/home/annabel/proj"),
        ("/opt/x", "/opt/x"),
    ],
)
def test_tilde_path(path: str, expected: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/home/ann/")
    assert fgb.tilde_path(path) == expected


@pytest.mark.parametrize(
    ("rel", "expected"),
    [
        (".", "./"),
        ("..", "../"),
        ("../..", "../../"),
        ("../x", "../x"),
        ("wt/foo", "./wt/foo"),
    ],
)
def test_render_relative(rel: str, expected: str) -> None:
    assert fgb.render_relative(rel) == expected


@pytest.fixture
def rel_root(tmp_path: Path) -> Path:
    root = Path(os.path.realpath(tmp_path)) / "rel"
    for sub in ("a/b/c", "a/bc", "x y/z", "real/wt"):
        (root / sub).mkdir(parents=True)
    (root / "link").symlink_to(root / "real")
    return root


def test_relative_paths(rel_root: Path) -> None:
    r = str(rel_root)
    assert fgb.relative_path(f"{r}/a", f"{r}/a") == "."
    assert fgb.relative_path(f"{r}/a", f"{r}/a/b/c") == "b/c"
    assert fgb.relative_path(f"{r}/a/b/c", f"{r}/a") == "../.."
    # /a/b must not count as an ancestor of /a/bc
    assert fgb.relative_path(f"{r}/a/b", f"{r}/a/bc") == "../bc"
    assert fgb.relative_path("/", f"{r}/a") == f"{r.lstrip('/')}/a"
    assert fgb.relative_path(f"{r}/a", f"{r}/x y/z") == "../x y/z"
    assert fgb.relative_path(f"{r}/link", f"{r}/real/wt") == "wt"
    assert fgb.relative_path(f"{r}/real", f"{r}/link/wt") == "wt"
    assert fgb.relative_path(f"{r}/a", f"{r}/a/missing/deeper") == "missing/deeper"


def test_macos_var_resolves_like_realpath(tmp_path: Path) -> None:
    # On macOS the temporary directory lives under /var -> /private/var
    logical = str(tmp_path)
    assert fgb.relative_path(logical, os.path.realpath(logical)) == "."


def test_relative_cwd_mode(rel_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(rel_root / "a" / "b")
    app = fgb.Fgb(fgb.Settings(wt_path_display="relative-cwd"), None)
    assert app.format_wt_path(str(rel_root / "a" / "bc")) == "../bc"


def test_expand_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FGB_TEST_VAR", "/srv/wt")
    monkeypatch.delenv("FGB_NO_SUCH_VAR", raising=False)
    assert fgb.expand_env("$FGB_TEST_VAR/x") == "/srv/wt/x"
    assert fgb.expand_env("${FGB_TEST_VAR}/x") == "/srv/wt/x"
    assert fgb.expand_env("plain/path") == "plain/path"
    assert fgb.expand_env("$FGB_NO_SUCH_VAR/y") == "/y"
    assert fgb.expand_env("a$(id -u)b") == "a$(id -u)b"
    assert fgb.expand_env("cost: $") == "cost: $"


@pytest.mark.parametrize(
    "hostile",
    ['${x;touch "$T/pwned"}', '${x$(touch "$T/pwned")}', '${a[$(touch "$T/pwned")]}'],
)
def test_expand_env_runs_nothing(
    hostile: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("T", str(tmp_path))
    # Not a plain variable name, so it expands to nothing
    assert fgb.expand_env(f"{hostile}/y") == "/y"
    assert not (tmp_path / "pwned").exists()


@pytest.mark.parametrize(
    ("mode", "path", "expected"),
    [
        ("tilde", "/home/ann/proj/wt", "~/proj/wt"),
        ("tilde", "/home/annabel/proj", "/home/annabel/proj"),
        ("tilde-gitdir", "/home/ann/proj/wt", "~/proj/wt"),
        ("absolute", "/home/ann/proj/wt", "/home/ann/proj/wt"),
        ("absolute-gitdir", "/home/ann/proj/wt", "/home/ann/proj/wt"),
        ("relative-home", "/home/ann/proj/wt", "~/proj/wt"),
        ("relative-home", "/home/ann", "~/"),
    ],
)
def test_display_modes(
    mode: str, path: str, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", "/home/ann")
    app = fgb.Fgb(fgb.Settings(wt_path_display=mode), None)
    assert app.format_wt_path(path) == expected


def test_relative_home_outside_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "home").mkdir(exist_ok=True)
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    app = fgb.Fgb(fgb.Settings(wt_path_display="relative-home"), None)
    assert app.format_wt_path(str(tmp_path / "elsewhere")) == "../elsewhere"


def test_expand_user_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/home/ann")
    assert fgb.expand_user_path("~", "/base") == "/home/ann"
    assert fgb.expand_user_path("~/x", "/base") == "/home/ann/x"
    assert fgb.expand_user_path("/abs", "/base") == "/abs"
    assert fgb.expand_user_path("rel/x", "/base") == "/base/rel/x"
