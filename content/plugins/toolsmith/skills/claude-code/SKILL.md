---
name: claude-code
description: Where Claude Code is set - its command line, settings files, environment variables, plugins, hooks, conversations. Use before changing or relying on an option, a setting, a hook or a plugin of Claude Code.
---

Each line here was true when it was written. Claude Code changes often: check the one you rely on with
`claude --help`, in the documentation or by a run in an empty folder.

What wins when a name is in two places (checked on Claude Code 2.1.332, one run each, print mode):
- A subagent: `--agents` over the project's `.claude/agents`, over the user's, over a plugin's.
- A setting: `--settings` over the project's and the user's files; lists (permission rules, hooks) are joined.
- A skill of a plugin has its own name `PLUGIN:SKILL` and stands beside a project's skill of the same name.
- `--setting-sources user` leaves out the project's skills, subagents, commands, hooks and `.mcp.json`; its
  `CLAUDE.md` is still read. What `--plugin-dir`, `--agents`, `--settings` and `--mcp-config` give stays.
- `"enabledPlugins": {"NAME@builtin": false}` turns off a built-in plugin (`cc-plugin-easel`: the server `easel`).
- A deny rule `Agent(NAME)` takes a subagent type from the session; `general-purpose` stays.

Where Claude Code is set:
- The command line of a session: the model, the effort, `--permission-mode`, `--continue`, `--name`, `--plugin-dir`, `--settings` (a file or a JSON text), `--remote-control`, `--autocompact`, `--fallback-model`, `--tools` (only the listed tools come in; with no `Skill` there are no skills), `--system-prompt` (in place of the default one), `--system-prompt-snapshot` (on: a continued conversation keeps the prompt it began with), `--agent` (an agent's file as the system prompt), `--strict-mcp-config` with `--mcp-config`.
- Settings files: `~/.claude/settings.json` for the user, `.claude/settings.json` in a project, and the one given with `--settings`. They hold `env`, `permissions`, `hooks`, `enabledPlugins`, `skillOverrides`, `outputStyle`. Remote Control (`remoteControlAtStartup`) is read from the user file only. `~/.claude.json` holds the account and the onboarding.
- Environment variables: the hard window (`CLAUDE_CODE_AUTO_COMPACT_WINDOW`; compaction comes at it minus 33k), the subagents' model and effort (`CLAUDE_CODE_SUBAGENT_MODEL`, `CLAUDE_CODE_SUBAGENT_EFFORT`), no advisor tool (`CLAUDE_CODE_DISABLE_ADVISOR_TOOL`).
- A plugin: `.claude-plugin/plugin.json`, `skills/NAME/SKILL.md`, `agents/NAME.md`, `hooks/hooks.json` with scripts under `${CLAUDE_PLUGIN_ROOT}`, `bin/` on the session's `PATH`. It comes from a marketplace (`.claude-plugin/marketplace.json` at the root of a repository; `claude plugin marketplace add`, `claude plugin install NAME@MARKETPLACE`) or, for one session, from `--plugin-dir`.
- A hook prints text into the session: `SessionStart` for the session (at a start, a resume and a compaction), `SubagentStart` for a subagent. A subagent does not get the session's system prompt, only what its hook and its agent file give.
- `SessionEnd` runs a command when a session ends, with the reason, the session's id and its transcript in the JSON on its input. It runs when the session is killed in the middle of a turn too (the reason `other`). All such hooks share 1.5 seconds unless one sets `timeout`, and what a hook starts ends with the session unless it is set apart (`setsid`).
- The conversations: `~/.claude/projects/<the folder's path with - for other characters>/*.jsonl`.
- Background sessions: `claude --resume ID --bg "PROMPT"` continues a conversation with no terminal, in a folder that is trusted; `claude agents --json` lists them; `claude stop` takes the first eight characters of the id, not the whole.
