#!/usr/bin/env bash
# install/update.sh - kit update: the kit's copy moved on (install/common.sh repo_update: the branch main followed,
# else the latest release), then the set-up of the new copy with no start. It asks nothing, so the centre can call
# it over ssh as a person calls it at the machine. The last line says what happened, and the exit code is 0 when
# the copy is at the newest (moved now, or there already), 1 when it is not, and 3 when it moved but the set-up
# left work not done (a sign-in missing, a package not installed): the new kit is there, the machine needs a look.
set -uo pipefail
[ "$(id -u)" != 0 ] || { echo "kit update: not updated: run this as the agent's user, not as root"; exit 1; }
HERE=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd -P); KIT=$(cd "$HERE/.." && pwd -P)
# shellcheck source=install/common.sh
source "$HERE/common.sh"
export PATH="$HOME/.local/bin:$PATH"
command -v git >/dev/null || { echo "kit update: not updated: git is not installed"; exit 1; }
at() { git -C "$KIT" describe --tags --always 2>/dev/null || echo "?"; }
WAS=$(at)
REPO_ROOT=$KIT; AGENT_KIT_YES=1 repo_update
if [ "$REPO_UPDATED" = 0 ]; then
  if [ -n "$REPO_WHY" ]; then echo "kit update: not updated: $REPO_WHY; at $WAS"; exit 1; fi
  echo "kit update: nothing new; at $WAS"; exit 0
fi
python3 -I "$KIT/kit/__main__.py" setup-log "the kit's copy $KIT moved from $WAS to $(at)" 2>/dev/null || true
# the set-up asks nothing and waits for no person (AGENT_KIT_NO_ASK), in a session of its own with no input.
# This file is read to its end before the copy moves: git puts a new file in its place, it does not write into it
S=(); ! command -v setsid >/dev/null || S=(setsid -w)
AGENT_KIT_UPDATED=1 AGENT_KIT_NO_ASK=1 "${S[@]+"${S[@]}"}" bash "$KIT/install/setup.sh" --no-start < /dev/null; RC=$?
if [ "$RC" != 0 ]; then
  echo "kit update: moved from $WAS to $(at), but the set-up left work not done (exit $RC)"; exit 3; fi
echo "kit update: moved from $WAS to $(at)"; exit 0
