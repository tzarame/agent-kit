"""analyst.py - where the tokens leak, by fixed rules over Claude Code's conversation files. No model is asked.

A finding is {"rule", "folder", "session", "agent" (a subagent's file, or None), "at", "tokens", ...}: numbers and
names only, never a text of the conversation. The rules and their limits are the constants below; the reasons for
the numbers are in the change `local-analyst` (design.md)."""
import glob, hashlib, json, os

import costs

CACHE_LIFE = 3600        # seconds a cache entry lives; a pause longer than this is a cold start, not a miss
MISS_CONTEXT = 20000     # a call with less context than this, or after less, is not judged
MISS_READ = 0.5          # under this share of the kept context read from the cache, the call is a miss
BIG_RESULT = 10000       # tokens (estimated) of one tool result
COMPACT_CALLS = 16       # fewer calls than this between two compactions: the compaction did not pay for itself
NAME = 100               # characters kept of a tool's name
LOOP_CALLS = 3           # the same tool with the same input this many times in a row
SUBAGENT_SHARE = 0.5     # the subagents' share of a session's dollars
SUBAGENT_USD = 1.0       # ... judged only when the session spent at least this
RULES = ("cache_miss", "cold_start", "big_result", "compact_often", "tool_loop", "subagent_share")


def _size(content):
    """The estimated tokens of a tool result's content (a string, or blocks of text)."""
    if isinstance(content, list):
        content = "".join(b["text"] for b in content
                          if isinstance(b, dict) and isinstance(b.get("text"), str))
    return costs.est_tokens(content) or 0 if isinstance(content, str) else 0


def read(path):
    """One conversation file as a list of events in the file's order: ("call", ts, model, tokens),
    ("tool", ts, name, digest of the input), ("result", ts, tool name, tokens), ("compact", ts, trigger),
    ("turn", ts) for a message of the user.
    A reply written on several lines is one call. None when the file cannot be read."""
    events, seen, names, results = [], {}, {}, set()
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return None
    with f:
        for line in f:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            ts = costs._ts(d.get("timestamp"))
            if ts is None:
                continue
            kind = d.get("type")
            if kind == "system" and d.get("subtype") == "compact_boundary":
                meta = d.get("compactMetadata") if isinstance(d.get("compactMetadata"), dict) else {}
                events.append(("compact", ts, meta.get("trigger")))
                continue
            msg = d.get("message") if isinstance(d.get("message"), dict) else {}
            blocks = msg.get("content") if isinstance(msg.get("content"), list) else []
            blocks = [b for b in blocks if isinstance(b, dict)]
            if kind == "assistant" and isinstance(msg.get("usage"), dict):
                mid = msg.get("id") or len(events)
                call = ("call", ts, msg.get("model"), costs.tokens(msg["usage"]))
                if mid in seen:
                    events[seen[mid]] = call[:1] + (events[seen[mid]][1],) + call[2:]   # the last usage, the first time
                else:
                    seen[mid] = len(events)
                    events.append(call)
                for b in blocks:
                    if b.get("type") == "tool_use" and isinstance(b.get("name"), str):
                        b = dict(b, name=b["name"][:NAME])
                        names[b.get("id")] = b["name"]
                        text = json.dumps(b.get("input"), sort_keys=True, default=str)
                        events.append(("tool", ts, b["name"], hashlib.sha256(text.encode()).hexdigest()[:12]))
            elif kind == "user":
                if not any(b.get("type") == "tool_result" for b in blocks):
                    events.append(("turn", ts))
                for b in blocks:
                    if b.get("type") == "tool_result" and b.get("tool_use_id") not in results:
                        results.add(b.get("tool_use_id"))   # a result written twice is one result
                        events.append(("result", ts, names.get(b.get("tool_use_id")), _size(b.get("content"))))
    return events


def judge(events):
    """The findings of one file's events, without the place (the caller adds folder, session, agent)."""
    out = []
    last = None            # (ts, model, context) of the call before
    compacted = False      # a compaction since the call before
    since_compact = None   # calls since the last compaction; None before the first one
    run = None             # [tool, digest, count, ts]

    def loop_end():
        if run and run[2] >= LOOP_CALLS:
            out.append({"rule": "tool_loop", "at": run[3], "tokens": 0, "tool": run[0], "calls": run[2]})

    for e in events:
        if e[0] == "compact":
            if since_compact is not None and since_compact < COMPACT_CALLS:
                out.append({"rule": "compact_often", "at": e[1], "tokens": 0, "calls": since_compact})
            since_compact, compacted = 0, True
        elif e[0] == "result":
            if e[3] >= BIG_RESULT:
                out.append({"rule": "big_result", "at": e[1], "tokens": e[3], "tool": e[2]})
        elif e[0] == "turn":
            loop_end()          # the same call asked for again by the user is no loop
            run = None
        elif e[0] == "tool":
            if run and run[:2] == [e[2], e[3]]:
                run[2] += 1
            else:
                loop_end()
                run = [e[2], e[3], 1, e[1]]
        else:
            _, ts, model, tok = e
            written = tok["cache_write_5m"] + tok["cache_write_1h"]
            context = tok["input"] + written + tok["cache_read"]
            kept = min(last[2], context) if last else 0   # a context cut since the call before is no miss
            if last and ts < last[0]:
                continue        # written out of the order of time: not judged, and not the call before of the next
            pause = int(ts - last[0]) if last else 0
            if not compacted and kept >= MISS_CONTEXT and tok["cache_read"] < MISS_READ * kept:
                lost = kept - tok["cache_read"]   # lost: sent before, not read now
                if pause > CACHE_LIFE:
                    out.append({"rule": "cold_start", "at": ts, "tokens": lost, "pause": pause})
                else:
                    out.append({"rule": "cache_miss", "at": ts, "tokens": lost, "pause": pause,
                                "model_changed": model != last[1]})
            last, compacted = (ts, model, context), False
            if since_compact is not None:
                since_compact += 1
    loop_end()
    return out


def _at(sorted_values, share):
    """The value at this share of a sorted list (0.5 is the median); 0 for an empty one."""
    return sorted_values[min(len(sorted_values) - 1, int(share * len(sorted_values)))] if sorted_values else 0


def watch(files, since, until):
    """What the period's calls show, over the events of several files: the calls, the tokens of their context and
    the share of it read from the cache, the context of one call (the median and the 90th percentile), the calls
    made for one message of the user (the mean, the median, the 90th percentile), and the compactions: asked by the
    user, after a pause longer than the cache's life, or in the course of the work."""
    contexts, read, turns = [], 0, []
    compactions = {"work": 0, "pause": 0, "manual": 0}
    for events in files:
        last, run = None, 0
        for e in events + [("turn", 0)]:
            if e[0] == "turn":
                if run:
                    turns.append(run)
                run = 0
            elif e[0] == "call":
                last = e[1]
                if since <= e[1] <= until:
                    run += 1
                    tok = e[3]
                    contexts.append(tok["input"] + tok["cache_write_5m"] + tok["cache_write_1h"] + tok["cache_read"])
                    read += tok["cache_read"]
            elif e[0] == "compact" and since <= e[1] <= until:
                kind = "manual" if e[2] == "manual" else "pause" if last and e[1] - last > CACHE_LIFE else "work"
                compactions[kind] += 1
    contexts.sort()
    turns.sort()
    return {"calls": len(contexts), "context": sum(contexts), "cache_read": read,
            "turns": len(turns), "turn_calls": round(sum(turns) / len(turns), 1) if turns else None,
            "turn_median": _at(turns, 0.5), "turn_p90": _at(turns, 0.9),
            "read_share": round(read / sum(contexts), 3) if sum(contexts) else None,
            "context_median": _at(contexts, 0.5), "context_p90": _at(contexts, 0.9), "compactions": compactions}


def report(projects_dir, since, until, folder=None, answers=None):
    """The findings of the period, the newest first, and their count and tokens by rule.
    answers: file name -> a model's kept answer (analyst_ask.answers); a finding with one gets it as "answer"."""
    prices = costs.load_prices()
    found, files = [], []
    names = sorted(os.listdir(projects_dir)) if os.path.isdir(projects_dir) else []
    for name in names:
        fdir = os.path.join(projects_dir, name)
        if (folder and name != folder) or not os.path.isdir(fdir):
            continue
        usd = {}            # session -> [main, subagents]
        mains = glob.glob(os.path.join(glob.escape(fdir), "*.jsonl"))
        subs = glob.glob(os.path.join(glob.escape(fdir), "*", "subagents", "*.jsonl"))
        for path in sorted(mains) + sorted(subs):
            if os.path.getmtime(path) < since:
                continue
            events = read(path)
            if events is None:
                continue
            files.append(events)
            sub = path in subs
            base = os.path.basename(path)[:-len(".jsonl")]
            session = os.path.basename(os.path.dirname(os.path.dirname(path))) if sub else base
            for e in events:
                if e[0] == "call" and since <= e[1] <= until:
                    usd.setdefault(session, [0.0, 0.0])[sub] += costs._usd(e[3], e[2], prices) or 0.0
            for f in judge(events):
                if since <= f["at"] <= until:
                    found.append(dict(f, folder=name, session=session, agent=base if sub else None))
        for session, (main, part) in sorted(usd.items()):
            if main + part >= SUBAGENT_USD and part > SUBAGENT_SHARE * (main + part):
                found.append({"rule": "subagent_share", "folder": name, "session": session, "agent": None,
                              "at": until, "tokens": 0, "share": round(part / (main + part), 2),
                              "usd": round(main + part, 2)})
    for f in found:
        got = (answers or {}).get("%s-%d-%s.json" % (f["agent"] or f["session"], int(f["at"]), f["rule"]))
        if got:
            f["answer"] = got.get("answer") or "no answer: " + got.get("error", "")
    found.sort(key=lambda f: (-f["at"], f["rule"], f["session"]))
    rules = {r: {"count": 0, "tokens": 0} for r in RULES}
    for f in found:
        rules[f["rule"]]["count"] += 1
        rules[f["rule"]]["tokens"] += f["tokens"]
    return {"since": since, "until": until, "rules": rules, "findings": found, "watch": watch(files, since, until)}
