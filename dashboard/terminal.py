"""terminal.py - a shell of the machine for the person: tmux sessions named term-XXXX, in the user's home folder, running
the login shell. Up to 4 at once. Typing (send) and closing work only on a session whose name matches term-XXXX and
that exists in tmux; any other name is refused before tmux is called, so nothing is ever typed into an agent's
session. The screen is read with console.screen. The tmux command is tmuxs._tmux (AGENT_KIT_TMUX)."""
import os, re, secrets, string
import console
from tmuxs import _tmux

TID_RE = re.compile(r"term-[a-z0-9]{4}")
MAX_OPEN = 4
MAX_TEXT = 4096
KEYS = ("Enter", "Tab", "Escape", "Up", "Down", "Left", "Right", "BSpace", "C-c", "C-d", "C-l")


class TerminalError(Exception):
    pass


def _exists(tid):
    return _tmux("has-session", "-t", "=" + tid).returncode == 0


def _check(tid):
    """the name must be a terminal's and must exist; raises TerminalError otherwise"""
    if not TID_RE.fullmatch(tid or ""):
        raise TerminalError("not a terminal: %r" % (tid,))
    if not _exists(tid):
        raise TerminalError("no such terminal: %s" % tid)


def listing():
    """the open terminals: a list of tids"""
    r = _tmux("list-sessions", "-F", "#{session_name}")
    if r.returncode != 0:
        return []
    return [n for n in r.stdout.splitlines() if TID_RE.fullmatch(n)]


def open(home):
    """{"tid": "term-XXXX"} of a new detached 120x32 session in home, running the login shell"""
    if len(listing()) >= MAX_OPEN:
        raise TerminalError("at most %d terminals are open; close one first" % MAX_OPEN)
    shell = os.environ.get("SHELL") or "/bin/bash"
    for _ in range(20):
        tid = "term-" + "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(4))
        if _exists(tid):
            continue
        r = _tmux("new-session", "-d", "-s", tid, "-x", "120", "-y", "32", "-c", home, shell)
        if r.returncode != 0:
            raise TerminalError("tmux could not open a terminal: " + r.stderr.strip())
        return {"tid": tid}
    raise TerminalError("could not pick a free name")


def screen(tid):
    """the same answer as console.screen; raises TerminalError when tid is not a terminal's name"""
    if not TID_RE.fullmatch(tid or ""):
        raise TerminalError("not a terminal: %r" % (tid,))
    return console.screen(tid)


def send(tid, text=None, key=None):
    """types text (literal, up to 4096 characters) or one key from KEYS into the terminal"""
    if (text is None) == (key is None):
        raise TerminalError("give either text or key")
    if key is not None and key not in KEYS:
        raise TerminalError("key not allowed: %r" % (key,))
    if text is not None and len(text) > MAX_TEXT:
        raise TerminalError("text longer than %d characters" % MAX_TEXT)
    _check(tid)
    if key is not None:
        r = _tmux("send-keys", "-t", "=" + tid + ":", key)
    else:
        r = _tmux("send-keys", "-l", "-t", "=" + tid + ":", "--", text)
    if r.returncode != 0:
        raise TerminalError("tmux refused the input: " + r.stderr.strip())


def close(tid):
    """kills the terminal's session"""
    _check(tid)
    if _tmux("kill-session", "-t", "=" + tid).returncode != 0:
        raise TerminalError("tmux could not close %s" % tid)
