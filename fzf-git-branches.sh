# Description: Manage Git branches and worktrees with fzf
# shellcheck shell=bash # sourced by bash and zsh; zsh-only code is guarded

command -v fzf >/dev/null 2>&1 || return

fgb() {
    local VERSION="0.23.3"

    # Set the command to use for fzf
    local fzf_version
    fzf_version="$(fzf --version | awk -F. '{ print $1 * 1e6 + $2 * 1e3 + $3 }')"
    local fzf_min_version=16001

    local FZF_ARGS_GLOB="\
            --ansi \
            --bind=ctrl-y:accept,ctrl-t:toggle+down \
            --border=top \
            --cycle \
            --multi \
            --pointer='' \
            --preview 'FGB_BRANCH={1}; \
                git log --oneline --decorate --graph --color=always \${FGB_BRANCH:1:-1}' \
        "
    FZF_ARGS_GLOB="${FGB_FZF_OPTS:-"$FZF_ARGS_GLOB"}"
    local FZF_CMD_GLOB
    if [[ $fzf_version -gt $fzf_min_version ]]; then
        FZF_CMD_GLOB="fzf --height 80% --reverse $FZF_ARGS_GLOB"
    elif [[ ${FZF_TMUX:-1} -eq 1 ]]; then
        FZF_CMD_GLOB="fzf-tmux -d${FZF_TMUX_HEIGHT:-40%}"
    else
        FZF_CMD_GLOB="fzf $FZF_ARGS_GLOB"
    fi

    __fgb__functions() {
        __fgb_confirmation_dialog() {
            # Confirmation dialog with a single 'y' character to accept

            local user_prompt="${1:-Are you sure?}"
            echo -en "$user_prompt (y|N): "

            local ANS
            if [[ -n "${ZSH_VERSION-}" ]]; then
                if [[ -t 0 ]]; then
                    # zsh's `read -k` puts the terminal into raw mode and returns on the
                    # first keypress, with no Enter needed. Passing -u here instead would
                    # read fd 0 line-buffered, so the answer would need confirming with
                    # Enter and that newline would be left behind for the shell to eat.
                    read -rk 1 ANS
                else
                    # Not a terminal, so there is no raw mode to enter: take the character
                    # from standard input, which `read -k` alone would ignore in favour of
                    # the tty. Keeps a piped or redirected answer working, as in bash.
                    read -rk 1 -u 0 ANS
                fi
            else
                read -rn 1 ANS
            fi
            echo # Move to the next line for a cleaner output

            case "$ANS" in
                [yY]) return 0 ;;
                *) return 1 ;;
            esac
        }

        __fgb_stdout_unindented() {
            # Print a string to stdout unindented

            # Usage: $0 "string"
            # String supposed to be indented with any number of any characters.
            # The first `|' character in the string will be treated as the start of the string.
            # The first and last lines of the string will be removed because they must be empty and
            # exist since a quoted literal starts with a new line after the opening quote and ends
            # with a new line before the closing quote, like this:

            # string="
            #     |line 1
            #     |line 2
            # "

            # source: https://unix.stackexchange.com/a/674903/424165

            # Concatenate lines that end with \# (backslash followed by a hash character) and then
            # remove indentation.
            # Uses awk instead of `sed -z` for BSD/macOS sed compatibility.
            local _joined
            _joined="$(awk '
                {
                    line = $0
                    while (line ~ /\\#$/) {
                        if ((getline next_line) <= 0) break
                        sub(/^[^|]*\|/, "", next_line)
                        line = substr(line, 1, length(line) - 2) next_line
                    }
                    print line
                }
            ' <<<"$1")"
            sed '1d;s/^[^|]*|//;$d' <<<"$_joined"
        }

        __fgb_git_branch_delete() {
            # Delete a Git branch

            if [[ -z "$1" ]]; then
                echo "$0: Missing argument: list of branches to delete" >&2
                return 1
            fi

            local \
                branch \
                branch_name \
                branches_to_delete="$1" \
                error_pattern \
                is_remote \
                local_branches \
                local_tracking \
                output \
                remote_name \
                remote_tracking \
                return_code \
                upstream \
                user_prompt \
                line

            local -a array_of_lines

            while IFS= read -r line; do
                array_of_lines+=("$line")
            done <<<"$branches_to_delete"
            for branch_name in "${array_of_lines[@]}"; do
                branch=""
                is_remote=false
                local_branches=""
                local_tracking=""
                output=""
                remote_name=""
                remote_tracking=""
                upstream=""

                # shellcheck disable=SC2053
                if [[ "$branch_name" == "$c_bracket_rem_open"*/*"$c_bracket_rem_close" ]]; then
                    is_remote=true
                    # Remove the first and the last characters (brackets)
                    branch_name="${branch_name:1}"
                    branch_name="${branch_name%?}"
                    # Remove everything after the first slash
                    remote_name="${branch_name%%/*}"
                    # Remove the first segment of the reference name (<upstream>/)
                    branch_name="${branch_name#*/}"
                elif [[ "$branch_name" == "$c_bracket_loc_open"*"$c_bracket_loc_close" ]]; then
                    # Remove the first and the last characters (brackets)
                    branch_name="${branch_name:1}"
                    branch_name="${branch_name%?}"
                else
                    echo "error: invalid branch name pattern: $branch_name" >&2
                    return 1
                fi

                if [[ "$c_extend_del" == true ]]; then
                    if [[ "$is_remote" == true ]]; then
                        # Find local branch that tracks the selected remote branch
                        local_branches="$(__fgb_git_branch_list "local")"
                        return_code=$?
                        [[ $return_code -ne 0 ]] && return "$return_code"
                        remote_tracking="refs/remotes/${branch_name}"
                        while IFS= read -r branch; do
                            upstream="$(
                                git \
                                    for-each-ref \
                                    --format \
                                    '%(upstream)' "$branch"
                            )"
                            if [[ "$remote_tracking" == "$upstream" ]]; then
                                local_tracking="$branch"
                                break
                            fi
                        done <<<"$(cut -d"${c_split_char}" -f1 <<<"$local_branches")"
                    else
                        # Find upstream branch for the selected local branch
                        local_tracking="$branch_name"
                        remote_tracking="$(
                            git for-each-ref --format '%(upstream)' "refs/heads/$branch_name"
                        )"
                    fi
                fi

                if [[ "$is_remote" == true ]]; then
                    branch_name="${branch_name#remotes/*/}"
                    user_prompt=$(__fgb_stdout_unindented "
                        |${col_r_bold}WARNING:${col_reset} \#
                        |Delete branch: '${col_b_bold}${branch_name}${col_reset}' \#
                        |from remote: ${col_y_bold}${remote_name}${col_reset}?
                    ")
                    # NOTE: Avoid --force here as it's an irreversible operation for remote branches
                    if __fgb_confirmation_dialog "$user_prompt"; then
                        git push --delete "$remote_name" "$branch_name" || return $?
                        if [[ "$c_extend_del" == true ]] && [[ -n "$local_tracking" ]]; then
                            branch="$c_bracket_loc_open"
                            branch+="${local_tracking#refs/heads/}"
                            branch+="$c_bracket_loc_close"
                            c_extend_del=false
                            __fgb_git_branch_delete "$branch"
                            c_extend_del=true
                        fi
                    fi
                else
                    user_prompt=$(__fgb_stdout_unindented "
                        |${col_r_bold}Delete${col_reset} \#
                        |local branch: \`${col_b_bold}${branch_name}${col_reset}'?
                    ")
                    local branch_deleted=false
                    if [[ "$c_force" == true ]] || __fgb_confirmation_dialog "$user_prompt"; then
                        if ! output="$(git branch -d "$branch_name" 2>&1)"; then
                            local head_branch
                            head_branch="$(git rev-parse --abbrev-ref HEAD)"
                            error_pattern="^error: the branch '$branch_name' is not fully merged\.\?$"
                            if ! grep -q "$error_pattern" <<<"$output"; then
                                echo "$output"
                                continue
                            fi
                            user_prompt=$(__fgb_stdout_unindented "
                                |
                                |${col_r_bold}WARNING:${col_reset} \#
                                |The branch '${col_b_bold}${branch_name}${col_reset}' \#
                                |is not yet merged into the \#
                                |'${col_g_bold}${head_branch}${col_reset}' branch.
                                |
                                |Are you sure you want to delete it?
                            ")
                            # NOTE: Avoid --force here
                            # as it's not clear if intended for non-merged branches
                            if __fgb_confirmation_dialog "$user_prompt"; then
                                git branch -D "$branch_name" && branch_deleted=true
                            fi
                        else
                            echo "$output"
                            branch_deleted=true
                        fi
                    fi
                    if [[ "$branch_deleted" == true ]] &&
                        [[ "$c_extend_del" == true ]] &&
                        [[ -n "$remote_tracking" ]]; then
                        branch="$c_bracket_rem_open"
                        branch+="${remote_tracking#refs/remotes/}"
                        branch+="$c_bracket_rem_close"
                        c_extend_del=false
                        __fgb_git_branch_delete "$branch"
                        c_extend_del=true
                    fi
                fi
            done
        }

        __fgb_git_branch_list() {
            # List branches in a git repository

            # shellcheck disable=SC2076
            if [[ $# -lt 1 ]]; then
                echo "$0 error: missing argument: branch_type (local|remote|all)" >&2
                return 1
            elif [[ ! " local remote all " =~ " $1 " ]]; then
                echo "$0 error: invalid argument: \`$1'" >&2
                return 1
            fi

            local branch_type="$1"
            local filter_list="${2-}"

            local -a ref_types=()
            [[ "$branch_type" == "local" ]] && ref_types=("heads")
            [[ "$branch_type" == "remote" ]] && ref_types=("remotes")
            [[ "$branch_type" == "all" ]] && ref_types=("heads" "remotes")

            local ref_type refs return_code line git_fmt
            git_fmt="%(refname)${c_split_char}${c_author_format}${c_split_char}${c_date_format}"
            local -a git_cmd=(git for-each-ref "--format=${git_fmt}")
            while IFS= read -r line; do
                git_cmd+=("--sort=${line}")
            done < <(tr ',' '\n' <<<"$c_branch_sort_order")
            for ref_type in "${ref_types[@]}"; do
                refs=$("${git_cmd[@]}" "refs/$ref_type")
                return_code=$?
                [[ $return_code -ne 0 ]] && return "$return_code"
                if [[ "$ref_type" == "remotes" ]]; then
                    # <remote>/HEAD is a symbolic ref pointing at another branch, not a
                    # branch of its own. Selecting it would run
                    # `git worktree add <path> HEAD` and silently create a detached
                    # worktree.
                    refs="$(
                        awk -F"$c_split_char" \
                            '$1 !~ /^refs\/remotes\/[^\/]+\/HEAD$/' <<<"$refs"
                    )"
                fi
                if [[ -n "$filter_list" ]]; then
                    # Compare the refname field exactly. Building a grep pattern out of
                    # branch names treats them as regexes, so a branch such as "feat.x"
                    # would also match "featqx" and could filter out the wrong ref.
                    # Passed through the environment rather than -v: awk rejects a
                    # literal newline in a -v assignment, and the list is multi-line.
                    FGB_FILTER_LIST="$filter_list" awk -F"$c_split_char" '
                        BEGIN {
                            n = split(ENVIRON["FGB_FILTER_LIST"], wanted, "\n")
                            for (i = 1; i <= n; i++) keep[wanted[i]] = 1
                        }
                        keep[$1]
                    ' <<<"$refs"
                else
                    echo "$refs"
                fi
            done
        }

        __fgb_branch_set_vars() {
            # Define branch related variables

            if [[ $# -ne 1 ]]; then
                echo "error: missing argument: branch list" >&2
                return 41
            fi

            local branch_list="$1"
            local \
                line \
                branch \
                branch_name \
                branch_curr_width \
                author_name \
                author_curr_width \
                date_curr_width
            while IFS= read -r line; do
                # Remove the longest suffix starting with unit delimeter char
                branch="${line%%"$c_split_char"*}"
                branch_name="$branch"
                # Remove first two segments of the reference name
                branch_name="${branch_name#*/}"
                branch_name="${branch_name#*/}"
                # Remove the shortest prefix ending with unit delimeter char
                author_name="${line#*"$c_split_char"}"
                # Remove the shortest suffix starting with unit delimeter char
                author_name="${author_name%"$c_split_char"*}"
                c_branch_author_map["$branch"]="$author_name"
                # Remove the longest prefix ending with unit delimeter char
                c_branch_date_map["$branch"]="${line##*"$c_split_char"}"
                date_curr_width="${#c_branch_date_map["$branch"]}"
                c_date_width="$((\
                    date_curr_width > c_date_width ? \
                    date_curr_width : \
                    c_date_width))"
                # Calculate column widths
                branch_curr_width="${#branch_name}"
                c_branch_width="$((\
                    branch_curr_width > c_branch_width ? \
                    branch_curr_width : \
                    c_branch_width))"
                # Trim long author names with multiple parts delimited by '/'
                author_curr_width="${#author_name}"
                if [[ "$author_curr_width" -gt 25 && "$author_name" == *"/"* ]]; then
                    author_name=".../${author_name#*/}"
                    c_branch_author_map["$branch"]="$author_name"
                    author_curr_width="${#author_name}"
                fi

                c_author_width="$((\
                    author_curr_width > c_author_width ? \
                    author_curr_width : \
                    c_author_width))"
            done <<<"$branch_list"
        }

        __fgb_branch_list() {
            # List branches in a git repository

            local branch branch_name author_name author_date bracket_open bracket_close
            while IFS= read -r branch; do
                branch="${branch%%"$c_split_char"*}"
                branch_name="$branch"
                if [[ "$branch" == refs/heads/* ]]; then
                    # Define the bracket characters
                    bracket_open="$c_bracket_loc_open" bracket_close="$c_bracket_loc_close"
                elif [[ "$branch" == refs/remotes/* ]]; then
                    # Define the bracket characters
                    bracket_open="$c_bracket_rem_open" bracket_close="$c_bracket_rem_close"
                fi
                # Remove first two segments of the reference name
                branch_name="${branch_name#*/}"
                branch_name="${branch_name#*/}"
                # Adjust the branch name column width based on the number of color code characters
                printf \
                    "%-$((c_branch_width + 13))b" \
                    "${bracket_open}${col_y_bold}${branch_name}${col_reset}${bracket_close}"
                if [[ "$c_show_author" == true ]]; then
                    author_name="${c_branch_author_map["$branch"]}"
                    printf \
                        "%${c_spacer}s${col_g}%-${c_author_width}s${col_reset}" " " "$author_name"
                fi
                if [[ "$c_show_date" == true ]]; then
                    author_date="${c_branch_date_map["$branch"]}"
                    printf "%${c_spacer}s(${col_b}%s${col_reset})" " " "$author_date"
                fi
                echo
            done <<<"$c_branches"
        }

        __fgb_set_spacer_var() {
            # Set spacer variables for branch/worktree list subcommands

            local list_type="${1:-branch}"
            # shellcheck disable=SC2076
            if [[ ! " branch worktree " =~ " $list_type " ]]; then
                echo "$0 error: invalid argument: \`$list_type'" >&2
                return 1
            fi

            local num_spacers
            if [[ $list_type == "branch" ]]; then
                # Add 5 to avoid truncating the date column
                c_total_width="$((c_branch_width + c_author_width + c_date_width + 5))"

                if [[ "$c_total_width" -gt "$WIDTH_OF_WINDOW" ]]; then
                    c_show_author=false
                    c_total_width="$((c_total_width - c_author_width))"
                fi

                if [[ "$c_total_width" -gt "$WIDTH_OF_WINDOW" ]]; then
                    c_show_date=false
                    c_total_width="$((c_total_width - c_date_width))"
                fi

                # Calculate spacers
                num_spacers=2
                c_spacer="$(
                    echo "$WIDTH_OF_WINDOW $c_total_width $num_spacers" |
                        awk '{printf("%.0f", ($1 - $2) / $3)}'
                )"
                [[ "$c_spacer" -le 0 ]] && c_spacer=1 || c_spacer=$((c_spacer < 4 ? c_spacer : 4))
            elif [[ $list_type == "worktree" ]]; then
                # Add 5 to avoid truncating the date column
                c_total_width="$((\
                    c_branch_width + c_wt_path_width + c_author_width + c_date_width + 5))"

                if [[ "$c_total_width" -gt "$WIDTH_OF_WINDOW" ]]; then
                    c_show_wt_path=false
                    c_show_wt_flag=true
                    c_total_width="$((c_total_width - c_wt_path_width + 1))"
                fi

                if [[ "$c_total_width" -gt "$WIDTH_OF_WINDOW" ]]; then
                    c_show_author=false
                    c_total_width="$((c_total_width - c_author_width))"
                fi

                if [[ "$c_total_width" -gt "$WIDTH_OF_WINDOW" ]]; then
                    c_show_date=false
                    c_total_width="$((c_total_width - c_date_width))"
                fi

                # Calculate spacers
                num_spacers=3
                if [[ "$c_show_wt_flag" == true ]]; then
                    num_spacers="$((num_spacers + 1))"
                    c_total_width="$((c_total_width + 2))"
                fi
                c_spacer="$(
                    echo "$WIDTH_OF_WINDOW $c_total_width $num_spacers" |
                        awk '{printf("%.0f", ($1 - $2) / $3)}'
                )"
                [[ "$c_spacer" -le 0 ]] && c_spacer=1 || c_spacer=$((c_spacer < 4 ? c_spacer : 4))
            fi
        }

        __fgb_print_branch_info() {
            # Pring branch information

            if [[ $# -lt 1 ]]; then
                echo "$0 error: missing argument: branch_name" >&2
                return 1
            fi

            local branch="$1"

            # A remote row has no worktree of its own; it resolves to the worktree of a
            # local branch tracking it. Name that branch when it is not simply the remote
            # branch without its remote prefix, since the path alone cannot say which
            # branch is checked out there.
            local wt_display="${c_worktree_path_map["refs/heads/${branch}"]}"
            if [[ -z "$wt_display" ]] && git show-ref --verify --quiet "refs/remotes/${branch}"; then
                local own_name="${branch#*/}" owner
                local counterpart="${c_remote_wt_map["refs/remotes/${branch}"]}"
                if [[ -n "$counterpart" ]]; then
                    wt_display="${counterpart%"$c_split_char"*}"
                    owner="${counterpart##*"$c_split_char"}"
                    [[ "$owner" != "$own_name" ]] && wt_display+=" ($owner)"
                fi
            fi

            local -A values=(
                ["1.branch"]="$branch"
                ["2.worktree"]="$wt_display"
                ["3.author"]="$(git log -1 --pretty=format:"%an <%ae>" "$branch" --)"
                ["4.authordate"]="$(git log -1 --format="%ad" --date=iso "$branch" --)"
                ["5.committer"]="$(git log -1 --pretty=format:"%cn <%ce>" "$branch" --)"
                ["6.committerdate"]="$(git log -1 --format="%cd" --date=iso "$branch" --)"
                ["7.HEAD"]="$(git rev-parse --verify "$branch")"
                ["8.message"]="$(git log -1 --format="%B" "$branch" --)"
            )

            local -A colors=(
                ["1.branch"]="$col_y_bold"
                ["2.worktree"]="$col_bold"
                ["3.author"]="$col_g"
                ["4.authordate"]="$col_b"
                ["5.committer"]="$col_g"
                ["6.committerdate"]="$col_b"
                ["7.HEAD"]="$col_m"
                ["8.message"]="$col_y"
            )

            local -a keys=()
            local line key
            if [[ -n "${ZSH_VERSION-}" ]]; then
                # zsh-only syntax stays inside a fixed eval string so that bash-based
                # tools (shfmt, shellcheck) can still parse this file
                while IFS=$'\n' read -r line; do
                    keys+=("$line")
                done <<<"$(eval 'for key in "${(@k)values}"; do echo "$key"; done' | sort -n)"
            else
                while IFS=$'\n' read -r line; do
                    keys+=("$line")
                done <<<"$(for key in "${!values[@]}"; do echo "$key"; done | sort -n)"
            fi

            local key_width max_width=0
            for key in "${keys[@]}"; do
                # Remove N. from the key
                key="${key:2}"
                key_width="${#key}"
                max_width="$((key_width > max_width ? key_width : max_width))"
            done

            local message_indent_width message_indent_str
            message_indent_width="$((max_width + 3))"
            message_indent_str=$(printf "%${message_indent_width}s")

            for key in "${keys[@]}"; do
                [[ -n "${values[$key]}" ]] &&
                    printf "%-${max_width}s : ${colors[$key]}%s${col_reset}\n" \
                        "${key:2}" "${values[$key]}" | sed "3,\$s/^/${message_indent_str}/"
            done
        }

        __fgb_git_branch_new() {
            # Create a fork from the selected branch

            if [[ $# -eq 0 ]]; then
                echo "$0 error: missing arguments: branch_name, branch_type" >&2
                return 1
            elif [[ $# -lt 2 ]]; then
                echo "$0 error: missing argument: branch_type" >&2
                return 1
            fi

            local branch_name="$1"
            local branch_type="$2"
            local for_new_worktree="${3:-false}"

            echo -e "Fork the branch \`${col_b_bold}${branch_name}${col_reset}' and switch to it."
            local message="Enter a name for the new branch:"
            local new_branch="$branch_name"
            if [[ "$branch_type" == "remote" ]]; then
                new_branch="${new_branch#*/}"
            fi
            new_branch+="-fork"
            if [[ -n "${ZSH_VERSION-}" ]]; then
                vared -p "$message " new_branch
            else
                echo -en "${message}${col_r}"
                IFS= read -re -p " " -i "$new_branch" new_branch
                echo -en "$col_reset"
            fi

            # An emptied or malformed entry would otherwise reach git and fail with a
            # message that does not say which name was rejected.
            if [[ -z "$new_branch" ]]; then
                echo "fgb: empty branch name, aborting" >&2
                return 1
            fi
            if ! git check-ref-format --branch "$new_branch" &>/dev/null; then
                echo "fgb: not a valid branch name: \`$new_branch'" >&2
                return 1
            fi

            local return_code
            if "$for_new_worktree"; then
                git branch "$new_branch" "$branch_name"
                return_code=$?
            else
                git switch -c "$new_branch" "$branch_name" >/dev/null
                return_code=$?
            fi
            [[ $return_code -eq 0 ]] &&
                c_new_branch="${c_bracket_loc_open}${new_branch}${c_bracket_loc_close}"
        }

        __fgb_branch_manage() {
            # Manage Git branches

            local \
                spacer_branch=" " \
                spacer_authour=" " \
                header_column_names_row

            spacer_branch="$(
                printf "%$((c_branch_width + 2 - ${#c_column_branch} + c_spacer))s" " "
            )"
            spacer_authour="$(printf "%$((c_author_width - ${#c_column_author} + c_spacer))s" " ")"

            header_column_names_row="${c_column_branch}${spacer_branch}"
            [[ "$c_show_author" == true ]] &&
                header_column_names_row+="${c_column_author}${spacer_authour}"
            [[ "$c_show_date" == true ]] && header_column_names_row+="$c_column_date"

            local header="Manage Git Branches:"
            header+=" ${c_del_key}:del, ${c_extend_del_key}:extended-del, ${c_info_key}:info"
            header+=", ${c_new_branch_key}:fork"
            [[ -n "$c_bind_keys" ]] && header+=", $c_bind_keys"
            header+=$(__fgb_stdout_unindented "
                |
                |$header_column_names_row
            ")
            local fzf_cmd
            fzf_cmd="\
                $FZF_CMD_GLOB \
                    --expect=$(printf '%q' "$c_del_key,$c_extend_del_key,$c_info_key,$c_new_branch_key") \
                    --header $(printf '%q' "$header") \
                "

            [[ $# -gt 0 ]] && fzf_cmd+=" --query=$(printf '%q' "$*")"

            local lines
            lines="$(__fgb_branch_list | eval "$fzf_cmd" | cut -d' ' -f1)"

            [[ -z "$lines" ]] && return

            local key
            key="$(head -1 <<<"$lines")"

            local is_remote=false

            local branch
            branch="$(tail -1 <<<"$lines")"
            # shellcheck disable=SC2053
            if [[ "$branch" == "$c_bracket_rem_open"*/*"$c_bracket_rem_close" ]]; then
                is_remote=true
            elif [[ "$branch" != "$c_bracket_loc_open"*"$c_bracket_loc_close" ]]; then
                echo "error: invalid branch name pattern: $branch" >&2
                return 1
            fi

            local branch_type=""
            case "${branch:0:1}" in
                "$c_bracket_loc_open") branch_type="local" ;;
                "$c_bracket_rem_open") branch_type="remote" ;;
            esac

            # Remove the first and the last characters (brackets)
            branch="${branch:1:-1}"
            case $key in
                "$c_del_key") __fgb_git_branch_delete "$(sed 1d <<<"$lines")" ;;
                "$c_extend_del_key")
                    c_extend_del=true
                    __fgb_git_branch_delete "$(sed 1d <<<"$lines")"
                    ;;
                "$c_info_key")
                    __fgb_print_branch_info "$branch"
                    ;;
                "$c_new_branch_key")
                    __fgb_git_branch_new "$branch" "$branch_type"
                    ;;
                *)
                    if ! git rev-parse --show-toplevel &>/dev/null; then
                        echo "Not inside a Git worktree. Exit..." >&2
                        return 128
                    fi

                    # Remove the first segment of the remote reference name (<upstream>/)
                    [[ "$is_remote" == true ]] && branch="${branch#*/}"
                    git switch "$branch"
                    ;;
            esac
        }

        __fgb_transform_git_format_string() {
            # Enclose the Git format string into %( ... ) brackets if needed

            if [[ $# -ne 1 ]]; then
                echo "$0 error: missing argument: input Git format string" >&2
                return 1
            fi

            local input_string="$1"
            if [[ "$input_string" =~ %\\([^\)]*[a-zA-Z0-9_]+[^\)]*\\) ]]; then
                printf "%s" "$input_string"
            else
                printf "%%(%s)" "$input_string"
            fi
        }

        __fgb_convert_git_format_string() {
            # Convert the Git format string compatible with for-each-ref command to the one
            # compatible with log command

            if [[ $# -ne 1 ]]; then
                echo "$0 error: missing argument: input Git format string" >&2
                return 1
            fi

            local input_string="$1"

            # Perform substitutions
            input_string="${input_string//\%\(authorname\)/%an}"
            input_string="${input_string//\%\(authoremail\)/<%ae>}"
            input_string="${input_string//\%\(committername\)/%cn}"
            input_string="${input_string//\%\(committeremail\)/<%ce>}"

            local date_formats="relative|local|default|iso|iso-strict|rfc|short|raw|"
            date_formats+="relative-local|default-local|iso-local|iso-strict-local|"
            date_formats+="rfc-local|short-local|raw-local"

            local regexp="%\((authordate|committerdate):(format:[^)]+|$date_formats)\)"

            input_string="$(sed -E "s/$regexp/%(\1)/g" <<<"$input_string")"
            input_string="${input_string//\%\(authordate\)/"$c_split_char"%ad"$c_split_char"}"
            input_string="${input_string//\%\(committerdate\)/"$c_split_char"%cd"$c_split_char"}"

            echo "$input_string"
        }

        __fgb_extract_date_format() {
            # Extract the date format from the Git for-each-ref compatible foramt string

            if [[ $# -ne 1 ]]; then
                echo "$0 error: missing argument: input Git format string" >&2
                return 1
            fi

            local input_string="$1"

            local date_formats="relative|local|default|iso|iso-strict|rfc|short|raw|"
            date_formats+="relative-local|default-local|iso-local|iso-strict-local|"
            date_formats+="rfc-local|short-local|raw-local"

            local regexp="%\((authordate|committerdate):(format:[^)]+|$date_formats)\)"

            local extracted
            extracted="$(grep -oE "$regexp" <<<"$input_string")"

            if [[ -n "$extracted" ]]; then
                sed -E "s/$regexp/%\1$c_split_char\2/" <<<"$extracted" |
                    sed 's/authordate/ad/;s/committerdate/cd/'
            fi
        }

        __fgb_branch() {
            # Manage Git branches

            local subcommand="$1"
            shift

            case $subcommand in
                list | manage)
                    if ! git rev-parse --git-dir &>/dev/null; then
                        echo "Not inside a Git repository. Exit..." >&2
                        return 128
                    fi

                    local -a fzf_query=()
                    local branch_show_remote=false branch_show_all=false
                    while [[ $# -gt 0 ]]; do
                        case "$1" in
                            -s | --sort)
                                shift
                                c_branch_sort_order="$1"
                                ;;
                            --sort=*)
                                c_branch_sort_order="${1#*=}"
                                ;;
                            -d | --date-format)
                                shift
                                c_date_format="$1"
                                ;;
                            --date-format=*)
                                c_date_format="${1#*=}"
                                ;;
                            -u | --author-format)
                                shift
                                c_author_format="$1"
                                ;;
                            --author-format=*)
                                c_author_format="${1#*=}"
                                ;;
                            -r | --remotes)
                                branch_show_remote=true
                                ;;
                            -a | --all)
                                branch_show_all=true
                                ;;
                            -f | --force)
                                if [[ "$subcommand" == "list" ]]; then
                                    echo "error: unknown option: \`$1'" >&2
                                    echo "${usage_message[branch_$subcommand]}" >&2
                                    return 1
                                fi
                                c_force=true
                                ;;
                            -h | --help)
                                echo "${usage_message[branch_$subcommand]}"
                                return 0
                                ;;
                            --)
                                if [[ "$subcommand" == "list" ]]; then
                                    echo "error: unknown option: \`$1'" >&2
                                    echo "       query not expected for the list command." >&2
                                    echo "${usage_message[branch_$subcommand]}" >&2
                                    return 1
                                fi
                                while [[ $# -gt 1 ]]; do
                                    shift
                                    fzf_query+=("$1")
                                done
                                break
                                ;;
                            --* | -*)
                                echo "error: unknown option: \`$1'" >&2
                                echo "${usage_message[branch_$subcommand]}" >&2
                                return 1
                                ;;
                            *)
                                if [[ "$subcommand" == "list" ]]; then
                                    echo "error: unknown option: \`$1'" >&2
                                    echo "       query not expected for the list command." >&2
                                    echo "${usage_message[branch_$subcommand]}" >&2
                                    return 1
                                fi
                                fzf_query+=("$1")
                                ;;
                        esac
                        shift
                    done

                    c_date_format="$(__fgb_transform_git_format_string "$c_date_format")"
                    c_author_format="$(__fgb_transform_git_format_string "$c_author_format")"

                    local branch_type
                    [[ "$branch_show_remote" == true ]] &&
                        branch_type="remote" ||
                        branch_type="local"
                    [[ "$branch_show_all" == true ]] && branch_type="all"

                    local return_code
                    c_branches="$(__fgb_git_branch_list "$branch_type")"
                    return_code=$?
                    [[ $return_code -ne 0 ]] && return "$return_code"
                    __fgb_branch_set_vars "$c_branches"
                    __fgb_set_spacer_var "branch"
                    case $subcommand in
                        list) __fgb_branch_list ;;
                        manage) __fgb_branch_manage "${fzf_query[@]}" ;;
                    esac
                    ;;
                -h | --help)
                    echo "${usage_message[branch]}"
                    ;;
                --* | -*)
                    echo "error: unknown option: \`$subcommand'" >&2
                    echo "${usage_message[branch]}" >&2
                    return 1
                    ;;
                *)
                    echo "error: unknown subcommand: \`$subcommand'" >&2
                    echo "${usage_message[branch]}" >&2
                    return 1
                    ;;
            esac
        }

        __fgb_git_worktree_delete() {
            # Delete a Git worktree for a given branch

            if [[ -z "$1" ]]; then
                echo "$0: Missing argument: list of branches" >&2
                return 1
            fi

            local \
                force_bak="$c_force" \
                branch_name \
                error_pattern \
                is_in_target_wt=false \
                orig_pwd="" \
                is_remote \
                output \
                success_message \
                user_prompt \
                worktrees_to_delete="$1" \
                wt_path \
                line

            local -a array_of_lines

            while IFS= read -r line; do
                array_of_lines+=("$line")
            done <<<"$worktrees_to_delete"
            for branch_name in "${array_of_lines[@]}"; do
                is_remote=false
                wt_path=""
                # shellcheck disable=SC2053
                if [[ "$branch_name" == "$c_bracket_rem_open"*/*"$c_bracket_rem_close" ]]; then
                    is_remote=true
                elif [[ "$branch_name" != "$c_bracket_loc_open"*"$c_bracket_loc_close" ]]; then
                    echo "error: invalid branch name pattern: $branch_name" >&2
                    return 1
                fi
                # Remove the first and the last characters (brackets)
                branch_name="${branch_name:1}"
                branch_name="${branch_name%?}"
                [[ ! "$is_remote" == true ]] &&
                    wt_path="${c_worktree_path_map["refs/heads/${branch_name}"]}"
                if [[ -n "$wt_path" ]]; then
                    # Process a branch with a corresponding worktree
                    is_in_target_wt=false
                    # Compare on a path-component boundary: the cwd may be a subdirectory
                    # of the worktree, and "$wt_path" alone would also match the unrelated
                    # sibling "${wt_path}_old".
                    if [[ "$PWD" == "$wt_path" || "$PWD" == "$wt_path"/* ]]; then
                        orig_pwd="$PWD"
                        cd "$c_git_root_path" && is_in_target_wt=true || return 1
                    fi
                    user_prompt=$(__fgb_stdout_unindented "
                        |${col_r_bold}Delete${col_reset} worktree: \#
                        |${col_y_bold}${wt_path}${col_reset}, \#
                        |for branch '${col_b_bold}${branch_name}${col_reset}'?
                    ")
                    if [[ "$c_force" == true ]] || __fgb_confirmation_dialog "$user_prompt"; then
                        success_message=$(__fgb_stdout_unindented "
                            |${col_g_bold}Deleted${col_reset} worktree: \#
                            |${col_y_bold}${wt_path}${col_reset} \#
                            |for branch '${col_b_bold}${branch_name}${col_reset}'
                        ")
                        if ! output="$(git worktree remove "$wt_path" 2>&1)"; then
                            error_pattern="^fatal: .* contains modified or untracked files,"
                            error_pattern+=" use --force to delete it$"
                            if ! grep -q "$error_pattern" <<<"$output"; then
                                echo "$output"
                                continue
                            fi
                            user_prompt=$(__fgb_stdout_unindented "
                                |
                                |${col_r_bold}WARNING:${col_reset} \#
                                |This will permanently reset/delete the following files:
                                |
                                |$(git -C "$wt_path" -c color.status=always status --short)
                                |
                                |in the ${col_y_bold}${wt_path}${col_reset} path.
                                |
                                |Are you sure you want to proceed?
                            ")
                            # NOTE: Avoid --force here as it's not undoable operation
                            if __fgb_confirmation_dialog "$user_prompt"; then
                                if output="$(git worktree remove "$wt_path" --force 2>&1)"; then
                                    echo -e "$success_message"
                                else
                                    echo "$output" >&2
                                fi
                                user_prompt=$(__fgb_stdout_unindented "
                                |${col_r_bold}Delete${col_reset} the corresponding \#
                                |'${col_b_bold}${branch_name}${col_reset}' branch as well?
                                ")
                                if __fgb_confirmation_dialog "$user_prompt"; then
                                    c_force=true
                                    branch_name="${c_bracket_loc_open}${branch_name}"
                                    branch_name+="$c_bracket_loc_close"
                                    __fgb_git_branch_delete "$branch_name"
                                    c_force="$force_bak"
                                fi
                            else
                                if [[ "$is_in_target_wt" == true ]]; then
                                    cd "$orig_pwd" || return 1
                                fi
                            fi
                        else
                            [[ "$c_force" == true ]] && echo -e "$success_message"
                            user_prompt=$(__fgb_stdout_unindented "
                                |${col_r_bold}Delete${col_reset} the corresponding \#
                                |'${col_b_bold}${branch_name}${col_reset}' branch as well?
                            ")
                            if __fgb_confirmation_dialog "$user_prompt"; then
                                c_force=true
                                branch_name="${c_bracket_loc_open}${branch_name}"
                                branch_name+="$c_bracket_loc_close"
                                __fgb_git_branch_delete "$branch_name"
                                c_force="$force_bak"
                            fi
                        fi
                    else
                        if [[ "$is_in_target_wt" == true ]]; then
                            cd "$orig_pwd" || return 1
                        fi
                    fi
                else
                    # Process a branch that doesn't have a corresponding worktree
                    c_force=true
                    if [[ "$is_remote" == true ]]; then
                        branch_name="${c_bracket_rem_open}${branch_name}${c_bracket_rem_close}"
                    else
                        branch_name="${c_bracket_loc_open}${branch_name}${c_bracket_loc_close}"
                    fi
                    __fgb_git_branch_delete "$branch_name"
                    c_force="$force_bak"
                fi
            done
        }

        __fgb_offer_reset_to_remote() {
            # Offer to bring a stale local branch up to the remote branch that was picked.
            #
            # Selecting a remote branch lands the user on its local counterpart: either a
            # worktree that already has it checked out, or a new one, since
            # `git worktree add <path> <branch>` resolves the name to the existing local
            # branch. Either way the state can be older than the remote's, silently.
            #
            # Only the behind count matters: an up-to-date or purely-ahead branch has
            # nothing stale about it.
            #
            # $3 is the worktree the branch is already checked out in, if any. git refuses
            # `git branch -f` on a checked-out branch, so there the reset has to happen
            # inside the worktree, which also discards uncommitted changes - those are
            # listed before asking.

            local remote_branch="$1" branch_name="$2" wt_path="${3-}"
            [[ -z "$remote_branch" ]] && return 0
            git show-ref --verify --quiet "refs/heads/${branch_name}" || return 0

            local counts ahead behind
            counts="$(
                git rev-list --left-right --count \
                    "refs/heads/${branch_name}...refs/remotes/${remote_branch}" 2>/dev/null
            )" || return 0
            ahead="${counts%%[[:space:]]*}"
            behind="${counts##*[[:space:]]}"
            [[ -z "$behind" || "$behind" -eq 0 ]] 2>/dev/null && return 0

            local commit_word="commits"
            [[ "$behind" -eq 1 ]] && commit_word="commit"

            local where_note
            if [[ -n "$wt_path" ]]; then
                where_note="The worktree ${col_y_bold}${wt_path}${col_reset} has it \#
                    |checked out, so it does not have the remote's state."
            else
                where_note="The new worktree checks out the local branch, so it would \#
                    |not have the remote's state."
            fi

            local discard_note=""
            if [[ -n "$ahead" && "$ahead" -gt 0 ]] 2>/dev/null; then
                local ahead_word="commits that are"
                [[ "$ahead" -eq 1 ]] && ahead_word="commit that is"
                discard_note="
                    |Resetting discards ${col_r_bold}${ahead}${col_reset} local \#
                    |${ahead_word} not on the remote."
            fi

            local dirty=""
            if [[ -n "$wt_path" ]]; then
                dirty="$(git -C "$wt_path" -c color.status=always status --short 2>/dev/null)"
            fi
            local dirty_note=""
            if [[ -n "$dirty" ]]; then
                dirty_note="
                    |
                    |${col_r_bold}It also discards these uncommitted changes:${col_reset}
                    |
                    |$dirty"
            fi

            local user_prompt
            user_prompt=$(__fgb_stdout_unindented "
                |
                |${col_y_bold}INFO:${col_reset} \#
                |Local branch '${col_b_bold}${branch_name}${col_reset}' is \#
                |${col_r_bold}${behind}${col_reset} ${commit_word} behind \#
                |'${col_y_bold}${remote_branch}${col_reset}'.
                |${where_note}${discard_note}${dirty_note}
                |
                |Reset '${col_b_bold}${branch_name}${col_reset}' to \#
                |'${col_y_bold}${remote_branch}${col_reset}'?
            ")
            __fgb_confirmation_dialog "$user_prompt" || return 0

            local reset_ok=false
            if [[ -n "$wt_path" ]]; then
                git -C "$wt_path" reset --hard "refs/remotes/${remote_branch}" >/dev/null &&
                    reset_ok=true
            else
                git branch -f "$branch_name" "refs/remotes/${remote_branch}" &&
                    reset_ok=true
            fi
            if [[ "$reset_ok" == true ]]; then
                echo -e "Reset '${col_b_bold}${branch_name}${col_reset}' to" \
                    "'${col_y_bold}${remote_branch}${col_reset}'"
            else
                echo "fgb: could not reset '$branch_name'" >&2
            fi
        }

        __fgb_git_worktree_jump_or_add() {
            # Jump to an existing worktree or add a new one for a given branch

            if [[ $# -eq 0 ]]; then
                echo "Missing argument: branch name" >&2
                return 1
            fi

            local \
                wt_owner="" \
                branch_name="$1" \
                remote_branch \
                wt_path \
                message \
                ref_prefix
            # shellcheck disable=SC2053
            if [[ "$branch_name" == "$c_bracket_rem_open"*/*"$c_bracket_rem_close" ]]; then
                # Remove the first and the last characters (brackets)
                remote_branch="${branch_name:1}"
                remote_branch="${remote_branch%?}"
                # Remove the first segment of the reference name (<upstream>/)
                branch_name="${remote_branch#*/}"
                ref_prefix="refs/remotes/"
            elif [[ "$branch_name" == "$c_bracket_loc_open"*"$c_bracket_loc_close" ]]; then
                branch_name="${branch_name:1}"
                branch_name="${branch_name%?}"
                ref_prefix="refs/heads/"
            elif [[ "$branch_name" == "$c_bracket_det_open"*"$c_bracket_det_close" ]]; then
                branch_name="${branch_name:1}"
                branch_name="${branch_name%?}"
                ref_prefix="$c_detached_wt_prefix"
            else
                echo "error: invalid branch name pattern: $branch_name" >&2
                return 1
            fi
            if [[ -n "$remote_branch" ]]; then
                # `git worktree add <path> <branch>` resolves a name to the existing local
                # branch, so a remote row whose counterpart is already checked out cannot
                # get a worktree of its own. Jump to the counterpart's instead of failing.
                local counterpart="${c_remote_wt_map["refs/remotes/${remote_branch}"]}"
                if [[ -n "$counterpart" ]]; then
                    wt_path="${counterpart%"$c_split_char"*}"
                    wt_owner="${counterpart##*"$c_split_char"}"
                fi
            else
                wt_path="${c_worktree_path_map["$ref_prefix$branch_name"]}"
            fi
            if [[ -n "$wt_path" ]]; then
                # The worktree may already be behind the remote branch that was picked.
                [[ -n "$wt_owner" ]] &&
                    __fgb_offer_reset_to_remote "$remote_branch" "$wt_owner" "$wt_path"
                cd "$wt_path" || return 1
                local owner_note=""
                [[ -n "$wt_owner" && "$wt_owner" != "$branch_name" ]] &&
                    owner_note=" (checked out as '${col_b_bold}${wt_owner}${col_reset}')"
                message=$(__fgb_stdout_unindented "
                    |${col_g_bold}Jumped${col_reset} to worktree: \#
                    |${col_y_bold}${wt_path}${col_reset}, \#
                    |for branch '${col_b_bold}${branch_name}${col_reset}'${owner_note}
                ")
                echo -e "$message"
            else
                if [[ "$c_confirmed" == true ]]; then
                    wt_path="$(__fgb_normalize_path "${c_wt_base_path}/${branch_name}")"
                else
                    local display_base
                    display_base="${c_wt_base_path/#$HOME/~}"
                    local base_env_var
                    [[ "$c_is_bare_repo" == true ]] &&
                        base_env_var="FGB_WT_BASE_PATH_BARE" ||
                        base_env_var="FGB_WT_BASE_PATH_REGULAR"
                    if [[ -n "$remote_branch" ]]; then
                        printf "%b\n" "$(__fgb_stdout_unindented "
                        |Add a new worktree for '${col_b_bold}${branch_name}${col_reset}' \#
                        |(remote branch: '${col_y_bold}${remote_branch}${col_reset}').
                        |Enter an absolute path or a path relative to: \#
                        |${col_y_bold}${display_base}${col_reset} \#
                        |(${base_env_var})
                        ")"
                    else
                        printf "%b\n" "$(__fgb_stdout_unindented "
                        |Add a new worktree for '${col_b_bold}${branch_name}${col_reset}'.
                        |Enter an absolute path or a path relative to: \#
                        |${col_y_bold}${display_base}${col_reset} \#
                        |(${base_env_var})
                        ")"
                    fi
                    message="Enter the path:"
                    wt_path="$branch_name"
                    if [[ -n "${ZSH_VERSION-}" ]]; then
                        vared -p "$message " wt_path
                    else
                        echo -en "${message}${col_r}"
                        IFS= read -re -p " " -i "$wt_path" wt_path
                        echo -en "$col_reset"
                    fi
                    # If the specified path is not an absolute one...
                    # shellcheck disable=SC2088 # matching a literal ~
                    case "$wt_path" in
                        "~") wt_path="$HOME" ;;
                        "~/"*) wt_path="${HOME}/${wt_path#\~/}" ;;
                        /*) ;;
                        *) wt_path="${c_wt_base_path}/${wt_path}" ;;
                    esac
                    # Collapse "." and ".." lexically. git resolves them when reporting
                    # worktree paths, so an unsimplified path would not match what the
                    # list shows afterwards.
                    wt_path="$(__fgb_normalize_path "$wt_path")"
                fi
                __fgb_offer_reset_to_remote "$remote_branch" "$branch_name"

                local output return_code
                output="$(git worktree add "$wt_path" "$branch_name" 2>&1)"
                return_code=$?
                if [[ $return_code -eq 0 ]]; then
                    cd "$wt_path" || return 1
                    message=$(__fgb_stdout_unindented "
                        |Worktree ${col_y_bold}${wt_path}${col_reset} \#
                        |for branch '${col_b_bold}${branch_name}${col_reset}' added successfully.
                        |${col_g_bold}Jumped${col_reset} there.
                    ")
                    echo -e "$message"
                else
                    echo "$output" >&2
                    return "$return_code"
                fi
            fi
        }

        __fgb_normalize_path() {
            # Collapse "." and ".." segments lexically.
            # Needs no GNU coreutils and, unlike realpath, does not require the path to
            # exist - both matter because worktree base paths are built before creation.

            local path="$1" seg rest result="" absolute=false
            [[ "$path" == /* ]] && absolute=true
            rest="$path"
            while [[ -n "$rest" ]]; do
                seg="${rest%%/*}"
                if [[ "$seg" == "$rest" ]]; then rest=""; else rest="${rest#*/}"; fi
                case "$seg" in
                    "" | ".") continue ;;
                    "..")
                        if [[ -n "$result" && "${result##*/}" != ".." ]]; then
                            result="${result%/*}"
                        elif [[ "$absolute" == false ]]; then
                            result="${result}/.."
                        fi
                        ;;
                    *) result="${result}/${seg}" ;;
                esac
            done
            if [[ "$absolute" == true ]]; then
                printf '%s' "${result:-/}"
            elif [[ -z "$result" ]]; then
                printf '.'
            else
                printf '%s' "${result#/}"
            fi
        }

        __fgb_expand_env() {
            # Expand $VAR and ${VAR} references without evaluating the template, so one
            # coming from the environment or fgbrc can never be executed as shell code.

            local out="" rest="$1" name value
            while [[ "$rest" == *'$'* ]]; do
                out+="${rest%%\$*}"
                rest="${rest#*\$}"
                if [[ "$rest" == '{'* ]]; then
                    name="${rest%%\}*}"
                    name="${name#\{}"
                    rest="${rest#*\}}"
                else
                    name=""
                    while [[ -n "$rest" ]]; do
                        case "${rest:0:1}" in
                            [A-Za-z0-9_])
                                name+="${rest:0:1}"
                                rest="${rest:1}"
                                ;;
                            *) break ;;
                        esac
                    done
                fi
                if [[ -z "$name" ]]; then
                    out+='$'
                    continue
                fi
                case "$name" in
                    [0-9]* | *[!A-Za-z0-9_]*)
                        # Not a plain variable name, so it expands to nothing: bash
                        # would run a subscript such as a[$(cmd)] during the lookup
                        continue
                        ;;
                esac
                if [[ -n "${ZSH_VERSION-}" ]]; then
                    # A fixed eval string, never built from the template, that only
                    # hides zsh-only syntax from bash-based tools such as shfmt;
                    # (P) treats $name as a parameter name, not as code
                    eval 'value="${(P)name}"'
                else
                    value="${!name}"
                fi
                out+="$value"
            done
            out+="$rest"
            printf '%s' "$out"
        }

        __fgb_tilde_path() {
            # Replace a leading $HOME with a literal "~", on a path-component boundary.
            #
            # ${path/#$HOME/~} cannot do this: bash tilde-expands the replacement, so the
            # substitution puts $HOME straight back and prints the absolute path, and the
            # pattern also matches "/home/ann" inside the unrelated "/home/annabel".

            local path="$1" home="${HOME%/}"
            if [[ -z "$home" ]]; then
                printf '%s' "$path"
            elif [[ "$path" == "$home" ]]; then
                printf '~'
            elif [[ "$path" == "$home"/* ]]; then
                printf '~%s' "${path#"$home"}"
            else
                printf '%s' "$path"
            fi
        }

        __fgb_render_relative() {
            # Render a relative path for display: "./" prefix for descendants, and a
            # trailing slash when the result is nothing but parent segments so that
            # "../.." reads as a directory the way "." and ".." already do.

            local rel="$1"
            case "$rel" in
                .) printf './' ;;
                .. | ../*)
                    case "$rel" in
                        *[!./]*) printf '%s' "$rel" ;;
                        *) printf '%s/' "$rel" ;;
                    esac
                    ;;
                *) printf './%s' "$rel" ;;
            esac
        }

        __fgb_canonical_path() {
            # Resolve a path the way realpath does: symlinks in the longest existing
            # ancestor are resolved with `cd`+`pwd -P` (so macOS /var reads as
            # /private/var), and the part that does not exist yet is normalized
            # lexically. zsh's `cd -q` skips chpwd hooks such as zoxide or mise,
            # which would otherwise run for every listed worktree.

            local p rest="" dir
            p="$1"
            [[ "$p" == /* ]] || p="$PWD/$p"
            p="$(__fgb_normalize_path "$p")"
            dir="$p"
            while [[ "$dir" != / && ! -d "$dir" ]]; do
                rest="/${dir##*/}${rest}"
                dir="${dir%/*}"
                [[ -z "$dir" ]] && dir=/
            done
            if [[ -n "${ZSH_VERSION-}" ]]; then
                dir="$(builtin cd -q -- "$dir" 2>/dev/null && pwd -P)" || return 1
            else
                dir="$(builtin cd -- "$dir" 2>/dev/null && pwd -P)" || return 1
            fi
            [[ "$dir" == / ]] && dir=""
            p="${dir}${rest}"
            printf '%s' "${p:-/}"
        }

        __fgb_relative_path() {
            # Print the path $2 relative to the directory $1, like GNU
            # `realpath --relative-to`, which BSD realpath (stock macOS) lacks.

            local base target common up="" rest
            base="$(__fgb_canonical_path "$1")" || return 1
            target="$(__fgb_canonical_path "$2")" || return 1
            common="$base"
            # Climb from the base until it is the target or one of its ancestors;
            # the pattern keeps /a/b from matching /a/bc
            while [[ "$common" != / && "$target" != "$common" && "$target" != "$common"/* ]]; do
                common="${common%/*}"
                [[ -z "$common" ]] && common=/
                up="${up}../"
            done
            if [[ "$target" == "$common" ]]; then
                rest=""
            elif [[ "$common" == / ]]; then
                rest="${target#/}"
            else
                rest="${target#"$common"/}"
            fi
            if [[ -n "$rest" ]]; then
                printf '%s' "${up}${rest}"
            elif [[ -n "$up" ]]; then
                printf '%s' "${up%/}"
            else
                printf '.'
            fi
        }

        __fgb_format_wt_path() {
            # Format a worktree absolute path according to c_wt_path_display mode

            local abs_path="$1"
            local rel
            case "$c_wt_path_display" in
                absolute)
                    printf "%s" "$abs_path"
                    ;;
                tilde)
                    __fgb_tilde_path "$abs_path"
                    ;;
                relative-cwd)
                    rel="$(__fgb_relative_path "$PWD" "$abs_path")" ||
                        {
                            printf "%s" "$abs_path"
                            return
                        }
                    __fgb_render_relative "$rel"
                    ;;
                relative-home)
                    rel="$(__fgb_relative_path "$HOME" "$abs_path")" ||
                        {
                            printf "%s" "$abs_path"
                            return
                        }
                    case "$rel" in
                        .)
                            # shellcheck disable=SC2088
                            printf "~/"
                            ;;
                        .. | ../*) printf "%s" "$rel" ;;
                        *)
                            # shellcheck disable=SC2088
                            printf "~/%s" "$rel"
                            ;;
                    esac
                    ;;
                relative-wt-base)
                    rel="$(__fgb_relative_path "$c_wt_base_path" "$abs_path")" ||
                        {
                            printf "%s" "$abs_path"
                            return
                        }
                    __fgb_render_relative "$rel"
                    ;;
                relative-gitdir)
                    rel="$(__fgb_relative_path "$c_git_common_dir" "$abs_path")" ||
                        {
                            printf "%s" "$abs_path"
                            return
                        }
                    __fgb_render_relative "$rel"
                    ;;
                relative-repo)
                    rel="$(__fgb_relative_path "$c_git_root_path" "$abs_path")" ||
                        {
                            printf "%s" "$abs_path"
                            return
                        }
                    __fgb_render_relative "$rel"
                    ;;
                absolute-gitdir)
                    # Re-joining the git common dir with the remainder of a path under it
                    # reproduces that path, and a path outside it is shown as-is either
                    # way, so this mode is the absolute path. Kept as its own name because
                    # it is a documented value and pairs with tilde-gitdir.
                    printf "%s" "$abs_path"
                    ;;
                tilde-gitdir)
                    # Likewise: absolute-gitdir with the $HOME prefix replaced by "~".
                    __fgb_tilde_path "$abs_path"
                    ;;
                *)
                    __fgb_tilde_path "$abs_path"
                    ;;
            esac
        }

        __fgb_build_remote_wt_map() {
            # Map each remote-tracking ref to "<worktree path><US><local branch>" for the
            # worktree of a local branch that tracks it.
            #
            # A worktree always checks out a local branch, so a remote-tracking ref is
            # never a key in c_worktree_path_map and a remote row would otherwise always
            # look worktree-less, however many of its tracking branches are checked out.
            # The link is the branch's configured upstream, which stays correct when a
            # local branch is named differently from the branch it tracks.
            #
            # Several local branches may track one remote branch, so the winner is chosen
            # by a rule that cannot tie: among the counterparts that actually hold a
            # worktree, the one named like the remote branch wins - branch names are
            # unique, so at most one can match - and otherwise the alphabetically first.
            #
            # Built once here rather than resolved per row: the alternative is a
            # `git for-each-ref` per remote branch, or per branch pair in `worktree add`.

            local local_ref upstream local_name want existing existing_name
            while IFS="$c_split_char" read -r local_ref upstream; do
                [[ -n "$upstream" ]] || continue
                [[ -n "${c_worktree_path_map["$local_ref"]}" ]] || continue
                local_name="${local_ref#refs/heads/}"
                # The remote branch's own name, i.e. without "refs/remotes/<remote>/"
                want="${upstream#refs/remotes/}"
                want="${want#*/}"
                existing="${c_remote_wt_map["$upstream"]}"
                if [[ -n "$existing" ]]; then
                    existing_name="${existing##*"$c_split_char"}"
                    if [[ "$local_name" != "$want" ]]; then
                        [[ "$existing_name" == "$want" ]] && continue
                        [[ "$existing_name" < "$local_name" ]] && continue
                    fi
                fi
                c_remote_wt_map["$upstream"]="${c_worktree_path_map["$local_ref"]}"
                c_remote_wt_map["$upstream"]+="${c_split_char}${local_name}"
            done < <(git for-each-ref --format="%(refname)${c_split_char}%(upstream)" refs/heads)
        }

        __fgb_worktree_list() {
            # List worktrees in a git repository

            __fgb_set_spacer_var "worktree"

            local branch branch_name wt_path wt_abs author_name author_date
            local bracket_open bracket_close
            while IFS= read -r branch; do
                branch="${branch%%"$c_split_char"*}"
                branch_name="$branch"
                if [[ "$branch" == refs/heads/* ]]; then
                    # Remove first two segments of the reference name
                    branch_name="${branch_name#*/}"
                    branch_name="${branch_name#*/}"
                    # Define the bracket characters
                    bracket_open="$c_bracket_loc_open" bracket_close="$c_bracket_loc_close"
                elif [[ "$branch" == refs/remotes/* ]]; then
                    # Remove first two segments of the reference name
                    branch_name="${branch_name#*/}"
                    branch_name="${branch_name#*/}"
                    # Define the bracket characters
                    bracket_open="$c_bracket_rem_open" bracket_close="$c_bracket_rem_close"
                elif [[ "$branch" == "$c_detached_wt_prefix"* ]]; then
                    # Remove first two segments of the reference name
                    branch_name="${branch_name#*/}"
                    branch_name="${branch_name#*/}"
                    # Define the bracket characters
                    bracket_open="$c_bracket_det_open" bracket_close="$c_bracket_det_close"
                fi
                # Adjust the branch name column width based on the number of color code characters
                printf \
                    "%-$((c_branch_width + 13))b" \
                    "${bracket_open}${col_y_bold}${branch_name}${col_reset}${bracket_close}"
                # A remote row has no worktree of its own; show the one belonging to the
                # local branch that tracks it, which is where selecting the row jumps to.
                wt_abs="${c_worktree_path_map["$branch"]}"
                if [[ -z "$wt_abs" && "$branch" == refs/remotes/* ]]; then
                    wt_abs="${c_remote_wt_map["$branch"]%"$c_split_char"*}"
                fi
                if [[ "$c_show_wt_path" == true ]]; then
                    if [[ -n "$wt_abs" ]]; then
                        wt_path="$(__fgb_format_wt_path "$wt_abs")"
                    else
                        wt_path=" "
                    fi
                    printf \
                        "%${c_spacer}s${col_bold}%-${c_wt_path_width}s${col_reset}" \
                        " " \
                        "$wt_path"
                fi
                if [[ "$c_show_wt_flag" == true ]]; then
                    [[ -n "$wt_abs" ]] && wt_path="+" || wt_path=" "
                    printf "%${c_spacer}s${col_bold}%s${col_reset}" " " "$wt_path"
                fi
                if [[ "$c_show_author" == true ]]; then
                    author_name="${c_branch_author_map["$branch"]}"
                    printf \
                        "%${c_spacer}s${col_g}%-${c_author_width}s${col_reset}" " " "$author_name"
                fi
                if [[ "$c_show_date" == true ]]; then
                    author_date="${c_branch_date_map["$branch"]}"
                    printf "%${c_spacer}s(${col_b}%s${col_reset})" " " "$author_date"
                fi
                echo
            done <<<"$c_branches"
        }

        __fgb_git_worktree_restore_stash() {
            # Restore a specific stash to the current worktree or fallback to the initial worktree
            # if needed

            if [[ "$(git rev-parse --is-inside-work-tree 2>/dev/null)" != "true" ]]; then
                echo "fatal: this operation must be run in a work tree" >&2
                return 128
            fi

            if [[ $# -eq 0 ]]; then
                echo "$0 error: missing arguments: stash_id, init_wt_path" >&2
                return 1
            elif [[ $# -lt 2 ]]; then
                echo "$0 error: missing argument: init_wt_path" >&2
                return 1
            fi

            local stash_id="$1"
            local init_wt_path="$2"

            local output return_code
            output="$(git -C "$PWD" -c color.status=always stash apply "$stash_id" 2>&1)"
            return_code=$?

            if [[ $return_code -ne 0 ]]; then
                printf "%b\n" "$(__fgb_stdout_unindented "
                    |
                    |${col_r_bold}WARNING:${col_reset} \#
                    |Failed to apply stash to the worktree created for the new branch.
                    |Restoring stashed changes to the initial worktree.
                    |
                    |${col_g}Stash apply output:${col_reset}
                    |
                    |$output
                ")"
                # Reset the working directory and staging area
                git -C "$PWD" reset --hard HEAD
                # Clean untracked files and directories
                git -C "$PWD" clean -fd
                if git -C "$init_wt_path" stash apply "$stash_id" &>/dev/null; then
                    git -C "$init_wt_path" stash drop "$stash_id" &>/dev/null
                else
                    printf "%b\n" "$(__fgb_stdout_unindented "
                        |
                        |${col_r_bold}ERROR:${col_reset} \#
                        |Failed to restore stash to the initial worktree: \#
                        |${col_y_bold}${init_wt_path}${col_reset}
                        |Your changes are still saved as: ${col_y_bold}${stash_id}${col_reset}
                        |Recover with: git -C ${col_y_bold}${init_wt_path}${col_reset} \#
                        |stash apply ${stash_id}
                    ")"
                fi
            else
                printf "%b\n" "$output"
                git -C "$PWD" stash drop "$stash_id" &>/dev/null
            fi
        }

        __fgb_git_worktree_for_new_branch() {
            # Create a worktree for a new branch

            if [[ -z "$c_new_branch" ]]; then
                return
            fi

            echo "Switched to a new branch '${c_new_branch:1:-1}'"

            local \
                current_date \
                init_wt_path \
                stash_created=false \
                stash_id \
                stash_message \
                user_prompt

            # Check if the current directory is a Git worktree
            if [[ "$(git rev-parse --is-inside-work-tree 2>/dev/null)" == "true" ]]; then
                init_wt_path="$PWD"
                # Check if there are any changes in the working directory
                if ! git diff --quiet || ! git diff --cached --quiet; then
                    # Show changed files in the working directory ignoring untracked files
                    user_prompt=$(__fgb_stdout_unindented "
                        |
                        |${col_y_bold}INFO:${col_reset} \#
                        |The current worktree has uncommitted changes:
                        |
                        |$(git -c color.status=always status --short -uno)
                        |
                        |Do you want to try to stash and pop them in a new worktree?
                    ")
                    if __fgb_confirmation_dialog "$user_prompt"; then
                        current_date="$(date +"%Y-%m-%d %H:%M:%S")"
                        stash_message="[$current_date] Stash to restore in a new worktree"
                        stash_message+=" for branch '${c_new_branch:1:-1}'"
                        if git stash push -m "$stash_message"; then
                            stash_id="$(git stash list --format='%gd' | head -1)"
                            stash_created=true
                        else
                            echo "fgb: failed to stash changes, aborting worktree creation" >&2
                            return 1
                        fi
                    fi
                fi
            fi

            local return_code
            local temp_file
            temp_file=$(mktemp)
            trap 'rm -f "$temp_file"' RETURN INT TERM

            __fgb_git_worktree_jump_or_add "$c_new_branch" 2>|"$temp_file"
            return_code=$?

            local output
            output=$(cat "$temp_file")
            if [[ $return_code -ne 0 ]]; then
                local error_pattern="^fatal: '.+' already exists$"
                if ! grep -qE "$error_pattern" <<<"$output"; then
                    echo "$output" >&2
                    __fgb_git_branch_delete "$c_new_branch"
                else
                    user_prompt=$(__fgb_stdout_unindented "
                        |
                        |${col_r_bold}WARNING:${col_reset} \#
                        |The path \#
                        |'${col_y_bold}${c_wt_base_path}\#
                        |/${c_new_branch:1:-1}${col_reset}' \#
                        |is already exists.
                        |
                        |Would you like to enter another path?
                    ")
                    if __fgb_confirmation_dialog "$user_prompt"; then
                        c_confirmed=false
                        __fgb_git_worktree_jump_or_add "$c_new_branch"
                        return_code=$?
                        if [[ $return_code -ne 0 ]]; then
                            __fgb_git_branch_delete "$c_new_branch"
                        fi
                    else
                        __fgb_git_branch_delete "$c_new_branch"
                    fi
                fi
            fi
            "$stash_created" && __fgb_git_worktree_restore_stash "$stash_id" "$init_wt_path"
            return "$return_code"
        }

        __fgb_worktree_add() {
            # Add a new worktree for a given branch

            # Drop branches that already have a worktree. For a remote branch that means
            # its local counterpart having one, since selecting the row jumps there rather
            # than creating anything.
            local line branch
            c_branches="$(while IFS= read -r line; do
                branch="${line%%"$c_split_char"*}"
                grep -qxF "${branch}" <<<"$c_worktree_branches" && continue
                [[ "$branch" == refs/remotes/* &&
                    -n "${c_remote_wt_map["$branch"]}" ]] && continue
                echo "$line"
            done <<<"$c_branches")"

            __fgb_branch_set_vars "$c_branches"
            __fgb_set_spacer_var "worktree"

            local \
                spacer_branch=" " \
                spacer_author=" " \
                header_column_names_row

            spacer_branch="$(
                printf "%$((c_branch_width + 2 - ${#c_column_branch} + c_spacer))s" " "
            )"
            spacer_author="$(printf "%$((c_author_width - ${#c_column_author} + c_spacer))s" " ")"

            header_column_names_row="${c_column_branch}${spacer_branch}"
            [[ "$c_show_author" == true ]] &&
                header_column_names_row+="${c_column_author}${spacer_author}"
            [[ "$c_show_date" == true ]] && header_column_names_row+="$c_column_date"

            local header="Add a Git Worktree:"
            header+=" ${c_del_key}:del"
            header+=", ${c_extend_del_key}:extended-del, ${c_info_key}:info, ${c_verbose_key}:verbose"
            header+=", ${c_new_branch_key}:fork, ${c_new_branch_verbose_key}:fork-verbose"
            [[ -n "$c_bind_keys" ]] && header+=", $c_bind_keys"
            header+=$(__fgb_stdout_unindented "
                |
                |$header_column_names_row
            ")

            local expected_keys="$c_del_key,$c_extend_del_key,$c_info_key,$c_verbose_key"
            expected_keys+=",$c_new_branch_key,$c_new_branch_verbose_key"

            local fzf_cmd
            fzf_cmd="\
                $FZF_CMD_GLOB \
                    --expect=$(printf '%q' "$expected_keys") \
                    --header $(printf '%q' "$header") \
                "

            [[ $# -gt 0 ]] && fzf_cmd+=" --query=$(printf '%q' "$*")"

            local lines
            lines="$(
                __fgb_branch_list |
                    eval "$fzf_cmd" |
                    cut -d' ' -f1
            )"

            [[ -z "$lines" ]] && return

            local key
            key="$(head -1 <<<"$lines")"
            branch="$(tail -1 <<<"$lines")"
            local branch_type=""

            case "${branch:0:1}" in
                "$c_bracket_loc_open") branch_type="local" ;;
                "$c_bracket_rem_open") branch_type="remote" ;;
            esac

            case $key in
                "$c_del_key") __fgb_git_branch_delete "$(sed 1d <<<"$lines")" ;;
                "$c_extend_del_key")
                    c_extend_del=true
                    __fgb_git_branch_delete "$(sed 1d <<<"$lines")"
                    ;;
                "$c_info_key")
                    # Remove the first and the last characters (brackets)
                    branch="${branch:1:-1}"
                    __fgb_print_branch_info "$branch"
                    ;;
                "$c_verbose_key")
                    c_confirmed=false
                    __fgb_git_worktree_jump_or_add "$branch"
                    ;;
                "$c_new_branch_key" | "$c_new_branch_verbose_key")
                    local return_code for_new_worktree=true
                    __fgb_git_branch_new "${branch:1:-1}" "$branch_type" "$for_new_worktree"
                    return_code=$?
                    [[ $return_code -ne 0 ]] && return "$return_code"
                    [[ "$key" == "$c_new_branch_verbose_key" ]] && c_confirmed=false
                    __fgb_git_worktree_for_new_branch
                    ;;
                *) __fgb_git_worktree_jump_or_add "$branch" ;;
            esac
        }

        __fgb_worktree_total() {
            # Manage Git worktrees

            __fgb_branch_set_vars "$c_branches"
            __fgb_set_spacer_var "worktree"

            local \
                spacer_branch=" " \
                column_wt="WT" \
                spacer_wt=" " \
                spacer_author=" " \
                header_column_names_row

            spacer_branch="$(
                printf "%$((c_branch_width + 2 - ${#c_column_branch} + c_spacer))s" " "
            )"
            if [[ "$c_show_wt_path" == true ]]; then
                spacer_wt="$(printf "%$((c_wt_path_width - ${#column_wt} + c_spacer))s" " ")"
            elif [[ "$c_show_wt_flag" == true ]]; then
                column_wt="W"
                spacer_wt="$(printf "%$((1 - ${#column_wt} + c_spacer))s" " ")"
            fi
            spacer_author="$(printf "%$((c_author_width - ${#c_column_author} + c_spacer))s" " ")"

            header_column_names_row="${c_column_branch}${spacer_branch}"
            [[ "$c_show_wt_path" == true || "$c_show_wt_flag" == true ]] &&
                header_column_names_row+="${column_wt}${spacer_wt}"
            [[ "$c_show_author" == true ]] &&
                header_column_names_row+="${c_column_author}${spacer_author}"
            [[ "$c_show_date" == true ]] && header_column_names_row+="$c_column_date"

            local header="Manage Git Worktrees (total):"
            header+=" ${c_del_key}:del"
            header+=", ${c_extend_del_key}:extended-del, ${c_info_key}:info, ${c_verbose_key}:verbose"
            header+=", ${c_new_branch_key}:fork, ${c_new_branch_verbose_key}:fork-verbose"
            [[ -n "$c_bind_keys" ]] && header+=", $c_bind_keys"
            header+=$(__fgb_stdout_unindented "
                |
                |$header_column_names_row
            ")

            local expected_keys="$c_del_key,$c_extend_del_key,$c_info_key,$c_verbose_key"
            expected_keys+=",$c_new_branch_key,$c_new_branch_verbose_key"

            local fzf_cmd
            fzf_cmd="\
                $FZF_CMD_GLOB \
                    --expect=$(printf '%q' "$expected_keys") \
                    --header $(printf '%q' "$header") \
                "

            [[ $# -gt 0 ]] && fzf_cmd+=" --query=$(printf '%q' "$*")"

            local lines
            lines="$(__fgb_worktree_list | eval "$fzf_cmd" | cut -d' ' -f1)"

            [[ -z "$lines" ]] && return

            local key
            key="$(head -1 <<<"$lines")"
            local branch
            branch="$(tail -1 <<<"$lines")"
            local branch_type=""

            case "${branch:0:1}" in
                "$c_bracket_loc_open") branch_type="local" ;;
                "$c_bracket_rem_open") branch_type="remote" ;;
            esac

            case $key in
                "$c_del_key") __fgb_git_worktree_delete "$(sed 1d <<<"$lines")" ;;
                "$c_extend_del_key")
                    c_extend_del=true
                    __fgb_git_worktree_delete "$(sed 1d <<<"$lines")"
                    ;;
                "$c_info_key")
                    # Remove the first and the last characters (brackets)
                    branch="${branch:1:-1}"
                    __fgb_print_branch_info "$branch"
                    ;;
                "$c_verbose_key")
                    c_confirmed=false
                    __fgb_git_worktree_jump_or_add "$branch"
                    ;;
                "$c_new_branch_key" | "$c_new_branch_verbose_key")
                    local return_code for_new_worktree=true
                    __fgb_git_branch_new "${branch:1:-1}" "$branch_type" "$for_new_worktree"
                    return_code=$?
                    [[ $return_code -ne 0 ]] && return "$return_code"
                    [[ "$key" == "$c_new_branch_verbose_key" ]] && c_confirmed=false
                    __fgb_git_worktree_for_new_branch
                    ;;
                *) __fgb_git_worktree_jump_or_add "$branch" ;;
            esac
        }

        __fgb_worktree_manage() {
            # Manage Git worktrees

            __fgb_set_spacer_var "worktree"

            local \
                spacer_branch=" " \
                column_wt="WT" \
                spacer_wt=" " \
                spacer_author=" " \
                header_column_names_row

            spacer_branch="$(
                printf "%$((c_branch_width + 2 - ${#c_column_branch} + c_spacer))s" " "
            )"
            if [[ "$c_show_wt_path" == true ]]; then
                spacer_wt="$(printf "%$((c_wt_path_width - ${#column_wt} + c_spacer))s" " ")"
            elif [[ "$c_show_wt_flag" == true ]]; then
                column_wt="W"
                spacer_wt="$(printf "%$((1 - ${#column_wt} + c_spacer))s" " ")"
            fi
            spacer_author="$(printf "%$((c_author_width - ${#c_column_author} + c_spacer))s" " ")"

            header_column_names_row="${c_column_branch}${spacer_branch}"
            [[ "$c_show_wt_path" == true || "$c_show_wt_flag" == true ]] &&
                header_column_names_row+="${column_wt}${spacer_wt}"
            [[ "$c_show_author" == true ]] &&
                header_column_names_row+="${c_column_author}${spacer_author}"
            [[ "$c_show_date" == true ]] && header_column_names_row+="$c_column_date"

            local header="Manage Git Worktrees:"
            header+=" ${c_del_key}:del, ${c_extend_del_key}:extended-del, ${c_info_key}:info"
            [[ -n "$c_bind_keys" ]] && header+=", $c_bind_keys"
            header+=$(__fgb_stdout_unindented "
                |
                |$header_column_names_row
            ")
            local fzf_cmd
            fzf_cmd="\
                $FZF_CMD_GLOB \
                    --expect=$(printf '%q' "$c_del_key,$c_extend_del_key,$c_info_key") \
                    --header $(printf '%q' "$header") \
                "

            [[ $# -gt 0 ]] && fzf_cmd+=" --query=$(printf '%q' "$*")"

            local lines
            lines="$(__fgb_worktree_list | eval "$fzf_cmd" | cut -d' ' -f1)"

            [[ -z "$lines" ]] && return

            local key
            key="$(head -1 <<<"$lines")"

            local branch
            branch="$(tail -1 <<<"$lines")"
            case $key in
                "$c_del_key") __fgb_git_worktree_delete "$(sed 1d <<<"$lines")" ;;
                "$c_extend_del_key")
                    c_extend_del=true
                    __fgb_git_worktree_delete "$(sed 1d <<<"$lines")"
                    ;;
                "$c_info_key")
                    # Remove the first and the last characters (brackets)
                    branch="${branch:1:-1}"
                    __fgb_print_branch_info "$branch"
                    ;;
                *) __fgb_git_worktree_jump_or_add "$branch" ;;
            esac
        }

        __fgb_worktree_set_vars() {
            # Define worktree related variables

            # Cache porcelain output - avoids repeated git subprocess calls
            local porcelain_output
            porcelain_output="$(git worktree list --porcelain)"

            local first_entry_attrs
            first_entry_attrs="$(awk 'NR>1 && /^$/{exit} NR>1{print $1}' <<<"$porcelain_output")"
            grep -qx "bare" <<<"$first_entry_attrs" && c_is_bare_repo=true || c_is_bare_repo=false

            # Ask git for the common directory rather than deriving it from the worktree
            # path. It is "<root>/.git" only for ordinary repositories; for a repo created
            # with --separate-git-dir it is somewhere else entirely, and deriving it would
            # produce a directory that does not exist.
            c_git_common_dir="$(git rev-parse --git-common-dir 2>/dev/null)"
            if [[ -z "$c_git_common_dir" ]]; then
                echo "fgb: cannot determine the git common directory" >&2
                return 128
            fi
            # --git-common-dir answers relative to the cwd (".git", "../../.git", "." in a
            # bare repo). Resolving with `cd`+`pwd -P` keeps the spelling git itself uses in
            # `worktree list` output, which matters when the cwd was reached via a symlink.
            c_git_common_dir="$(cd "$c_git_common_dir" 2>/dev/null && pwd -P)" || {
                echo "fgb: cannot resolve the git common directory" >&2
                return 128
            }

            # The path git reports for the main worktree is the common directory with a
            # "/.git" suffix stripped, so it is wrong whenever that suffix is absent.
            # Recover the real one in that case; git cannot always answer it either, so
            # fall back to what it reported rather than inventing a path.
            local reported_main
            reported_main="$(awk 'NR==1{sub(/^worktree /, ""); print}' <<<"$porcelain_output")"
            if [[ "$c_is_bare_repo" == true ]]; then
                c_git_root_path="$c_git_common_dir"
            elif [[ "$c_git_common_dir" == */.git ]]; then
                c_git_root_path="$reported_main"
            else
                local core_wt toplevel
                core_wt="$(git config core.worktree 2>/dev/null)"
                if [[ -n "$core_wt" ]]; then
                    [[ "$core_wt" != /* ]] && core_wt="${c_git_common_dir}/${core_wt}"
                    c_git_root_path="$(cd "$core_wt" 2>/dev/null && pwd -P)"
                fi
                if [[ -z "$c_git_root_path" ]]; then
                    toplevel="$(git rev-parse --show-toplevel 2>/dev/null)"
                    c_git_root_path="${toplevel:-$reported_main}"
                fi
            fi

            # Expand worktree base path template.
            # Placeholders: {repo_name} = basename of the repo's working-tree root (for
            #               bare repos the bare directory itself, e.g. "my-project.git"),
            #               {repo_name_short} = same with a .git suffix stripped.
            local repo_name
            repo_name="$(basename "$c_git_root_path")"
            local repo_name_short="${repo_name%.git}"
            local tmpl
            if [[ "$c_is_bare_repo" == true ]]; then
                tmpl="$c_wt_base_path_tmpl_bare"
            else
                tmpl="$c_wt_base_path_tmpl_regular"
            fi
            tmpl="${tmpl//\{repo_name\}/$repo_name}"
            tmpl="${tmpl//\{repo_name_short\}/$repo_name_short}"
            # Expand a leading ~ and any environment variables before deciding whether the
            # template is absolute; without this a natural "~/worktrees" is treated as
            # relative and anchored, creating a literal "~" directory under the git dir.
            # shellcheck disable=SC2088 # matching a literal ~
            case "$tmpl" in
                "~") tmpl="$HOME" ;;
                "~/"*) tmpl="${HOME}/${tmpl#\~/}" ;;
            esac
            [[ "$tmpl" == *'$'* ]] && tmpl="$(__fgb_expand_env "$tmpl")"
            if [[ "$tmpl" == /* ]]; then
                c_wt_base_path="$tmpl"
            else
                c_wt_base_path="${c_git_common_dir}/${tmpl#./}"
            fi
            # Collapse ".." segments so a template that escapes the anchor does not leave
            # them behind: git resolves them when reporting worktree paths, so an
            # unsimplified base would no longer match what the picker displays.
            c_wt_base_path="$(__fgb_normalize_path "$c_wt_base_path")"

            # Parse the porcelain output record by record. Entries are separated by blank
            # lines and their attribute lines may appear in any order or be absent
            # (locked, prunable, ...), so relying on fixed line numbers is not safe.
            # Paths are taken with substr rather than $2 so that ones containing spaces
            # survive.
            local wt_list
            wt_list="$(
                awk -v split_char="$c_split_char" -v ref_prefix="$c_detached_wt_prefix" \
                    -v reported_main="$reported_main" -v real_main="$c_git_root_path" '
                    function flush(  short) {
                        if (path != "" && !bare) {
                            if (branch != "") {
                                printf "%s%s%s\n", path, split_char, branch
                            } else if (detached && hash != "") {
                                short = substr(hash, 1, 7)
                                printf "%s%s%s%s\n", path, split_char, ref_prefix, short
                            }
                        }
                        path = ""; branch = ""; hash = ""; detached = 0; bare = 0
                    }
                    /^worktree /  {
                        flush()
                        path = substr($0, 10)
                        # git reports the main worktree as the common directory with a
                        # "/.git" suffix stripped, which is not the working tree when that
                        # suffix is absent. Use the path resolved above instead.
                        if (path == reported_main) path = real_main
                    }
                    /^HEAD /      { hash = substr($0, 6) }
                    /^branch /    { branch = substr($0, 8) }
                    /^detached$/  { detached = 1 }
                    /^bare$/      { bare = 1 }
                    END           { flush() }
                ' <<<"$porcelain_output"
            )"

            c_worktree_branches="$(
                awk -F"$c_split_char" 'NF>1{print $2}' <<<"$wt_list"
            )"

            local \
                branch \
                line \
                wt_path \
                wt_path_curr_width
            while IFS= read -r line; do
                [[ "$line" = "" ]] && continue
                branch="${line#*"$c_split_char"}"
                c_worktree_path_map["$branch"]="${line%"$c_split_char"*}"
                # Calculate column widths
                wt_path="$(__fgb_format_wt_path "${c_worktree_path_map["$branch"]}")"
                wt_path_curr_width="${#wt_path}"
                c_wt_path_width="$((\
                    wt_path_curr_width > c_wt_path_width ? \
                    wt_path_curr_width : \
                    c_wt_path_width))"
            done <<<"$wt_list"

            __fgb_build_remote_wt_map
        }

        __fgb_worktree() {
            # Manage Git worktrees

            local subcommand="$1"
            shift
            case $subcommand in
                add | list | manage | total)
                    if ! git rev-parse --git-dir &>/dev/null; then
                        echo "Not inside a Git repository. Exit..." >&2
                        return 128
                    fi

                    # Worktrees are not supported for submodules: a submodule's git
                    # directory lives inside the superproject's, at
                    # <super>/.git/modules/<name>, and worktree base paths are anchored to
                    # the git common directory, so its worktrees would land under the
                    # superproject's .git - invisible to normal tooling and removed by
                    # `git submodule deinit`.
                    #
                    # Only an absolute answer is accepted: `git rev-parse` echoes options
                    # it does not recognise straight back to stdout and still exits 0, so
                    # a git older than 2.13 would otherwise report the option name itself
                    # and make every repository look like a submodule.
                    local superproject
                    superproject="$(git rev-parse --show-superproject-working-tree 2>/dev/null)"
                    if [[ "$superproject" == /* ]]; then
                        printf "%b\n" "$(__fgb_stdout_unindented "
                            |${col_r_bold}fgb:${col_reset} \#
                            |this repository is a submodule of \#
                            |${col_y_bold}${superproject}${col_reset}
                            |Worktrees are not supported for submodules - skipping.
                            |Clone the submodule as a standalone repository to use \#
                            |worktrees with it.
                        ")" >&2
                        return 1
                    fi

                    local -a fzf_query=()
                    local branch_show_remote=false branch_show_all=false
                    while [[ $# -gt 0 ]]; do
                        case "$1" in
                            -r | --remotes | -a | --all | -c | --confirm)
                                # shellcheck disable=SC2076
                                if [[ " list manage " =~ " $subcommand " ]]; then
                                    echo "error: unknown option: \`$1'" >&2
                                    echo "${usage_message[worktree_$subcommand]}" >&2
                                    return 1
                                fi
                                case "$1" in
                                    -r | --remotes)
                                        branch_show_remote=true
                                        ;;
                                    -a | --all)
                                        branch_show_all=true
                                        ;;
                                    -c | --confirm) c_confirmed=true ;;
                                esac
                                ;;
                            -s | --sort)
                                shift
                                c_branch_sort_order="$1"
                                ;;
                            --sort=*)
                                c_branch_sort_order="${1#*=}"
                                ;;
                            -d | --date-format)
                                shift
                                c_date_format="$1"
                                ;;
                            --date-format=*)
                                c_date_format="${1#*=}"
                                ;;
                            -u | --author-format)
                                shift
                                c_author_format="$1"
                                ;;
                            --author-format=*)
                                c_author_format="${1#*=}"
                                ;;
                            -p | --wt-path-display)
                                shift
                                c_wt_path_display="$1"
                                ;;
                            --wt-path-display=*)
                                c_wt_path_display="${1#*=}"
                                ;;
                            -f | --force) c_force=true ;;
                            -h | --help)
                                echo "${usage_message[worktree_$subcommand]}"
                                return 0
                                ;;
                            --)
                                if [[ "$subcommand" == "list" ]]; then
                                    echo "error: unknown option: \`$1'" >&2
                                    echo "       query not expected for the list command." >&2
                                    echo "${usage_message[branch_$subcommand]}" >&2
                                    return 1
                                fi
                                while [[ $# -gt 1 ]]; do
                                    shift
                                    fzf_query+=("$1")
                                done
                                break
                                ;;
                            --* | -*)
                                echo "error: unknown option: \`$1'" >&2
                                echo "${usage_message[worktree_$subcommand]}" >&2
                                return 1
                                ;;
                            *) fzf_query+=("$1") ;;
                        esac
                        shift
                    done

                    c_date_format="$(__fgb_transform_git_format_string "$c_date_format")"
                    c_author_format="$(__fgb_transform_git_format_string "$c_author_format")"

                    __fgb_worktree_set_vars || return $?

                    local branch_type
                    [[ "$branch_show_remote" == true ]] &&
                        branch_type="remote" ||
                        branch_type="local"
                    [[ "$branch_show_all" == true ]] && branch_type="all"

                    local filter_list
                    # shellcheck disable=SC2076
                    [[ " list manage " =~ " $subcommand " ]] && filter_list="$c_worktree_branches"

                    local return_code
                    c_branches="$(__fgb_git_branch_list "$branch_type" "$filter_list")"
                    return_code=$?
                    [[ $return_code -ne 0 ]] && return "$return_code"

                    local detached_wt
                    detached_wt="$(grep "^$c_detached_wt_prefix" <<<"$c_worktree_branches")"

                    # shellcheck disable=SC2076
                    if [[ -n "$detached_wt" && " local all " =~ " $branch_type " ]]; then
                        local \
                            line \
                            hash \
                            wt_hash_data \
                            author_format \
                            date_format \
                            dates_with_format \
                            log_format \
                            log_date \
                            log_output \
                            dates_data

                        # Git's iso-strict format
                        local regexp='\([0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\}'
                        regexp+='T[0-9]\{2\}:[0-9]\{2\}:[0-9]\{2\}[+-][0-9]\{2\}:[0-9]\{2\}\)'

                        author_format="$(__fgb_convert_git_format_string "$c_author_format")"
                        date_format="$(__fgb_convert_git_format_string "$c_date_format")"

                        dates_with_format="$(__fgb_extract_date_format "$c_author_format")"
                        dates_with_format="${dates_with_format}$(
                            __fgb_extract_date_format "$c_date_format"
                        )"

                        while IFS= read -r line; do
                            hash="${line#"$c_detached_wt_prefix"}"
                            wt_hash_data="$(
                                git log -1 \
                                    --pretty=format:"$(printf '%s%b%s' \
                                        "$author_format" \
                                        "$c_split_char" \
                                        "$date_format")" \
                                    --date=iso-strict \
                                    "$hash"
                            )"
                            while IFS= read -r dates_data; do
                                log_format="${dates_data%%"$c_split_char"*}"
                                log_date="${dates_data##*"$c_split_char"}"
                                log_output="$(
                                    git log -1 \
                                        --pretty=format:"$log_format" \
                                        --date="$log_date" \
                                        "$hash"
                                )"
                                local safe_log_output="${log_output//\\/\\\\}"
                                safe_log_output="${safe_log_output//&/\\&}"
                                safe_log_output="${safe_log_output//\//\\/}"
                                wt_hash_data="$(
                                    # shellcheck disable=SC2001
                                    sed "s/$c_split_char$regexp$c_split_char/$safe_log_output/" <<< \
                                        "$wt_hash_data"
                                )"
                            done <<<"$dates_with_format"
                            c_branches="$line$c_split_char$wt_hash_data
                                $c_branches"
                        done <<<"$detached_wt"
                    fi

                    # Remove leading spaces
                    # shellcheck disable=SC2001
                    c_branches="$(sed 's/^[[:space:]]*//' <<<"$c_branches")"

                    __fgb_branch_set_vars "$c_branches"

                    case "$subcommand" in
                        add) __fgb_worktree_add "${fzf_query[@]}" ;;
                        list) __fgb_worktree_list ;;
                        manage) __fgb_worktree_manage "${fzf_query[@]}" ;;
                        total) __fgb_worktree_total "${fzf_query[@]}" ;;
                    esac
                    ;;
                -h | --help)
                    echo "${usage_message[worktree]}"
                    ;;
                --* | -*)
                    echo "error: unknown option: \`$subcommand'" >&2
                    echo "${usage_message[worktree]}" >&2
                    return 1
                    ;;
                *)
                    echo "error: unknown subcommand: \`$subcommand'" >&2
                    echo "${usage_message[worktree]}" >&2
                    return 1
                    ;;
            esac
        }

        # Process the configuration file
        local fgbrc_file="$HOME"/.config/fgbrc key value env_var_pattern='^[[:space:]]*'
        env_var_pattern+='FGB_(SORT_ORDER|DATE_FORMAT|AUTHOR_FORMAT|WT_PATH_DISPLAY|'
        env_var_pattern+='WT_BASE_PATH_(BARE|REGULAR)|'
        env_var_pattern+='BINDKEY_(DEL|EXTEND_DEL|INFO|VERBOSE|NEW_BRANCH|NEW_BRANCH_VERBOSE))*='
        if [[ -f "$fgbrc_file" ]]; then
            while IFS='=' read -r key value; do
                # Trim leading spaces from key
                key="${key#"${key%%[![:space:]]*}"}"
                # Strip inline comment and trailing whitespace from value
                value="$(sed 's/[[:space:]]*#.*//; s/[[:space:]]*$//' <<<"$value")"
                # Check if the variable is defined in the environment
                [[ "$(printenv "$key")" != "" ]] && continue
                # Declare local first, then assign without eval so the value
                # is never interpreted as shell code (protects against
                # metacharacters such as ; $() ` in config values).
                eval "local $key"
                printf -v "$key" '%s' "$value"
                # Loop through only valid lines
            done < <(grep -E "$env_var_pattern" "$fgbrc_file")
        fi

        # Declare "global" (commonly used) variables
        local \
            col_reset='\033[0m' \
            col_r='\033[31m' \
            col_g='\033[32m' \
            col_y='\033[33m' \
            col_b='\033[34m' \
            col_m='\033[35m' \
            col_bold='\033[1m' \
            col_r_bold='\033[1;31m' \
            col_g_bold='\033[1;32m' \
            col_y_bold='\033[1;33m' \
            col_b_bold='\033[1;34m' \
            c_git_root_path="" \
            c_wt_base_path="" \
            c_wt_base_path_tmpl_bare="${FGB_WT_BASE_PATH_BARE:-./wt}" \
            c_wt_base_path_tmpl_regular="${FGB_WT_BASE_PATH_REGULAR:-./wt}" \
            c_git_common_dir="" \
            c_is_bare_repo=false \
            c_wt_path_display="${FGB_WT_PATH_DISPLAY:-tilde}" \
            c_branches="" \
            c_spacer=1 \
            c_worktree_branches="" \
            c_wt_path_width=0 \
            c_show_author=true \
            c_show_date=true \
            c_show_wt_flag=false \
            c_show_wt_path=true \
            c_bracket_loc_open="[" \
            c_bracket_loc_close="]" \
            c_bracket_rem_open="(" \
            c_bracket_rem_close=")" \
            c_bracket_det_open="{" \
            c_bracket_det_close="}" \
            c_force=false \
            c_extend_del=false \
            c_confirmed=false \
            c_branch_sort_order="${FGB_SORT_ORDER:--committerdate}" \
            c_date_format="${FGB_DATE_FORMAT:-committerdate:relative}" \
            c_author_format="${FGB_AUTHOR_FORMAT:-committername}" \
            c_del_key="${FGB_BINDKEY_DEL:-ctrl-d}" \
            c_extend_del_key="${FGB_BINDKEY_EXTEND_DEL:-ctrl-alt-d}" \
            c_info_key="${FGB_BINDKEY_INFO:-ctrl-o}" \
            c_verbose_key="${FGB_BINDKEY_VERBOSE:-ctrl-v}" \
            c_new_branch_key="${FGB_BINDKEY_NEW_BRANCH:-alt-n}" \
            c_new_branch_verbose_key="${FGB_BINDKEY_NEW_BRANCH_VERBOSE:-alt-N}" \
            c_column_branch="Branch" \
            c_column_author="Author" \
            c_column_date="Date" \
            c_bind_keys="" \
            c_detached_wt_prefix="detached/heads/" \
            c_new_branch=""

        # Extract all --bind keys specified in FZF arguments so far to add them to the header
        c_bind_keys="$(echo "$FZF_CMD_GLOB" | tr ' ' '\n' | grep -- '--bind' |
            cut -d'=' -f2 | tr '\n' ',' | sed 's/,$//;s/,/, /g')"

        local \
            c_branch_width="${#c_column_branch}" \
            c_author_width="${#c_column_author}" \
            c_date_width="${#c_column_date}" \
            c_total_width=0

        local c_split_char=$'\x1f' # (ASCII 31, Unit Separator)

        local -A \
            c_branch_author_map \
            c_branch_date_map \
            c_remote_wt_map \
            c_worktree_path_map

        # Define messages
        local version_message="fzf-git-branches, version $VERSION"
        local copyright_message
        copyright_message=$(__fgb_stdout_unindented "
            |Copyright (C) 2024 Andrei Bulgakov <https://github.com/awerebea>.

            |License GPLv3+: GNU GPL version 3 or later <http://gnu.org/licenses/gpl.html>
            |This is free software; you are free to change and redistribute it.
            |There is NO WARRANTY, to the extent permitted by law.
        ")

        local default_sort_order="${FGB_SORT_ORDER:--committerdate}"
        local default_date_format="${FGB_DATE_FORMAT:-committerdate:relative}"
        local default_author_format="${FGB_AUTHOR_FORMAT:-committername}"

        local -A usage_message=(
            ["fgb"]="$(__fgb_stdout_unindented "
            |Usage: fgb <command> [<args>]
            |
            |Commands:
            |  branch    Manage branches in a Git repository
            |
            |  worktree  Manage worktrees in a Git repository (bare and regular)
            |
            |Options:
            |  -v, --version
            |            Show version information
            |
            |  -h, --help
            |            Show help message
            |
            |Configuration:
            |  Settings can be stored in \$HOME/.config/fgbrc (one KEY=value per line).
            |  Environment variables take precedence over the config file.
            |
            |  FGB_SORT_ORDER                   sort key ($default_sort_order)
            |  FGB_DATE_FORMAT                  date format ($default_date_format)
            |  FGB_AUTHOR_FORMAT                author format ($default_author_format)
            |  FGB_WT_PATH_DISPLAY              worktree path display ($c_wt_path_display)
            |  FGB_WT_BASE_PATH_BARE            worktree base path, bare repos \#
            |($c_wt_base_path_tmpl_bare)
            |  FGB_WT_BASE_PATH_REGULAR         worktree base path, regular repos \#
            |($c_wt_base_path_tmpl_regular)
            |  FGB_BINDKEY_DEL                  delete key ($c_del_key)
            |  FGB_BINDKEY_EXTEND_DEL           extended delete key ($c_extend_del_key)
            |  FGB_BINDKEY_INFO                 info key ($c_info_key)
            |  FGB_BINDKEY_VERBOSE              force path prompt key ($c_verbose_key)
            |  FGB_BINDKEY_NEW_BRANCH           fork branch key ($c_new_branch_key)
            |  FGB_BINDKEY_NEW_BRANCH_VERBOSE   fork with custom path \#
            |($c_new_branch_verbose_key)
            |  FGB_FZF_OPTS                     fzf display options (env only; \#
            |must be exported before sourcing the script)
            ")"

            ["branch"]="$(__fgb_stdout_unindented "
            |Usage: fgb branch <subcommand> [<args>]
            |
            |Subcommands:
            |  list    List branches in a Git repository and exit
            |
            |  manage  Switch to existing branches in the Git repository or delete them
            |
            |Options:
            |  -h, --help
            |          Show help message
            ")"

            ["branch_list"]="$(__fgb_stdout_unindented "
            |Usage: fgb branch list [<args>]
            |
            |List branches in a Git repository and exit
            |
            |Options:
            |  -s, --sort=<sort>
            |          Sort key passed to git for-each-ref --sort. \#
            |          Default: '$default_sort_order'. \#
            |          Prefix with - for descending order. \#
            |          Examples: refname, -authordate, \#
            |          -committerdate,committername
            |
            |  -d, --date-format=<date>
            |          Date column format (git for-each-ref). \#
            |          Default: '$default_date_format'. \#
            |          Examples: authordate:short, \#
            |          committerdate:format:'%Y-%m-%d %H:%M'
            |
            |  -u, --author-format=<author>
            |          Author column format (git for-each-ref). \#
            |          Default: '$default_author_format'. \#
            |          Examples: authoremail, \#
            |          %(committername) %(committeremail)
            |
            |  -r, --remotes
            |          List remote branches only (default: local only)
            |
            |  -a, --all
            |          List both local and remote branches
            |
            |  -h, --help
            |          Show help message
            ")"

            ["branch_manage"]="$(__fgb_stdout_unindented "
            |Usage: fgb branch manage [<args>] [<query>]
            |
            |Switch to existing branches in the Git repository or delete them
            |
            |Query:
            |  <query>  Query to filter branches by using fzf
            |
            |Options:
            |  -s, --sort=<sort>
            |          Sort key passed to git for-each-ref --sort. \#
            |          Default: '$default_sort_order'. \#
            |          Prefix with - for descending order. \#
            |          Examples: refname, -authordate, \#
            |          -committerdate,committername
            |
            |  -d, --date-format=<date>
            |          Date column format (git for-each-ref). \#
            |          Default: '$default_date_format'. \#
            |          Examples: authordate:short, \#
            |          committerdate:format:'%Y-%m-%d %H:%M'
            |
            |  -u, --author-format=<author>
            |          Author column format (git for-each-ref). \#
            |          Default: '$default_author_format'. \#
            |          Examples: authoremail, \#
            |          %(committername) %(committeremail)
            |
            |  -r, --remotes
            |          List remote branches only (default: local only)
            |
            |  -a, --all
            |          List both local and remote branches
            |
            |  -f, --force
            |          Skip the confirmation prompt before deleting \#
            |          branches or worktrees
            |
            |  -h, --help
            |          Show help message
            ")"

            ["worktree"]="$(__fgb_stdout_unindented "
            |Usage: fgb worktree <subcommand> [<args>]
            |
            |Subcommands:
            |  list    List all worktrees in a Git repository and exit
            |
            |  manage  Switch to existing worktrees in the Git repository or delete them
            |
            |  add     Add a new worktree for a selected branch
            |
            |  total   Full worktree control: add, switch to, or delete worktrees,
            |          optionally removing their corresponding branches
            |
            |Options:
            |  -h, --help
            |          Show help message
            ")"

            ["worktree_list"]="$(__fgb_stdout_unindented "
            |Usage: fgb worktree list [<args>]
            |
            |List all worktrees in a Git repository and exit
            |
            |Options:
            |  -s, --sort=<sort>
            |          Sort key passed to git for-each-ref --sort. \#
            |          Default: '$default_sort_order'. \#
            |          Prefix with - for descending order. \#
            |          Examples: refname, -authordate, \#
            |          -committerdate,committername
            |
            |  -d, --date-format=<date>
            |          Date column format (git for-each-ref). \#
            |          Default: '$default_date_format'. \#
            |          Examples: authordate:short, \#
            |          committerdate:format:'%Y-%m-%d %H:%M'
            |
            |  -u, --author-format=<author>
            |          Author column format (git for-each-ref). \#
            |          Default: '$default_author_format'. \#
            |          Examples: authoremail, \#
            |          %(committername) %(committeremail)
            |
            |  -p, --wt-path-display=<mode>
            |          How worktree paths are displayed. \#
            |          Default: '$c_wt_path_display'. Modes:
            |            tilde            $HOME replaced by ~ (default)
            |            absolute         full absolute path
            |            relative-cwd     relative to current directory
            |            relative-home    relative to $HOME (~/... prefix)
            |            relative-repo    relative to repo root (bare: same as relative-gitdir)
            |            relative-gitdir  relative to git common dir (e.g. ./wt/branch)
            |            relative-wt-base relative to worktree base path (e.g. ./branch)
            |            absolute-gitdir  git-common-dir prefix + relative path
            |            tilde-gitdir     same as absolute-gitdir with $HOME replaced by ~
            |
            |  -h, --help
            |          Show help message
            ")"

            ["worktree_manage"]="$(__fgb_stdout_unindented "
            |Usage: fgb worktree manage [<args>] [<query>]
            |
            |Switch to existing worktrees in the Git repository or delete them
            |
            |Query:
            |  <query>  Query to filter branches by using fzf
            |
            |Options:
            |  -s, --sort=<sort>
            |          Sort key passed to git for-each-ref --sort. \#
            |          Default: '$default_sort_order'. \#
            |          Prefix with - for descending order. \#
            |          Examples: refname, -authordate, \#
            |          -committerdate,committername
            |
            |  -d, --date-format=<date>
            |          Date column format (git for-each-ref). \#
            |          Default: '$default_date_format'. \#
            |          Examples: authordate:short, \#
            |          committerdate:format:'%Y-%m-%d %H:%M'
            |
            |  -u, --author-format=<author>
            |          Author column format (git for-each-ref). \#
            |          Default: '$default_author_format'. \#
            |          Examples: authoremail, \#
            |          %(committername) %(committeremail)
            |
            |  -p, --wt-path-display=<mode>
            |          How worktree paths are displayed. \#
            |          Default: '$c_wt_path_display'. Modes:
            |            tilde            $HOME replaced by ~ (default)
            |            absolute         full absolute path
            |            relative-cwd     relative to current directory
            |            relative-home    relative to $HOME (~/... prefix)
            |            relative-repo    relative to repo root (bare: same as relative-gitdir)
            |            relative-gitdir  relative to git common dir (e.g. ./wt/branch)
            |            relative-wt-base relative to worktree base path (e.g. ./branch)
            |            absolute-gitdir  git-common-dir prefix + relative path
            |            tilde-gitdir     same as absolute-gitdir with $HOME replaced by ~
            |
            |  FGB_WT_BASE_PATH_BARE / FGB_WT_BASE_PATH_REGULAR
            |          Template for the default worktree base directory.
            |          Relative paths are anchored to the git common dir.
            |          Placeholders: {repo_name}, {repo_name_short}
            |          Default: './wt'
            |          Example: '../worktrees/{repo_name_short}' (sibling dir)
            |
            |  -f, --force
            |          Skip the confirmation prompt before deleting \#
            |          branches or worktrees
            |
            |  -h, --help
            |          Show help message
            ")"

            ["worktree_add"]="$(__fgb_stdout_unindented "
            |Usage: fgb worktree add [<args>] [<query>]
            |
            |Add a new worktree based on a selected Git branch
            |
            |Query:
            |  <query>  Query to filter branches by using fzf
            |
            |Options:
            |  -s, --sort=<sort>
            |          Sort key passed to git for-each-ref --sort. \#
            |          Default: '$default_sort_order'. \#
            |          Prefix with - for descending order. \#
            |          Examples: refname, -authordate, \#
            |          -committerdate,committername
            |
            |  -d, --date-format=<date>
            |          Date column format (git for-each-ref). \#
            |          Default: '$default_date_format'. \#
            |          Examples: authordate:short, \#
            |          committerdate:format:'%Y-%m-%d %H:%M'
            |
            |  -u, --author-format=<author>
            |          Author column format (git for-each-ref). \#
            |          Default: '$default_author_format'. \#
            |          Examples: authoremail, \#
            |          %(committername) %(committeremail)
            |
            |  -p, --wt-path-display=<mode>
            |          How worktree paths are displayed. \#
            |          Default: '$c_wt_path_display'. Modes:
            |            tilde            $HOME replaced by ~ (default)
            |            absolute         full absolute path
            |            relative-cwd     relative to current directory
            |            relative-home    relative to $HOME (~/... prefix)
            |            relative-repo    relative to repo root (bare: same as relative-gitdir)
            |            relative-gitdir  relative to git common dir (e.g. ./wt/branch)
            |            relative-wt-base relative to worktree base path (e.g. ./branch)
            |            absolute-gitdir  git-common-dir prefix + relative path
            |            tilde-gitdir     same as absolute-gitdir with $HOME replaced by ~
            |
            |  FGB_WT_BASE_PATH_BARE / FGB_WT_BASE_PATH_REGULAR
            |          Template for the default worktree base directory.
            |          Relative paths are anchored to the git common dir.
            |          Placeholders: {repo_name}, {repo_name_short}
            |          Default: './wt'
            |          Example: '../worktrees/{repo_name_short}' (sibling dir)
            |
            |  -r, --remotes
            |          List remote branches only (default: local only)
            |
            |  -a, --all
            |          List both local and remote branches
            |
            |  -c, --confirm
            |          Skip the interactive path prompt when adding a worktree. \#
            |          The path is derived automatically as <base-path>/<branch-name>. \#
            |          Without this flag the prompt is shown pre-filled with the branch \#
            |          name so you can edit it before confirming. Use ctrl-v during fzf \#
            |          to override this flag and force the prompt for a single selection.
            |
            |  -f, --force
            |          Skip the confirmation prompt before deleting \#
            |          branches or worktrees
            |
            |  -h, --help
            |          Show help message
            ")"

            ["worktree_total"]="$(__fgb_stdout_unindented "
            |Usage: fgb worktree total [<args>] [<query>]
            |
            |Add a new one, switch to an existing worktree in the Git repository, \#
            |or delete them, optionally with corresponding branches
            |
            |Query:
            |  <query>  Query to filter branches by using fzf
            |
            |Options:
            |  -s, --sort=<sort>
            |          Sort key passed to git for-each-ref --sort. \#
            |          Default: '$default_sort_order'. \#
            |          Prefix with - for descending order. \#
            |          Examples: refname, -authordate, \#
            |          -committerdate,committername
            |
            |  -d, --date-format=<date>
            |          Date column format (git for-each-ref). \#
            |          Default: '$default_date_format'. \#
            |          Examples: authordate:short, \#
            |          committerdate:format:'%Y-%m-%d %H:%M'
            |
            |  -u, --author-format=<author>
            |          Author column format (git for-each-ref). \#
            |          Default: '$default_author_format'. \#
            |          Examples: authoremail, \#
            |          %(committername) %(committeremail)
            |
            |  -p, --wt-path-display=<mode>
            |          How worktree paths are displayed. \#
            |          Default: '$c_wt_path_display'. Modes:
            |            tilde            $HOME replaced by ~ (default)
            |            absolute         full absolute path
            |            relative-cwd     relative to current directory
            |            relative-home    relative to $HOME (~/... prefix)
            |            relative-repo    relative to repo root (bare: same as relative-gitdir)
            |            relative-gitdir  relative to git common dir (e.g. ./wt/branch)
            |            relative-wt-base relative to worktree base path (e.g. ./branch)
            |            absolute-gitdir  git-common-dir prefix + relative path
            |            tilde-gitdir     same as absolute-gitdir with $HOME replaced by ~
            |
            |  FGB_WT_BASE_PATH_BARE / FGB_WT_BASE_PATH_REGULAR
            |          Template for the default worktree base directory.
            |          Relative paths are anchored to the git common dir.
            |          Placeholders: {repo_name}, {repo_name_short}
            |          Default: './wt'
            |          Example: '../worktrees/{repo_name_short}' (sibling dir)
            |
            |  -r, --remotes
            |          List remote branches only (default: local only)
            |
            |  -a, --all
            |          List both local and remote branches
            |
            |  -c, --confirm
            |          Skip the interactive path prompt when adding a worktree. \#
            |          The path is derived automatically as <base-path>/<branch-name>. \#
            |          Without this flag the prompt is shown pre-filled with the branch \#
            |          name so you can edit it before confirming. Use ctrl-v during fzf \#
            |          to override this flag and force the prompt for a single selection.
            |
            |  -f, --force
            |          Skip the confirmation prompt before deleting \#
            |          branches or worktrees
            |
            |  -h, --help
            |          Show help message
            ")"
        )

        # Define command and adjust arguments
        local fgb_command="${1:-}"
        [[ $# -gt 0 ]] && shift
        local fgb_subcommand="${1:-}"

        local WIDTH_OF_WINDOW
        WIDTH_OF_WINDOW="$(tput cols)"

        case "$fgb_command" in
            branch)
                case "$fgb_subcommand" in
                    "")
                        echo -e "error: need a subcommand" >&2
                        echo "${usage_message[$fgb_command]}" >&2
                        return 1
                        ;;
                    *) __fgb_branch "$@" ;;
                esac
                ;;
            worktree)
                case "$fgb_subcommand" in
                    "")
                        echo -e "error: need a subcommand" >&2
                        echo "${usage_message[$fgb_command]}" >&2
                        return 1
                        ;;
                    *) __fgb_worktree "$@" ;;
                esac
                ;;
            -h | --help | help)
                echo "${usage_message[fgb]}"
                ;;
            -v | --version | version)
                echo "$version_message"
                echo "$copyright_message"
                ;;
            --* | -*)
                echo "error: unknown option: \`$fgb_command'" >&2
                echo "${usage_message[fgb]}" >&2
                return 1
                ;;
            "")
                echo "${usage_message[fgb]}" >&2
                return 1
                ;;
            *)
                echo "fgb: '$fgb_command' is not a fgb command. See 'fgb --help'." >&2
                return 1
                ;;
        esac
    }

    # Start here
    __fgb__functions "$@"
    local exit_code="$?"

    unset -f \
        __fgb__functions \
        __fgb_branch \
        __fgb_branch_list \
        __fgb_format_wt_path \
        __fgb_branch_manage \
        __fgb_branch_set_vars \
        __fgb_confirmation_dialog \
        __fgb_expand_env \
        __fgb_normalize_path \
        __fgb_canonical_path \
        __fgb_relative_path \
        __fgb_render_relative \
        __fgb_tilde_path \
        __fgb_convert_git_format_string \
        __fgb_extract_date_format \
        __fgb_git_branch_delete \
        __fgb_git_branch_list \
        __fgb_git_branch_new \
        __fgb_git_worktree_delete \
        __fgb_git_worktree_for_new_branch \
        __fgb_git_worktree_jump_or_add \
        __fgb_build_remote_wt_map \
        __fgb_offer_reset_to_remote \
        __fgb_git_worktree_restore_stash \
        __fgb_print_branch_info \
        __fgb_set_spacer_var \
        __fgb_stdout_unindented \
        __fgb_transform_git_format_string \
        __fgb_worktree \
        __fgb_worktree_add \
        __fgb_worktree_list \
        __fgb_worktree_manage \
        __fgb_worktree_set_vars \
        __fgb_worktree_total

    return "$exit_code"
}
