#!/usr/bin/env bash
# tests/dashboard.test.sh - the dashboard's server end to end: dash.py on a free port of 127.0.0.1, HOME a temp
# folder, the kit a fake that logs its arguments, tailscale a fake that is down, tmux on its own socket
# (env -u TMUX). The projects and the sessions read, start/stop/restart by the kit, tmux marks and close, the page, the key.
# Exit 0 when every case passes.
REPO=$(cd "$(dirname "$0")/.." && pwd -P)
T=$(mktemp -d) || exit 1; T=$(cd "$T" && pwd -P)
SOCK="dashtest-$$-$RANDOM"
cleanup() { [ -n "$SRV" ] && kill "$SRV" 2>/dev/null; env -u TMUX tmux -L "$SOCK" kill-server 2>/dev/null; rm -rf "$T"; }
trap cleanup EXIT
export HOME="$T/home"; BIN="$T/bin"; LOG="$T/kit.log"; KIT="$HOME/.config/agent-kit"
mkdir -p "$HOME" "$BIN" "$T/work" || exit 1
printf '#!/bin/sh\necho "$*" >> "%s"\necho "tmux=$TMUX" > "%s/kit.env"\n[ ! -f "%s/fail" ] || exit 3\n' "$LOG" "$T" "$T" > "$T/kit.sh"
printf '#!/bin/sh\nexit 1\n' > "$BIN/tailscale"; chmod +x "$BIN/tailscale"
PORT=$(python3 -I -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
B="http://127.0.0.1:$PORT"
PASS=0; FAIL=0; RC=0; OUT=""; SRV=""
check() { if [ "$2" = 0 ]; then PASS=$((PASS+1)); echo "ok   - $1"; else FAIL=$((FAIL+1)); echo "FAIL - $1 | out: $OUT"; fi; }
# req METHOD PATH [BODY] -> OUT (body) and RC (HTTP status)
req() {
  local data=()
  [ -n "${3:-}" ] && data=(-H 'Content-Type: application/json' --data-binary "$3")
  OUT=$(curl -s -o "$T/body" -w '%{http_code}' -X "$1" "${data[@]}" "$B$2"); RC=$OUT; OUT=$(cat "$T/body")
}
jq_() { python3 -I -c 'import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1]))' "$1" < "$T/body" 2>/dev/null; }
tm() { env -u TMUX tmux -L "$SOCK" "$@"; }

TMUX=/x/of-the-terminal AGENT_KIT_KIT="sh $T/kit.sh" AGENT_KIT_TMUX="tmux -L $SOCK" PATH="$BIN:$PATH" \
  python3 -I "$REPO/dashboard/dash.py" --port "$PORT" > "$T/server.log" 2>&1 &
SRV=$!
for _ in $(seq 50); do curl -s -o /dev/null "$B/api/v1/hello" && break; sleep 0.1; done

# 1. hello with no key; the page with its security headers
req GET /api/v1/hello
[ "$RC" = 200 ] && [ "$(jq_ 'd["kind"]')" = dashboard ] && [ "$(jq_ 'd["api"]')" = 1 ]
check "hello: 200, kind dashboard, api 1, no key" $?
hdr=$(curl -s -D - -o "$T/page" "$B/") 
printf '%s' "$hdr" | grep -qi '^Content-Security-Policy:' && printf '%s' "$hdr" | grep -qi '^HTTP/1.0 200\|^HTTP/1.1 200' \
  && grep -q '<title>Agents' "$T/page" && ! printf '%s' "$hdr" | grep -qi 'Access-Control-Allow-Origin'
check "page: 200, CSP set, no Access-Control-Allow-Origin" $?
# 2. state with no config of the kit
req GET /api/v1/state
[ "$RC" = 200 ] && [ "$(jq_ 'd["agents"]')" = "[]" ] && [ "$(jq_ 'd["tmux"]')" = "[]" ] && [ "$(jq_ 'sorted(d["machine"])')" != "" ]
check "state: 200 with machine, no agents, no tmux sessions" $?
# 3. the agents are the projects of the kit's config: the fields of a new session, the agent over the project
mkdir -p "$KIT/sessions"
cat > "$KIT/config.json" <<EOF
{"version": 3, "session": {"model": "haiku", "effort": "low"},
 "projects": {"work": {"folder": "$T/work", "model": "sonnet", "agent": "p"}, "other": {}, "bad/name": {}},
 "agents": {"p": {"effort": "high", "agent": "dev"}}}
EOF
req GET /api/v1/state
[ "$(jq_ '[a["id"] for a in d["agents"]]')" = "['other', 'work']" ] && [ "$(jq_ 'd["agents"][1]["model"]')" = sonnet ] \
  && [ "$(jq_ 'd["agents"][1]["effort"]')" = high ] && [ "$(jq_ 'd["agents"][1]["role"]')" = p ] \
  && [ "$(jq_ 'd["agents"][1]["dir"]')" = "$T/work" ] && [ "$(jq_ 'd["agents"][0]["dir"]')" = "$HOME/other" ] \
  && [ "$(jq_ 'd["agents"][1]["running"]')" = False ]
check "state: the projects of config.json, a bad name left out, the folder of a project with none" $?
# 4. the dashboard writes nothing of the kit's: no route makes or changes a project
cp "$KIT/config.json" "$T/config.before"
req POST /api/v1/profiles "{\"dir\":\"$T/work\"}"; a=$RC
req PUT /api/v1/profiles/work '{"model":"opus"}'; b=$RC
req DELETE /api/v1/profiles/work; c=$RC
[ "$a$b$c" = 404404404 ] && cmp -s "$KIT/config.json" "$T/config.before"
check "no route writes a project: 404, config.json as it was" $?
# 5. a body over 1 MB: 413
head -c 1200000 /dev/zero | tr '\0' 'a' > "$T/big"
RC=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' --data-binary "@$T/big" "$B/api/v1/agents/work/start")
[ "$RC" = 413 ]
check "body over 1 MB: 413" $?
# 6. start: the kit gets start and the project; the model and the effort as keys of this start
req POST /api/v1/agents/work/start '{}'; a=$RC
req POST /api/v1/agents/work/start '{"model":"fable","effort":"high"}'; b=$RC
[ "$a$b" = 200200 ] && grep -qx "start work" "$LOG" && grep -qx "start work --fable --high" "$LOG"
check "start: kit start PROJECT, with the keys given" $?
req POST /api/v1/agents/work/start '{"fresh":true}'; a=$RC
req POST /api/v1/agents/work/start '{"model":"gpt"}'; b=$RC
req POST /api/v1/agents/work/start '{"effort":"--dry-run"}'; c=$RC
req POST /api/v1/agents/work/start 'not json'; e=$RC
[ "$a$b$c$e" = 400400400400 ] && ! grep -q 'gpt\|dry-run' "$LOG"
check "start: another field, an unknown model or effort, not JSON: 400, the kit not called" $?
# 7. a session of the kit in tmux: the project runs, the session is marked as its, with what it runs with
ses() { printf '{"id": "%s", "project": "%s", "folder": "%s", "keys": [], "config": {"model": "%s", "effort": "high", "agent": "p", "idle_compact_from": 100000, "cache_life": null, "env": {"A_TOKEN": "t0p"}, "system_prompt": "x"}}\n' \
  "$1" "$2" "$T/work" "$3" > "$KIT/sessions/$1.json"; tm new-session -d -s "$1" "sleep 300"; }
ses aaaa work sonnet; ses bbbb work opus
printf '{"id": "cccc", "project": "work", "config": {}}\n' > "$KIT/sessions/cccc.json"   # its tmux session is gone
req GET /api/v1/state
[ "$(jq_ 'd["agents"][1]["running"]')" = True ] && [ "$(jq_ '[s["id"] for s in d["agents"][1]["sessions"]]')" = "['aaaa', 'bbbb']" ] \
  && [ "$(jq_ '[s["differs"] for s in d["agents"][1]["sessions"]]')" = "[False, True]" ] \
  && [ "$(jq_ 'sorted((t["name"], t["agent"]) for t in d["tmux"])')" = "[('aaaa', 'work'), ('bbbb', 'work')]" ] \
  && [ "$(jq_ 'd["agents"][0]["running"]')" = False ]
check "state: the sessions that run, each with its fields; one that differs from the project is said" $?
[ "$(jq_ 'sorted(d["agents"][1]["sessions"][0]["settings"].items(), key=str)')" \
  = "[('agent', 'p'), ('cache_life', None), ('effort', 'high'), ('idle_compact_from', 100000), ('model', 'sonnet')]" ] \
  && ! grep -q 't0p' "$T/body"
check "state: a session's settings as it was started, plain values only, never its env or its prompt" $?
# 8. one session stopped: kit kill ID; a session that does not run: 404
req POST /api/v1/sessions/bbbb/stop; a=$RC
req POST /api/v1/sessions/cccc/stop; b=$RC
req POST /api/v1/sessions/zzzz/stop; c=$RC
[ "$a$b$c" = 200404404 ] && grep -qx "kill bbbb" "$LOG" && ! grep -q "kill cccc" "$LOG"
check "session stop: kit kill ID; 404 for a session that does not run" $?
# 9. stop: each session of the project that runs; restart: the stops, then a start
: > "$LOG"
req POST /api/v1/agents/work/stop
[ "$RC" = 200 ] && [ "$(cat "$LOG")" = "kill aaaa
kill bbbb" ]
check "stop: kit kill for each session of the project" $?
: > "$LOG"
req POST /api/v1/agents/work/restart '{"model":"opus"}'
[ "$RC" = 200 ] && [ "$(cat "$LOG")" = "kill aaaa
kill bbbb
start work --opus" ]
check "restart: the stops, then kit start with the keys" $?
: > "$LOG"
req POST /api/v1/agents/other/stop
[ "$RC" = 200 ] && [ "$(jq_ 'd["ok"]')" = True ] && [ ! -s "$LOG" ]
check "stop of a project with no session: ok, the kit not called" $?
# 10. a failed kit is said, not hidden; a failed stop of a restart starts nothing
: > "$T/fail"; : > "$LOG"
req POST /api/v1/agents/work/start '{}'; a=$RC; ok=$(jq_ 'd["ok"]')
req POST /api/v1/agents/work/restart '{}'
rm -f "$T/fail"
[ "$a" = 200 ] && [ "$ok" = False ] && [ "$(jq_ 'd["ok"]')" = False ] && [ "$(grep -c '^start' "$LOG")" = 1 ]
check "a failing kit: ok false in the answer; a restart whose stop failed starts nothing" $?
# 11. the kit is called with no TMUX of the dashboard's own terminal
grep -q '^tmux=$' "$T/kit.env"
check "the kit runs with no TMUX: it opens no session on the dashboard's terminal" $?
tm kill-session -t aaaa; tm kill-session -t bbbb
# 12. close a tmux session: 200, then 404; a name with a bad character: 400
tm new-session -d -s "free-one" "sleep 300"
req DELETE "/api/v1/tmux/free-one"; a=$RC
req DELETE "/api/v1/tmux/free-one"; b=$RC
req DELETE "/api/v1/tmux/a%3Bb"; c=$RC
[ "$a$b$c" = 200404400 ] && ! tm has-session -t free-one 2>/dev/null
check "tmux close: 200, then 404 for the gone session, 400 for a bad name" $?
# 14. unknown paths; no agent for an unknown ID
req GET /api/v1/nothing; a=$RC
req POST /api/v1/agents/zzzz/start '{}'; b=$RC   # no such project
[ "$a$b" = 404404 ]
check "unknown path and unknown agent: 404" $?
# 15. the key: printed by the key command, the same until --new
K1=$(HOME="$HOME" python3 -I "$REPO/dashboard/dash.py" key 2>/dev/null)
K2=$(HOME="$HOME" python3 -I "$REPO/dashboard/dash.py" key 2>/dev/null)
[ "${#K1}" -ge 32 ] && [ "$K1" = "$K2" ] && [ -f "$HOME/.config/agent-kit/dashboard-key" ]
check "key: printed, the same key again" $?
# 16. --bind tailscale: the machine's Tailscale address, 127.0.0.1 and a word when there is none or it is no address
bound() {   # bound WHAT-TAILSCALE-PRINTS RC -> the server's first lines
  printf '#!/bin/sh\necho "%s"\nexit %s\n' "$1" "$2" > "$T/ts/tailscale"; chmod +x "$T/ts/tailscale"
  PATH="$T/ts:$PATH" python3 -I "$REPO/dashboard/dash.py" --port "$P2" --bind tailscale > "$T/bound" 2>&1 &
  local p=$!
  for _ in $(seq 50); do grep -q '^dashboard on' "$T/bound" && break; sleep 0.1; done
  kill "$p" 2>/dev/null; wait "$p" 2>/dev/null; OUT=$(cat "$T/bound")
}
mkdir -p "$T/ts"
P2=$(python3 -I -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
LO2="127.0.0.$((1 + 1))"   # a second loopback address, in place of a Tailscale one
bound "$LO2" 0
printf '%s' "$OUT" | grep -q "^dashboard on http://$LO2:" && ! printf '%s' "$OUT" | grep -q 'no Tailscale address'
check "bind tailscale: on the address tailscale gives" $?
bound "" 1; a=$OUT; bound "not an address; rm" 0
for o in "$a" "$OUT"; do
  printf '%s' "$o" | grep -q '^no Tailscale address: the dashboard is on this machine only' \
    && printf '%s' "$o" | grep -q '^dashboard on http://127.0.0.1:' || a=bad
done
[ "$a" != bad ]
check "bind tailscale: 127.0.0.1 and a word when tailscale is down or prints no address" $?

echo "passed $PASS, failed $FAIL"; [ "$FAIL" = 0 ]
