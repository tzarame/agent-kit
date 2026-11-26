#!/usr/bin/env bash
# subagent-rules.sh - a SubagentStart hook: gives each subagent the common rules (system-prompt.md) and its own
# (subagent.md), and between them the system-prompt.md of each plugin of the session that has one
# (AGENT_KIT_PLUGIN_PROMPTS, set by the start), as the hook's additionalContext. With AGENT_KIT_PROMPT=0 the kit
# started the session with Claude Code's own prompt and nothing of its own, and the hook gives nothing.
cat >/dev/null
[ "${AGENT_KIT_PROMPT:-}" = 0 ] && exit 0
d=$(dirname "$(readlink -f "$0")")/..
python3 -I - "$d/system-prompt.md" "${AGENT_KIT_PLUGIN_PROMPTS:-}" "$d/subagent.md" <<'PY'
import json, sys
def read(p):
    try:
        return open(p, encoding="utf-8").read().strip()
    except (OSError, UnicodeDecodeError):
        return ""    # a plugin's file that is gone since the start
paths = [sys.argv[1]] + [p for p in sys.argv[2].split(":") if p] + [sys.argv[3]]
text = "\n".join(t for t in map(read, paths) if t)
print(json.dumps({"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": text}}))
PY
