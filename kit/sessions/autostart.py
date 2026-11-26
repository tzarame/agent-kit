"""autostart.py - kit autostart [--dry-run]: a session of each project whose entry in the config has "autostart":
true and that has no session of the kit running, started as kit start starts it and not opened. The user's unit that
kit setup-files writes (kit/machine.py) runs it when the machine starts. Each start writes its own record to kit.log; the autostart's record
names the projects started, the ones already running and the ones that failed. A dry run shows each start's dry run
and changes nothing."""
from kit import config
from kit.sessions import start, tmux


def autostart(io, args):
    dry = args == ["--dry-run"]
    if args and not dry:
        io.err.write("kit autostart: unknown option %s\n" % args[0])
        return 2
    if not io.exists(io.config):
        io.out.write("kit autostart: no config %s; nothing to start\n" % io.config)
        return 0
    try:
        user = config.read(io.config)[0]
    except config.ConfigError as e:
        io.err.write("kit autostart: %s\n" % e)
        if not dry:
            io.log({"command": "autostart", "error": "kit autostart: %s" % e})
        return 2
    names = sorted(n for n, entry in user.get("projects", {}).items() if entry.get("autostart") is True)
    running = {}
    for sid, name in tmux.sessions(io):
        running.setdefault(name, sid)
    record = {"command": "autostart", "started": [], "running": {}, "failed": []}
    for name in names:
        if name in running:
            io.out.write("kit autostart: %s: already running, kit attach %s\n" % (name, running[name]))
            record["running"][name] = running[name]
            continue
        io.out.write("kit autostart: %s\n" % name)
        rc = start.start(io, [name] + (["--dry-run"] if dry else []), detached=True)
        record["started" if rc == 0 else "failed"].append(name)
        if rc != 0:
            io.err.write("kit autostart: %s: not started (exit code %d)\n" % (name, rc))
    if not names:
        io.out.write("kit autostart: no project has \"autostart\": true in %s\n" % io.config)
    if not dry:
        io.log(record)
    return 1 if record["failed"] else 0
