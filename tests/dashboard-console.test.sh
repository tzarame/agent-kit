#!/usr/bin/env bash
# tests/dashboard-console.test.sh - console.py (reading) and terminal.py (a shell of the machine) on an isolated tmux
# socket (env -u TMUX), HOME a temp folder. A session agent-abcd stands for an agent: nothing may be typed into it.
# Exit 0 when every case passes.
REPO=$(cd "$(dirname "$0")/.." && pwd -P)
T=$(mktemp -d) || exit 1; T=$(cd "$T" && pwd -P)
SOCK="consoletest-$$-$RANDOM"
cleanup() { env -u TMUX tmux -L "$SOCK" kill-server 2>/dev/null; rm -rf "$T"; }
trap cleanup EXIT
export HOME="$T/home"; mkdir -p "$HOME" || exit 1
export AGENT_KIT_TMUX="tmux -L $SOCK"
tm() { env -u TMUX tmux -L "$SOCK" "$@"; }

# an agent's session: it prints one line and waits
tm new-session -d -s agent-abcd -x 120 -y 32 "sh -c 'echo hello-from-agent; sleep 600'"
sleep 0.5

cat > "$T/check.py" <<'PY'
import os, sys, time
sys.path.insert(0, os.path.join(os.environ["REPO"], "dashboard"))
import console, terminal
from terminal import TerminalError

def case(name, ok):
    print(("ok   - " if ok else "FAIL - ") + name)

def refused(fn):
    try:
        fn()
    except TerminalError:
        return True
    return False

home = os.environ["HOME"]

# console: the agent's screen and size
s = console.screen("agent-abcd")
case("console.screen shows the agent's text", s is not None and "hello-from-agent" in s["screen"])
case("console.screen gives the size 120x32", s is not None and s["cols"] == 120 and s["rows"] == 32)
case("console.screen: unknown session gives None", console.screen("agent-zzzz") is None)
case("console.screen: a bad name gives None", console.screen("agent;abcd") is None and console.screen("a" * 65) is None)

# terminal: open
t1 = terminal.open(home)["tid"]
import re
case("terminal.open makes term-XXXX", re.fullmatch(r"term-[a-z0-9]{4}", t1) is not None)

# typing: text then Enter, the shell evaluates the arithmetic
terminal.send(t1, text="echo typed-$((40+2))")
terminal.send(t1, key="Enter")
found = False
for _ in range(50):
    if "typed-42" in (terminal.screen(t1) or {}).get("screen", ""):
        found = True
        break
    time.sleep(0.1)
case("send text and Enter: the screen shows typed-42", found)

# the agent's session is never typed into
before = console.screen("agent-abcd")["screen"]
case("send to agent-abcd is refused", refused(lambda: terminal.send("agent-abcd", text="echo intruder")))
case("send key to agent-abcd is refused", refused(lambda: terminal.send("agent-abcd", key="Enter")))
case("close agent-abcd is refused", refused(lambda: terminal.close("agent-abcd")))
time.sleep(0.5)
after = console.screen("agent-abcd")["screen"]
case("the agent's screen is unchanged and has no intruder text", before == after and "intruder" not in after)

for bad in ["main", "term-ab", "term-abcd:0", "term-abcd.0", "term-zzzz", "", "term-ABCD", "term-abcde"]:
    case("send refused for %r" % bad, refused(lambda b=bad: terminal.send(b, text="x")))
    case("close refused for %r" % bad, refused(lambda b=bad: terminal.close(b)))

case("send to term-zzzz (no such terminal) is refused", refused(lambda: terminal.send("term-zzzz", key="Enter")))
case("a key outside the list is refused", refused(lambda: terminal.send(t1, key="C-x")))
case("text and key together are refused", refused(lambda: terminal.send(t1, text="a", key="Enter")))
case("text over 4096 characters is refused", refused(lambda: terminal.send(t1, text="a" * 4097)))

# the limit of four
tids = [t1]
for _ in range(3):
    tids.append(terminal.open(home)["tid"])
case("four terminals are open", len(terminal.listing()) == 4)
case("a fifth terminal is refused", refused(lambda: terminal.open(home)))

# close removes the session
terminal.close(t1)
case("close removes the session", t1 not in terminal.listing() and console.screen(t1) is None)
for t in tids[1:]:
    terminal.close(t)
case("the others close too; none left", terminal.listing() == [])

# the source of console.py has no way to type
src = open(os.path.join(os.environ["REPO"], "dashboard", "console.py")).read()
case("console.py has no send-keys", "send-keys" not in src)
PY

REPO="$REPO" python3 -I "$T/check.py" > "$T/out" 2>"$T/err"
RC=$?
PASS=0; FAIL=0
while IFS= read -r line; do
  case "$line" in
    "ok   - "*) PASS=$((PASS+1)) ;;
    "FAIL - "*) FAIL=$((FAIL+1)) ;;
  esac
  echo "$line"
done < "$T/out"
[ "$RC" = 0 ] || { FAIL=$((FAIL+1)); echo "FAIL - check.py exited $RC: $(head -c 300 "$T/err")"; }
echo "passed $PASS, failed $FAIL"
[ "$FAIL" = 0 ]
