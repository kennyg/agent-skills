#!/usr/bin/env bash
# going-ashore.sh — provision a remote host with the firstmate toolchain.
#
# Installs herdr, treehouse, and no-mistakes using each tool's native vendor
# installer, targeting /usr/local/bin so the binaries resolve on the default
# PATH — including the non-interactive, non-login shell a plain
# `ssh host 'herdr ...'` gets (where ~/.local/bin and mise shims are absent).
# mise is still installed (for tools like node) and kept as a per-tool fallback
# if a vendor installer fails. Idempotent and safe to re-run. Run it ON the host
# you are landing on, e.g.:
#   ssh <host> 'bash -s' < going-ashore.sh
#   # or copy it over and run:  bash ~/going-ashore.sh
set -u

log() { printf '\n== %s ==\n' "$1"; }
ok() { printf '  ok    %s\n' "$1"; }
warn() { printf '  warn  %s\n' "$1"; }
err() { printf '  FAIL  %s\n' "$1"; }
rc=0

command -v curl >/dev/null 2>&1 || {
	err "curl is required but not found"
	exit 1
}
# NOTE: do NOT prepend $HOME/.local/bin to PATH. The treehouse / no-mistakes
# installers self-target /usr/local/bin ONLY when ~/.local/bin is absent from
# PATH; prepending it diverts them back to the per-user dir that vanishes over a
# non-interactive SSH shell.

log "Host"
uname -a

# --- mise (still installed for tools like node; also a per-tool fallback) --
log "mise"
if command -v mise >/dev/null 2>&1; then
	ok "mise already present ($(command -v mise))"
else
	printf '  installing mise ...\n'
	curl -fsSL https://mise.run | sh || {
		err "mise install failed"
		exit 1
	}
	hash -r 2>/dev/null || true
fi
MISE="$(command -v mise || echo "$HOME/.local/bin/mise")"
"$MISE" --version >/dev/null 2>&1 || {
	err "mise not runnable at $MISE"
	exit 1
}
# expose mise shims for in-run verification of any mise-fallback tools
export PATH="$HOME/.local/share/mise/shims:$PATH"

# --- toolchain: native vendor installer first, mise as fallback -----------
# Each tool's native installer lands the binary in /usr/local/bin (on the
# default PATH, incl. non-interactive SSH). If the vendor installer fails, fall
# back to mise: the tool-registry name where mise knows the tool, else the
# github: backend (ubi: is deprecated). Each candidate ref is tried in order.
# land <tool> <vendor-install-command> "<mise-ref> [<mise-ref>...]"
land() {
	local name=$1 vendor=$2 refs=$3 ref
	if command -v "$name" >/dev/null 2>&1 || "$MISE" which "$name" >/dev/null 2>&1; then
		ok "$name already available"
		return 0
	fi
	printf '  landing %s via vendor installer ...\n' "$name"
	if sh -c "$vendor"; then
		hash -r 2>/dev/null || true
		if command -v "$name" >/dev/null 2>&1; then
			ok "$name landed via vendor installer -> $(command -v "$name")"
			return 0
		fi
		warn "$name: vendor installer ran but binary not on PATH; trying mise"
	else
		warn "$name: vendor installer failed; trying mise"
	fi
	# shellcheck disable=SC2086  # deliberate word-split of the space-separated ref list
	for ref in $refs; do
		printf '  landing %s via mise (%s) ...\n' "$name" "$ref"
		if "$MISE" use -g "$ref" >/dev/null 2>&1; then
			"$MISE" reshim >/dev/null 2>&1 || true
			hash -r 2>/dev/null || true
			if command -v "$name" >/dev/null 2>&1 || "$MISE" which "$name" >/dev/null 2>&1; then
				ok "$name landed via mise ($ref)"
				return 0
			fi
			warn "$name: mise ($ref) did not expose the binary"
		else
			warn "$name: mise ref '$ref' failed (older mise may predate a registry entry)"
		fi
	done
	err "$name install failed (vendor and all mise refs)"
	rc=1
}

log "Land toolchain"
# herdr: installer defaults to ~/.local/bin and does NOT self-sudo, so run it
# under sudo with an explicit /usr/local/bin target (that dir is root-owned).
land herdr "sudo env HERDR_INSTALL_DIR=/usr/local/bin sh -c 'curl -fsSL https://herdr.dev/install.sh | sh'" 'herdr github:ogulcancelik/herdr'
# treehouse: self-targets /usr/local/bin and self-sudos when ~/.local/bin is
# not on PATH; run plainly.
land treehouse 'curl -fsSL https://kunchenguid.github.io/treehouse/install.sh | sh' 'github:kunchenguid/treehouse'
# no-mistakes: installs under ~/.no-mistakes/bin and self-sudo-symlinks it into
# /usr/local/bin; run plainly.
land no-mistakes 'curl -fsSL https://raw.githubusercontent.com/kunchenguid/no-mistakes/main/docs/install.sh | sh' 'github:kunchenguid/no-mistakes'

log "Verify"
for t in mise herdr treehouse no-mistakes gh node git; do
	if command -v "$t" >/dev/null 2>&1; then
		v=$("$t" --version 2>/dev/null | head -1)
		ok "$t -> $(command -v "$t")${v:+  [$v]}"
	elif [ "$t" = mise ] && "$MISE" --version >/dev/null 2>&1; then
		ok "mise -> $MISE  [$("$MISE" --version 2>/dev/null | head -1)]"
	elif "$MISE" which "$t" >/dev/null 2>&1; then
		ok "$t -> (mise) $("$MISE" which "$t")"
	else
		err "$t MISSING"
		rc=1
	fi
done

log "GitHub auth"
if gh auth status >/dev/null 2>&1; then
	ok "gh authenticated as $(gh api user -q .login 2>/dev/null || echo '?')"
else
	warn "gh not authenticated on this host — run: gh auth login"
fi

log "Shell activation"
ok "firstmate toolchain installs to /usr/local/bin (on the default PATH, incl. non-interactive SSH shells)"
if grep -qs 'mise activate' "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile" 2>/dev/null; then
	ok "mise activation already in a shell rc (for mise-managed tools like node)"
else
	warn "mise-managed tools (e.g. node) need mise activated in new shells:"
	# shellcheck disable=SC2016  # the $(...) is printed literally for the user to copy, not expanded
	printf '        echo '\''eval "$(mise activate bash)"'\'' >> ~/.bashrc   # or your shell'\''s rc\n'
fi

log "Result"
if [ "$rc" -eq 0 ]; then
	ok "shore secured — toolchain landed to /usr/local/bin."
	printf '     Next: start herdr with  herdr  (or  herdr server  headless), then land firstmate.\n'
else
	err "some steps need attention (see above); re-run after fixing."
fi
exit "$rc"
