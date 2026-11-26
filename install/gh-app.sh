#!/usr/bin/env bash
# gh-app.sh - the agent on GitHub as the App itself (NAME[bot]), not as the person who signed in: the person can then
# approve the agent's pull requests, and the agent has the App's rights only (no admin, no bypass of the rules).
# The App's private key is put on the machine by hand, once: gh-app.sh key reads it from the terminal and writes it
# to ~/.config/agent-kit/app-key.pem (mode 600). From it come installation tokens (one hour each, kept in
# ~/.config/agent-kit/app-tokens/ until five minutes before their end), one per account the App is installed on.
# With the key there, kit start gives a session this file as git's credential helper and bin/gh in front of gh (the
# lines of gh-app.sh env); the person's own gh login is not changed. To go back: remove the key file.
# Usage: gh-app.sh key              paste the key, then Ctrl-D (or: gh-app.sh key < file.pem); checked against GitHub
#        gh-app.sh token [OWNER]    a token for OWNER's repositories (with none: the owner of the folder's origin)
#        gh-app.sh who              who the agent is on GitHub: NAME[bot], and the accounts the App is installed on
#        gh-app.sh env              the lines a shell runs (eval) to use the App: bin/gh first, git's helper
#        gh-app.sh gh ARGS          gh with the token of the repository's owner (bin/gh calls this)
#        gh-app.sh git-credential get   git's credential helper (the owner is in the path: credential.useHttpPath)
set -euo pipefail
umask 077
export PATH="$HOME/.local/bin:$PATH"
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd -P)
CONF="$HOME/.config/agent-kit"; KEY="$CONF/app-key.pem"; TOK="$CONF/app-tokens"
# the Client ID of the user's GitHub App (not a secret): the set-up writes it with --app-client-id ID
APP=${AGENT_KIT_CLIENT_ID:-$(cat "$CONF/app-client-id" 2>/dev/null || true)}
API=https://api.github.com
die() { echo "gh-app.sh: $*" >&2; exit 1; }
need_app() {
  case "$APP" in
    "") die "no Client ID of the GitHub App on this machine; give it to the set-up: --app-client-id ID" ;;
    *[!A-Za-z0-9.]*) die "not a Client ID of a GitHub App: $APP" ;;
  esac
}
usage() { sed -n '9,14p' "$0" | sed 's/^# \{0,1\}//; s/^Usage: /       /'; }
b64() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }
# the App's own short pass (ten minutes), signed with the key $1
jwt() {
  local now h p s; now=$(date +%s)
  h=$(printf '{"alg":"RS256","typ":"JWT"}' | b64)
  p=$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' $((now - 60)) $((now + 540)) "$APP" | b64)
  s=$(printf '%s.%s' "$h" "$p" | openssl dgst -sha256 -sign "$1" -binary | b64)
  printf '%s.%s.%s' "$h" "$p" "$s"
}
# a call as the App; the pass goes to curl on its input, not in its arguments (seen by other users in ps)
api() { local k=$1; shift; printf 'Authorization: Bearer %s\n' "$(jwt "$k")" | curl -fsS -H @- -H "Accept: application/vnd.github+json" "$@"; }
# the accounts the App is installed on: ID, the account in small letters, the App's name; a line each
installs() { api "$1" "$API/app/installations?per_page=100" | python3 -c '
import json, sys
for i in json.load(sys.stdin):
    print(i["id"], i["account"]["login"].lower(), i["app_slug"])'; }
# the owner of the folder's origin on github.com, or nothing (not a failure outside a repository)
here_owner() { { git remote get-url origin 2>/dev/null || true; } | sed -n 's#^\(https://\|ssh://git@\|git@\)github\.com[:/]\([^/]*\)/.*#\2#p'; }
token() {
  local o f now id got=""
  [ -s "$KEY" ] || die "no key of the App on this machine; put it with: gh-app.sh key"
  need_app
  o=$(printf '%s' "${1:-}" | tr 'A-Z' 'a-z'); now=$(date +%s); mkdir -p "$TOK"
  if [ -z "$o" ]; then   # no owner known: the first account of the list
    o=$(cat "$TOK/.first" 2>/dev/null || true)
    if [ -z "$o" ]; then
      got=$(installs "$KEY") || die "no answer from GitHub for the App's key"
      o=$(printf '%s\n' "$got" | head -1 | cut -d' ' -f2); [ -n "$o" ] || die "the App is not installed on any account"
      printf '%s\n' "$o" > "$TOK/.first"
    fi
  fi
  case "$o" in *[!a-z0-9_.-]*|.*) die "not an account's name: $o" ;; esac
  f="$TOK/$o"
  if [ -s "$f" ] && [ "$(( $(cut -d' ' -f1 "$f") - now ))" -gt 300 ]; then cut -d' ' -f2 "$f"; return; fi
  [ -n "${got:-}" ] || got=$(installs "$KEY") || die "no answer from GitHub for the App's key"
  id=$(printf '%s\n' "$got" | awk -v o="$o" '$2 == o { print $1; exit }')
  [ -n "$id" ] || die "the App is not installed on $o"
  api "$KEY" -X POST "$API/app/installations/$id/access_tokens" | python3 -c '
import calendar, json, sys, time
d = json.load(sys.stdin)
print(calendar.timegm(time.strptime(d["expires_at"], "%Y-%m-%dT%H:%M:%SZ")), d["token"])' > "$f.$$" \
    && [ -s "$f.$$" ] || { rm -f "$f.$$"; die "GitHub gave no token for $o"; }
  mv "$f.$$" "$f"; cut -d' ' -f2 "$f"
}
CMD=${1:-}; [ $# -eq 0 ] || shift
case "$CMD" in
  key)
    command -v openssl >/dev/null || die "openssl is missing; install it and run again"
    need_app
    mkdir -p "$CONF"; chmod 700 "$CONF"
    if [ -t 0 ]; then   # typed or pasted: not shown on the screen
      echo "Paste the App's private key (the .pem file's text), then press Enter and Ctrl-D. It is not shown." >&2
      trap 'stty echo 2>/dev/null || true' EXIT; stty -echo
    fi
    k=$(cat); stty echo 2>/dev/null || true
    printf '%s\n' "$k" > "$KEY.new"; k=""
    trap 'rm -f "$KEY.new"; stty echo 2>/dev/null || true' EXIT
    openssl pkey -in "$KEY.new" -noout 2>/dev/null || die "that is not a private key; nothing changed"
    got=$(installs "$KEY.new") || die "GitHub did not accept the key for the App $APP (or no network); nothing changed"
    [ -n "$got" ] || die "the key is right, but the App is not installed on any account; nothing changed"
    mv "$KEY.new" "$KEY"; rm -rf "$TOK"
    echo "the key is in ${KEY/#$HOME/\~}: new sessions act as $(printf '%s\n' "$got" | head -1 | cut -d' ' -f3)[bot] on: $(printf '%s\n' "$got" | cut -d' ' -f2 | paste -sd' ')"
    ;;
  token) token "${1:-$(here_owner)}" ;;
  who)
    [ -s "$KEY" ] || die "no key of the App on this machine; put it with: gh-app.sh key"
    need_app
    got=$(installs "$KEY") && [ -n "$got" ] || die "no answer from GitHub for the App's key"
    echo "$(printf '%s\n' "$got" | head -1 | cut -d' ' -f3)[bot] on: $(printf '%s\n' "$got" | cut -d' ' -f2 | paste -sd' ')"
    ;;
  env)
    # bin/gh in front of gh; git asks this file for the token, with the repository's path, so the token is its
    # owner's; the helpers set before are not used. USER@MACHINE is for the agent to sign its work with
    [ -s "$KEY" ] && [ -z "${AGENT_KIT_MACHINE:-}" ] || exit 0   # nothing with no key, or when set already
    n=${GIT_CONFIG_COUNT:-0}
    printf 'export PATH=%q\n' "$HERE/bin:$PATH"
    printf 'export GIT_CONFIG_KEY_%d=%q GIT_CONFIG_VALUE_%d=%q\n' \
      "$n" credential.https://github.com.helper "$n" "" \
      $((n+1)) credential.https://github.com.helper $((n+1)) "!bash $(printf '%q' "$HERE/gh-app.sh") git-credential" \
      $((n+2)) credential.https://github.com.useHttpPath $((n+2)) true
    printf 'export GIT_CONFIG_COUNT=%d AGENT_KIT_MACHINE=%q\n' $((n+3)) "$(id -un)@$(uname -n)"
    ;;
  gh)
    # the owner: of the repository named (-R, --repo, GH_REPO, gh repo ... OWNER/NAME), of a path of gh api, else of
    # the folder's origin
    o="" prev=""
    for a in "$@"; do
      case "$prev" in -R|--repo) r=${a#https://github.com/}; r=${r#github.com/}; o=${r%%/*} ;; esac
      case "$a" in
        --repo=*) r=${a#--repo=}; r=${r#https://github.com/}; r=${r#github.com/}; o=${r%%/*} ;;
        repos/*/*|/repos/*/*|orgs/*|/orgs/*|users/*|/users/*) [ -n "$o" ] || { r=${a#/}; r=${r#*/}; o=${r%%/*}; } ;;
      esac
      prev=$a
    done
    if [ -z "$o" ] && [ "${1:-}" = repo ]; then   # gh repo clone OWNER/NAME or its link: the first such argument
      for a in "${@:3}"; do
        r=${a#https://github.com/}; r=${r#github.com/}
        case "$r" in -*|/*|*/*/*|*:*) ;; */*) o=${r%%/*}; break ;; esac
      done
    fi
    [ -n "$o" ] || { r=${GH_REPO:-}; r=${r#github.com/}; o=${r%%/*}; }
    [ -n "$o" ] || o=$(here_owner)
    real=""; IFS=: read -ra dirs <<< "$PATH"   # the real gh: the next one on the PATH after bin/gh
    for d in "${dirs[@]}"; do [ -x "$d/gh" ] && ! [ "$d/gh" -ef "$HERE/bin/gh" ] && { real="$d/gh"; break; }; done
    [ -n "$real" ] || die "gh is not installed"
    # an owner the App is not installed on (someone else's public repository): the first account's token reads it
    GH_TOKEN=$(token "$o" 2>/dev/null) || GH_TOKEN=$(token "") || exit 1
    export GH_TOKEN; exec "$real" "$@"
    ;;
  git-credential)
    [ "${1:-}" = get ] || exit 0   # nothing is stored or erased
    host="" path=""
    while IFS='=' read -r k v; do case "$k" in host) host=$v ;; path) path=$v ;; esac; done
    [ "$host" = github.com ] || exit 0
    t=$(token "${path%%/*}") || exit 1
    printf 'username=x-access-token\npassword=%s\n' "$t"
    ;;
  *) usage; [ -z "$CMD" ] || [ "$CMD" = -h ] || [ "$CMD" = --help ] || exit 2 ;;
esac
