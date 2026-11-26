#!/usr/bin/env bash
# openspec-only.sh - a PreToolUse hook on Write, Edit and NotebookEdit: the agent spec writes only under openspec/ of
# the session's folder (cwd). Another file in the folder is denied with the reason; a file elsewhere, such as a
# scratch note, passes. The path is judged both as named and as its links resolve, so neither a link in the folder
# to a file outside nor openspec/.. lets a write through. Input it cannot read passes untouched. Only these tools are checked, not a shell command: it
# keeps a session on its task, it is not a lock.
IN=$(cat) || exit 0
SPEC_IN="$IN" python3 -I - <<'PY' || exit 0
import json, os, sys
try:
    d = json.loads(os.environ["SPEC_IN"])
    t = d["tool_input"]
    path, cwd = t.get("file_path") or t.get("notebook_path"), d["cwd"]
except (ValueError, KeyError, TypeError, AttributeError):
    sys.exit(0)
if not (isinstance(path, str) and path and isinstance(cwd, str) and cwd):
    sys.exit(0)
def outside_plans(root, full):
    """whether full is in the folder root but not under its openspec/"""
    plans = os.path.join(root, "openspec")
    return os.path.commonpath([full, root]) == root and os.path.commonpath([full, plans]) != plans
named = os.path.normpath(os.path.join(os.path.abspath(cwd), path))
real = os.path.realpath(os.path.join(cwd, path))
if not (outside_plans(os.path.normpath(os.path.abspath(cwd)), named) or outside_plans(os.path.realpath(cwd), real)):
    sys.exit(0)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
    "permissionDecisionReason": "The agent spec writes only under openspec/ of the project: it plans, the agent dev "
                                "writes the code. Put this in the change's tasks instead."}}))
PY
exit 0
