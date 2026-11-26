#!/usr/bin/env bash
# tests/dashboard-routes.test.sh - the dashboard's routes of notes, console, terminal, files and telemetry, end to end:
# dash.py on a free port of 127.0.0.1, HOME a temp folder, a git repository of the agent's folder in the temp folder,
# tmux on its own socket (env -u TMUX). A session agent-ID stands for an agent: nothing may be typed into it.
# Exit 0 when every case passes.
REPO=$(cd "$(dirname "$0")/.." && pwd -P)
T=$(mktemp -d) || exit 1; T=$(cd "$T" && pwd -P)
SOCK="routestest-$$-$RANDOM"
cleanup() { [ -n "$SRV" ] && kill "$SRV" 2>/dev/null; env -u TMUX tmux -L "$SOCK" kill-server 2>/dev/null; rm -rf "$T"; }
trap cleanup EXIT
export HOME="$T/home"; BIN="$T/bin"; mkdir -p "$HOME" "$BIN" "$T/work" || exit 1
printf '#!/bin/sh\nexit 1\n' > "$BIN/tailscale"; chmod +x "$BIN/tailscale"
# the old launcher is a fake: nothing calls it
mkdir -p "$T/fake" && printf '#!/bin/sh\necho "launcher $*" >> "$HOME/launcher-calls"\nexit 1\n' > "$T/fake/agent.sh"
chmod +x "$T/fake/agent.sh"
export SHELL=/bin/sh
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

# the agent's folder: a git repository on branch main, with a file and a folder
git -C "$T/work" init -q && git -C "$T/work" symbolic-ref HEAD refs/heads/main
git -C "$T/work" -c user.name=tester -c user.email=tester@localhost commit -q --allow-empty -m first
printf 'hello file\n' > "$T/work/README.md"; mkdir "$T/work/sub"; printf 'x\n' > "$T/work/sub/a.txt"
printf 'secret-outside\n' > "$T/x"   # next to the folder: a path that leaves it must never read this

AGENT_KIT_TMUX="tmux -L $SOCK" AGENT_KIT_LAUNCHER="bash $T/fake/agent.sh" PATH="$BIN:$PATH" \
  python3 -I "$REPO/dashboard/dash.py" --port "$PORT" > "$T/server.log" 2>&1 &
SRV=$!
for _ in $(seq 50); do curl -s -o /dev/null "$B/api/v1/hello" && break; sleep 0.1; done

# 0. a project of the kit's config, its folder the git repository; SID is its session, started by hand below
ID=routes; OID=other; SID=rtss; KIT="$HOME/.config/agent-kit"; mkdir -p "$KIT/sessions" "$T/other"
printf '{"version": 2, "projects": {"routes": {"folder": "%s"}, "other": {"folder": "%s"}}}\n' "$T/work" "$T/other" > "$KIT/config.json"
req GET /api/v1/state
[ "$RC" = 200 ] && [ "$(jq_ '[a["id"] for a in d["agents"]]')" = "['other', 'routes']" ]
check "the projects of the config are the agents" $?

# 1. notes: written, read back; the project's branch is untouched
HEAD0=$(git -C "$T/work" rev-parse HEAD)
req PUT "/api/v1/notes/$ID" '{"text":"# Notes\nhello routes\n"}'; a=$RC
req GET "/api/v1/notes/$ID"; b=$RC
[ "$a$b" = 200200 ] && [ "$(jq_ 'd["text"]')" = "$(printf '# Notes\nhello routes')" ] \
  && [ "$(jq_ 'type(d["saved"]).__name__')" != NoneType ]
check "notes: written and read back, 200" $?
[ "$(git -C "$T/work" symbolic-ref --short HEAD)" = main ] && [ "$(git -C "$T/work" rev-parse HEAD)" = "$HEAD0" ] \
  && git -C "$T/work" rev-parse --verify -q notes >/dev/null
check "notes: the branch main and its HEAD untouched; the notes live on branch notes" $?
req PUT "/api/v1/notes/$ID" '{"text":"a\u0000b"}'
check "notes: a NUL character gives 400" $([ "$RC" = 400 ]; echo $?)
head -c 1100000 /dev/zero | tr '\0' 'a' | python3 -I -c 'import json,sys; sys.stdout.write(json.dumps({"text": sys.stdin.read()}))' > "$T/big.json"
RC=$(curl -s -o "$T/body" -w '%{http_code}' -X PUT -H 'Content-Type: application/json' --data-binary "@$T/big.json" "$B/api/v1/notes/$ID")
check "notes: a note over 1 MB is refused (413 by the body cap, before the notes module)" $([ "$RC" = 413 ]; echo $?)
req GET /api/v1/notes/zzzz; a=$RC
req PUT /api/v1/notes/zzzz '{"text":"x"}'; b=$RC
[ "$a$b" = 404404 ]
check "notes: an unknown agent is 404" $?

# 2. console: 404 while the agent does not run; the session agent-ID started by hand shows its text
req GET "/api/v1/agents/$ID/console"
[ "$RC" = 404 ] && [ "$(jq_ 'd["error"]')" = "not running" ]
check "console: an agent not running is 404 'not running'" $?
printf '{"id": "%s", "project": "routes", "folder": "%s", "config": {}}\n' "$SID" "$T/work" > "$KIT/sessions/$SID.json"
tm new-session -d -s "$SID" -x 120 -y 32 "sh -c 'echo console-hello; sleep 600'"
for _ in $(seq 30); do req GET "/api/v1/agents/$ID/console"; [[ "$OUT" == *console-hello* ]] && break; sleep 0.1; done
[ "$RC" = 200 ] && [[ "$(jq_ 'd["screen"]')" == *console-hello* ]] && [ "$(jq_ 'd["cols"]')" = 120 ]
check "console: the session's screen shows its text, size 120" $?

# 3. console is read only: POST is not a route, and the screen stays the same
req GET "/api/v1/agents/$ID/console"; before=$(jq_ 'd["screen"]')
req POST "/api/v1/agents/$ID/console" '{"text":"should-not-appear"}'; code=$RC
req GET "/api/v1/agents/$ID/console"; after=$(jq_ 'd["screen"]')
[ "$code" = 404 ] && [ "$before" = "$after" ] && [[ "$after" != *should-not-appear* ]]
check "console: POST is not a route (404), the agent's screen unchanged" $?

# 4. terminal: open, type, read the output, close; POST to an agent's session is refused
req GET /api/v1/terminal; a=$(jq_ 'd["terminals"]')
req POST /api/v1/terminal; b=$RC; TID=$(jq_ 'd["tid"]')
[ "$a" = "[]" ] && [ "$b" = 201 ] && [[ "$TID" =~ ^term-[a-z0-9]{4}$ ]]
check "terminal: none open, then one opened (201, term-XXXX)" $?
req POST "/api/v1/terminal/$TID" '{"text":"echo routes-$((40+2))"}'; a=$RC
req POST "/api/v1/terminal/$TID" '{"key":"Enter"}'; b=$RC
found=no
for _ in $(seq 50); do req GET "/api/v1/terminal/$TID"; [[ "$(jq_ 'd["screen"]')" == *routes-42* ]] && { found=yes; break; }; sleep 0.1; done
[ "$a$b" = 200200 ] && [ "$found" = yes ]
check "terminal: typed echo routes-\$((40+2)) and Enter; the screen shows routes-42" $?
req POST /api/v1/terminal/agent-"$ID" '{"text":"should-not-appear"}'; code=$RC
req GET "/api/v1/agents/$ID/console"; after=$(jq_ 'd["screen"]')
[ "$code" = 404 ] && [[ "$after" != *should-not-appear* ]]
check "terminal: POST to an agent's session is 404 and nothing is typed there" $?
req DELETE "/api/v1/terminal/$TID"; a=$RC
req GET "/api/v1/terminal/$TID"; b=$RC
[ "$a$b" = 200404 ] && ! tm has-session -t "$TID" 2>/dev/null
check "terminal: closed (200), then 404" $?
# four open at most: the fifth is 409
TIDS=()
for _ in 1 2 3 4; do req POST /api/v1/terminal; TIDS+=("$(jq_ 'd["tid"]')"); done
req POST /api/v1/terminal; fifth=$RC
for t in "${TIDS[@]}"; do req DELETE "/api/v1/terminal/$t"; done
[ "$fifth" = 409 ] && ! tm list-sessions -F '#{session_name}' 2>/dev/null | grep -q '^term-'
check "terminal: a fifth one is 409; the four are closed" $?

# 5. files: list, read, save; the mtime rules; paths that leave the folder
req GET "/api/v1/agents/$ID/files"; a=$RC
[ "$a" = 200 ] && [ "$(jq_ 'd["kind"]')" = dir ] && [[ "$OUT" == *README.md* ]]
check "files: the folder's list, 200" $?
req GET "/api/v1/agents/$ID/files?path=README.md"
[ "$RC" = 200 ] && [ "$(jq_ 'd["kind"]')" = file ] && [ "$(jq_ 'd["text"]')" = "$(printf 'hello file\n')" ]
check "files: a file is read with its text and mtime" $?
M=$(jq_ 'd["mtime"]')
req PUT "/api/v1/agents/$ID/files?path=README.md" "{\"text\":\"changed\n\",\"mtime\":\"$M\"}"
[ "$RC" = 200 ] && [ "$(cat "$T/work/README.md")" = changed ]
check "files: saved with the right mtime (200)" $?
req PUT "/api/v1/agents/$ID/files?path=README.md" "{\"text\":\"stale\n\",\"mtime\":\"$M\"}"; a=$RC
[ "$a" = 409 ] && [ "$(jq_ 'd["kind"]')" = changed ] && [ "$(cat "$T/work/README.md")" = changed ]
check "files: a save with an old mtime is 409 and the file is not overwritten" $?
req GET "/api/v1/agents/$ID/files?path=..%2fx"; a=$RC; A=$OUT
req GET "/api/v1/agents/$ID/files?path=../x"; b=$RC; Bo=$OUT
req GET "/api/v1/agents/$ID/files?path=%2e%2e/x"; c=$RC; Co=$OUT
req GET "/api/v1/agents/$ID/files?path=/etc/passwd"; d=$RC
req PUT "/api/v1/agents/$ID/files?path=../x" '{"text":"hacked\n","mtime":null}'; e=$RC
[ "$a$b$c$d$e" = 403403403403403 ] && [[ "$A$Bo$Co" != *secret-outside* ]] && [ "$(cat "$T/x")" = secret-outside ]
check "files: ../x, %2e%2e/x and /etc/passwd are 403; the file outside is untouched" $?
req GET "/api/v1/agents/zzzz/files"; a=$RC
[ "$a" = 404 ]
check "files: an unknown agent is 404" $?

# 6. telemetry: status, install, the keys never in an answer, a bad address, delete
req GET /api/v1/telemetry; a=$(jq_ 'd["set_up"]')
req PUT /api/v1/telemetry '{"logs_url":"ftp://127.0.0.1:9428","traces_to":""}'; b=$RC
req PUT /api/v1/telemetry '{"logs_url":"http://user:pw@127.0.0.1:9428","traces_to":""}'; c=$RC
[ "$a" = False ] && [ "$b" = 400 ] && [ "$c" = 400 ]
check "telemetry: not set up at first; a bad address and a user in an address are 400" $?
req PUT /api/v1/telemetry '{"logs_url":"http://127.0.0.1:9428","traces_to":"langfuse","langfuse_url":"http://127.0.0.1:3000","langfuse_public_key":"pk-routes","langfuse_secret_key":"sk-SECRET-ROUTES","read_langfuse_url":"http://127.0.0.1:3000","read_langfuse_public_key":"pk-read-routes","read_langfuse_secret_key":"sk-READ-ROUTES"}'; a=$RC; A=$OUT
req GET /api/v1/telemetry; b=$RC; Bo=$OUT
[ "$a" = 200 ] && [ "$(jq_ 'd["set_up"]')" = True ] && [ "$(jq_ 'd["receivers"]')" = "['victorialogs', 'langfuse']" ]
check "telemetry: installed, status true with the receivers' names" $?
[[ "$A$Bo" != *sk-SECRET-ROUTES* && "$A$Bo" != *pk-routes* && "$A$Bo" != *READ-ROUTES* && "$A$Bo" != *read-routes* ]] && [ -f "$HOME/.config/agent-kit/telemetry.env" ] \
  && grep -q "^LANGFUSE_SECRET_KEY='sk-READ-ROUTES'$" "$HOME/.config/agent-kit/telemetry.env"
check "telemetry: no key in any answer (the reading key neither), the reading key in the file" $?
req DELETE /api/v1/telemetry; a=$RC
req GET /api/v1/telemetry; [ "$a" = 200 ] && [ "$(jq_ 'd["set_up"]')" = False ] && [ ! -f "$HOME/.config/agent-kit/telemetry.env" ]
check "telemetry: removed (200), status false" $?

# 7. what the kit does not write yet: no last event, no answers, no telemetry mode, and no mark of the kit's update
req GET /api/v1/state
[ "$RC" = 200 ] && [ "$(jq_ '[d["agents"][1][k] for k in ("answers", "last_event", "telemetry")]')" = "[None, None, 'nodata']" ] \
  && [ "$(jq_ '"kit" in d["agents"][1]')" = False ]
check "state: answers and last_event null, telemetry nodata, no kit mark" $?
touch -d "2 minutes ago" "$KIT/sessions/$SID.json"   # the session's start is its file's time

# 9. costs: made-up conversation files in the temp HOME (one reply per line, Opus 5: 1 MTok of input = 5.00 USD)
#    the folder of an agent is its path with each character that is not a letter or a digit turned into '-'
DAY=86400
WF=$(printf '%s' "$T/work" | sed 's/[^A-Za-z0-9]/-/g'); OF=$(printf '%s' "$T/other" | sed 's/[^A-Za-z0-9]/-/g')
conv() {   # conv FOLDER FILE UNIX-TIME INPUT-TOKENS: one assistant reply of Opus 5 at that time
  mkdir -p "$HOME/.claude/projects/$1"
  printf '{"type":"assistant","timestamp":"%s","gitBranch":"267-costs","message":{"id":"m%s","model":"claude-opus-5-20260101","role":"assistant","content":[{"type":"text","text":"ok"}],"usage":{"input_tokens":%s,"output_tokens":0,"cache_read_input_tokens":0,"cache_creation_input_tokens":0}}}\n' \
    "$(date -u -d "@$3" +%Y-%m-%dT%H:%M:%S.000Z)" "$RANDOM$RANDOM" "$4" >> "$HOME/.claude/projects/$1/$2.jsonl"
}
NOW=$(date +%s)
conv "$WF" s1 $((NOW - DAY)) 1000000          # a day ago: in the default week
conv "$WF" s2 $((NOW - 30 * DAY)) 2000000     # 30 days ago: out of the default week
conv "$OF" s3 $((NOW - DAY)) 3000000          # another agent's folder, a day ago
req GET /api/v1/costs; a=$RC; A=$OUT
[ "$a" = 200 ] && [ "$(jq_ 'd["until"] - d["since"]')" = 604800 ] && [ "$(jq_ 'abs(d["until"] - '"$NOW"') < 120')" = True ] \
  && [ "$(jq_ 'd["total"]["input"]')" = 4000000 ] && [ "$(jq_ 'round(d["total"]["usd"], 2)')" = 20.0 ]
check "costs: default period is the last 7 days (until now), 4 MTok of input from the two folders, 20.00 USD" $?
req GET "/api/v1/costs?since=$((NOW - 31 * DAY))&until=$((NOW - 29 * DAY))"; a=$RC
[ "$a" = 200 ] && [ "$(jq_ 'd["total"]["input"]')" = 2000000 ] && [ "$(jq_ 'd["since"]')" = $((NOW - 31 * DAY)) ] \
  && [ "$(jq_ 'd["until"]')" = $((NOW - 29 * DAY)) ] && [ "$(jq_ 'len(d["tasks"])')" = 1 ]
check "costs: a given period counts only the reply in it (2 MTok, 200)" $?
req GET "/api/v1/costs?agent=$ID"; a=$RC
[ "$a" = 200 ] && [ "$(jq_ 'len(d["agents"])')" = 1 ] && [ "$(jq_ 'd["agents"][0]["folder"]')" = "$WF" ] \
  && [ "$(jq_ 'd["total"]["input"]')" = 1000000 ]
check "costs: agent=ID counts only that agent's folder (1 MTok)" $?
req GET "/api/v1/costs?agent=$OID"; [ "$RC" = 200 ] && [ "$(jq_ 'd["total"]["input"]')" = 3000000 ]
check "costs: the other agent's folder alone (3 MTok)" $?
req GET "/api/v1/costs?since=$((NOW - 2 * DAY))&until=$((NOW - 3 * DAY))"; a=$RC
[ "$a" = 400 ] && [ -n "$(jq_ 'd["error"]')" ]
check "costs: since after until is 400 with an error" $?
req GET "/api/v1/costs?since=abc"; a=$RC; A=$OUT
req GET "/api/v1/costs?until=1.5"; b=$RC
req GET "/api/v1/costs?since=-5"; c=$RC
[ "$a$b$c" = 400400400 ] && [[ "$A" == *'"error"'* ]]
check "costs: a number that is not whole seconds (abc, 1.5, -5) is 400 with an error" $?
req GET "/api/v1/costs?since=$((NOW - 367 * DAY))&until=$NOW"; a=$RC
req GET "/api/v1/costs?since=$((NOW - 366 * DAY))&until=$NOW"; b=$RC
[ "$a$b" = 400200 ]
check "costs: a period over 366 days is 400; exactly 366 days is 200" $?
req GET /api/v1/analyst; a=$RC
[ "$a" = 200 ] && [ "$(jq_ 'd["until"] - d["since"]')" = 604800 ] && [ "$(jq_ 'sorted(d) == ["findings", "rules", "since", "until", "watch"]')" = True ] \
  && [ "$(jq_ 'd["rules"]["cache_miss"]["count"]')" = 0 ] && [ "$(jq_ 'd["watch"]["calls"]')" = 2 ]
check "analyst: the default week, the rules, the findings (none in these files) and the watched numbers" $?
req GET "/api/v1/analyst?since=abc"; a=$RC
req GET "/api/v1/analyst?agent=zzzz"; b=$RC
[ "$a" = 400 ] && [ "$b" = 404 ]
check "analyst: a wrong period is 400, an unknown agent 404, as for the costs" $?
req GET "/api/v1/costs?agent=zzzz"; a=$RC; err=$(jq_ 'd["error"]')
req GET "/api/v1/costs?agent=$ID"; b=$RC
[ "$a" = 404 ] && [ "$err" = "no such agent" ] && [ "$b" = 200 ]
check "costs: an unknown agent is 404 with an error" $?

# 6b. telemetry check and arrives; the state's telemetry field: a session started before telemetry.env was written
#     needs a restart. The receiver's port is free (nothing listens): every answer is "unreachable" and no key shows.
DOWNP=$(python3 -I -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')
req PUT /api/v1/telemetry "{\"logs_url\":\"http://127.0.0.1:$DOWNP\",\"logs_user\":\"lu\",\"logs_password\":\"pw-ROUTES-SECRET\",\"traces_to\":\"\"}"
a=$RC
req GET /api/v1/state
RUNNING=$(jq_ "[a for a in d['agents'] if a['id']=='$ID'][0]['running']"); TEL=$(jq_ "[a for a in d['agents'] if a['id']=='$ID'][0]['telemetry']")
[ "$a" = 200 ] && [ "$RUNNING" = True ] && [ "$TEL" = nodata ]
check "state: telemetry is nodata with the file written (the kit gives it to no session yet)" $?
req POST /api/v1/telemetry/check; a=$RC; A=$OUT
[ "$a" = 200 ] && [ "$(jq_ 'd["receivers"]["victorialogs"]["key"]')" = unreachable ] && [[ "$A" != *pw-ROUTES-SECRET* ]]
check "telemetry check: 200, the receiver is unreachable, the password in no answer" $?
req GET /api/v1/telemetry/arrives; a=$RC; A=$OUT
[ "$a" = 200 ] && [ "$(jq_ "d['agents']['$ID']['late']")" = False ] && [ -n "$(jq_ 'd["reason"]')" ] && [[ "$A" != *pw-ROUTES-SECRET* ]]
check "telemetry arrives: 200, the agent with late false, a reason, the password in no answer" $?
req GET /api/v1/telemetry/arrives?x=1; [ "$RC" = 200 ]
check "telemetry arrives: the query string is ignored (200)" $?
req DELETE /api/v1/telemetry; a=$RC
req GET /api/v1/state
[ "$a" = 200 ] && [ "$(jq_ "[a for a in d['agents'] if a['id']=='$ID'][0]['telemetry']")" = nodata ]
check "state: telemetry is nodata once removed" $?
req GET /api/v1/telemetry/check; [ "$RC" = 404 ] || [ "$RC" = 405 ]
check "telemetry check: a GET is not a route (404 or 405)" $?

# 8. the access check still refuses a foreign Origin
RC=$(curl -s -o /dev/null -w '%{http_code}' -H 'Origin: http://evil.example' "$B/api/v1/state")
check "a foreign Origin is refused (403)" $([ "$RC" = 403 ]; echo $?)

# 10. no update from the dashboard: the routes are gone
for r in "GET /api/v1/version" "GET /api/v1/update" "POST /api/v1/update"; do
  req $r; check "update: $r is not a route (404)" $([ "$RC" = 404 ]; echo $?)
done
[ ! -s "$HOME/launcher-calls" ]
check "the old launcher (the fake agent.sh) was never run" $?

echo "passed $PASS, failed $FAIL"; [ "$FAIL" = 0 ]
