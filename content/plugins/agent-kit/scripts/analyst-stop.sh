#!/usr/bin/env bash
# analyst-stop.sh - a Stop hook: gives the turn's end to the kit's analyst (dashboard/analyst_ask.py), which asks a
# small model about a new finding in the background. It never stops the turn and never fails it; the analyst's own
# run of the model (AGENT_KIT_ANALYST set) is left alone.
[ -z "${AGENT_KIT_ANALYST:-}" ] || exit 0
ASK="$(dirname "$0")/../../../../dashboard/analyst_ask.py"
[ -f "$ASK" ] || exit 0
timeout 10 python3 -I "$ASK" hook >/dev/null 2>&1
exit 0
