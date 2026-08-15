#!/usr/bin/env bash
# gen-skills-table.sh — regenerate the "Available Skills" table in README.md
# from the frontmatter of each skills/*/SKILL.md.
#
# The table is the only place a skill's existence is advertised to a reader, and
# a hand-maintained one drifts silently: code-ingest shipped without a row and
# stayed invisible for two releases. Frontmatter is the single source of truth;
# this rewrites the table between the markers below to match it.
#
# The cell text is the first sentence of the `description` field. That field is
# written for agent tool-selection, so its later sentences are trigger phrases
# ("Use when the user says ...") that read badly in a table — the first sentence
# is the part that describes the skill.
#
#   scripts/gen-skills-table.sh           # rewrite README.md in place
#   scripts/gen-skills-table.sh --check   # print a diff and exit 1 if stale
#
# Depends only on bash, awk, sed and diff — nothing beyond what mise already
# pins for this repo.
set -euo pipefail

readonly BEGIN_MARKER='<!-- BEGIN GENERATED SKILLS TABLE -->'
readonly END_MARKER='<!-- END GENERATED SKILLS TABLE -->'

repo_root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
cd "$repo_root"

readme=README.md
check_only=false

case ${1-} in
"") ;;
--check) check_only=true ;;
-h | --help)
	sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
	exit 0
	;;
*)
	printf 'Unknown option: %s\n' "$1" >&2
	printf 'Usage: %s [--check]\n' "$0" >&2
	exit 2
	;;
esac

die() {
	printf 'gen-skills-table: %s\n' "$1" >&2
	exit 1
}

# frontmatter_field <file> <key> — print a single-line scalar from the YAML
# frontmatter, with surrounding quotes stripped. Prints nothing if absent.
frontmatter_field() {
	awk -v key="$2" -v sq="'" '
		NR == 1 && $0 == "---" { in_fm = 1; next }
		in_fm && $0 == "---" { exit }
		!in_fm { next }
		{
			i = index($0, ":")
			if (i == 0) next
			if (substr($0, 1, i - 1) != key) next

			v = substr($0, i + 1)
			sub(/^[ \t]+/, "", v)
			sub(/[ \t]+$/, "", v)

			first = substr(v, 1, 1)
			last = substr(v, length(v), 1)
			if (length(v) >= 2 && first == last && (first == "\"" || first == sq)) {
				v = substr(v, 2, length(v) - 2)
				if (first == "\"") gsub(/\\"/, "\"", v)
			}

			print v
			exit
		}
	' "$1"
}

# Trim to the first sentence and drop its trailing period. A sentence ends at
# ". " — a period with no space after it is a version number or a filename.
first_sentence() {
	printf '%s' "$1" | sed -E 's/\. .*$//; s/\.$//'
}

# Escape the characters that would otherwise break a markdown table cell.
escape_cell() {
	printf '%s' "$1" | sed 's/|/\\|/g'
}

build_table() {
	printf '| Skill | Description |\n'
	printf '|-------|-------------|\n'

	local dir slug skill name desc
	for dir in skills/*/; do
		slug=${dir#skills/}
		slug=${slug%/}
		skill=skills/$slug/SKILL.md
		[ -f "$skill" ] || die "skills/$slug has no SKILL.md"

		name=$(frontmatter_field "$skill" name)
		desc=$(frontmatter_field "$skill" description)

		[ -n "$name" ] || die "$skill: no 'name' in frontmatter"
		[ -n "$desc" ] || die "$skill: no 'description' in frontmatter"
		[ "$name" = "$slug" ] ||
			die "$skill: name '$name' does not match directory '$slug'"
		case $desc in
		'|' | '>' | '|'* | '>'*)
			die "$skill: multi-line description scalars are not supported"
			;;
		esac

		printf '| [%s](skills/%s/) | %s |\n' \
			"$slug" "$slug" "$(escape_cell "$(first_sentence "$desc")")"
	done
}

render() {
	SKILLS_TABLE=$1 awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
		$0 == begin { print; print ENVIRON["SKILLS_TABLE"]; skipping = 1; next }
		$0 == end { skipping = 0 }
		!skipping { print }
	' "$readme"
}

grep -qF "$BEGIN_MARKER" "$readme" || die "$readme is missing $BEGIN_MARKER"
grep -qF "$END_MARKER" "$readme" || die "$readme is missing $END_MARKER"

# The shell sorts the glob; pin the collation so every machine agrees.
export LC_ALL=C
table=$(build_table)

if [ "$check_only" = true ]; then
	if ! render "$table" | diff -u "$readme" -; then
		printf '\n%s is stale. Run: scripts/gen-skills-table.sh\n' "$readme" >&2
		exit 1
	fi
	exit 0
fi

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
render "$table" >"$tmp"
cat "$tmp" >"$readme"
