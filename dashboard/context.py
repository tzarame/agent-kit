"""context.py - the context size of an agent (PLAN.md section 5): the usage of the last reply that is not a
subagent's, in the newest conversation of the agent's folder. Claude Code keeps the conversations in
~/.claude/projects/ with each character that is not a letter or a digit turned into '-'. The file is read from its
end, a block at a time: it is never loaded whole."""
import glob, json, os, re

BLOCK = 64 * 1024
MAX_SCAN = 8 * 1024 * 1024
KEYS = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def _lines_backwards(f, size):
    pos, tail, scanned = size, b"", 0
    while pos > 0 and scanned < MAX_SCAN:
        step = min(BLOCK, pos)
        pos -= step
        f.seek(pos)
        chunk = f.read(step)
        scanned += step
        parts = (chunk + tail).split(b"\n")
        tail = parts[0]
        for line in reversed(parts[1:]):
            yield line
    if pos == 0:
        yield tail


def tokens(home, folder):
    """{"tokens": n, "time": mtime of the conversation} or None when there is no reply to read"""
    if not folder or not os.path.isdir(folder):
        return None
    d = os.path.join(home, ".claude", "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(folder)))
    files = glob.glob(os.path.join(glob.escape(d), "*.jsonl"))
    if not files:
        return None
    newest = max(files, key=os.path.getmtime)
    with open(newest, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        for raw in _lines_backwards(f, size):
            if b'"usage"' not in raw:
                continue
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            msg = rec.get("message") if isinstance(rec, dict) else None
            if not isinstance(rec, dict) or rec.get("type") != "assistant" or rec.get("isSidechain"):
                continue
            usage = msg.get("usage") if isinstance(msg, dict) else None
            if not isinstance(usage, dict):
                continue
            try:
                n = sum(int(usage.get(k) or 0) for k in KEYS)
            except (TypeError, ValueError):
                continue
            if n:
                return {"tokens": n, "time": int(os.path.getmtime(newest))}
    return None
