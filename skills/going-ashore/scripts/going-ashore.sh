#!/usr/bin/env bash
# going-ashore.sh — provision a remote host with the firstmate toolchain via mise.
#
# Installs mise (if missing), then lands herdr, treehouse, and no-mistakes as
# global mise tools using the ubi backend (GitHub-release binaries). If a mise
# backend fails, it falls back to that tool's vendor install script. Idempotent
# and safe to re-run. Run it ON the host you are landing on, e.g.:
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
export PATH="$HOME/.local/bin:$PATH"

log "Host"
uname -a

# --- mise (the tool manager the captain prefers) --------------------------
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
# expose mise shims for in-run verification
export PATH="$HOME/.local/share/mise/shims:$PATH"

# --- toolchain: mise first, vendor installer as fallback ------------------
# mise's ubi backend is deprecated; use the tool-registry name where mise knows
# the tool (herdr does), and the github: backend otherwise. Each candidate ref
# is tried in order, then the vendor installer as a last resort.
# land <tool> "<mise-ref> [<mise-ref>...]" <vendor-install-command>
land() {
	local name=$1 refs=$2 vendor=$3 ref
	if command -v "$name" >/dev/null 2>&1 || "$MISE" which "$name" >/dev/null 2>&1; then
		ok "$name already available"
		return 0
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
	printf '  falling back to vendor installer for %s ...\n' "$name"
	if sh -c "$vendor"; then
		hash -r 2>/dev/null || true
		ok "$name landed via vendor installer"
	else
		err "$name install failed (all mise refs and vendor)"
		rc=1
	fi
}

log "Land toolchain"
# herdr: mise registry name, then github: backend for older mise, then vendor.
land herdr 'herdr github:ogulcancelik/herdr' 'curl -fsSL https://herdr.dev/install.sh | sh'
# treehouse / no-mistakes: not in the mise registry -> github: backend, then vendor.
land treehouse 'github:kunchenguid/treehouse' 'curl -fsSL https://kunchenguid.github.io/treehouse/install.sh | sh'
land no-mistakes 'github:kunchenguid/no-mistakes' 'curl -fsSL https://raw.githubusercontent.com/kunchenguid/no-mistakes/main/docs/install.sh | sh'

log "Verify"
for t in mise herdr treehouse no-mistakes gh node git; do
	if command -v "$t" >/dev/null 2>&1; then
		v=$("$t" --version 2>/dev/null | head -1)
		ok "$t -> $(command -v "$t")${v:+  [$v]}"
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

log "Shell activation (mise)"
if grep -qs 'mise activate' "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile" 2>/dev/null; then
	ok "mise activation already in a shell rc"
else
	warn "activate mise so tools are on PATH in new shells:"
	# shellcheck disable=SC2016  # the $(...) is printed literally for the user to copy, not expanded
	printf '        echo '\''eval "$(mise activate bash)"'\'' >> ~/.bashrc   # or your shell'\''s rc\n'
fi

log "Result"
if [ "$rc" -eq 0 ]; then
	ok "shore secured — toolchain landed via mise."
	printf '     Next: start herdr with  herdr  (or  herdr server  headless), then land firstmate.\n'
else
	err "some steps need attention (see above); re-run after fixing."
fi
exit "$rc"
