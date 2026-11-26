#!/usr/bin/env bash
# tests/dashboard-analyst.test.sh - dashboard/analyst.py: where the tokens leak, by fixed rules.
# Made-up conversation files in a temp folder; the real ~/.claude/projects is never read. HOME is a temp folder too.
# Exit 0 when every case passes.
REPO=$(cd "$(dirname "$0")/.." && pwd -P)
T=$(mktemp -d) || exit 1; T=$(cd "$T" && pwd -P); trap 'rm -rf "$T"' EXIT
export HOME="$T/home"; mkdir -p "$HOME" || exit 1
cat > "$T/case.py" <<'PY'
import datetime, json, os, sys
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(sys.argv[1], "dashboard"))
import analyst

P = os.path.join(sys.argv[2], "projects")
SINCE, UNTIL = 1780000000, 1780172800
OPUS, HAIKU = "claude-opus-5-20260101", "claude-haiku-5-20260101"
fails = []

def want(name, ok):
    if not ok:
        fails.append(name)
    print(("ok   - " if ok else "FAIL - ") + name)

def iso(n):
    return datetime.datetime.fromtimestamp(SINCE + n, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

def call(mid, at, read=0, written=0, model=OPUS, tools=()):
    """A reply at second `at` with that much context read from the cache and written to it."""
    blocks = [{"type": "tool_use", "id": i, "name": n, "input": inp} for i, n, inp in tools] or [{"type": "text", "text": "SECRET"}]
    return {"type": "assistant", "timestamp": iso(at), "message": {"id": mid, "model": model, "content": blocks,
            "usage": {"input_tokens": 2, "output_tokens": 10, "cache_read_input_tokens": read,
                      "cache_creation_input_tokens": written}}}

def result(tid, at, chars):
    return {"type": "user", "timestamp": iso(at), "message": {"content": [
        {"type": "tool_result", "tool_use_id": tid, "content": [{"type": "text", "text": "x" * chars}]}]}}

def said(at):
    """A message of the user at second `at`."""
    return {"type": "user", "timestamp": iso(at), "message": {"content": "do it"}}

def compact(at, trigger=None):
    return dict({"type": "system", "subtype": "compact_boundary", "timestamp": iso(at)},
                **({"compactMetadata": {"trigger": trigger}} if trigger else {}))

def write(rel, items):
    p = os.path.join(P, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("not json\n")
        for it in items:
            f.write(json.dumps(it) + "\n")

def rules(items):
    return [f["rule"] for f in analyst.judge(analyst.read(write("-t/one.jsonl", items) or os.path.join(P, "-t/one.jsonl")))]

K = 1000
# the cache
want("a warm call is no finding", rules([call("a", 0, 0, 80 * K), call("b", 60, 80 * K, K)]) == [])
want("the first call of a file is no finding", rules([call("a", 0, 0, 80 * K)]) == [])
got = analyst.judge(analyst.read(os.path.join(P, "-t/one.jsonl")) if rules([call("a", 0, 0, 80 * K), call("b", 60, 0, 81 * K)]) else [])
want("nothing read after a short pause is a miss, with the tokens sent before and not read",
     [(f["rule"], f["tokens"], f["pause"], f["model_changed"]) for f in got] == [("cache_miss", 80 * K + 2, 60, False)])
want("a miss with another model says the model changed",
     analyst.judge(analyst.read(os.path.join(P, "-t/one.jsonl")) if rules([call("a", 0, 0, 80 * K), call("b", 60, 0, 80 * K, HAIKU)]) else [])[0]["model_changed"] is True)
want("nothing read after a pause over an hour is a cold start, not a miss",
     rules([call("a", 0, 0, 80 * K), call("b", 3700, 0, 80 * K)]) == ["cold_start"])
want("the first call after a compaction is no miss",
     rules([call("a", 0, 0, 80 * K), compact(10), call("b", 20, 0, 40 * K)]) == [])
want("a context cut and read whole from the cache is no miss",
     rules([call("a", 0, 0, 90 * K), call("b", 5, 40 * K, K)]) == [])
want("a small context is not judged", rules([call("a", 0, 0, 10 * K), call("b", 5, 0, 10 * K)]) == [])
want("a reply written on two lines is one call",
     rules([call("a", 0, 0, 80 * K), call("b", 60, 80 * K, K), call("b", 61, 80 * K, K)]) == [])
# the results
big = [call("a", 0, tools=[("t1", "Read", {"f": 1})]), result("t1", 1, 4 * analyst.BIG_RESULT), result("t1", 2, 4 * analyst.BIG_RESULT)]
got = analyst.judge(analyst.read(os.path.join(P, "-t/one.jsonl")) if rules(big) else [])
want("a result over the limit is found once, with its tool and size",
     [(f["rule"], f["tool"], f["tokens"]) for f in got] == [("big_result", "Read", analyst.BIG_RESULT)])
want("a result under the limit is no finding",
     rules([call("a", 0, tools=[("t1", "Read", {})]), result("t1", 1, 4 * analyst.BIG_RESULT - 4)]) == [])
# the compactions
often = [compact(0)] + [call("c%d" % i, i + 1) for i in range(analyst.COMPACT_CALLS - 1)] + [compact(100)]
want("a second compaction after too few calls is found", rules(often) == ["compact_often"])
want("the first compaction and one after enough calls are no finding",
     rules([call("z", 0), compact(1)] + [call("c%d" % i, i + 2) for i in range(analyst.COMPACT_CALLS)] + [compact(100)]) == [])
# the loops
loop = [call("l%d" % i, i, tools=[("t%d" % i, "Bash", {"command": "ls"})]) for i in range(3)]
got = analyst.judge(analyst.read(os.path.join(P, "-t/one.jsonl")) if rules(loop) else [])
want("the same call three times in a row is a loop", [(f["rule"], f["tool"], f["calls"]) for f in got] == [("tool_loop", "Bash", 3)])
want("three calls with different input are no loop",
     rules([call("l%d" % i, i, tools=[("t%d" % i, "Bash", {"command": str(i)})]) for i in range(3)]) == [])
want("the same call in three turns of the user is no loop",
     rules([x for i in range(3) for x in (call("l%d" % i, i, tools=[("t%d" % i, "Bash", {"command": "ls"})]),
            {"type": "user", "timestamp": iso(i), "message": {"content": "again"}})]) == [])
want("a call written before the call above it in time is not judged",
     rules([call("a", 100, 0, 90 * K), call("b", 50, 100, 90 * K)]) == []
     and rules([call("a", 3650, 0, 90 * K), call("b", 0, 0, 90 * K), call("c", 3660, 0, 90 * K)]) == ["cache_miss"])
want("a tool's name is cut", len(analyst.judge(analyst.read(os.path.join(P, "-t/one.jsonl")) if rules(
     [call("a", 0, tools=[("t1", "N" * 500, {})]), result("t1", 1, 4 * analyst.BIG_RESULT)]) else [])[0]["tool"]) == analyst.NAME)

# the report: folders, sessions, subagents, the period
os.remove(os.path.join(P, "-t/one.jsonl"))
write("-a/s1.jsonl", [call("a", 0, 0, 80 * K), call("b", 60, 0, 80 * K), call("c", -500, 0, 80 * K)])
write("-a/s1/subagents/agent-1.jsonl", [call("d", 0, 0, 2000 * K), call("e", 30, 0, 2000 * K)])
write("-b/s2.jsonl", [call("f", 0, 0, 80 * K), call("g", 4000, 0, 80 * K)])
r = analyst.report(P, SINCE, UNTIL)
w = r["watch"]
want("the report says what the calls show", (w["calls"], w["context"], w["cache_read"], w["read_share"]) ==
     (6, 6 * 2 + 4 * 80 * K + 2 * 2000 * K, 0, 0.0) and (w["context_median"], w["context_p90"]) == (80 * K + 2, 2000 * K + 2))
write("-w/s3.jsonl", [call("a", 0, 30 * K, 10 * K), compact(10, "auto"), call("b", 20, 0, 40 * K), compact(4000, "auto"),
                      call("c", 4010, 30 * K, 10 * K), compact(4020, "manual"), compact(4030)])
w = analyst.report(P, SINCE, UNTIL, "-w")["watch"]
want("the compactions are counted by their cause: in the work, after a pause, asked",
     w["compactions"] == {"work": 2, "pause": 1, "manual": 1} and w["read_share"] == round(60 * K / (120 * K + 6), 3))
want("a period with no call has no share", analyst.report(P + "-none", SINCE, UNTIL)["watch"]["read_share"] is None)
write("-w/s3.jsonl", [said(0), call("a", 1), call("b", 2), call("c", 3), said(10), call("d", 11), said(20), said(30),
                      call("e", 31, tools=[("t1", "Read", {})]), result("t1", 32, 10), call("f", 33), call("g", -900)])
w = analyst.report(P, SINCE, UNTIL, "-w")["watch"]
want("the calls made for one message of the user: the mean, the median, the 90th percentile; a tool's result is no message",
     (w["turns"], w["turn_calls"], w["turn_median"], w["turn_p90"]) == (3, 2.0, 2, 3))
want("a period with no call has no calls for a message", analyst.report(P + "-none", SINCE, UNTIL)["watch"]["turn_calls"] is None)
os.remove(os.path.join(P, "-w/s3.jsonl"))
want("the report counts by rule", (r["rules"]["cache_miss"]["count"], r["rules"]["cold_start"]["count"],
     r["rules"]["subagent_share"]["count"], r["rules"]["tool_loop"]["count"]) == (2, 1, 1, 0))
want("a finding names its folder, session and the subagent's file",
     sorted((f["folder"], f["session"], f["agent"] or "") for f in r["findings"] if f["rule"] == "cache_miss")
     == [("-a", "s1", ""), ("-a", "s1", "agent-1")])
share = [f for f in r["findings"] if f["rule"] == "subagent_share"]
want("the subagents' share of a session's money is found", share and share[0]["session"] == "s1" and share[0]["share"] > 0.9)
want("the newest finding is first", [f["at"] for f in r["findings"]] == sorted((f["at"] for f in r["findings"]), reverse=True))
want("one folder alone", {f["folder"] for f in analyst.report(P, SINCE, UNTIL, "-b")["findings"]} == {"-b"})
want("a finding out of the period is left out", analyst.report(P, SINCE + 100, UNTIL)["rules"]["cache_miss"]["count"] == 0)
want("no text of a conversation is in the answer", "SECRET" not in json.dumps(r) and "xxxx" not in json.dumps(r))
want("a folder that is not there gives an empty answer", analyst.report(P + "-none", SINCE, UNTIL)["findings"] == [])

# the model for one finding: a fake claude on the PATH, a fake start of the detached run
import analyst_ask, subprocess, time
HOME = os.path.join(sys.argv[2], "home")
BIN = os.path.join(sys.argv[2], "bin"); os.makedirs(BIN)
with open(os.path.join(BIN, "claude"), "w") as f:
    f.write('#!/bin/bash\nprintf "%s\\n" "$AGENT_KIT_ANALYST" "$PWD" "$@" > "$FAKE_OUT"; cat >> "$FAKE_OUT"; echo "the answer"\n')
os.chmod(os.path.join(BIN, "claude"), 0o755)
os.environ["PATH"] = BIN + ":" + os.environ["PATH"]; os.environ["FAKE_OUT"] = os.path.join(sys.argv[2], "fake.out")
NOW = SINCE + 100
miss = [call("a", 0, 0, 80 * K, tools=[("t1", "Bash", {"command": "A" * 900})]), result("t1", 1, 900), call("b", 60, 0, 81 * K)]
write("-h/s9.jsonl", miss)
FILE = os.path.join(P, "-h/s9.jsonl")
started = []
spawn = lambda argv, **kw: started.append((argv, kw))
hook = lambda env=None, now=NOW, path=FILE: analyst_ask.hook(json.dumps({"transcript_path": path}), HOME, env or {}, now, spawn)
want("the analyst's own run starts nothing", hook({"AGENT_KIT_ANALYST": "1"}) is None and not started)
want("a hook input with no file starts nothing", hook(path="/nonexistent.jsonl") is None and analyst_ask.hook("x", HOME, {}, NOW, spawn) is None)
argv = hook()
want("a new miss starts one detached run with the guard set", argv and argv[-3:] == [FILE, repr(float(SINCE + 60)), "cache_miss"]
     and len(started) == 1 and started[0][1]["start_new_session"] and started[0][1]["env"]["AGENT_KIT_ANALYST"] == "1")
want("the same finding is not asked twice, nor a second one within the hour", hook() is None and hook(now=NOW + 4000) is None)
write("-h/s8.jsonl", [call("a", 0, 0, 80 * K), call("b", 60, 0, 81 * K, HAIKU)])
want("a miss with a changed model is not asked about", hook(path=os.path.join(P, "-h/s8.jsonl")) is None)
write("-h/s7.jsonl", miss)
want("with no state, an old finding is not asked about", hook(now=NOW + 5000, path=os.path.join(P, "-h/s7.jsonl")) is None)
got = analyst_ask.ask(FILE, float(SINCE + 60), "cache_miss", HOME)
sent = open(os.environ["FAKE_OUT"]).read()
want("the answer is kept in a file of the owner alone", got.get("answer") == "the answer"
     and os.stat(os.path.join(analyst_ask.answers_dir(HOME), "s9-%d-cache_miss.json" % (SINCE + 60))).st_mode & 0o77 == 0)
want("the model runs with the guard, outside the project, with no tools and no kept session",
     sent.splitlines()[0] == "1" and sent.splitlines()[1] == analyst_ask.state_dir(HOME)
     and "--no-session-persistence" in sent and "--tools\n\n" in sent and "\nhaiku\n" in sent)
want("the lines sent are cut short", "tool Bash" in sent and "A" * 301 not in sent and "x" * 301 not in sent and "cache_read=0" in sent)
write("-h/s6.jsonl", [{"type": "user", "timestamp": iso(0), "message": {"content": [{"type": "text", "text": "b\nb \ud83d"}] * 200}},
                      {"type": "system", "subtype": "S" * 5000, "timestamp": iso(1)}])
lines = analyst_ask.cut(os.path.join(P, "-h/s6.jsonl"), SINCE + 60)
want("a line sent is one line of valid text under the limit", len(lines) == 2 and all(len(l) <= analyst_ask.LINE and "\n" not in l for l in lines)
     and "\n".join(lines).encode("utf-8"))
r = analyst.report(P, SINCE, UNTIL, "-h", analyst_ask.answers(HOME))
want("the report joins the answer to its finding", [f.get("answer") for f in r["findings"] if f["session"] == "s9"] == ["the answer"])
os.environ["PATH"] = "/nonexistent"
want("with no claude the error is kept, and nothing is raised", "error" in analyst_ask.ask(FILE, float(SINCE + 60), "cache_miss", HOME))

if fails:
    print("\n".join(fails))
sys.exit(1 if fails else 0)
PY
out=$(python3 -I "$T/case.py" "$REPO" "$T" 2>&1); rc=$?
echo "$out"
PASS=$(printf '%s\n' "$out" | grep -c '^ok   - ')
FAIL=$(printf '%s\n' "$out" | grep -c '^FAIL - ')
[ "$rc" = 0 ] || [ "$FAIL" != 0 ] || FAIL=1
echo "passed $PASS, failed $FAIL"; [ "$FAIL" = 0 ]
