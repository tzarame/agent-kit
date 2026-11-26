"""opencode.py - the engine OpenCode: from a session's fields to its command line, its environment and the agents'
files of the session's own folder of the kit. Pure, as kit/plan.py is. Nothing is written to the project or to
OpenCode's own folders, and OpenCode's sign-in is its own: the kit gives it no key."""
import json

from kit import plan

# the fields this engine honours; another one set off the kit's default is refused by its name (engines.make)
FIELDS = ("engine", "model", "effort", "agent", "subagents", "role", "plugins", "system_prompt",
          "system_prompt_append", "env", "permission_mode")
# the permission modes there are here: manual asks, bypassPermissions is OpenCode's --auto
MODES = {"manual": [], "bypassPermissions": ["--auto"]}
CONFIG_DIR_VAR = "OPENCODE_CONFIG_DIR"          # the folder OpenCode reads its agents from
CONFIG_VAR = "OPENCODE_CONFIG_CONTENT"          # a configuration given whole, over the files
# OpenCode's own way to drive the program claude, by the Agent SDK: the kit never turns it on
CLAUDE_PATH_VAR = "OPENCODE_CLAUDE_PATH"
MAIN = "kit"                                    # the session's agent, when the profile names none


def _model(value, where):
    if value is None or "/" not in value.strip("/"):
        raise plan.PlanError("%s: %s: OpenCode needs a model as provider/model, like openai/gpt-5; with none it "
                             "would use its own free models, and the project's text would go to them"
                             % (where, "none" if value is None else value))
    return value


def _file(description, mode, model, effort, text):
    """an agent's file of OpenCode: the header and the prompt"""
    head = ["description: " + json.dumps(description, ensure_ascii=False), "mode: " + mode]
    head += ["model: " + model] if model else []
    head += ["variant: " + effort] if effort else []
    return "---\n%s\n---\n%s" % ("\n".join(head), text)


def make(name, entry, f, sid, plugins, given, machine, talked, texts, mcp_file, folder):
    """the session's config of engines.make, for `opencode`; folder is the session's own folder of the kit"""
    _model(f["model"], "model")
    if f["permission_mode"] not in MODES:
        raise plan.PlanError("permission_mode: %s: OpenCode has %s" % (f["permission_mode"], " and ".join(MODES)))
    if folder is None:
        raise plan.PlanError("engine: opencode: no folder for the session's agents")
    for n in f["plugins"]:
        if n not in plugins:
            raise plan.PlanError("plugins: %s: no such plugin; there are %s" % (n, ", ".join(sorted(plugins))))
    main = f["agent"] or MAIN
    role = plan.body(texts.get("role", "")) if f["role"] is not None else ""
    parts = [texts.get("system_prompt", "") if f["system_prompt"] is not None else "", role,
             texts.get("system_prompt_append", "") if f["system_prompt_append"] is not None else ""]
    for n in dict.fromkeys(f["plugins"]):
        t = texts.get("plugins", {}).get(n) if n != plan.CORE else None
        parts += [t.get("system-prompt.md", ""), t.get("agent.md", "")] if t else []
    described = plan.described(texts["role"], main) if f["role"] is not None and texts.get("role") else \
        "The session's agent."
    files = [{"file": "%s/agents/%s.md" % (folder, main),
              "text": _file(described, "primary", f["model"], f["effort"], plan.prompt(*parts))}]
    for n, s in (texts.get("subagents") or {}).items():
        model = _model(s["model"], "subagents: %s: model" % n) if s["model"] is not None else None
        files.append({"file": "%s/agents/%s.md" % (folder, n),
                      "text": _file(s["description"], "subagent", model, s["effort"], s["prompt"])})
    env = dict(machine or {})
    env[plan.SESSION_VAR] = sid
    env[CONFIG_DIR_VAR] = folder
    env[CONFIG_VAR] = json.dumps({"update": "disable", "model": f["model"], "default_agent": main},
                                 separators=(",", ":"))
    env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
    # no CLAUDE.md, ~/.claude/skills or Claude Code's prompt: the session has the kit's rules once, from the kit
    env["OPENCODE_DISABLE_CLAUDE_CODE"] = "1"
    env.update(f["env"])
    # --standalone: the session has its own server, and OpenCode's background service is not started
    argv = ["opencode", "--standalone"] + MODES[f["permission_mode"]]
    return {"id": sid, "project": name, "folder": entry["folder"], "repo": entry.get("repo") or None, "config": f,
            "keys": list(given), "env": env, "unset": [v for v in (CLAUDE_PATH_VAR,) if v not in env],
            "mcp": None, "files": files, "argv": argv}
