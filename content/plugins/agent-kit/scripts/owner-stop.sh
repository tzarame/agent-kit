#!/usr/bin/env bash
# owner-stop.sh - a Stop hook: a final message that gives the owner an `ssh` line to this machine which
# `owner-run cmd` did not print is stopped, and the agent is told to put the step through the gate (the skill
# owner-run). A line printed by the gate, an ssh line to another machine, and a message with no ssh pass. The hook
# lets the message through on its own error and when it has stopped this turn already (stop_hook_active).
IN=$(cat) || exit 0
GATE="$(dirname "$0")/../bin/owner-run"
ST="${XDG_STATE_HOME:-$HOME/.local/state}/agent-kit/owner-run"
case "$IN" in *ssh*) ;; *) exit 0 ;; esac
HOSTS=$(timeout 5 bash "$GATE" hosts 2>/dev/null) || HOSTS=$HOSTNAME
OWNER_IN="$IN" OWNER_HOSTS="$HOSTS" OWNER_PRINTED="$ST/printed" python3 - <<'PY' || exit 0
import json, os, re, sys
try:
    d = json.loads(os.environ["OWNER_IN"])
    msg = d.get("last_assistant_message") or ""
except ValueError:
    sys.exit(0)
if d.get("stop_hook_active") or not isinstance(msg, str):
    sys.exit(0)
hosts = {h.strip().lower() for h in os.environ.get("OWNER_HOSTS", "").split() if h.strip()}
try:
    printed = {l.strip() for l in open(os.environ["OWNER_PRINTED"], encoding="utf8")}
except OSError:
    printed = set()
def ours(part):   # an ssh command to this machine
    m = re.match(r"ssh\s.*?\b[\w.-]+@([\w.-]+)", part)
    if not m:
        return False
    h = m.group(1).lower()
    return any(h == x or h.startswith(x + ".") for x in hosts)
bad = []
for line in msg.splitlines():
    line = line.strip().strip("`").strip()
    line = re.sub(r"^(\$|>|PS>)\s*", "", line)
    for part in (p.strip().strip("`").strip() for p in line.split("||")):
        if ours(part) and part not in printed:
            bad.append(part)
if bad:
    print(json.dumps({"decision": "block", "reason": "This message gives the owner an ssh line the gate did not print: "
        + bad[0][:200] + " . Put the step through the gate (the skill owner-run: stage, the review by owner-review, "
        "owner-run cmd) and give its line, or take the line out."}))
PY
exit 0
