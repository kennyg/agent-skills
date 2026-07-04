#!/usr/bin/env bash
# land-fleet.sh — Going Ashore, step 2: raise the flag and land firstmate.
#
# Run it ON a host already provisioned by going-ashore.sh (herdr, treehouse,
# no-mistakes present). It starts a persistent headless herdr server, then
# clones firstmate. After it finishes, boot the first mate INSIDE the host's
# herdr and bridge from your Mac with `herdr --remote <host>` (see SKILL.md).
#
# Config (env):
#   FM_SRC   firstmate clone source (default: upstream origin URL below).
#            - a git URL clones UPSTREAM (misses any local-only commits).
#            - a path to a .bundle clones YOUR EXACT local main. Create it on
#              the Mac with:  git -C <firstmate> bundle create ~/firstmate.bundle main
#              scp it over, then run with FM_SRC=~/firstmate.bundle
#   FM_DIR   where firstmate lands (default: ~/firstmate)
set -u

FM_SRC="${FM_SRC:-https://github.com/kunchenguid/firstmate.git}"
FM_DIR="${FM_DIR:-$HOME/firstmate}"

log() { printf '\n== %s ==\n' "$1"; }
ok() { printf '  ok    %s\n' "$1"; }
err() { printf '  FAIL  %s\n' "$1"; }
rc=0

# make mise-shimmed tools reachable in a non-interactive shell
export PATH="$HOME/.local/share/mise/shims:$HOME/.local/bin:$PATH"

# NOTE: `herdr status server` exits 0 even when the server is NOT running, so its
# exit code is useless as a liveness test. Parse the reported status instead.
server_running() { herdr status server 2>/dev/null | grep -q 'status: running'; }

log "Preflight"
for t in herdr git; do
	if command -v "$t" >/dev/null 2>&1; then ok "$t present"; else
		err "$t not found — run going-ashore.sh first"
		exit 1
	fi
done

# --- raise the flag: a persistent, headless herdr server ------------------
log "Raise the flag (herdr server)"
if server_running; then
	ok "herdr server already running"
else
	printf '  starting headless herdr server ...\n'
	# setsid + detached stdio so the server survives this SSH session closing
	setsid herdr server >"$HOME/.herdr-server.log" 2>&1 </dev/null &
	for _ in $(seq 1 15); do
		server_running && break
		sleep 1
	done
	if server_running; then
		ok "herdr server is up (log: ~/.herdr-server.log)"
	else
		err "herdr server did not come up — see ~/.herdr-server.log"
		tail -15 "$HOME/.herdr-server.log" 2>/dev/null | sed 's/^/    /'
		rc=1
	fi
fi

# --- land the fleet: clone firstmate --------------------------------------
log "Land firstmate"
if [ -d "$FM_DIR/.git" ]; then
	ok "firstmate already present at $FM_DIR"
elif [ -e "$FM_DIR" ]; then
	err "$FM_DIR exists but is not a git repo — move it aside and re-run"
	rc=1
else
	printf '  cloning %s -> %s ...\n' "$FM_SRC" "$FM_DIR"
	if git clone --quiet "$FM_SRC" "$FM_DIR"; then
		ok "firstmate cloned"
	else
		err "clone failed from $FM_SRC (private repo? run 'gh auth setup-git' first)"
		rc=1
	fi
fi

# --- sanity check (do NOT run session-start here; the agent owns that) -----
if [ -d "$FM_DIR/.git" ]; then
	log "Sanity check"
	if [ -f "$FM_DIR/bin/fm-session-start.sh" ]; then
		ok "bin/fm-session-start.sh present"
		(cd "$FM_DIR" && git log --oneline -1) | sed 's/^/  head: /'
	else
		err "firstmate bin/ missing — is $FM_SRC the right repo?"
		rc=1
	fi
fi

log "Result"
if [ "$rc" -eq 0 ]; then
	ok "flag raised and firstmate landed."
	cat <<EOF
     Next (boot the first mate — see the going-ashore SKILL.md for exact commands):
       * confirm the Claude Code harness is installed AND logged in on this host
       * inside THIS host's herdr, create a workspace at $FM_DIR and launch
         'claude --dangerously-skip-permissions' in it (persistent + autonomous)
       * from your Mac, drive her with:  herdr --remote <host>
EOF
else
	err "some steps need attention (see above); re-run after fixing."
fi
exit "$rc"
