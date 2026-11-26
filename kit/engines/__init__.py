"""engines - the coding agents a profile can start, one module each (the names are config.ENGINES). make() gives the
session's config from the project's fields and the start's keys, by the module of the field `engine`. Pure, as
kit/plan.py is."""
from kit import plan
from kit.engines import claude, codex, opencode

ENGINES = {"claude": claude, "codex": codex, "opencode": opencode}


def make(name, entry, fields, sid, plugins, layer=None, given=(), machine=None, talked=True, texts=None,
         mcp_file=None, folders=None, base=None):
    """the session's config: its ID, the project, its folder and repository, the fields with the start's keys over
    them, the keys as given, the environment, the variables to drop, the MCP servers' file and the command line.
    plugins is {name: folder} of the plugins there are; machine is the machine's variables (GitHub as the App), under
    the kit's own; fields has the agent's over the project's already (config.agent); texts is {field: the text of
    its file} of role, system_prompt and system_prompt_append; mcp_file is where the session's MCP servers are written;
    talked is false when the folder has no conversation yet or the start has the key --new, and then --continue, which
    stops claude in a folder with no conversation, is left out. folders is the kit's folder of the engines' own files: a
    session of another engine than claude has ENGINE/ID of it. base is the kit's default fields: with it, a field the
    engine does not honour and that is set off its default is refused by its name"""
    f = plan.fields_of(fields, layer)
    engine = ENGINES[f["engine"]]
    if f["engine"] == "claude":
        return engine.make(name, entry, f, sid, plugins, given, machine, talked, texts or {}, mcp_file)
    if base is not None and engine.FIELDS:
        bad = sorted(k for k in f if k not in engine.FIELDS and k in base and f[k] != base[k])
        if bad:
            raise plan.PlanError("engine: %s does not have %s; leave %s as the kit's default in this profile"
                                 % (f["engine"], ", ".join(bad), "it" if len(bad) == 1 else "them"))
    folder = "%s/%s/%s" % (folders, f["engine"], sid) if folders else None
    return engine.make(name, entry, f, sid, plugins, given, machine, talked, texts or {}, mcp_file, folder)
