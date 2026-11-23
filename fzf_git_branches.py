#!/usr/bin/env python3
"""Manage Git branches and worktrees with fzf.

A standalone port of the fzf-git-branches shell function. A child process
cannot change its parent shell's directory, so commands that jump to a
worktree write the target to the file given with --cwd-file and a small
shell function (`fzf-git-branches init <shell>`, named `fgb`) runs the `cd`.
Without the wrapper, a "cd <path>" hint is printed instead.
"""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import os
import re
import shlex
import shutil
import subprocess
import sys
import termios
import time
import tty
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any, TextIO

if sys.version_info < (3, 10):  # noqa: UP036 - runs on older Pythons too
    sys.exit("fzf-git-branches: Python 3.10 or newer is required")

# Semantic version: MAJOR for breaking CLI or behavior changes, MINOR for new
# features, PATCH for fixes. Bump it with every change to this script.
__version__ = "1.1.1"

# Canonical program name for the version output (GNU: a constant, never
# derived from argv[0]); usage and error messages use the invoked name (PROG).
PROG_NAME = "fzf-git-branches"
# The shell function installed by `init`; usage shows it when run through it
WRAPPER_NAME = "fgb"
PROG = Path(sys.argv[0]).name
# Short and long options that take a value. Used to enforce GNU rules that
# argparse does not: `-s=x` is rejected, and a value that starts with `-`
# (`-s -committerdate`) is taken as the value, as getopt does.
SHORT_VALUE_OPTS = "sdupC"
LONG_VALUE_OPTS = (
    "--sort",
    "--date-format",
    "--author-format",
    "--wt-path-display",
    "--color",
    "--config",
    "--cwd-file",
)
# Options accepted before the command
GLOBAL_VALUE_OPTS = ("-C", "--color", "--config", "--cwd-file")

# Settings: environment variable names double as config file keys
ENV_CONFIG = "FGB_CONFIG"
ENV_SORT_ORDER = "FGB_SORT_ORDER"
ENV_DATE_FORMAT = "FGB_DATE_FORMAT"
ENV_AUTHOR_FORMAT = "FGB_AUTHOR_FORMAT"
ENV_WT_PATH_DISPLAY = "FGB_WT_PATH_DISPLAY"
ENV_WT_BASE_PATH_BARE = "FGB_WT_BASE_PATH_BARE"
ENV_WT_BASE_PATH_REGULAR = "FGB_WT_BASE_PATH_REGULAR"
ENV_FZF_OPTS = "FGB_FZF_OPTS"
ENV_COLOR = "FGB_COLOR"
ENV_KEEP_SUBDIR = "FGB_KEEP_SUBDIR"
DEFAULT_SORT_ORDER = "-committerdate"
DEFAULT_DATE_FORMAT = "committerdate:relative"
DEFAULT_AUTHOR_FORMAT = "committername"
DEFAULT_WT_BASE_PATH = "./wt"
# Picker action -> (setting, default key), in the order the headers list them
PICKER_KEYS = {
    "del": ("FGB_BINDKEY_DEL", "ctrl-d"),
    "extended-del": ("FGB_BINDKEY_EXTEND_DEL", "ctrl-alt-d"),
    "info": ("FGB_BINDKEY_INFO", "ctrl-o"),
    "verbose": ("FGB_BINDKEY_VERBOSE", "ctrl-v"),
    "fork": ("FGB_BINDKEY_NEW_BRANCH", "alt-n"),
    "fork-verbose": ("FGB_BINDKEY_NEW_BRANCH_VERBOSE", "alt-N"),
}
CONFIG_KEYS = {
    ENV_SORT_ORDER,
    ENV_DATE_FORMAT,
    ENV_AUTHOR_FORMAT,
    ENV_WT_PATH_DISPLAY,
    ENV_WT_BASE_PATH_BARE,
    ENV_WT_BASE_PATH_REGULAR,
    ENV_FZF_OPTS,
    ENV_COLOR,
    ENV_KEEP_SUBDIR,
    *(setting for setting, _ in PICKER_KEYS.values()),
}
# Worktree path display modes; the first one is the default
WT_PATH_MODES = (
    "tilde",
    "absolute",
    "relative-cwd",
    "relative-home",
    "relative-repo",
    "relative-gitdir",
    "relative-wt-base",
    "absolute-gitdir",
    "tilde-gitdir",
)
# --color: auto colors a stream only when it is a terminal and NO_COLOR is
# unset, always colors it even when piped, never colors anything
COLOR_MODES = ("auto", "always", "never")
# Values of boolean settings, compared case-insensitively
BOOLEAN_VALUES = {
    "true": True,
    "false": False,
    "1": True,
    "0": False,
    "yes": True,
    "no": False,
    "on": True,
    "off": False,
}
BOOLEAN_HELP = "true or false (also 1/0, yes/no, on/off)"
# Subcommands of the commands that have them
SUBCOMMANDS = {
    "branch": ["list", "manage"],
    "worktree": ["list", "manage", "add", "total"],
}
# Shells `init` can set up; sh covers dash and ksh
INIT_SHELLS = ("bash", "zsh", "sh", "ksh", "dash", "fish", "nu", "pwsh")
COMPLETION_SHELLS = ("bash", "zsh", "fish")
# Oldest fzf with every option the pickers and prompts use (--disabled)
FZF_MIN_VERSION = (0, 27, 0)
# --no-separator appeared later; it is only passed to fzf versions that have it
FZF_NO_SEPARATOR_VERSION = (0, 35, 0)
# fzf exit code for Esc / Ctrl-C
FZF_CANCELLED = 130
# Exit code for "not inside a Git repository / worktree"
EXIT_NO_REPO = 128

# Unit Separator between fields of git's formatted output
US = "\x1f"
DETACHED_PREFIX = "detached/heads/"
BRACKETS = {"local": ("[", "]"), "remote": ("(", ")"), "detached": ("{", "}")}
COLUMN_BRANCH = "Branch"
COLUMN_AUTHOR = "Author"
COLUMN_DATE = "Date"
# Author names longer than this that contain "/" are shortened to ".../rest"
AUTHOR_TRIM_WIDTH = 25
# Spaces between columns, at most
MAX_SPACER = 4

COLOR_RESET = "\033[0m"
COLOR_RED = "\033[31m"
COLOR_GREEN = "\033[32m"
COLOR_YELLOW = "\033[33m"
COLOR_BLUE = "\033[34m"
COLOR_MAGENTA = "\033[35m"
COLOR_BOLD = "\033[1m"
COLOR_RED_BOLD = "\033[1;31m"
COLOR_GREEN_BOLD = "\033[1;32m"
COLOR_YELLOW_BOLD = "\033[1;33m"
COLOR_BLUE_BOLD = "\033[1;34m"
ANSI_ESCAPE = re.compile(r"\033\[[0-9;]*m")

# Date atoms of git for-each-ref format strings, rewritten for `git log`
DATE_ATOM = re.compile(r"%\((authordate|committerdate)(?::([^)]+))?\)")
NAME_ATOMS = {
    "%(authorname)": "%an",
    "%(authoremail)": "<%ae>",
    "%(committername)": "%cn",
    "%(committeremail)": "<%ce>",
}
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclasses.dataclass
class ColorSetting:
    mode: str = COLOR_MODES[0]


# Set once by main() from --color, the environment or the config file
COLOR = ColorSetting()


class AppError(Exception):
    """An expected failure, reported as 'Error: <message>'."""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

LISTING_HELP = {
    "sort": (
        "sort key passed to git for-each-ref --sort; prefix with - for "
        "descending order; several keys separated by commas, e.g. refname, "
        f"-authordate, -committerdate,committername (env: {ENV_SORT_ORDER}, "
        f"default: {DEFAULT_SORT_ORDER})"
    ),
    "date": (
        "date column format (git for-each-ref), e.g. authordate:short, "
        "committerdate:format:'%%Y-%%m-%%d %%H:%%M' "
        f"(env: {ENV_DATE_FORMAT}, default: {DEFAULT_DATE_FORMAT})"
    ),
    "author": (
        "author column format (git for-each-ref), e.g. authoremail, "
        "'%%(committername) %%(committeremail)' "
        f"(env: {ENV_AUTHOR_FORMAT}, default: {DEFAULT_AUTHOR_FORMAT})"
    ),
}
WT_PATH_EPILOG = """\
Worktree path display modes (-p, FGB_WT_PATH_DISPLAY):
  tilde            $HOME replaced by ~ (default)
  absolute         full absolute path
  relative-cwd     relative to the current directory
  relative-home    relative to $HOME (~/... prefix)
  relative-repo    relative to the repo root (bare: same as relative-gitdir)
  relative-gitdir  relative to the git common dir (e.g. ./wt/branch)
  relative-wt-base relative to the worktree base path (e.g. ./branch)
  absolute-gitdir  git common dir prefix + relative path
  tilde-gitdir     same as absolute-gitdir with $HOME replaced by ~

FGB_WT_BASE_PATH_BARE / FGB_WT_BASE_PATH_REGULAR:
  Template for the default worktree base directory. A leading ~ and $VAR
  references are expanded; relative paths are anchored to the git common
  dir. Placeholders: {repo_name}, {repo_name_short}. Default: './wt'.
  Example: '../worktrees/{repo_name_short}' (sibling dir)"""
CONFIG_EPILOG = f"""\
Configuration:
  Settings are read from $HOME/.config/fgbrc (one KEY=value per line, read
  as data, never executed), or the file given with --config or
  {ENV_CONFIG}. Precedence: command line > environment > config file >
  default.

  FGB_SORT_ORDER                   sort key ({DEFAULT_SORT_ORDER})
  FGB_DATE_FORMAT                  date format ({DEFAULT_DATE_FORMAT})
  FGB_AUTHOR_FORMAT                author format ({DEFAULT_AUTHOR_FORMAT})
  FGB_WT_PATH_DISPLAY              worktree path display (tilde)
  FGB_WT_BASE_PATH_BARE            worktree base path, bare repos (./wt)
  FGB_WT_BASE_PATH_REGULAR         worktree base path, regular repos (./wt)
  FGB_BINDKEY_DEL                  delete key (ctrl-d)
  FGB_BINDKEY_EXTEND_DEL           extended delete key (ctrl-alt-d)
  FGB_BINDKEY_INFO                 info key (ctrl-o)
  FGB_BINDKEY_VERBOSE              force path prompt key (ctrl-v)
  FGB_BINDKEY_NEW_BRANCH           fork branch key (alt-n)
  FGB_BINDKEY_NEW_BRANCH_VERBOSE   fork with custom path (alt-N)
  FGB_FZF_OPTS                     fzf display options (replace the defaults)
  FGB_COLOR                        auto, always or never (auto)
  FGB_KEEP_SUBDIR                  keep the subdirectory, true or false (false)

Shell integration (the `fgb` function, which can change directory):
  eval "$({PROG_NAME} init bash)"   # or zsh, sh; see `init --help`

Exit codes: 0 success or cancelled, 1 error, 2 usage error, 128 not inside
a Git repository or worktree, 130 interrupted; failed git commands pass
their own code through."""
CONFIG_COMMAND_EPILOG = """\
Options given here are shown as a command would see them, e.g.
`fgb config -s refname`. To check a whole command line instead, append
--show-config to it: `fgb worktree add -a -c --show-config`.

Sources: command line, environment, config file (with its line number) or
default. An empty environment variable counts as unset; the report says so."""
PICKER_EPILOG = """\
Picker keys (change them with FGB_BINDKEY_*):
  enter, ctrl-y  jump / switch to the branch or worktree
  ctrl-t         toggle the selection
{keys}"""
PICKER_KEY_HELP = {
    "del": "delete the selected branches or worktrees",
    "extended-del": "delete, and also the linked local or remote branch",
    "info": "show branch information",
    "verbose": "ask for the worktree path even with --confirm",
    "fork": "fork the branch under the cursor (and add a worktree for it)",
    "fork-verbose": "fork and always ask for the worktree path",
}
INIT_EPILOG = f"""\
Add the line for your shell to its startup file:

  bash  ~/.bashrc                  eval "$({PROG_NAME} init bash)"
  zsh   ~/.zshrc (after compinit)  eval "$({PROG_NAME} init zsh)"
  sh, dash, ksh  ~/.profile / $ENV / ~/.kshrc
                                   eval "$({PROG_NAME} init sh)"
  fish  ~/.config/fish/config.fish {PROG_NAME} init fish | source
  nu    run once:
        {PROG_NAME} init nu | save -f ($nu.data-dir | path join \
"vendor/autoload/fzf-git-branches.nu")
  pwsh  $PROFILE                   Invoke-Expression (& {PROG_NAME} init \
pwsh | Out-String)

This defines the `fgb` function: it runs {PROG_NAME} and changes to the
worktree it jumps to (bash, zsh and fish also get completion)."""


def picker_epilog(actions: Sequence[str]) -> str:
    keys = "\n".join(
        f"  {PICKER_KEYS[action][1]:<14} {PICKER_KEY_HELP[action]}"
        for action in actions
    )
    return PICKER_EPILOG.format(keys=keys)


COLOR_HELP = (
    "color the output: auto (in terminals), always (also when piped) "
    f"or never (env: {ENV_COLOR}, default: auto)"
)
CONFIG_HELP = f"config file (env: {ENV_CONFIG}, default: $HOME/.config/fgbrc)"
KEEP_SUBDIR_HELP = (
    "keep the current subdirectory when jumping to or adding a worktree: "
    "land in the same path relative to its root, or the nearest parent that "
    f"exists there (env: {ENV_KEEP_SUBDIR}, default: false)"
)
SHOW_CONFIG_HELP = (
    "show the settings this command would use, where each one comes from, "
    "and what they resolve to, instead of running it"
)


def option_parents() -> dict[str, argparse.ArgumentParser]:
    """Option groups shared by several commands, by name."""
    parents = {
        name: argparse.ArgumentParser(add_help=False, allow_abbrev=False)
        for name in (
            "common",
            "listing",
            "wt_path",
            "subdir",
            "scope",
            "force",
            "confirm",
            "query",
        )
    }
    # Options shared by all commands, accepted after the command name too;
    # unset unless given there, so that one given before the command stays
    common = parents["common"]
    common.add_argument(
        "-C",
        "--color",
        choices=COLOR_MODES,
        default=argparse.SUPPRESS,
        help=COLOR_HELP,
    )
    common.add_argument(
        "--config", metavar="FILE", default=argparse.SUPPRESS, help=CONFIG_HELP
    )
    common.add_argument(
        "--show-config",
        action="store_true",
        default=argparse.SUPPRESS,
        help=SHOW_CONFIG_HELP,
    )
    # Set by the shell wrapper: the file to write the new directory to
    common.add_argument(
        "--cwd-file", metavar="FILE", default=argparse.SUPPRESS, help=argparse.SUPPRESS
    )
    common.add_argument(
        "--version",
        action="version",
        version=f"{PROG_NAME} {__version__}",
        help="show the version and exit",
    )
    listing = parents["listing"]
    listing.add_argument("-s", "--sort", metavar="SORT", help=LISTING_HELP["sort"])
    listing.add_argument(
        "-d", "--date-format", metavar="FORMAT", help=LISTING_HELP["date"]
    )
    listing.add_argument(
        "-u", "--author-format", metavar="FORMAT", help=LISTING_HELP["author"]
    )
    parents["wt_path"].add_argument(
        "-p",
        "--wt-path-display",
        metavar="MODE",
        choices=WT_PATH_MODES,
        help=(
            "how worktree paths are displayed, see below "
            f"(env: {ENV_WT_PATH_DISPLAY}, default: tilde)"
        ),
    )
    # Both forms, so the command line overrides the setting either way
    parents["subdir"].add_argument(
        "-k",
        "--keep-subdir",
        dest="keep_subdir",
        action="store_const",
        const="true",
        help=KEEP_SUBDIR_HELP,
    )
    parents["subdir"].add_argument(
        "--no-keep-subdir",
        dest="keep_subdir",
        action="store_const",
        const="false",
        help="land in the worktree root",
    )
    parents["scope"].add_argument(
        "-r",
        "--remotes",
        action="store_true",
        help="list remote branches only (default: local only)",
    )
    parents["scope"].add_argument(
        "-a", "--all", action="store_true", help="list both local and remote branches"
    )
    parents["force"].add_argument(
        "-f",
        "--force",
        action="store_true",
        help="skip the confirmation prompt before deleting branches or worktrees",
    )
    parents["confirm"].add_argument(
        "-c",
        "--confirm",
        action="store_true",
        help=(
            "skip the path prompt when adding a worktree: the path is "
            "<base-path>/<branch-name>; the verbose key (ctrl-v) asks anyway"
        ),
    )
    parents["query"].add_argument(
        "query",
        nargs="*",
        metavar="QUERY",
        help="initial fzf query; words are joined with spaces",
    )
    return parents


PICKER_TITLES = {
    "worktree manage": "Manage Git Worktrees",
    "worktree add": "Add a Git Worktree",
    "worktree total": "Manage Git Worktrees (total)",
}
PICKER_ACTIONS = {
    "branch manage": ("del", "extended-del", "info", "fork"),
    "worktree manage": ("del", "extended-del", "info"),
    "worktree add": tuple(PICKER_KEYS),
    "worktree total": tuple(PICKER_KEYS),
}
# Command path -> (summary, option groups); the order is the help's order
COMMAND_TABLE = {
    "branch": ("Manage branches in a Git repository", ()),
    "branch list": ("List branches in a Git repository and exit", ("listing", "scope")),
    "branch manage": (
        "Switch to existing branches in the Git repository or delete them",
        ("listing", "scope", "force", "query"),
    ),
    "worktree": ("Manage worktrees in a Git repository (bare and regular)", ()),
    "worktree list": (
        "List all worktrees in a Git repository and exit",
        ("listing", "wt_path"),
    ),
    "worktree manage": (
        "Switch to existing worktrees in the Git repository or delete them",
        ("listing", "wt_path", "subdir", "force", "query"),
    ),
    "worktree add": (
        "Add a new worktree based on a selected Git branch",
        ("listing", "wt_path", "subdir", "scope", "confirm", "force", "query"),
    ),
    "worktree total": (
        "Full worktree control: add a new one, switch to or delete worktrees, "
        "optionally with their branches",
        ("listing", "wt_path", "subdir", "scope", "confirm", "force", "query"),
    ),
    "config": (
        "Show the settings in effect, where each one comes from, and what they "
        "resolve to in this repository",
        ("listing", "wt_path", "subdir"),
    ),
    "init": ("Print the shell integration (the fgb function) for a shell", ()),
    "completion": ("Print the completion script for a shell", ()),
}


def command_epilog(path: str) -> str | None:
    parts = []
    if path in PICKER_ACTIONS:
        parts.append(picker_epilog(PICKER_ACTIONS[path]))
    if path.startswith("worktree "):
        parts.append(WT_PATH_EPILOG)
    if path == "init":
        parts.append(INIT_EPILOG)
    if path == "config":
        parts.append(CONFIG_COMMAND_EPILOG)
    return "\n\n".join(parts) or None


def build_parser(
    prog: str = PROG, color: bool = True
) -> tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser]]:
    """Return the main parser and the parsers of each command path; `color`
    lets argparse (3.14+) color help and usage errors, which the command
    parsers inherit."""
    parents = option_parents()
    colors: dict[str, Any] = {"color": color} if sys.version_info >= (3, 14) else {}
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            f"{PROG_NAME} {__version__}\n"
            "Manage Git branches and worktrees (bare and regular) with fzf."
        ),
        epilog=CONFIG_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
        **colors,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{PROG_NAME} {__version__}",
        help="show the version and exit",
    )
    parser.add_argument("-C", "--color", choices=COLOR_MODES, help=COLOR_HELP)
    parser.add_argument("--config", metavar="FILE", help=CONFIG_HELP)
    parser.add_argument("--show-config", action="store_true", help=SHOW_CONFIG_HELP)
    parser.add_argument("--cwd-file", metavar="FILE", help=argparse.SUPPRESS)
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    groups = {"": commands}
    leaves: dict[str, argparse.ArgumentParser] = {}
    for path, (summary, options) in COMMAND_TABLE.items():
        group, _, name = path.rpartition(" ")
        leaves[path] = groups[group].add_parser(
            name,
            parents=[parents["common"], *(parents[option] for option in options)],
            allow_abbrev=False,
            help=summary,
            description=f"{PROG_NAME} {__version__}\n{summary}.",
            epilog=command_epilog(path),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        if path in SUBCOMMANDS:
            groups[path] = leaves[path].add_subparsers(
                dest="subcommand", metavar="SUBCOMMAND", required=True
            )
    leaves["init"].add_argument(
        "shell", metavar="SHELL", choices=INIT_SHELLS, help=", ".join(INIT_SHELLS)
    )
    leaves["completion"].add_argument(
        "shell",
        metavar="SHELL",
        choices=COMPLETION_SHELLS,
        help=", ".join(COMPLETION_SHELLS),
    )
    commands.add_parser("version", help="show the version and exit")
    commands.add_parser("help", help="show this help and exit")
    # Hidden: fzf's preview command
    preview = commands.add_parser(
        "_preview", parents=[parents["common"]], allow_abbrev=False
    )
    preview.add_argument("row")
    leaves["_preview"] = preview
    return parser, leaves


def reject_short_equals(argv: Sequence[str]) -> None:
    """Reject `-s=value`: under GNU rules only long options take `=`."""
    take_value = False
    for arg in argv:
        if arg == "--":
            return
        if take_value:
            take_value = False
            continue
        if arg in LONG_VALUE_OPTS:
            take_value = True
            continue
        if not arg.startswith("-") or arg.startswith("--") or arg == "-":
            continue
        chars = arg[1:]
        for i, char in enumerate(chars):
            if char in SHORT_VALUE_OPTS:
                rest = chars[i + 1 :]
                if rest.startswith("="):
                    raise AppError(
                        f"'-{char}=...' is not supported; use '-{char} VALUE', "
                        f"'-{char}VALUE' or the long form with '='"
                    )
                take_value = not rest
                break


def attach_values(argv: Sequence[str]) -> list[str]:
    """Attach separate option values to their options, as getopt reads them.

    argparse refuses a value that starts with `-` (`-s -committerdate`), so
    `-s VALUE` becomes `-sVALUE` and `--sort VALUE` becomes `--sort=VALUE`.
    """
    result: list[str] = []
    args = list(argv)
    i = 0
    while i < len(args):
        arg = args[i]
        i += 1
        if arg == "--":
            result += args[i - 1 :]
            break
        has_next = i < len(args)
        if arg in LONG_VALUE_OPTS and has_next:
            result.append(f"{arg}={args[i]}")
            i += 1
            continue
        if arg.startswith("-") and not arg.startswith("--") and len(arg) > 1:
            chars = arg[1:]
            for j, char in enumerate(chars):
                if char in SHORT_VALUE_OPTS:
                    if j == len(chars) - 1 and has_next:
                        arg += args[i]
                        i += 1
                    break
        result.append(arg)
    return result


def command_path(argv: Sequence[str]) -> tuple[int | None, str]:
    """Index of the command and the command path ("worktree add"), skipping
    the global options that may come before the command."""
    value = False
    for index, arg in enumerate(argv):
        if value:
            value = False
        elif arg in GLOBAL_VALUE_OPTS:
            value = True
        elif arg == "--":
            return None, ""
        elif not arg.startswith("-"):
            path = arg
            if arg in ("branch", "worktree"):
                for sub in argv[index + 1 :]:
                    if not sub.startswith("-"):
                        path = f"{arg} {sub}"
                        break
            return index, path
    return None, ""


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def config_value(raw: str) -> str:
    """The value part of a config line: a comment starts with `#` at the
    beginning or after whitespace; one pair of matching quotes is removed."""
    value = re.sub(r"(^|\s)#.*", "", raw).strip()
    if len(value) > 1 and value[0] in "\"'" and value.endswith(value[0]):
        value = value[1:-1]
    return value


def load_config(
    path: Path,
    explicit: bool,
    lines: dict[str, int] | None = None,
    quiet: bool = False,
) -> dict[str, str]:
    """Read KEY=VALUE lines as data (never executed); `lines` receives the
    line number of each key; `quiet` skips the warnings about bad lines."""
    if not path.is_file():
        if explicit:
            raise AppError(f"config file not found: {path}")
        return {}
    config: dict[str, str] = {}
    for number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ")
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep:
            if not quiet:
                warn(f"{path}:{number}: ignoring invalid line")
            continue
        if key not in CONFIG_KEYS:
            if not quiet:
                warn(f"{path}:{number}: ignoring unknown key '{key}'")
            continue
        config[key] = config_value(value)
        if lines is not None:
            lines[key] = number
    return config


def resolve(
    cli: str | None, env_name: str, config: dict[str, str], default: str = ""
) -> str:
    """Precedence: command line > environment > config file > default."""
    for value in (cli, os.environ.get(env_name), config.get(env_name)):
        if value:
            return value
    return default


def choice(
    cli: str | None, env_name: str, config: dict[str, str], values: Sequence[str]
) -> str:
    value = resolve(cli, env_name, config, values[0])
    if value not in values:
        raise AppError(f"{env_name} must be one of: {', '.join(values)}")
    return value


def flag(cli: str | None, env_name: str, config: dict[str, str]) -> bool:
    """A boolean setting, with resolve()'s precedence."""
    value = resolve(cli, env_name, config, "false")
    if value.lower() not in BOOLEAN_VALUES:
        raise AppError(f"{env_name} must be {BOOLEAN_HELP}")
    return BOOLEAN_VALUES[value.lower()]


def config_path(cli: str | None) -> tuple[Path, bool]:
    if cli:
        return Path(cli).expanduser(), True
    env = os.environ.get(ENV_CONFIG)
    if env:
        return Path(env).expanduser(), True
    return Path.home() / ".config" / "fgbrc", False


@dataclasses.dataclass
class Settings:
    sort_order: str = DEFAULT_SORT_ORDER
    date_format: str = DEFAULT_DATE_FORMAT
    author_format: str = DEFAULT_AUTHOR_FORMAT
    wt_path_display: str = WT_PATH_MODES[0]
    wt_base_bare: str = DEFAULT_WT_BASE_PATH
    wt_base_regular: str = DEFAULT_WT_BASE_PATH
    keys: dict[str, str] = dataclasses.field(
        default_factory=lambda: {
            action: key for action, (_, key) in PICKER_KEYS.items()
        }
    )
    fzf_opts: str = ""
    keep_subdir: bool = False
    force: bool = False
    confirmed: bool = False
    branch_type: str = "local"


def settings_from(args: argparse.Namespace, config: dict[str, str]) -> Settings:
    remotes = getattr(args, "remotes", False)
    everything = getattr(args, "all", False)
    return Settings(
        sort_order=resolve(
            getattr(args, "sort", None), ENV_SORT_ORDER, config, DEFAULT_SORT_ORDER
        ),
        date_format=resolve(
            getattr(args, "date_format", None),
            ENV_DATE_FORMAT,
            config,
            DEFAULT_DATE_FORMAT,
        ),
        author_format=resolve(
            getattr(args, "author_format", None),
            ENV_AUTHOR_FORMAT,
            config,
            DEFAULT_AUTHOR_FORMAT,
        ),
        wt_path_display=choice(
            getattr(args, "wt_path_display", None),
            ENV_WT_PATH_DISPLAY,
            config,
            WT_PATH_MODES,
        ),
        wt_base_bare=resolve(None, ENV_WT_BASE_PATH_BARE, config, DEFAULT_WT_BASE_PATH),
        wt_base_regular=resolve(
            None, ENV_WT_BASE_PATH_REGULAR, config, DEFAULT_WT_BASE_PATH
        ),
        keys={
            action: resolve(None, setting, config, default)
            for action, (setting, default) in PICKER_KEYS.items()
        },
        fzf_opts=resolve(None, ENV_FZF_OPTS, config),
        keep_subdir=flag(getattr(args, "keep_subdir", None), ENV_KEEP_SUBDIR, config),
        force=getattr(args, "force", False),
        confirmed=getattr(args, "confirm", False),
        branch_type="all" if everything else "remote" if remotes else "local",
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def colors_on() -> bool:
    """Whether to build colored text at all; emit() strips it again for a
    stream that is not to be colored."""
    if COLOR.mode == "auto":
        return not os.environ.get("NO_COLOR")
    return COLOR.mode == "always"


def paint(text: str, color: str) -> str:
    return f"{color}{text}{COLOR_RESET}" if colors_on() and text and color else text


def emit(text: str = "", stream: TextIO | None = None, end: str = "\n") -> None:
    """Print to stdout, or to `stream`; without colors unless --color is
    always, or auto and the stream is a terminal."""
    stream = stream or sys.stdout
    if not (COLOR.mode == "always" or (colors_on() and stream.isatty())):
        text = ANSI_ESCAPE.sub("", text)
    print(text, end=end, file=stream, flush=True)


def warn(text: str) -> None:
    emit(f"{paint('Warning:', COLOR_YELLOW_BOLD)} {text}", sys.stderr)


def report(text: str) -> None:
    emit(f"{paint('Error:', COLOR_RED_BOLD)} {text}", sys.stderr)


def terminal_width() -> int:
    """Columns of the terminal, as `tput cols` reports them."""
    columns = os.environ.get("COLUMNS", "")
    if columns.isdigit() and int(columns) > 0:
        return int(columns)
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        try:
            return os.get_terminal_size(stream.fileno()).columns
        except (OSError, ValueError, AttributeError):
            continue
    try:
        fd = os.open("/dev/tty", os.O_RDONLY)
    except OSError:
        return 80
    try:
        return os.get_terminal_size(fd).columns
    except OSError:
        return 80
    finally:
        os.close(fd)


def stdin_is_tty() -> bool:
    try:
        return os.isatty(sys.stdin.fileno())
    except (OSError, ValueError, AttributeError):
        return False


def confirm(prompt: str) -> bool:
    """Ask a yes/no question answered by a single key: y is yes, anything
    else (Enter included) is no."""
    emit(f"{prompt} (y|N): ", end="")
    if stdin_is_tty():
        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            answer = os.read(fd, 1).decode(errors="replace")
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    else:
        answer = sys.stdin.read(1)
    emit()
    return answer in {"y", "Y"}


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def normalize_path(path: str) -> str:
    """Collapse "." and ".." segments lexically, without touching the disk."""
    absolute = path.startswith("/")
    parts: list[str] = []
    for segment in path.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if parts and parts[-1] != "..":
                parts.pop()
            elif not absolute:
                parts.append("..")
            continue
        parts.append(segment)
    joined = "/".join(parts)
    if absolute:
        return f"/{joined}"
    return joined or "."


def expand_env(template: str) -> str:
    """Expand $VAR and ${VAR} without evaluating anything. Names that are
    not plain identifiers expand to nothing."""
    out: list[str] = []
    rest = template
    while "$" in rest:
        before, _, rest = rest.partition("$")
        out.append(before)
        if rest.startswith("{") and "}" in rest:
            name, _, rest = rest[1:].partition("}")
        else:
            match = re.match(r"[A-Za-z0-9_]*", rest)
            name = match.group(0) if match else ""
            rest = rest[len(name) :]
        if not name:
            out.append("$")
            continue
        if IDENTIFIER.fullmatch(name):
            out.append(os.environ.get(name, ""))
    out.append(rest)
    return "".join(out)


def tilde_path(path: str) -> str:
    """Replace a leading $HOME with "~" on a path-component boundary."""
    home = os.environ.get("HOME", "").rstrip("/")
    if not home:
        return path
    if path == home:
        return "~"
    if path.startswith(f"{home}/"):
        return f"~{path[len(home) :]}"
    return path


def render_relative(rel: str) -> str:
    """ "./" prefix for descendants; a trailing slash on parent-only paths."""
    if rel == ".":
        return "./"
    if rel == ".." or rel.startswith("../"):
        return rel if set(rel) - {".", "/"} else f"{rel}/"
    return f"./{rel}"


def render_home(rel: str) -> str:
    """A path relative to $HOME, shown with a "~/" prefix."""
    if rel == ".":
        return "~/"
    if rel == ".." or rel.startswith("../"):
        return rel
    return f"~/{rel}"


def canonical_path(path: str) -> str:
    """Like realpath: symlinks in the existing part resolved (macOS /var is
    /private/var), the part that does not exist yet normalized lexically."""
    return os.path.realpath(normalize_path(os.path.join(os.getcwd(), path)))


def relative_path(base: str, target: str) -> str:
    return os.path.relpath(canonical_path(target), canonical_path(base))


def expand_user_path(path: str, base: str) -> str:
    """`~`, `~/x` and absolute paths as given; others relative to `base`."""
    home = os.environ.get("HOME", "")
    if path == "~":
        return home
    if path.startswith("~/"):
        return f"{home}/{path[2:]}"
    if path.startswith("/"):
        return path
    return f"{base}/{path}"


# ---------------------------------------------------------------------------
# git and fzf
# ---------------------------------------------------------------------------


def git(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run git, capturing its output."""
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def git_out(*args: str, cwd: str | None = None) -> str:
    """git's stdout without the trailing newline, or "" when it failed."""
    result = git(*args, cwd=cwd)
    return result.stdout.rstrip("\n") if result.returncode == 0 else ""


def git_show(*args: str, cwd: str | None = None) -> int:
    """Run git with its output going straight to the terminal."""
    sys.stdout.flush()
    return subprocess.run(["git", *args], cwd=cwd, check=False).returncode


def combined(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stdout + result.stderr).rstrip("\n")


def colored_status(path: str, *extra: str) -> str:
    return git_out("-C", path, "-c", "color.status=always", "status", "--short", *extra)


def fzf_version() -> tuple[int, ...]:
    fzf = shutil.which("fzf")
    if fzf is None:
        raise AppError("fzf not found; install it from https://github.com/junegunn/fzf")
    output = subprocess.run(
        [fzf, "--version"], capture_output=True, text=True, check=False
    ).stdout
    match = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", output.strip())
    if not match:
        raise AppError(f"cannot read the fzf version from: {output.strip()!r}")
    version = tuple(int(part or 0) for part in match.groups())
    if version < FZF_MIN_VERSION:
        wanted = ".".join(map(str, FZF_MIN_VERSION))
        raise AppError(f"fzf {wanted} or newer is required (found {output.strip()})")
    return version


def script_path() -> str:
    return os.path.realpath(__file__)


def preview_command() -> str:
    """fzf's preview: this program itself, quoted for sh."""
    command = [sys.executable, script_path()]
    if COLOR.mode == "never":
        command += ["--color=never"]
    return f"{shlex.join([*command, '_preview'])} {{1}}"


def default_fzf_args() -> list[str]:
    return [
        "--ansi",
        "--bind=ctrl-y:accept,ctrl-t:toggle+down",
        "--border=top",
        "--cycle",
        "--multi",
        "--pointer=",
        "--preview",
        preview_command(),
    ]


def bind_keys(args: Sequence[str]) -> str:
    """The --bind values in fzf arguments, for the picker header."""
    values: list[str] = []
    for i, arg in enumerate(args):
        if arg.startswith("--bind="):
            values.append(arg.removeprefix("--bind="))
        elif arg == "--bind" and i + 1 < len(args):
            values.append(args[i + 1])
    return ", ".join(",".join(values).split(",")) if values else ""


def parse_row(token: str) -> tuple[str, str]:
    """(kind, name) of a picker row's first field such as "[main]"."""
    inner = token[1:-1]
    if len(token) > 1:
        if token[0] == "(" and token[-1] == ")" and "/" in inner:
            return "remote", inner
        if token[0] == "[" and token[-1] == "]":
            return "local", inner
        if token[0] == "{" and token[-1] == "}":
            return "detached", inner
    raise AppError(f"invalid branch name pattern: {token}")


def token_for(kind: str, name: str) -> str:
    opening, closing = BRACKETS[kind]
    return f"{opening}{name}{closing}"


def git_log_format(fmt: str, commit: str) -> str:
    """Render a git for-each-ref format string for a commit (detached
    worktrees have no ref for for-each-ref to format)."""
    pieces: list[str] = []
    position = 0
    for match in DATE_ATOM.finditer(fmt):
        pieces.append(fmt[position : match.start()])
        placeholder = "%ad" if match.group(1) == "authordate" else "%cd"
        pieces.append(
            git_out(
                "log",
                "-1",
                f"--format={placeholder}",
                f"--date={match.group(2) or 'default'}",
                commit,
                "--",
            )
        )
        position = match.end()
    pieces.append(fmt[position:])
    text = "".join(pieces)
    for atom, placeholder in NAME_ATOMS.items():
        if atom in text:
            text = text.replace(
                atom, git_out("log", "-1", f"--format={placeholder}", commit, "--")
            )
    return text


def wrap_format(fmt: str) -> str:
    """Enclose a git format string in %( ... ) unless it already has atoms."""
    if re.search(r"%\([^)]*[a-zA-Z0-9_]+[^)]*\)", fmt):
        return fmt
    return f"%({fmt})"


@dataclasses.dataclass
class Row:
    ref: str
    author: str
    date: str

    @property
    def kind(self) -> str:
        if self.ref.startswith("refs/remotes/"):
            return "remote"
        if self.ref.startswith(DETACHED_PREFIX):
            return "detached"
        return "local"

    @property
    def name(self) -> str:
        """The ref without its first two segments ("origin/x" for remotes)."""
        return re.sub(r"^(?:[^/]*/){0,2}", "", self.ref)


# ---------------------------------------------------------------------------
# The application
# ---------------------------------------------------------------------------


class Fgb:
    """State of one run, as the shell function kept it in c_* variables."""

    def __init__(self, settings: Settings, cwd_file: str | None) -> None:
        self.settings = settings
        self.cwd_file = cwd_file
        self.start_dir = os.getcwd()
        self.new_cwd = ""
        # The worktree changed to, without the subdirectory kept in it
        self.new_wt = ""
        self.subdir = current_subdir() if settings.keep_subdir else ""
        self.width = terminal_width()
        self.date_format = wrap_format(settings.date_format)
        self.author_format = wrap_format(settings.author_format)
        self.rows: list[Row] = []
        self.branch_width = len(COLUMN_BRANCH)
        self.author_width = len(COLUMN_AUTHOR)
        self.date_width = len(COLUMN_DATE)
        self.wt_path_width = 0
        self.spacer = 1
        self.show_author = True
        self.show_date = True
        self.show_wt_path = True
        self.show_wt_flag = False
        self.extend_del = False
        self.confirmed = settings.confirmed
        # Worktree state
        self.is_bare = False
        self.common_dir = ""
        self.root = ""
        self.wt_base = ""
        self.wt_refs: list[str] = []
        self.wt_paths: dict[str, str] = {}
        self.remote_wt: dict[str, tuple[str, str]] = {}
        self.fzf_ver: tuple[int, ...] = ()
        self.last_add_error = ""
        self.query = ""

    # -- directory changes -------------------------------------------------

    def change_dir(self, path: str) -> None:
        self.new_cwd = path

    def enter_worktree(self, path: str) -> str:
        """Change to the worktree at `path`; with --keep-subdir to the current
        subdirectory in it, or its nearest parent that exists there. Returns
        the subdirectory entered, "" for the root."""
        self.new_wt = path
        parts = self.subdir.split("/") if self.subdir else []
        kept = len(parts)
        while kept and not os.path.isdir(os.path.join(path, *parts[:kept])):
            kept -= 1
        subdir = "/".join(parts[:kept])
        if kept < len(parts):
            missing = paint(self.subdir, COLOR_RED)
            instead = (
                f"'{paint(subdir, COLOR_YELLOW)}'" if subdir else "the worktree root"
            )
            warn(f"'{missing}' does not exist in this worktree; using {instead}")
        self.change_dir(os.path.join(path, subdir) if subdir else path)
        return subdir

    def finish(self) -> None:
        """Hand the new directory to the shell wrapper, or print a hint."""
        if not self.new_cwd:
            return
        if self.cwd_file:
            Path(self.cwd_file).write_text(self.new_cwd, encoding="utf-8")
        elif os.path.realpath(self.new_cwd) != os.path.realpath(self.start_dir):
            emit(
                f"cd {shlex.quote(self.new_cwd)}  "
                f"# run it, or use the shell integration: {PROG_NAME} init --help",
                sys.stderr,
            )

    # -- branch data -------------------------------------------------------

    def git_branch_list(
        self, branch_type: str, keep: set[str] | None = None
    ) -> list[Row]:
        ref_types = {
            "local": ["heads"],
            "remote": ["remotes"],
            "all": ["heads", "remotes"],
        }[branch_type]
        fmt = f"%(refname){US}{self.author_format}{US}{self.date_format}"
        command = ["for-each-ref", f"--format={fmt}"]
        command += [
            f"--sort={key}" for key in self.settings.sort_order.split(",") if key
        ]
        rows: list[Row] = []
        for ref_type in ref_types:
            result = git(*command, f"refs/{ref_type}")
            if result.returncode != 0:
                raise AppError(result.stderr.strip(), result.returncode)
            for line in result.stdout.splitlines():
                # The author is everything between the first and last field
                ref, _, rest = line.partition(US)
                author, _, date = rest.rpartition(US)
                if not ref:
                    continue
                # <remote>/HEAD is a symbolic ref pointing at another branch;
                # selecting it would create a detached worktree
                if re.fullmatch(r"refs/remotes/[^/]+/HEAD", ref):
                    continue
                if keep is not None and ref not in keep:
                    continue
                rows.append(Row(ref, author, date))
        return rows

    def set_widths(self, rows: Sequence[Row]) -> None:
        for row in rows:
            self.date_width = max(self.date_width, len(row.date))
            self.branch_width = max(self.branch_width, len(row.name))
            if len(row.author) > AUTHOR_TRIM_WIDTH and "/" in row.author:
                row.author = f".../{row.author.split('/', 1)[1]}"
            self.author_width = max(self.author_width, len(row.author))

    def set_spacer(self, list_type: str) -> None:
        def spacer(total: int, count: int) -> int:
            value = round((self.width - total) / count)
            return 1 if value <= 0 else min(value, MAX_SPACER)

        if list_type == "branch":
            total = self.branch_width + self.author_width + self.date_width + 5
            if total > self.width:
                self.show_author = False
                total -= self.author_width
            if total > self.width:
                self.show_date = False
                total -= self.date_width
            self.spacer = spacer(total, 2)
            return
        total = (
            self.branch_width
            + self.wt_path_width
            + self.author_width
            + self.date_width
            + 5
        )
        if total > self.width:
            self.show_wt_path = False
            self.show_wt_flag = True
            total = total - self.wt_path_width + 1
        if total > self.width:
            self.show_author = False
            total -= self.author_width
        if total > self.width:
            self.show_date = False
            total -= self.date_width
        count = 3
        if self.show_wt_flag:
            count += 1
            total += 2
        self.spacer = spacer(total, count)

    # -- rendering ---------------------------------------------------------

    def branch_cell(self, row: Row) -> str:
        opening, closing = BRACKETS[row.kind]
        padding = " " * max(self.branch_width - len(row.name), 0)
        return f"{opening}{paint(row.name, COLOR_YELLOW_BOLD)}{closing}{padding}"

    def tail_cells(self, row: Row) -> str:
        gap = " " * self.spacer
        text = ""
        if self.show_author:
            text += gap + paint(row.author.ljust(self.author_width), COLOR_GREEN)
        if self.show_date:
            text += f"{gap}({paint(row.date, COLOR_BLUE)})"
        return text

    def branch_lines(self) -> list[str]:
        return [self.branch_cell(row) + self.tail_cells(row) for row in self.rows]

    def row_worktree(self, row: Row) -> str:
        path = self.wt_paths.get(row.ref, "")
        if not path and row.kind == "remote":
            path = self.remote_wt.get(row.ref, ("", ""))[0]
        return path

    def worktree_lines(self) -> list[str]:
        self.set_spacer("worktree")
        gap = " " * self.spacer
        lines = []
        for row in self.rows:
            text = self.branch_cell(row)
            path = self.row_worktree(row)
            if self.show_wt_path:
                shown = self.format_wt_path(path) if path else " "
                text += gap + paint(shown.ljust(self.wt_path_width), COLOR_BOLD)
            if self.show_wt_flag:
                text += gap + paint("+" if path else " ", COLOR_BOLD)
            lines.append(text + self.tail_cells(row))
        return lines

    def column_row(self, wt_column: bool) -> str:
        def pad(width: int) -> str:
            return " " * max(abs(width), 1)

        text = COLUMN_BRANCH + pad(
            self.branch_width + 2 - len(COLUMN_BRANCH) + self.spacer
        )
        if wt_column and self.show_wt_path:
            text += "WT" + pad(self.wt_path_width - 2 + self.spacer)
        elif wt_column and self.show_wt_flag:
            text += "W" + pad(1 - 1 + self.spacer)
        if self.show_author:
            text += COLUMN_AUTHOR + pad(
                self.author_width - len(COLUMN_AUTHOR) + self.spacer
            )
        if self.show_date:
            text += COLUMN_DATE
        return text

    def format_wt_path(self, path: str) -> str:
        """A worktree path as the display mode shows it; absolute on failure."""
        bases: dict[str, Callable[[], str]] = {
            "relative-cwd": os.getcwd,
            "relative-wt-base": lambda: self.wt_base,
            "relative-gitdir": lambda: self.common_dir,
            "relative-repo": lambda: self.root,
        }
        mode = self.settings.wt_path_display
        try:
            if mode in bases:
                return render_relative(relative_path(bases[mode](), path))
            if mode == "relative-home":
                return render_home(relative_path(os.environ.get("HOME", "/"), path))
        except (OSError, ValueError):
            return path
        if mode in {"absolute", "absolute-gitdir"}:
            # A path under the git common dir re-joins to itself
            return path
        return tilde_path(path)

    # -- fzf ---------------------------------------------------------------

    def fzf_args(self) -> tuple[list[str], dict[str, str] | None]:
        """fzf's options and environment. With the built-in options, fzf runs
        its commands with sh, whatever the user's $SHELL is."""
        if self.settings.fzf_opts:
            return shlex.split(self.settings.fzf_opts), None
        return default_fzf_args(), {**os.environ, "SHELL": "/bin/sh"}

    def pick(
        self,
        lines: Sequence[str],
        title: str,
        actions: Sequence[str],
        columns: str,
    ) -> tuple[str, list[str]] | None:
        """Show the picker; return (action, chosen row tokens) or None.

        The action is one of `actions`, or "" for Enter.
        """
        self.fzf_ver = self.fzf_ver or fzf_version()
        args, env = self.fzf_args()
        keys = [self.settings.keys[action] for action in actions]
        header = f"{title}: " + ", ".join(
            f"{key}:{action}" for key, action in zip(keys, actions, strict=True)
        )
        binds = bind_keys(args)
        if binds:
            header += f", {binds}"
        command = [
            "fzf",
            "--height",
            "80%",
            "--reverse",
            *(["--no-color"] if COLOR.mode == "never" else []),
            *args,
            f"--expect={','.join(keys)}",
            "--header",
            f"{header}\n{columns}",
        ]
        if self.query:
            command.append(f"--query={self.query}")
        result = subprocess.run(
            command,
            input="".join(f"{line}\n" for line in lines),
            stdout=subprocess.PIPE,
            text=True,
            env=env,
            check=False,
        )
        output = ANSI_ESCAPE.sub("", result.stdout).rstrip("\n").split("\n")
        key, selected = output[0], [line for line in output[1:] if line]
        if not selected:
            return None
        action = dict(zip(keys, actions, strict=True)).get(key, "")
        return action, [line.split(" ", 1)[0] for line in selected]

    def prompt_text(self, message: str, initial: str) -> str | None:
        """Edit a line that starts as `initial`; None when cancelled.

        fzf serves as the line editor (an empty list, Enter prints the
        query): it can pre-fill text, which input() cannot.
        """
        self.fzf_ver = self.fzf_ver or fzf_version()
        command = [
            "fzf",
            "--height=3",
            "--reverse",
            "--disabled",
            "--info=hidden",
            f"--prompt={message} ",
            f"--query={initial}",
            "--bind=enter:print-query",
        ]
        if COLOR.mode == "never":
            command.append("--no-color")
        else:
            command.append("--color=query:red")
        if self.fzf_ver >= FZF_NO_SEPARATOR_VERSION:
            command.append("--no-separator")
        result = subprocess.run(
            command, input="", stdout=subprocess.PIPE, text=True, check=False
        )
        if result.returncode != 0:
            return None
        return result.stdout.rstrip("\n")

    # -- branch actions ----------------------------------------------------

    def delete_branches(self, tokens: Sequence[str]) -> int:
        code = 0
        for token in tokens:
            code = self.delete_branch(token) or code
        return code

    def tracking_branch(self, remote_ref: str) -> str:
        """The first local branch (in sort order) whose upstream is `remote_ref`."""
        command = ["for-each-ref", f"--format=%(refname){US}%(upstream)"]
        command += [
            f"--sort={key}" for key in self.settings.sort_order.split(",") if key
        ]
        for line in git_out(*command, "refs/heads").splitlines():
            ref, _, upstream = line.partition(US)
            if upstream == remote_ref:
                return ref
        return ""

    def delete_branch(self, token: str) -> int:
        kind, name = parse_row(token)
        if kind == "remote":
            return self.delete_remote_branch(name)
        if kind != "local":
            raise AppError(f"invalid branch name pattern: {token}")
        return self.delete_local_branch(name)

    def delete_remote_branch(self, name: str) -> int:
        remote, _, branch = name.partition("/")
        local_tracking = ""
        if self.extend_del:
            local_tracking = self.tracking_branch(f"refs/remotes/{name}")
        prompt = (
            f"{paint('WARNING:', COLOR_RED_BOLD)} Delete branch: "
            f"'{paint(branch, COLOR_BLUE_BOLD)}' from remote: "
            f"{paint(remote, COLOR_YELLOW_BOLD)}?"
        )
        # Never skipped by --force: deleting a remote branch is final
        if not confirm(prompt):
            return 0
        code = git_show("push", "--delete", remote, branch)
        if code != 0 or not local_tracking:
            return code
        local = token_for("local", local_tracking.removeprefix("refs/heads/"))
        return self.without_extend(lambda: self.delete_branch(local))

    def delete_local_branch(self, name: str) -> int:
        remote_tracking = ""
        if self.extend_del:
            remote_tracking = git_out(
                "for-each-ref", "--format=%(upstream)", f"refs/heads/{name}"
            )
        prompt = (
            f"{paint('Delete', COLOR_RED_BOLD)} local branch: "
            f"`{paint(name, COLOR_BLUE_BOLD)}'?"
        )
        if not (self.settings.force or confirm(prompt)):
            return 0
        code, deleted = self.git_delete_branch(name)
        if deleted and remote_tracking.startswith("refs/remotes/"):
            remote = token_for("remote", remote_tracking.removeprefix("refs/remotes/"))
            return self.without_extend(lambda: self.delete_branch(remote))
        return code

    def git_delete_branch(self, name: str) -> tuple[int, bool]:
        """`git branch -d`, offering -D for an unmerged branch; return the exit
        code and whether the branch is gone."""
        result = git("branch", "-d", name)
        if result.returncode == 0:
            emit(combined(result))
            return 0, True
        output = combined(result)
        pattern = rf"^error: the branch '{re.escape(name)}' is not fully merged\.?$"
        if not re.search(pattern, output, re.MULTILINE):
            emit(output, sys.stderr)
            return result.returncode, False
        head = git_out("rev-parse", "--abbrev-ref", "HEAD")
        prompt = (
            f"\n{paint('WARNING:', COLOR_RED_BOLD)} The branch "
            f"'{paint(name, COLOR_BLUE_BOLD)}' is not yet merged into the "
            f"'{paint(head, COLOR_GREEN_BOLD)}' branch.\n\n"
            "Are you sure you want to delete it?"
        )
        # Not skipped by --force: that is not meant for unmerged branches
        if not confirm(prompt):
            return 0, False
        code = git_show("branch", "-D", name)
        return code, code == 0

    def without_extend(self, action: Callable[[], int]) -> int:
        saved, self.extend_del = self.extend_del, False
        try:
            return action()
        finally:
            self.extend_del = saved

    def with_force(self, action: Callable[[], int]) -> int:
        saved, self.settings.force = self.settings.force, True
        try:
            return action()
        finally:
            self.settings.force = saved

    def print_branch_info(self, name: str) -> int:
        worktree = self.wt_paths.get(f"refs/heads/{name}", "")
        # A remote branch resolves to the worktree of a local branch tracking
        # it; that branch is named unless it is the remote one without prefix
        path, owner = self.remote_wt.get(f"refs/remotes/{name}", ("", ""))
        if not worktree and path:
            worktree = path
            if owner != name.split("/", 1)[-1]:
                worktree += f" ({owner})"

        def log(fmt: str, *extra: str) -> str:
            return git_out("log", "-1", f"--format={fmt}", *extra, name, "--")

        values = [
            ("branch", name, COLOR_YELLOW_BOLD),
            ("worktree", worktree, COLOR_BOLD),
            ("author", log("%an <%ae>"), COLOR_GREEN),
            ("authordate", log("%ad", "--date=iso"), COLOR_BLUE),
            ("committer", log("%cn <%ce>"), COLOR_GREEN),
            ("committerdate", log("%cd", "--date=iso"), COLOR_BLUE),
            ("HEAD", git_out("rev-parse", "--verify", name), COLOR_MAGENTA),
            ("message", log("%B").rstrip("\n"), COLOR_YELLOW),
        ]
        width = max(len(key) for key, _, _ in values)
        indent = " " * (width + 3)
        for key, value, color in values:
            if value:
                text = value.replace("\n", f"\n{indent}")
                emit(f"{key:<{width}} : {paint(text, color)}")
        return 0

    def new_branch(self, name: str, kind: str, for_worktree: bool) -> str | None:
        """Fork `name`; return the new branch's name, or None."""
        emit(f"Fork the branch `{paint(name, COLOR_BLUE_BOLD)}' and switch to it.")
        initial = name.split("/", 1)[1] if kind == "remote" else name
        new = self.prompt_text("Enter a name for the new branch:", f"{initial}-fork")
        if new is None:
            return None
        if not new:
            raise AppError("empty branch name, aborting")
        if git("check-ref-format", "--branch", new).returncode != 0:
            raise AppError(f"not a valid branch name: `{new}'")
        if for_worktree:
            code = git_show("branch", new, name)
        else:
            sys.stdout.flush()
            code = subprocess.run(
                ["git", "switch", "-c", new, name],
                stdout=subprocess.DEVNULL,
                check=False,
            ).returncode
        if code != 0:
            raise AppError(f"cannot create the branch '{new}'", code)
        return new

    # -- worktree actions --------------------------------------------------

    def delete_worktrees(self, tokens: Sequence[str]) -> int:
        code = 0
        for token in tokens:
            code = self.delete_worktree(token) or code
        return code

    def delete_worktree(self, token: str) -> int:
        kind, name = parse_row(token)
        path = ""
        if kind == "local":
            path = self.wt_paths.get(f"refs/heads/{name}", "")
        elif kind == "detached":
            path = self.wt_paths.get(f"{DETACHED_PREFIX}{name}", "")
        if not path:
            # A branch without a worktree: delete the branch itself
            return self.with_force(lambda: self.delete_branch(token))
        what = "detached HEAD" if kind == "detached" else "branch"
        prompt = (
            f"{paint('Delete', COLOR_RED_BOLD)} worktree: "
            f"{paint(path, COLOR_YELLOW_BOLD)}, for {what} "
            f"'{paint(name, COLOR_BLUE_BOLD)}'?"
        )
        if not (self.settings.force or confirm(prompt)):
            return 0
        done = (
            f"{paint('Deleted', COLOR_GREEN_BOLD)} worktree: "
            f"{paint(path, COLOR_YELLOW_BOLD)} for {what} "
            f"'{paint(name, COLOR_BLUE_BOLD)}'"
        )
        # git runs from the repository root, so the worktree being deleted may
        # be the current directory; the shell moves out only on success
        cwd = os.getcwd()
        inside = cwd == path or cwd.startswith(f"{path}/")
        code = self.remove_worktree(path)
        if code is not None:
            return code
        emit(done)
        if inside:
            os.chdir(self.root)
            self.change_dir(self.root)
        if kind == "detached":
            return 0
        prompt = (
            f"{paint('Delete', COLOR_RED_BOLD)} the corresponding "
            f"'{paint(name, COLOR_BLUE_BOLD)}' branch as well?"
        )
        if confirm(prompt):
            return self.with_force(lambda: self.delete_branch(token_for("local", name)))
        return 0

    def remove_worktree(self, path: str) -> int | None:
        """`git worktree remove`, offering --force for a dirty worktree; None
        when the worktree is gone, otherwise the exit code."""
        result = git("worktree", "remove", path, cwd=self.root)
        if result.returncode == 0:
            return None
        output = combined(result)
        pattern = (
            r"^fatal: .* contains modified or untracked files,"
            r" use --force to delete it$"
        )
        if not re.search(pattern, output, re.MULTILINE):
            emit(output, sys.stderr)
            return result.returncode
        prompt = (
            f"\n{paint('WARNING:', COLOR_RED_BOLD)} This will permanently "
            "reset/delete the following files:\n\n"
            f"{colored_status(path)}\n\n"
            f"in the {paint(path, COLOR_YELLOW_BOLD)} path.\n\n"
            "Are you sure you want to proceed?"
        )
        # Not skipped by --force: this cannot be undone
        if not confirm(prompt):
            return 0
        result = git("worktree", "remove", path, "--force", cwd=self.root)
        if result.returncode != 0:
            emit(combined(result), sys.stderr)
            return result.returncode
        return None

    def offer_reset_to_remote(
        self, remote_branch: str, branch: str, wt_path: str = ""
    ) -> None:
        """Offer to bring a stale local branch up to the remote branch picked.

        Selecting a remote branch lands on its local counterpart, which may be
        behind the remote. With `wt_path` the branch is checked out there, so
        the reset happens in that worktree and discards its changes, which are
        listed first.
        """
        if not remote_branch:
            return
        if git("show-ref", "--verify", "--quiet", f"refs/heads/{branch}").returncode:
            return
        counts = git(
            "rev-list",
            "--left-right",
            "--count",
            f"refs/heads/{branch}...refs/remotes/{remote_branch}",
        )
        try:
            ahead, behind = (int(part) for part in counts.stdout.split())
        except ValueError:
            return
        if counts.returncode != 0 or behind == 0:
            return
        prompt = reset_prompt(remote_branch, branch, wt_path, ahead, behind)
        if not confirm(prompt):
            return
        b_branch = paint(branch, COLOR_BLUE_BOLD)
        y_remote = paint(remote_branch, COLOR_YELLOW_BOLD)
        if wt_path:
            result = git(
                "-C", wt_path, "reset", "--hard", f"refs/remotes/{remote_branch}"
            )
            if result.stderr:
                emit(result.stderr.rstrip("\n"), sys.stderr)
            ok = result.returncode == 0
        else:
            ok = git_show("branch", "-f", branch, f"refs/remotes/{remote_branch}") == 0
        if ok:
            emit(f"Reset '{b_branch}' to '{y_remote}'")
        else:
            emit(f"could not reset '{branch}'", sys.stderr)

    def jump_or_add(self, token: str, quiet: bool = False) -> int:
        """Jump to the row's worktree, or add one; with `quiet`, a git error is
        kept in last_add_error instead of being printed."""
        kind, name = parse_row(token)
        if kind == "remote":
            branch = name.split("/", 1)[1]
            # `git worktree add <path> <branch>` resolves a name to the local
            # branch, so jump to its worktree when it already has one
            path, owner = self.remote_wt.get(f"refs/remotes/{name}", ("", ""))
            if path:
                # The worktree may be behind the remote branch that was picked
                self.offer_reset_to_remote(name, owner, path)
                return self.jump(path, branch, owner)
            return self.add_worktree(branch, name, quiet)
        prefix = DETACHED_PREFIX if kind == "detached" else "refs/heads/"
        path = self.wt_paths.get(f"{prefix}{name}", "")
        if path:
            return self.jump(path, name)
        return self.add_worktree(name, "", quiet)

    def jump(self, path: str, branch: str, owner: str = "") -> int:
        subdir = self.enter_worktree(path)
        note = ""
        if owner and owner != branch:
            note = f" (checked out as '{paint(owner, COLOR_BLUE_BOLD)}')"
        emit(
            f"{paint('Jumped', COLOR_GREEN_BOLD)} to worktree: "
            f"{paint(path, COLOR_YELLOW_BOLD)}{subdir_note(subdir)}, for branch "
            f"'{paint(branch, COLOR_BLUE_BOLD)}'{note}"
        )
        return 0

    def ask_worktree_path(self, branch: str, remote_branch: str) -> str | None:
        env_var = ENV_WT_BASE_PATH_BARE if self.is_bare else ENV_WT_BASE_PATH_REGULAR
        remote_note = ""
        if remote_branch:
            remote_note = (
                f" (remote branch: '{paint(remote_branch, COLOR_YELLOW_BOLD)}')"
            )
        emit(
            f"Add a new worktree for '{paint(branch, COLOR_BLUE_BOLD)}'"
            f"{remote_note}.\nEnter an absolute path or a path relative to: "
            f"{paint(tilde_path(self.wt_base), COLOR_YELLOW_BOLD)} ({env_var})"
        )
        answer = self.prompt_text("Enter the path:", branch)
        if answer is None:
            return None
        # Collapse "." and ".." as git does when it reports worktree paths
        return normalize_path(expand_user_path(answer, self.wt_base))

    def add_worktree(self, branch: str, remote_branch: str, quiet: bool) -> int:
        if self.confirmed:
            path: str | None = normalize_path(f"{self.wt_base}/{branch}")
        else:
            path = self.ask_worktree_path(branch, remote_branch)
        if path is None:
            self.last_add_error = "cancelled"
            return FZF_CANCELLED
        self.offer_reset_to_remote(remote_branch, branch)
        result = git("worktree", "add", path, branch)
        if result.returncode != 0:
            self.last_add_error = combined(result)
            if not quiet:
                emit(self.last_add_error, sys.stderr)
            return result.returncode
        subdir = self.enter_worktree(path)
        emit(
            f"Worktree {paint(path, COLOR_YELLOW_BOLD)} for branch "
            f"'{paint(branch, COLOR_BLUE_BOLD)}' added successfully.\n"
            f"{paint('Jumped', COLOR_GREEN_BOLD)} there{subdir_note(subdir)}."
        )
        return 0

    def restore_stash(self, stash: str, target: str, init_path: str) -> None:
        """Apply the stash in `target`; if that fails, put it back where it was
        taken from."""
        result = git("-C", target, "-c", "color.status=always", "stash", "apply", stash)
        if result.returncode == 0:
            emit(combined(result))
            drop_stash(stash, target)
            return
        if target == init_path:
            emit(
                f"\n{paint('ERROR:', COLOR_RED_BOLD)} Failed to restore stash to "
                f"the initial worktree: {paint(init_path, COLOR_YELLOW_BOLD)}\n"
                f"{combined(result)}\n"
                f"Your changes are still saved as: {paint(stash, COLOR_YELLOW_BOLD)}"
            )
            return
        emit(
            f"\n{paint('WARNING:', COLOR_RED_BOLD)} Failed to apply stash to the "
            "worktree created for the new branch.\nRestoring stashed changes to "
            f"the initial worktree.\n\n{paint('Stash apply output:', COLOR_GREEN)}"
            f"\n\n{combined(result)}"
        )
        git_show("-C", target, "reset", "--hard", "HEAD")
        git_show("-C", target, "clean", "-fd")
        if git("-C", init_path, "stash", "apply", stash).returncode == 0:
            drop_stash(stash, init_path)
        else:
            ref = stash_ref(stash, init_path) or stash
            emit(
                f"\n{paint('ERROR:', COLOR_RED_BOLD)} Failed to restore stash to "
                f"the initial worktree: {paint(init_path, COLOR_YELLOW_BOLD)}\n"
                f"Your changes are still saved as: {paint(ref, COLOR_YELLOW_BOLD)}\n"
                f"Recover with: git -C {paint(init_path, COLOR_YELLOW_BOLD)} "
                f"stash apply {ref}"
            )

    def worktree_for_new_branch(self, new: str) -> int:
        emit(f"Switched to a new branch '{new}'")
        token = token_for("local", new)
        stash = ""
        init_path = os.getcwd()
        if git_out("rev-parse", "--is-inside-work-tree") == "true" and (
            git("diff", "--quiet").returncode
            or git("diff", "--cached", "--quiet").returncode
        ):
            prompt = (
                f"\n{paint('INFO:', COLOR_YELLOW_BOLD)} The current worktree has "
                f"uncommitted changes:\n\n{colored_status(init_path, '-uno')}\n\n"
                "Do you want to try to stash and pop them in a new worktree?"
            )
            if confirm(prompt):
                stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                message = (
                    f"[{stamp}] Stash to restore in a new worktree for branch '{new}'"
                )
                if git_show("stash", "push", "-m", message) != 0:
                    raise AppError(
                        "failed to stash changes, aborting worktree creation"
                    )
                # The stash stack is shared by all worktrees: keep the commit,
                # not the stash@{n} position, which other pushes shift
                stash = git_out("rev-parse", "stash@{0}")
        code = self.jump_or_add(token, quiet=True)
        if code != 0:
            output = self.last_add_error
            match = re.search(r"^fatal: '(.+)' already exists$", output, re.MULTILINE)
            if match is None:
                if output != "cancelled":
                    emit(output, sys.stderr)
                self.delete_branch(token)
            else:
                prompt = (
                    f"\n{paint('WARNING:', COLOR_RED_BOLD)} The path "
                    f"'{paint(match.group(1), COLOR_YELLOW_BOLD)}' already exists."
                    "\n\nWould you like to enter another path?"
                )
                if confirm(prompt):
                    self.confirmed = False
                    code = self.jump_or_add(token)
                    if code != 0:
                        self.delete_branch(token)
                else:
                    self.delete_branch(token)
        if stash:
            self.restore_stash(stash, self.new_wt or init_path, init_path)
        return code

    # -- worktree state ----------------------------------------------------

    def load_worktrees(self) -> None:
        porcelain = git_out("worktree", "list", "--porcelain")
        records = porcelain.split("\n\n")
        first = records[0].split("\n")
        self.is_bare = "bare" in first[1:]
        common = git_out("rev-parse", "--git-common-dir")
        if not common:
            raise AppError("cannot determine the git common directory", EXIT_NO_REPO)
        common = os.path.join(os.getcwd(), common)
        if not os.path.isdir(common):
            raise AppError("cannot resolve the git common directory", EXIT_NO_REPO)
        # `pwd -P`: the spelling git itself uses in `worktree list` output
        self.common_dir = os.path.realpath(common)
        reported_main = first[0].removeprefix("worktree ")
        self.root = self.find_root(reported_main)
        self.wt_base = self.expand_base()
        for record in records:
            path, ref = parse_worktree_record(record)
            if not ref:
                continue
            # git reports the main worktree as the common dir without its
            # "/.git", which is not the working tree when that suffix is absent
            if path == reported_main:
                path = self.root
            self.wt_refs.append(ref)
            self.wt_paths[ref] = path
        for path in self.wt_paths.values():
            self.wt_path_width = max(self.wt_path_width, len(self.format_wt_path(path)))
        self.build_remote_wt_map()

    def find_root(self, reported_main: str) -> str:
        """The main worktree (the bare directory itself in a bare repo)."""
        if self.is_bare:
            return self.common_dir
        if self.common_dir.endswith("/.git"):
            return reported_main
        # A --separate-git-dir repo: git cannot always say where the working
        # tree is, so fall back to what it reported rather than invent a path
        core = git_out("config", "core.worktree")
        if core:
            core = os.path.join(self.common_dir, core)
            if os.path.isdir(core):
                return os.path.realpath(core)
        return git_out("rev-parse", "--show-toplevel") or reported_main

    def expand_base(self) -> str:
        repo_name = os.path.basename(self.root)
        repo_name_short = repo_name.removesuffix(".git")
        template = (
            self.settings.wt_base_bare
            if self.is_bare
            else self.settings.wt_base_regular
        )
        template = template.replace("{repo_name}", repo_name)
        template = template.replace("{repo_name_short}", repo_name_short)
        home = os.environ.get("HOME", "")
        if template == "~":
            template = home
        elif template.startswith("~/"):
            template = f"{home}/{template[2:]}"
        if "$" in template:
            template = expand_env(template)
        if not template.startswith("/"):
            template = f"{self.common_dir}/{template.removeprefix('./')}"
        # git resolves ".." when reporting worktree paths
        return normalize_path(template)

    def build_remote_wt_map(self) -> None:
        """Map each remote-tracking ref to (worktree, local branch) of a local
        branch tracking it that has a worktree. Among several, the one named
        like the remote branch wins, otherwise the alphabetically first."""
        for line in git_out(
            "for-each-ref", f"--format=%(refname){US}%(upstream)", "refs/heads"
        ).splitlines():
            local_ref, _, upstream = line.partition(US)
            if not upstream or local_ref not in self.wt_paths:
                continue
            local_name = local_ref.removeprefix("refs/heads/")
            want = upstream.removeprefix("refs/remotes/").split("/", 1)[-1]
            existing = self.remote_wt.get(upstream)
            if (
                existing
                and local_name != want
                and (existing[1] == want or existing[1] < local_name)
            ):
                continue
            self.remote_wt[upstream] = (self.wt_paths[local_ref], local_name)

    def detached_rows(self) -> list[Row]:
        """Rows for detached worktrees, newest-listed first as before."""
        rows: list[Row] = []
        for ref in self.wt_refs:
            if ref.startswith(DETACHED_PREFIX):
                commit = ref.removeprefix(DETACHED_PREFIX)
                rows.insert(
                    0,
                    Row(
                        ref,
                        git_log_format(self.author_format, commit),
                        git_log_format(self.date_format, commit),
                    ),
                )
        return rows

    # -- commands ----------------------------------------------------------

    def branch_list(self) -> int:
        self.rows = self.git_branch_list(self.settings.branch_type)
        self.set_widths(self.rows)
        self.set_spacer("branch")
        for line in self.branch_lines():
            emit(line)
        return 0

    def branch_manage(self) -> int:
        self.rows = self.git_branch_list(self.settings.branch_type)
        self.set_widths(self.rows)
        self.set_spacer("branch")
        picked = self.pick(
            self.branch_lines(),
            "Manage Git Branches",
            PICKER_ACTIONS["branch manage"],
            self.column_row(wt_column=False),
        )
        if picked is None:
            return 0
        action, tokens = picked
        kind, name = parse_row(tokens[-1])
        if action == "fork":
            self.new_branch(name, kind, for_worktree=False)
            return 0
        if action:
            return self.act(action, tokens, self.delete_branches)
        if git("rev-parse", "--show-toplevel").returncode != 0:
            raise AppError("Not inside a Git worktree", EXIT_NO_REPO)
        branch = name.split("/", 1)[1] if kind == "remote" else name
        return git_show("switch", branch)

    def act(
        self, action: str, tokens: Sequence[str], delete: Callable[[Sequence[str]], int]
    ) -> int:
        """Run a picker action on the chosen rows; Enter ("") jumps."""
        if action in ("del", "extended-del"):
            self.extend_del = action == "extended-del"
            return delete(tokens)
        token = tokens[-1]
        kind, name = parse_row(token)
        if action == "info":
            return self.print_branch_info(name)
        if action in ("verbose", "fork-verbose"):
            self.confirmed = False
        if action in ("fork", "fork-verbose"):
            new = self.new_branch(name, kind, for_worktree=True)
            return 0 if new is None else self.worktree_for_new_branch(new)
        return self.jump_or_add(token)

    def worktree_command(self, subcommand: str) -> int:
        superproject = git_out("rev-parse", "--show-superproject-working-tree")
        # Only an absolute answer counts: old gits echo the option back
        if superproject.startswith("/"):
            raise AppError(
                "this repository is a submodule of "
                f"{paint(superproject, COLOR_YELLOW_BOLD)}\n"
                "Worktrees are not supported for submodules - skipping.\n"
                "Clone the submodule as a standalone repository to use worktrees "
                "with it."
            )
        self.load_worktrees()
        branch_type = self.settings.branch_type
        keep = set(self.wt_refs) if subcommand in ("list", "manage") else None
        rows = self.git_branch_list(branch_type, keep)
        if branch_type in ("local", "all"):
            rows = self.detached_rows() + rows
        self.rows = rows
        self.set_widths(rows)
        if subcommand == "list":
            for line in self.worktree_lines():
                emit(line)
            return 0
        path = f"worktree {subcommand}"
        delete = self.delete_worktrees
        if subcommand == "add":
            # Branches that have a worktree are not offered, nor remote
            # branches whose local counterpart has one (selecting them jumps)
            self.rows = [
                row
                for row in self.rows
                if row.ref not in self.wt_paths and row.ref not in self.remote_wt
            ]
            self.set_spacer("worktree")
            lines = self.branch_lines()
            columns = self.column_row(wt_column=False)
            delete = self.delete_branches
        else:
            lines = self.worktree_lines()
            columns = self.column_row(wt_column=True)
        picked = self.pick(lines, PICKER_TITLES[path], PICKER_ACTIONS[path], columns)
        if picked is None:
            return 0
        return self.act(*picked, delete)


def reset_prompt(
    remote_branch: str, branch: str, wt_path: str, ahead: int, behind: int
) -> str:
    """The question offer_reset_to_remote asks, with what a reset discards."""
    commit_word = "commit" if behind == 1 else "commits"
    if wt_path:
        where = (
            f"The worktree {paint(wt_path, COLOR_YELLOW_BOLD)} has it checked "
            "out, so it does not have the remote's state."
        )
    else:
        where = (
            "The new worktree checks out the local branch, so it would not "
            "have the remote's state."
        )
    discard = ""
    if ahead > 0:
        ahead_word = "commit that is" if ahead == 1 else "commits that are"
        discard = (
            f"\nResetting discards {paint(str(ahead), COLOR_RED_BOLD)} local "
            f"{ahead_word} not on the remote."
        )
    dirty = colored_status(wt_path) if wt_path else ""
    dirty_note = ""
    if dirty:
        dirty_note = (
            "\n\n"
            + paint("It also discards these uncommitted changes:", COLOR_RED_BOLD)
            + f"\n\n{dirty}"
        )
    b_branch = paint(branch, COLOR_BLUE_BOLD)
    y_remote = paint(remote_branch, COLOR_YELLOW_BOLD)
    return (
        f"\n{paint('INFO:', COLOR_YELLOW_BOLD)} Local branch '{b_branch}' is "
        f"{paint(str(behind), COLOR_RED_BOLD)} {commit_word} behind "
        f"'{y_remote}'.\n{where}{discard}{dirty_note}\n\n"
        f"Reset '{b_branch}' to '{y_remote}'?"
    )


def current_subdir() -> str:
    """The current directory relative to the top of its worktree, "" at the
    top or outside any worktree (a bare repository, a .git directory)."""
    if git_out("rev-parse", "--is-inside-work-tree") != "true":
        return ""
    return git_out("rev-parse", "--show-prefix").rstrip("/")


def subdir_note(subdir: str) -> str:
    return f" (subdirectory: {paint(subdir, COLOR_YELLOW)})" if subdir else ""


def parse_worktree_record(record: str) -> tuple[str, str]:
    """(path, ref) of one `git worktree list --porcelain` entry. Attribute
    lines may come in any order or be absent (locked, prunable, ...); the ref
    of a detached worktree is detached/heads/<short sha>; a bare entry has no
    ref."""
    fields: dict[str, str] = {}
    for line in record.split("\n"):
        key, _, value = line.partition(" ")
        fields[key] = value
    if "bare" in fields or "worktree" not in fields:
        return "", ""
    ref = fields.get("branch", "")
    if not ref and "detached" in fields and fields.get("HEAD"):
        ref = f"{DETACHED_PREFIX}{fields['HEAD'][:7]}"
    return fields["worktree"], ref


def drop_stash(commit: str, cwd: str) -> None:
    ref = stash_ref(commit, cwd)
    if ref:
        git("-C", cwd, "stash", "drop", ref)


def stash_ref(commit: str, cwd: str) -> str:
    """The current stash@{n} of a stash commit."""
    for line in git_out("-C", cwd, "stash", "list", "--format=%gd %H").splitlines():
        ref, _, sha = line.partition(" ")
        if sha == commit:
            return ref
    return ""


# ---------------------------------------------------------------------------
# Shell integration
# ---------------------------------------------------------------------------


def program_command() -> str:
    """How the wrapper calls this program: by name when that name on PATH is
    this file, otherwise by its absolute path."""
    found = shutil.which(PROG_NAME)
    if found and os.path.realpath(found) == script_path():
        return PROG_NAME
    return script_path()


POSIX_WRAPPER = """\
# {prog} shell integration for {shell}
# Defines `fgb`, which runs {prog} and changes to the worktree it jumps to.
# A leading backslash keeps the user's aliases (rm, cat, cd, ...) out of it:
# bash and zsh expand them when the function is defined.
fgb() {{
    __fgb_tmp=$(\\command mktemp "${{TMPDIR:-/tmp}}/fgb.XXXXXX") || return 1
    \\command {command} --cwd-file "$__fgb_tmp" "$@"
    __fgb_rc=$?
    __fgb_dir=$(\\command cat -- "$__fgb_tmp" 2>/dev/null)
    \\command rm -f -- "$__fgb_tmp"
    if [ -n "$__fgb_dir" ]; then
        \\cd -- "$__fgb_dir" || __fgb_rc=1
    fi
    set -- "$__fgb_rc"
    unset __fgb_tmp __fgb_dir __fgb_rc
    return "$1"
}}
"""
FISH_WRAPPER = """\
# {prog} shell integration for fish
# Defines `fgb`, which runs {prog} and changes to the worktree it jumps to.
function fgb --wraps={prog} --description 'Manage Git branches and worktrees with fzf'
    set -l tmpdir /tmp
    set -q TMPDIR; and set tmpdir $TMPDIR
    set -l tmp (command mktemp $tmpdir/fgb.XXXXXX); or return 1
    command {command} --cwd-file $tmp $argv
    set -l code $status
    set -l dir (command cat -- $tmp 2>/dev/null)
    command rm -f -- $tmp
    if test -n "$dir"
        cd -- $dir; or set code 1
    end
    return $code
end
"""
NU_WRAPPER = """\
# {prog} shell integration for nushell
# Defines `fgb`, which runs {prog} and changes to the worktree it jumps to.
def --env --wrapped fgb [...args: string] {{
    let tmp = (mktemp --tmpdir fgb.XXXXXX)
    $env.LAST_EXIT_CODE = 0
    try {{ ^{command} --cwd-file $tmp ...$args }} catch {{ }}
    let code = $env.LAST_EXIT_CODE
    let dir = (open --raw $tmp | str trim --right --char "\\n")
    # Not to the trash, whatever the always_trash setting says
    rm --force --permanent $tmp
    if $dir != "" {{ cd $dir }}
    $env.LAST_EXIT_CODE = $code
}}
"""
PWSH_WRAPPER = """\
# {prog} shell integration for PowerShell
# Defines `fgb`, which runs {prog} and changes to the worktree it jumps to.
# PowerShell drops a bare -- from the arguments; quote it: fgb branch manage '--' x
function fgb {{
    $fgbTmp = [System.IO.Path]::GetTempFileName()
    try {{
        & {command} --cwd-file $fgbTmp @args
        $fgbCode = $LASTEXITCODE
        $fgbDir = [System.IO.File]::ReadAllText($fgbTmp)
        if ($fgbDir) {{ Set-Location -LiteralPath $fgbDir }}
    }} finally {{
        Remove-Item -LiteralPath $fgbTmp -Force -ErrorAction SilentlyContinue
    }}
    $global:LASTEXITCODE = $fgbCode
}}
"""


def fish_quote(text: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./-]+", text):
        return text
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def init_script(shell: str) -> str:
    command = program_command()
    if shell in ("bash", "zsh", "sh", "ksh", "dash"):
        text = POSIX_WRAPPER.format(
            prog=PROG_NAME, shell=shell, command=shlex.quote(command)
        )
    elif shell == "fish":
        text = FISH_WRAPPER.format(prog=PROG_NAME, command=fish_quote(command))
    elif shell == "nu":
        quoted = (
            command
            if re.fullmatch(r"[A-Za-z0-9_./-]+", command)
            else ("'" + command + "'")
        )
        text = NU_WRAPPER.format(prog=PROG_NAME, command=quoted)
    else:
        quoted = "'" + command.replace("'", "''") + "'"
        text = PWSH_WRAPPER.format(prog=PROG_NAME, command=quoted)
    if shell in COMPLETION_SHELLS:
        text += "\n" + completion_script(shell)
    return text


def completion_tree() -> dict[str, list[tuple[list[str], bool, list[str], str]]]:
    """Options of every command path: (option strings, takes a value,
    choices, help)."""
    _, leaves = build_parser()
    tree: dict[str, list[tuple[list[str], bool, list[str], str]]] = {}
    for path, leaf in leaves.items():
        if path.startswith("_"):
            continue
        options = []
        for action in leaf._actions:
            if not action.option_strings or action.help == argparse.SUPPRESS:
                continue
            takes_value = action.nargs != 0
            choices = [str(c) for c in action.choices] if action.choices else []
            summary = (action.help or "").split(" (")[0].split(";")[0]
            options.append((list(action.option_strings), takes_value, choices, summary))
        tree[path] = options
    return tree


COMMAND_SUMMARIES = {
    "branch": "Manage branches",
    "worktree": "Manage worktrees",
    "config": "Show the settings and their sources",
    "init": "Print the shell integration",
    "completion": "Print the completion script",
    "version": "Show the version",
    "help": "Show the help",
}


def completion_script(shell: str) -> str:
    tree = completion_tree()
    if shell == "bash":
        return bash_completion(tree)
    if shell == "zsh":
        return zsh_completion(tree)
    return fish_completion(tree)


def bash_completion(
    tree: dict[str, list[tuple[list[str], bool, list[str], str]]],
) -> str:
    # Value options mean the same in every command, so one case covers them
    values: dict[str, list[str]] = {}
    cases = []
    for path, options in tree.items():
        for strings, takes_value, choices, _ in options:
            if takes_value:
                values["|".join(strings)] = choices
        words = " ".join(opt for strings, _, _, _ in options for opt in strings)
        if path in ("init", "completion"):
            shells = INIT_SHELLS if path == "init" else COMPLETION_SHELLS
            words += " " + " ".join(shells)
        cases.append(f'        "{path}") words="{words}" ;;')
    value_cases = [
        f'        {pattern}) words="{" ".join(choices)}" ;;'
        if choices
        else f"        {pattern}) return ;;"
        for pattern, choices in values.items()
    ]
    commands = " ".join(COMMAND_SUMMARIES)
    return f"""\
_fzf_git_branches_complete() {{
    local cur=${{COMP_WORDS[COMP_CWORD]}} prev=${{COMP_WORDS[COMP_CWORD-1]}}
    local path="" word words="" i
    case "$prev" in
{chr(10).join(value_cases)}
    esac
    if [[ -z $words ]]; then
        for ((i = 1; i < COMP_CWORD; i++)); do
            word=${{COMP_WORDS[i]}}
            [[ $word == -* ]] && continue
            if [[ -z $path ]]; then
                path=$word
            elif [[ $path == branch || $path == worktree ]]; then
                path="$path $word"
                break
            else
                break
            fi
        done
        case "$path" in
            "") words="{commands} -C --color --config --show-config --version" ;;
            branch) words="{" ".join(SUBCOMMANDS["branch"])}" ;;
            worktree) words="{" ".join(SUBCOMMANDS["worktree"])}" ;;
{chr(10).join("    " + case for case in cases)}
            *) return ;;
        esac
    fi
    local IFS=$'\\n'
    COMPREPLY=($(IFS=' ' compgen -W "$words" -- "$cur"))
}}
complete -o default -F _fzf_git_branches_complete fgb {PROG_NAME}
"""


def zsh_quote(text: str) -> str:
    return (
        text.replace("'", "'\\''")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace(":", "\\:")
    )


def zsh_completion(
    tree: dict[str, list[tuple[list[str], bool, list[str], str]]],
) -> str:
    cases = []
    for path, options in tree.items():
        specs = []
        for strings, takes_value, choices, summary in options:
            exclusive = f"({' '.join(strings)})"
            for opt in strings:
                spec = opt
                if takes_value:
                    spec += "=" if opt.startswith("--") else "+"
                spec += f"[{zsh_quote(summary)}]"
                if takes_value:
                    spec += ":value:" + (f"({' '.join(choices)})" if choices else "")
                specs.append(f"'{exclusive}{spec}'")
        if path in ("init", "completion"):
            shells = " ".join(INIT_SHELLS if path == "init" else COMPLETION_SHELLS)
            specs.append(f"':shell:({shells})'")
        elif path in (
            "branch manage",
            "worktree manage",
            "worktree add",
            "worktree total",
        ):
            specs.append("'*:query:'")
        cases.append(f"        '{path}') _arguments -s -S {' '.join(specs)} ;;")
    commands = " ".join(
        f"'{name}:{summary}'" for name, summary in COMMAND_SUMMARIES.items()
    )
    return f"""\
_fzf_git_branches() {{
    local -a args=("${{(@)words[2,CURRENT-1]}}") path=()
    local word
    for word in $args; do
        [[ $word == -* ]] && continue
        path+=($word)
        (( ${{#path}} == 1 )) && [[ $word != branch && $word != worktree ]] && break
        (( ${{#path}} == 2 )) && break
    done
    if (( ${{#path}} == 0 )); then
        local -a commands=({commands})
        _describe command commands
        return
    fi
    if (( ${{#path}} == 1 )) && [[ $path[1] == branch || $path[1] == worktree ]]; then
        case $path[1] in
            branch) compadd -- {" ".join(SUBCOMMANDS["branch"])} ;;
            worktree) compadd -- {" ".join(SUBCOMMANDS["worktree"])} ;;
        esac
        return
    fi
    case "$path" in
{chr(10).join(cases)}
    esac
}}
if (( $+functions[compdef] )); then
    compdef _fzf_git_branches fgb {PROG_NAME}
fi
"""


def fish_completion(
    tree: dict[str, list[tuple[list[str], bool, list[str], str]]],
) -> str:
    lines = [
        f"complete -c {PROG_NAME} -f",
        "function __fzf_git_branches_path",
        "    set -l words (commandline -opc)[2..]",
        "    set -l path",
        "    for word in $words",
        "        string match -q -- '-*' $word; and continue",
        "        set -a path $word",
        "        if test (count $path) -eq 1",
        "            and not contains -- $word branch worktree",
        "            break",
        "        end",
        "        test (count $path) -eq 2; and break",
        "    end",
        "    string join ' ' -- $path",
        "end",
    ]
    prefix = f"complete -c {PROG_NAME}"
    for name, summary in COMMAND_SUMMARIES.items():
        lines.append(
            f"{prefix} -n 'test -z (__fzf_git_branches_path)' -a {name} -d '{summary}'"
        )
    for parent, subs in SUBCOMMANDS.items():
        for sub in subs:
            lines.append(
                f"{prefix} -n 'test (__fzf_git_branches_path) = {parent}' -a {sub}"
            )
    for path, options in tree.items():
        condition = f"-n 'test (__fzf_git_branches_path) = \"{path}\"'"
        for strings, takes_value, choices, summary in options:
            flags = []
            for opt in strings:
                flags.append(
                    f"-l {opt[2:]}" if opt.startswith("--") else f"-s {opt[1:]}"
                )
            extra = ""
            if takes_value:
                extra = f" -x -a '{' '.join(choices)}'" if choices else " -r"
            text = summary.replace("'", "\\'")
            lines.append(f"{prefix} {condition} {' '.join(flags)}{extra} -d '{text}'")
        if path in ("init", "completion"):
            shells = " ".join(INIT_SHELLS if path == "init" else COMPLETION_SHELLS)
            lines.append(f"{prefix} {condition} -a '{shells}'")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Settings report (config command, --show-config)
# ---------------------------------------------------------------------------

# Setting -> (argparse dest of its option, the option, default value)
SETTING_OPTIONS: dict[str, tuple[str, str, str]] = {
    ENV_SORT_ORDER: ("sort", "-s", DEFAULT_SORT_ORDER),
    ENV_DATE_FORMAT: ("date_format", "-d", DEFAULT_DATE_FORMAT),
    ENV_AUTHOR_FORMAT: ("author_format", "-u", DEFAULT_AUTHOR_FORMAT),
    ENV_WT_PATH_DISPLAY: ("wt_path_display", "-p", WT_PATH_MODES[0]),
    ENV_WT_BASE_PATH_BARE: ("", "", DEFAULT_WT_BASE_PATH),
    ENV_WT_BASE_PATH_REGULAR: ("", "", DEFAULT_WT_BASE_PATH),
    **{setting: ("", "", key) for setting, key in PICKER_KEYS.values()},
    ENV_FZF_OPTS: ("", "", ""),
    ENV_COLOR: ("color", "-C", COLOR_MODES[0]),
    ENV_KEEP_SUBDIR: ("keep_subdir", "-k", "false"),
}
# Settings with a fixed set of values
SETTING_CHOICES = {ENV_WT_PATH_DISPLAY: WT_PATH_MODES, ENV_COLOR: COLOR_MODES}
BOOLEAN_SETTINGS = {ENV_KEEP_SUBDIR: "--no-keep-subdir"}
SOURCE_COLORS = {
    "command line": COLOR_GREEN,
    "environment": COLOR_YELLOW,
    "config file": COLOR_BLUE,
}


@dataclasses.dataclass
class ConfigSource:
    """The config file a run reads and where each of its keys is."""

    path: Path
    explicit: bool
    values: dict[str, str]
    lines: dict[str, int]

    def describe(self, cli: str | None) -> str:
        if cli:
            how = "--config"
        elif os.environ.get(ENV_CONFIG):
            how = ENV_CONFIG
        else:
            how = "default location"
        found = "found" if self.path.is_file() else "not found"
        return f"{self.path} ({how}, {found})"


def setting_source(
    setting: str, args: argparse.Namespace, config: ConfigSource
) -> tuple[str, str]:
    """(value, source) of a setting, following resolve()'s precedence."""
    dest, option, default = SETTING_OPTIONS[setting]
    cli = getattr(args, dest, None) if dest else None
    if cli:
        if setting in BOOLEAN_SETTINGS and cli == "false":
            option = BOOLEAN_SETTINGS[setting]
        return cli, f"command line ({option})"
    env = os.environ.get(setting)
    if env:
        return env, "environment"
    # Empty values count as unset; say so, they are easy to miss
    notes = ["empty in the environment"] if env is not None else []
    line = config.lines.get(setting)
    if config.values.get(setting):
        value, source = (
            config.values[setting],
            f"config file ({config.path.name}:{line})",
        )
    else:
        if line:
            notes.append(f"empty in {config.path.name}:{line}")
        value, source = default, "default"
    return value, source + (f" ({'; '.join(notes)})" if notes else "")


def report_table(rows: Sequence[tuple[str, str, str]]) -> list[str]:
    """Aligned rows of (name, value, source), the source colored by kind."""
    name_width = max(len(name) for name, _, _ in rows)
    value_width = max(len(value) for _, value, _ in rows)
    lines = []
    for name, value, source in rows:
        color = next(
            (c for kind, c in SOURCE_COLORS.items() if source.startswith(kind)), ""
        )
        text = f"  {name:<{name_width}}  {value:<{value_width}}"
        lines.append(f"{text}  {paint(source, color)}".rstrip())
    return lines


def invalid_note(setting: str, value: str) -> str:
    """What the setting takes when `value` is invalid, otherwise ""."""
    choices: Sequence[str] = SETTING_CHOICES.get(setting, ())
    if setting in BOOLEAN_SETTINGS:
        choices, value = tuple(BOOLEAN_VALUES), value.lower()
    return f"one of {', '.join(choices)}" if choices and value not in choices else ""


def settings_rows(
    args: argparse.Namespace, config: ConfigSource
) -> list[tuple[str, str, str]]:
    rows = []
    for setting in SETTING_OPTIONS:
        value, source = setting_source(setting, args, config)
        shown = value
        if setting == ENV_FZF_OPTS and not value:
            shown = "(built-in options)"
        note = invalid_note(setting, value)
        if note:
            shown += f" (invalid: {note})"
        rows.append((setting, shown, source))
    return rows


def call_rows(args: argparse.Namespace, query: str) -> list[tuple[str, str]]:
    """What the checked command line asks for besides the settings."""
    words = [args.command, getattr(args, "subcommand", "")]
    rows = [("command", " ".join(word for word in [PROG, *words] if word))]
    if hasattr(args, "remotes"):
        scope = "all (-a)" if args.all else "remote (-r)" if args.remotes else "local"
        rows.append(("branches", scope))
    if hasattr(args, "confirm"):
        path = "derived (-c)" if args.confirm else "asked for"
        rows.append(("worktree path", path))
    if hasattr(args, "force"):
        rows.append(("delete", "without asking (-f)" if args.force else "asks first"))
    if hasattr(args, "query"):
        rows.append(("fzf query", query or "(none)"))
    return rows


def color_decision() -> str:
    if COLOR.mode != "auto":
        return f"{'on' if COLOR.mode == 'always' else 'off'} ({COLOR.mode})"
    if os.environ.get("NO_COLOR"):
        return "off (NO_COLOR is set)"
    if sys.stdout.isatty():
        return "on (stdout is a terminal)"
    return "off for output (stdout is not a terminal), on in fzf"


def fzf_description() -> str:
    fzf = shutil.which("fzf")
    if fzf is None:
        return "not found (needed by the manage, add and total commands)"
    try:
        version = ".".join(map(str, fzf_version()))
    except AppError as exc:
        return f"{fzf}: {exc}"
    return f"{fzf} {version}"


def runtime_rows(args: argparse.Namespace, settings: Settings) -> list[tuple[str, str]]:
    columns = os.environ.get("COLUMNS", "")
    width_source = "COLUMNS" if columns.isdigit() and int(columns) > 0 else "terminal"
    shell = os.environ.get("SHELL", "sh")
    runner = (
        f"$SHELL ({shell}), as FGB_FZF_OPTS is set"
        if settings.fzf_opts
        else "/bin/sh (built-in options)"
    )
    wrapped = getattr(args, "cwd_file", None)
    rows = [
        ("terminal width", f"{terminal_width()} columns ({width_source})"),
        ("colors", color_decision()),
        ("fzf", fzf_description()),
        ("fzf runs commands with", runner),
        (
            "directory changes",
            "by the fgb shell function"
            if wrapped
            else "printed as a cd hint (not run through fgb)",
        ),
    ]
    return rows + repository_rows(settings)


def repository_rows(settings: Settings) -> list[tuple[str, str]]:
    if git("rev-parse", "--git-dir").returncode != 0:
        return [("repository", "none (not inside a Git repository)")]
    superproject = git_out("rev-parse", "--show-superproject-working-tree")
    if superproject.startswith("/"):
        return [
            ("repository", f"submodule of {superproject}"),
            ("worktree commands", "refused for submodules"),
        ]
    app = Fgb(settings, None)
    try:
        app.load_worktrees()
    except AppError as exc:
        return [("repository", str(exc))]
    setting = ENV_WT_BASE_PATH_BARE if app.is_bare else ENV_WT_BASE_PATH_REGULAR
    template = settings.wt_base_bare if app.is_bare else settings.wt_base_regular
    if git_out("rev-parse", "--is-inside-work-tree") != "true":
        subdir = "none (not inside a worktree)"
    else:
        kept = "kept" if settings.keep_subdir else "not kept"
        subdir = f"{current_subdir() or '(the worktree root)'}, {kept} on switching"
    return [
        ("repository", "bare" if app.is_bare else "regular"),
        ("main worktree", app.root),
        ("git common dir", app.common_dir),
        ("worktree base", f"{app.wt_base} (from {setting}={template})"),
        ("worktrees", str(len(app.wt_paths))),
        ("subdirectory", subdir),
    ]


def usable_value(setting: str, args: argparse.Namespace, config: ConfigSource) -> str:
    """The setting's value, or its default when the value is invalid."""
    value = setting_source(setting, args, config)[0]
    return SETTING_OPTIONS[setting][2] if invalid_note(setting, value) else value


def show_config(args: argparse.Namespace, query: str, config: ConfigSource) -> int:
    """The settings report of `config` and --show-config."""
    rows = settings_rows(args, config)
    # The report runs with invalid values too: those use their defaults
    lenient = {
        setting: usable_value(setting, args, config) for setting in SETTING_OPTIONS
    }
    COLOR.mode = lenient[ENV_COLOR]
    settings = Settings(
        wt_base_bare=lenient[ENV_WT_BASE_PATH_BARE],
        wt_base_regular=lenient[ENV_WT_BASE_PATH_REGULAR],
        wt_path_display=lenient[ENV_WT_PATH_DISPLAY],
        fzf_opts=lenient[ENV_FZF_OPTS],
        keep_subdir=BOOLEAN_VALUES[lenient[ENV_KEEP_SUBDIR].lower()],
    )
    emit(f"{PROG_NAME} {__version__}")
    emit(f"Config file: {config.describe(getattr(args, 'config', None))}")
    emit(f"\n{paint('Settings', COLOR_BOLD)}")
    for line in report_table(rows):
        emit(line)
    sections = [("Runtime", runtime_rows(args, settings))]
    if args.command != "config":
        sections.insert(0, ("Command line", call_rows(args, query)))
    for title, pairs in sections:
        emit(f"\n{paint(title, COLOR_BOLD)}")
        width = max(len(name) for name, _ in pairs)
        for name, value in pairs:
            emit(f"  {name:<{width}}  {value}")
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def cmd_preview(row: str) -> int:
    """fzf's preview: the graph of the row's branch or commit."""
    if len(row) < len("[]"):
        return 0
    color = "never" if COLOR.mode == "never" else "always"
    return subprocess.run(
        [
            "git",
            "log",
            "--oneline",
            "--decorate",
            "--graph",
            f"--color={color}",
            row[1:-1],
            "--",
        ],
        check=False,
    ).returncode


def in_repository() -> None:
    if git("rev-parse", "--git-dir").returncode != 0:
        raise AppError("Not inside a Git repository", EXIT_NO_REPO)


def early_color(argv: Sequence[str]) -> str:
    """The color mode for help and usage errors, which argparse prints
    before the settings are resolved. Nothing fails here: an invalid or
    unreadable setting counts as unset, and the full run reports it."""
    options: dict[str, str] = {}
    for arg in attach_values(argv):
        if arg == "--":
            break
        name, sep, value = arg.partition("=")
        if sep and name in ("--color", "--config"):
            options[name] = value
        elif arg.startswith("-") and not arg.startswith("--"):
            # The first option taking a value takes the rest of the word
            for index, char in enumerate(arg[1:], start=2):
                if char in SHORT_VALUE_OPTS:
                    if char == "C":
                        options["--color"] = arg[index:]
                    break
    try:
        config = load_config(*config_path(options.get("--config")), quiet=True)
    except (AppError, OSError, UnicodeDecodeError):
        config = {}
    levels = (options.get("--color"), os.environ.get(ENV_COLOR), config.get(ENV_COLOR))
    return next((mode for mode in levels if mode in COLOR_MODES), COLOR_MODES[0])


@contextlib.contextmanager
def help_colors(mode: str) -> Iterator[None]:
    """argparse colors only a terminal on its own; `always` colors any
    output, as it does everywhere else."""
    saved = os.environ.get("PYTHON_COLORS")
    if mode == "always":
        os.environ["PYTHON_COLORS"] = "1"
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("PYTHON_COLORS", None)
        else:
            os.environ["PYTHON_COLORS"] = saved


def run(args: argparse.Namespace, query: str) -> int:
    command = args.command
    if command == "config" or getattr(args, "show_config", False):
        path, explicit = config_path(getattr(args, "config", None))
        lines: dict[str, int] = {}
        values = load_config(path, explicit, lines)
        return show_config(args, query, ConfigSource(path, explicit, values, lines))
    if command in ("init", "completion"):
        script = init_script if command == "init" else completion_script
        print(script(args.shell), end="")
        return 0
    config_cli = getattr(args, "config", None)
    path, explicit = config_path(config_cli)
    config = load_config(path, explicit)
    COLOR.mode = choice(getattr(args, "color", None), ENV_COLOR, config, COLOR_MODES)
    if command == "_preview":
        return cmd_preview(args.row)
    in_repository()
    app = Fgb(settings_from(args, config), getattr(args, "cwd_file", None))
    app.query = query
    try:
        if command == "branch":
            if args.subcommand == "list":
                return app.branch_list()
            return app.branch_manage()
        return app.worktree_command(args.subcommand)
    finally:
        app.finish()


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # Run through the shell wrapper, the user typed `fgb`
    wrapped = any(arg == "--cwd-file" or arg.startswith("--cwd-file=") for arg in argv)
    mode = early_color(argv)
    parser, leaves = build_parser(
        WRAPPER_NAME if wrapped else PROG, color=mode != "never"
    )
    index, path = command_path(argv)

    with help_colors(mode):
        # `version` and `help` as the command win over everything else
        if index is not None and argv[index] == "version":
            print(f"{PROG_NAME} {__version__}")
            return 0
        if index is not None and argv[index] == "help":
            parser.print_help()
            return 0

        leaf = leaves.get(path, parser)
        try:
            reject_short_equals(argv)
        except AppError as exc:
            leaf.error(str(exc))
        argv = attach_values(argv)
        # Words after `--` are query words, as are positional words that the
        # query argument did not take because options came between them
        dash_query: list[str] = []
        if "--" in argv and index is not None and argv.index("--") > index:
            split = argv.index("--")
            argv, dash_query = argv[:split], argv[split + 1 :]
        args, extras = parser.parse_known_args(argv)
        takes_query = hasattr(args, "query")
        unknown = [arg for arg in extras if arg.startswith("-") or not takes_query]
        if dash_query and not takes_query:
            unknown += ["--", *dash_query]
        if unknown:
            leaf.error(f"unrecognized arguments: {' '.join(unknown)}")
        words = [*getattr(args, "query", []), *extras, *dash_query]
        query = " ".join(words)

    try:
        return run(args, query)
    except AppError as exc:
        report(str(exc))
        return exc.code
    except KeyboardInterrupt:
        emit()
        return 130
    except BrokenPipeError:
        # Output piped into a command that exited early (e.g. `| head`)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 1


if __name__ == "__main__":
    sys.exit(main())
