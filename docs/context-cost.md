# The cost of the context: a reference

What an agent's context costs in Claude Code, what changes the cost, and what the kit does about it. The
numbers here are from measurements on the kit's own sessions. Facts of Claude Code are from its documentation as
read on 24 November 2026 (version 2.1.331):
<https://code.claude.com/docs/en/prompt-caching.md>.

## How a call is paid

Every call sends the whole conversation: the tool definitions and the system prompt, the project context
(CLAUDE.md, memory), then every message and tool result. The model keeps nothing between calls.

A call has tokens of four kinds, and each kind has its own price. Here a cost is always written as the tokens of
each kind first, and then in **units**: one unit is the price of one input token with no cache.

| Kind of tokens | Units for one token |
|---|---|
| Input read from the cache | 0.1 |
| Input written to the cache, life of five minutes | 1.25 |
| Input written to the cache, life of an hour | 2 |
| Input with no cache | 1 |
| Output | 5 |

The ratios are of the public API prices; how a subscription counts them is not known here, and is assumed the
same. An ordinary call of a main agent here: about 70 thousand tokens read, 2 thousand written, under one
thousand of output: about 15 thousand units.

## How the cache works

- The cache holds the **start** of a request. The match is exact: a change anywhere recomputes all that follows
  it. There is no cache by file or by piece.
- The order is fixed: tools and system prompt, project context, conversation. What changes least is first.
- On an ordinary call the border is the end of the call before: all before it is read, the new end (the last
  reply, the tool results, the new message) is written.
- A read renews the entry's life. The life is five minutes or an hour, nothing else, and Claude Code places the
  borders itself: neither can be set by hand, only the life chosen (`promptCacheTtl`, `subagentPromptCacheTtl`).
- On a subscription within the plan's usage the main conversation gets an hour; subagents, workflows, forks and
  the compaction get five minutes. Measured: so it is.
- Each model has its own cache. The cache is in effect of one machine and one folder.

## What loses the cache

- A pause longer than the life: the next call writes the whole context anew.
- Another model (14 of 17 misses in a week here). A skill or command that names a model is such a switch.
- A changed set of tool definitions: an MCP server connected or a whole tool denied, when tools are loaded at
  the start. With deferred tools (the default) the list of the first call is kept. A plugin's skills, agents
  and hooks turned on or off keep the cache: they are added at the end.
- A compaction: the conversation and the project context are written anew, the system prompt is still read.
- An upgrade of Claude Code, for the first conversation after the restart. Old images removed from a long
  conversation.

## What keeps it

Editing files, editing CLAUDE.md in a session (it is read at the start only), a change of the permission mode or
the output style, a skill or a command loaded (it is added at the end), `/rewind`, a subagent started, a change of
effort on the present models. A session resumed keeps its system prompt and reads what is unchanged and alive.

## What it means for the money

- **The start is paid on every call.** Ten thousand tokens at the start are one thousand on each call, about 7%
  of a call here. Put there only what is needed nearly always; load the rest on demand (skills, deferred tools).
  Warming the cache with what may be needed later costs on every call and saves nothing.
- **A large one-time text belongs in a subagent**: a web page, a file read only for a conclusion. It then never
  enters the main context, and only the answer does. A file the agent edits must be in its own context.
- **A skill can be given to a subagent** (`skills:` in the agent's file, or `context: fork` in the skill): a
  reviewer or an adviser carries a large skill, and the main context gets its answer.
- **A subagent's cache lives five minutes.** One continued after a longer pause writes its context anew.
- **A compaction** at a context of 97 thousand tokens:

  | Step | Tokens | Kind | Units |
  |---|---|---|---|
  | The summary call reads the context | 97 thousand | input, read from the cache | 10 thousand |
  | It writes the summary | 8 thousand | output | 40 thousand |
  | The next call writes the new context | 25 thousand | input, written to the cache | 31 to 50 thousand |

  81 to 100 thousand units in all. It then saves 5 thousand units a call, so it pays back in 16 to 19 calls. It
  is cheap only while the cache is alive: with no cache the first step is 97 thousand units, not 10. It runs on
  the session's model, and no setting names another.
- **Clearing** (`/clear`) reads about 11 thousand tokens from the cache (1 thousand units) and leaves a context
  of that size; it loses all the agent learned. Clear when the task is done or changed; compact when the same task goes on.
- **After a pause over an hour**, with a context of 98 thousand tokens: to go on writes them all anew, 196
  thousand units; to compact then is 190 to 250 thousand units and pays back when many calls follow; to clear is
  about 20 thousand units. So a new task: clear; the same task: go on or compact. Best is a compaction before the hour ends, which Claude Code does itself.

## The settings

What each does and when it is needed. The kit's own fields are in `docs/config.md`.

| Setting | What it does | When it is needed | Limits |
|---|---|---|---|
| `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, `autoCompactWindow` (the kit: `context_window`) | The window; the compaction comes when the used context is 33 thousand under it | When the context grows fast or the model is cheap and weak with a long context: a smaller window keeps each call cheap. Too small, and compactions cost more than they save | 100000 or more |
| `--autocompact N` (the kit: `compact_window`) | The same, but `/autocompact` in the session can change it | When the person in the session is to choose | the same |
| `idleCompaction` (the kit: `idle_compact`) | Compacts a session about an hour after its last request, while the cache lives | Always, where sessions are left and come back: leave it on | on by default; needs a cache of an hour |
| `CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS` (the kit: `idle_compact_from`, 100000) | The used context from which the idle compaction applies | Lower it to 100000: most costly returns here had a context of 100 to 200 thousand | default 200000, 100000 at least |
| `promptCacheTtl` (the kit: `cache_life`) | The life of the main conversation's cache | `5m` only for an agent that works alone with no pause over five minutes; else leave the hour | `5m` or `1h` |
| `subagentPromptCacheTtl` (the kit: `subagent_cache_life`); in one agent's file `experimental.cacheTtl` | The life of the cache of subagents, forks and the compaction | `1h` only when subagents are often continued after more than five minutes (not measured yet) | `5m` or `1h` |
| `CLAUDE_CODE_SUBAGENT_MODEL` (the kit: `subagent_model`) | The subagents' model by default | A cheap model for steps that copy and run; a step with a decision names a stronger one | |
| A `PreCompact` hook | Its output is instructions for the summary | When a compaction loses something the work needs (the task list, the open files) | cannot start a compaction |

- The threshold of the auto-compaction is the size of the **used** context at which it comes, not the free part.
  By calculation, with a growth of 2 thousand a call the best is about 100 thousand; 85 to 125 is within 5%.
- The idle compaction cannot run when the auto-compaction comes under 100 thousand (a window of 132 thousand
  compacts at 99). Where it ran, a return wrote 49 thousand tokens in place of 314 thousand.
- A life of five minutes for the main conversation is about a tie on a machine where the agent works alone
  with few pauses (47.4 against 49.7 million in 8 days here) and loses where a person answers every 10 to 20
  minutes. A wait of over five minutes for a tool or a subagent is such a pause too.

## Decided (in `spend-optimisation`)

- The idle threshold goes down to 100 thousand on every machine.
- The small window (about 140 thousand) stays for subagents on the cheap model only; the main agent's window is
  chosen by the research.
- No warming of an idle session: the returns after a pause are about 3% of the cost.
