#!/usr/bin/env bash
# tests/dashboard-telemetry.test.sh - dashboard/telemetry.py: "install telemetry" (PLAN.md section 6): the file
# ~/.config/agent-kit/telemetry.env, its lines, status, remove. No server, no receiver: HOME is a temp folder.
# Exit 0 when every case passes.
REPO=$(cd "$(dirname "$0")/.." && pwd -P)
T=$(mktemp -d) || exit 1; T=$(cd "$T" && pwd -P); trap 'rm -rf "$T"' EXIT
export HOME="$T/home"; mkdir -p "$HOME" || exit 1
cat > "$T/case.py" <<'PY'
import base64, json, os, shlex, stat, sys
sys.path.insert(0, os.path.join(sys.argv[1], "dashboard"))
import telemetry

T = sys.argv[2]
fails = []

def want(name, ok):
    if not ok:
        fails.append(name)
    print(("ok   - " if ok else "FAIL - ") + name)

def lines_of(home):
    out = {}
    with open(telemetry.file_of(home)) as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                k, _, v = line.rstrip("\n").partition("=")
                out[k] = shlex.split(v)[0]   # the value in its single quotes, as bash and Python read it
    return out

def basic(header, prefix):
    """the Basic value of a header line, decoded: ("user", "password") or the pair of the Langfuse value"""
    v = header.split("Authorization=Basic ", 1)[1].split(",")[0]
    return base64.b64decode(v).decode()

def refused(name, home, form):
    before = os.path.exists(telemetry.file_of(home))
    try:
        telemetry.install(home, form)
    except telemetry.Invalid:
        ok = not os.path.exists(telemetry.file_of(home)) or before
        want(name, ok)
        return
    want(name + " (it was not refused)", False)

# 1. logs only
H1 = os.path.join(T, "h1")
telemetry.install(H1, {"logs_url": "http://192.168.1.10:9428"})
p1 = telemetry.file_of(H1)
want("install: the file is mode 600 in a folder 700",
     stat.S_IMODE(os.stat(p1).st_mode) == 0o600 and stat.S_IMODE(os.stat(os.path.dirname(p1)).st_mode) == 0o700)
l1 = lines_of(H1)
want("logs only: the logs endpoint, the otlp logs exporter, the protocol, telemetry on",
     l1.get("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT") == "http://192.168.1.10:9428/insert/opentelemetry/v1/logs"
     and l1.get("OTEL_LOGS_EXPORTER") == "otlp" and l1.get("OTEL_EXPORTER_OTLP_PROTOCOL") == "http/protobuf"
     and l1.get("CLAUDE_CODE_ENABLE_TELEMETRY") == "1")
want("logs only: no traces variables, no logs headers", not any("TRACES" in k or k == "OTEL_EXPORTER_OTLP_LOGS_HEADERS" or k == "OTEL_TRACES_EXPORTER" for k in l1))
want("logs only: the dashboard's lines: receivers and the logs query address",
     l1.get("AGENT_KIT_TELEMETRY_RECEIVERS") == "victorialogs" and l1.get("AGENT_KIT_TELEMETRY_LOGS_QUERY") == "http://192.168.1.10:9428")
want("logs only: no prompt text", "OTEL_LOG_USER_PROMPTS" not in l1)

# 2. logs with auth + VictoriaTraces with auth
H2 = os.path.join(T, "h2")
telemetry.install(H2, {"logs_url": "https://logs.example.net", "logs_user": "lu", "logs_password": "lp-1",
                       "traces_to": "victoria", "traces_url": "https://traces.example.net:10428/",
                       "traces_user": "tu", "traces_password": "tp2"})
l2 = lines_of(H2)
want("logs + VictoriaTraces: logs headers decode to lu:lp-1",
     l2.get("OTEL_EXPORTER_OTLP_LOGS_HEADERS", "").startswith("Authorization=Basic ") and basic(l2["OTEL_EXPORTER_OTLP_LOGS_HEADERS"], "") == "lu:lp-1")
want("logs + VictoriaTraces: traces endpoint, exporter and beta flag",
     l2.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") == "https://traces.example.net:10428/insert/opentelemetry/v1/traces"
     and l2.get("OTEL_TRACES_EXPORTER") == "otlp" and l2.get("CLAUDE_CODE_ENHANCED_TELEMETRY_BETA") == "1")
want("logs + VictoriaTraces: traces headers decode to tu:tp2",
     basic(l2.get("OTEL_EXPORTER_OTLP_TRACES_HEADERS", ""), "") == "tu:tp2")
want("logs + VictoriaTraces: receivers name both, the logs query is the logs address only",
     l2.get("AGENT_KIT_TELEMETRY_RECEIVERS") == "victorialogs,victoriatraces" and l2.get("AGENT_KIT_TELEMETRY_LOGS_QUERY") == "https://logs.example.net")
want("logs + VictoriaTraces: no Langfuse line", not any("langfuse" in k.lower() or "langfuse" in v for k, v in l2.items() if k != "AGENT_KIT_TELEMETRY_RECEIVERS"))

# 3. logs + Langfuse
H3 = os.path.join(T, "h3")
telemetry.install(H3, {"logs_url": "http://192.168.1.10:9428", "traces_to": "langfuse",
                       "langfuse_url": "https://cloud.langfuse.com", "langfuse_public_key": "pk-lf-1",
                       "langfuse_secret_key": "sk-lf-2"})
l3 = lines_of(H3)
want("logs + Langfuse: the Langfuse traces endpoint",
     l3.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") == "https://cloud.langfuse.com/api/public/otel/v1/traces")
hdr = l3.get("OTEL_EXPORTER_OTLP_TRACES_HEADERS", "")
want("logs + Langfuse: the Basic header is pk:sk and the ingestion version is in the same value",
     basic(hdr, "") == "pk-lf-1:sk-lf-2" and hdr.endswith(",x-langfuse-ingestion-version=4"))
want("logs + Langfuse: no logs headers (no auth on logs), receivers victorialogs,langfuse",
     "OTEL_EXPORTER_OTLP_LOGS_HEADERS" not in l3 and l3.get("AGENT_KIT_TELEMETRY_RECEIVERS") == "victorialogs,langfuse")

# 4. bash can source the file and sees the same values
out = os.popen("bash -c 'set -a; . \"$1\"; set +a; printf \"%s\\n\" \"$OTEL_EXPORTER_OTLP_TRACES_HEADERS\" \"$OTEL_EXPORTER_OTLP_TRACES_ENDPOINT\" \"$AGENT_KIT_TELEMETRY_LOGS_QUERY\"' x " + repr(telemetry.file_of(H3))).read().split("\n")
want("bash source: the same values as the file",
     out[0] == hdr and out[1] == l3["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] and out[2] == "http://192.168.1.10:9428")

# 5. status: set_up and receivers only; the secret is nowhere in it
st = telemetry.status(H3)
text = json.dumps(st)
want("status: exactly set_up and receivers", st == {"set_up": True, "receivers": ["victorialogs", "langfuse"]})
want("status: the secret key, the password and the header appear nowhere", "sk-lf-2" not in text and "lp-1" not in text and "Basic" not in text)
want("status with the VictoriaTraces file: its names", telemetry.status(H2) == {"set_up": True, "receivers": ["victorialogs", "victoriatraces"]})

# 5b. the Langfuse reading key, for the langfuse add-on: its three lines with any traces receiver, the reading key and
# not the sending one; none without it; the file still mode 600; the key nowhere in the status
RK = {"read_langfuse_url": "https://read.langfuse.example", "read_langfuse_public_key": "pk-read-1", "read_langfuse_secret_key": "sk-read-2"}
for to, extra in (("", {}), ("victoria", {"traces_url": "https://traces.example.net"}),
                  ("langfuse", {"langfuse_url": "https://cloud.langfuse.com", "langfuse_public_key": "pk-send", "langfuse_secret_key": "sk-send"})):
    h = os.path.join(T, "hr-" + (to or "none"))
    telemetry.install(h, dict({"logs_url": "http://192.168.1.10:9428", "traces_to": to}, **extra, **RK))
    l = lines_of(h)
    want("reading key with traces to %r: the three lines, the reading key" % to,
         l.get("LANGFUSE_BASE_URL") == "https://read.langfuse.example" and l.get("LANGFUSE_PUBLIC_KEY") == "pk-read-1"
         and l.get("LANGFUSE_SECRET_KEY") == "sk-read-2" and stat.S_IMODE(os.stat(telemetry.file_of(h)).st_mode) == 0o600
         and "sk-read" not in json.dumps(telemetry.status(h)))
want("no reading key: no LANGFUSE_ line (logs + Langfuse traces)", not any(k.startswith("LANGFUSE_") for k in l3))
for k in RK:
    refused("a reading key without %s refused" % k, os.path.join(T, "hr-part"),
            dict({"logs_url": "http://192.168.1.10:9428"}, **{x: v for x, v in RK.items() if x != k}))
refused("a reading secret key with $(...) refused", os.path.join(T, "hr-part"),
        dict({"logs_url": "http://192.168.1.10:9428"}, **dict(RK, read_langfuse_secret_key="$(id)")))
refused("a reading address with ftp refused", os.path.join(T, "hr-part"),
        dict({"logs_url": "http://192.168.1.10:9428"}, **dict(RK, read_langfuse_url="ftp://x")))

# 6. refused, and no file written
H6 = os.path.join(T, "h6")
refused("bad address: ftp scheme refused", H6, {"logs_url": "ftp://192.168.1.10:9428"})
refused("bad address: no host refused", H6, {"logs_url": "http://:9428"})
refused("bad address: a space refused", H6, {"logs_url": "http://192.168.1.10 :9428"})
refused("bad address: $(...) refused", H6, {"logs_url": "http://x/$(id)"})
refused("bad address: a user in the address refused", H6, {"logs_url": "http://u:p@192.168.1.10:9428"})
refused("bad address: a bad port refused", H6, {"logs_url": "http://192.168.1.10:notaport"})
refused("value with a newline refused", H6, {"logs_url": "http://192.168.1.10:9428", "logs_user": "u\nx", "logs_password": "p"})
refused("password with a quote refused", H6, {"logs_url": "http://192.168.1.10:9428", "logs_user": "u", "logs_password": "p'q"})
refused("key with $(...) refused", H6, {"logs_url": "http://192.168.1.10:9428", "traces_to": "langfuse",
        "langfuse_url": "https://cloud.langfuse.com", "langfuse_public_key": "pk", "langfuse_secret_key": "$(id)"})
refused("user with a colon refused", H6, {"logs_url": "http://192.168.1.10:9428", "logs_user": "a:b", "logs_password": "p"})
refused("user without password refused", H6, {"logs_url": "http://192.168.1.10:9428", "logs_user": "u"})
refused("traces to victoria without its address refused", H6, {"logs_url": "http://192.168.1.10:9428", "traces_to": "victoria"})
refused("an unknown traces receiver refused", H6, {"logs_url": "http://192.168.1.10:9428", "traces_to": "jaeger"})
refused("an unknown field refused", H6, {"logs_url": "http://192.168.1.10:9428", "OTEL_LOG_USER_PROMPTS": "1"})
want("refused: no file was written", not os.path.exists(telemetry.file_of(H6)))

# a refused install keeps the old file
before = open(telemetry.file_of(H1)).read()
refused("a refused install over a file keeps it", H1, {"logs_url": "http://a b"})
want("the old file is untouched after a refusal", open(telemetry.file_of(H1)).read() == before)

# 7. remove, and status with no file
telemetry.remove(H1)
want("remove: the file is gone", not os.path.exists(telemetry.file_of(H1)))
want("status with no file: set_up false", telemetry.status(H1) == {"set_up": False, "receivers": []})
telemetry.remove(H1)
want("remove again: no error", True)

# 8. check and arrives against a fake receiver on 127.0.0.1 (a free port, in this process): the good key
# lu:good-pass is answered 200; any other key 401; "redirect" answers 302 to another host; a port with nothing
# listening is "down".
import socket, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Recv(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def _answer(self):
        srv = self.server
        if srv.mode == "redirect":
            code, body, extra = 302, b"", [("Location", "http://localhost:%d/elsewhere" % srv.server_address[1])]
        elif self.headers.get("Authorization") != "Basic " + base64.b64encode(b"lu:good-pass").decode():
            code, body, extra = 401, b"no", []
        elif "/select/logsql/query" in self.path:
            code, body, extra = 200, srv.rows, []
        else:
            code, body, extra = 200, b"[]", []
        self.send_response(code)
        for k, v in extra:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    do_GET = _answer
    do_POST = _answer

def receiver(mode):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Recv)
    srv.mode, srv.rows = mode, b""
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv

def down_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port

def logs_home(name, url, password="good-pass", user="lu"):
    home = os.path.join(T, name)
    form = {"logs_url": url}
    if user:
        form.update({"logs_user": user, "logs_password": password})
    telemetry.install(home, form)
    return home

G = receiver("good")
R = receiver("redirect")
GOOD = "http://127.0.0.1:%d" % G.server_address[1]
REDIR = "http://127.0.0.1:%d" % R.server_address[1]
DOWN = "http://127.0.0.1:%d" % down_port()
now = int(time.time())

def at(sec):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now - sec)) + ".000Z"

G.rows = ("\n".join(json.dumps(r) for r in [{"agent.id": "a1", "last": at(60)}, {"agent.id": "a2", "last": at(2000)}])
          + "\n").encode()

c_good = telemetry.check(logs_home("good", GOOD)).get("receivers", {}).get("victorialogs", {})
want("check: the good key is accepted", c_good.get("key") == "accepted")
c_bad = telemetry.check(logs_home("bad", GOOD, password="wrong-pass")).get("receivers", {}).get("victorialogs", {})
want("check: a key answered 401 is refused, the 401 in the detail",
     c_bad.get("key") == "refused" and "401" in c_bad.get("detail", ""))
c_down = telemetry.check(logs_home("down", DOWN)).get("receivers", {}).get("victorialogs", {})
want("check: a receiver that is down is unreachable", c_down.get("key") == "unreachable")
c_redir = telemetry.check(logs_home("redir", REDIR)).get("receivers", {}).get("victorialogs", {})
want("check: a redirect to another host is not followed (not checked)", c_redir.get("key") == "not checked")
c_nokey = telemetry.check(logs_home("nokey", GOOD, user=None)).get("receivers", {}).get("victorialogs", {})
want("check: no key kept: not checked, no request", c_nokey.get("key") == "not checked")
answers = json.dumps([c_good, c_bad, c_down, c_redir, c_nokey])
want("check: no key appears in any answer", "good-pass" not in answers and "wrong-pass" not in answers)

HA = logs_home("arr", GOOD)
agents = [{"id": "a1", "running": True, "started": None},
          {"id": "a2", "running": True, "started": None},
          {"id": "a3", "running": True, "started": now - 100},
          {"id": "a4", "running": True, "started": now - 2000}]
ar = telemetry.arrives(HA, agents, now=now)
want("arrives: no reason when the receiver answers", "reason" not in ar and ar.get("limit") == 600)
want("arrives: a fresh agent is not late, its last record is kept",
     ar["agents"]["a1"]["late"] is False and ar["agents"]["a1"]["last"] == now - 60)
want("arrives: an agent silent for over 600 s is late", ar["agents"]["a2"]["late"] is True
     and ar["agents"]["a2"]["last"] == now - 2000)
want("arrives: no record yet, started 100 s ago: not late", ar["agents"]["a3"]["late"] is False
     and ar["agents"]["a3"]["last"] is None)
want("arrives: no record yet, started 2000 s ago: late", ar["agents"]["a4"]["late"] is True)
ad = telemetry.arrives(logs_home("arrdown", DOWN), agents, now=now)
want("arrives: no receiver answering: no last record, a reason",
     all(v["last"] is None for v in ad["agents"].values()) and "reason" in ad)
want("arrives: no receiver: a running agent started 2000 s ago is still late", ad["agents"]["a4"]["late"] is True)

G.shutdown(); G.server_close(); R.shutdown(); R.server_close()

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
