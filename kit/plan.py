"""plan.py - the plan of a session: from the start's keys and the project's fields (config.py) to the session's config,
its environment and its command line. Pure: it reads no file, starts no process and has no clock; the ID is given.
A mistake raises PlanError, which the command turns into exit code 2. Standard library only."""
import hashlib, json, re

from kit import config

MODELS = ("opus", "sonnet", "haiku", "fable")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# the keys of parked parts, refused with a message that names them
EDITOR = ("--code-server", "--vscode")
PARKED = ("--label", "--save", "--no-dashboard", "--clear", "-n", "--reset", "--role", "--addon",
          "--model", "--effort", "--sub-model", "--sub-effort", "--subagents", "--tools", "--env", "--env-clear",
          "--cli", "--centre")
# the old roles and add-ons: an agent or a plugin each now, or a tool
ROLES_ADDONS = ("--qa", "--bare", "--design", "--development", "--toolsmith", "--fullstack", "--universal", "--gstack",
                "--playwright-cli", "--chrome-devtools-mcp", "--openspec", "--langfuse")
# the keys that are gone, with what is in their place
# the keys of the two windows and the field each sets; the other window is dropped
WINDOW_KEYS = {"--window": "context_window", "--compact": "compact_window"}
# the keys that are gone, with what is in their place
GONE = {"--eco": "an agent in its place: --agent NAME", "--profile": "an agent in its place: --agent NAME"}
PLUGIN_TEXTS = ("system-prompt.md", "agent.md")     # a plugin's own lines of the system prompt
CORE = "agent-kit"                                  # the plugin each session has, first
HEADER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)  # the header of an agent's file
WINDOW_KEY = re.compile(r"([1-9][0-9]*)([kK]?)")
ID = re.compile(r"[a-z0-9]{4}")                     # a session's ID
SESSION_VAR = "AGENT_KIT_SESSION"                   # the session's ID, for the hooks
# a variable whose name ends so is shown only as its fingerprint
SECRET = re.compile(r"(^|_)(KEY|TOKEN|SECRET|PASSWORD|CREDENTIALS)$", re.IGNORECASE)
# the variables the kit sets or leaves out; one it leaves out is dropped from an inherited environment
WINDOW_VAR = "CLAUDE_CODE_AUTO_COMPACT_WINDOW"
ADVISOR_VAR = "CLAUDE_CODE_DISABLE_ADVISOR_TOOL"
IDLE_VAR = "CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS"     # the context from which an idle session is compacted
CONNECTORS_VAR = "ENABLE_CLAUDEAI_MCP_SERVERS"
# 1: the session has a system prompt of its agent, and the session's hook gives nothing; 0: the session has Claude
# Code's own, and the kit gives it and its subagents no text: neither hook gives any
PROMPT_VAR = "AGENT_KIT_PROMPT"
PLUGIN_PROMPTS_VAR = "AGENT_KIT_PLUGIN_PROMPTS"     # the plugins' system-prompt.md files, for the subagents' hook
DESIGN_VAR = "AGENT_KIT_DESIGN_DIR"                  # the folder of the project's design, in the project
ROLE_VAR = "AGENT_KIT_ROLE"                         # the agent's file, for the hook outside the kit; never set here
# the agent a session of Claude Code is started as when its subagents have tools it has not: --tools is the pool
# of the session and its subagents, and the session's own smaller list is the tools of the agent it is started as
SESSION_AGENT = "kit-session"


class PlanError(Exception):
    """a start that cannot be planned; the message names the key or the field"""


def parse_start(args):
    """the words after `kit start`: (the project, its repository named as owner/name or None, the keys' layer of the
    fields, the keys as given, dry run, whether a new conversation is asked for by --new). The last key of a kind
    wins"""
    name, layer, given, dry, fresh, i = None, {}, [], False, False, 0
    while i < len(args):
        a = args[i]
        i += 1
        if a == "--dry-run":
            dry = True
        elif a == "--new":
            fresh = True
            given.append(a)
        elif a[2:] in MODELS and a.startswith("--"):
            layer["model"] = a[2:]
            given.append(a)
        elif a[2:] in EFFORTS and a.startswith("--"):
            layer["effort"] = a[2:]
            given.append(a)
        elif a in WINDOW_KEYS:
            if i >= len(args):
                raise PlanError("kit start: %s needs a value: a number of tokens, like 132k or 132000, "
                                "or default" % a)
            v = args[i]
            i += 1
            given += [a, v]
            if v == "default":
                for w in config.WINDOWS:
                    layer.pop(w, None)
                continue
            m = WINDOW_KEY.fullmatch(v)
            n = int(m.group(1)) * (1000 if m.group(2) else 1) if m else 0
            if not 1 <= n <= config.WINDOW_MAX:
                raise PlanError("kit start: %s %s: a number of tokens, like 132k or 132000, up to %d, "
                                "or default" % (a, v, config.WINDOW_MAX))
            layer.update(dict.fromkeys(config.WINDOWS), **{WINDOW_KEYS[a]: n})
        elif a in GONE:
            raise PlanError("kit start: %s is gone; %s" % (a, GONE[a]))
        elif a == "--agent":
            if i >= len(args) or not config.WORD.fullmatch(args[i]):
                raise PlanError("kit start: --agent needs an agent's name, like --agent qa")
            layer["agent"] = args[i]
            given += [a, args[i]]
            i += 1
        elif a == "--plugin":
            if i >= len(args) or not config.WORD.fullmatch(args[i]):
                raise PlanError("kit start: --plugin needs a plugin's name, like --plugin qa")
            layer.setdefault("plugins", []).append(args[i])
            given += [a, args[i]]
            i += 1
        elif a in EDITOR:
            raise PlanError("kit start: %s: the editor is parked" % a)
        elif a in ROLES_ADDONS:
            raise PlanError("kit start: %s: a role or an add-on of the old kit; an agent or a plugin now: "
                            "--agent NAME, --plugin NAME" % a)
        elif a in PARKED:
            raise PlanError("kit start: %s: the key of a parked part" % a)
        elif a.startswith("-"):
            raise PlanError("kit start: unknown option %s" % a)
        elif name is None:
            name = a
        else:
            raise PlanError("kit start: one project only, not %s and %s" % (name, a))
    if name is None:
        raise PlanError("kit start: the project's name is missing: kit start PROJECT, or owner/name to clone it")
    owner, slash, short = name.rpartition("/")
    if slash and not config.REPO.fullmatch(name):
        raise PlanError("kit start: %s: the owner of a repository has letters, digits and -, and does not start "
                        "with -" % name)
    if not config.NAME.fullmatch(short):
        raise PlanError("kit start: %s: a project's name has letters, digits and . _ -, and starts with neither . "
                        "nor -" % name)
    return short, (name if slash else None), layer, given, dry, fresh


def _settings(f):
    s = {}
    if not f["claude_ai_skills"]:
        s["syncClaudeAiSkills"] = False
    if not f["claude_ai_plugins"]:
        s["syncClaudeAiPlugins"] = False
    if not f["idle_compact"]:
        s["idleCompaction"] = False
    for field, key in (("cache_life", "promptCacheTtl"), ("subagent_cache_life", "subagentPromptCacheTtl")):
        if f[field] is not None:
            s[key] = f[field]
    if f["output_style"] is not None:
        s["outputStyle"] = f["output_style"]
    if not f["bundled_skills"]:
        s["disableBundledSkills"] = True
    if f["bundled_skills_off"]:
        s["skillOverrides"] = {n: "off" for n in f["bundled_skills_off"]}
    if f["builtin_plugins_off"]:
        s["enabledPlugins"] = {n + "@builtin": False for n in f["builtin_plugins_off"]}
    if f["subagents_off"]:
        s["permissions"] = {"deny": ["Agent(%s)" % n for n in f["subagents_off"]]}
    return json.dumps(s, separators=(",", ":")) if s else None


def window(value, model):
    """the hard window of the model: a number as it is; of an object, the model's own key, else the first key that is a
    part of the model's name, else "*", else none"""
    if not isinstance(value, dict):
        return value
    if model in value:
        return value[model]
    for k, v in value.items():
        if k != "*" and k in model:
            return v
    return value.get("*")


def _plugin_dirs(names, found):
    """--plugin-dir for agent-kit first, then for each plugin of the list once; found is {name: folder}"""
    out = []
    for n in [CORE] + list(names):
        if n not in found:
            raise PlanError("plugins: %s: no such plugin; there are %s" % (n, ", ".join(sorted(found)) or "none"))
        if found[n] not in out[1::2]:
            out += ["--plugin-dir", found[n]]
    return out


DESCRIPTION = re.compile(r"^description:[ \t]*(.+?)[ \t]*$", re.MULTILINE)


def described(text, name):
    """the description in the header of an agent's file; with none, the agent's name"""
    head = HEADER.match(text)
    found = DESCRIPTION.search(head.group(0)) if head else None
    return found.group(1) if found else "The agent %s." % name


def subagents(f, agent_of, text_of):
    """the agents of the field subagents, ready for an engine: {name: {"description", "prompt", "model", "effort",
    "plugins"}}. agent_of(NAME) gives an agent's fields (config.agent) and text_of(PATH) the text of its role's
    file; the entry's own model and effort win over the agent's"""
    out = {}
    for x in f["subagents"]:
        own = {"agent": x} if isinstance(x, str) else x
        name = own["agent"]
        if name == f["agent"]:
            raise PlanError("subagents: %s is the session's agent already; an agent is the session or its subagent"
                            % name)
        desc = agent_of(name)
        if not desc.get("role"):
            raise PlanError("subagents: %s: the agent has no role, and a subagent is its role's text" % name)
        text = text_of(desc["role"])
        out[name] = {"description": described(text, name), "prompt": body(text) + "\n",
                     "model": own.get("model") or desc.get("model"),
                     "effort": own.get("effort") or desc.get("effort"), "plugins": list(desc.get("plugins") or [])}
    return out


def body(text):
    """the text of an agent's file without its header"""
    return HEADER.sub("", text, count=1).strip()


def prompt(*texts):
    """a prompt of texts in their order, the empty ones left out"""
    return "\n\n".join(t.strip() for t in texts if t and t.strip()) + "\n"


def names(name, sid, f):
    """(the session's name, the prefix of Remote Control): the agent's prefix, the project, the ID, its postfix"""
    pre, post = [f["name_prefix"]] if f["name_prefix"] else [], [f["name_postfix"]] if f["name_postfix"] else []
    return "-".join(pre + [name, sid] + post), "-".join(pre + [name] + post)


def fields_of(fields, layer):
    """the fields with the start's keys over them; a key --plugin adds to the plugins of the config and the agent"""
    f = config.over(fields, layer or {})
    if (layer or {}).get("plugins"):
        f["plugins"] = list(dict.fromkeys(list(fields["plugins"]) + layer["plugins"]))
    return f


def fingerprint(value):
    """sha256: and the first 12 hex digits of the value's hash"""
    return "sha256:" + hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]


MCP_KEYS = ("mcp_servers", "mcpServers")
MCP_PLAIN = ("type",)                   # of an MCP server only its type is shown; the rest (command, env, headers,
                                        # url, args) may hold a key, and is shown as fingerprints


def _server(s):
    if not isinstance(s, dict):
        return fingerprint(s)
    return {k: v if k in MCP_PLAIN and isinstance(v, str) else
            {h: fingerprint(x) for h, x in v.items()} if isinstance(v, dict) else
            [fingerprint(x) for x in v] if isinstance(v, list) else fingerprint(v) for k, v in s.items()}


def _servers(doc):
    return {n: _server(s) for n, s in doc.items()} if isinstance(doc, dict) else fingerprint(doc)


def kept(doc):
    """the session's config as sessions/ID.json keeps it: the MCP servers only as the log shows them, since their
    own file holds them whole"""
    if not doc.get("mcp") and not doc["config"].get("mcp_servers"):
        return doc
    return dict(doc, config=dict(doc["config"], mcp_servers=_servers(doc["config"]["mcp_servers"])),
                mcp={"file": doc["mcp"]["file"]} if doc.get("mcp") else None)


def shown(doc):
    """the document as the log and --dry-run show it: a variable of a secret's name, and the env and headers of an
    MCP server, only as fingerprints"""
    if isinstance(doc, dict):
        return {k: _servers(v) if k in MCP_KEYS else
                fingerprint(v) if isinstance(k, str) and SECRET.search(k) and isinstance(v, str) else shown(v)
                for k, v in doc.items()}
    if isinstance(doc, list):
        return [shown(v) for v in doc]
    return doc
