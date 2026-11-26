"""projects.py - the kit's projects and sessions, read only: the projects of ~/.config/agent-kit/config.json (what the
next session of a project starts with) and the sessions of ~/.config/agent-kit/sessions/ID.json (what each session
runs with). The core owns both files; the dashboard never writes them."""
import json, os, re

NAME_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,63}")   # a project's name, as the core checks it
ID_RE = re.compile(r"[a-z0-9]{4}")                           # a session's ID
# the session's fields shown: the name on the page, the name in the core's files
FIELDS = (("model", "model"), ("effort", "effort"), ("subm", "subagent_model"), ("sube", "subagent_effort"),
          ("window", "context_window"), ("compact", "compact_window"), ("role", "agent"), ("plugins", "plugins"))
# what a session was started with, shown as it is in its file: plain values only, never its env or its prompt
SETTINGS = ("agent", "model", "effort", "fallback_model", "advisor", "subagent_model", "subagent_effort",
            "context_window", "compact_window", "idle_compact", "idle_compact_from", "cache_life",
            "subagent_cache_life", "prompt_suggestions", "permission_mode", "remote_control", "output_style")


def kit_dir(home):
    return os.path.join(home, ".config", "agent-kit")


def _json(path):
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _fields(*layers):
    """the shown fields, each from the last layer that sets it"""
    out = {}
    for key, name in FIELDS:
        out[key] = [] if key == "plugins" else None
        for layer in layers:
            if isinstance(layer, dict) and layer.get(name) is not None:
                out[key] = layer[name]
    return out


def _agent(agents, name):
    """the layers of the config's agent name, the one it is built over first; an agent of the kit's own (not in the
    config) gives none: the page shows its name only"""
    chain = []
    while isinstance(name, str) and isinstance(agents.get(name), dict) and agents[name] not in chain:
        chain.insert(0, agents[name])
        name = agents[name].get("agent")
    return chain


def list_all(home, root=None):
    """each project of the config, by name: its folder and the fields a new session of it gets (the config's
    session, then the project, then the project's agent). A config that cannot be read: no projects."""
    doc = _json(os.path.join(kit_dir(home), "config.json")) or {}
    found = doc.get("projects")
    agents = doc.get("agents") if isinstance(doc.get("agents"), dict) else {}
    out = []
    for name in sorted(found if isinstance(found, dict) else {}):
        p = found[name]
        if not NAME_RE.fullmatch(name) or not isinstance(p, dict):
            continue
        folder = p.get("folder") if isinstance(p.get("folder"), str) else os.path.join(root or home, name)
        view = {"id": name, "name": name, "dir": folder, "autostart": p.get("autostart") is True}
        view.update(_fields(doc.get("session"), p))
        agent = view["role"]
        view.update(_fields(doc.get("session"), p, *_agent(agents, agent)), role=agent)
        out.append(view)
    return out


def get(home, name, root=None):
    for p in list_all(home, root):
        if p["id"] == name:
            return p
    return None


def sessions(home):
    """each session's file: its ID, project, folder, the keys it was started with, the fields it runs with and the
    time of its start (the file's). A file that cannot be read is left out."""
    folder = os.path.join(kit_dir(home), "sessions")
    out = []
    for f in sorted(os.listdir(folder) if os.path.isdir(folder) else []):
        sid = f[:-5]
        doc = _json(os.path.join(folder, f)) if f.endswith(".json") and ID_RE.fullmatch(sid) else None
        if doc is None or doc.get("id") != sid or not isinstance(doc.get("project"), str):
            continue
        view = {"id": sid, "project": doc["project"], "dir": doc.get("folder"), "keys": doc.get("keys") or [],
                "started": int(os.path.getmtime(os.path.join(folder, f)))}
        view.update(_fields(doc.get("config")))
        config = doc.get("config") if isinstance(doc.get("config"), dict) else {}
        view["settings"] = {k: config[k] for k in SETTINGS
                            if k in config and (config[k] is None or type(config[k]) in (str, int, bool))}
        out.append(view)
    return out
