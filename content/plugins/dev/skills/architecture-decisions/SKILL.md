---
name: architecture-decisions
description: How to make, record and enforce an architecture decision - a choice that is costly to reverse, such as a style, a technology, a boundary or a data store. Use when choosing, recording, changing or enforcing such a decision, or when asking an AI about one or reviewing its answer.
---

Get the business goals and constraints first. A good design for the wrong problem is still wrong.
Name every option and what each one costs, including the costs that appear later. Do not present one option as obviously best.
Weigh the criteria by this project's priorities. A plain count of advantages can pick the wrong option.
Choose a technology by criteria. Name a product only when a required quality needs it.
Prototype the open options against real constraints when the answer depends on facts you do not have yet.
Write each decision down: the context, the options rejected and why, and the known limits. A decision that is not written down gets argued again, forgotten, or quietly reversed.
Never edit an accepted decision in place. Write a new record that supersedes it and link the two.
Send a decision with cross-team, cost or security impact to whoever approves such changes, before building it.
Turn each recorded decision into an automated check that fails the build. A written rule alone erodes.
Redo the analysis when the context changes. An old choice is not permanent.
A generic best-practice answer, including one from an AI model, is a hypothesis: the model does not have this project's context. Use a model to list the trade-offs and risks you may have missed, not to pick the option, and check its answer against this project's facts.
