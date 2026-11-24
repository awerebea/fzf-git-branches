# fzf-git-branches

Manage Git branches and worktrees with `fzf`: list, switch to, add, fork and
delete them from a fuzzy finder. Works in bare and regular repositories.

`fzf-git-branches` is a standalone Python program, so it works the same in any
shell. A small shell function, `fgb`, wraps it so that jumping to a worktree
changes the directory of your shell.

## Features

- List, delete, and switch to Git branches and worktrees.
- Add worktrees for local or remote branches, or fork a branch into a new
  worktree, carrying uncommitted changes over.
- Optionally land in the same subdirectory of the worktree you switch to.
- Integrated with `fzf`, with a `git log` graph preview.
- Confirmation dialogs answered with a single key.
- Colored output, columns that adapt to the terminal width.
- Shell integration for bash, zsh, sh (dash, ksh), fish, nushell and
  PowerShell; completion for bash, zsh and fish.

## Requirements

- [git](https://git-scm.com/)
- [fzf](https://github.com/junegunn/fzf) 0.27 or newer (not needed for the
  `list` commands)
- Python 3.10 or newer, standard library only. Stock macOS ships Python 3.9 as
  `/usr/bin/python3`; install a newer one (Homebrew, mise, pyenv, ...) and make
  sure it comes first on `PATH`.

## Installation

1. Clone the repository:

   ```sh
   git clone https://github.com/awerebea/fzf-git-branches.git ~/.fzf-git-branches
   ```

2. Put the program on your `PATH` as `fzf-git-branches`, for example with a
   symlink into `~/.local/bin`:

   ```sh
   mkdir -p ~/.local/bin
   ln -s ~/.fzf-git-branches/fzf_git_branches.py ~/.local/bin/fzf-git-branches
   ```

   Check it with `fzf-git-branches version`.

3. Add the shell integration to your shell's startup file (next section).
   It defines the `fgb` function.

### Shell integration

A program cannot change the directory of the shell that started it. The `fgb`
function runs `fzf-git-branches`, which writes the worktree to jump to into a
temporary file, and then changes to it in your shell. Directory hooks (zoxide,
mise, direnv, ...) run as after any `cd`.

| Shell        | Startup file                     | Line to add                                              |
| ------------ | -------------------------------- | -------------------------------------------------------- |
| bash         | `~/.bashrc`                      | `eval "$(fzf-git-branches init bash)"`                   |
| zsh          | `~/.zshrc`, after `compinit`     | `eval "$(fzf-git-branches init zsh)"`                    |
| dash, ksh    | `~/.profile`, `$ENV`, `~/.kshrc` | `eval "$(fzf-git-branches init sh)"`                     |
| fish         | `~/.config/fish/config.fish`     | `fzf-git-branches init fish \| source`                   |
| PowerShell   | `$PROFILE`                       | `Invoke-Expression (& fzf-git-branches init pwsh \| Out-String)` |

For **nushell**, which cannot evaluate generated code at startup, save the
integration once into the autoload directory (and again after upgrading):

```nu
mkdir ($nu.data-dir | path join "vendor/autoload")
fzf-git-branches init nu | save -f ($nu.data-dir | path join "vendor/autoload/fzf-git-branches.nu")
```

Notes:

- bash, zsh and fish also get completion for `fgb` and `fzf-git-branches`. In
  zsh, put the line after `compinit` so that the completion is registered.
- PowerShell removes a bare `--` from a function's arguments; quote it:
  `fgb branch manage '--' -query`.
- When `fzf-git-branches` is not on `PATH`, `init` writes the program's
  absolute path into the function instead, so
  `eval "$(~/.fzf-git-branches/fzf_git_branches.py init zsh)"` works too.
- Without the integration everything still works; where `fgb` would change
  directory, `fzf-git-branches` prints the `cd` command to run instead.

Aliases are plain aliases of the `fgb` function, for example:

```sh
alias gbl='fgb branch list'
alias gbm='fgb branch manage'
alias gwl='fgb worktree list'
alias gwm='fgb worktree manage'
alias gwa='fgb worktree add --confirm'
alias gwt='fgb worktree total --confirm'
```

### Upgrading from the sourced script (0.x)

Version 1.0.0 replaces the sourced `fzf-git-branches.sh` with the program
above. Remove the `source .../fzf-git-branches.sh` line (or the lazy-load
snippet) from your startup file and follow the installation steps. Settings in
`~/.config/fgbrc` and the environment keep working. What changed:

- `-v` is gone; use `--version` or `fgb version`. The version output is one
  line, `fzf-git-branches 1.0.0`.
- Usage errors print `usage: ...` and `error: ...` and exit with 2 (was 1).
  Short options can be combined (`-ra`) and take attached values (`-srefname`);
  `-s=x` is rejected, use `-s x`, `-sx` or `--sort=x`.
- Help is available everywhere, also outside a repository.
- `branch list` and `worktree list` reject a query, `--` and `-f`.
- An invalid `FGB_WT_PATH_DISPLAY` is an error instead of falling back to
  `tilde`.
- Colors follow `-C/--color` and `FGB_COLOR`, in the help too: by default
  only terminals get them, so `fgb branch list | less` is plain text, and
  `NO_COLOR` is honored.
- `FGB_FZF_OPTS` can be set in `~/.config/fgbrc` too, and is split like shell
  words (quotes work, `$VAR` is not expanded).
- The fzf-tmux fallback for fzf older than 0.16.1 is gone; fzf 0.27 or newer is
  required.
- The default preview runs `fzf-git-branches _preview`, through `sh`, so it no
  longer depends on bash syntax and works when your shell is fish or nushell.

## Usage

```text
fgb [-C MODE] [-L LEVEL] [--config FILE] COMMAND [SUBCOMMAND] [OPTIONS] [QUERY...]
```

| Command                        | Description                                                         |
| ------------------------------ | ------------------------------------------------------------------- |
| `fgb branch list`              | List branches and exit                                              |
| `fgb branch manage [QUERY]`    | Switch to branches, delete, fork, or show information               |
| `fgb worktree list`            | List worktrees and exit                                             |
| `fgb worktree manage [QUERY]`  | Jump to worktrees or delete them                                    |
| `fgb worktree add [QUERY]`     | Add a worktree for a branch that has none                           |
| `fgb worktree total [QUERY]`   | All of the above: add, jump, delete worktrees and their branches   |
| `fgb config`                   | Show the settings in effect and where each one comes from           |
| `fgb init SHELL`               | Print the shell integration                                         |
| `fgb completion SHELL`         | Print only the completion script (bash, zsh, fish)                  |
| `fgb version`, `fgb help`      | Show the version or the help                                        |

The query (words after the options, or after `--`) is fzf's initial query.
Every command has `-h/--help`, `--version` and `--show-config` (see
[Checking the settings](#checking-the-settings)).

<details>
  <summary>Screenshot</summary>

![image](https://github.com/awerebea/fzf-git-branches/assets/63558838/562de083-563d-4e12-8b86-fe0f5a6f356d)

</details>

### Options

| Option                       | Commands                    | Description                                                     |
| ---------------------------- | --------------------------- | --------------------------------------------------------------- |
| `-s, --sort SORT`            | all list/picker commands    | `git for-each-ref --sort` keys, comma-separated                 |
| `-d, --date-format FORMAT`   | all list/picker commands    | Date column format                                              |
| `-u, --author-format FORMAT` | all list/picker commands    | Author column format                                            |
| `-p, --wt-path-display MODE` | `worktree *`                | How worktree paths are shown (see below)                        |
| `-k, --keep-subdir`          | `worktree manage/add/total` | Keep the current subdirectory (see below); `--no-keep-subdir` turns it off |
| `-r, --remotes`              | `branch *`, `worktree add/total` | Remote branches only (default: local only)                 |
| `-a, --all`                  | `branch *`, `worktree add/total` | Local and remote branches                                  |
| `-c, --confirm`              | `worktree add/total`        | No path prompt: new worktrees go to `<base path>/<branch>`      |
| `-f, --force`                | `branch manage`, `worktree manage/add/total` | Skip the first delete confirmation             |
| `-C, --color MODE`           | all                         | `auto` (terminals only), `always`, `never`                      |
| `-L, --log-level LEVEL`      | all                         | What goes to stderr: `error`, `warning`, `notice` (default), `info`, `debug` |
| `--config FILE`              | all                         | Config file instead of `~/.config/fgbrc`                        |
| `--show-config`              | all                         | Show what the command would use instead of running it           |

`--force` never skips the questions that guard irreversible steps: deleting a
remote branch, an unmerged branch, or a worktree with uncommitted changes.

Sort keys: `-committerdate` (default), `refname`, `authorname`, and so on.
With several keys (`-committerdate,committername`) branches are grouped by the
last key and sorted by the earlier ones within each group.

Date formats: `committerdate:relative` (default), `authordate:short`,
`authordate:(relative|local|default|iso|iso-strict|rfc|short|raw)`,
`authordate:format:'%Y-%m-%d %H:%M:%S'`,
`committerdate:format-local:'%Y-%m-%d %H:%M:%S'`,
`%(authordate) %(committerdate:short)`.

Author formats: `committername` (default), `authoremail`,
`%(committername) %(committeremail)`,
`%(authorname) %(authoremail) / %(committername) %(committeremail)`.

### Key bindings

In the picker (change the action keys with the `FGB_BINDKEY_*` settings):

| Key            | Setting                          | Action                                                              |
| -------------- | -------------------------------- | ------------------------------------------------------------------- |
| `enter/ctrl-y` |                                  | Switch to the branch, or jump to (or add) its worktree              |
| `ctrl-t`       |                                  | Toggle the selection                                                |
| `ctrl-d`       | `FGB_BINDKEY_DEL`                | Delete the selected branches or worktrees                           |
| `ctrl-alt-d`   | `FGB_BINDKEY_EXTEND_DEL`         | Extended delete (see below)                                         |
| `ctrl-o`       | `FGB_BINDKEY_INFO`               | Show branch information                                             |
| `ctrl-v`       | `FGB_BINDKEY_VERBOSE`            | Ask for the new worktree's path even with `--confirm`               |
| `alt-n`        | `FGB_BINDKEY_NEW_BRANCH`         | Fork the branch; in `worktree` commands also add a worktree for it  |
| `alt-N`        | `FGB_BINDKEY_NEW_BRANCH_VERBOSE` | Fork and add a worktree, always asking for its path                 |

Extended delete: deleting a worktree offers to delete its branch (as plain
delete does), deleting a local branch also offers its upstream remote branch,
and deleting a remote branch also offers the local branch tracking it.

`enter`, `ctrl-y` and `ctrl-t` come from the default fzf options and change
with `FGB_FZF_OPTS`.

### Keeping the subdirectory

With `-k/--keep-subdir` (or `FGB_KEEP_SUBDIR=true`), jumping to a worktree,
adding one or forking into one lands in the same subdirectory you are in now,
not in the worktree's root: from `~/repo.git/wt/main/src/app`, jumping to
`feat` goes to `~/repo.git/wt/feat/src/app`.

If that directory does not exist in the target worktree, fgb warns and lands
in its nearest parent that does, or in the root:

```text
Warning: 'src/app/new-module' does not exist in this worktree; using 'src/app'
```

The subdirectory is where you are relative to the top of the current
worktree, as `git rev-parse --show-prefix` reports it. Outside any worktree
(in a bare repository or a `.git` directory) there is none, and fgb lands in
the root. Deleting the worktree you are in still goes to the repository root.

### Remote branches

Selecting a remote branch creates a worktree for its local counterpart, since
`git worktree add <path> <branch>` resolves a name to the existing local
branch:

- **No local branch yet** - git creates one tracking the remote branch and
  checks it out in the new worktree.
- **The local counterpart already has a worktree** - the remote branch shows
  that worktree in the `WT` column, since that is where selecting it goes, and
  fgb jumps there. Such branches are therefore not offered by `worktree add`.
  If that worktree is behind the remote branch, fgb says so and offers to
  reset it first, defaulting to no; the reset is a `git reset --hard` in that
  worktree, so any uncommitted changes are listed before you answer. The link
  is the branch's configured upstream, so it holds even when the local branch
  is named differently; then the jump message names the branch checked out
  there. If several local branches track one remote branch and more than one
  has a worktree, the one named like the remote branch wins, and otherwise the
  alphabetically first.
- **The local counterpart exists, has no worktree, and is behind the remote** -
  fgb reports how far behind it is and offers to reset it to the remote branch
  first, defaulting to no. If the local branch also has commits the remote does
  not, the prompt says how many a reset would discard.

`ctrl-o` (info) shows the resolved worktree for a remote branch too.
`<remote>/HEAD` is not listed: it is a symbolic ref, and selecting it would
create a detached worktree.

## Configuration

Settings come from the command line, the environment, and the config file
`~/.config/fgbrc` (or `--config FILE` / `FGB_CONFIG`), in that order of
precedence, then the defaults. An empty value counts as unset. See
[`fgbrc`](fgbrc) for a commented example.

The config file holds `KEY=value` lines and is read as data, never executed.
`#` starts a comment at the beginning of a line or after whitespace, one pair
of surrounding quotes is removed, and an `export ` prefix is allowed. Unknown
keys are reported as warnings.

| Setting                          | Option | Default                  |
| -------------------------------- | ------ | ------------------------ |
| `FGB_SORT_ORDER`                 | `-s`   | `-committerdate`         |
| `FGB_DATE_FORMAT`                | `-d`   | `committerdate:relative` |
| `FGB_AUTHOR_FORMAT`              | `-u`   | `committername`          |
| `FGB_WT_PATH_DISPLAY`            | `-p`   | `tilde`                  |
| `FGB_WT_BASE_PATH_BARE`          |        | `./wt`                   |
| `FGB_WT_BASE_PATH_REGULAR`       |        | `./wt`                   |
| `FGB_BINDKEY_DEL`                |        | `ctrl-d`                 |
| `FGB_BINDKEY_EXTEND_DEL`         |        | `ctrl-alt-d`             |
| `FGB_BINDKEY_INFO`               |        | `ctrl-o`                 |
| `FGB_BINDKEY_VERBOSE`            |        | `ctrl-v`                 |
| `FGB_BINDKEY_NEW_BRANCH`         |        | `alt-n`                  |
| `FGB_BINDKEY_NEW_BRANCH_VERBOSE` |        | `alt-N`                  |
| `FGB_FZF_OPTS`                   |        | see below                |
| `FGB_COLOR`                      | `-C`   | `auto`                   |
| `FGB_KEEP_SUBDIR`                | `-k`   | `false`                  |
| `FGB_LOG_LEVEL`                  | `-L`   | `notice`                 |

Boolean settings take `true` or `false`, or `1/0`, `yes/no`, `on/off`, in any
case.

### Checking the settings

`fgb config` lists every setting with its value and where that value comes
from: the command line, the environment, the config file (with the line
number) or the default. An empty variable or config value counts as unset,
and the report says when one was skipped. Invalid values are marked instead
of stopping the report. A second part shows what the settings resolve to:
the terminal width and whether colors are on (and why), the fzf found and
which shell runs its commands, whether `fgb` can change directory, and, in a
repository, whether it is bare, its main worktree, git common dir and the
resolved worktree base path.

`fgb config` takes the same `-s`, `-d`, `-u`, `-p` and `-C` options as the
other commands. To check a whole command line, append `--show-config` to it;
the command is not run, and the report adds what it asked for (branches,
path prompt, delete confirmation, fzf query):

```sh
fgb config
fgb worktree add -a -c -s refname feat --show-config
```

```text
fzf-git-branches 1.1.0
Config file: /home/me/.config/fgbrc (default location, found)

Settings
  FGB_SORT_ORDER                  refname                 command line (-s)
  FGB_DATE_FORMAT                 committerdate:short     config file (fgbrc:19)
  FGB_WT_PATH_DISPLAY             tilde                   default (empty in the environment)
  FGB_BINDKEY_DEL                 ctrl-x                  environment
  ...

Command line
  command        fgb worktree add
  branches       all (-a)
  worktree path  derived (-c)
  delete         asks first
  fzf query      feat

Runtime
  terminal width          120 columns (terminal)
  colors                  on (stdout is a terminal)
  fzf                     /usr/bin/fzf 0.60.0
  fzf runs commands with  /bin/sh (built-in options)
  directory changes       by the fgb shell function
  repository              bare
  ...
```

### Log levels

Lists, branch details and prompts go to stdout. Everything else goes to
stderr, as much as `-L/--log-level` (or `FGB_LOG_LEVEL`) asks for; each level
includes the ones before it:

| Level     | Shows                                                                   |
| --------- | ----------------------------------------------------------------------- |
| `error`   | What stops the run (`Error: ...`)                                       |
| `warning` | Problems that do not stop it: ignored config lines, a missing subdirectory with `-k`, a failed reset or stash apply |
| `notice`  | The outcome of each action: jumped to, added, deleted, reset, switched to a new branch, the stash applied (default) |
| `info`    | The config file and every setting with its source, the repository, what was picked, the directory changed to |
| `debug`   | Every git and fzf command, its exit code and the first 10 lines of its output (`debug: ...`) |

The config file's own `FGB_LOG_LEVEL` applies to the problems found in that
file. Messages from git about a failed command and the `cd` hint printed
without the shell integration are not diagnostics and always appear.

`-L warning` makes a successful run silent:

```text
$ fgb worktree manage
Jumped to worktree: /home/me/repo.git/wt/feat, for branch 'feat'
$ fgb -L warning worktree manage
$
```

```sh
fgb -L debug worktree manage 2> /tmp/fgb.log
```

### fzf options

The default fzf options are:

```sh
--height 80% --reverse --ansi --bind=ctrl-y:accept,ctrl-t:toggle+down \
--border=top --cycle --multi --pointer= --preview '<fzf-git-branches _preview {1}>'
```

`FGB_FZF_OPTS` replaces everything after `--reverse`. It is split like shell
words. With the defaults, fzf runs the preview with `sh`; with your own
options, fzf uses your `$SHELL` as usual, so write commands for it. The keys of
`--bind` options are listed in the picker header.

### Worktree path display

`FGB_WT_PATH_DISPLAY` or `-p` selects how worktree paths are shown:

| Mode               | Description                                                                |
| ------------------ | -------------------------------------------------------------------------- |
| `tilde` (default)  | Absolute path with `$HOME` collapsed to `~`                                |
| `absolute`         | Full absolute path                                                         |
| `relative-cwd`     | Path relative to the current directory                                     |
| `relative-home`    | Path relative to `$HOME` (e.g. `~/Github/project.git/wt/branch`)           |
| `relative-repo`    | Path relative to the repo root (for bare repos: same as `relative-gitdir`) |
| `relative-gitdir`  | Path relative to the git common dir (e.g. `./wt/my-branch`)                |
| `relative-wt-base` | Path relative to the worktree base dir (e.g. `./my-branch`)                |
| `absolute-gitdir`  | Absolute path (a path under the git common dir re-joins to itself)         |
| `tilde-gitdir`     | Same as `absolute-gitdir` but with `$HOME` collapsed to `~`                |

A path that is only parent segments is shown with a trailing slash, so `.`,
`..` and `../..` display as `./`, `../` and `../../`. Symlinks are resolved as
git does (on macOS, `/var` is `/private/var`).

### Worktree base path

The default worktree base path template is `./wt`, anchored to the git common
dir:

- Bare repo (`project.git/`): worktrees land at `project.git/wt/<branch>`
- Regular repo (`project/`): worktrees land at `project/.git/wt/<branch>`

Set `FGB_WT_BASE_PATH_BARE` and/or `FGB_WT_BASE_PATH_REGULAR` to customize. A
leading `~` and `$VAR` / `${VAR}` references are expanded first (only plain
variable names; nothing is ever evaluated); what remains is used as-is when it
starts with `/`, and anchored to the git common dir otherwise. `.` and `..`
segments are collapsed. Placeholders: `{repo_name}` (basename of the repo's
working-tree root, which for a bare repo is the bare directory itself, e.g.
`project.git`) and `{repo_name_short}` (the same without a trailing `.git`).

```sh
# Organize worktrees in a per-project subdir inside the bare repo:
FGB_WT_BASE_PATH_BARE=./wt/{repo_name_short}
# => project.git/wt/project/feature-x

# The old outside-the-repo default (before v0.19):
FGB_WT_BASE_PATH_BARE=../worktrees/{repo_name_short}
FGB_WT_BASE_PATH_REGULAR=../../worktrees/{repo_name}

# Absolute, ~ and $VAR forms all work:
FGB_WT_BASE_PATH_REGULAR=~/Work/worktrees/{repo_name}
FGB_WT_BASE_PATH_BARE=$WORKTREES/{repo_name_short}
```

## Exit codes

| Code | Meaning                                                    |
| ---- | ---------------------------------------------------------- |
| 0    | Success, or the picker was cancelled                       |
| 1    | Error (printed as `Error: ...`)                            |
| 2    | Usage error                                                |
| 128  | Not inside a Git repository (or worktree, where one is needed) |
| 130  | Interrupted, or a path prompt was cancelled                |

A failing `git switch` or `git worktree add` passes its own exit code through.

## Known limitations

- **Submodules are not supported** by the `worktree` commands. A submodule's
  git directory lives inside the superproject's, at
  `<super>/.git/modules/<name>`, so its worktrees would be created under the
  superproject's `.git`, invisible to normal tooling and removed by
  `git submodule deinit`. `fgb worktree` detects this and exits with a message.
  Clone the submodule as a standalone repository to use worktrees with it.
- **Column widths are measured in characters, not display cells.** Names with
  double-width characters (CJK, some emoji) can shift the columns after them.
- A repository created with `--separate-git-dir` records nothing that points
  back to its main working tree, so from one of its _linked_ worktrees the main
  worktree's path cannot be determined; git reports its git directory instead.
- The program needs a POSIX system (Linux, macOS, WSL); PowerShell is
  supported there, not on native Windows.

## Development

The tests use [pytest](https://pytest.org/), declared as the `dev`
dependency group in `pyproject.toml` (the program itself needs none), and build throwaway repositories in a temporary directory. A stub `fzf` on
`PATH` records its arguments and answers with scripted selections, so the
pickers run without a terminal; the shell integration is tested in every
installed shell (bash, zsh, dash, ksh, fish, nu, pwsh; missing ones are
skipped).

```sh
python3 -m venv .venv && .venv/bin/pip install --group dev  # pip 25.1+
.venv/bin/pytest
ruff check . && ruff format --check . && mypy
```

The previous shell implementation, `fzf-git-branches.sh`, and its suite,
`tests/run.sh`, remain in the repository for now.

## License

This program is licensed under the GPL License.
See the [LICENSE](LICENSE) file for more details.

## Contribution

Feel free to open issues or submit pull requests if you find bugs
or have suggestions for improvements.

## Inspiration

Inspired by [fzf-marks](https://github.com/urbainvaes/fzf-marks) and
[git-worktree.nvim](https://github.com/ThePrimeagen/git-worktree.nvim).
