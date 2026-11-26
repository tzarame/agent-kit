"""kit: the launcher of agent-kit. The parts depend one way: __main__ -> cli -> sessions (kit start, run, list,
attach, kill) and machine (the set-up's files) -> plan and io (the files, the processes, the clock) -> old (the old
kit's project files) -> quoted (bash's KEY=VALUE words) -> config -> files (a file written whole) and defaults.json."""
