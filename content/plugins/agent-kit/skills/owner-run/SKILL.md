---
name: owner-run
description: How to give the owner a command to run himself - a shell command, a piece of configuration, a step with rights (sudo, sign-in, settings). Use whenever the owner, not you, is to run something.
---
A command for the owner never goes into the chat by hand. It is a script with its rollback, reviewed in a sandbox, and
the owner gets one line from the gate `owner-run`, which works the same in bash, zsh, fish and PowerShell.
It counts: anything the owner is to carry out, on this machine or over ssh. It does not count: what you run yourself,
an example in an explanation not meant to be run, code in the repository (it has its own review).

1. Write `run.sh` and `rollback.sh` in a new folder of the scratchpad. In `run.sh` the headers:
   `# owner-run-goal: TEXT`; `# owner-run-file: ~/PATH` for each file it changes; `# owner-run-ro: ~/PATH` for a
   folder it only reads; `# owner-run-user: root` only when it needs root.
   `run.sh` saves the state before into `$OWNER_RUN_SAVE`, writes a new file and then moves it, is safe to run twice.
   `rollback.sh` checks the state is the one `run.sh` left, refuses otherwise, and puts the saved state back.
2. `owner-run stage NAME DIR`. With no `bwrap` it refuses: tell the owner to install the package `bubblewrap`.
3. Give the review to the subagent `owner-review` (it runs on `sonnet`, `medium`): the name, the goal, the facts of
   the machine, not your view of the script. Only it can run `owner-run approve`.
4. When it refuses, fix the script, stage it again, review again.
5. `owner-run cmd NAME` prints the line, and a second one for a shell with no `||`. Give them as printed, in a code
   block. Say nothing of the review unless it found a risk that stays.

The owner's run prints `OK` or `FAILED` and the line to undo it; the rollback is kept in
`~/.local/share/agent-kit/owner-run/rollback/`, and the kit never deletes it. A root step is refused by `cmd` until
the root side of the gate is installed.
