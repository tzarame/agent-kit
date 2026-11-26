"""tmux.py - the kit's sessions in tmux: the words that start one, and kit list, attach and kill. A session of the
kit is a tmux session named by the session's ID, with the option @agent-kit set to the project's name; any other
tmux session is not the kit's, and these commands leave it alone."""
import os, time
from kit import plan

MARK = "@agent-kit"
SETTLED = 120   # seconds: a younger config may be of a start still on its way to tmux, and is left


def new_session(sid, name, python, main):
    """the words of one tmux call: a new session running `kit run ID`, then its mark. A lone ; is tmux's separator of
    two commands; a word that ends in ; would lose it, and none of these does (the ID and the name have no ;)"""
    return ["new-session", "-d", "-s", sid, python, "-I", main, "run", sid,
            ";", "set-option", "-t", "=%s:" % sid, MARK, name]


def sessions(io):
    """[(ID, project)] of the kit's sessions; none when tmux has no server"""
    rc, out, _ = io.tmux(["list-sessions", "-F", "#{session_name} #{%s}" % MARK, "-f", "#{%s}" % MARK])
    found = []
    for line in out.splitlines() if rc == 0 else ():
        sid, _, name = line.partition(" ")
        if plan.ID.fullmatch(sid) and name:
            found.append((sid, name))
    return found


def open_session(io, sid, started=False, detached=False):
    """the session on this terminal: tmux's switch-client inside tmux, else attach in place of the kit; with no
    terminal after a start, or detached, the command that opens it"""
    if io.environ.get("TMUX") and not detached:
        rc, _, err = io.tmux(["switch-client", "-t", "=" + sid])
        if rc != 0:
            io.err.write("kit: tmux switch-client: %s; open it: kit attach %s\n" % (err.strip(), sid))
        return 0 if rc == 0 else 1
    if detached or (started and not io.tty()):
        io.out.write("started %s; open it: kit attach %s\n" % (sid, sid))
        return 0
    io.exec(["tmux", "attach-session", "-t", "=" + sid], io.environ)
    return 1


def _ours(io, cmd, args):
    """(the ID, the project) of the one argument, a session of the kit; None with the message written"""
    if len(args) != 1:
        io.err.write("kit: %s needs the ID of a session (kit list)\n" % cmd)
        return None
    name = dict(sessions(io)).get(args[0])
    if name is None:
        io.err.write("kit: no session %s of the kit (kit list)\n" % args[0])
        return None
    return args[0], name


def sweep(io):
    """the config sessions/ID.json, and the MCP servers' file, of a session that is gone (Claude exited by itself,
    the machine restarted) removed, in the log; nothing when tmux gives no clear answer"""
    rc, out, err = io.tmux(["list-sessions", "-F", "#{session_name}"])
    if rc != 0 and "no server running" not in err and "error connecting" not in err:
        return
    live = {line.partition(" ")[0] for line in out.splitlines()} if rc == 0 else set()
    try:
        names = sorted(os.listdir(io.sessions))
    except OSError:
        return
    changes = []
    for f in names:
        sid = f[:-len(".json")]
        if not f.endswith(".json") or not plan.ID.fullmatch(sid) or sid in live:
            continue
        try:
            if time.time() - os.path.getmtime(io.session_file(sid)) < SETTLED:
                continue
        except OSError:
            continue
        for path in (io.session_file(sid), io.mcp_file(sid)):
            if io.remove(path):
                changes.append({"removed": path})
    if changes:
        io.log({"command": "list", "gone": True, "changes": changes})


def list_sessions(io, args):
    if args:
        io.err.write("kit list: takes no argument\n")
        return 2
    sweep(io)
    found = sessions(io)
    if not found:
        io.out.write("no session is running; start one: kit start PROJECT\n")
        return 0
    io.out.write("%-6s %s\n" % ("ID", "PROJECT"))
    for sid, name in found:
        io.out.write("%-6s %s\n" % (sid, name))
    io.out.write("open one: kit attach ID\n")
    return 0


def attach(io, args):
    got = _ours(io, "attach", args)
    return 2 if got is None else open_session(io, got[0])


def kill(io, args):
    """the tmux session stopped, and its config sessions/ID.json and its MCP servers' file removed; all in the log"""
    got = _ours(io, "kill", args)
    if got is None:
        return 2
    sid, name = got
    rc, _, err = io.tmux(["kill-session", "-t", "=" + sid])
    if rc != 0:
        io.err.write("kit kill: tmux: %s\n" % err.strip())
        return 1
    changes = [{"stopped": sid}]
    for path in (io.session_file(sid), io.mcp_file(sid)):
        if io.remove(path):
            changes.append({"removed": path})
    io.log({"command": "kill", "project": name, "id": sid, "changes": changes})
    io.out.write("stopped %s\n" % sid)
    return 0
