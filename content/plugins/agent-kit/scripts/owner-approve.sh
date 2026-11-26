#!/usr/bin/env bash
# owner-approve.sh - a PreToolUse hook on Bash: a command that runs `owner-run approve` is denied unless it comes from
# the reviewer subagent owner-review (agent_type owner-review or PLUGIN:owner-review). So the agent that wrote a
# script cannot approve it itself. Any other command, or input it cannot read, passes untouched.
IN=$(cat) || exit 0
OWNER_IN="$IN" python3 - <<'PY' || exit 0
import json, os, re, sys
try:
    d = json.loads(os.environ["OWNER_IN"])
    cmd = d["tool_input"]["command"]
except (ValueError, KeyError, TypeError):
    sys.exit(0)
if not isinstance(cmd, str) or not re.search(r"owner-run\S*\s+approve\b", cmd):
    sys.exit(0)
if re.fullmatch(r"(.+:)?owner-review", str(d.get("agent_type") or "")):
    sys.exit(0)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
    "permissionDecisionReason": "owner-run approve is for the reviewer only: give the stage to the subagent owner-review."}}))
PY
exit 0
