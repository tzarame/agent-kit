"""tmuxs.py - every tmux session of the user, marked, and closing one by name. The tmux command comes from
AGENT_KIT_TMUX (default tmux; the tests give an isolated socket). Names are checked and passed as arguments,
never through a shell."""
import os, re, shlex, subprocess

NAME_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}\Z")
SHELLS = ("bash", "sh", "zsh", "dash", "fish", "ksh", "tcsh", "csh", "-bash", "-sh", "-zsh")


def valid(name):
    return bool(NAME_RE.match(name))


def _tmux(*args):
    argv = shlex.split(os.environ.get("AGENT_KIT_TMUX") or "tmux") + list(args)
    env = dict(os.environ)
    env.pop("TMUX", None)   # run from inside a tmux session, the default server is still the one meant
    return subprocess.run(argv, capture_output=True, text=True, timeout=10, env=env)


def sessions(projects):
    """projects: the project of each session of the kit, by its ID. Each tmux session: name, agent (the project of
    a session of the kit, or None), marks: agent | unknown, and empty when every pane runs only a shell. No tmux
    server: no sessions."""
    r = _tmux("list-sessions", "-F", "#{session_name}")
    if r.returncode != 0:
        return []
    panes = {}
    r2 = _tmux("list-panes", "-a", "-F", "#{session_name}\t#{pane_current_command}")
    for line in r2.stdout.splitlines():
        name, _, cmd = line.partition("\t")
        panes.setdefault(name, []).append(cmd)
    out = []
    for name in (n for n in r.stdout.splitlines() if n):
        agent = projects.get(name)
        cmds = panes.get(name, [])
        marks = ["agent" if agent else "unknown"]
        if all(c in SHELLS for c in cmds):
            marks.append("empty")
        out.append({"name": name, "agent": agent, "marks": marks, "panes": len(cmds)})
    return out


def close(name):
    """closes the session of exactly this name; False when there is no such session"""
    if not valid(name):
        return False
    return _tmux("kill-session", "-t", "=" + name).returncode == 0
