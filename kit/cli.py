"""cli.py - the command kit: its words to one command of the sessions or of the set-up, the usage, and the exit codes
(0 done, 1 failed, 2 a wrong command or config)."""
import os
import sys

from kit import machine, plan
from kit.io import Io, why
from kit.sessions import autostart, mcp, run, start, tmux

USAGE = """\
usage: kit COMMAND
  kit start PROJECT [KEYS]  start a session of the project in tmux, and open it; owner/PROJECT clones the repository
                            into ROOT/PROJECT when there is no folder (ROOT: AGENT_KIT_ROOT, else the home folder)
  kit list                  the kit's sessions: ID and project
  kit attach ID             open a session of the kit
  kit kill ID               stop a session of the kit
  kit autostart [--dry-run] start a session of each project with "autostart": true in the config that has none
                            running, and open none; the user's unit of the set-up runs it at the
                            machine's start
  kit mcp list              the MCP servers of Claude Code's files: name, scope and folder; no value of one
  kit mcp remove NAME SCOPE [FOLDER]
                            remove one by claude mcp remove (FOLDER for the scopes local and project)
  kit setup [OPTIONS]       set up the machine again: the kit's update, the packages, GitHub, Claude Code and the
                            kit's files (install/setup.sh --no-start; its options: kit setup --help)
  kit update                move the kit's copy on (the branch main, else the latest release) and set up again;
                            asks nothing; the last line says what happened (exit 0: at the newest; 1: not
                            moved; 3: moved, but the set-up left work not done)
  kit dashboard [--port N]  run the dashboard here, until Ctrl-C: the projects, the sessions, a console, the files;
                            on the machine's Tailscale address, else on 127.0.0.1 (port 8765)
  kit help                  this text
  docs/context-cost.md      what a call costs, how the cache works, and when to set each field of the window
                            and the cache
the keys of kit start, over the config ~/.config/agent-kit/config.json for this start only:
  --%s
  --%s
  --window N|default        the context window, like 132k or 132000
  --compact N|default       the size the session compacts at, in place of the context window
  --agent NAME              the session as the agent NAME, its fields over the project's: dev, dev-eco,
                            design, qa, spec, toolsmith
  --plugin NAME             one more plugin; the key again for each
  --new                     begin a new conversation; without it the session continues the folder's last one
  --dry-run                 print the session's config and what the start would do, and change nothing
""" % (" --".join(plan.MODELS), " --".join(plan.EFFORTS))


def setup(io, args):
    """install/setup.sh --no-start in place of the kit"""
    try:
        io.exec(["bash", os.path.join(io.kit, "install", "setup.sh"), "--no-start"] + list(args), io.environ)
    except OSError as e:
        io.err.write("kit setup: %s\n" % why(e))
    return 1


def update(io, args):
    """install/update.sh in place of the kit: the copy moved on, the set-up with no start, one last line"""
    if args:
        io.err.write("kit update takes no word\n")
        return 2
    try:
        io.exec(["bash", os.path.join(io.kit, "install", "update.sh")], io.environ)
    except OSError as e:
        io.err.write("kit update: %s\n" % why(e))
    return 1


def dashboard(io, args):
    """the dashboard's own program in place of the kit: the core runs it and imports nothing of it"""
    try:
        io.exec([sys.executable, "-I", os.path.join(io.kit, "dashboard", "dash.py"), "--bind", "tailscale"]
                + list(args), io.environ)
    except OSError as e:
        io.err.write("kit dashboard: %s\n" % why(e))
    return 1


# run, setup-files and setup-log are for tmux and install/setup.sh, not in the usage
COMMANDS = {"start": start.start, "list": tmux.list_sessions, "attach": tmux.attach, "kill": tmux.kill, "run": run.run,
            "autostart": autostart.autostart, "mcp": mcp.mcp, "setup": setup, "update": update, "dashboard": dashboard, "setup-files": machine.setup_files,
            "setup-log": machine.setup_log}
PARKED = {"killall": "kit killall is parked; stop each session: kit kill ID",
          "new": "kit new is now kit start: kit start PROJECT [KEYS]"}


def main(argv, io=None):
    io = io or Io()
    cmd, args = (argv[0], argv[1:]) if argv else ("help", [])
    if cmd in ("help", "-h", "--help"):
        io.out.write(USAGE)
        return 0
    if cmd in COMMANDS:
        return COMMANDS[cmd](io, args)
    if cmd in PARKED:
        io.err.write(PARKED[cmd] + "\n")
    else:
        io.err.write("kit: unknown command %s\n%s" % (cmd, USAGE))
    return 2
