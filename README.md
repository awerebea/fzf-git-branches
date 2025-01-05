# fzf-git-branches

A script to manage Git branches and worktrees using `fzf` in `bash` and `zsh`. It provides a
convenient way to handle Git branches and worktrees with a fuzzy finder interface.

## Features

- List, delete, and switch to Git branches and worktrees.
- Integrated with `fzf` for enhanced user interaction.
- Support for confirmation dialogs.
- ANSI output coloring for better readability.

## Requirements

- `git` (https://git-scm.com/)
- `fzf` (https://github.com/junegunn/fzf)
- Modern version of `bash` or `zsh`

## Installation

1. Clone the repository or download the script.

   ```sh
   git clone https://github.com/awerebea/fzf-git-branches.git ~/.fzf-git-branches
   ```

2. Source the script in your shell configuration file (`.bashrc`, `.zshrc`, etc.):

   ```sh
   source ~/.fzf-git-branches/fzf-git-branches.sh
   ```

3. Ensure `fzf` is installed and available in your `PATH`.

## Configuration

Options that can be defined using environment variables may also be specified in a configuration file located at:  
`$HOME/.config/fgbrc`

<details>
  <summary>Screenshot</summary>

![image](https://github.com/user-attachments/assets/7e6829dc-e6b2-44f2-97b7-ac5a53825094)

</details>

## Advanced Configuration

### Default Options Overriding

The default values of FZF options are set as follows:

```sh
--height 80% \
--reverse \
--ansi \
--bind=ctrl-y:accept,ctrl-t:toggle+down \
--border=top \
--cycle \
--multi \
--pointer='' \
--preview 'FGB_BRANCH={1}; git log --oneline --decorate --graph --color=always \${FGB_BRANCH:1:-1}'
```

These defaults can be overridden by setting the `FGB_FZF_OPTS` environment variable.

The default branches sort order is `-committerdate`, but this can be overridden by setting the `FGB_SORT_ORDER` environment variable.

Similarly, the default date format is `committerdate:relative`, which can be overridden using `FGB_DATE_FORMAT`.

Lastly, the default author format is `committername`, could be redefined with `FGB_AUTHOR_FORMAT`.

### Lazy Load

To reduce shell startup time, consider lazy loading the script by calling it instead of sourcing it automatically every time.
Replace `source ~/.fzf-git-branches/fzf-git-branches.sh` in your shell rc file with the following code snippet.
This snippet defines several functions and aliases that load the script only when needed:

```sh
# Check if the script is installed
if [ -f "$HOME/.fzf-git-branches/fzf-git-branches.sh" ]; then
    lazy_fgb() {
        unset -f fgb gbl gbm gwl gwa gwm gwt lazy_fgb
        if ! source "$HOME/.fzf-git-branches/fzf-git-branches.sh"; then
            echo "Failed to load fzf-git-branches" >&2
            return 1
        fi
        alias gbl='fgb branch list'
        alias gbm='fgb branch manage'
        alias gwl='fgb worktree list'
        alias gwm='fgb worktree manage'
        alias gwa='fgb worktree add --confirm'
        alias gwt='fgb worktree total --confirm'
        fgb "$@"
    }
    function fgb() {
        lazy_fgb "$@"
    }
    function gbl() {
        lazy_fgb branch list "$@"
    }
    function gbm() {
        lazy_fgb branch manage "$@"
    }
    function gwl() {
        lazy_fgb worktree list "$@"
    }
    function gwm() {
        lazy_fgb worktree manage "$@"
    }
    function gwa() {
        lazy_fgb worktree add --confirm "$@"
    }
    function gwt() {
        lazy_fgb worktree total --confirm "$@"
    }
fi
```

#### Lazy Load Explanation

This snippet defines a lazy loading function `lazy_fgb` and related functions
that wrap the `lazy_fgb` function call with corresponding commands, subcommands, and any additional arguments provided:

- `lazy_fgb`: The main function responsible for lazy loading fzf-git-branches.sh and executing commands based on arguments passed to it.
- `fgb`: Calls `lazy_fgb` with any arguments.
- `gbl`: Calls `lazy_fgb` with the command `branch list`.
- `gbm`: Calls `lazy_fgb` with the command `branch manage`.
- `gwl`: Calls `lazy_fgb` with the command `worktree list`.
- `gwm`: Calls `lazy_fgb` with the command `worktree manage`.
- `gwa`: Calls `lazy_fgb` with the command `worktree add --confirm`.
- `gwt`: Calls `lazy_fgb` with the command `worktree total --confirm`.

Here’s how it works:

Lazy Loading Function `lazy_fgb`:
On its first call, `lazy_fgb` unsets itself and all related functions.
It then sources the `fzf-git-branches.sh` script to load its functionality.

Aliases for Convenience:
To replace the functions that were unset earlier, `lazy_fgb` establishes aliases with identical names
corresponding to commonly used commands provided by the script.
These aliases simplify the execution of the script’s commands, enhancing usability and efficiency.

Customization:
Users can edit or expand the aliases as needed for their specific requirements.

This approach enhances shell startup efficiency by loading scripts only when necessary,
while the predefined aliases streamline command execution once the script is loaded.

## Usage

To start using the script, call the `fgb` function in your terminal with a command and its options as arguments.

### Examples

Manage branches:

```sh
fgb branch manage
```

<details>
  <summary>Screenshot</summary>

![image](https://github.com/awerebea/fzf-git-branches/assets/63558838/562de083-563d-4e12-8b86-fe0f5a6f356d)

</details>

Manage worktrees:

```sh
fgb worktree total
```

<details>
  <summary>Screenshot</summary>

![image](https://github.com/awerebea/fzf-git-branches/assets/63558838/f043dd0e-af1d-491b-a8c6-3c5cd0a3d37d)

</details>

This will open a fzf interface to manage your Git branches.

### Key Bindings

Default key bindings that can be overridden by `FGB_FZF_OPTS` environment variable:

- `enter/ctrl-y`: Select the branch/worktree to jump to.
- `ctrl-t`: Toggle the selection.

After invoking fzf, the following key bindings are expected (and can be redefined by the <br/>
`FGB_BINDKEY_DEL`, `FGB_BINDKEY_EXTEND_DEL`, `FGB_BINDKEY_INFO`, `FGB_BINDKEY_VERBOSE`
environment variables respectively):

- `ctrl-d`: Delete the selected branch.
    <details>
      <summary>Screenshot</summary>

  ![image](https://github.com/awerebea/fzf-git-branches/assets/63558838/395654d8-43d8-48ca-87d9-be9097ec8d32)
    </details>

- `ctrl-alt-d`: Extended delete.
  When deleting a worktree, delete the associated local branch;
  when deleting a local branch, delete the remote branch.
    <details>
      <summary>Screenshot</summary>

  ![image](https://github.com/awerebea/fzf-git-branches/assets/63558838/7fd26620-0dce-4f8b-b889-c46ec6f6548e)
    </details>

- `ctrl-o`: Show branch information.
    <details>
      <summary>Screenshot</summary>

  ![image](https://github.com/awerebea/fzf-git-branches/assets/63558838/0581fe20-f60b-4881-b605-010bf23dacff)
    </details>

- `ctrl-v`: Use _verbose_ mode to prompt for user confirmation of the directory name for the new worktree,
  even when this confirmation is suppressed by the `-c, --confirm` option.
    <details>
      <summary>Screenshot</summary>

  ![image](https://github.com/awerebea/fzf-git-branches/assets/63558838/4937c29e-c2e2-4d77-b61d-5089c8704207)
    </details>

- `alt-n`: Create a new branch by forking the currently selected (highlighted) branch and assigning it a specified name.
    <details>
      <summary>Screenshot</summary>

  ![image](https://github.com/user-attachments/assets/119cb58d-a660-4615-bbf2-636697ca15eb)
    </details>

### Available Commands and Subcommands

#### Branch Commands

- `fgb branch list [args]`:
  Lists the Git branches in the repository and exit.

- `fgb branch manage [args]`:
  Switch to existing branches in the git repository, delete them,
  or get information about branches.

#### Worktree Commands

- `fgb worktree list [args]`:
  Lists all worktrees in a bare Git repository and exit.

- `fgb worktree manage [args]`:
  Switch to existing worktrees in the bare Git repository or delete them.

- `fgb worktree add [args]`:
  Add a new worktree based on a selected Git branch.

- `fgb worktree total [args]`:
  **_Total_** control over worktrees.
  Add a new one, switch to an existing worktree in the bare Git repository,
  or delete them, optionally with corresponding branches.

##### Available options used in commands in appropriate combinations.

- By default, all commands list only local branches.
- `-r, --remotes`: Lists only remote branches.
    <details>
      <summary>Screenshot</summary>

  ![image](https://github.com/awerebea/fzf-git-branches/assets/63558838/e914f240-2548-4250-87ce-074677e35654)
    </details>

- `-a, --all`: Lists both local and remote branches.
    <details>
      <summary>Screenshot</summary>

  ![image](https://github.com/awerebea/fzf-git-branches/assets/63558838/93e26ef9-7cfa-492c-863d-5eef74097af1)
    </details>

- `-s, --sort`: Sort branches by **_<sort>_**:
  - `-committerdate` (default )
  - `refname`
  - `authorname`
  - etc.

    You can specify multiple sort criteria separated by commas (e.g., `-committerdate,committername`).
    In such cases:
    - Branches will first be grouped alphabetically by the last specified criterion (e.g., committer name in the example).
    - Within each group, branches will then be sorted based on the preceding criteria (e.g., by committer date in reverse order in the example).
- `-f, --force`:
  Suppress confirmation dialog for non-destructive operations
- `-c, --confirm`:
  Automatic confirmation of the directory name for the new worktree
- `-d, --date-format`:
  Format for 'date' string:
  - `committerdate:relative` (default)
  - `%(authordate) %(committerdate:short)`
  - `authordate:(relative|local|default|iso|iso-strict|rfc|short|raw)`
  - `authordate:format:'%Y-%m-%d %H:%M:%S'`
  - `committerdate:format-local:'%Y-%m-%d %H:%M:%S'`
- `-u, --author-format`:
  Format for 'author' string:
  - `committername` (default)
  - `authoremail`
  - `%(committername) %(committeremail)`
  - `%(authorname) %(authormail) / %(committername) %(committeremail)`

<details>
  <summary>Screenshot</summary>

![image](https://github.com/awerebea/fzf-git-branches/assets/63558838/f333eb76-ef12-4565-b381-a6b8b72b6acb)

</details>

For more details on each command and its options,
you can use the `-h` or `--help` option. For example:

```sh
fgb branch manage --help
```

<details>
  <summary>Screenshot</summary>

![image](https://github.com/awerebea/fzf-git-branches/assets/63558838/532722b3-21e3-483b-b987-f414118da191)

</details>

## License

This script is licensed under the GPL License.
See the [LICENSE](LICENSE) file for more details.

## Contribution

Feel free to open issues or submit pull requests if you find bugs
or have suggestions for improvements.

## Inspiration

Inspired by [fzf-marks](https://github.com/urbainvaes/fzf-marks) and
[git-worktree.nvim](https://github.com/ThePrimeagen/git-worktree.nvim).
