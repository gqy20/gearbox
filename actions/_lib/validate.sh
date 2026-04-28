# Shared input validation functions for Gearbox composite actions.
# Sourced by each action's run: block to prevent shell injection.
#
# Usage:
#   source "$GITHUB_ACTION_PATH/../_lib/validate.sh"
#   validate_repo "${{ inputs.repo }}"
#   validate_number "issue_number" "${{ inputs.issue_number }}"

set -uo pipefail

# Validate a GitHub repository identifier (owner/name format).
# Accepts only alphanumeric, dash, underscore, dot, and single slash.
validate_repo() {
  local value="$1"
  if ! [[ "$value" =~ ^[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+$ ]]; then
    echo "::error::Invalid repo format '$value'. Expected owner/repo with alphanumeric characters."
    exit 1
  fi
}

# Validate a comma-separated list of repo identifiers (for benchmarks etc).
validate_repo_list() {
  local value="$1"
  if [ -z "$value" ]; then
    return 0  # empty is allowed for optional inputs
  fi
  # Split on comma and validate each entry
  local IFS=','
  for entry in $value; do
    # Trim whitespace
    entry="$(echo "$entry" | xargs)"
    if [ -n "$entry" ]; then
      validate_repo "$entry"
    fi
  done
}

# Validate that a value is a non-negative integer.
# Usage: validate_number [label] <value>
# If only one arg is provided, it's treated as the value.
validate_number() {
  local label="input"
  local value="$1"
  if [ $# -ge 2 ]; then
    label="$1"
    value="$2"
  fi
  if ! [[ "$value" =~ ^[0-9]+$ ]]; then
    echo "::error::Invalid $label '$value'. Must be a positive integer."
    exit 1
  fi
}

# Validate a file path — reject shell metacharacters ($ ` ; | & newline).
validate_path() {
  local value="$1"
  local forbidden='$`;|&'
  # Check each forbidden character individually for reliability
  local ch
  for ch in '$' '`' ';' '|' '&'; do
    case "$value" in *"$ch"*)
      echo "::error::Invalid path '$value'. Contains disallowed character: $ch"
      exit 1
      ;;
    esac
  done
  # Reject command substitution patterns $(…) and ((…))
  if [[ "$value" == *'$('* ]] || [[ "$value" == *'(('* ]]; then
    echo "::error::Invalid path '$value'. Contains command substitution pattern."
    exit 1
  fi
}
