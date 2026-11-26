# The kit's configuration

Each field of the kit's configuration: what it is for, its default, and how the start gives it to Claude Code. The
kit prepares the session; it does not tune it. So each thing the kit can set is a field here, with a default, and a
project or a start's key can change it. The defaults are `kit/defaults.json`; `tests/test_config.py` checks that
this file and that one name the same fields.

The defaults are also the first config: a start that finds no `~/.config/agent-kit/config.json` copies
`kit/defaults.json` there, and the user changes his copy. A field missing from the copy, as one that a later release
adds, takes its default. A change to a field already in the copy reaches it by a migration: the top field `version`
(a whole number from 1; a copy without it has 1) says which of the kit's steps the copy has had, and the set-up and
each start bring the copy to the kit's version. A step changes a default (only where the copy still holds the old
one: a value the user wrote is kept), renames a field or drops one. The copy as it was is kept beside it as
`config.json.vN`, N its old version, and the change goes to `kit.log` whole.

The session's fields. By default the kit sets none of the model, the effort, the windows, the subagents' model or
effort, the agent, the tools, the MCP servers or the system prompt: the session has Claude Code's own, and an agent
sets them.

| Field | What it is for | Default | How the start gives it |
|---|---|---|---|
| `advisor` | The advisor: a stronger model that the session calls as a tool. `off`: no advisor, the user's `advisorModel` and `/advisor` do not work. `default`: what Claude Code has (off, unless the user set `advisorModel`). A model's name: that model as the advisor. | `off` | `off`: `CLAUDE_CODE_DISABLE_ADVISOR_TOOL=1` in the environment; `default`: nothing; a model: `--advisor MODEL` |
| `context_window` | The hard window: compaction comes at this size minus 33k, and `/autocompact` inside the session does not change it. A number, or an object by the model (as `{"haiku": 113000, "*": 200000}`): the model's own key, else the first key that is a part of the model's name, else `"*"`, else none. When to set it: `docs/context-cost.md`. | none | `CLAUDE_CODE_AUTO_COMPACT_WINDOW` in the environment |
| `compact_window` | The soft window: compaction comes at this size minus 33k, and `/autocompact` inside the session changes it for that session. When to set it: `docs/context-cost.md`. | none | `--autocompact N` |
| `idle_compact` | Whether Claude Code compacts a session left idle, about an hour after its last request, while its cache still lives. Leave it on where sessions are left and come back: a return then writes the summary, not the whole context. See `docs/context-cost.md`. | `true` | `false`: `"idleCompaction":false` in the `--settings` JSON string; `true`: nothing |
| `idle_compact_from` | The used context, in tokens, from which the idle compaction applies; 100000 at least. Claude Code's own is 200000; the kit's is lower because most costly returns had a context of 100 to 200 thousand. It never applies when the window compacts under it (a `context_window` of 132000 compacts at 99000). `null`: Claude Code's own. When to set it: `docs/context-cost.md`. | `100000` | `CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS` in the environment; `null` or `idle_compact` `false`: nothing |
| `cache_life` | The life of the prompt cache of the main conversation, `5m` or `1h`. Set `5m` only for an agent that works alone with no pause over five minutes (a write costs 1.25 in place of 2); `1h` on an API key, where the default is five minutes. When to set it: `docs/context-cost.md`. | none: Claude Code's own | `"promptCacheTtl"` in the `--settings` JSON string |
| `subagent_cache_life` | The life of the prompt cache of subagents, workflows and the compaction, `5m` or `1h`. Set `1h` for subagents that work long with pauses or are continued after more than five minutes. When to set it: `docs/context-cost.md`. | none: Claude Code's own (five minutes) | `"subagentPromptCacheTtl"` in the `--settings` JSON string |
| `model` | The session's model. | none | `--model MODEL`; none: nothing |
| `effort` | The session's effort. | none | `--effort EFFORT`; none: nothing |
| `fallback_model` | The model the session takes when its own is overloaded. | none | `--fallback-model MODEL` |
| `subagent_model` | The subagents' model by default; the `model` of an agent's definition and of the call win over it. When to set it: `docs/context-cost.md`. | none | `CLAUDE_CODE_SUBAGENT_MODEL` in the environment; none: nothing |
| `subagent_effort` | The subagents' effort by default. | none | `CLAUDE_CODE_SUBAGENT_EFFORT` in the environment; none: nothing |
| `permission_mode` | The permission mode. | `auto` | `--permission-mode MODE` |
| `prompt_suggestions` | The suggestions of the next prompt. | `false` | `--prompt-suggestions false`; `true`: nothing |
| `remote_control` | The session reached from the phone and the browser. | `true` | `--remote-control` with `--remote-control-session-name-prefix PREFIX-PROJECT-POSTFIX` (the parts that are set); `false`: nothing |
| `claude_ai_skills` | The skills synced from the claude.ai account. | `false` | `false`: `"syncClaudeAiSkills":false` in the `--settings` JSON string; `true`: nothing |
| `claude_ai_plugins` | The plugins synced from the claude.ai account. | `false` | `false`: `"syncClaudeAiPlugins":false` in the `--settings` JSON string; `true`: nothing |
| `claude_ai_connectors` | The MCP connectors of the claude.ai account. | `false` | `false`: `ENABLE_CLAUDEAI_MCP_SERVERS=false` in the environment; `true`: nothing |
| `env` | The project's variables, such as `GH_TOKEN`; a variable here wins over one the kit sets. The user's `env` and the project's are merged by the variable's name, the project's value winning. | empty | the environment, never a command line |
| `engine` | The coding agent the session runs: `claude` (Claude Code) or `opencode` (OpenCode: `model` as `provider/model` is required, `permission_mode` is `manual` or `bypassPermissions`, and a field it does not have, set off the kit's default, is refused by its name). `codex` is a stub: a start with it is refused as not built. OpenCode is a trial. A name the kit has no module for is refused. | `claude` | the program of the command line, built by `kit/engines/NAME.py` |
| `subagents` | The agents the session has as subagents, under their own names: a list, each a name or `{"agent": NAME, "model": ..., "effort": ...}`, whose model and effort win over the agent's. The subagent is the agent's role; its plugins are added to the session's. An agent is the session or its subagent, not both; a subagent needs a role. The kit's `dev` has `design` on `fable` with the effort `low`. | `[]` |
| `agent` | The agent the session is started as: a description of the group `agents` or of a source (`agents/NAME.json`; the kit's are `dev`, `design`, `qa`, `spec`), whose fields lie over the project's. Inside a description: the agent it is built over. `null`: no agent. The start's `--agent NAME` wins. An agent there is not stops the start (exit code 2). | none | its fields over the project's, its plugins added |
| `role` | The agent's role: a Markdown file, a path from `/` or `~/` (in a source's description, also a path from its folder `agents/`), whose text without its header is added to the system prompt. A missing file stops the start. | none | its text after `system_prompt`'s in `--system-prompt`, else after `system_prompt_append`'s in `--append-system-prompt` |
| `system_prompt` | A Markdown file, a path from `/` or `~/`, given in place of Claude Code's system prompt, then the agent's text. The kit's rules are such a file: `plugins/agent-kit/system-prompt.md`. A missing file stops the start (exit code 2). | none | `--system-prompt TEXT --system-prompt-snapshot off` and `AGENT_KIT_PROMPT=1`; none: `AGENT_KIT_PROMPT=0`, and the rules' hooks give nothing |
| `system_prompt_append` | A Markdown file, a path from `/` or `~/`, added after the system prompt, Claude Code's or the one above. A missing file stops the start. | none | `--append-system-prompt TEXT` |
| `tools` | The built-in tools the session has, as `["Bash", "Read", "Edit"]`; `[]` none. With no `Skill`, no skill comes in. | none: all | `--tools A,B`; none: nothing |
| `subagent_tools` | The built-in tools the session's subagents have and the session has not, as `["WebSearch", "WebFetch"]`: what they bring in stays out of the session's window. It needs `tools` with a tool in it and a `system_prompt`; without either the start stops (exit code 2). Claude Code only. | none | `--tools` names both lists, and the session is started as the agent `kit-session` whose tools are those of `tools` and whose prompt is the session's own (`--agent kit-session`, its entry in `--agents`) |
| `mcp_servers` | The session's MCP servers, as in `.mcp.json`: `{NAME: {"command": ...}}` or `{NAME: {"type": "http", "url": ...}}`. In the log and the dry run and in `sessions/ID.json` only a server's `type` is shown; its `command`, `env`, `headers`, `url` and `args` are fingerprints. | `{}` | the file `sessions/ID.mcp.json` (mode 600, removed by `kit kill`) by `--mcp-config FILE` |
| `mcp_strict` | Only the servers of `mcp_servers`: those of Claude Code's files and of the plugins are left out. | `false` | `--strict-mcp-config` |
| `project_config` | Claude Code reads what the project's repository holds for it: the skills, subagents, commands and settings of its `.claude/` (the hooks and the permission rules among them) and the servers of its `.mcp.json`. With `false` none of them comes in; the project's `CLAUDE.md` is still read. | `true` | `false`: `--setting-sources user` |
| `bundled_skills` | Claude Code's own bundled skills. | `true` | `false`: `"disableBundledSkills":true` in the `--settings` JSON string |
| `bundled_skills_off` | Bundled skills turned off one by one, by name. | `[]` | `"skillOverrides":{NAME:"off"}` in the `--settings` JSON string |
| `builtin_plugins_off` | Claude Code's built-in plugins turned off, by name (`cc-plugin-easel`: the chart tool and its MCP server `easel`). | `[]` | `"enabledPlugins":{"NAME@builtin":false}` in the `--settings` JSON string |
| `subagents_off` | Subagents the session may not start, by name: Claude Code's own (`Plan`, `claude`, `web-fetch`) or others. `general-purpose` stays on Claude Code's list. | `[]` | `"permissions":{"deny":["Agent(NAME)"]}` in the `--settings` JSON string |
| `name_prefix`, `name_postfix` | Words before and after the session's name. | none | `--name PREFIX-PROJECT-ID-POSTFIX` (the parts that are set) |
| `plugins` | The session's plugins besides `agent-kit` and the agent's, which each session has: folders, each with its skills, agents, hooks, tools (`bin/`, MCP) and output styles; the kit's `plugins/NAME` first, then `~/.local/share/agent-kit/plugins/NAME`. A project's list takes the place of the session's; the agent's plugins and the start's `--plugin NAME` add to it. | `[]` | `--plugin-dir PATH` for `agent-kit` first, then the agent's, then one for each plugin here |
| `design_dir` | The folder of the project's design, inside the project: the design system and the designs made with it; the designer reads its `DESIGN.md` first and writes its own work there. | `design` | `AGENT_KIT_DESIGN_DIR` in the session's environment |
| `output_style` | The session's output style: its text goes into the system prompt of each request of the session, not of a subagent. A plugin's style is `PLUGIN:NAME`. | none | `"outputStyle":"NAME"` in the `--settings` JSON string |
| `keep_coding_instructions` | Whether the session's style keeps Claude Code's own section on the work with code (the scope of a change, the comments, the checks); with `false` that section is left out. Written down, not used yet. | `true` | not given at the start yet: it is the field `keep-coding-instructions` in the header of the style's file, and Claude Code has no flag or key for it |

A session has at most one of the two windows: a project, an agent or a key that sets one drops the other, so
`compact_window` in an agent drops the project's `context_window`. With neither, the model's own window. Neither window changes the
model's window, only where compaction comes (measured 2026-11-22, Claude Code 2.1.327).

A variable that the kit sets in one case and leaves out in another (`CLAUDE_CODE_AUTO_COMPACT_WINDOW`,
`CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS`,
`CLAUDE_CODE_DISABLE_ADVISOR_TOOL`, `ENABLE_CLAUDEAI_MCP_SERVERS`) is dropped from the environment the session
inherits when the kit leaves it out and `env` does not give it, so a variable of the tmux server or of the shell does
not change the session.

Not measured: that `outputStyle` in the `--settings` JSON string takes a plugin's style.

The project's fields: where the project is, and whether the machine's start starts it. A project gives them.

| Field | What it is for | Default | How the start gives it |
|---|---|---|---|
| `repo` | The project's repository, `owner/name`, cloned when the folder is missing. | empty | the clone by `kit start` (`gh repo clone`) |
| `folder` | The project's folder, where the session runs. | empty | the session's working folder |
| `autostart` | A session of the project started when the machine starts, not opened; one already running is left. | `false` | `kit autostart`, which the user's unit of `kit setup-files` runs at the machine's start (with linger) |

The agents: the group `agents` of the config, `{NAME: {FIELD: VALUE}}`, each a set of the session's fields above (a
field that is not one is refused), and the files `agents/NAME.json` of a source: the kit's folder, and
`~/.local/share/agent-kit/`, read first. The config's agent of a source's name lies over it field by field. An
agent's field `agent` names the agent it is built over; one built over itself is refused. The fields of a session
come in this order, the last winning: the defaults, the user's `session`, the project, the agent, then the start's
keys; the plugins of the project, the agent and the keys add up. For example `{"kit": {"agent": "dev",
"system_prompt": "~/.agent-kit/plugins/agent-kit/system-prompt.md"}}`. Version 3 of the config brings `profiles`
to `agents` and a project's `profile` to its `agent`.

The user's fields: what the set-up writes into `~/.claude/settings.json`, the other keys kept. They hold for every
session of the user, the kit's and the others, so a project cannot change them; a session's field can still turn
the thing off for one session.

| Field | What it is for | Default | How the set-up gives it |
|---|---|---|---|
| `claude_ai_connectors` | The MCP connectors of the claude.ai account, for every session of the user. | `false` | `false`: `"disableClaudeAiConnectors": true` in `~/.claude/settings.json`; `true`: nothing |
