"""claude.py - the engine Claude Code: from a session's fields to its command line, its environment and its MCP
servers' file. Pure, as kit/plan.py is: the fields, the texts and the ID are given."""
import json

from kit import plan


def _subagent_tools(f, sp, subs):
    """the tools of subagent_tools the session has not itself; with any, the session must name its own tools and
    have a system prompt of the kit: started as an agent with Claude Code's own prompt it would lose that prompt"""
    extra = [t for t in dict.fromkeys(f["subagent_tools"]) if t not in (f["tools"] or [])]
    if not extra:
        return []
    if not f["tools"]:
        raise plan.PlanError("subagent_tools: tools names no tool; the session's own tools must be listed, and "
                             "subagent_tools adds to them the tools only its subagents have")
    if sp is None:
        raise plan.PlanError("subagent_tools: system_prompt is not set; the session is started as an agent, and "
                             "with no system_prompt it would lose Claude Code's own prompt")
    return extra


def make(name, entry, f, sid, plugins, given, machine, talked, texts, mcp_file):
    """the session's config of engines.make, for `claude`; f is the fields with the start's keys over them"""
    if f["context_window"] is not None and f["compact_window"] is not None:
        raise plan.PlanError("context_window and compact_window are both set; a session has one of them")
    subs = texts.get("subagents") or {}
    if plan.SESSION_AGENT in subs:
        raise plan.PlanError("subagents: %s is the name the kit starts a session under" % plan.SESSION_AGENT)
    # a subagent's plugins come with it: its skills are theirs
    dirs = plan._plugin_dirs(list(f["plugins"]) + [p for s in subs.values() for p in s["plugins"]], plugins)
    env = dict(machine or {})
    for field, var in (("subagent_model", "CLAUDE_CODE_SUBAGENT_MODEL"), ("subagent_effort",
                                                                         "CLAUDE_CODE_SUBAGENT_EFFORT")):
        if f[field] is not None:
            env[var] = f[field]
    w = plan.window(f["context_window"], f["model"] or "")
    if w is not None:
        env[plan.WINDOW_VAR] = str(w)
    if f["idle_compact"] and f["idle_compact_from"] is not None:
        env[plan.IDLE_VAR] = str(f["idle_compact_from"])
    env[plan.SESSION_VAR] = sid
    env[plan.DESIGN_VAR] = f["design_dir"]
    if f["advisor"] == "off":
        env[plan.ADVISOR_VAR] = "1"
    if not f["claude_ai_connectors"]:
        env[plan.CONNECTORS_VAR] = "false"
    sp, role = f["system_prompt"], plan.body(texts.get("role", "")) if f["role"] is not None else ""
    env[plan.PROMPT_VAR] = "0" if sp is None else "1"
    env.update(f["env"])
    argv = ["claude"]
    for field in ("model", "effort"):
        if f[field] is not None:
            argv += ["--" + field, f[field]]
    session_name, rc_prefix = plan.names(name, sid, f)
    argv += ["--permission-mode", f["permission_mode"]]
    argv += (["--continue"] if talked else []) + ["--name", session_name] + dirs
    if sp is not None:
        # the snapshot off: a continued conversation gets the prompt of this start, not the one it began with
        argv += ["--system-prompt", plan.prompt(texts.get("system_prompt", ""), role),
                 "--system-prompt-snapshot", "off"]
    # with Claude Code's own prompt, the agent's text is added to it, after the file of system_prompt_append
    added = [texts.get("system_prompt_append", "") if f["system_prompt_append"] is not None else "",
             role if sp is None else ""]
    # a plugin of the session brings its own lines: its system-prompt.md (the subagents get it by the hook) and
    # its agent.md (the session only), after the agent's text, in the plugins' order
    own = [(n, texts.get("plugins", {}).get(n)) for n in dict.fromkeys(f["plugins"]) if n != plan.CORE]
    if sp is not None:
        # in place of Claude Code's prompt the session has the kit's: the session's own lines of the kit come with it
        added.append((texts.get("plugins", {}).get(plan.CORE) or {}).get("agent.md", ""))
    for n, t in own:
        added += [t.get("system-prompt.md", ""), t.get("agent.md", "")] if t else []
    for_subagents = [plugins[n] + "/system-prompt.md" for n, t in own if t and t.get("system-prompt.md")]
    if any(":" in p for p in for_subagents):     # the hook splits the list at ":"
        raise plan.PlanError("kit start: a plugin's folder has a colon in its path, and its lines would not reach "
                        "the subagents: %s" % next(p for p in for_subagents if ":" in p))
    if for_subagents:
        env[plan.PLUGIN_PROMPTS_VAR] = ":".join(for_subagents)
    if any(t.strip() for t in added):
        argv += ["--append-system-prompt", plan.prompt(*added)]
    agents = {n: {k: s[k] for k in ("description", "prompt", "model", "effort") if s[k] is not None}
              for n, s in subs.items()}
    extra = _subagent_tools(f, sp, subs)
    if extra:
        # started as this agent, the session has its own tools only. Claude Code 2.1.332 gives a session started
        # as an agent the agent's prompt and not the one of --system-prompt (seen in a live session), so the
        # agent's prompt is that same text
        agents[plan.SESSION_AGENT] = {"description": "The session itself; never start it as a subagent.",
                                      "prompt": plan.prompt(texts.get("system_prompt", ""), role),
                                      "tools": list(f["tools"])}
        argv += ["--agent", plan.SESSION_AGENT]
    if agents:
        argv += ["--agents", json.dumps(agents, ensure_ascii=False, separators=(",", ":"))]
    if f["tools"] is not None:
        argv += ["--tools", ",".join(list(f["tools"]) + extra)]
    mcp = {"mcpServers": f["mcp_servers"]} if f["mcp_servers"] else None
    if mcp is not None:
        if mcp_file is None:
            raise plan.PlanError("mcp_servers: no file for the session's MCP servers")
        argv += ["--mcp-config", mcp_file]
    if f["mcp_strict"]:
        argv += ["--strict-mcp-config"]
    if not f["project_config"]:
        argv += ["--setting-sources", "user"]
    if f["remote_control"]:
        argv += ["--remote-control", "--remote-control-session-name-prefix", rc_prefix]
    if not f["prompt_suggestions"]:
        argv += ["--prompt-suggestions", "false"]
    s = plan._settings(f)
    if s is not None:
        argv += ["--settings", s]
    if f["fallback_model"] is not None:
        argv += ["--fallback-model", f["fallback_model"]]
    if f["advisor"] not in ("off", "default"):
        argv += ["--advisor", f["advisor"]]
    if f["compact_window"] is not None:
        argv += ["--autocompact", str(f["compact_window"])]
    unset = [v for v in (plan.WINDOW_VAR, plan.IDLE_VAR, plan.ADVISOR_VAR, plan.CONNECTORS_VAR, plan.ROLE_VAR,
                         plan.PLUGIN_PROMPTS_VAR, "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_SUBAGENT_EFFORT")
             if v not in env]
    return {"id": sid, "project": name, "folder": entry["folder"], "repo": entry.get("repo") or None, "config": f,
            "keys": list(given), "env": env, "unset": unset,
            "mcp": {"file": mcp_file, "content": mcp} if mcp is not None else None, "argv": argv}
