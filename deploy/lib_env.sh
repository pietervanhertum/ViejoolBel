#!/usr/bin/env bash
#
# lib_env.sh — safely read KEY=value from an env file WITHOUT executing it.
#
# The service's env file (/etc/viejoolbel/viejoolbel.env) is a systemd
# EnvironmentFile, whose format is NOT guaranteed to be bash-sourceable: a value
# may contain a space after '=', quotes, or characters bash would try to run.
# Sourcing it with `.` therefore risks executing file contents (e.g. a token line
# turning into a "command not found"). This reader extracts a single value with
# text tools only, tolerant of surrounding whitespace and one layer of quotes.
#
# Usage:  value="$(viejoolbel_read_env /path/to/env KEY)"

viejoolbel_read_env() {
  local file="$1" key="$2" line
  [[ -f "$file" ]] || return 0
  # Last matching assignment wins (mirrors "later lines override").
  line="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "$file" | tail -n1)" || return 0
  [[ -n "$line" ]] || return 0
  line="${line#*=}"                              # drop everything up to the first '='
  line="${line#"${line%%[![:space:]]*}"}"        # ltrim whitespace
  line="${line%"${line##*[![:space:]]}"}"        # rtrim whitespace
  case "$line" in                                # strip one layer of quotes
    \"*\") line="${line#\"}"; line="${line%\"}" ;;
    \'*\') line="${line#\'}"; line="${line%\'}" ;;
  esac
  printf '%s' "$line"
}
