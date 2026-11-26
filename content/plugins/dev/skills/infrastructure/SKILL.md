---
name: infrastructure
description: What runs and where - servers, containers, networks, DNS, CI/CD, deployment, databases in operation, cloud resources, backups, monitoring. Use when installing, configuring, deploying or changing something that runs.
---

Before you touch a thing, find out what is running and who depends on it.
Make the change in code and configuration kept in the repository, not by hand: then it can be repeated and reverted.
One change at a time, and a check after each. Know how to roll back before you start.

Check which machine and which environment you are on. Before anything that deletes, restarts or changes access, show the user the command and ask. Make sure a backup exists and can be restored.
