"""console.py - reads the screen of a tmux session: the active pane's text and its size. Reading only: this module
has no way to send keys or to change a session. The tmux command is tmuxs._tmux (AGENT_KIT_TMUX). A name is checked
and passed as one argument, never through a shell."""
import re
from tmuxs import _tmux

NAME_RE = re.compile(r"[A-Za-z0-9_.-]{1,64}")


def screen(session):
    """{"screen", "cols", "rows"} of the active pane of the session of exactly this name; None when there is none"""
    if not NAME_RE.fullmatch(session or ""):
        return None
    r = _tmux("capture-pane", "-p", "-t", "=" + session + ":")
    if r.returncode != 0:
        return None
    size = _tmux("display-message", "-p", "-t", "=" + session + ":", "#{pane_width} #{pane_height}")
    cols, _, rows = size.stdout.strip().partition(" ")
    if size.returncode != 0 or not (cols.isdigit() and rows.isdigit()):
        return None
    return {"screen": r.stdout, "cols": int(cols), "rows": int(rows)}
