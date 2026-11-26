# The kit's plugins

Each folder here is a plugin of Claude Code, in its own format: `.claude-plugin/plugin.json`, `skills/NAME/SKILL.md`,
`agents/NAME.md`, `hooks/hooks.json`, `bin/` (put on the session's `PATH`). The kit gives a session its plugins with
`--plugin-dir`: `agent-kit` first, always, then the plugin of the session's agent (the field `agent`, `dev` by default,
or `--agent NAME`), then those of the field `plugins`, or of the start's keys `--plugin NAME`. The marketplace at the root, `.claude-plugin/marketplace.json`, lists the same plugins for a
`claude` started without the kit. A skill is in one plugin only; what two plugins need is in `agent-kit`.
`tests/test_plugins.py` checks all of this.

A plugin is packaging only. A role is an agent: the file `agents/NAME.md` of the plugin NAME, in Claude Code's agent
format; its text is in the session's system prompt, after the kit's rules. A skill is loaded by a call of Skill and is
never in the prompt. Without the kit, `claude --agent NAME` gives the same role.

A plugin of this folder is found before one of `~/.local/share/agent-kit/plugins/NAME` (a plugin fetched from
elsewhere), so a fetched plugin cannot take the name of one of the kit.

## agent-kit

What every session has.

- `system-prompt.md`: the rules of the session and of each subagent: the `From:` line, OpenSpec, commit and push,
  the care before a change.
- `agent.md`: the rules of the session only: the answers, the review of a change, what to give a subagent.
- `subagent.md`: the rules of a subagent only. `agents/subagent.md` is the same text as a subagent's definition.
- `skills/security`, `skills/owner-run`: needed by every kind of work. `bin/owner-run` and `agents/owner-review.md` are
  the gate of a command for the owner (the skill `owner-run` says how).

| Event | Script | What it does |
|---|---|---|
| `SessionStart` | `scripts/session-rules.sh` | Nothing when the kit gave the rules as the system prompt (`AGENT_KIT_PROMPT=1`). Else gives the session `system-prompt.md`, `agent.md` and its agent's text; again after a compaction and a resume. |
| `SubagentStart` | `scripts/subagent-rules.sh` | Gives each subagent `system-prompt.md` and `subagent.md`. |
| `PreToolUse` (Bash) | `scripts/owner-approve.sh` | Denies `owner-run approve` to all but the reviewer `owner-review`, so the agent that wrote a script cannot approve it. |
| `Stop` | `scripts/owner-stop.sh` | Stops a final message that gives the owner an `ssh` line to this machine the gate did not print. |

## dev

Architecture, development and deploy: the agent `dev`, the default one of a session, and the skills `development`,
`app-architecture`, `system-design`, `architecture-decisions`, `infrastructure`.

## design

How a thing looks and how an interface works: the agent `design` and the skills `design`, `ui-ux`.

## qa

Quality assurance: the agent `qa`, the skill `testing`, and a `PreToolUse` hook (`scripts/no-code.sh`) that refuses `Write`, `Edit`
and `NotebookEdit` of a file inside the session's folder: a finding is reported, not fixed. It is not a lock: a shell
command is not checked, and a file outside the folder (a scratch script) is allowed.

## spec

Planning in OpenSpec: the agent `spec`, and a `PreToolUse` hook (`scripts/openspec-only.sh`) that refuses `Write`,
`Edit` and `NotebookEdit` of a file inside the session's folder but outside its `openspec/`. It has no skill of its
own: its profile names the plugins `openspec` and `dev`, for example
`{"profiles": {"plan": {"agent": "spec", "plugins": ["openspec", "dev"]}}}`. Like qa's hook, it is not a lock.

## toolsmith

The agent that works on the kit itself. `skills/claude-code`: where Claude Code is set and what wins when a name
is in two places. Its agent takes `dev` and `openspec` too.

## openspec

[OpenSpec](https://github.com/Fission-AI/OpenSpec) for a project: no agent, and not given by default. Name it in
the field `plugins` of a project, or start with `--plugin openspec`.

- `bin/openspec`: the program. Its first call downloads the release the skills were written for into
  `~/.local/share/agent-kit/openspec/VERSION` (about 90 MB), with OpenSpec's install script of the same tag, which
  checks the program against the release's checksums. An `openspec` the user installed is not touched; one earlier
  on the `PATH` is run in its place. The usage statistics are off.
- `skills/openspec-*`: OpenSpec's own six skills (MIT, `LICENSE.OpenSpec`), as `openspec init` writes them for
  Claude Code. They come with the plugin, so `openspec init` here writes only the project's `openspec/` folder and
  no file of Claude Code in the project.
- A new version: change `VERSION` in `bin/openspec`, run `openspec update` in this repository and copy
  `.claude/skills/openspec-*` here; `tests/test_plugins.py` fails while the two differ.
