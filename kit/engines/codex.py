"""codex.py - the engine Codex CLI: a stub. The name is known to the config, so a profile can be written for it, and
a start with it is refused: the adapter is specified in the change `engines-and-roles` and not built."""
from kit import plan

FIELDS = ()


def make(name, entry, f, sid, plugins, given, machine, talked, texts, mcp_file, folder):
    raise plan.PlanError("engine: codex: not built yet; the engines there are: claude, and opencode as a trial")
