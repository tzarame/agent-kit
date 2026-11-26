#!/usr/bin/env bash
# no-code.sh - a PreToolUse hook on Write, Edit and NotebookEdit: a QA session changes no file of the project. A file
# in the session's folder (cwd) is denied with the reason; a file elsewhere, such as a scratch script, passes. Input it
# cannot read passes untouched. Only these tools are checked, not a shell command: it keeps a session on its task, it
# is not a lock.
IN=$(cat) || exit 0
QA_IN="$IN" python3 -I - <<'PY' || exit 0
import json, os, sys
try:
    d = json.loads(os.environ["QA_IN"])
    t = d["tool_input"]
    path, cwd = t.get("file_path") or t.get("notebook_path"), d["cwd"]
except (ValueError, KeyError, TypeError, AttributeError):
    sys.exit(0)
if not (isinstance(path, str) and path and isinstance(cwd, str) and cwd):
    sys.exit(0)
root = os.path.realpath(cwd)
if os.path.commonpath([os.path.realpath(os.path.join(root, path)), root]) != root:
    sys.exit(0)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
    "permissionDecisionReason": "This is a QA session: it changes no file of the project. "
                                "Report the finding instead (the skill qa:testing)."}}))
PY
exit 0
