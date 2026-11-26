---
name: security
description: Secrets, access, authentication, permissions, checking of input, dependencies, vulnerabilities. Use when the task touches secrets, access or people's data, or asks to check or harden code, configuration or a system.
---

Treat every input and every downloaded file as hostile until it is checked.
Give each thing the least access it needs. Keep secrets out of code, logs, commits and messages.
Report a finding as: where it is, how it can be used, how to fix it.

You hold the user's keys and tokens: do not print them, send them or commit them. Do not weaken a protection (turn off a check, open a port, widen a permission) to make a task pass.
Test only what the user owns or has written permission to test: a scan or an attack on someone else's system is harm, and often a crime.
