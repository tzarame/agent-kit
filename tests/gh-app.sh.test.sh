#!/usr/bin/env bash
# tests/gh-app.sh.test.sh - the agent on GitHub as the App (install/gh-app.sh): key, token, gh, git-credential.
# HOME is a temp folder; the key is a real one made here with openssl; curl is a fake that answers as GitHub does
# (the installations, a token) and keeps the pass it was given; gh is a fake that records its token and arguments.
# Exit 0 when every case passes.
REPO=$(cd "$(dirname "$0")/.." && pwd -P)
T=$(mktemp -d) || exit 1; T=$(cd "$T" && pwd -P); trap 'rm -rf "$T"' EXIT
export HOME="$T/home"; BIN="$T/bin"; LOG="$T/log"; CONF="$HOME/.config/agent-kit"
mkdir -p "$HOME" "$BIN" "$T/install/bin" "$T/work" || exit 1
cp "$REPO/install/gh-app.sh" "$T/install/" && cp "$REPO/install/bin/gh" "$T/install/bin/" || exit 1; G="$T/install/gh-app.sh"
command -v openssl >/dev/null || { echo "openssl is missing: the test cannot make a key"; exit 1; }
openssl genrsa -out "$T/key.pem" 2048 2>/dev/null && openssl pkey -in "$T/key.pem" -pubout -out "$T/pub.pem" || exit 1
cat > "$BIN/curl" <<'EOS'
#!/bin/sh
# the pass comes on the input (-H @-); the address is the last argument
sed -n 's/^Authorization: Bearer //p' > "$FAKE_PASS"
for a in "$@"; do url=$a; done
echo "curl $url" >> "$FAKE_LOG"
[ -z "$FAKE_DOWN" ] || exit 22
case "$url" in
  */app/installations\?*) echo '[{"id":11,"account":{"login":"Acme"},"app_slug":"the-agent"},{"id":22,"account":{"login":"other-org"},"app_slug":"the-agent"}]' ;;
  */app/installations/*/access_tokens) id=${url%/access_tokens}; id=${id##*/}
    n=$(cat "$FAKE_N" 2>/dev/null || echo 0); n=$((n+1)); echo "$n" > "$FAKE_N"
    printf '{"token":"ghs_%s_%s","expires_at":"%s"}\n' "$id" "$n" "$(date -u -d "+${FAKE_LIFE:-3600} seconds" +%Y-%m-%dT%H:%M:%SZ)" ;;
  *) exit 22 ;;
esac
EOS
printf '#!/bin/sh\necho "gh token=$GH_TOKEN $*" >> "$FAKE_LOG"\n' > "$BIN/gh"
chmod +x "$BIN/curl" "$BIN/gh"
PASS=0; FAIL=0; RC=0; OUT=""
check() { if [ "$2" = 0 ]; then PASS=$((PASS+1)); echo "ok   - $1"; else FAIL=$((FAIL+1)); echo "FAIL - $1 | rc=$RC | out: $OUT | log: $(tr '\n' '|' < "$LOG" 2>/dev/null)"; fi; }
go() { : > "$LOG"; OUT=$(cd "$T/work" && FAKE_LOG="$LOG" FAKE_PASS="$T/pass" FAKE_N="$T/n" PATH="$T/install/bin:$BIN:$PATH" bash "$G" "$@" 2>&1); RC=$?; }
has() { case "$OUT" in *"$1"*) return 0 ;; esac; return 1; }
logged() { grep -qF -- "$1" "$LOG"; }

# 0. no Client ID of the App: nothing is asked of GitHub, the key is not taken
go key < "$T/key.pem"
[ "$RC" = 1 ] && has "--app-client-id" && [ ! -e "$CONF/app-key.pem" ] && ! logged curl
check "key with no Client ID: says the set-up's key, GitHub is not asked" $?
mkdir -p "$CONF" && echo Iv1.0123456789abcdef > "$CONF/app-client-id"
# 1. no key yet
go token acme
[ "$RC" = 1 ] && has "gh-app.sh key" && ! logged curl
check "token with no key: says how to put it, GitHub is not asked" $?
# 2. key: not a key
go key <<< "not a key"
[ "$RC" = 1 ] && has "not a private key" && [ ! -e "$CONF/app-key.pem" ] && [ ! -e "$CONF/app-key.pem.new" ]
check "key: a text that is not a key is refused, nothing is left" $?
# 3. key: GitHub does not accept it
FAKE_DOWN=1 go key < "$T/key.pem"
[ "$RC" = 1 ] && has "nothing changed" && [ ! -e "$CONF/app-key.pem" ] && [ ! -e "$CONF/app-key.pem.new" ]
check "key: refused by GitHub, nothing is left" $?
# 4. key: stored, mode 600, the accounts named, the key itself not printed
go key < "$T/key.pem"
[ "$RC" = 0 ] && cmp -s "$T/key.pem" "$CONF/app-key.pem" && [ "$(stat -c %a "$CONF/app-key.pem")" = 600 ] \
  && has "the-agent[bot]" && has "acme other-org" && ! has "PRIVATE KEY"
check "key: stored with mode 600, says the bot and its accounts" $?
# 5. the pass given to GitHub is signed with the key, for the App, for ten minutes at most
IFS=. read -r h p s < "$T/pass"
d64() { local x; x=$(printf '%s' "$1" | tr '_-' '/+'); while [ $(( ${#x} % 4 )) -ne 0 ]; do x+="="; done; printf '%s' "$x" | openssl base64 -d -A; }
d64 "$s" > "$T/sig"; pl=$(d64 "$p")
printf '%s.%s' "$h" "$p" | openssl dgst -sha256 -verify "$T/pub.pem" -signature "$T/sig" >/dev/null 2>&1 \
  && python3 -c 'import json,sys,time; d=json.loads(sys.argv[1]); sys.exit(not (d["iss"]=="Iv1.0123456789abcdef" and d["iat"]<=time.time() and 0<d["exp"]-time.time()<=600))' "$pl"
check "the pass: signed with the key, the App's Client ID, ten minutes at most" $?
# 6. token: of the account named, whatever the case of its letters; kept with mode 600
go token ACME
[ "$RC" = 0 ] && [ "$OUT" = ghs_11_1 ] && [ "$(stat -c %a "$CONF/app-tokens/acme")" = 600 ]
check "token: the installation of the account, kept with mode 600" $?
# 7. token: the kept one, GitHub not asked again
go token acme
[ "$RC" = 0 ] && [ "$OUT" = ghs_11_1 ] && ! logged curl
check "token: the kept one while it lives" $?
# 8. token: a new one when less than five minutes are left
FAKE_LIFE=200 go token other-org; first=$OUT
go token other-org
[ "$RC" = 0 ] && [ "$first" = ghs_22_2 ] && [ "$OUT" = ghs_22_3 ]
check "token: a new one when the kept one ends in five minutes" $?
# 9. token: an account without the App, and a name that is not one
go token nobody; a=$RC; has "not installed on nobody"; b=$?
go token ../x
[ "$a" = 1 ] && [ "$b" = 0 ] && [ "$RC" = 1 ] && has "not an account" && ! logged curl
check "token: no installation, and a bad name" $?
# 10. token with no owner: the owner of the folder's origin; outside a repository the first account
git -C "$T/work" init -q && git -C "$T/work" remote add origin git@github.com:other-org/thing.git
FAKE_LIFE=3600 go token; a=$OUT
git -C "$T/work" remote remove origin
go token
[ "$a" = ghs_22_3 ] && [ "$OUT" = ghs_11_1 ]
check "token with no owner: the origin's, else the first account" $?
# 11. gh: the token of the repository named, of the api path, of the origin; the arguments unchanged
git -C "$T/work" remote add origin https://github.com/other-org/thing.git
go gh pr list -R acme/kit; a=$?; logged "gh token=ghs_11_1 pr list -R acme/kit"; a=$((a + $?))
go gh api repos/acme/kit/issues; logged "gh token=ghs_11_1 api repos/acme/kit/issues"; a=$((a + $?))
go gh pr view 5; logged "gh token=ghs_22_3 pr view 5"; a=$((a + $?))
check "gh: the token of -R, of the api path, of the origin" "$a"
# an owner the App is not installed on (a public repository of someone else): the first account's token
go gh api repos/nobody/thing/releases; logged "gh token=ghs_11_1 api repos/nobody/thing/releases"
check "gh: an owner without the App gets the first account's token" $?
# outside a repository: the owner named in gh repo clone, as a name or a link; with none, the first account, not a silent stop
nogit() { : > "$LOG"; OUT=$(cd "$T/nogit" && FAKE_LOG="$LOG" FAKE_PASS="$T/pass" FAKE_N="$T/n" PATH="$T/install/bin:$BIN:$PATH" bash "$G" "$@" 2>&1); RC=$?; }
mkdir -p "$T/nogit"
nogit gh repo clone acme/kit "$T/nogit/kit" -- -q; a=$RC; logged "gh token=ghs_11_1 repo clone acme/kit"; a=$((a + $?))
nogit gh repo clone https://github.com/acme/kit; a=$((a + RC)); logged "gh token=ghs_11_1 repo clone https"; a=$((a + $?))
nogit gh repo list; a=$((a + RC)); logged "gh token=ghs_ repo list" || logged "repo list"; a=$((a + $?))
check "gh outside a repository: the owner of gh repo clone; no silent stop" "$a"
# 12. bin/gh in front of gh: the same, and the real gh is the next one on the PATH
: > "$LOG"; (cd "$T/work" && FAKE_LOG="$LOG" FAKE_PASS="$T/pass" FAKE_N="$T/n" PATH="$T/install/bin:$BIN:$PATH" gh issue list --repo=acme/kit)
logged "gh token=ghs_11_1 issue list --repo=acme/kit"
check "bin/gh: runs the real gh with the token" $?
# 13. git-credential: the owner from the path; nothing for another host or another action
go git-credential get <<< $'protocol=https\nhost=github.com\npath=acme/kit.git'; a=$OUT
go git-credential get <<< $'protocol=https\nhost=example.com\npath=acme/kit.git'; b=$OUT
go git-credential store <<< $'protocol=https\nhost=github.com\npath=acme/kit.git'
[ "$a" = $'username=x-access-token\npassword=ghs_11_1' ] && [ -z "$b" ] && [ -z "$OUT" ] && [ "$RC" = 0 ]
check "git-credential: the owner's token for github.com only, get only" $?
# 14. git itself, set as gh-app.sh env sets it: the helper is asked with the path
OUT=$(cd "$T/work" && FAKE_LOG="$LOG" FAKE_PASS="$T/pass" FAKE_N="$T/n" PATH="$T/install/bin:$BIN:$PATH" \
  git -c credential.https://github.com.helper= -c "credential.https://github.com.helper=!bash $G git-credential" \
  -c credential.https://github.com.useHttpPath=true credential fill <<< $'protocol=https\nhost=github.com\npath=other-org/thing.git' 2>&1)
has "password=ghs_22_3"
check "git: asks the helper and gets the owner's token" $?
# 15. who: the App's name and its accounts
go who
[ "$RC" = 0 ] && [ "$OUT" = "the-agent[bot] on: acme other-org" ]
check "who: NAME[bot] and the accounts" $?
# 16. env: the lines for a shell; nothing when set already, or with no key
go env; a=$OUT
mv "$CONF/app-key.pem" "$T/k"; go env; b=$OUT; mv "$T/k" "$CONF/app-key.pem"
[ -z "$b" ] && [ -n "$a" ]; x=$?
OUT=$(cd "$T/work" && env -u AGENT_KIT_MACHINE -u GIT_CONFIG_COUNT bash -c 'eval "$(bash "$1" env)"; echo "${PATH%%:*} $GIT_CONFIG_COUNT $GIT_CONFIG_VALUE_0|$GIT_CONFIG_VALUE_2 $AGENT_KIT_MACHINE"; bash "$1" env' _ "$G" 2>&1)
[ "$x" = 0 ] && [ "$OUT" = "$T/install/bin 3 |true $(id -un)@$(uname -n)" ]
check "env: bin/gh first, git's helper, USER@MACHINE; nothing a second time or with no key" $?

echo "passed $PASS, failed $FAIL"; [ "$FAIL" = 0 ]
