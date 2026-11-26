"""config.py - the kit's configuration: the fields and their checks, kit/defaults.json, the user's file
~/.config/agent-kit/config.json (one-config) and the migrations of the user's copy. The fields are those of
docs/config.md. The old project files are kit/old.py's. A mistake raises ConfigError, which the
command turns into exit code 2. Standard library only."""
import json, os, re

from kit import files

DEFAULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "defaults.json")

WINDOWS = ("context_window", "compact_window")
WORD = re.compile(r"[A-Za-z0-9._:/-]+")             # a model, an effort, a plugin: no space, no quote
WORDS = re.compile(r"[A-Za-z0-9._:/-]+(,[A-Za-z0-9._:/-]+)*")   # --fallback-model takes a list
STYLE = re.compile(r"[A-Za-z0-9 ._:-]+")
ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+")   # a GitHub account, not starting with -, and a name
NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]*")  # a project's name: no / and no leading . or -
MODES = ("acceptEdits", "auto", "bypassPermissions", "manual", "dontAsk", "plan")
WINDOW_MAX = 99999999                               # a window is a whole number of at most 8 digits
IDLE_MIN = 100000                                   # Claude Code raises a lower idle threshold to this
SUBAGENT = ("agent", "model", "effort")             # the keys of an entry of subagents
ENGINES = ("claude", "codex", "opencode")                               # the coding agents kit/engines has a module for
LIVES = ("5m", "1h")                                # the lives of the prompt cache that Claude Code takes


class ConfigError(Exception):
    """a config that cannot be used; the message names the file and the place"""


def _word(v):
    return isinstance(v, str) and WORD.fullmatch(v) is not None


def _opt(test):
    return lambda v: v is None or test(v)


def _window(v):
    return type(v) is int and 1 <= v <= WINDOW_MAX


def _windows(v):
    """a window, or an object of windows by the model: a key is a part of the model's name, "*" any other model"""
    if _window(v):
        return True
    return isinstance(v, dict) and v != {} and all((k == "*" or _word(k)) and _opt(_window)(x) for k, x in v.items())


def _bool(v):
    return type(v) is bool


def _words(v):
    return isinstance(v, list) and all(_word(x) for x in v)


def _subagents(v):
    """the agents given to the session as subagents: each a name, or {"agent": NAME} with its own model and effort;
    a name once"""
    def one(x):
        return _word(x) or (isinstance(x, dict) and _word(x.get("agent")) and set(x) <= set(SUBAGENT)
                            and all(_opt(_word)(x.get(k)) for k in ("model", "effort")))
    if not isinstance(v, list) or not all(one(x) for x in v):
        return False
    names = [x if isinstance(x, str) else x["agent"] for x in v]
    return len(set(names)) == len(names)


def _file(v):
    """a Markdown file of a prompt: a path from / or ~/"""
    return isinstance(v, str) and (v.startswith("/") or v.startswith("~/")) and "\0" not in v and "\n" not in v


def _mcp(v):
    """MCP servers by their names, each an object as in Claude Code's .mcp.json"""
    return isinstance(v, dict) and all(isinstance(k, str) and NAME.fullmatch(k) and isinstance(x, dict) and x
                                       for k, x in v.items())


def _inside(v):
    """a folder inside the project: names of letters, digits and . _ - joined by /, none starting with . or -"""
    return isinstance(v, str) and all(NAME.fullmatch(p) for p in v.split("/"))


def _name_part(v):
    return isinstance(v, str) and NAME.fullmatch(v) is not None


def _env(v):
    return isinstance(v, dict) and all(ENV_NAME.fullmatch(k) and isinstance(x, str) and "\0" not in x
                                       for k, x in v.items())


_plugins = _words


def _folder(v):
    return (isinstance(v, str) and (v.startswith("/") or v == "~" or v.startswith("~/")) and "\0" not in v
            and "\n" not in v)


# each field of the session: its check and what the message says it must be
SESSION = {
    "advisor": (_word, "off, default or a model's name"),
    "context_window": (_opt(_windows), "a whole number of tokens, 1 to %d, an object of such numbers by the model "
                                       '(as {"haiku": 113000, "*": 200000}), or null' % WINDOW_MAX),
    "compact_window": (_opt(_window), "a whole number of tokens, 1 to %d, or null" % WINDOW_MAX),
    "idle_compact": (_bool, "true or false"),
    "idle_compact_from": (_opt(lambda v: type(v) is int and IDLE_MIN <= v <= WINDOW_MAX),
                          "a whole number of tokens, %d to %d, or null" % (IDLE_MIN, WINDOW_MAX)),
    "cache_life": (_opt(lambda v: v in LIVES), "5m, 1h or null"),
    "subagent_cache_life": (_opt(lambda v: v in LIVES), "5m, 1h or null"),
    "model": (_opt(_word), "a model's name: letters, digits and . _ : / -, or null"),
    "effort": (_opt(_word), "an effort: letters, digits and . _ : / -, or null"),
    "fallback_model": (_opt(lambda v: isinstance(v, str) and WORDS.fullmatch(v) is not None),
                       "a model's name, or several separated by commas, or null"),
    "subagent_model": (_opt(_word), "a model's name: letters, digits and . _ : / -, or null"),
    "subagent_effort": (_opt(_word), "an effort: letters, digits and . _ : / -, or null"),
    "permission_mode": (lambda v: v in MODES, "one of " + ", ".join(MODES)),
    "prompt_suggestions": (_bool, "true or false"),
    "remote_control": (_bool, "true or false"),
    "claude_ai_skills": (_bool, "true or false"),
    "claude_ai_plugins": (_bool, "true or false"),
    "claude_ai_connectors": (_bool, "true or false"),
    "env": (_env, "an object of variables: names of letters, digits and _, values strings"),
    "engine": (lambda v: v in ENGINES, "one of " + ", ".join(ENGINES)),
    "agent": (_opt(_word), "an agent's name, or null"),
    "subagents": (_subagents, "a list of agents, each a name or {\"agent\": NAME, \"model\": ..., \"effort\": ...}, "
                              "a name once"),
    "role": (_opt(_file), "a Markdown file, a path from / or ~/, or null"),
    "plugins": (_plugins, "a list of plugins' names"),
    "design_dir": (_inside, "a folder inside the project, like design or docs/design: no / first, no .."),
    "system_prompt": (_opt(_file), "a Markdown file, a path from / or ~/, or null"),
    "system_prompt_append": (_opt(_file), "a Markdown file, a path from / or ~/, or null"),
    "tools": (_opt(_words), "a list of Claude Code's built-in tools, or null"),
    "subagent_tools": (_words, "a list of Claude Code's built-in tools"),
    "mcp_servers": (_mcp, "an object of MCP servers by their names, each an object as in .mcp.json"),
    "mcp_strict": (_bool, "true or false"),
    "project_config": (_bool, "true or false"),
    "bundled_skills": (_bool, "true or false"),
    "bundled_skills_off": (_words, "a list of bundled skills' names"),
    "builtin_plugins_off": (_words, "a list of Claude Code's built-in plugins' names"),
    "subagents_off": (_words, "a list of subagents' names"),
    "name_prefix": (_opt(_name_part), "a word of letters, digits and . _ -, or null"),
    "name_postfix": (_opt(_name_part), "a word of letters, digits and . _ -, or null"),
    "output_style": (_opt(lambda v: isinstance(v, str) and STYLE.fullmatch(v) is not None),
                     "a style's name: letters, digits, spaces and . _ : -, or null"),
    "keep_coding_instructions": (_bool, "true or false"),
}
PROJECT = {
    "repo": (_opt(lambda v: isinstance(v, str) and (v == "" or REPO.fullmatch(v) is not None)), "owner/name"),
    "folder": (_folder, "the project's folder: a path from / or ~/"),
    "autostart": (_bool, "true or false"),
}
USER = {
    "claude_ai_connectors": (_bool, "true or false"),
}
TOP = ("version", "user", "session", "agents", "projects", "content")
# the content (the agents and the plugins a session is made of) is the kit's folder content/; dir names a folder
# read over it, a working copy of that folder for one
CONTENT = {
    "dir": (lambda v: v is None or (isinstance(v, str) and v.startswith(("/", "~/"))), "a path from / or ~/, or null"),
}
FILES = ("role", "system_prompt", "system_prompt_append")   # the fields that name a Markdown file

# the migrations of the user's copy, in order: (the version a step brings the copy to, its changes). A change is
# ("default", "GROUP.FIELD", OLD, NEW): the field of the copy's group (user or session) that still holds the old default
# takes the new one, a value the user changed is kept; ("rename", "GROUP.FIELD", "NEW"): the field renamed, and for a
# session's field in each project too; ("drop", "GROUP.FIELD"): the field taken out, the same way. A field a release
# adds needs none: the defaults give it. ("agents",): the profiles become agents (_agents). kit/defaults.json has the
# last version; the first is 1, with no change
MIGRATIONS = (
    # 2: the release's defaults are Claude Code's own (agents)
    (2, (("default", "session.model", "haiku", None), ("default", "session.effort", "xhigh", None),
         ("default", "session.subagent_model", "haiku", None), ("default", "session.subagent_effort", "low", None),
         ("default", "session.agent", "dev", None), ("default", "session.system_prompt", "kit", None),
         ("default", "session.context_window", 200000, None))),
    # 3: one notion, the agent: the group profiles and a project's profile go (agents)
    (3, (("agents",),)),
)
KEPT = "%s.v%d"                                     # the copy as it was before a migration: PATH.vN, N its version


def _no_twins(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError("the key %r is given twice" % k)
        d[k] = v
    return d


def read_json(path):
    """the JSON object of the file; ConfigError names the file, and the line and the column of a mistake"""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        raise ConfigError("%s: %s" % (path, e.strerror))
    except UnicodeDecodeError:
        raise ConfigError("%s: not UTF-8 text" % path)
    try:
        doc = json.loads(text, object_pairs_hook=_no_twins)
    except json.JSONDecodeError as e:
        raise ConfigError("%s: line %d, column %d: %s" % (path, e.lineno, e.colno, e.msg))
    except ValueError as e:
        raise ConfigError("%s: %s" % (path, e))
    if not isinstance(doc, dict):
        raise ConfigError("%s: the file is not a JSON object" % path)
    return doc


def _fields(group, table, where):
    if not isinstance(group, dict):
        raise ConfigError("%s: not an object" % where)
    for k, v in group.items():
        if k not in table:
            raise ConfigError("%s.%s: a field the kit does not know" % (where, k))
        test, what = table[k]
        if not test(v):
            raise ConfigError("%s.%s: %s is not allowed; it must be %s" % (where, k, json.dumps(v), what))
    if all(group.get(w) is not None for w in WINDOWS):
        raise ConfigError("%s: context_window and compact_window are both set; a session has one of them" % where)


def entry_fields(entry, where):
    """ConfigError when a project's entry has a field the kit does not know or a value not allowed"""
    _fields(entry, dict(SESSION, **PROJECT), where)


def check(doc, where):
    """ConfigError when the document has a field the kit does not know or a value not allowed; where is the file"""
    for k in doc:
        if k not in TOP:
            raise ConfigError("%s: %s: a field the kit does not know" % (where, k))
    if "version" in doc and not _version(doc["version"]):
        raise ConfigError("%s: version: %s is not allowed; it must be a whole number from 1"
                          % (where, json.dumps(doc["version"])))
    _fields(doc.get("user", {}), USER, where + ": user")
    _fields(doc.get("session", {}), SESSION, where + ": session")
    _fields(doc.get("content", {}), CONTENT, where + ": content")
    agents = doc.get("agents", {})
    if not isinstance(agents, dict):
        raise ConfigError("%s: agents: not an object" % where)
    for name, fields in agents.items():
        place = "%s: agents.%s" % (where, name)
        if not NAME.fullmatch(name):
            raise ConfigError("%s: an agent's name has letters, digits and . _ -, and starts with neither . nor -"
                              % place)
        _fields(fields, SESSION, place)
    projects = doc.get("projects", {})
    if not isinstance(projects, dict):
        raise ConfigError("%s: projects: not an object" % where)
    for name, entry in projects.items():
        place = "%s: projects.%s" % (where, name)
        if not NAME.fullmatch(name):
            raise ConfigError("%s: a project's name has letters, digits and . _ -, and starts with neither . nor -"
                              % place)
        entry_fields(entry, place)
        if "folder" not in entry:
            raise ConfigError("%s: the entry has no folder" % place)
    return doc


def _version(v):
    return type(v) is int and v >= 1


def _same(a, b):
    """the same JSON value: true is not 1"""
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def _groups(doc, group):
    """(the place, the object) of each object of the document that holds the group's fields: the group, and for the
    session's fields each project too"""
    found = [(group, doc.get(group))]
    if group == "session" and isinstance(doc.get("projects"), dict):
        found += [("projects." + name, entry) for name, entry in doc["projects"].items()]
    return [(where, g) for where, g in found if isinstance(g, dict)]


def _agents(doc):
    """the profiles made agents: the group renamed, a profile's own agent kept as the agent it is built over; a
    project's profile becomes its agent, and where the project names an agent of its own and the profile none, the
    profile's fields go into the project's entry, over its own as the profile lay"""
    done, profiles = [], doc.pop("profiles", None)
    profiles = profiles if isinstance(profiles, dict) else {}
    if profiles:
        agents = doc.setdefault("agents", {})
        for name, fields in profiles.items():
            if isinstance(agents, dict) and name not in agents:     # an agent of that name already there wins
                agents[name] = fields
                done.append({"rename": "profiles." + name, "to": "agents." + name})
            else:
                done.append({"drop": "profiles." + name, "value": fields})
    for where, entry in _groups(doc, "session"):
        if where == "session" or "profile" not in entry:
            continue
        name = entry.pop("profile")
        fields = profiles.get(name)
        if name is None:
            continue
        if entry.get("agent") is not None and isinstance(fields, dict) and fields.get("agent") is None:
            if any(w in fields for w in WINDOWS):
                for w in WINDOWS:
                    entry.pop(w, None)
            entry.update(fields)
            done.append({"put": "profiles." + name, "into": where})
        else:
            entry["agent"] = name
            done.append({"rename": where + ".profile", "to": "agent", "value": name})
    return done


def _change(doc, step):
    """the change of one step made in the document; what was done, each with the old value"""
    if step[0] == "agents":
        return _agents(doc)
    kind, (group, _, field) = step[0], step[1].partition(".")
    if kind not in ("default", "rename", "drop"):
        raise ValueError("a migration's change %r is not default, rename or drop" % kind)
    done = []
    if kind == "default":
        g = doc.get(group)
        if isinstance(g, dict) and field in g and _same(g[field], step[2]):
            g[field] = step[3]
            done.append({"set": step[1], "from": step[2], "to": step[3]})
        return done
    for where, g in _groups(doc, group):
        if field not in g:
            continue
        value = g.pop(field)
        if kind == "rename" and step[2] not in g:     # a field of the new name already there wins
            g[step[2]] = value
            done.append({"rename": "%s.%s" % (where, field), "to": step[2]})
        else:
            done.append({"drop": "%s.%s" % (where, field), "value": value})
    return done


def migrate(doc, kit, steps=None):
    """(the document brought to the kit's version by the steps after its own version, what was done); the version
    first. A document without a version has the first one. The document is not changed, and it is given back as it is
    when it has the kit's version or a later one, or a version that check refuses"""
    have, want = doc.get("version", 1), kit.get("version", 1)
    if not _version(have) or have >= want:
        return doc, []
    out = json.loads(json.dumps(doc))
    done = [{"version": have, "to": want}]
    for to, changes in MIGRATIONS if steps is None else steps:
        if have < to <= want:
            for step in changes:
                done += _change(out, step)
    out.pop("version", None)
    return dict({"version": want}, **out), done


def over(base, layer):
    """the session's fields of layer over those of base. A layer with either window gives both windows, so a window
    of the layer drops the other one of base; env is merged by the variable's name"""
    out = dict(base)
    for k, v in layer.items():
        if k in SESSION:
            out[k] = dict(out.get("env") or {}, **v) if k == "env" else v
    if any(w in layer for w in WINDOWS):
        for w in WINDOWS:
            out[w] = layer.get(w)
    return out


def over_agent(base, layer):
    """the fields of layer over those of base, as over, but the plugins of both"""
    out = over(base, layer)
    if "plugins" in layer:
        out["plugins"] = list(dict.fromkeys(list(base.get("plugins") or []) + list(layer["plugins"])))
    return out


def agent_fields(doc, where):
    """ConfigError when an agent's description has a field the kit does not know or a value not allowed"""
    _fields(doc, SESSION, where)
    return doc


def agent(user, name, source=None, known=()):
    """the session's fields of the agent name: the description of a source (source(NAME): its fields, or None when
    no source has it; known: the names the sources have) with the config's agent of that name over it, laid over
    the agent it is built over (its field agent). ConfigError for an agent there is not, and for one built over
    itself"""
    mine = user.get("agents", {})

    def one(n, chain):
        theirs = source(n) if source is not None else None
        if n not in mine and theirs is None:
            raise ConfigError("agent: %s: no such agent; there are %s"
                              % (n, ", ".join(sorted(set(known) | set(mine))) or "none"))
        desc = over_agent(theirs or {}, mine.get(n, {}))
        base = desc.get("agent")
        if base is None:
            return desc
        if base in chain + [n]:
            raise ConfigError("agent: %s: built over itself: %s" % (name, " over ".join(chain + [n, base])))
        return over_agent(one(base, chain + [n]), desc)
    return dict(one(name, []), agent=name)


def defaults(path=DEFAULTS):
    """the kit's default configuration, checked"""
    return check(read_json(path), path)


def read(path, kit=None):
    """the user's config over the kit's defaults: (the document as the user wrote it, brought to the kit's version
    here but not in the file, the defaults); upgrade writes the migration"""
    kit = kit if kit is not None else defaults()
    return check(migrate(read_json(path), kit)[0], path), kit


def session(kit, user, name):
    """the session's fields of the project name: the defaults, the user's session, the project's entry over them"""
    fields = over(over(kit.get("session", {}), user.get("session", {})), user.get("projects", {}).get(name, {}))
    missing = set(SESSION) - set(fields)
    if missing:
        raise ConfigError("the kit's defaults have no %s" % ", ".join(sorted(missing)))
    return fields


def user_fields(kit, user):
    """the user's fields: the defaults, the user's group over them"""
    fields = dict(kit.get("user", {}), **user.get("user", {}))
    missing = set(USER) - set(fields)
    if missing:
        raise ConfigError("the kit's defaults have no user's %s" % ", ".join(sorted(missing)))
    return fields


def project(user, name):
    """the project's entry, or None when the config has no such project"""
    return user.get("projects", {}).get(name)


def first_config(path, kit_path=DEFAULTS):
    """a copy of the kit's defaults at path when there is no file there; True when it was made. A file made there in
    between is kept"""
    if os.path.lexists(path):
        return False
    with open(kit_path, "rb") as f:
        data = f.read()
    tmp = files.new_file(path, data)
    try:
        os.link(tmp, path)
    except FileExistsError:
        return False
    finally:
        os.unlink(tmp)
    return True


def write(path, doc):
    """the document as the file at path, mode 600"""
    files.put(path, (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def upgrade(path, kit, steps=None):
    """the file at path brought to the kit's version, read again just before: the file as it was kept as PATH.vN
    (N its version; one already there is kept), then the new one written whole. What was done, [] when the file has
    the kit's version"""
    doc = read_json(path)
    new, done = migrate(doc, kit, steps)
    if done:
        check(new, path)
        try:
            os.link(path, KEPT % (path, done[0]["version"]))
        except FileExistsError:
            pass
        write(path, new)
    return done


def add_project(path, name, entry):
    """the entry of a new project added to the user's file; the file is read again just before, and checked"""
    doc = check(read_json(path), path)
    projects = doc.setdefault("projects", {})
    if name in projects:
        return projects[name]
    projects[name] = entry
    write(path, check(doc, path))
    return entry
