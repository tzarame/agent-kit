# agent-kit

agent-kit sets up a Linux machine (Debian, Ubuntu, Arch or CachyOS, Fedora) for work with Claude Code and starts
Claude there in tmux, with our plugins and settings. Each session can be reached from the Claude app with Remote
Control.

## Install

Once, as your normal user (not root):

```
git clone URL ~/.agent-kit
~/.agent-kit/install/setup.sh
```

`URL` is the address of this repository. The first command copies it to `~/.agent-kit`. The second sets up what is
missing (the packages git, tmux, curl and python3, the GitHub sign-in, Claude Code, the command `kit`), then starts
the project you name; with none named and no repository yet in the home folder, it asks on a terminal for one to
clone. Sign in to Claude with
`claude auth login` when the set-up says so.

Without the set-up, on a machine that already has `python3`, `tmux` and a signed-in `claude`: `python3
~/.agent-kit/kit/__main__.py start PROJECT` starts a session from the clone, with the same keys and the same config.
It writes the config and the session's files only; no command `kit`, no start at boot.

## Daily use

| You want to | Run |
|---|---|
| Set up or update the machine | `kit setup`, or `~/.agent-kit/install/setup.sh` |
| Update the kit, with no question asked | `kit update` |
| Set it up and start a project | `~/.agent-kit/install/setup.sh PROJECT` |
| Start a session of a project | `kit start PROJECT` |
| See what a start would do, with no change | `kit start PROJECT --dry-run`, or `kit setup --dry-run` |
| See the sessions | `kit list` |
| Open a session, or stop it | `kit attach ID`, `kit kill ID` |
| Start each project with `"autostart": true` that has no session running | `kit autostart` |

`PROJECT` is a project of the config, a folder in your home folder (or in `AGENT_KIT_ROOT`), or `owner/name` of a
GitHub repository: `kit start` clones it when its folder is missing.

Each `kit start` is a new tmux session with a random ID, so several sessions of one project can run side by side.
A session continues the last conversation of its folder; `kit start PROJECT --new` begins a new one, and so does
`/clear` in the session. The session goes on after the terminal or the ssh connection is closed: `kit attach ID`
opens it again.

Each run of the set-up moves `~/.agent-kit` to the latest release (asked on a terminal) and prints the version, for
example `agent-kit v0.7.0 (1458c2d5)`; `--no-update` skips it. Claude Code is installed when it is missing and
updates itself. The log marks each step `✓` (done), `✗` (not done) or `-` (skipped) and ends with what was not done.
`kit setup --help` lists the keys.

## The keys of a start

They hold for that session only, are not written to the config, and win over the config and the agent.

| Key | Meaning |
|---|---|
| `--opus`, `--sonnet`, `--haiku`, `--fable` | The session's model. |
| `--low`, `--medium`, `--high`, `--xhigh`, `--max` | The session's effort. |
| `--window N` | The context window, for example `132k`; `default` takes the config's. |
| `--compact N` | The size the session compacts at (`compact_window`), in place of the context window. |
| `--agent NAME` | The session as the agent `NAME` (`dev`, `dev-eco`, `design`, `qa`, `spec`, `toolsmith`, or one of yours), in place of the project's `agent`. |
| `--plugin NAME` | One more plugin for the session; the key again for each. |
| `--new` | Begin a new conversation, in place of the last one of the folder. The earlier ones stay in `/resume`. |
| `--dry-run` | Print the session's config, its environment and its command line, and change nothing. |

Example: `kit start my-site --agent design --sonnet --high`

## The config

`~/.config/agent-kit/config.json` holds what each session gets. The first run copies the kit's defaults there
(`kit/defaults.json`); then the file is yours, and a field you leave out takes its default. Its groups:

- `session`: the fields of every session, such as `model`, `effort`, `subagent_model`, `context_window`,
  `remote_control`, `plugins` and `env`. By default the kit sets none of the model, the effort, the window, the
  agent, the tools or the system prompt: the session has Claude Code's own.
- `agents`: an agent is one description by its name: any of the session's fields, with its role (`role`, a
  Markdown file) and its plugins, such as `{"work": {"agent": "dev", "model": "opus", "system_prompt":
  "~/prompts/work.md"}}`; `agent` inside it is the agent it is built over. The kit has `dev`, `design`, `qa` and
  `spec` (`content/agents/NAME.json`). A project's field `agent` or `--agent NAME` takes one; the order is the defaults,
  `session`, the project, the agent, then the start's keys, and the plugins add up.
- `projects`: one entry for each project, with its `repo`, `folder` and `autostart`, and any session field that the
  project changes. `kit start` adds the entry of a new project. The old kit called it a profile, one file each;
  its old file is read once into the entry and kept.
- `user`: what the set-up writes into Claude Code's own `~/.claude/settings.json`, for every session of the user.

`version` says which of the kit's changes the file has had. When a release changes a field the file holds, the next
set-up or start brings the file up to date, keeps a value you wrote, and keeps the file as it was as
`config.json.vN`.

Each field, its default and how it reaches Claude Code: [docs/config.md](docs/config.md).

## Agents, skills and plugins

Each text has one place:

- An **agent** is the session's role: `dev`, `design`, `qa` or `spec` (the field `agent`, or `--agent NAME`);
  none by default. Its text is added to the system prompt.
- A **skill** is knowledge for one kind of work. It is loaded by a call of Skill, and is never in the prompt.
- A **plugin** is packaging only: a folder with an agent, its skills and its hooks. Each session has `agent-kit`
  (the kit's rules, the security skill, the gate of a command for the owner), the agent's plugin, and those of the
  field `plugins`.
- The **system prompt** is Claude Code's own by default. A profile's `system_prompt` names a Markdown file
  given in its place, then the agent's text; `system_prompt_append` names one added to it. The kit's rules are
  such a file: `content/plugins/agent-kit/system-prompt.md`. `kit start PROJECT --dry-run` prints the prompt.
  A plugin of the session adds its own lines: the `system-prompt.md` (the session and its subagents) and the
  `agent.md` (the session) in its folder, as `content/plugins/openspec` does.

OpenSpec is the plugin `openspec`: `"plugins": ["openspec"]` in a project's entry, or `--plugin openspec` for one
start. It brings the program and its skills; the session makes the project's `openspec/` folder with
`openspec init`.

What each plugin holds: [content/plugins/README.md](content/plugins/README.md).

### What a session of the kit's agents has

The kit's agents (`dev`, `design`, `qa`, `spec`, `toolsmith`) start with the kit's own system prompt in place of
Claude Code's, a short list of tools, the web tools for the subagents only (ask the subagent `web`), and a window
of 256 thousand tokens (133 thousand on haiku). `dev-eco` is `dev` at the least cost: on haiku, a window of 133
thousand, and only `Bash`, `Read`, `Edit`, `Write`, `Skill`, `Agent` and `ToolSearch`. Each is a field of the agent's file in `content/agents/`: `system_prompt`, `tools`,
`subagent_tools`, `context_window`; a project or an agent of yours sets its own over them.

### A tool of another developer

By default the kit does not limit a session's MCP servers or tools. A profile can: `tools` lists the built-in
tools, `mcp_servers` gives servers as in `.mcp.json` and `mcp_strict` makes them the only ones, `bundled_skills`
false or `bundled_skills_off` turns off Claude Code's bundled skills, `builtin_plugins_off` its built-in plugins
and `subagents_off` subagents by name, and `project_config` false leaves out what the
project's repository holds for Claude Code (its `.claude/` and `.mcp.json`; its `CLAUDE.md` is still read).
`kit mcp list` names the MCP servers of
Claude Code's own files, and `kit mcp remove NAME SCOPE` removes one by Claude Code's command. A tool of another
developer is connected in Claude Code's own ways:

- **A plugin**: put its folder (the one with `.claude-plugin/plugin.json`) in `~/.local/share/agent-kit/plugins/`,
  and name it in the field `plugins` or by `--plugin NAME`. Its skills, its MCP servers (`.mcp.json` of the plugin)
  and the programs in its `bin/` come into the session.
- **An MCP server of a project**: the project's own `.mcp.json`. Claude Code asks once whether to use it.
- **A program with its own installer**: install it as its developer says; the session finds it on the `PATH`.

A tool's installer and its servers run with your rights: read what you install.

The plugins also work without the kit: add this repository as a marketplace in Claude Code
(`claude plugin marketplace add`) and install them from it.

## Where the kit keeps its files

Nothing is written into a project's folder.

| Place | Content |
|---|---|
| `~/.agent-kit` | The copy of this repository. |
| `~/.local/bin/kit` | The command. |
| `~/.config/agent-kit/config.json` | The config; `config.json.vN`, the config as it was before a release changed it. |
| `~/.config/agent-kit/sessions/ID.json` | The config of one session, as it was started. `kit kill ID` removes it, and `kit list` that of a session gone. |
| `~/.config/agent-kit/sessions/ID.mcp.json` | The MCP servers of one session's profile, readable by you only. `kit kill ID` removes it. |
| `~/.config/agent-kit/kit.log` | One line for each start, kill and set-up of the kit's files, with each change whole. A key or a token is there only as its fingerprint. |
| `~/.claude.json`, `~/.claude/settings.json`, `~/.bashrc` | A few keys of Claude Code and the line that puts `~/.local/bin` on the `PATH`; the other keys and lines are kept. |

Read `kit.log` first when a session did not get what you expected.

## Good to know

- Claude Code needs about 1.2 GB free in the home folder to install; with less the set-up says so and does not start
  the installer.
- Without password-free sudo: on Debian and Ubuntu the packages go to the home folder; on Arch, CachyOS and Fedora
  the set-up prints the command for root and waits.
- The start at boot: the set-up writes your own unit `~/.local/share/systemd/user/kit-autostart.service`, which
  runs `kit autostart`. It runs at boot only when your user has linger; when it has not, the set-up says the one
  command for root, `loginctl enable-linger USER`. The kit has no script that root runs.
- With the key of the agents' GitHub App on the machine (`install/gh-app.sh key`), the sessions work on GitHub as the
  App, not as the person who signed in.
- The dashboard: `kit dashboard` runs a page of the projects and their sessions (start, stop, a console, the
  files) until Ctrl-C, on the machine's Tailscale address when it has one, else on 127.0.0.1, port 8765. From
  another device of the same Tailscale user it opens with no key; anyone else needs the key
  (`python3 dashboard/dash.py key`). It is a program beside the kit: a session runs the same with it off.
- Waiting outside the kit for now: the editor (code-server, VS Code), the telemetry, the set-up of Tailscale and
  the dev copy. The telemetry and the sessions' isolation are planned; neither is built yet.

## This repository

| Folder | Content |
|---|---|
| [install](install/) | `setup.sh`, the set-up of the machine in bash: the packages, the sign-ins, the GitHub App. |
| [kit](kit/) | The command `kit` in Python: the config, the session's plan, the start in tmux, the kit's files. |
| [content](content/) | What a session is made of: the agents (`agents/`) and our Claude Code plugins (`plugins/`). |
| [dashboard](dashboard/), [centre](centre/) | The page of one machine's sessions, and the page of several machines. |
| [tests](tests/) | The tests: `python3 -m unittest discover -s tests`; of the dashboard and the centre: `bash tests/NAME.test.sh`. |
| [docs](docs/) | The references: the fields of the config, the cost of the context. |

This repository is the version to install: the kit is developed elsewhere and comes here as a release.
