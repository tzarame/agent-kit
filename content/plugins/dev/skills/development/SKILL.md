---
name: development
description: Writing and changing code - a feature, a bug fix, a refactoring, tests, a script. Use when the task is to write, change, debug or review code.
---

Read the code around the change first and write in its style: the same names, structure and libraries.
Make the smallest change that solves the task. Do not rewrite what was not asked.
Check the result by running it: the tests, or the code itself. Say plainly what was run and what was not.

Deleting files, `git reset --hard`, a forced push, a migration, an upgrade of dependencies, a script run on real data: each can destroy the user's work.
