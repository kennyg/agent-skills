#!/usr/bin/env bash
# check-script-header.sh — enforce the skill script header rule from CONTRIBUTING.md.
#
# Every skills/*/scripts/*.py must start with the uv shebang, carry a PEP 723
# inline metadata block, and be executable. A file whose name starts with an
# underscore is an importable helper and is skipped.
#
#   scripts/check-script-header.sh FILE...
#
# Prints one line per problem and exits 1 if there is any.
set -euo pipefail

shebang='#!/usr/bin/env -S uv run --script'
status=0

for file in "$@"; do
	case "$(basename "$file")" in _*) continue ;; esac

	if [ "$(head -n 1 "$file")" != "$shebang" ]; then
		echo "$file: first line must be: $shebang"
		status=1
	fi
	if ! grep -q '^# /// script$' "$file" || ! grep -q '^# ///$' "$file"; then
		echo "$file: missing the PEP 723 block (# /// script ... # ///)"
		status=1
	else
		for key in requires-python dependencies; do
			if ! grep -q "^# $key = " "$file"; then
				echo "$file: PEP 723 block has no \`$key\`"
				status=1
			fi
		done
	fi
	if [ ! -x "$file" ]; then
		echo "$file: not executable; run chmod +x"
		status=1
	fi
done

exit "$status"
