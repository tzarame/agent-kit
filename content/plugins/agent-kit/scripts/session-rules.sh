#!/usr/bin/env bash
# session-rules.sh - a SessionStart hook: gives the session the common rules (system-prompt.md), its own (agent.md)
# and its role's text. It runs at each start, resume and compaction, so the rules are there after a compaction too.
# A session the kit started has AGENT_KIT_PROMPT: 1, its agent's system prompt; 0, Claude Code's own with nothing of
# the kit's. Either way the hook gives nothing.
[ -n "${AGENT_KIT_PROMPT:-}" ] && exit 0
d=$(dirname "$(readlink -f "$0")")/..
cat "$d/system-prompt.md" "$d/agent.md"
# the role: the agent's file (AGENT_KIT_ROLE) without its header
if [ -r "${AGENT_KIT_ROLE:-}" ]; then
  awk 'NR == 1 && $0 == "---" { h = 1; next } h && $0 == "---" { h = 0; next } !h' "$AGENT_KIT_ROLE"
fi
