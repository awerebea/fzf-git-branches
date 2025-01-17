# Description: Manage Git branches and worktrees with fzf

command -v fzf >/dev/null 2>&1 || return

fgb() {
    local VERSION="0.16.0"

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
                read -rk 1 ANS
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
            # remove indentation
            sed '1d;s/^[^|]*|//;$d' <<< "$(sed -z 's/\\#\n[^|]*|//g' <<< "$1")"
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
                array_of_lines+=( "$line" )
            done <<< "$branches_to_delete"
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
                    branch_name="${branch_name:1}"; branch_name="${branch_name%?}"
                    # Remove everything after the first slash
                    remote_name="${branch_name%%/*}"
                    # Remove the first segment of the reference name (<upstream>/)
                    branch_name="${branch_name#*/}"
                elif [[ "$branch_name" == "$c_bracket_loc_open"*"$c_bracket_loc_close" ]]; then
                    # Remove the first and the last characters (brackets)
                    branch_name="${branch_name:1}"; branch_name="${branch_name%?}"
                else
                    echo "error: invalid branch name pattern: $branch_name" >&2
                    return 1
                fi

                if [[ "$c_extend_del" == true ]]; then
                    if [[ "$is_remote" == true ]]; then
                        # Find local branch that tracks the selected remote branch
                        local_branches="$(__fgb_git_branch_list "local")"
                        return_code=$?; [[ $return_code -ne 0 ]] && return "$return_code"
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
                        done <<< "$(cut -d: -f1 <<< "$local_branches")"
                    else
                        # Find upstream branch for the selected local branch
                        local_tracking="$branch_name"
                        remote_tracking="$(
                            git  for-each-ref --format '%(upstream)' "refs/heads/$branch_name"
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
                    # NOTE: Avoid --force here as it's no undoable operation for remote branches
                    if __fgb_confirmation_dialog "$user_prompt"; then
                        git push --delete "$remote_name" "$branch_name" || return $?
                        if [[ "$c_extend_del" == true ]]; then
                            if [[ -n "$local_tracking" ]]; then
                                branch="$c_bracket_loc_open"
                                branch+="${local_tracking#refs/heads/}"
                                branch+="$c_bracket_loc_close"
                                __fgb_git_branch_delete "$branch"
                            fi
                        fi
                    fi
                else
                    user_prompt=$(__fgb_stdout_unindented "
                        |${col_r_bold}Delete${col_reset} \#
                        |local branch: \`${col_b_bold}${branch_name}${col_reset}'?
                    ")
                    if [[ "$c_force" == true ]] || __fgb_confirmation_dialog "$user_prompt"; then
                        if ! output="$(git branch -d "$branch_name" 2>&1)"; then
                            local head_branch; head_branch="$(git rev-parse --abbrev-ref HEAD)"
                            error_pattern="^error: the branch '$branch_name' is not fully merged\.\?$"
                            if ! grep -q "$error_pattern" <<< "$output"; then
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
                                git branch -D "$branch_name" || return $?
                            fi
                        else
                            echo "$output"
                            if [[ "$c_extend_del" == true ]]; then
                                if [[ -n "$remote_tracking" ]]; then
                                    branch="$c_bracket_rem_open"
                                    branch+="${remote_tracking#refs/remotes/}"
                                    branch+="$c_bracket_rem_close"
                                    __fgb_git_branch_delete "$branch"
                                fi
                            fi
                        fi
                    fi
                fi
            done
        }

        __fgb_git_branch_list() {
            # List branches in a git repository

            # shellcheck disable=SC2076
            if [[ $# -lt 1  ]]; then
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

            local ref_type refs return_code git_cmd line
            git_cmd="git for-each-ref "
            git_cmd+="--format=\"$(\
                printf '%%(refname)%b%s%b%s' \
                    "$c_split_char" \
                    "$c_author_format" \
                    "$c_split_char" \
                    "$c_date_format"
                )\" "
            while IFS= read -r line; do
                git_cmd+="--sort=\"$line\" "
            done < <(tr ',' '\n' <<< "$c_branch_sort_order")
            for ref_type in "${ref_types[@]}"; do
                refs=$(eval "$git_cmd refs/$ref_type")
                return_code=$?; [[ $return_code -ne 0 ]] && return "$return_code"
                if [[ -n "$filter_list" ]]; then
                    echo "$refs" | grep "$(
                        sed "s/^/^/; s/$/$(printf "%b" "$c_split_char")/" <<< "$filter_list"
                    )"
                else
                    echo "$refs"
                fi
            done
        }

        __fgb_branch_set_vars() {
            # Define branch related variables

            if [ $# -ne 1 ]; then
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
                c_date_width="$((
                    date_curr_width > c_date_width ?
                    date_curr_width :
                    c_date_width
                ))"
                # Calculate column widths
                branch_curr_width="${#branch_name}"
                c_branch_width="$((
                    branch_curr_width > c_branch_width ?
                    branch_curr_width :
                    c_branch_width
                ))"
                # Trim long author names with multiple parts delimited by '/'
                author_curr_width="${#author_name}"
                if [[ "$author_curr_width" -gt 25 && "$author_name" == *"/"* ]]; then
                    author_name=".../${author_name#*/}"
                    c_branch_author_map["$branch"]="$author_name"
                    author_curr_width="${#author_name}"
                fi

                c_author_width="$((
                    author_curr_width > c_author_width ?
                    author_curr_width :
                    c_author_width
                ))"
            done <<< "$branch_list"
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
                branch_name="${branch_name#*/}"; branch_name="${branch_name#*/}"
                # Adjust the branch name column width based on the number of color code characters
                printf \
                    "%-$(( c_branch_width + 13 ))b" \
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
            done <<< "$c_branches"
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
                c_total_width="$(( c_branch_width + c_author_width + c_date_width + 5 ))"

                if [ "$c_total_width" -gt "$WIDTH_OF_WINDOW" ]; then
                    c_show_author=false
                    c_total_width="$(( c_total_width - c_author_width ))"
                fi

                if [ "$c_total_width" -gt "$WIDTH_OF_WINDOW" ]; then
                    c_show_date=false
                    c_total_width="$(( c_total_width - c_date_width ))"
                fi

                # Calculate spacers
                num_spacers=2
                c_spacer="$(
                    echo "$WIDTH_OF_WINDOW $c_total_width $num_spacers" | \
                        awk '{printf("%.0f", ($1 - $2) / $3)}'
                )"
                [ "$c_spacer" -le 0 ] && c_spacer=1 || c_spacer=$(( c_spacer < 4 ? c_spacer : 4 ))
            elif [[ $list_type == "worktree" ]]; then
                # Add 5 to avoid truncating the date column
                c_total_width="$((
                        c_branch_width + c_wt_path_width + c_author_width + c_date_width + 5
                ))"

                if [ "$c_total_width" -gt "$WIDTH_OF_WINDOW" ]; then
                    c_show_wt_path=false
                    c_show_wt_flag=true
                    c_total_width="$(( c_total_width - c_wt_path_width + 1 ))"
                fi

                if [ "$c_total_width" -gt "$WIDTH_OF_WINDOW" ]; then
                    c_show_author=false
                    c_total_width="$(( c_total_width - c_author_width ))"
                fi

                if [ "$c_total_width" -gt "$WIDTH_OF_WINDOW" ]; then
                    c_show_date=false
                    c_total_width="$(( c_total_width - c_date_width ))"
                fi

                # Calculate spacers
                num_spacers=3
                if [[ "$c_show_wt_flag" == true ]]; then
                    num_spacers="$(( num_spacers + 1 ))"
                    c_total_width="$(( c_total_width + 2 ))"
                fi
                c_spacer="$(
                    echo "$WIDTH_OF_WINDOW $c_total_width $num_spacers" | \
                        awk '{printf("%.0f", ($1 - $2) / $3)}'
                )"
                [ "$c_spacer" -le 0 ] && c_spacer=1 || c_spacer=$(( c_spacer < 4 ? c_spacer : 4 ))
            fi
        }

        __fgb_print_branch_info() {
            # Pring branch information

            if [[ $# -lt 1  ]]; then
                echo "$0 error: missing argument: branch_name" >&2
                return 1
            fi

            local branch="$1"

            local -A values=(
                ["1.branch"]="$branch"
                ["2.worktree"]="${c_worktree_path_map["refs/heads/${branch}"]}"
                ["3.author"]="$(git log -1 --pretty=format:"%an <%ae>" "$branch")"
                ["4.authordate"]="$(git log -1 --format="%ad" --date=iso "$branch")"
                ["5.committer"]="$(git log -1 --pretty=format:"%cn <%ce>" "$branch")"
                ["6.committerdate"]="$(git log -1 --format="%cd" --date=iso "$branch")"
                ["7.HEAD"]="$(git rev-parse "$branch")"
                ["8.message"]="$(git log -1 --format="%B" "$branch")"
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
                # shellcheck disable=2066,2296
                while IFS=$'\n' read -r line; do
                    keys+=("$line")
                done <<< "$(for key in "${(@k)values}"; do echo "$key"; done | sort -n)"
            else
                while IFS=$'\n' read -r line; do
                    keys+=("$line")
                done <<< "$(for key in "${!values[@]}"; do echo "$key"; done | sort -n)"
            fi

            local key_width max_width=0
            for key in "${keys[@]}"; do
                # Remove N. from the key
                key="${key:2}"
                key_width="${#key}"
                max_width="$(( key_width > max_width ? key_width : max_width ))"
            done

            local message_indent_width message_indent_str
            message_indent_width="$(( max_width + 3 ))"
            message_indent_str=$(printf "%${message_indent_width}s")

            for key in "${keys[@]}"; do
                [[ -n "${values[$key]}" ]] && \
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
            new_branch+="_fork"
            if [[ -n "${ZSH_VERSION-}" ]]; then
                vared -p "$message " new_branch
            else
                echo -en "${message}${col_r}"
                IFS= read -re -p " " -i "$new_branch" new_branch
                echo -en "$col_reset"
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
                printf "%$(( c_branch_width + 2 - ${#c_column_branch} + c_spacer ))s" " "
            )"
            spacer_authour="$(printf "%$(( c_author_width - ${#c_column_author} + c_spacer ))s" " ")"

            header_column_names_row="${c_column_branch}${spacer_branch}"
            [[ "$c_show_author" == true ]] && \
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
            local fzf_cmd="\
                $FZF_CMD_GLOB \
                    --expect='"$c_del_key,$c_extend_del_key,$c_info_key,$c_new_branch_key"' \
                    --header '$header' \
                "

            [[ $# -gt 0 ]] && fzf_cmd+=" --query='$*'"

            local lines; lines="$(__fgb_branch_list | eval "$fzf_cmd" | cut -d' ' -f1)"

            [[ -z "$lines" ]] && return

            local key; key="$(head -1 <<< "$lines")"

            local is_remote=false

            local branch; branch="$(tail -1 <<< "$lines")"
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
                "$c_del_key") __fgb_git_branch_delete "$(sed 1d <<< "$lines")" ;;
                "$c_extend_del_key")
                    c_extend_del=true
                    __fgb_git_branch_delete "$(sed 1d <<< "$lines")"
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

            if [[ $# -ne 1  ]]; then
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

            input_string="$(sed -E "s/$regexp/%(\1)/g" <<< "$input_string")"
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

            extracted="$(grep -oE "$regexp" <<< "$input_string")"

            if [[ -n "$extracted" ]]; then
                sed -E "s/$regexp/%\1$c_split_char\2/" <<< "$extracted" |
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
                    while [ $# -gt 0 ]; do
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
                                while [ $# -gt 1 ]; do
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
                    [[ "$branch_show_remote" == true ]] && \
                        branch_type="remote" || \
                        branch_type="local"
                    [[ "$branch_show_all" == true ]] && branch_type="all"

                    local return_code
                    c_branches="$(__fgb_git_branch_list "$branch_type")"
                    return_code=$?; [[ $return_code -ne 0 ]] && return "$return_code"
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
                is_remote \
                output \
                success_message \
                user_prompt \
                worktrees_to_delete="$1" \
                wt_path \
                line

            local -a array_of_lines

            while IFS= read -r line; do
                array_of_lines+=( "$line" )
            done <<< "$worktrees_to_delete"
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
                branch_name="${branch_name:1}"; branch_name="${branch_name%?}"
                [[ ! "$is_remote" == true ]] && \
                    wt_path="${c_worktree_path_map["refs/heads/${branch_name}"]}"
                if [[ -n "$wt_path" ]]; then
                    # Process a branch with a corresponding worktree
                    is_in_target_wt=false
                    if [[ "$PWD" == "$wt_path" ]]; then
                        cd "$c_bare_repo_path" && is_in_target_wt=true || return 1
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
                            if ! grep -q "$error_pattern" <<< "$output"; then
                                echo "$output"
                                continue
                            fi
                            user_prompt=$(__fgb_stdout_unindented "
                                |
                                |${col_r_bold}WARNING:${col_reset} \#
                                |This will permanently reset/delete the following files:
                                |
                                |$(script -q /dev/null -c "git -C \"$wt_path\" status --short")
                                |
                                |in the ${col_y_bold}${wt_path}${col_reset} path.
                                |
                                |Are you sure you want to proceed?
                            ")
                            # NOTE: Avoid --force here as it's not undoable operation
                            if __fgb_confirmation_dialog "$user_prompt"; then
                                if output="$(git worktree remove "$wt_path" --force)"; then
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
                                    cd "$wt_path" || return 1
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
                            cd "$wt_path" || return 1
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

        __fgb_git_worktree_jump_or_add() {
            # Jump to an existing worktree or add a new one for a given branch

            if [ $# -eq 0 ]; then
                echo "Missing argument: branch name" >&2
                return 1
            fi

            local \
                branch_name="$1" \
                remote_branch \
                wt_path \
                message \
                ref_prefix
            # shellcheck disable=SC2053
            if [[ "$branch_name" == "$c_bracket_rem_open"*/*"$c_bracket_rem_close" ]]; then
                # Remove the first and the last characters (brackets)
                remote_branch="${branch_name:1}"; remote_branch="${remote_branch%?}"
                # Remove the first segment of the reference name (<upstream>/)
                branch_name="${remote_branch#*/}"
                ref_prefix="refs/remotes/"
            elif [[ "$branch_name" == "$c_bracket_loc_open"*"$c_bracket_loc_close" ]]; then
                branch_name="${branch_name:1}"; branch_name="${branch_name%?}"
                ref_prefix="refs/heads/"
            elif [[ "$branch_name" == "$c_bracket_det_open"*"$c_bracket_det_close" ]]; then
                branch_name="${branch_name:1}"; branch_name="${branch_name%?}"
                ref_prefix="$c_detached_wt_prefix"
            else
                echo "error: invalid branch name pattern: $branch_name" >&2
                return 1
            fi
            wt_path="${c_worktree_path_map["$ref_prefix$branch_name"]}"
            if [[ -n "$wt_path" ]]; then
                cd "$wt_path" || return 1
                message=$(__fgb_stdout_unindented "
                    |${col_g_bold}Jumped${col_reset} to worktree: \#
                    |${col_y_bold}${wt_path}${col_reset}, \#
                    |for branch '${col_b_bold}${branch_name}${col_reset}'
                ")
                echo -e "$message"
            else
                if [[ "$c_confirmed" == true ]]; then
                    wt_path="${c_bare_repo_path}/${branch_name}"
                else
                    if [[ -n "$remote_branch" ]]; then
                        printf "%b\n" "$(__fgb_stdout_unindented "
                        |Add a new worktree for '${col_b_bold}${branch_name}${col_reset}' \#
                        |(remote branch: '${col_y_bold}${remote_branch}${col_reset}').
                        |The path to the worktree must be absolute \#
                        |or relative to the path to the bare repository.
                        ")"
                    else
                        printf "%b\n" "$(__fgb_stdout_unindented "
                        |Add a new worktree for '${col_b_bold}${branch_name}${col_reset}'.
                        |The path to the worktree must be absolute \#
                        |or relative to the path to the bare repository.
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
                    [[ "$wt_path" != /* ]] && wt_path="${c_bare_repo_path}/${wt_path}"
                    wt_path="$(readlink -m "$wt_path")" # Normalize the path
                fi
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

        __fgb_worktree_list() {
            # List worktrees in a git repository

            __fgb_set_spacer_var "worktree"

            local branch wt_path author_name author_date bracket_open bracket_close
            while IFS= read -r branch; do
                branch="${branch%%"$c_split_char"*}"
                branch_name="$branch"
                if [[ "$branch" == refs/heads/* ]]; then
                    # Remove first two segments of the reference name
                    branch_name="${branch_name#*/}"; branch_name="${branch_name#*/}"
                    # Define the bracket characters
                    bracket_open="$c_bracket_loc_open" bracket_close="$c_bracket_loc_close"
                elif [[ "$branch" == refs/remotes/* ]]; then
                    # Remove first two segments of the reference name
                    branch_name="${branch_name#*/}"; branch_name="${branch_name#*/}"
                    # Define the bracket characters
                    bracket_open="$c_bracket_rem_open" bracket_close="$c_bracket_rem_close"
                elif [[ "$branch" == "$c_detached_wt_prefix"* ]]; then
                    # Remove first two segments of the reference name
                    branch_name="${branch_name#*/}"; branch_name="${branch_name#*/}"
                    # Define the bracket characters
                    bracket_open="$c_bracket_det_open" bracket_close="$c_bracket_det_close"
                fi
                # Adjust the branch name column width based on the number of color code characters
                printf \
                    "%-$(( c_branch_width + 13 ))b" \
                    "${bracket_open}${col_y_bold}${branch_name}${col_reset}${bracket_close}"
                if [[ "$c_show_wt_path" == true ]]; then
                    if [[ -n "${c_worktree_path_map["$branch"]}" ]]; then
                        wt_path="${c_worktree_path_map["$branch"]}"
                        [ "$wt_path" != "" ] && \
                            wt_path="$(realpath --relative-to="$c_bare_repo_path" "$wt_path")"
                        [[ ! "$wt_path" =~ ^\.\./ ]] && wt_path="./$wt_path"
                    else
                        wt_path=" "
                    fi
                    printf \
                        "%${c_spacer}s${col_bold}%-${c_wt_path_width}s${col_reset}" \
                        " " \
                        "$wt_path"
                fi
                if [[ "$c_show_wt_flag" == true ]]; then
                    [[ -n "${c_worktree_path_map["$branch"]}" ]] && wt_path="+" || wt_path=" "
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
            done <<< "$c_branches"
        }

        __fgb_git_worktree_restore_stash() {
            # Restore a specific stash to the current worktree or fallback to the initial worktree
            # if needed

            if ! "$(git rev-parse --is-inside-work-tree)"; then
                echo "fatal: this operation must be run in a work tree" >&2
                return 128
            fi

            if [[ $# -eq 0 ]]; then
                echo "$0 error: missing arguments: stash_message, init_wt_path" >&2
                return 1
            elif [[ $# -lt 2 ]]; then
                echo "$0 error: missing argument: init_wt_path" >&2
                return 1
            fi

            local stash_message="$1"
            local init_wt_path="$2"

            local stash_id
            stash_id="$(
                git -C "$PWD" stash list | grep -F "$stash_message" | head -n 1 | cut -d":" -f1
            )"

            local output
            output="$(script -q /dev/null -c "git -C \"$PWD\" stash apply \"$stash_id\" 2>&1")"

            local return_code
            if grep -Eq "^(ERROR|FAILED|CONFLICT)" <<< "$output"; then
                return_code=1
            else
                return_code=0
            fi

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
                git -C "$init_wt_path" stash apply "$stash_id" &>/dev/null
                git -C "$init_wt_path" stash drop "$stash_id" &>/dev/null
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
                stash_message \
                user_prompt

            # Check if the current directory is a Git worktree
            if "$(git rev-parse --is-inside-work-tree)"; then
                init_wt_path="$PWD"
                # Check if there are any changes in the working directory
                if ! git diff --quiet || ! git diff --cached --quiet; then
                    # Show changed files in the working directory ignoring untracked files
                    user_prompt=$(__fgb_stdout_unindented "
                        |
                        |${col_y_bold}INFO:${col_reset} \#
                        |The current worktree has uncommitted changes:
                        |
                        |$(script -q /dev/null -c "git status --short -uno")
                        |
                        |Do you want to try to stash and pop them in a new worktree?
                    ")
                    if __fgb_confirmation_dialog "$user_prompt"; then
                        current_date="$(date +"%Y-%m-%d %H:%M:%S")"
                        stash_message="[$current_date] Stash to restore in a new worktree"
                        stash_message+=" for branch '${c_new_branch:1:-1}'"
                        git stash push -m "$stash_message" && stash_created=true
                    fi
                fi
            fi

            local return_code
            local temp_file; temp_file=$(mktemp)

            __fgb_git_worktree_jump_or_add "$c_new_branch" 2>|"$temp_file"
            return_code=$?

            local output; output=$(cat "$temp_file")
            rm "$temp_file"
            if [[ $return_code -ne 0 ]]; then
                local error_pattern="^fatal: '.*/${c_new_branch:1:-1}' already exists$"
                if ! grep -q "$error_pattern" <<< "$output"; then
                    echo "$output" >&2
                else
                    user_prompt=$(__fgb_stdout_unindented "
                        |
                        |${col_r_bold}WARNING:${col_reset} \#
                        |The path \#
                        |'${col_y_bold}${c_bare_repo_path}\#
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
            "$stash_created" && __fgb_git_worktree_restore_stash "$stash_message" "$init_wt_path"
            return "$return_code"
        }

        __fgb_worktree_add() {
            # Add a new worktree for a given branch

            local line branch upstream wt_branch
            c_branches="$(while IFS= read -r line; do
                    branch="${line%%"$c_split_char"*}"
                    grep -q -E "${branch}$" <<< "$c_worktree_branches" && continue
                    if [[ "$branch" == refs/remotes/* ]]; then
                        while IFS= read -r wt_branch; do
                            upstream="$(
                                git \
                                    for-each-ref \
                                    --format \
                                    '%(upstream)' "$wt_branch"
                            )"
                            [[ "$branch" == "$upstream" ]] && continue 2
                        done <<< "$c_worktree_branches"
                    fi
                    echo "$line"
            done <<< "$c_branches")"

            __fgb_branch_set_vars "$c_branches"
            __fgb_set_spacer_var "worktree"

            local \
                spacer_branch=" " \
                spacer_author=" " \
                header_column_names_row

            spacer_branch="$(
                printf "%$(( c_branch_width + 2 - ${#c_column_branch} + c_spacer ))s" " "
            )"
            spacer_author="$(printf "%$(( c_author_width - ${#c_column_author} + c_spacer ))s" " ")"

            header_column_names_row="${c_column_branch}${spacer_branch}"
            [[ "$c_show_author" == true ]] && \
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

            # shellcheck disable=SC2027
            local fzf_cmd="\
                $FZF_CMD_GLOB \
                    --expect='"$expected_keys"' \
                    --header '$header' \
                "

            [[ $# -gt 0 ]] && fzf_cmd+=" --query='$*'"

            local lines; lines="$(
                __fgb_branch_list | \
                    eval "$fzf_cmd" | \
                    cut -d' ' -f1
            )"

            [[ -z "$lines" ]] && return

            local key; key="$(head -1 <<< "$lines")"
            branch="$(tail -1 <<< "$lines")"
            local branch_type=""

            case "${branch:0:1}" in
                "$c_bracket_loc_open") branch_type="local" ;;
                "$c_bracket_rem_open") branch_type="remote" ;;
            esac

            case $key in
                "$c_del_key") __fgb_git_branch_delete "$(sed 1d <<< "$lines")" ;;
                "$c_extend_del_key")
                    c_extend_del=true
                    __fgb_git_branch_delete "$(sed 1d <<< "$lines")"
                    ;;
                "$c_info_key")
                    # Remove the first and the last characters (brackets)
                    branch="${branch:1:-1}"
                    __fgb_print_branch_info "$branch"
                    ;;
                "$c_verbose_key") c_confirmed=false; __fgb_git_worktree_jump_or_add "$branch" ;;
                "$c_new_branch_key" | "$c_new_branch_verbose_key")
                    local return_code for_new_worktree=true
                    __fgb_git_branch_new "${branch:1:-1}" "$branch_type" "$for_new_worktree"
                    return_code=$?; [[ $return_code -ne 0 ]] && return "$return_code"
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
                printf "%$(( c_branch_width + 2 - ${#c_column_branch} + c_spacer ))s" " "
            )"
            if [[ "$c_show_wt_path" == true ]]; then
                spacer_wt="$(printf "%$(( c_wt_path_width - ${#column_wt} + c_spacer ))s" " ")"
            elif [[ "$c_show_wt_flag" == true ]]; then
                column_wt="W"
                spacer_wt="$(printf "%$(( 1 - ${#column_wt} + c_spacer ))s" " ")"
            fi
            spacer_author="$(printf "%$(( c_author_width - ${#c_column_author} + c_spacer ))s" " ")"

            header_column_names_row="${c_column_branch}${spacer_branch}"
            [[ "$c_show_wt_path" == true || "$c_show_wt_flag" == true ]] && \
                header_column_names_row+="${column_wt}${spacer_wt}"
            [[ "$c_show_author" == true ]] && \
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

            # shellcheck disable=SC2027
            local fzf_cmd="\
                $FZF_CMD_GLOB \
                    --expect='"$expected_keys"' \
                    --header '$header' \
                "

            [[ $# -gt 0 ]] && fzf_cmd+=" --query='$*'"

            local lines; lines="$(__fgb_worktree_list | eval "$fzf_cmd" | cut -d' ' -f1)"

            [[ -z "$lines" ]] && return

            local key; key="$(head -1 <<< "$lines")"
            local branch; branch="$(tail -1 <<< "$lines")"
            local branch_type=""

            case "${branch:0:1}" in
                "$c_bracket_loc_open") branch_type="local" ;;
                "$c_bracket_rem_open") branch_type="remote" ;;
            esac

            case $key in
                "$c_del_key") __fgb_git_worktree_delete "$(sed 1d <<< "$lines")" ;;
                "$c_extend_del_key")
                    c_extend_del=true
                    __fgb_git_worktree_delete "$(sed 1d <<< "$lines")"
                    ;;
                "$c_info_key")
                    # Remove the first and the last characters (brackets)
                    branch="${branch:1:-1}"
                    __fgb_print_branch_info "$branch"
                    ;;
                "$c_verbose_key") c_confirmed=false; __fgb_git_worktree_jump_or_add "$branch" ;;
                "$c_new_branch_key" | "$c_new_branch_verbose_key")
                    local return_code for_new_worktree=true
                    __fgb_git_branch_new "${branch:1:-1}" "$branch_type" "$for_new_worktree"
                    return_code=$?; [[ $return_code -ne 0 ]] && return "$return_code"
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
                printf "%$(( c_branch_width + 2 - ${#c_column_branch} + c_spacer ))s" " "
            )"
            if [[ "$c_show_wt_path" == true ]]; then
                spacer_wt="$(printf "%$(( c_wt_path_width - ${#column_wt} + c_spacer ))s" " ")"
            elif [[ "$c_show_wt_flag" == true ]]; then
                column_wt="W"
                spacer_wt="$(printf "%$(( 1 - ${#column_wt} + c_spacer ))s" " ")"
            fi
            spacer_author="$(printf "%$(( c_author_width - ${#c_column_author} + c_spacer ))s" " ")"

            header_column_names_row="${c_column_branch}${spacer_branch}"
            [[ "$c_show_wt_path" == true  || "$c_show_wt_flag" == true ]] && \
                header_column_names_row+="${column_wt}${spacer_wt}"
            [[ "$c_show_author" == true ]] && \
                header_column_names_row+="${c_column_author}${spacer_author}"
            [[ "$c_show_date" == true ]] && header_column_names_row+="$c_column_date"

            local header="Manage Git Worktrees:"
            header+=" ${c_del_key}:del, ${c_extend_del_key}:extended-del, ${c_info_key}:info"
            [[ -n "$c_bind_keys" ]] && header+=", $c_bind_keys"
            header+=$(__fgb_stdout_unindented "
                |
                |$header_column_names_row
            ")
            local fzf_cmd="\
                $FZF_CMD_GLOB \
                    --expect='"$c_del_key,$c_extend_del_key,$c_info_key"' \
                    --header '$header' \
                "

            [[ $# -gt 0 ]] && fzf_cmd+=" --query='$*'"

            local lines; lines="$(__fgb_worktree_list | eval "$fzf_cmd" | cut -d' ' -f1)"

            [[ -z "$lines" ]] && return

            local key; key="$(head -1 <<< "$lines")"

            local branch; branch="$(tail -1 <<< "$lines")"
            case $key in
                "$c_del_key") __fgb_git_worktree_delete "$(sed 1d <<< "$lines")" ;;
                "$c_extend_del_key")
                    c_extend_del=true
                    __fgb_git_worktree_delete "$(sed 1d <<< "$lines")"
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

            c_bare_repo_path="$(
                git worktree list | \
                    grep " (bare)$" | \
                    rev | \
                    cut -d' ' -f2- | \
                    sed 's/^[[:space:]]*//' | \
                    rev
            )"

            local wt_list; wt_list="$(git worktree list --porcelain | sed '1,3d' |
                awk -v split_char="$c_split_char" -v ref_prefix="$c_detached_wt_prefix" '
                    /^worktree/ {
                        path = $2
                    }
                    /^HEAD/ {
                        hash = $2
                    }
                    /^branch/ {
                        branch = $2
                        printf "%s%s%s\n", path, split_char, branch
                    }
                    /^detached/ {
                        printf "%s%s%s%.7s\n", path, split_char, ref_prefix, hash
                }')"

            c_worktree_branches="$(
                awk -v split_char="$c_split_char" -F"$c_split_char" '{print $2}' <<< "$wt_list"
            )"

            local \
                branch \
                line \
                wt_path \
                wt_path_curr_width
            while IFS= read -r line; do
                [ "$line" = "" ] && break
                branch="${line#*"$c_split_char"}"
                c_worktree_path_map["$branch"]="${line%"$c_split_char"*}"
                # Calculate column widths
                wt_path="${c_worktree_path_map["$branch"]}"
                [ "$wt_path" != "" ] && \
                    wt_path="$(realpath --relative-to="$c_bare_repo_path" "$wt_path")"
                [[ ! "$wt_path" =~ ^\.\./ ]] && wt_path="./$wt_path"
                wt_path_curr_width="${#wt_path}"
                c_wt_path_width="$((
                        wt_path_curr_width > c_wt_path_width ?
                        wt_path_curr_width :
                        c_wt_path_width
                ))"
            done <<< "$wt_list"
        }

        __fgb_worktree() {
            # Manage Git worktrees

            local subcommand="$1"
            shift
            case $subcommand in
                add | list | manage | total)
                    if ! (git worktree list | grep -q " (bare)$") &>/dev/null; then
                        echo "Not inside a bare Git repository. Exit..." >&2
                        return 128
                    fi

                    local -a fzf_query=()
                    local branch_show_remote=false branch_show_all=false
                    while [ $# -gt 0 ]; do
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
                            -f | --force) c_force=true ;;
                            -h | --help) echo "${usage_message[worktree_$subcommand]}" >&2 ;;
                            --)
                                if [[ "$subcommand" == "list" ]]; then
                                    echo "error: unknown option: \`$1'" >&2
                                    echo "       query not expected for the list command." >&2
                                    echo "${usage_message[branch_$subcommand]}" >&2
                                    return 1
                                fi
                                while [ $# -gt 1 ]; do
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
                    [[ "$branch_show_remote" == true ]] && \
                        branch_type="remote" || \
                        branch_type="local"
                    [[ "$branch_show_all" == true ]] && branch_type="all"

                    local filter_list
                    # shellcheck disable=SC2076
                    [[ " list manage " =~ " $subcommand " ]] && filter_list="$c_worktree_branches"

                    local return_code
                    c_branches="$(__fgb_git_branch_list "$branch_type" "$filter_list")"
                    return_code=$?; [[ $return_code -ne 0 ]] && return "$return_code"

                    local detached_wt
                    detached_wt="$(grep "^$c_detached_wt_prefix" <<< "$c_worktree_branches")"

                    # shellcheck disable=SC2076
                    if [[ -n "$detached_wt" && " local all " =~ " $branch_type " ]]; then
                        local \
                            line \
                            hash \
                            wt_hash_data \
                            author_format \
                            date_format \
                            log_format \
                            log_date \
                            log_output

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
                                log_output="$(git log -1 \
                                    --pretty=format:"$log_format" \
                                    --date="$log_date" \
                                    "$hash"
                                )"
                                wt_hash_data="$(
                                    sed "s/$c_split_char$regexp$c_split_char/$log_output/" <<< \
                                        "$wt_hash_data"
                                )"
                            done <<< "$dates_with_format"
                            c_branches="$line$c_split_char$wt_hash_data
                                $c_branches"
                        done <<< "$detached_wt"
                    fi

                    # Remove leading spaces
                    c_branches="$(sed 's/^[[:space:]]*//' <<< "$c_branches")"

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
        env_var_pattern+='FGB_(SORT_ORDER|DATE_FORMAT|AUTHOR_FORMAT|'
        env_var_pattern+='BINDKEY_(DEL|EXTEND_DEL|INFO|VERBOSE|NEW_BRANCH))*='
        if [[ -f "$fgbrc_file" ]]; then
            while IFS='=' read -r key value; do
                # Trim leading spaces
                key="${key#"${key%%[![:space:]]*}"}"
                # Check if the variable is defined in the environment
                [ "$(printenv "$key")" != "" ] && continue
                eval "local $key=$value"
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
            c_bare_repo_path \
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
            |  worktree  Manage worktrees in a Git repository
            |
            |Options:
            |  -v, --version
            |            Show version information
            |
            |  -h, --help
            |            Show help message
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
            |          Sort branches by <sort>: '$default_sort_order' (default)
            |
            |  -d, --date-format=<date>
            |          Format for <date> string: '$default_date_format' (default)
            |
            |  -u, --author-format=<author>
            |          Format for <author> string: '$default_author_format' (default)
            |
            |  -r, --remotes
            |          List remote branches
            |
            |  -a, --all
            |          List all branches
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
            |          Sort branches by <sort>: '$default_sort_order' (default)
            |
            |  -d, --date-format=<date>
            |          Format for <date> string: '$default_date_format' (default)
            |
            |  -u, --author-format=<author>
            |          Format for <author> string: '$default_author_format' (default)
            |
            |  -r, --remotes
            |          List remote branches
            |
            |  -a, --all
            |          List all branches
            |
            |  -f, --force
            |          Suppress confirmation dialog for non-destructive operations
            |
            |  -h, --help
            |          Show help message
            ")"

            ["worktree"]="$(__fgb_stdout_unindented "
            |Usage: fgb worktree <subcommand> [<args>]
            |
            |Subcommands:
            |  list    List all worktrees in a bare Git repository and exit
            |
            |  manage  Switch to existing worktrees in the bare Git repository or delete them
            |
            |  add     Add a new worktree based on a selected Git branch
            |
            |  total   Add a new one, switch to an existing worktree in the bare Git repository,
            |          or delete them, optionally with corresponding branches
            |
            |Options:
            |  -h, --help
            |          Show help message
            ")"

            ["worktree_list"]="$(__fgb_stdout_unindented "
            |Usage: fgb worktree list [<args>]
            |
            |List all worktrees in a bare Git repository and exit
            |
            |Options:
            |  -s, --sort=<sort>
            |          Sort branches by <sort>: '$default_sort_order' (default)
            |
            |  -d, --date-format=<date>
            |          Format for <date> string: '$default_date_format' (default)
            |
            |  -u, --author-format=<author>
            |          Format for <author> string: '$default_author_format' (default)
            |
            |  -h, --help
            |          Show help message
            ")"

            ["worktree_manage"]="$(__fgb_stdout_unindented "
            |Usage: fgb worktree manage [<args>] [<query>]
            |
            |Switch to existing worktrees in the bare Git repository or delete them
            |
            |Query:
            |  <query>  Query to filter branches by using fzf
            |
            |Options:
            |  -s, --sort=<sort>
            |          Sort branches by <sort>: '$default_sort_order' (default)
            |
            |  -d, --date-format=<date>
            |          Format for <date> string: '$default_date_format' (default)
            |
            |  -u, --author-format=<author>
            |          Format for <author> string: '$default_author_format' (default)
            |
            |  -f, --force
            |          Suppress confirmation dialog for non-destructive operations
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
            |          Sort branches by <sort>: '$default_sort_order' (default)
            |
            |  -d, --date-format=<date>
            |          Format for <date> string: '$default_date_format' (default)
            |
            |  -u, --author-format=<author>
            |          Format for <author> string: '$default_author_format' (default)
            |
            |  -r, --remotes
            |          List remote branches
            |
            |  -a, --all
            |          List all branches
            |
            |  -c, --confirm
            |          Automatic confirmation of the directory name for the new worktree
            |
            |  -f, --force
            |          Suppress confirmation dialog for non-destructive operations
            |
            |  -h, --help
            |          Show help message
            ")"

            ["worktree_total"]="$(__fgb_stdout_unindented "
            |Usage: fgb worktree total [<args>] [<query>]
            |
            |Add a new one, switch to an existing worktree in the bare Git repository, \#
            |or delete them, optionally with corresponding branches
            |
            |Query:
            |  <query>  Query to filter branches by using fzf
            |
            |Options:
            |  -s, --sort=<sort>
            |          Sort branches by <sort>: '$default_sort_order' (default)
            |
            |  -d, --date-format=<date>
            |          Format for <date> string: '$default_date_format' (default)
            |
            |  -u, --author-format=<author>
            |          Format for <author> string: '$default_author_format' (default)
            |
            |  -r, --remotes
            |          List remote branches
            |
            |  -a, --all
            |          List all branches
            |
            |  -c, --confirm
            |          Automatic confirmation of the directory name for the new worktree
            |
            |  -f, --force
            |          Suppress confirmation dialog for non-destructive operations
            |
            |  -h, --help
            |          Show help message
            ")"
        )

        # Define command and adjust arguments
        local fgb_command="${1:-}"
        [ $# -gt 0 ] && shift
        local fgb_subcommand="${1:-}"

        local WIDTH_OF_WINDOW; WIDTH_OF_WINDOW="$(tput cols)"

        case "$fgb_command" in
            branch)
                case "$fgb_subcommand" in
                    "") echo -e "error: need a subcommand" >&2
                        echo "${usage_message[$fgb_command]}" >&2
                        return 1
                        ;;
                    *) __fgb_branch "$@" ;;
                esac
                ;;
            worktree)
                case "$fgb_subcommand" in
                    "") echo -e "error: need a subcommand" >&2
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
        __fgb_branch_manage \
        __fgb_branch_set_vars \
        __fgb_confirmation_dialog \
        __fgb_convert_git_format_string \
        __fgb_extract_date_format \
        __fgb_git_branch_delete \
        __fgb_git_branch_list \
        __fgb_git_branch_new \
        __fgb_git_worktree_delete \
        __fgb_git_worktree_for_new_branch \
        __fgb_git_worktree_jump_or_add \
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
