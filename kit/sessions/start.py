"""start.py - kit start PROJECT [KEYS]: first each check (the keys, the config, the project and its folder, the
plugins, the plan), then each write (the first config or the migration of the user's copy, the clone, the project's
entry, sessions/ID.json), one tmux
session of the kit that runs `kit run ID`, and the attach. Each change goes to kit.log whole, a secret only as its
fingerprint. A dry run prints the session's config and what the start would do, and changes nothing."""
import json, os

from kit import config, engines, files, old, plan, quoted
from kit.io import why
from kit.sessions import run, tmux

IDS_TRIED = 100                                     # random IDs tried before the start gives up


def _user(io):
    """(the user's config brought to the kit's version, the kit's defaults, whether the defaults are to be copied, the
    migration the file needs); with no file yet the defaults are the user's config"""
    kit = config.defaults()
    if not io.exists(io.config):
        return kit, kit, True, []
    return config.read(io.config, kit)[0], kit, False, config.migrate(config.read_json(io.config), kit)[1]


def _project(io, user, name, repo):
    """(the project's entry, whether it is new, the repository to clone or None, the folder made absolute). An entry
    of the config is used as it is; with none, the folder ROOT/NAME and its old file, read once"""
    entry, new = config.project(user, name), False
    if entry is not None:
        have = entry.get("repo") or None
        if repo and have and repo != have:
            raise plan.PlanError("kit start: %s: the project %s has the repository %s in the config"
                                 % (repo, name, have))
        repo = have or repo
    else:
        folder, new = os.path.join(io.root, name), True
        entry = old.read_old(io.conf, name, folder) or {"folder": folder}
        if repo:
            entry["repo"] = repo
        config.check({"projects": {name: entry}}, "kit start")
    folder = io.expand(entry["folder"])
    if os.path.isdir(folder):
        return entry, new, None, folder
    if io.exists(folder):
        raise plan.PlanError("kit start: the folder of %s is not a folder: %s" % (name, folder))
    if repo:
        return entry, new, repo, folder
    if new:
        raise plan.PlanError("kit start: no project %s in the config and no folder %s; give owner/%s to clone it"
                             % (name, folder, name))
    raise plan.PlanError("kit start: the folder of %s is not there: %s" % (name, folder))


def _texts(io, fields):
    """{field: the text of its Markdown file} of role, system_prompt and system_prompt_append; a file that cannot be
    read stops the start. "plugins": {a plugin: {file: text}} of the system-prompt.md and agent.md a plugin has"""
    out = {"plugins": {}}
    for name, folder in sorted(io.plugins().items()):
        own = {}
        for part in plan.PLUGIN_TEXTS:
            try:
                text = io.read(os.path.join(folder, part))
            except (OSError, UnicodeDecodeError):
                text = None
            if text:
                own[part] = text
        if own:
            out["plugins"][name] = own
    for field in config.FILES:
        path = fields[field]
        if path is not None:
            out[field] = _text(io, field, path)
    return out


def _text(io, field, path):
    """the text of a field's Markdown file; a file that cannot be read stops the start"""
    try:
        text = io.read(io.expand(path))
    except OSError as e:
        text, problem = None, why(e)
    except UnicodeDecodeError:
        text, problem = None, "not UTF-8 text"
    else:
        problem = "no such file"
    if text is None:
        raise plan.PlanError("kit start: %s: %s: %s" % (field, path, problem))
    return text


def _machine(io):
    """the machine's variables for GitHub as the App, from `install/gh-app.sh env`; {} when the machine has no App's
    key, or with a warning when the script fails"""
    try:
        env = {}
        for line in io.machine_text().splitlines():
            if line.strip():
                if not line.startswith("export "):
                    raise ValueError("%r is not a line of export" % line)
                env.update(quoted.parse_q(line[len("export "):]))
        return env
    except (OSError, ValueError) as e:
        io.err.write("kit start: GitHub as the App: %s; the session goes on without it\n" % why(e))
        return {}


def _new_id(io, dry):
    """a random ID with no config and, but in a dry run, no tmux session of that name"""
    for _ in range(IDS_TRIED):
        sid = io.new_id()
        if not io.exists(io.session_file(sid)) and (dry or not io.has_session(sid)):
            return sid
    raise OSError("no free ID of a session in %d tries" % IDS_TRIED)


def start(io, args, detached=False):
    """kit start; detached: the session is started and not opened, for kit autostart"""
    try:
        name, repo, layer, given, dry, fresh = plan.parse_start(args)
        user, kit, first, moves = _user(io)
        entry, new, clone, folder = _project(io, user, name, repo)
        fields = config.session(kit, user, name)
        if new:
            fields = config.over(fields, entry)
        aname = layer.get("agent") or fields["agent"]
        if aname:
            fields = config.over_agent(fields, config.agent(user, aname, io.agent, io.agent_files()))
        texts = _texts(io, config.over(fields, layer))
        texts["subagents"] = plan.subagents(
            config.over(fields, layer), lambda n: config.agent(user, n, io.agent, io.agent_files()),
            lambda path: _text(io, "subagents: role", path))
        planned = dict(entry, folder=folder)
        if clone:
            planned["repo"] = clone
        machine = _machine(io)
        found = io.plugins()
        sid = _new_id(io, dry)
        doc = engines.make(name, planned, fields, sid, found, layer, given, machine,
                           io.talked(folder) and not fresh, texts,
                           io.mcp_file(sid), io.engines, kit["session"])
    except (config.ConfigError, plan.PlanError) as e:
        io.err.write("%s\n" % e)
        return 2
    except OSError as e:
        io.err.write("kit start: %s\n" % why(e))
        return 1
    words = tmux.new_session(doc["id"], name, io.python, io.main)
    if dry:
        todo = ([{"copy": config.DEFAULTS, "to": io.config}] if first else []) + \
               ([_migrated(io, moves)] if moves else []) + \
               ([{"clone": clone, "into": folder}] if clone else []) + \
               ([{"add": name, "to": io.config, "entry": plan.shown(entry)}] if new else []) + \
               ([{"write": doc["mcp"]["file"]}] if doc["mcp"] else []) + \
               [{"write": x["file"]} for x in doc.get("files", ())] + \
               [{"write": io.session_file(doc["id"])}, {"tmux": words, "in": folder}]
        io.out.write(json.dumps(plan.shown(doc), indent=2, ensure_ascii=False) + "\n")
        for t in todo:
            io.err.write("kit start --dry-run: would %s\n" % json.dumps(t, ensure_ascii=False))
        return 0
    return _do(io, doc, words, machine, first, clone, entry if new else None, kit, detached)


def _migrated(io, moves):
    """the change of the config's migration, as the log and --dry-run show it"""
    return {"migrate": io.config, "keep": config.KEPT % (io.config, moves[0]["version"]),
            "changes": plan.shown(moves)}


def _do(io, doc, words, machine, first, clone, new_entry, kit, detached):
    """the writes and the tmux session, in this order; the log gets each change done, whole, and the error that
    stopped the start"""
    sid, name, folder, done = doc["id"], doc["project"], doc["folder"], []
    record = {"command": "start", "project": name, "id": sid, "session": plan.shown(doc)}
    try:
        if first and config.first_config(io.config):
            done.append({"copy": config.DEFAULTS, "to": io.config, "content": plan.shown(config.defaults())})
        moves = [] if first else config.upgrade(io.config, kit)
        if moves:
            done.append(_migrated(io, moves))
        if clone:
            # gh as the App when the machine has its key: only the machine's variables, not the session's
            rc = io.clone(clone, folder, run.child_env(io.environ, {"env": machine}))
            if rc != 0:
                raise OSError("gh repo clone %s %s: exit code %d" % (clone, folder, rc))
            done.append({"clone": clone, "into": folder})
        if new_entry is not None:
            saved = config.add_project(io.config, name, new_entry)
            done.append({"add": name, "to": io.config, "entry": plan.shown(saved)})
        if doc["mcp"]:
            config.write(doc["mcp"]["file"], doc["mcp"]["content"])
            done.append({"write": doc["mcp"]["file"], "content": plan.shown(doc["mcp"]["content"])})
        for x in doc.get("files", ()):
            files.put(x["file"], x["text"].encode("utf-8"))
            done.append({"write": x["file"], "content": x["text"]})
        config.write(io.session_file(sid), plan.kept(doc))
        done.append({"write": io.session_file(sid), "content": "session"})
        rc, _, err = io.tmux(words, cwd=folder)
        if rc != 0:
            raise OSError("tmux: %s" % (err.strip() or "exit code %d" % rc))
        done.append({"tmux": words, "in": folder})
    except (config.ConfigError, OSError) as e:
        record["error"] = "kit start: %s" % why(e)
        io.err.write(record["error"] + "\n")
        return 1
    finally:
        record["changes"] = done
        io.log(record)
    return tmux.open_session(io, sid, started=True, detached=detached)
