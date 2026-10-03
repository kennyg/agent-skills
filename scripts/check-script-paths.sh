#!/usr/bin/env bash
# check-script-paths.sh — keep machine-specific paths out of skill scripts.
#
# A skill is installed on other machines. A path such as /Users/<name>/ or an
# iCloud folder only works on the machine that wrote it. Scripts must take the
# project root from an argument, $CLAUDE_PROJECT_DIR or the current directory.
#
#   scripts/check-script-paths.sh FILE...
#
# Prints each offending line and exits 1 if there is any.
set -euo pipefail

pattern='/Users/|/home/|~/|Mobile Documents'
status=0

for file in "$@"; do
	if grep -nE -- "$pattern" "$file" | sed "s|^|$file:|"; then
		status=1
	fi
done

exit "$status"
