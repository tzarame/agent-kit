"""mcp.py - kit mcp list and kit mcp remove: the MCP servers Claude Code holds outside a session. The list reads only
the names under mcpServers of ~/.claude.json (the user's, and each folder's local ones) and of the projects'
.mcp.json, prints no value of a server and connects to none. A removal is Claude Code's own command; the kit writes
no file of Claude Code's."""
import os

from kit import config

SCOPES = ("user", "local", "project")
USAGE = "usage: kit mcp list | kit mcp remove NAME user | kit mcp remove NAME local|project FOLDER\n"


def _names(doc):
    """the names under mcpServers of a JSON object; none when it has no such object"""
    found = doc.get("mcpServers") if isinstance(doc, dict) else None
    return sorted(n for n in found if isinstance(n, str)) if isinstance(found, dict) else []


def _doc(path):
    """the JSON object of the file; None when it is missing or cannot be read"""
    try:
        return config.read_json(path)
    except config.ConfigError:
        return None


def servers(io):
    """[(name, scope, folder or None)]: the user's servers and the local ones of ~/.claude.json, then those of the
    .mcp.json of each folder Claude Code knows and of each project of the kit's config"""
    state = _doc(io.claude_state) or {}
    found = [(n, "user", None) for n in _names(state)]
    known = state.get("projects") if isinstance(state.get("projects"), dict) else {}
    for folder in sorted(known):
        found += [(n, "local", folder) for n in _names(known[folder])]
    projects = (_doc(io.config) or {}).get("projects")
    folders = set(known)
    for entry in projects.values() if isinstance(projects, dict) else ():
        if isinstance(entry, dict) and isinstance(entry.get("folder"), str):
            folders.add(os.path.abspath(io.expand(entry["folder"])))
    for folder in sorted(folders):
        found += [(n, "project", folder) for n in _names(_doc(os.path.join(folder, ".mcp.json")))]
    return found


def mcp(io, args):
    if args == ["list"]:
        found = servers(io)
        if not found:
            io.out.write("no MCP server in Claude Code's files\n")
            return 0
        io.out.write("%-24s %-8s %s\n" % ("NAME", "SCOPE", "FOLDER"))
        for name, scope, folder in found:
            io.out.write(("%-24s %-8s %s" % (name, scope, folder or "")).rstrip() + "\n")
        io.out.write("remove one: kit mcp remove NAME SCOPE [FOLDER]\n")
        return 0
    if args[:1] != ["remove"] or len(args) not in (3, 4) or args[2] not in SCOPES \
            or (len(args) == 4) != (args[2] != "user"):
        io.err.write(USAGE)
        return 2
    name, scope = args[1], args[2]
    folder = os.path.abspath(io.expand(args[3])) if len(args) == 4 else None
    if (name, scope, folder) not in servers(io):
        io.err.write("kit mcp remove: no server %s of the scope %s%s (kit mcp list)\n"
                     % (name, scope, " in " + folder if folder else ""))
        return 2
    argv = ["claude", "mcp", "remove", name, "-s", scope]
    rc, out, err = io.claude(argv[1:], folder or io.home)
    io.out.write(out)
    io.err.write(err)
    io.log({"command": "mcp remove", "server": name, "scope": scope, "folder": folder, "argv": argv,
            "exit": rc, "changes": [{"removed": {"mcp_server": name, "scope": scope, "folder": folder}}] if rc == 0
            else []})
    return 0 if rc == 0 else 1
