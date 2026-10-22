# shellcheck shell=bash
# Tracked Python files shared by bin/format and bin/lint.

# Fills the named array with every tracked *.py path, relative to the repository root.
python_files_read() {
  local -n files_ref=$1
  local listing
  listing=$(git -c core.quotePath=false ls-files -- '*.py') || {
    echo 'error: cannot list tracked Python files with git ls-files' >&2
    return 1
  }
  [[ -n "$listing" ]] || {
    echo 'error: git ls-files found no tracked Python files' >&2
    return 1
  }
  # shellcheck disable=SC2034 # files_ref is a nameref to the caller's array
  mapfile -t files_ref <<<"$listing"
}
