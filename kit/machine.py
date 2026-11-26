"""machine.py - kit setup-files, which install/setup.sh runs after the packages: the set-up's files of the user. The
command ~/.local/bin/kit, the user's unit that runs kit autostart when the machine starts, with the link that enables
it, the line of ~/.bashrc that puts ~/.local/bin on the PATH, the first config, the marks of
Claude Code's first run in ~/.claude.json, and the user's fields of the config in ~/.claude/settings.json; the user's
copy of the config is brought to the kit's version (config.upgrade). The other
keys of a file are kept. A file is written only when it changes, whole, as a new file moved into place (~/.bashrc:
the line added at its end), and each change goes to kit.log whole. A dry run prints what it would do and changes
nothing."""
import json, os, shlex

from kit import config, plan
from kit.io import why

COMMAND = """#!/usr/bin/env bash
# the command kit of agent-kit, written by its set-up on each run
exec python3 -I %s "$@"
"""
BASHRC_MARK = "# agent-kit: ~/.local/bin"
BASHRC = """
%s holds programs installed without root
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac
""" % BASHRC_MARK
# The unit is the user's own: no root writes or runs a file of the kit. It runs when the user's units start, which is
# the machine's start when the user has linger. The tmux server and its sessions outlive kit autostart (KillMode).
UNIT = """# agent-kit: written by kit setup-files on each set-up; kit autostart: kit/sessions/autostart.py
[Unit]
Description=agent-kit: a session of each project with "autostart": true

[Service]
Type=oneshot
RemainAfterExit=yes
Environment=PATH=%%h/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart="%s" autostart
TimeoutStartSec=5min
KillMode=process

[Install]
WantedBy=default.target
"""
UNIT_TARGET = "../kit-autostart.service"
OLD_UNIT = (".config", "systemd", "user", "default.target.wants", "agent-kit-autostart.service")
USAGE = "usage: kit setup-files [--dry-run]"


def command_text(main):
    return COMMAND % shlex.quote(main)


def unit_text(command):
    return UNIT % command.replace("%", "%%")


def first_run(state, version):
    """the keys of ~/.claude.json that mark Claude Code's first-run screens done; the theme only when there is none.
    Once they are done the file is left: Claude Code moves its own version mark, and the file holds the account"""
    if state.get("hasCompletedOnboarding") is True and isinstance(state.get("lastOnboardingVersion"), str):
        return {}
    want = {"hasCompletedOnboarding": True, "lastOnboardingVersion": version}
    if "theme" not in state:
        want["theme"] = "dark"
    return want


def user_settings(fields):
    """the keys of ~/.claude/settings.json that the user's fields give"""
    return {} if fields["claude_ai_connectors"] else {"disableClaudeAiConnectors": True}


def changed(doc, want):
    """the keys of want that doc does not have with the same value and type"""
    return {k: v for k, v in want.items() if not (k in doc and doc[k] == v and type(doc[k]) is type(v))}


def hint(want):
    return ", ".join('"%s": %s' % (k, json.dumps(v)) for k, v in want.items())


class Run:
    """one kit setup-files: the changes done, or with dry those it would do"""

    def __init__(self, io, dry):
        self.io, self.dry, self.done = io, dry, []

    def change(self, change, do, said):
        """the change done by do, and said; with dry only printed. do returns False when there was nothing to do"""
        if self.dry:
            self.io.err.write("kit setup-files --dry-run: would %s\n" % json.dumps(change, ensure_ascii=False))
        elif do() is not False:
            self.done.append(change)
            self.io.out.write("kit setup-files: %s\n" % said)

    def keys(self, path, want_of, note=None):
        """the keys want_of(the file's object) gives, set in the JSON file at path, the other keys and the mode kept;
        a file that is not a JSON object is left as it is, with a hint to set them by hand. The log has the keys set,
        and the file whole only without a note"""
        text = self.io.read(path)
        try:
            doc = {} if text is None else json.loads(text)
            if not isinstance(doc, dict):
                raise ValueError("%s is not a JSON object" % path)
        except ValueError as e:
            what = str(e) if str(e).startswith(path) else "%s is not plain JSON" % path
            self.io.err.write("kit setup-files: %s; left as it is. Set by hand: %s\n" % (what, hint(want_of({}))))
            return
        want = changed(doc, want_of(doc))
        if not want:
            return
        new = dict(doc, **want)
        change = {"set": want, "in": path, "content": note or plan.shown(new)}
        self.change(change, lambda: self.io.put(path, json.dumps(new, indent=2, ensure_ascii=False) + "\n"),
                    "set in %s: %s" % (path, ", ".join(want)))


def _command(io, run):
    text = command_text(io.main)
    if io.read(io.command) != text:
        run.change({"write": io.command, "content": text}, lambda: io.put(io.command, text, 0o755),
                   "wrote the command %s" % io.command)
    if BASHRC_MARK not in (io.read(io.bashrc) or ""):
        run.change({"append": io.bashrc, "content": BASHRC}, lambda: io.append(io.bashrc, BASHRC),
                   "added to %s: ~/.local/bin on the PATH of new shells" % io.bashrc)


def _unit(io, run):
    """the autostart's unit and its link; systemctl is not called, and the field autostart turns it off"""
    text = unit_text(io.command)
    if io.read(io.unit) != text:
        run.change({"write": io.unit, "content": text}, lambda: io.put(io.unit, text, 0o644),
                   "wrote the autostart's unit %s" % io.unit)
    if not io.exists(io.unit_link):
        run.change({"link": io.unit_link, "to": UNIT_TARGET}, lambda: io.link(io.unit_link, UNIT_TARGET),
                   "enabled the autostart's unit: it runs kit autostart when the machine starts")
    name, linger = io.linger()
    if not linger:
        io.err.write("kit setup-files: the autostart waits for a login of %s: the user's units start with the "
                     "machine only with linger. As root: loginctl enable-linger %s\n" % (name, name))
    if io.exists(os.path.join(io.home, *OLD_UNIT)):
        io.err.write("kit setup-files: the old kit's unit of the autostart is enabled too; turn it off: "
                     "systemctl --user disable agent-kit-autostart\n")


def _config(io, run, kit, has_config):
    """the first config, or the copy brought to the kit's version"""
    if not has_config:
        run.change({"copy": config.DEFAULTS, "to": io.config, "content": plan.shown(kit)},
                   lambda: config.first_config(io.config), "copied the first config to %s" % io.config)
        return
    moves = config.migrate(config.read_json(io.config), kit)[1]
    if moves:
        keep = config.KEPT % (io.config, moves[0]["version"])
        run.change({"migrate": io.config, "keep": keep, "changes": plan.shown(moves)},
                   lambda: config.upgrade(io.config, kit) != [],
                   "brought %s to the kit's version %d; the old one is %s" % (io.config, moves[0]["to"], keep))


def _claude(io, run, fields):
    """the keys of Claude Code's two files, the others kept"""
    version = io.claude_version()
    if version is None:
        io.err.write("kit setup-files: Claude Code does not answer; its first-run screens are left as they are\n")
    else:
        # ~/.claude.json holds the account: the log has only the keys set
        run.keys(io.claude_state, lambda doc: first_run(doc, version), "the other keys kept")
    if user_settings(fields):
        run.keys(io.claude_settings, lambda doc: user_settings(fields))


def setup_log(io, args):
    """kit setup-log WORDS: one change of install/setup.sh, added to kit.log; a secret is never in the words"""
    try:
        io.log({"command": "setup", "change": " ".join(args)})
    except OSError as e:
        io.err.write("kit setup-log: %s\n" % why(e))
        return 1
    return 0


def setup_files(io, args):
    wrong = [a for a in args if a != "--dry-run"]
    if wrong:
        io.err.write("kit setup-files: unknown option %s\n%s\n" % (wrong[0], USAGE))
        return 2
    run = Run(io, "--dry-run" in args)
    record = {"command": "setup-files"}
    try:
        kit = config.defaults()
        has_config = io.read(io.config) is not None
        user = config.read(io.config, kit)[0] if has_config else kit
        fields = config.user_fields(kit, user)
        _command(io, run)
        _unit(io, run)
        _config(io, run, kit, has_config)
        _claude(io, run, fields)
    except config.ConfigError as e:
        record["error"] = "kit setup-files: %s" % e
        io.err.write(record["error"] + "\n")
        return 2
    except OSError as e:
        record["error"] = "kit setup-files: %s" % why(e)
        io.err.write(record["error"] + "\n")
        return 1
    finally:
        record["changes"] = run.done
        if not run.dry and (run.done or "error" in record):
            io.log(record)
    return 0
