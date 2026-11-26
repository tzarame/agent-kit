#!/usr/bin/env bash
# tests/dashboard-costs.test.sh - dashboard/costs.py: what agents and subagents spent (PLAN.md "Costs").
# Made-up conversation files in a temp folder; the real ~/.claude/projects is never read. HOME is a temp folder too.
# Exit 0 when every case passes.
REPO=$(cd "$(dirname "$0")/.." && pwd -P)
T=$(mktemp -d) || exit 1; T=$(cd "$T" && pwd -P); trap 'rm -rf "$T"' EXIT
export HOME="$T/home"; mkdir -p "$HOME" || exit 1
cat > "$T/case.py" <<'PY'
import datetime, json, os, sys
sys.path.insert(0, os.path.join(sys.argv[1], "dashboard"))
import costs

T = sys.argv[2]
P = os.path.join(T, "projects")
SINCE, UNTIL = 1780000000, 1780172800   # the period: two days
fails = []

def want(name, ok):
    if not ok:
        fails.append(name)
    print(("ok   - " if ok else "FAIL - ") + name)

def iso(n):
    return datetime.datetime.fromtimestamp(SINCE + n, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

def U(i=0, o=0, r=0, w=0, w5=None, w1=None):
    """A usage block: input, output, cache read, cache write; w5/w1 is the 5m/1h split when given."""
    d = {"input_tokens": i, "output_tokens": o, "cache_read_input_tokens": r, "cache_creation_input_tokens": w}
    if w5 is not None:
        d["cache_creation"] = {"ephemeral_5m_input_tokens": w5, "ephemeral_1h_input_tokens": w1}
    return d

def asst(mid, model, usage, at, branch=None, text="ok"):
    d = {"type": "assistant", "timestamp": iso(at), "sessionId": "x", "isSidechain": False,
         "message": {"id": mid, "model": model, "role": "assistant", "content": [{"type": "text", "text": text}],
                     "usage": usage}}
    if branch:
        d["gitBranch"] = branch
    return d

def write(rel, items, raw=()):
    p = os.path.join(P, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it) + "\n")
        for r in raw:
            f.write(r)
    return p

OPUS = "claude-opus-5-20260101"        # Opus 5: input 5, output 25 USD per MTok
ALL5 = U(100000, 10000, 1000000, 300000, 200000, 100000)   # 0.5 + 1.25 + 1.0 + 0.5 + 0.25 = 3.50
FALL = U(0, 0, 0, 500000)              # no split: 500000 x 6.25 / 1e6 = 3.125, as 5 minute writes
A, B, C = "-tmp-proj-a", "-tmp-proj-b", "-tmp-proj-c"

# folder A: a session on branch 267-costs (task 267)
s1 = write(A + "/s1.jsonl", [
    asst("m1", OPUS, ALL5, 100, "267-costs"),
    asst("m1", OPUS, ALL5, 100, "267-costs", text="second block of the same reply"),   # same id: counted once
    asst("m2", OPUS, FALL, 200, "267-costs"),
    asst("m3", OPUS, U(77777), -50, "267-costs"),     # before since: out
    asst("m4", OPUS, U(88888), 172810, "267-costs"),  # after until: out
], raw=["{this line is broken\n"])
# session on a branch with a dotted version: no task, so session:s2
write(A + "/s2.jsonl", [asst("m6", OPUS, U(1000000), 400, "fix/review-after-0.12")])
# a model with no price, no branch
write(A + "/s3.jsonl", [asst("m5", "claude-mystery-9", U(1000, 1000), 300)])
# a subagent of s1: brief 42 chars, last assistant text 17 chars
write(A + "/s1/subagents/agent-abc.jsonl", [
    {"type": "user", "timestamp": iso(90), "isSidechain": True, "message": {"role": "user", "content": "b" * 42}},
    asst("a1", OPUS, U(200000), 120, text="first"),
    asst("a2", OPUS, U(0), 130, text="r" * 17),
])
with open(os.path.join(P, A, "s1", "subagents", "agent-abc.meta.json"), "w") as f:
    json.dump({"agentType": "general-purpose", "description": "x"}, f)
# a subagent whose file is older than since: skipped whole
old = write(A + "/s1/subagents/agent-old.jsonl", [asst("o1", OPUS, U(333333), 120)])
os.utime(old, (SINCE - 1000, SINCE - 1000))
# folder B: one reply, branch main (no task: session:s9)
write(B + "/s9.jsonl", [asst("m9", OPUS, U(1000000), 10, "main")])
# folder C: one reply, a model with no price only (all unpriced)
write(C + "/s10.jsonl", [asst("m10", "claude-mystery-9", U(2000), 10, "main")])

prices = costs.load_prices()

# price(): known answers
want("price: all five kinds of one reply = 3.50 USD", abs(costs.price(ALL5, OPUS, prices) - 3.5) < 1e-9)
want("price: no split, the cache write is a 5 minute write (3.125 USD)", abs(costs.price(FALL, OPUS, prices) - 3.125) < 1e-9)
want("price: 1 MTok of Opus 5 input = 5.00 USD", abs(costs.price(U(1000000), OPUS, prices) - 5.0) < 1e-9)
want("price: longest prefix: claude-opus-4-5 is 5.00, not Opus 4 at 15.00",
     abs(costs.price(U(1000000), "claude-opus-4-5-20251101", prices) - 5.0) < 1e-9)
M = 1000000
def UC(i, r, o, w5=0, w1=0):
    return {"input_tokens": i, "cache_read_input_tokens": r, "output_tokens": o, "cache_creation_input_tokens": w5 + w1,
            "cache_creation": {"ephemeral_5m_input_tokens": w5, "ephemeral_1h_input_tokens": w1}}
want("price: Haiku 5.5, a prompt up to 100k: input 0.10 per MTok (0.505 USD)",
     abs(costs.price(UC(50000, 0, M), "claude-haiku-5-5", prices) - 0.505) < 1e-9)
want("price: Haiku 5.5, a prompt over 100k (cache counted in): the dearer tier (2.5055 USD)",
     abs(costs.price(UC(1000, 100000, M), "claude-haiku-5-5", prices) - 2.5055) < 1e-9)
want("price: Fable 5.2 reads the cache at 0.025x: 8 + 0.20 + 40 + 10 + 16 = 74.20 USD",
     abs(costs.price(UC(M, M, M, M, M), "claude-fable-5-2", prices) - 74.2) < 1e-9)
want("price: Opus 5.5 reads the cache at 0.05x: 4 + 0.20 + 20 + 5 + 8 = 37.20 USD",
     abs(costs.price(UC(M, M, M, M, M), "claude-opus-5-5", prices) - 37.2) < 1e-9)
want("price: Opus 4.8 reads the cache at 0.1x: 5 + 0.50 + 25 + 6.25 + 10 = 46.75 USD",
     abs(costs.price(UC(M, M, M, M, M), "claude-opus-4-8", prices) - 46.75) < 1e-9)
want("price: an unknown model gives None", costs.price(ALL5, "claude-mystery-9", prices) is None)

# task_label
labels = {"267-something": "267", "fix/267-x": "267", "issue-267": "267", "agent-kit-267": "267",
          "fix/12-and-34": "12", "fix/review-after-0.12": None, "main": None, "feature/1234567-x": None,
          "v0.12.1": None, "": None, None: None}
for b, want_label in labels.items():
    want("task_label: %r -> %r" % (b, want_label), costs.task_label(b) == want_label)

# report, folder A only
r = costs.report(P, SINCE, UNTIL, folder=A)
T_ = {t["task"]: t for t in r["tasks"]}
want("report: the period keeps since..until (echoed)", r["since"] == SINCE and r["until"] == UNTIL)
want("report: one agent, the folder A", [x["folder"] for x in r["agents"]] == [A])
ag = r["agents"][0]
want("agent: main input 100000 + 1000000 + 1000, subagent input 200000 (m3, m4, the old file out)",
     ag["main"]["input"] == 1101000 and ag["subagents"]["input"] == 200000)
want("agent: the duplicated reply counted once (output 10000 + 1000)", ag["main"]["output"] == 11000)
want("tasks: 267, session:s2, session:s3", sorted(T_) == ["267", "session:s2", "session:s3"])
t267 = T_["267"]
want("main: 5m and 1h split, and the fallback to 5m (700000 and 100000)",
     t267["main"]["cache_write_5m"] == 700000 and t267["main"]["cache_write_1h"] == 100000)
want("main: money 3.50 + 3.125 = 6.625 USD", abs(t267["main"]["usd"] - 6.625) < 1e-9)
want("main: the subagent is not in main", t267["main"]["input"] == 100000)
want("subagents: the subagent's own tokens, 200000 input = 1.00 USD",
     t267["subagents"]["input"] == 200000 and abs(t267["subagents"]["usd"] - 1.0) < 1e-9)
calls = t267["calls"]
want("calls: only agent-abc (the old file is skipped)", [c["agent"] for c in calls] == ["agent-abc"])
c = calls[0] if calls else {}
want("calls: type from meta, brief 42 chars, report 17 chars",
     c.get("type") == "general-purpose" and c.get("brief_chars") == 42 and c.get("report_chars") == 17)
want("calls: the call's tokens are its own", c.get("tokens", {}).get("input") == 200000)
want("calls: brief 42 chars is about 11 tokens, report 17 chars about 5",
     c.get("brief_tokens") == 11 and c.get("report_tokens") == 5)
want("est_tokens: characters over 4, rounded up; 0 for empty; None for no text",
     costs.est_tokens("abcd") == 1 and costs.est_tokens("abcde") == 2 and costs.est_tokens("") == 0
     and costs.est_tokens(None) is None)
want("task session:s2: 1000000 input = 5.00 USD",
     T_["session:s2"]["main"]["input"] == 1000000 and abs(T_["session:s2"]["main"]["usd"] - 5.0) < 1e-9)
want("unknown model: tokens counted, money 0 and partial", T_["session:s3"]["main"]["input"] == 1000
     and T_["session:s3"]["main"]["usd"] == 0.0 and T_["session:s3"]["main"]["usd_partial"] is True)
want("unknown model: listed under unpriced", r["unpriced"] == ["claude-mystery-9"])
want("mixed: the total sums the priced part (3.5 + 3.125 + 5.0 + 1.0 = 12.625 USD) and is partial",
     abs(r["total"]["usd"] - 12.625) < 1e-9 and r["total"]["usd_partial"] is True and r["total"]["input"] == 1301000)
want("mixed: the agent's main is partial, the task 267 main is not (6.625 USD)",
     ag["main"]["usd_partial"] is True and t267["main"]["usd_partial"] is False)
want("mixed: the subagents of 267 are priced in full", t267["subagents"]["usd_partial"] is False)

# all unpriced: a folder whose only model has no price
rc = costs.report(P, SINCE, UNTIL, folder=C)
want("all unpriced: the total is 0 USD, partial, and the model is listed",
     rc["total"]["usd"] == 0.0 and rc["total"]["usd_partial"] is True and rc["total"]["input"] == 2000
     and rc["unpriced"] == ["claude-mystery-9"])
want("all unpriced: its task has 0 USD and partial", rc["tasks"][0]["main"]["usd"] == 0.0
     and rc["tasks"][0]["main"]["usd_partial"] is True)
want("priced only: a folder of Opus alone is not partial", costs.report(P, SINCE, UNTIL, folder=B)["total"]["usd_partial"] is False)

# report, all folders, then a period after the data
r2 = costs.report(P, SINCE, UNTIL)
want("no folder: all three folders, the total adds folders B and C", [x["folder"] for x in r2["agents"]] == [A, B, C]
     and r2["total"]["input"] == 2303000)
want("no folder: a session with no task is session:s9", "session:s9" in [t["task"] for t in r2["tasks"]])
r3 = costs.report(P, UNTIL + 1000, UNTIL + 2000)
want("period after the data: nothing counted", r3["total"]["input"] == 0 and r3["tasks"] == [])

# labels: a profile's LABEL names the task of its folder's sessions (own folder P2, so the counts above stay)
P2 = os.path.join(T, "projects2")
def wr(rel, items):
    p = os.path.join(P2, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it) + "\n")
E, F, G, H = "-tmp-proj-e", "-tmp-proj-f", "-tmp-proj-g", "-tmp-proj-h"
wr(E + "/s11.jsonl", [asst("e1", OPUS, U(1000000), 100, "fix/999-x")])
wr(E + "/s11/subagents/agent-e.jsonl", [asst("e2", OPUS, U(300000), 110)])
wr(F + "/s12.jsonl", [asst("f1", OPUS, U(1000000), 100, "fix/267-x")])
wr(G + "/s13.jsonl", [asst("g1", OPUS, U(1000000), 100, "fix/77-x")])
wr(G + "/s14.jsonl", [asst("g2", OPUS, U(1000000), 100)])
wr(H + "/s15.jsonl", [asst("h1", OPUS, U(1000000), 100)])
want("label_task: #267 -> 267, 267 -> 267, # and empty -> None",
     costs.label_task("#267") == "267" and costs.label_task("267") == "267" and costs.label_task("#") is None
     and costs.label_task("") is None and costs.label_task(None) is None)
tk = lambda r: [t["task"] for t in r["tasks"]]
rE = costs.report(P2, SINCE, UNTIL, folder=E, labels={E: "#267"})
want("label #267 in the folder: the task is 267, not the branch's 999; the subagent is in 267 too",
     tk(rE) == ["267"] and rE["tasks"][0]["main"]["input"] == 1000000 and rE["tasks"][0]["subagents"]["input"] == 300000)
rEn = costs.report(P2, SINCE, UNTIL, folder=E)
want("no labels given: the branch's 999, as before", tk(rEn) == ["999"] and rEn["tasks"][0]["subagents"]["input"] == 300000)
rF = costs.report(P2, SINCE, UNTIL, folder=F, labels={F: ""})
want("empty label: the branch rule (fix/267-x gives 267)", tk(rF) == ["267"])
rAll = costs.report(P2, SINCE, UNTIL, labels={E: "#267", F: None})
t267 = [t for t in rAll["tasks"] if t["task"] == "267"]
want("#267 (label) and fix/267-x (branch) are one task 267: 2 MTok of main input, the subagent's 300000",
     len(t267) == 1 and t267[0]["main"]["input"] == 2000000 and t267[0]["subagents"]["input"] == 300000)
rG = costs.report(P2, SINCE, UNTIL, folder=G, labels={G: None})
want("two profiles in one folder, different labels: no label (branch 77; a session with no branch is session:s14)",
     tk(rG) == ["77", "session:s14"])
rH = costs.report(P2, SINCE, UNTIL, folder=H, labels={H: "12"})
want("a label and no branch: the task is 12", tk(rH) == ["12"])

# Langfuse (langfuse_costs.py): a fake server on 127.0.0.1 answers the metrics request; no real receiver is used
import base64, socket, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit
import langfuse_costs, telemetry

HOME = os.environ["HOME"]
GOOD = "Basic " + base64.b64encode(b"pk-test:sk-test").decode("ascii")
ROWS = {"data": [
    {"time_dimension": "2026-06-01", "providedModelName": "claude-opus-5-20260101", "sum_totalCost": 1.5},
    {"time_dimension": "2026-06-02", "providedModelName": "claude-opus-5-20260101", "sum_totalCost": 0.5},
    {"time_dimension": "2026-06-02", "providedModelName": "claude-haiku-5-5", "sum_totalCost": 0.25}]}
seen = {}

class Fake(BaseHTTPRequestHandler):
    def do_GET(self):
        seen["path"] = self.path
        seen["auth"] = self.headers.get("Authorization")
        if urlsplit(self.path).path != "/api/public/v2/metrics":
            code, body = 404, b"{}"
        elif seen["auth"] != GOOD:
            code, body = 401, b'{"message":"Invalid credentials"}'
        else:
            code, body = 200, json.dumps(ROWS).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass

srv = HTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=srv.serve_forever, daemon=True).start()
FAKE = "http://127.0.0.1:%d" % srv.server_address[1]

def setup(url, sk="sk-test"):
    telemetry.install(HOME, {"logs_url": "http://127.0.0.1:9", "traces_to": "langfuse", "langfuse_url": url,
                             "langfuse_public_key": "pk-test", "langfuse_secret_key": sk})

def leaks(r):
    text = json.dumps(r)
    return "sk-test" in text or "pk-test" in text or "Basic " in text

telemetry.remove(HOME)
r = langfuse_costs.report(HOME, SINCE, UNTIL)
want("langfuse, no keys set: an error, no money", r.get("source") == "langfuse" and "error" in r and "usd" not in r)

setup(FAKE)
r = langfuse_costs.report(HOME, SINCE, UNTIL)
q = parse_qs(urlsplit(seen.get("path", "")).query).get("query", [""])[0]
want("langfuse 200: the sum is 2.25 USD, the model's 2.0 and haiku's 0.25",
     r.get("source") == "langfuse" and "error" not in r and abs(r.get("usd", -1) - 2.25) < 1e-9
     and r.get("by_model") == [{"model": "claude-haiku-5-5", "usd": 0.25},
                               {"model": "claude-opus-5-20260101", "usd": 2.0}])
want("langfuse 200: Basic key sent, the query asks the daily cost by model",
     seen.get("auth") == GOOD and '"granularity": "day"' in q and "totalCost" in q and "fromTimestamp" in q)
want("langfuse 200: no key in the answer", not leaks(r))

setup(FAKE, sk="wrong")
r = langfuse_costs.report(HOME, SINCE, UNTIL)
want("langfuse 401: refused, no money, no key in the answer",
     r.get("error") == "refused: answered 401" and "usd" not in r and not leaks(r))

s = socket.socket()
s.bind(("127.0.0.1", 0))
closed = "http://127.0.0.1:%d" % s.getsockname()[1]
s.close()
setup(closed)
r = langfuse_costs.report(HOME, SINCE, UNTIL)
want("langfuse not reachable: an error, no money", r.get("error") == "not reachable" and "usd" not in r)

srv.shutdown()
srv.server_close()
telemetry.remove(HOME)

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
