#!/usr/bin/env bash
# install/common.sh - the common functions of the set-up (install/setup.sh reads it with source): the lines of the
# steps, the GitHub name of a link, the yes/no question, the update of the kit's copy, the free space check and the
# install of Claude Code, and the wait for a root command

# the lines of the steps: done, not done, skipped. What was not done also goes to the file AGENT_KIT_RESULTS, when
# the set-up set one, for its summary at the end. Colours only on a terminal (NO_COLOR turns them off). info: a
# plain line, under a heading of the set-up
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then C_OK=$'\e[32m' C_NO=$'\e[31m' C_DIM=$'\e[2m' C_B=$'\e[1m' C_0=$'\e[0m'; else C_OK="" C_NO="" C_DIM="" C_B="" C_0=""; fi
ok() { printf '  %s✓%s %s\n' "$C_OK" "$C_0" "$*"; }
no() { printf '  %s✗%s %s\n' "$C_NO" "$C_0" "$*"; [ -z "${AGENT_KIT_RESULTS:-}" ] || printf '%s\n' "$*" >> "$AGENT_KIT_RESULTS"; return 0; }
skip() { printf '  %s- %s%s\n' "$C_DIM" "$*" "$C_0"; }
info() { printf '%s%s\n' "${AGENT_KIT_RESULTS:+  }" "$*"; }
# owner/name of a GitHub link (https, ssh, with .git or a slash at the end); owner/name stays as it is
gh_name() { printf '%s' "$1" | sed -E 's#^(https?://)?(www\.)?github\.com[/:]##; s#^git@github\.com:##; s#\.git$##; s#/+$##'; }
# has_tty: there is a terminal to ask on. Never with AGENT_KIT_NO_ASK set (kit update: nothing is asked, also
# when a person runs it at a terminal)
has_tty() { [ -z "${AGENT_KIT_NO_ASK:-}" ] && { : < /dev/tty; } 2>/dev/null; }

# confirm QUESTION: a yes/no question on the terminal, yes by default (Enter). With no terminal, or with
# AGENT_KIT_YES set (kit update): yes at once
confirm() {
  local k
  [ -z "${AGENT_KIT_YES:-}" ] || return 0
  has_tty || return 0
  printf '%s [Y/n] ' "$1" > /dev/tty
  IFS= read -r k < /dev/tty || return 0
  case "$k" in n|N|no|No|NO|н|Н|нет|Нет) return 1 ;; esac
  return 0
}

# repo_update: the kit's copy at REPO_ROOT moved on. A copy on the branch main follows its origin's main
# (fast-forward only); any other copy follows the latest release tag vN.N.N, and a copy on another branch is left.
# The fetch goes as the GitHub App when its key is on the machine, and never asks on the terminal. Sets
# REPO_UPDATED (1 when the copy moved), REPO_FETCHED (0 when the origin did not answer) and REPO_WHY (why the copy
# was not moved, empty when it moved or had nothing to take)
_repo_kept() { REPO_WHY=$2; "$1" "repository not updated ($2)"; }
repo_update() {
  REPO_UPDATED=0 REPO_FETCHED=1 REPO_WHY=""
  local br rel cur up here
  br=$(git -C "$REPO_ROOT" symbolic-ref --short -q HEAD 2>/dev/null || true)
  if [ -n "$br" ] && [ "$br" != main ]; then _repo_kept skip "on the branch $br"; return 0; fi
  here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
  if [ -n "$(git -C "$REPO_ROOT" remote 2>/dev/null)" ]; then
    # no question on the terminal (git's own, ssh's) and no wait without an end
    ( eval "$(bash "$here/gh-app.sh" env 2>/dev/null || true)"
      export GIT_TERMINAL_PROMPT=0 GIT_SSH_COMMAND="${GIT_SSH_COMMAND:-ssh} -o BatchMode=yes"
      t=(); ! command -v timeout >/dev/null || t=(timeout 120)
      "${t[@]+"${t[@]}"}" git -C "$REPO_ROOT" fetch -q --tags < /dev/null 2>/dev/null ) || REPO_FETCHED=0
    # an origin that did not answer: the copy is not moved to what an earlier fetch left
    if [ "$REPO_FETCHED" = 0 ]; then _repo_kept skip "the kit's repository did not answer"; return 0; fi
  fi
  cur=$(git -C "$REPO_ROOT" describe --tags --always 2>/dev/null || echo "?")
  # a copy on main whose origin has no main (or that has no origin) is not taken off its branch to a release
  if [ "$br" = main ] && ! git -C "$REPO_ROOT" rev-parse -q --verify 'refs/remotes/origin/main^{commit}' \
    >/dev/null 2>&1; then _repo_kept skip "on main, and its origin has no main"; return 0; fi
  if [ "$br" = main ] && up=$(git -C "$REPO_ROOT" rev-parse -q --verify 'refs/remotes/origin/main^{commit}' 2>/dev/null); then
    [ "$(git -C "$REPO_ROOT" rev-parse HEAD)" = "$up" ] && return 0
    if ! git -C "$REPO_ROOT" merge-base --is-ancestor HEAD "$up" 2>/dev/null; then
      _repo_kept skip "main has commits that its origin has not"; return 0; fi
    git -C "$REPO_ROOT" diff --quiet HEAD -- 2>/dev/null || { _repo_kept no "local changes"; return 0; }
    rel=$(git -C "$REPO_ROOT" describe --tags --always "$up" 2>/dev/null || echo "?")
    confirm "Update found: agent-kit $cur -> $rel. Install it?" || {
      REPO_WHY="the update was declined"; skip "agent-kit $cur kept: the update to $rel not installed"; return 0; }
    if git -C "$REPO_ROOT" merge -q --ff-only "$up" 2>/dev/null; then REPO_UPDATED=1; ok "agent-kit updated: $cur -> $rel"
    else _repo_kept no "local changes"; fi
    return 0
  fi
  rel=$(git -C "$REPO_ROOT" tag -l | grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1 || true)
  if [ -z "$rel" ]; then _repo_kept skip "no release tag"; return 0; fi
  [ "$(git -C "$REPO_ROOT" rev-parse HEAD)" = "$(git -C "$REPO_ROOT" rev-parse "$rel^{commit}")" ] && return 0
  # a copy past the latest release (main after it, a commit not released yet) is never moved back to it
  if git -C "$REPO_ROOT" merge-base --is-ancestor "$rel" HEAD 2>/dev/null; then
    _repo_kept skip "ahead of the release $rel"; return 0; fi
  # an update is found: said and asked (yes with no terminal)
  git -C "$REPO_ROOT" diff --quiet HEAD -- 2>/dev/null || { _repo_kept no "local changes"; return 0; }
  confirm "Update found: agent-kit $cur -> $rel. Install it?" || {
    REPO_WHY="the update was declined"; skip "agent-kit $cur kept: the update to $rel not installed"; return 0; }
  if git -C "$REPO_ROOT" checkout -q --detach "$rel" 2>/dev/null; then REPO_UPDATED=1; ok "agent-kit updated: $cur -> $rel"
  else _repo_kept no "local changes"; fi
  return 0
}

# Claude Code's installer keeps up to three copies of the program (about 375 MB each: the download, the staging
# folder, the versions folder), all in the home folder. With less free space it fails half-way (ENOSPC)
CLAUDE_MB=1200
# claude_space: 0 when the home folder has the space, or it cannot be measured
claude_space() {
  local f
  f=$(df -Pk "$HOME" 2>/dev/null | awk 'NR==2 {print int($4/1024)}') || true
  [ -n "$f" ] || return 0
  [ "$f" -ge "$CLAUDE_MB" ] && return 0
  no "Claude Code not installed: $f MB free in $HOME, about $CLAUDE_MB MB needed (its installer keeps up to three copies of a 375 MB program). Free $((CLAUDE_MB - f)) MB more, then run this again"
  return 1
}
claude_install() {
  claude_space || return 1
  local log; log=$(mktemp)   # the installer's own lines are shown only when it fails
  info "installing Claude Code"
  if curl -fsSL https://claude.ai/install.sh | bash > "$log" 2>&1 && command -v claude >/dev/null; then rm -f "$log"; ok "Claude Code installed"
  else tail -n 20 "$log" | sed 's/^/    /'; rm -f "$log"; no "Claude Code was not installed"; return 1; fi
}

# What only root can install, when this user has no password-free sudo: with a terminal the set-up waits while
# the owner runs the command as root elsewhere. Enter: check again (0). Esc or s: stop (1). With no terminal: 1 at
# once
root_wait() {
  has_tty || return 1
  local k
  while :; do
    printf 'Enter: check again. Esc or s: stop. ' > /dev/tty
    IFS= read -rsn1 k < /dev/tty || { echo > /dev/tty; return 1; }
    echo > /dev/tty
    case "$k" in
      '') return 0 ;;
      s|S) return 1 ;;
      $'\e') while IFS= read -rsn1 -t 0.05 k < /dev/tty; do :; done; return 1 ;;   # Esc; the rest of an arrow key's code is dropped
    esac
  done
}
