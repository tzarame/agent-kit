#!/usr/bin/env bash
# tests/owner-stop.test.sh - tests of the hooks of the gate owner-run: content/plugins/agent-kit/scripts/owner-stop.sh (Stop: an
# ssh line to this machine not printed by the gate is stopped) and owner-approve.sh (PreToolUse: `owner-run approve`
# only from the subagent owner-review). HOME is a temp folder; the gate's hosts come from its config and $HOSTNAME, so no
# tailscale and no ip are called. Exit 0 when every case passes.
REPO=$(cd "$(dirname "$0")/.." && pwd -P)
T=$(mktemp -d) || exit 1
T=$(cd "$T" && pwd -P)
trap 'rm -rf "$T"' EXIT
HOME="$T/home"; export HOME
BIN="$T/bin"; ST="$HOME/.local/state/agent-kit/owner-run"
mkdir -p "$HOME/.config/agent-kit" "$ST" "$BIN" || exit 1
for p in bash sh sed tail head python3 dirname timeout cat; do ln -s "$(command -v "$p")" "$BIN/$p" || exit 1; done
printf 'TS_HOST=box-ts\nLAN_HOST=10.0.0.7\n' > "$HOME/.config/agent-kit/owner-run.env"
STOP="$REPO/content/plugins/agent-kit/scripts/owner-stop.sh"; APPROVE="$REPO/content/plugins/agent-kit/scripts/owner-approve.sh"
GOOD="ssh -o ConnectTimeout=5 -t me@box-ts /x/owner-run exec one 0123456789abcdef"
GOOD2="ssh -o ConnectTimeout=5 -t me@10.0.0.7 /x/owner-run exec one 0123456789abcdef"
printf '%s\n%s\n' "$GOOD" "$GOOD2" > "$ST/printed"
PASS=0 FAIL=0
ok() { PASS=$((PASS+1)); echo "ok   $1"; }
no() { FAIL=$((FAIL+1)); echo "FAIL $1"; [ -n "${2:-}" ] && printf '     %s\n' "$2"; }
# stop MESSAGE [ACTIVE]: the Stop hook on a final message; RC and OUT after it
stop() { OUT=$(python3 -c 'import json,sys; print(json.dumps({"hook_event_name":"Stop","last_assistant_message":sys.argv[1],"stop_hook_active":sys.argv[2]=="1"}))' "$1" "${2:-0}" \
  | env -i HOME="$HOME" PATH="$BIN" bash "$STOP" 2>&1); RC=$?; }
blocked() { [ "$RC" = 0 ] && [[ $OUT == *'"decision": "block"'* ]]; }
# approve COMMAND [AGENT_TYPE]: the PreToolUse hook on a Bash call
approve() { OUT=$(python3 -c 'import json,sys; d={"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":sys.argv[1]}}
if sys.argv[2]: d["agent_type"]=sys.argv[2]
print(json.dumps(d))' "$1" "${2:-}" | env -i HOME="$HOME" PATH="$BIN" bash "$APPROVE" 2>&1); RC=$?; }
denied() { [ "$RC" = 0 ] && [[ $OUT == *'"permissionDecision": "deny"'* ]]; }

# 1. the gate's line, as one line with || or apart, in backticks: passes
stop "Run this:
\`$GOOD || $GOOD2\`
or, with no ||:
    $GOOD2"
if [ "$RC" = 0 ] && [ -z "$OUT" ]; then ok "1 the gate's line passes"; else no "1 gate line" "rc=$RC $OUT"; fi

# 2. a hand-made line to this machine (the Tailscale name, its DNS name, the LAN address, root): stopped
r=1; for l in "ssh acme@box-ts 'cat ~/x'" "ssh root@box-ts.tail0.ts.net /usr/bin/true" "\$ ssh me@10.0.0.7 ls" "$GOOD || ssh me@$HOSTNAME sudo ls"; do
  stop "Paste: $l"; stop "$l"; blocked || { r=0; echo "     not stopped: $l / $OUT"; }; done
[ "$r" = 1 ] && ok "2 a line the gate did not print: stopped" || no "2 hand-made lines"

# 3. ssh to another machine, ssh in prose with no user@host, no ssh: pass
r=1; for l in "ssh git@github.com" "ssh deploy@other.example ls" "use ssh with your key" "all done"; do
  stop "$l"; { [ "$RC" = 0 ] && [ -z "$OUT" ]; } || { r=0; echo "     stopped: $l / $OUT"; }; done
[ "$r" = 1 ] && ok "3 other machines, prose, no ssh: pass" || no "3 pass"

# 4. stopped once already this turn, or input it cannot read: passes
stop "ssh me@box-ts ls" 1; R1=$RC O1=$OUT
OUT=$(echo 'ssh {not json' | env -i HOME="$HOME" PATH="$BIN" bash "$STOP" 2>&1); RC=$?
if [ "$R1" = 0 ] && [ -z "$O1" ] && [ "$RC" = 0 ] && [ -z "$OUT" ]; then ok "4 stop_hook_active and bad input: pass"; else no "4 fail open" "$R1 $O1 / $RC $OUT"; fi

# 5. approve: denied for the session and another subagent; allowed for owner-review, with or without the plugin's name
approve "owner-run approve one 0123456789abcdef"; D1=0; denied && D1=1
approve "/x/bin/owner-run  approve one 0123456789abcdef" "core:subagent"; D2=0; denied && D2=1
approve "owner-run approve one 0123456789abcdef" "core:owner-review"; A1=$RC$OUT
approve "owner-run approve one 0123456789abcdef" "owner-review"; A2=$RC$OUT
if [ "$D1$D2" = 11 ] && [ "$A1" = 0 ] && [ "$A2" = 0 ]; then ok "5 approve only for owner-review"; else no "5 approve" "d=$D1$D2 a1=$A1 a2=$A2"; fi

# 6. other commands and bad input: pass
approve "owner-run cmd one"; R1=$RC$OUT; approve "ls approve"; R2=$RC$OUT
OUT=$(echo '{' | env -i HOME="$HOME" PATH="$BIN" bash "$APPROVE" 2>&1); R3=$?$OUT
if [ "$R1" = 0 ] && [ "$R2" = 0 ] && [ "$R3" = 0 ]; then ok "6 other commands, bad input: pass"; else no "6 pass" "$R1 / $R2 / $R3"; fi

echo "passed $PASS, failed $FAIL"
[ "$FAIL" = 0 ]
