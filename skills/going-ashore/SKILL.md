---
name: going-ashore
description: Runbook for standing up a first mate and its fleet on a remote host over SSH + herdr ("going ashore"). Use when the captain wants to relocate or extend the fleet to a remote box (e.g. a dev server), run agents on a beefier/always-on machine, or asks to "go ashore" / "set up a remote fleet"; covers survey, provision, raise-the-flag, land, boot (persistent + autonomous), and bridge, with the version/vault/harness/permission caveats learned in practice.
---

# Going Ashore — landing the fleet on a remote host

herdr is client/server: a persistent **server** owns the sessions and agents; a
**client** attaches to it, locally or over SSH (`herdr --remote <host>`). "Going
ashore" means running the herdr server + a first mate on a remote host, so the
fleet executes there (always-on, beefier, survives your laptop sleeping) while
you drive it from your Mac. The host's first mate is a **separate first mate with
its own fleet** — its own backlog, projects, and crew — not this one relocated.

Scripts live beside this file in `scripts/`. Run each ON the host by piping over
SSH: `ssh <host> 'bash -s' < <script>`. The captain runs the `curl | sh` ones
(the classifier blocks piped installers); the SSH-only steps firstmate can run.

## Phase 1 — Survey the shore
Inventory the host before touching it:
```sh
ssh <host> 'echo "== host =="; uname -a;
  echo "== firstmate toolchain =="; for t in herdr treehouse no-mistakes; do printf "%s: " "$t"; command -v "$t" || echo MISSING; done;
  echo "== harness =="; for t in claude codex; do printf "%s: " "$t"; command -v "$t" || echo MISSING; done;
  echo "== base =="; for t in mise gh node git curl; do printf "%s: " "$t"; command -v "$t" || echo MISSING; done;
  echo "== gh auth =="; gh auth status 2>&1 | head -3'
```
Note the arch (Linux x86_64 is the tested target) and what's missing. **Two
prerequisites are easy to miss:** the **harness** (Claude Code) itself, and its
**auth** — both are needed to boot a first mate and neither is installed by the
provision script.

## Phase 2 — Provision the toolchain — `scripts/going-ashore.sh`
Installs the firstmate toolchain — herdr, treehouse, no-mistakes — using each
tool's **native vendor installer, targeting `/usr/local/bin`**. That dir is on
the default PATH, including the non-interactive, non-login shell a plain
`ssh <host> 'herdr ...'` gets (where `~/.local/bin` and mise's shims are *not*),
so the tools resolve over the exact SSH path herdr's backend uses. mise is still
installed (for tools like node) and kept as a per-tool **fallback** if a vendor
installer fails. Idempotent. Captain runs it (installs software):
```
! ssh <host> 'bash -s' < <skill>/scripts/going-ashore.sh
```

## Phase 3 & 4 — Raise the flag + land firstmate — `scripts/land-fleet.sh`
Starts a persistent headless herdr server, then clones firstmate. Run it after
provisioning:
```
! ssh <host> 'bash -s' < <skill>/scripts/land-fleet.sh
```
- **`herdr status server` gotcha:** it exits 0 even when the server is NOT
  running — the script parses `status: running` from its output instead. Never
  trust its exit code for liveness.
- **Version choice (`FM_SRC`):** default clones **upstream** (misses any
  local-only commits — fine, since local-only bits like the vault curator stay
  home). For a byte-exact mirror of your machine, ship a bundle:
  `git -C <firstmate> bundle create ~/firstmate.bundle main`, scp it, run with
  `FM_SRC=~/firstmate.bundle`.

## Phase 5 — Boot the first mate (persistent + autonomous)
Run the first mate **inside the host's herdr** (not a bare SSH pane) so she
survives SSH/network drops. Prereqs: the harness is installed AND logged in
(`/login` is interactive — the **captain** does it; it authenticates the host's
`~/.claude` globally, so any claude session there inherits it).

Orchestrate the host's herdr over SSH (`<P>` = the pane id printed by create):
```sh
ssh <host> 'export PATH="$HOME/.local/share/mise/shims:$HOME/.local/bin:$PATH";
  herdr workspace create --label firstmate --cwd "$HOME/firstmate" --no-focus'   # note the pane id
ssh <host> 'herdr pane run <P> "  cd ~/firstmate && claude --dangerously-skip-permissions"'
```
Then handle the interactive bits by reading the pane (`herdr pane read <P>`) and
sending keys (`herdr pane send-keys <P> ...`):
- accept the first-run **trust** dialog (once per dir), then the
  **Bypass Permissions** warning (`Down`, `Enter` to pick "Yes, I accept").
- kick her off: `herdr pane send-text <P> "You are the first mate on this host. Run your session start and stand ready."` then `send-keys <P> Enter`.

`--dangerously-skip-permissions` makes her operate hands-free like the crew
(otherwise she prompts before every `bin/fm-*.sh`). This is a real posture on a
remote box — get the captain's explicit OK before enabling it.

## Phase 6 — Bridge (drive her from your Mac)
```
herdr --remote <host>
```
Attaches to the host's herdr; the `firstmate` workspace holds her. `--remote`
needs matching herdr protocol versions on both ends (check `herdr --version`).

## Standing caveats
- **The vault stays home.** iCloud/Obsidian doesn't follow to the host, so wiki
  work (the vault curator) stays local. The host is for project work.
- **Separate fleet.** The host's first mate has its own backlog/projects/crew.
- **No version pin.** The native installers always fetch the **latest** published
  release of each tool. That's correct for a fresh landing, but matching an
  existing fleet's exact tool versions is a separate step this script does not
  guarantee.
- **Boot durability.** The `setsid herdr server` survives disconnects but NOT a
  host reboot. For set-and-forget, install a systemd **user** unit that runs
  `herdr server` on boot (`loginctl enable-linger <user>` so it starts without a
  login session). Optional hardening, not required for a working landing.
