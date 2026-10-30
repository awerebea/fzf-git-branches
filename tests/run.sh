#!/usr/bin/env bash
# Test suite for fzf-git-branches.
#
# Usage:
#   tests/run.sh              run the suite under every shell found (bash, zsh)
#   tests/run.sh --in-shell   run the suite once, in the current shell
#
# Self-contained: builds throwaway git repositories under a temporary directory
# and exercises the script's internal functions directly, because the normal
# entry points open fzf. Needs nothing beyond git and the shell under test.
#
# Exits non-zero if any check fails.
#
# shellcheck disable=SC2034 # globals set here are read by the sourced fgb functions
# shellcheck disable=SC2016,SC2088 # expected values hold a literal ~ and $

#------------------------------------------------------------------------------
# Driver: re-run this file under each shell so cross-shell differences surface.
#------------------------------------------------------------------------------

if [[ "${1-}" != "--in-shell" ]]; then
    self="$0"
    overall=0
    ran_any=false
    for shell_name in bash zsh; do
        if ! command -v "$shell_name" >/dev/null 2>&1; then
            printf 'skip: %s is not installed\n' "$shell_name"
            continue
        fi
        ran_any=true
        printf '\n=================== %s ===================\n' "$shell_name"
        "$shell_name" "$self" --in-shell || overall=1
    done
    if [[ "$ran_any" != true ]]; then
        printf 'error: neither bash nor zsh is available\n' >&2
        exit 1
    fi
    exit "$overall"
fi

#------------------------------------------------------------------------------
# Setup
#------------------------------------------------------------------------------

if [[ -n "${ZSH_VERSION-}" ]]; then
    current_shell=zsh
else
    current_shell=bash
fi

tests_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(dirname -- "$tests_dir")
fgb_script="$repo_dir/fzf-git-branches.sh"

if [[ ! -f "$fgb_script" ]]; then
    printf 'error: cannot find %s\n' "$fgb_script" >&2
    exit 1
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT INT TERM

# Keep the user's git configuration and identity out of the fixtures.
export GIT_CONFIG_GLOBAL=/dev/null
export GIT_CONFIG_SYSTEM=/dev/null
export GIT_AUTHOR_NAME=test GIT_AUTHOR_EMAIL=test@example.com
export GIT_COMMITTER_NAME=test GIT_COMMITTER_EMAIL=test@example.com

passed=0
failed=0

describe() {
    printf '\n# %s\n' "$1"
}

ok() {
    passed=$((passed + 1))
    printf '  ok   %s\n' "$1"
}

bad() {
    failed=$((failed + 1))
    printf '  FAIL %s\n' "$1"
    [[ -n "${2-}" ]] && printf '       %s\n' "$2"
    return 0
}

# eq <name> <got> <want>
eq() {
    if [[ "$2" = "$3" ]]; then
        ok "$1"
    else
        bad "$1" "got '$2' want '$3'"
    fi
}

# has <name> <haystack> <needle>
has() {
    case "$2" in
        *"$3"*) ok "$1" ;;
        *) bad "$1" "'$3' not found in: $(printf '%s' "$2" | tr '\n' '/')" ;;
    esac
}

# hasnt <name> <haystack> <needle>
hasnt() {
    case "$2" in
        *"$3"*) bad "$1" "unexpected '$3'" ;;
        *) ok "$1" ;;
    esac
}

fatal() {
    printf 'error: %s\n' "$1" >&2
    exit 1
}

#------------------------------------------------------------------------------
# Load the script's internal functions
#
# They live inside fgb() and are unset when it returns, so they are lifted out
# of the source between two fixed anchors and dedented. If either anchor ever
# moves the guard below fails loudly rather than silently skipping tests.
#------------------------------------------------------------------------------

awk '
    /^        __fgb_confirmation_dialog\(\) \{$/ { grab = 1 }
    /^        # Process the configuration file$/ { grab = 0 }
    grab { sub(/^        /, ""); print }
' "$fgb_script" >"$TMP/funcs.sh"

[[ -s "$TMP/funcs.sh" ]] || fatal "could not lift the internal functions out of $fgb_script"

# shellcheck source=/dev/null
. "$TMP/funcs.sh"

for fn in \
    __fgb_normalize_path \
    __fgb_expand_env \
    __fgb_tilde_path \
    __fgb_render_relative \
    __fgb_format_wt_path \
    __fgb_build_remote_wt_map \
    __fgb_offer_reset_to_remote \
    __fgb_worktree_set_vars \
    __fgb_worktree_list \
    __fgb_git_branch_list \
    __fgb_git_worktree_jump_or_add \
    __fgb_print_branch_info; do
    command -v "$fn" >/dev/null 2>&1 || fatal "expected function $fn was not loaded"
done

#------------------------------------------------------------------------------
# Globals the lifted functions expect, mirroring the script's own defaults
#------------------------------------------------------------------------------

typeset -A c_worktree_path_map
typeset -A c_remote_wt_map
typeset -A c_branch_author_map
typeset -A c_branch_date_map

reset_globals() {
    # Colours are blanked so assertions can match plain text.
    col_reset='' col_r='' col_g='' col_y='' col_b='' col_m='' col_bold=''
    col_r_bold='' col_g_bold='' col_y_bold='' col_b_bold=''

    c_split_char=$(printf '\037')
    c_bracket_loc_open='[' c_bracket_loc_close=']'
    c_bracket_rem_open='(' c_bracket_rem_close=')'
    c_bracket_det_open='{' c_bracket_det_close='}'
    c_detached_wt_prefix='detached/heads/'

    c_wt_path_display=absolute
    c_is_bare_repo=false
    c_confirmed=true
    c_force=false
    c_extend_del=false
    c_git_root_path='' c_git_common_dir='' c_wt_base_path=''
    c_wt_base_path_tmpl_bare='./wt'
    c_wt_base_path_tmpl_regular='./wt'
    c_branch_sort_order='-committerdate'
    c_date_format='%(committerdate:relative)'
    c_author_format='%(committername)'

    c_branches='' c_worktree_branches=''
    c_wt_path_width=0 c_branch_width=24 c_author_width=6 c_date_width=4
    c_total_width=0 c_spacer=2
    c_show_author=false c_show_date=false
    c_show_wt_path=true c_show_wt_flag=false
    WIDTH_OF_WINDOW=200

    # Clear without re-declaring: typeset inside a function would make these
    # local to it, and the functions under test would fill throwaway copies.
    c_worktree_path_map=()
    c_remote_wt_map=()
    c_branch_author_map=()
    c_branch_date_map=()
}

# Re-read repository state for the current directory.
refresh() {
    c_worktree_path_map=()
    c_remote_wt_map=()
    c_wt_path_width=0
    __fgb_worktree_set_vars
}

#------------------------------------------------------------------------------
# Fixtures
#------------------------------------------------------------------------------

git_q() { git "$@" >/dev/null 2>&1; }

commit_file() {
    printf '%s\n' "$2" >"$1/$2.txt"
    git_q -C "$1" add -A
    git_q -C "$1" commit -m "add $2"
}

# plain/            ordinary repo
# plain-wt-spaced/  linked worktree whose path contains a space
# plain-wt-locked/  linked, locked worktree (extra porcelain attribute line)
build_plain() {
    git_q init -b main "$TMP/plain"
    commit_file "$TMP/plain" base
    git_q -C "$TMP/plain" branch spaced
    git_q -C "$TMP/plain" branch locked
    git_q -C "$TMP/plain" worktree add "$TMP/with space/wt" spaced
    git_q -C "$TMP/plain" worktree add "$TMP/plain-wt-locked" locked
    git_q -C "$TMP/plain" worktree lock "$TMP/plain-wt-locked"
}

build_bare() {
    git_q init -b main "$TMP/seed"
    commit_file "$TMP/seed" base
    git_q init --bare "$TMP/hub.git"
    git_q -C "$TMP/seed" remote add origin "$TMP/hub.git"
    git_q -C "$TMP/seed" push -u origin main
    git_q -C "$TMP/hub.git" symbolic-ref HEAD refs/heads/main
    git_q -C "$TMP/hub.git" worktree add "$TMP/hub.git/wt/main" main
}

build_sepgitdir() {
    git_q init -b main --separate-git-dir="$TMP/sep.gitdir" "$TMP/sepwork"
    commit_file "$TMP/sepwork" base
}

build_submodule() {
    git_q init -b main "$TMP/super"
    commit_file "$TMP/super" base
    git_q -C "$TMP/super" -c protocol.file.allow=always submodule add "$TMP/plain" sub
    git_q -C "$TMP/super" commit -m "add submodule"
}

# clone/ with remote-tracking branches:
#   linked    local counterpart holding a worktree
#   stale     local counterpart with no worktree, one commit behind its remote
#   orphan    remote branch with no local counterpart
#   twin      tracked by several local branches (twin, aaa-twin, zzz-twin)
build_remote() {
    git_q init -b main "$TMP/rseed"
    commit_file "$TMP/rseed" base
    git_q init --bare "$TMP/remote.git"
    git_q -C "$TMP/rseed" remote add origin "$TMP/remote.git"
    git_q -C "$TMP/rseed" push -u origin main
    for b in linked stale orphan twin; do
        git_q -C "$TMP/rseed" checkout -b "$b" main
        commit_file "$TMP/rseed" "$b"
        git_q -C "$TMP/rseed" push -u origin "$b"
    done
    git_q -C "$TMP/rseed" checkout main

    # Point the remote's HEAD at a branch that exists, so the clone actually gets a
    # refs/remotes/origin/HEAD for the "not listed" check to be meaningful.
    git_q -C "$TMP/remote.git" symbolic-ref HEAD refs/heads/main

    git_q clone "$TMP/remote.git" "$TMP/clone"
    git_q -C "$TMP/clone" branch linked origin/linked
    git_q -C "$TMP/clone" worktree add "$TMP/wt-linked" linked
    git_q -C "$TMP/clone" branch stale "origin/stale~1"
    git_q -C "$TMP/clone" branch --set-upstream-to=origin/stale stale
    for b in twin aaa-twin zzz-twin; do
        git_q -C "$TMP/clone" branch "$b" origin/twin
        git_q -C "$TMP/clone" branch --set-upstream-to=origin/twin "$b"
        git_q -C "$TMP/clone" worktree add "$TMP/wt-$b" "$b"
    done
}

build_plain
build_bare
build_sepgitdir
build_submodule
build_remote

#------------------------------------------------------------------------------
# Path helpers
#------------------------------------------------------------------------------

reset_globals

describe "path helpers collapse, expand and render paths"
eq "normalize collapses .." "$(__fgb_normalize_path /a/b/../c)" "/a/c"
eq "normalize collapses . and //" "$(__fgb_normalize_path /a/./b//c)" "/a/b/c"
eq "normalize can reach the root" "$(__fgb_normalize_path /a/b/../..)" "/"
eq "normalize stops at the root" "$(__fgb_normalize_path /a/../../b)" "/b"
eq "normalize escapes a git dir" "$(__fgb_normalize_path /x/r/.git/../wt)" "/x/r/wt"
eq "normalize keeps leading .." "$(__fgb_normalize_path ../../x)" "../../x"
eq "normalize keeps spaces" "$(__fgb_normalize_path '/with space/wt')" "/with space/wt"
eq "normalize of . is ." "$(__fgb_normalize_path .)" "."

(
    HOME=/home/ann
    eq "tilde substitutes a literal ~" "$(__fgb_tilde_path /home/ann/proj)" "~/proj"
    eq "tilde on \$HOME itself" "$(__fgb_tilde_path /home/ann)" "~"
    eq "tilde needs a path boundary" "$(__fgb_tilde_path /home/annabel/proj)" "/home/annabel/proj"
    eq "tilde leaves other paths alone" "$(__fgb_tilde_path /opt/x)" "/opt/x"
) || failed=$((failed + 1))

eq "render . as a directory" "$(__fgb_render_relative .)" "./"
eq "render .. as a directory" "$(__fgb_render_relative ..)" "../"
eq "render ../.. as a directory" "$(__fgb_render_relative ../..)" "../../"
eq "render a parent-relative path" "$(__fgb_render_relative ../x)" "../x"
eq "render a descendant" "$(__fgb_render_relative wt/foo)" "./wt/foo"

FGB_TEST_VAR=/srv/wt
export FGB_TEST_VAR
eq "expand \$VAR" "$(__fgb_expand_env '$FGB_TEST_VAR/x')" "/srv/wt/x"
eq "expand \${VAR}" "$(__fgb_expand_env '${FGB_TEST_VAR}/x')" "/srv/wt/x"
eq "leave a plain path alone" "$(__fgb_expand_env 'plain/path')" "plain/path"
eq "an unset variable is empty" "$(__fgb_expand_env '$FGB_NO_SUCH_VAR/y')" "/y"
eq "no command substitution" "$(__fgb_expand_env 'a$(id -u)b')" 'a$(id -u)b'

#------------------------------------------------------------------------------
# Repository identity
#------------------------------------------------------------------------------

describe "repository identity comes from git, not from string surgery"

reset_globals
cd "$TMP/plain" || fatal "cannot enter the plain fixture"
refresh
eq "ordinary repo: root" "$c_git_root_path" "$(cd "$TMP/plain" && pwd -P)"
eq "ordinary repo: common dir" "$c_git_common_dir" "$(cd "$TMP/plain/.git" && pwd -P)"
eq "ordinary repo: not bare" "$c_is_bare_repo" "false"

reset_globals
cd "$TMP/hub.git" || fatal "cannot enter the bare fixture"
refresh
eq "bare repo: detected" "$c_is_bare_repo" "true"
eq "bare repo: root is the dir" "$c_git_root_path" "$(cd "$TMP/hub.git" && pwd -P)"
eq "bare repo: common dir" "$c_git_common_dir" "$(cd "$TMP/hub.git" && pwd -P)"

reset_globals
cd "$TMP/sepwork" || fatal "cannot enter the separate-git-dir fixture"
refresh
eq "separate git dir: common dir" "$c_git_common_dir" "$(cd "$TMP/sep.gitdir" && pwd -P)"
eq "separate git dir: root is the working tree" \
    "$c_git_root_path" "$(cd "$TMP/sepwork" && pwd -P)"
eq "separate git dir: main worktree mapped to the working tree" \
    "${c_worktree_path_map["refs/heads/main"]}" "$(cd "$TMP/sepwork" && pwd -P)"

describe "worktree base path templates"

expand_base() {
    # $1 = template, $2 = directory to resolve it in
    reset_globals
    c_wt_base_path_tmpl_regular="$1"
    c_wt_base_path_tmpl_bare="$1"
    cd "$2" || fatal "cannot enter $2"
    refresh
    printf '%s' "$c_wt_base_path"
}

eq "relative template anchors to the git dir" \
    "$(expand_base './wt' "$TMP/plain")" "$(cd "$TMP/plain/.git" && pwd -P)/wt"
eq "..  in a template is collapsed" \
    "$(expand_base '../wt' "$TMP/plain")" "$(cd "$TMP/plain" && pwd -P)/wt"
eq "absolute template used as-is" \
    "$(expand_base '/abs/wt' "$TMP/plain")" "/abs/wt"
eq "{repo_name} in an ordinary repo is the working-tree root" \
    "$(expand_base '../w/{repo_name}' "$TMP/plain")" "$(cd "$TMP/plain" && pwd -P)/w/plain"
eq "{repo_name} in a bare repo keeps .git" \
    "$(expand_base '../w/{repo_name}' "$TMP/hub.git")" "$(dirname "$(cd "$TMP/hub.git" && pwd -P)")/w/hub.git"
eq "{repo_name_short} strips .git" \
    "$(expand_base '../w/{repo_name_short}' "$TMP/hub.git")" "$(dirname "$(cd "$TMP/hub.git" && pwd -P)")/w/hub"
eq "a ~ template is expanded, not anchored" \
    "$(HOME=/home/ann expand_base '~/worktrees' "$TMP/plain")" "/home/ann/worktrees"
eq "a \$VAR template is expanded" \
    "$(expand_base '$FGB_TEST_VAR/w' "$TMP/plain")" "/srv/wt/w"

#------------------------------------------------------------------------------
# Porcelain parsing
#------------------------------------------------------------------------------

describe "worktree list parsing survives spaces and extra attributes"

reset_globals
cd "$TMP/plain" || fatal "cannot enter the plain fixture"
refresh
eq "a path containing a space is not truncated" \
    "${c_worktree_path_map["refs/heads/spaced"]}" "$(cd "$TMP/with space/wt" && pwd -P)"
eq "a locked worktree is still parsed" \
    "${c_worktree_path_map["refs/heads/locked"]}" "$(cd "$TMP/plain-wt-locked" && pwd -P)"
eq "the main worktree is included" \
    "${c_worktree_path_map["refs/heads/main"]}" "$(cd "$TMP/plain" && pwd -P)"

#------------------------------------------------------------------------------
# Path display modes
#------------------------------------------------------------------------------

describe "path display modes"

reset_globals
cd "$TMP/plain" || fatal "cannot enter the plain fixture"
refresh
wt_abs="${c_worktree_path_map["refs/heads/main"]}"

c_wt_path_display=absolute
eq "absolute" "$(__fgb_format_wt_path "$wt_abs")" "$wt_abs"

c_wt_path_display=relative-gitdir
eq "relative-gitdir of the main worktree" "$(__fgb_format_wt_path "$wt_abs")" "../"

c_wt_path_display=relative-repo
eq "relative-repo of the main worktree" "$(__fgb_format_wt_path "$wt_abs")" "./"

c_wt_path_display=absolute-gitdir
eq "absolute-gitdir is the absolute path" "$(__fgb_format_wt_path "$wt_abs")" "$wt_abs"

c_wt_path_display=tilde-gitdir
eq "tilde-gitdir outside \$HOME is unchanged" "$(__fgb_format_wt_path "$wt_abs")" "$wt_abs"

# Exercised through format_wt_path, not just the helper: the tilde modes are where
# a ${path/#$HOME/~} style substitution would silently print the absolute path back.
render_as() { (
    HOME="$1"
    c_wt_path_display="$3"
    __fgb_format_wt_path "$2"
); }
eq "tilde mode collapses \$HOME" \
    "$(render_as /home/ann /home/ann/proj/wt tilde)" "~/proj/wt"
eq "tilde mode needs a path boundary" \
    "$(render_as /home/ann /home/annabel/proj tilde)" "/home/annabel/proj"
eq "tilde-gitdir collapses \$HOME" \
    "$(render_as /home/ann /home/ann/proj/wt tilde-gitdir)" "~/proj/wt"
eq "an unknown mode falls back to tilde" \
    "$(render_as /home/ann /home/ann/proj/wt bogus-mode)" "~/proj/wt"

#------------------------------------------------------------------------------
# Remote branches
#------------------------------------------------------------------------------

describe "remote branches resolve to their counterpart's worktree"

reset_globals
cd "$TMP/clone" || fatal "cannot enter the clone fixture"
refresh

owner_of() { printf '%s' "${c_remote_wt_map["$1"]##*"$c_split_char"}"; }
path_of() { printf '%s' "${c_remote_wt_map["$1"]%"$c_split_char"*}"; }

eq "a remote branch finds its counterpart's worktree" \
    "$(path_of refs/remotes/origin/linked)" "$(cd "$TMP/wt-linked" && pwd -P)"
eq "and records the owning branch" \
    "$(owner_of refs/remotes/origin/linked)" "linked"
eq "a counterpart without a worktree yields nothing" \
    "${c_remote_wt_map["refs/remotes/origin/stale"]}" ""
eq "a remote branch with no counterpart yields nothing" \
    "${c_remote_wt_map["refs/remotes/origin/orphan"]}" ""

describe "several counterparts: the tie-break cannot tie"

eq "the branch named like the remote wins" \
    "$(owner_of refs/remotes/origin/twin)" "twin"
eq "reporting that branch's worktree" \
    "$(path_of refs/remotes/origin/twin)" "$(cd "$TMP/wt-twin" && pwd -P)"

git_q -C "$TMP/clone" worktree remove --force "$TMP/wt-twin"
refresh
eq "without the name match, the alphabetically first wins" \
    "$(owner_of refs/remotes/origin/twin)" "aaa-twin"

git_q -C "$TMP/clone" worktree remove --force "$TMP/wt-aaa-twin"
refresh
eq "then the next alphabetically" "$(owner_of refs/remotes/origin/twin)" "zzz-twin"

git_q -C "$TMP/clone" worktree remove --force "$TMP/wt-zzz-twin"
refresh
eq "with none left there is no entry" "${c_remote_wt_map["refs/remotes/origin/twin"]}" ""

# Put the twins back for the listing tests below.
for b in twin aaa-twin zzz-twin; do
    git_q -C "$TMP/clone" worktree add "$TMP/wt-$b" "$b"
done
refresh

describe "selecting a remote branch jumps to that worktree"

start_pwd="$PWD"
# Not run in $(...): the function cd's, and a subshell would discard that.
__fgb_git_worktree_jump_or_add "(origin/linked)" >"$TMP/out.txt" 2>&1
out=$(cat "$TMP/out.txt")
eq "landed in the counterpart's worktree" "$PWD" "$(cd "$TMP/wt-linked" && pwd -P)"
has "reported a jump" "$out" "Jumped"
cd "$start_pwd" || fatal "cannot return to $start_pwd"

describe "a stale counterpart is reported when jumping to its worktree"

# The counterpart holds a worktree and is one commit behind its remote: selecting the
# remote row lands on that worktree, so the staleness has to be reported there too and
# not only when a worktree is about to be created.
git_q -C "$TMP/wt-linked" reset --hard "origin/linked~1"

out=$(printf 'n' | __fgb_git_worktree_jump_or_add "(origin/linked)" 2>&1)
has "jumping reports how far behind the worktree is" "$out" "1 commit behind"
has "and names the worktree that has it checked out" "$out" "has it checked out"
has "it still jumps after declining" "$out" "Jumped"
eq "declining leaves the branch stale" \
    "$(git -C "$TMP/clone" log -1 --format=%s linked)" "add base"
cd "$TMP/clone" || fatal "cannot return to the clone"

out=$(printf 'y' | __fgb_git_worktree_jump_or_add "(origin/linked)" 2>&1)
eq "accepting brings the worktree up to the remote" \
    "$(git -C "$TMP/clone" log -1 --format=%s linked)" "add linked"
cd "$TMP/clone" || fatal "cannot return to the clone"

out=$(printf 'n' | __fgb_git_worktree_jump_or_add "(origin/linked)" 2>&1)
hasnt "no prompt once it is up to date" "$out" "commit behind"
cd "$TMP/clone" || fatal "cannot return to the clone"

# Uncommitted work in that worktree would be lost, so it is listed before asking.
git_q -C "$TMP/wt-linked" reset --hard "origin/linked~1"
printf 'dirty\n' >"$TMP/wt-linked/base.txt"
printf 'new\n' >"$TMP/wt-linked/untracked.txt"
out=$(printf 'n' | __fgb_git_worktree_jump_or_add "(origin/linked)" 2>&1)
has "the prompt lists uncommitted changes" "$out" "discards these uncommitted changes"
has "including the modified file" "$out" "base.txt"
has "and the untracked file" "$out" "untracked.txt"
eq "declining keeps them" \
    "$(git -C "$TMP/wt-linked" status --short | wc -l | tr -d ' ')" "2"
cd "$TMP/clone" || fatal "cannot return to the clone"

git_q -C "$TMP/wt-linked" checkout -- .
rm -f "$TMP/wt-linked/untracked.txt"
git_q -C "$TMP/wt-linked" reset --hard origin/linked

out=$(printf 'n' | __fgb_git_worktree_jump_or_add "[linked]" 2>&1)
hasnt "no prompt for a local selection" "$out" "commit behind"
cd "$TMP/clone" || fatal "cannot return to the clone"

describe "a stale counterpart is reported before the worktree is created"

git_q -C "$TMP/clone" branch -f stale "origin/stale~1"
out=$(printf 'n' | __fgb_offer_reset_to_remote "origin/stale" "stale" 2>&1)
has "reports how far behind the branch is" "$out" "1 commit behind"
eq "declining leaves the branch alone" \
    "$(git -C "$TMP/clone" log -1 --format=%s stale)" "add base"

out=$(printf 'y' | __fgb_offer_reset_to_remote "origin/stale" "stale" 2>&1)
eq "accepting resets it to the remote" \
    "$(git -C "$TMP/clone" log -1 --format=%s stale)" "add stale"

git_q -C "$TMP/clone" branch -f stale origin/stale
out=$(printf 'y' | __fgb_offer_reset_to_remote "origin/stale" "stale" 2>&1)
eq "no prompt when the counterpart is up to date" "$out" ""

out=$(printf 'y' | __fgb_offer_reset_to_remote "origin/orphan" "orphan" 2>&1)
eq "no prompt without a local counterpart" "$out" ""

out=$(printf 'y' | __fgb_offer_reset_to_remote "" "stale" 2>&1)
eq "no prompt for a local selection" "$out" ""

describe "a counterpart that is ahead as well as behind"

git_q -C "$TMP/clone" branch -f stale "origin/stale~1"
git_q -C "$TMP/clone" worktree add "$TMP/wt-stale" stale
commit_file "$TMP/wt-stale" ahead1
git_q -C "$TMP/clone" worktree remove --force "$TMP/wt-stale"
out=$(printf 'n' | __fgb_offer_reset_to_remote "origin/stale" "stale" 2>&1)
has "warns that a reset discards local commits" "$out" "discards"
has "singular wording for one commit" "$out" "1 local commit that is not on the remote"
eq "declining keeps the local commit" \
    "$(git -C "$TMP/clone" log -1 --format=%s stale)" "add ahead1"

git_q -C "$TMP/clone" worktree add "$TMP/wt-stale" stale
commit_file "$TMP/wt-stale" ahead2
git_q -C "$TMP/clone" worktree remove --force "$TMP/wt-stale"
out=$(printf 'n' | __fgb_offer_reset_to_remote "origin/stale" "stale" 2>&1)
has "plural wording for several commits" "$out" "2 local commits that are not on the remote"

git_q -C "$TMP/clone" branch -f stale origin/stale
git_q -C "$TMP/clone" worktree add "$TMP/wt-stale" stale
commit_file "$TMP/wt-stale" onlyahead
git_q -C "$TMP/clone" worktree remove --force "$TMP/wt-stale"
out=$(printf 'y' | __fgb_offer_reset_to_remote "origin/stale" "stale" 2>&1)
eq "no prompt when only ahead" "$out" ""
eq "and the branch is untouched" \
    "$(git -C "$TMP/clone" log -1 --format=%s stale)" "add onlyahead"
git_q -C "$TMP/clone" branch -f stale "origin/stale~1"

#------------------------------------------------------------------------------
# Listing
#------------------------------------------------------------------------------

describe "the listing shows the worktree a row resolves to"

reset_globals
cd "$TMP/clone" || fatal "cannot enter the clone fixture"
refresh
c_branches=$(__fgb_git_branch_list all)
__fgb_branch_set_vars "$c_branches"
listing=$(__fgb_worktree_list)

has "a local row shows its own worktree" "$listing" "[linked]"
has "a remote row shows the counterpart's" "$listing" "(origin/linked)"
eq "the fixture does have a remote HEAD to filter" \
    "$(git -C "$TMP/clone" for-each-ref --format='%(refname)' refs/remotes/origin/HEAD)" \
    "refs/remotes/origin/HEAD"
hasnt "<remote>/HEAD is not listed" "$listing" "origin/HEAD"

remote_line=$(printf '%s\n' "$listing" | grep '(origin/linked)')
has "the remote row carries a path" "$remote_line" "$(cd "$TMP/wt-linked" && pwd -P)"
twin_line=$(printf '%s\n' "$listing" | grep '(origin/twin)')
has "the twin row uses the name match" "$twin_line" "$(cd "$TMP/wt-twin" && pwd -P)"
stale_line=$(printf '%s\n' "$listing" | grep '(origin/stale)')
hasnt "a row with no worktree stays blank" "$stale_line" "/wt-"

describe "branch info reports the resolved worktree"

info=$(__fgb_print_branch_info "linked" 2>&1)
has "a local branch reports its worktree" "$info" "$(cd "$TMP/wt-linked" && pwd -P)"
info=$(__fgb_print_branch_info "origin/linked" 2>&1)
has "a remote branch reports one too" "$info" "$(cd "$TMP/wt-linked" && pwd -P)"
hasnt "with no redundant owner suffix" "$info" "(linked)"
info=$(__fgb_print_branch_info "origin/stale" 2>&1)
hasnt "nothing to report without a worktree" "$info" "worktree"

# A local branch tracking a differently named remote branch: the owner is not
# obvious from the row, so it is named.
git_q -C "$TMP/clone" branch alias origin/orphan
git_q -C "$TMP/clone" branch --set-upstream-to=origin/orphan alias
git_q -C "$TMP/clone" worktree add "$TMP/wt-alias" alias
refresh
info=$(__fgb_print_branch_info "origin/orphan" 2>&1)
has "a borrowed worktree names the branch that owns it" "$info" "(alias)"

#------------------------------------------------------------------------------
# Public entry points
#------------------------------------------------------------------------------

describe "submodules are refused, other repositories are not"

run_fgb() {
    # Runs the real entry point in a subshell so its cd and locals do not leak.
    (
        cd "$1" || exit 1
        shift
        # shellcheck disable=SC1090
        . "$fgb_script"
        fgb "$@" 2>&1
    )
}

out=$(run_fgb "$TMP/super/sub" worktree list)
has "a submodule is refused" "$out" "is a submodule of"
has "and says worktrees are unsupported" "$out" "not supported for submodules"

out=$(run_fgb "$TMP/super" worktree list)
hasnt "the superproject is not refused" "$out" "is a submodule of"

out=$(run_fgb "$TMP/plain" worktree list)
hasnt "an ordinary repo is not refused" "$out" "is a submodule of"

out=$(run_fgb "$TMP/hub.git" worktree list)
hasnt "a bare repo is not refused" "$out" "is a submodule of"

describe "the confirmation dialog acts on a single keypress"

# Every prompt is meant to act the moment a key is pressed, with no Enter. That only
# happens on a real terminal, so this needs a pty; python3 supplies one when present.
# The suite's own answers arrive down a pipe, which exercises the other branch, so
# without this the terminal path would go untested - which is how it once regressed.
if python3 -c 'import pty' >/dev/null 2>&1; then
    cat >"$TMP/dialog.sh" <<DIALOG
. "$TMP/funcs.sh"
if __fgb_confirmation_dialog "Proceed?"; then echo "ANSWER=yes"; else echo "ANSWER=no"; fi
if read -r -t 1 _rest; then echo "BUFFER=leftover"; else echo "BUFFER=empty"; fi
echo "DONE-MARKER"
DIALOG

    cat >"$TMP/keypress.py" <<'PTYDRIVER'
import os, pty, select, sys, time
shell, script, keys = sys.argv[1], sys.argv[2], sys.argv[3].encode()
pid, fd = pty.fork()
if pid == 0:
    os.execvp(shell, [shell, script])
time.sleep(0.5)
os.write(fd, keys)
out, deadline = b"", time.time() + 5.0
while time.time() < deadline and b"DONE-MARKER" not in out:
    r, _, _ = select.select([fd], [], [], 0.3)
    if not r:
        continue
    try:
        chunk = os.read(fd, 4096)
    except OSError:
        break
    if not chunk:
        break
    out += chunk
try:
    os.kill(pid, 9)
except OSError:
    pass
os.waitpid(pid, 0)
sys.stdout.write(out.decode(errors="replace").replace("\r", ""))
PTYDRIVER

    keypress=$(python3 "$TMP/keypress.py" "$current_shell" "$TMP/dialog.sh" y)
    has "a bare y is accepted, no Enter needed" "$keypress" "ANSWER=yes"
    has "and leaves nothing in the input buffer" "$keypress" "BUFFER=empty"

    keypress=$(python3 "$TMP/keypress.py" "$current_shell" "$TMP/dialog.sh" n)
    has "a bare n is declined, no Enter needed" "$keypress" "ANSWER=no"

    keypress=$(python3 "$TMP/keypress.py" "$current_shell" "$TMP/dialog.sh" Y)
    has "an uppercase Y is accepted" "$keypress" "ANSWER=yes"
else
    printf '  skip a working python3 is needed to allocate a terminal for these checks\n'
fi

describe "nothing leaks into the calling shell"

# Run in a pristine shell, not a subshell: this suite defines c_* globals of its
# own, and a subshell would inherit them and report them as leaks.
cat >"$TMP/leakcheck.sh" <<'LEAKCHECK'
cd "$1" || exit 1
# shellcheck disable=SC1090
. "$2"
fgb worktree list >/dev/null 2>&1
printf '%s|%s' \
    "$(typeset -f 2>/dev/null | grep -c '^__fgb_')" \
    "$(set 2>/dev/null \
        | grep -E '^(c_[a-z_]+|wt_abs|repo_name|extracted|dates_data)=' \
        | cut -d= -f1 | tr '\n' ' ')"
LEAKCHECK
leaks=$("$current_shell" "$TMP/leakcheck.sh" "$TMP/plain" "$fgb_script")
eq "no functions survive" "${leaks%%|*}" "0"
eq "no variables survive" "${leaks#*|}" ""

#------------------------------------------------------------------------------
# Report
#------------------------------------------------------------------------------

printf '\n'
if [[ "$failed" -eq 0 ]]; then
    printf 'All %s checks passed.\n' "$passed"
    exit 0
fi
printf '%s passed, %s FAILED.\n' "$passed" "$failed"
exit 1
