#!/usr/bin/env bash
# install/setup.sh - the set-up of the machine, then the start of a project: the entry of the kit, run from its
# clone, and kit setup runs it with --no-start. Each run does only what is missing, so it is safe to run
# again:
#   0. the keys, before any step (install/keys.sh): a wrong key exits 2 and nothing changes; --help prints the usage
#   1. the kit's copy moved to the latest release (asked on a terminal); after an update the set-up runs again from it
#   2. the system packages git, tmux, curl and python3: sudo only for what is missing and only when it needs no
#      password; else the Debian packages in the home folder, and the root command for the rest (Enter checks again,
#      Esc or s stops). Nothing is upgraded
#   3. GitHub: the App itself when its key is on the machine (install/gh-app.sh), gh's own sign-in, the token of the
#      public step, or a code for the user's GitHub App (--app-client-id). It never stops the set-up
#   4. Claude Code installed when it is missing, after a check of the free space; never updated (it updates itself)
#   5. the kit's files: kit setup-files (kit/machine.py), each change in kit.log; the plugins of the old kit, named,
#      and removed with --remove-old-plugins
#   6. the Claude sign-in hint, and the summary of what was not done
#   7. the start, last, as it may open the session on this terminal: kit start PROJECT with the start's keys; it
#      clones owner/name when its folder is missing. A project is asked for, on a terminal, only when GitHub is signed
#      in and the projects' folder has none yet
# Each change of a step goes to kit.log (kit setup-log), a key only as its fingerprint.
# --dry-run changes nothing: the steps say what they would do, and kit start --dry-run prints the session's plan.
# Exit: 2 for a wrong key; 1 as root, or when the set-up cannot go on (a package, Claude Code); else the start's
# code, and 1 when that is 0 but GitHub is not signed in
set -u
[ "$(id -u)" != 0 ] || { echo "setup.sh: run this as your normal user, not as root: the agent, its sign-ins and its files belong to that user. It asks for sudo itself, only for missing packages." >&2; exit 1; }
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd -P); KIT=$(cd "$HERE/.." && pwd -P)
# shellcheck source=install/common.sh
source "$HERE/common.sh"
# shellcheck source=install/keys.sh
source "$HERE/keys.sh"
ORIG=("$@")   # the keys as given, for the run of the new release after an update
read_keys "$@"
[ "$HELP" = 0 ] || { usage; exit 0; }
export PATH="$HOME/.local/bin:$PATH"   # the programs installed without root
CONF="$HOME/.config/agent-kit"
say() { printf '\n%s== %s%s\n' "$C_B" "$*" "$C_0"; }
# changed WORDS: one change of the set-up, added to kit.log; never a secret
changed() { python3 -I "$KIT/kit/__main__.py" setup-log "$@" 2>/dev/null || true; }

# the version of this copy: the tag (with the commits after it, if any) and the commit's first 8 characters
echo "agent-kit $(git -C "$KIT" describe --tags --always --dirty 2>/dev/null || echo "?") ($(git -C "$KIT" rev-parse --short=8 HEAD 2>/dev/null || echo "no git"))"
[ "$DRY" = 0 ] || echo "dry run: nothing is changed"
# what was not done, for the summary at the end
AGENT_KIT_RESULTS=$(mktemp); export AGENT_KIT_RESULTS; trap 'rm -f "$AGENT_KIT_RESULTS"' EXIT

# 1. the kit's copy first: moved to the latest release before any step, so a fix in a release reaches a machine where
# a step fails. After an update the set-up runs again from the new release, by this
# same path
if [ -n "${AGENT_KIT_UPDATED:-}" ] || [ "$NOUPD" = 1 ]; then :
elif [ "$DRY" = 1 ]; then skip "the kit's copy not checked for an update (--dry-run)"
elif command -v git >/dev/null; then
  REPO_ROOT=$KIT; repo_update
  if [ "$REPO_UPDATED" = 1 ]; then
    changed "the kit's copy $KIT moved to $(git -C "$KIT" describe --tags --always 2>/dev/null)"
    rm -f "$AGENT_KIT_RESULTS"; AGENT_KIT_UPDATED=1 exec bash "$KIT/install/setup.sh" "${ORIG[@]+"${ORIG[@]}"}"; fi
fi
if [ "$DRY" = 0 ]; then
  mkdir -p "$CONF" "$HOME/.local/bin"; chmod 700 "$CONF"
  # a git installed in the home folder by an earlier version lacks the paths of its helpers: add them
  f="$HOME/.local/bin/git"
  if [ -f "$f" ] && grep -q '^p=".*/\.local/pkg"$' "$f" && ! grep -q GIT_EXEC_PATH "$f"; then
    # shellcheck disable=SC2016 # the line is written as it is, for the launcher to expand
    sed -i 's|^exec |export GIT_EXEC_PATH="$p/usr/lib/git-core" GIT_TEMPLATE_DIR="$p/usr/share/git-core/templates"\nexec |' "$f"
    info "the paths of git's helpers added to $f"; changed "the paths of git's helpers added to $f"
  fi
fi

# 2. the system packages: sudo only for what is missing
PKGS="git tmux curl python3"
missing() { local c m=""; for c in $PKGS; do command -v "$c" >/dev/null || m="$m $c"; done; printf '%s' "$m"; }
# the missing packages without root on Debian or Ubuntu: apt-get download as the user, dpkg -x under ~/.local/pkg, and
# a small launcher in ~/.local/bin for each program; a launcher whose program does not run is removed
home_install() {
  command -v apt-get >/dev/null || return 0
  local c t p d want more pre="$HOME/.local/pkg"
  mkdir -p "$pre" "$HOME/.local/bin"
  for c in $need; do
    t=$(mktemp -d)
    want=$(apt-cache depends --recurse --no-recommends --no-suggests --no-conflicts --no-breaks --no-replaces --no-enhances "$c" 2>/dev/null \
      | grep '^[a-z0-9]' | sort -u | while read -r p; do dpkg -s "$p" >/dev/null 2>&1 || echo "$p"; done)
    # shellcheck disable=SC2086 # the packages are words
    if [ -n "$want" ] && (cd "$t" && apt-get download -q $want) >/dev/null 2>&1; then
      for d in "$t"/*.deb; do dpkg -x "$d" "$pre"; done
      # git looks for its helpers (the https one too) and its templates in /usr, so it is told where they are
      # shellcheck disable=SC2016 # expanded by the launcher
      more=""; [ "$c" = git ] && more='export GIT_EXEC_PATH="$p/usr/lib/git-core" GIT_TEMPLATE_DIR="$p/usr/share/git-core/templates"\n'
      # shellcheck disable=SC2016 # expanded by the launcher
      printf '#!/bin/sh\np="%s"\nexport LD_LIBRARY_PATH="$(echo "$p"/usr/lib/*-linux-gnu | tr " " ":")${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\n'"$more"'exec "$p/usr/bin/%s" "$@"\n' "$pre" "$c" > "$HOME/.local/bin/$c"
      chmod +x "$HOME/.local/bin/$c"
      if "$c" --version >/dev/null 2>&1 || "$c" -V >/dev/null 2>&1; then info "$c installed in your home folder"
      else rm -f "$HOME/.local/bin/$c"; fi
    fi
    rm -rf "$t"
  done
}
# what is still missing only root can install: the command is said, and the set-up waits (Enter checks again)
root_install() {
  local how
  need=$(missing)
  while [ -n "$need" ]; do
    if command -v pacman >/dev/null; then how="pacman -S --needed${need//python3/python}"
    elif command -v dnf >/dev/null; then how="dnf install$need"
    else how="apt-get install$need"; fi
    echo "missing:$need, and this user has no password-free sudo. Install them as root on the machine (for example from the provider's console): $how" >&2
    root_wait || { echo "setup.sh: the set-up cannot go on without:$need. Install them, then run this again." >&2; exit 1; }
    need=$(missing)
  done
}
# shellcheck disable=SC2086 # the packages are words
sudo_install() {
  local c
  info "missing:$need (with sudo)"
  if command -v apt-get >/dev/null; then sudo apt-get update -qq; for c in $need; do sudo apt-get install -y -qq "$c" >/dev/null; done
  elif command -v pacman >/dev/null; then sudo pacman -S --needed --noconfirm ${need//python3/python} >/dev/null
  elif command -v dnf >/dev/null; then sudo dnf install -y -q $need >/dev/null
  else echo "setup.sh: no apt-get, pacman or dnf here: install by hand:$need, then run this again" >&2; exit 1; fi
}
say "System packages"
need=$(missing); asked=$need
if [ -z "$need" ]; then ok "all present"
elif [ "$DRY" = 1 ]; then skip "missing:$need; would be installed (--dry-run)"
else
  if sudo -n true 2>/dev/null; then sudo_install; else home_install; root_install; fi
  for c in $asked; do
    if command -v "$c" >/dev/null; then ok "$c installed"; changed "the package $c installed"
    else no "$c not installed"; fi
  done
fi

# 3. GitHub for the agent's work: the App itself when its key is on the machine, else a sign-in to the agent's GitHub
# App, so the agent reaches only the repositories the App is installed on, with no more rights than the person who
# signs in. It never stops the set-up: without a sign-in, the clone is skipped
say "GitHub"
# the Client ID of the user's GitHub App (not a secret; the kit has none of its own): --app-client-id, kept in a
# file for the later runs and for gh-app.sh, else AGENT_KIT_CLIENT_ID, else the file
if [ -z "$APPID" ]; then :
elif [ "$DRY" = 1 ]; then skip "the App's Client ID not written to ~/.config/agent-kit/app-client-id (--dry-run)"
else printf '%s\n' "$APPID" > "$CONF/app-client-id.new" && mv "$CONF/app-client-id.new" "$CONF/app-client-id" \
  && ok "the App's Client ID is in ~/.config/agent-kit/app-client-id" \
  && changed "the App's Client ID $APPID written to $CONF/app-client-id"; fi
AGENT_APP=${APPID:-${AGENT_KIT_CLIENT_ID:-$(cat "$CONF/app-client-id" 2>/dev/null || true)}}
[ -z "$AGENT_APP" ] || export AGENT_KIT_CLIENT_ID=$AGENT_APP
# --app-key FILE: the App's private key, checked against GitHub and copied to its place by gh-app.sh key
if [ -z "$APPKEY" ]; then :
elif [ "$DRY" = 1 ]; then skip "the App's key not copied (--dry-run)"
elif [ ! -r "$APPKEY" ]; then no "--app-key: no file $APPKEY"
elif out=$(bash "$HERE/gh-app.sh" key < "$APPKEY" 2>&1); then
  ok "$out"
  changed "the App's key of $APPKEY copied to $CONF/app-key.pem," \
    "sha256:$(openssl dgst -sha256 < "$APPKEY" 2>/dev/null | sed 's/.* //' | cut -c1-12)"
else no "the App's key not taken: $out"; fi
field() { sed -n "s/.*\"$1\": *\"\{0,1\}\([^\",}]*\).*/\1/p"; }   # one field of a flat JSON answer
CRED="$CONF/git-credentials"   # the token the public step got from the same App
me() { local l; l=$(gh api user --jq .login 2>/dev/null) || l=""; case "$l" in ""|*[!A-Za-z0-9-]*) ;; *) printf ' as %s' "$l" ;; esac; }
# device_login: the code for the agent's GitHub App, and the wait for it (or for a gh auth login done meanwhile)
device_login() {
  local r dev every a tok=""
  r=$(curl -fsS -X POST -H "Accept: application/json" -d "client_id=$AGENT_APP" https://github.com/login/device/code 2>/dev/null) || r=""
  dev=$(printf '%s' "$r" | field device_code); every=$(printf '%s' "$r" | field interval)
  if [ -z "$dev" ]; then info "no answer from GitHub (no network?)"; return 0; fi
  info "Open $(printf '%s' "$r" | field verification_uri) and enter the code $(printf '%s' "$r" | field user_code)"
  info "(allow the App), or run gh auth login in another terminal. Waiting..."
  for _ in $(seq 180); do
    sleep "${every:-5}"
    if gh auth status >/dev/null 2>&1; then ok "logged in$(me)"; GHOK=1; return 0; fi   # signed in by the user
    a=$(curl -fsS -X POST -H "Accept: application/json" -d "client_id=$AGENT_APP&device_code=$dev&grant_type=urn:ietf:params:oauth:grant-type:device_code" https://github.com/login/oauth/access_token 2>/dev/null) \
      || { info "no answer from GitHub (no network?)"; return 0; }
    tok=$(printf '%s' "$a" | field access_token); [ -n "$tok" ] && break
    case $(printf '%s' "$a" | field error) in
      authorization_pending) ;; slow_down) every=$(( ${every:-5} + 5 )) ;;
      *) echo "setup.sh: the GitHub sign-in failed: $(printf '%s' "$a" | field error)" >&2; return 0 ;;
    esac
  done
  if [ -n "$tok" ]; then printf '%s' "$tok" | gh auth login --hostname github.com --git-protocol https --with-token \
    && { GHOK=1; ok "logged in$(me)"; changed "GitHub signed in$(me), by a code for the App $AGENT_APP"; }; fi
  return 0
}
GHOK=0 APPWHO=""
if ! command -v gh >/dev/null; then no "gh is not installed, so GitHub is skipped: install gh (https://cli.github.com), then run this again"
else
  # who is logged in: the App itself when its key is on the machine and GitHub takes it, else the person. kit start
  # gives the sessions the App's helpers itself (install/gh-app.sh env)
  if [ -s "$CONF/app-key.pem" ]; then APPWHO=$(bash "$HERE/gh-app.sh" who 2>/dev/null) || APPWHO=""; fi
  if [ -n "$APPWHO" ]; then ok "logged in as the App: $APPWHO"; GHOK=1
  elif gh auth status >/dev/null 2>&1; then ok "logged in$(me)"; GHOK=1
  elif [ "$DRY" = 1 ]; then skip "not signed in; would sign in (--dry-run)"
  elif [ -s "$CRED" ] && sed -n 's#^https://[^:]*:\([^@]*\)@github.com$#\1#p' "$CRED" | head -1 | gh auth login --hostname github.com --git-protocol https --with-token 2>/dev/null; then
    ok "logged in$(me) with the token of the public step"; GHOK=1
    changed "GitHub signed in$(me), with the token of $CRED"
  elif [ -n "$AGENT_APP" ] && [ -z "${AGENT_KIT_NO_ASK:-}" ]; then device_login   # it waits for a person
  # the sign-in by default is the user's own: gh asks on the terminal; with no terminal the command is said
  elif has_tty; then
    info "not signed in to GitHub: gh auth login asks you now"
    if gh auth login --hostname github.com --git-protocol https --web < /dev/tty; then
      GHOK=1; ok "logged in$(me)"; changed "GitHub signed in$(me), by gh auth login"
    fi
  else info "not signed in to GitHub: sign in with gh auth login in a terminal"; fi
  if [ -n "$APPWHO" ] || [ "$DRY" = 1 ]; then :   # git has the App's helper in the sessions; a dry run changes nothing
  elif [ "$GHOK" = 1 ]; then
    had=$(git config --global --get-all credential.https://github.com.helper 2>/dev/null || true)
    gh auth setup-git; [ -n "$had" ] || changed "git signs in to GitHub by gh (gh auth setup-git)"
  else no "GitHub not signed in; the set-up goes on without it. Sign in later: run gh auth login in another terminal, then setup.sh again."; fi
fi

# 4. Claude Code: installed when missing, after a check of the free space; it updates itself
say "Claude Code"
if command -v claude >/dev/null; then ok "Claude Code $(claude --version 2>/dev/null | cut -d' ' -f1)"
elif [ "$DRY" = 1 ]; then skip "not installed; would be installed (--dry-run)"
elif claude_install; then changed "Claude Code installed"
else { echo "setup.sh: the set-up cannot go on without Claude Code" >&2; exit 1; }; fi

# 5. the kit's files: the command kit, the PATH line of ~/.bashrc, the first config, the marks of Claude Code's first
# run and the user's fields in Claude Code's settings (kit/machine.py); each change goes to kit.log
say "The kit's files"
D=(); [ "$DRY" = 0 ] || D=(--dry-run)
out=$(python3 -I "$KIT/kit/__main__.py" setup-files "${D[@]+"${D[@]}"}" 2>&1); rc=$?
[ -z "$out" ] || printf '%s\n' "$out" | sed 's/^/    /'
if [ "$rc" = 0 ]; then ok "the command kit: $HOME/.local/bin/kit"; else no "the kit's files: kit setup-files failed (exit $rc)"; fi

# the plugins and the marketplace agent-kit that the old kit installed in Claude Code (the kit gives its plugins by
# --plugin-dir now): named, and removed only with --remove-old-plugins, by Claude Code's own commands
OLD=$(claude plugin list --json 2>/dev/null | python3 -I -c '
import json, sys
for p in json.load(sys.stdin):
    if str(p.get("id", "")).endswith("@agent-kit"): print(p["id"], p.get("scope") or "user")' 2>/dev/null || true)
OLDM=$(claude plugin marketplace list --json 2>/dev/null | python3 -I -c '
import json, sys
print("".join("agent-kit" for m in json.load(sys.stdin) if m.get("name") == "agent-kit"))' 2>/dev/null || true)
if [ -z "$OLD$OLDM" ]; then :
elif [ "$OLDPLUG" = 0 ]; then
  info "the old kit's plugins are in Claude Code: $(printf '%s' "${OLD:-the marketplace agent-kit}" | paste -sd, -)"
  info "remove them when no session of the old kit runs: --remove-old-plugins"
elif [ "$DRY" = 1 ]; then skip "the old kit's plugins not removed (--dry-run)"
else
  while read -r id scope; do
    [ -n "$id" ] || continue
    if claude plugin uninstall "$id" --scope "$scope" >/dev/null 2>&1; then
      ok "the old plugin $id removed"; changed "the old plugin $id ($scope) removed from Claude Code"
    else no "the old plugin $id not removed: claude plugin uninstall $id --scope $scope"; fi
  done <<< "$OLD"
  if [ -z "$OLDM" ]; then :
  elif claude plugin marketplace remove agent-kit >/dev/null 2>&1; then
    ok "the old marketplace agent-kit removed"; changed "the old marketplace agent-kit removed from Claude Code"
  else no "the old marketplace not removed: claude plugin marketplace remove agent-kit"; fi
fi

# 6. the Claude sign-in, without waiting, and the summary
say "Claude"
if claude auth status >/dev/null 2>&1; then ok "signed in"; else no "Sign in to Claude: run claude auth login"; fi
say "Summary"
if [ -s "$AGENT_KIT_RESULTS" ]; then echo "not done:"; sed 's/^/  ✗ /' "$AGENT_KIT_RESULTS"; else ok "all done"; fi

# 7. the start: the project given, or, on a terminal, asked when the projects' folder has none yet (a first run)
ROOT=${AGENT_KIT_ROOT:-$HOME}; case "$ROOT" in \~|\~/*) ROOT=$HOME${ROOT:1} ;; esac   # a leading ~, as kit/io.py
has_project() { local d; for d in "$ROOT"/*/; do [ -d "$d.git" ] && return 0; done; return 1; }
ask() { local v=""; has_tty || return 0; read -r -p "$1: " v < /dev/tty || true; printf '%s' "$v"; }
if [ "$START" = 1 ] && [ -z "$PROJECT" ] && [ "$GHOK" = 1 ] && [ "$DRY" = 0 ] && ! has_project; then
  PROJECT=$(gh_name "$(ask "Repository to work on (owner/name or a link; Enter: none)")")
fi
RC=0
if [ "$START" = 0 ]; then say "Set up; not started (--no-start)"
elif [ -z "$PROJECT" ]; then say "Set up; no project named"; info "start one: kit start PROJECT, or kit start owner/name to clone it"
else
  say "Start"
  env -u AGENT_KIT_RESULTS -u AGENT_KIT_UPDATED python3 -I "$KIT/kit/__main__.py" start "$PROJECT" "${KEYS[@]+"${KEYS[@]}"}" \
    || { RC=$?; no "the start failed (exit $RC)"; }
fi
# GitHub still not signed in: a caller sees it in the exit code
if [ "$GHOK" = 0 ] && [ "$RC" = 0 ]; then
  echo "setup.sh: GitHub is not signed in: run gh auth login in another terminal, then setup.sh again" >&2; RC=1
fi
exit "$RC"
