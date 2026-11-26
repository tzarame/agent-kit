#!/usr/bin/env bash
# tests/owner-run.test.sh - tests of content/plugins/agent-kit/bin/owner-run, the gate for a command the owner runs himself.
# HOME is a temp folder; PATH holds links to the programs the gate needs, a fake tailscale and a fake ip. The cases
# with a real sandbox run only where bwrap works (not in the CI's containers); the others put a fake bwrap and mark
# the test as passed by hand. Exit 0 when every case passes.
REPO=$(cd "$(dirname "$0")/.." && pwd -P)
T=$(mktemp -d) || exit 1
T=$(cd "$T" && pwd -P)
trap 'rm -rf "$T"' EXIT
HOME="$T/home"; export HOME
BIN="$T/bin"; ST="$HOME/.local/state/agent-kit/owner-run"; RB="$HOME/.local/share/agent-kit/owner-run/rollback"
mkdir -p "$HOME/.config" "$BIN" || exit 1
for p in bash sh sed sha256sum cut cat mkdir mv rm cp id date readlink stat cmp diff grep tail head mktemp python3 dirname; do
  ln -s "$(command -v "$p")" "$BIN/$p" || exit 1
done
printf '#!/bin/sh\necho %s\n' "'{\"Self\":{\"HostName\":\"box-ts\"}}'" > "$BIN/tailscale"
printf '#!/bin/sh\necho "1.1.1.1 via 10.0.0.1 dev eth0 src 10.0.0.7 uid 1000"\n' > "$BIN/ip"
chmod +x "$BIN/tailscale" "$BIN/ip"
REAL_BWRAP=$(command -v bwrap 2>/dev/null)
BWRAP=0; [ -n "$REAL_BWRAP" ] && "$REAL_BWRAP" --ro-bind / / --unshare-all --dev /dev --proc /proc true 2>/dev/null && BWRAP=1
fake_bwrap() { rm -f "$BIN/bwrap"; printf '#!/bin/sh\nexit 1\n' > "$BIN/bwrap"; chmod +x "$BIN/bwrap"; }
real_bwrap() { rm -f "$BIN/bwrap"; ln -s "$REAL_BWRAP" "$BIN/bwrap"; }
S="$REPO/content/plugins/agent-kit/bin/owner-run"
PASS=0 FAIL=0 SKIP=0
ok() { PASS=$((PASS+1)); echo "ok   $1"; }
no() { FAIL=$((FAIL+1)); echo "FAIL $1"; [ -n "${2:-}" ] && printf '     %s\n' "$2"; }
skip() { SKIP=$((SKIP+1)); echo "skip $1 (no working bwrap)"; }
# go ARGS...: the gate; RC, OUT (stdout) and ERR (stderr) after it
go() { OUT=$(env -i HOME="$HOME" PATH="$BIN" "$S" "$@" 2>"$T/err"); RC=$?; ERR=$(cat "$T/err"); }
# pair DIR [RUN [ROLLBACK]]: a script that writes a line into ~/conf.txt and a rollback that puts the old one back
pair() {
  mkdir -p "$1"
  printf '%s\n' '#!/bin/bash' '# owner-run-goal: add a line to conf.txt' '# owner-run-file: ~/conf.txt' \
    "${2:-cp conf.txt \"\$OWNER_RUN_SAVE/conf.txt\" && echo added >> conf.txt}" > "$1/run.sh"
  printf '%s\n' '#!/bin/bash' "${3:-cp \"\$OWNER_RUN_SAVE/conf.txt\" conf.txt}" > "$1/rollback.sh"
}
passed() { mkdir -p "$ST/tested" && echo "$1" > "$ST/tested/$2"; }   # passed NAME HASH: a test passed, by hand
echo old > "$HOME/conf.txt"

# 1. no bwrap: the stage is refused, and the owner is told to install bubblewrap
rm -f "$BIN/bwrap"; pair "$T/a"; go stage one "$T/a"
if [ "$RC" != 0 ] && [[ $ERR == *"no bwrap"*bubblewrap* ]] && [ ! -e "$ST/stage/one" ]; then ok "1 no bwrap: refused, bubblewrap named"; else no "1 no bwrap" "rc=$RC $OUT $ERR"; fi

# 2. staged, no verdict: cmd prints nothing; approve with no passed test is refused
fake_bwrap; go stage one "$T/a"; H=${OUT#one }
go cmd one; R1=$RC O1=$OUT
go approve one "$H"
if [[ $H =~ ^[0-9a-f]{16}$ ]] && [ "$R1" != 0 ] && [ -z "$O1" ] && [ "$RC" != 0 ] && [[ $ERR == *"no passed test"* ]]; then ok "2 no verdict: no line; no approve before a test"; else no "2 no verdict" "h=$H r1=$R1 o1=$O1 rc=$RC $ERR"; fi

# 3. a passed test and a verdict: the line names both hosts, the full path, only plain words
passed one "$H"; go approve one "$H"; go cmd one
L=$(head -n 1 <<<"$OUT")
if [ "$RC" = 0 ] && [ "$L" = "ssh -o ConnectTimeout=5 -t $(id -un)@box-ts $S exec one $H || ssh -o ConnectTimeout=5 -t $(id -un)@10.0.0.7 $S exec one $H" ] \
  && ! grep -q "[\"'\$<>;*?\\\\~\`(){}]" <<<"$L"; then ok "3 the line: Tailscale, then LAN, plain words"; else no "3 the line" "rc=$RC $OUT $ERR"; fi

# 4. the hosts from the config win over tailscale and ip
mkdir -p "$HOME/.config/agent-kit"; printf 'TS_HOST=ts.example\nLAN_HOST=192.168.9.9\n' > "$HOME/.config/agent-kit/owner-run.env"
go cmd one
if [[ $OUT == *"@ts.example "*"@192.168.9.9 "* ]]; then ok "4 the hosts from owner-run.env"; else no "4 config hosts" "$OUT $ERR"; fi
rm "$HOME/.config/agent-kit/owner-run.env"

# 5. a script changed after its verdict: no line, and exec of the old hash fails
echo '# more' >> "$T/a/run.sh"; go cmd one; R1=$RC O1=$OUT
go exec one "$H"
if [ "$R1" != 0 ] && [ -z "$O1" ] && [ "$RC" = 0 ] && [[ $OUT == FAILED* ]] && [ "$(cat "$HOME/conf.txt")" = old ]; then ok "5 changed after review: no line, exec refused"; else no "5 changed" "r1=$R1 $O1 rc=$RC $OUT"; fi

# 6. exec: runs once, keeps the rollback in its folder; a second exec fails
pair "$T/a"; go stage one "$T/a"; H=${OUT#one }; passed one "$H"; go approve one "$H"
go exec one "$H"; R1=$RC O1=$OUT
ID=$(ls "$RB" 2>/dev/null | head -n 1)
go exec one "$H"
if [ "$R1" = 0 ] && [[ $O1 == *$'\nOK\n'* ]] && [ "$(cat "$HOME/conf.txt")" = $'old\nadded' ] && [ -f "$RB/$ID/rollback.sh" ] && [ -f "$RB/$ID/save/conf.txt" ] \
  && [[ $ID == *-one ]] && [ "$RC" = 0 ] && [[ $OUT == *"has run already"* ]] && [ "$(cat "$HOME/conf.txt")" = $'old\nadded' ]; then ok "6 exec once, rollback kept"; else no "6 exec" "r1=$R1 $O1 / rc=$RC $OUT / $ID"; fi

# 7. undo: puts the file back once; the folder stays
go undo "$ID"; R1=$RC O1=$OUT; go undo "$ID"
if [ "$R1" = 0 ] && [ "$O1" = OK ] && [ "$(cat "$HOME/conf.txt")" = old ] && [[ $OUT == *"undone already"* ]] && [ -f "$RB/$ID/rollback.sh" ]; then ok "7 undo once, folder kept"; else no "7 undo" "$O1 / $OUT"; fi

# 8. the staged folder gone (a reboot): exec fails and runs nothing
pair "$T/b"; echo "# b" >> "$T/b/run.sh"; go stage two "$T/b"; H=${OUT#two }; passed two "$H"; go approve two "$H"; rm -rf "$T/b"
go exec two "$H"
if [ "$RC" = 0 ] && [[ $OUT == FAILED*"cannot copy"* ]] && [ "$(cat "$HOME/conf.txt")" = old ] && [ ! -e "$ST/ran/$H" ]; then ok "8 the folder gone: exec refused"; else no "8 gone" "$OUT"; fi

# 9. a root step: no line yet; a bad declared path: refused at the stage
pair "$T/c"; sed -i '2a # owner-run-user: root' "$T/c/run.sh"; go stage three "$T/c"; H=${OUT#three }; passed three "$H"; go approve three "$H"; go cmd three; R1=$RC O1=$OUT
pair "$T/d"; sed -i '2a # owner-run-file: /etc/passwd' "$T/d/run.sh"; go stage four "$T/d"
if [ "$R1" != 0 ] && [ -z "$O1" ] && [ "$RC" != 0 ] && [[ $ERR == *"starts with ~/"* ]]; then ok "9 root: no line; a path outside ~: refused"; else no "9 root, path" "r1=$R1 $O1 / rc=$RC $ERR"; fi

# 10-12. the real sandbox
if [ "$BWRAP" = 1 ]; then
  real_bwrap; echo old > "$HOME/conf.txt"
  pair "$T/e"; go stage five "$T/e"; H=${OUT#five }; go test five
  if [ "$RC" = 0 ] && [[ $OUT == *"PASSED five $H"* ]] && [ -f "$ST/tested/$H" ] && [ "$(cat "$HOME/conf.txt")" = old ]; then ok "10 sandbox: a good pair passes, the real file untouched"; else no "10 good pair" "rc=$RC $OUT $ERR"; fi
  pair "$T/f" '' 'true'; go stage six "$T/f"; H=${OUT#six }; go test six
  if [ "$RC" != 0 ] && [[ $OUT == *"NOT restored"* ]] && [ ! -f "$ST/tested/$H" ] && [ "$(cat "$HOME/conf.txt")" = old ]; then ok "11 sandbox: a rollback that restores nothing fails"; else no "11 bad rollback" "rc=$RC $OUT"; fi
  pair "$T/g" 'curl -s https://example.com >/dev/null || python3 -c "import socket; socket.create_connection((\"1.1.1.1\",53),2)"'; go stage seven "$T/g"; go test seven
  if [ "$RC" != 0 ] && [[ $OUT == *"run.sh exit "[1-9]* ]]; then ok "12 sandbox: no network"; else no "12 network" "rc=$RC $OUT"; fi
else skip "10-12 sandbox"; fi

echo "passed $PASS, failed $FAIL, skipped $SKIP"
[ "$FAIL" = 0 ]
