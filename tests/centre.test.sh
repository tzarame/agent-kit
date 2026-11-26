#!/usr/bin/env bash
# tests/centre.test.sh - the control centre's server end to end: two real dashboards (dashboard/dash.py) on free
# ports of 127.0.0.1, each with its own temp HOME and tmux on its own socket; a fake old dashboard (api 0);
# a second centre; the centre on a free port; a fake tailscale on PATH that prints the peers. HOME is a temp folder.
# Exit 0 when every case passes.
REPO=$(cd "$(dirname "$0")/.." && pwd -P)
T=$(mktemp -d) || exit 1; T=$(cd "$T" && pwd -P)
SOCK="centretest-$$-$RANDOM"
PIDS=""
cleanup() { for p in $PIDS; do kill "$p" 2>/dev/null; done; env -u TMUX tmux -L "$SOCK" kill-server 2>/dev/null; rm -rf "$T"; }
trap cleanup EXIT
export HOME="$T/home"; BIN="$T/bin"; mkdir -p "$HOME" "$BIN" "$T/work" "$T/home1" "$T/home2" "$T/home3" || exit 1
freeport() { python3 -I -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])'; }
P1=$(freeport); P2=$(freeport); OLD=$(freeport); C=$(freeport); D=$(freeport); DEAD=$(freeport)
B="http://127.0.0.1:$C"
PASS=0; FAIL=0; RC=0; OUT=""
check() { if [ "$2" = 0 ]; then PASS=$((PASS+1)); echo "ok   - $1"; else FAIL=$((FAIL+1)); echo "FAIL - $1"; fi; }
# req METHOD PATH [BODY]: sets RC (HTTP status) and OUT (answer body) for the centre
req() {
  local data=()
  [ -n "${3:-}" ] && data=(-H 'Content-Type: application/json' --data-binary "$3")
  RC=$(curl -s -o "$T/body" -w '%{http_code}' -X "$1" "${data[@]}" "$B$2"); OUT=$(cat "$T/body")
}
# jq_ EXPR: evaluates EXPR on the last answer body (variable d) and prints it
jq_() { python3 -I -c 'import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1]))' "$1" < "$T/body" 2>/dev/null; }

# the fake network: this machine and one peer on 127.0.0.1, one peer offline
cat > "$T/status.json" <<'JSON'
{"Self":{"HostName":"this-box","TailscaleIPs":["127.0.0.1"],"Online":true,"UserID":1},
 "User":{"1":{"LoginName":"owner@example.com"}},
 "Peer":{"nodeA":{"HostName":"peer-a","TailscaleIPs":["127.0.0.1"],"Online":true,"UserID":1},
         "nodeB":{"HostName":"peer-off","TailscaleIPs":["192.0.2.7"],"Online":false,"UserID":1}}}
JSON
printf '#!/bin/sh\n[ "$1 $2" = "status --json" ] && cat "%s/status.json" && exit 0\nexit 1\n' "$T" > "$BIN/tailscale"
chmod +x "$BIN/tailscale"

# a fake old dashboard: api 0; it logs the Authorization header of each request
cat > "$T/old.py" <<'PY'
import http.server, json, sys
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        with open(sys.argv[2], "a") as f:
            f.write("%s\n" % self.headers.get("Authorization"))
        if self.path.endswith("/hello"):
            obj = {"kind": "dashboard", "machine": "old-box", "version": "0.1", "api": 0}
        else:
            obj = {"machine": "old-box", "agents": [], "tmux": []}
        raw = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    def log_message(self, *a):
        return
http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
PY
python3 -I -B "$T/old.py" "$OLD" "$T/old-auth.log" > "$T/old.log" 2>&1 &
PIDS="$PIDS $!"

# two real dashboards, each with its own HOME, tmux on the isolated socket
for pair in "$T/home1:$P1" "$T/home2:$P2"; do
  env HOME="${pair%%:*}" AGENT_KIT_TMUX="tmux -L $SOCK" PATH="$BIN:$PATH" \
    python3 -I -B "$REPO/dashboard/dash.py" --port "${pair##*:}" > "$T/dash${pair##*:}.log" 2>&1 &
  PIDS="$PIDS $!"
done

# a fake gh (CENTRE_GH): keeps the repository's centre.json in $T/ghstore; a file "fail" there makes every call fail
mkdir -p "$T/ghstore"
# a fake ssh and a fake ssh-keygen (CENTRE_SSH, CENTRE_SSH_KEYGEN): the ssh logs each call as a JSON line with
# whether SSH_ASKPASS was used; the step named in FAKE_SSH_DIR/fail fails; a password is checked against FAKE_SSH_EXPECT
mkdir -p "$T/fake" "$T/tmp" && printf 'Welcome\nKEYFAKE-0123456789abc\n' > "$T/fake/api-key-output"
cat > "$T/fake/ssh" <<'PY'
#!/usr/bin/env python3
import json, os, subprocess, sys
d = os.environ["FAKE_SSH_DIR"]
argv = sys.argv[1:]
asks = "PubkeyAuthentication=no" in argv
with open(os.path.join(d, "ssh.log"), "a") as f:
    f.write(json.dumps({"argv": argv, "askpass": asks}) + "\n")
if asks:
    got = subprocess.run([os.environ["SSH_ASKPASS"]], capture_output=True, text=True).stdout
    if os.environ.get("SSH_ASKPASS_REQUIRE") != "force" or got != open(os.environ["FAKE_SSH_EXPECT"], encoding="utf-8").read():
        sys.stderr.write("Permission denied (password).\n")
        sys.exit(255)
remote = argv[-1]
fail = open(os.path.join(d, "fail")).read().strip() if os.path.exists(os.path.join(d, "fail")) else ""
if "authorized_keys" in remote:
    step = "auth"
elif "install.sh" in remote:
    step = "install"
elif "dash.py key" in remote:
    step = "key"
elif remote == "bash -s" and os.path.exists(os.path.join(d, "survey")):
    sys.stdout.write(open(os.path.join(d, "survey")).read())
    sys.exit(0)
else:
    sys.stderr.write("the fake does not know this command\n")
    sys.exit(1)
if fail == step:
    sys.stderr.write("Warning: a noisy line\nboom: %s failed\n" % step)
    sys.exit(1)
if step == "key":
    sys.stdout.write(open(os.path.join(d, "api-key-output")).read())
sys.exit(0)
PY
cat > "$T/fake/ssh-keygen" <<'PY'
#!/usr/bin/env python3
import os, secrets, sys
d = os.environ["FAKE_SSH_DIR"]
open(os.path.join(d, "keygen.log"), "a").write(" ".join(sys.argv[1:]) + "\n")
f = sys.argv[sys.argv.index("-f") + 1]
if os.path.exists(f):
    sys.stderr.write("the key exists\n")
    sys.exit(1)
open(f, "w").write("-----BEGIN FAKE KEY-----\nPRIVFAKE-%s\n" % secrets.token_hex(8))
open(f + ".pub", "w").write("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFAKEKEYFAKE agent-kit-centre\n")
PY
chmod +x "$T/fake/ssh" "$T/fake/ssh-keygen"
cat > "$T/gh" <<'PY'
#!/usr/bin/env python3
# fake gh for the centre's tests: "gh api PATH" (GET) and "gh api -X PUT PATH --input -" (PUT) of one file
import base64, hashlib, json, os, sys
d = os.environ["FAKE_GH_DIR"]
f = os.path.join(d, "centre.json")
def die(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)
if os.path.exists(os.path.join(d, "fail")):
    die("gh: could not reach GitHub")
args = sys.argv[1:]
if args[:1] != ["api"]:
    die("gh: unknown command")
args = args[1:]
if args[:2] == ["-X", "PUT"]:
    body = json.loads(sys.stdin.read())
    cur = open(f, encoding="utf-8").read() if os.path.exists(f) else None
    if cur is not None and body.get("sha") != hashlib.sha1(cur.encode("utf-8")).hexdigest():
        die("gh: sha does not match (HTTP 409)")
    with open(f, "w", encoding="utf-8") as o:
        o.write(base64.b64decode(body["content"]).decode("utf-8"))
    print(json.dumps({"content": {"path": "centre.json"}}))
else:
    if not args[0].endswith("/contents/centre.json") or not os.path.exists(f):
        die("gh: Not Found (HTTP 404)")
    text = open(f, encoding="utf-8").read()
    print(json.dumps({"sha": hashlib.sha1(text.encode("utf-8")).hexdigest(),
                      "content": base64.encodebytes(text.encode("utf-8")).decode("ascii")}))
PY
chmod +x "$T/gh"

# the centre, and a second centre on another port with its own HOME
env AGENT_KIT_FIND_PORTS="$P1,$P2,$OLD" AGENT_KIT_FIND_CENTRE_PORTS="$C,$D" PATH="$BIN:$PATH" \
  CENTRE_GH="$T/gh" FAKE_GH_DIR="$T/ghstore" CENTRE_SSH="$T/fake/ssh" CENTRE_SSH_KEYGEN="$T/fake/ssh-keygen" \
  FAKE_SSH_DIR="$T/fake" FAKE_SSH_EXPECT="$T/expect" TMPDIR="$T/tmp" python3 -I -B "$REPO/centre/centre.py" --port "$C" > "$T/centre.log" 2>&1 &
PIDS="$PIDS $!"
env HOME="$T/home3" AGENT_KIT_FIND_PORTS="$P1,$P2,$OLD" AGENT_KIT_FIND_CENTRE_PORTS="$C,$D" PATH="$BIN:$PATH" \
  python3 -I -B "$REPO/centre/centre.py" --port "$D" > "$T/centre2.log" 2>&1 &
PIDS="$PIDS $!"
for port in "$P1" "$P2" "$OLD" "$C" "$D"; do
  for _ in $(seq 50); do curl -s -o /dev/null "http://127.0.0.1:$port/" 2>/dev/null && break; sleep 0.1; done
done

# 1. hello with no key; the page says Control centre, with the CSP header, no Access-Control-Allow-Origin
req GET /api/v1/hello
[ "$RC" = 200 ] && [ "$(jq_ 'd["kind"]')" = centre ] && [ "$(jq_ 'd["api"]')" = 1 ] && [ -n "$(jq_ 'd["machine"]')" ]
check "hello: 200, kind centre, api 1, no key" $?
hdr=$(curl -s -D - -o "$T/page" "$B/")
grep -q 'Control centre' "$T/page" && printf '%s' "$hdr" | grep -qi '^Content-Security-Policy:' \
  && ! printf '%s' "$hdr" | grep -qi 'Access-Control-Allow-Origin'
check "page: says Control centre, CSP set, no Access-Control-Allow-Origin" $?

# 2. before anything is added: the two dashboards and the old one are found; this centre is not
req GET /api/v1/state
[ "$RC" = 200 ] && [ "$(jq_ "len(d['found'])")" = 3 ] && [ "$(jq_ "d['machines']")" = "[]" ] \
  && [ "$(jq_ "len([a for a in d['found'] if a['address'] in ('http://127.0.0.1:$P1','http://127.0.0.1:$P2','http://127.0.0.1:$OLD')])")" = 3 ] \
  && [ "$(jq_ "len([a for a in d['found'] if a['address']=='$B'])")" = 0 ]
check "state: the dashboards found, not added; this centre not counted" $?

# 3. add: alpha, beta, old and a machine that is down
req POST /api/v1/machines "{\"name\":\"alpha\",\"address\":\"http://127.0.0.1:$P1\"}"; a=$RC
req POST /api/v1/machines "{\"name\":\"beta\",\"address\":\"http://127.0.0.1:$P2\"}"; b=$RC
req POST /api/v1/machines "{\"name\":\"old\",\"address\":\"http://127.0.0.1:$OLD\"}"; c=$RC
req POST /api/v1/machines "{\"name\":\"down\",\"address\":\"http://127.0.0.1:$DEAD\"}"; e=$RC
[ "$a$b$c$e" = 201201201201 ]
check "machines added: 201 each" $?
req POST /api/v1/machines "{\"name\":\"alpha\",\"address\":\"http://127.0.0.1:$P1\"}"; a=$RC
req POST /api/v1/machines '{"name":"x","address":"ftp://127.0.0.1:1"}'; b=$RC
req POST /api/v1/machines 'not json'; c=$RC
[ "$a$b$c" = 400400400 ]
check "add: a name twice, a wrong address, not JSON: 400" $?

# 4. listed; each machine with its dashboard's state; the down one with an error; the old one older
req GET /api/v1/state
[ "$RC" = 200 ] && [ "$(jq_ "[m['name'] for m in d['machines']]")" = "['alpha', 'beta', 'old', 'down']" ] \
  && [ "$(jq_ "len(d['found'])")" = 0 ] \
  && [ "$(jq_ "d['machines'][0]['state'] is not None")" = True ] \
  && [ "$(jq_ "d['machines'][1]['state'] is not None")" = True ] \
  && [ "$(jq_ "d['machines'][2]['state'] is not None")" = True ] \
  && [ "$(jq_ "d['machines'][3]['error'] is not None")" = True ] \
  && [ "$(jq_ "d['machines'][0]['error']")" = None ]
check "state: machines listed; the down one shows error, the others still show" $?
[ "$(jq_ "d['machines'][2]['older']")" = True ] && [ "$(jq_ "d['machines'][0]['older']")" = False ] \
  && [ "$(jq_ "d['machines'][2]['version']")" = 0.1 ] && [ "$(jq_ "d['machines'][2]['api']")" = 0 ]
check "older: true for the dashboard that answers api 0, false for the others" $?

# 5. a project in the kit's config of each machine; the pass-through reads each, and the state shows both
for pair in "home1:work" "home2:other"; do
  mkdir -p "$T/${pair%%:*}/.config/agent-kit"
  printf '{"version": 2, "projects": {"%s": {"folder": "%s"}}}\n' "${pair##*:}" "$T/work" > "$T/${pair%%:*}/.config/agent-kit/config.json"
done
req GET "/api/v1/machines/alpha/api/v1/state"; a=$RC; A=$(jq_ "d['agents'][0]['id']")
req GET "/api/v1/machines/beta/api/v1/state"; b=$RC
[ "$a$b" = 200200 ] && [ "$A" = work ] && [ "$(jq_ "d['agents'][0]['id']")" = other ]
check "pass-through: the state of alpha and of beta, each with its project" $?
req GET /api/v1/state
[ "$(jq_ "[a['name'] for a in d['machines'][0]['state']['agents']]")" = "['work']" ] \
  && [ "$(jq_ "[a['name'] for a in d['machines'][1]['state']['agents']]")" = "['other']" ]
check "state: the agents of both machines" $?

# 6. the pass-through refuses a path outside /api/v1, an unknown machine, and a path with ..
req GET "/api/v1/machines/alpha/etc/passwd"; a=$RC
req GET "/api/v1/machines/nobody/api/v1/state"; b=$RC
c=$(curl -s --path-as-is -o /dev/null -w '%{http_code}' "$B/api/v1/machines/alpha/api/v1/../hello")
[ "$a$b" = 404404 ] && [ "$c" = 400 ]
check "pass-through: outside /api/v1 and unknown machine: 404; .. : 400" $?

# 7. a key: kept in keys.json (600), folder 700, sent as Bearer to that machine, in no answer
KEYV="k-test-0123456789abcdefSECRET"
req PUT /api/v1/machines/old "{\"key\":\"$KEYV\"}"; a=$RC; leak=0
grep -q "$KEYV" "$T/body" && leak=1
for p in /api/v1/hello /api/v1/state /api/v1/groups; do req GET "$p"; grep -q "$KEYV" "$T/body" && leak=1; done
[ "$a" = 200 ] && [ "$leak" = 0 ] && [ "$(stat -c %a "$HOME/.config/agent-kit/centre/keys.json")" = 600 ] \
  && [ "$(stat -c %a "$HOME/.config/agent-kit/centre")" = 700 ] && grep -q "$KEYV" "$HOME/.config/agent-kit/centre/keys.json"
check "key: in keys.json, mode 600, folder 700, in no API answer" $?
req GET /api/v1/state
[ "$RC" = 200 ] && [ "$(jq_ "d['machines'][2]['has_key']")" = True ] && grep -q "^Bearer $KEYV\$" "$T/old-auth.log"
check "key: sent to the machine as Bearer, and the state says has_key" $?

# 8. a machine turned off is not asked (no error); then removed
req PUT /api/v1/machines/down '{"on":false}'; a=$RC
req GET /api/v1/state
[ "$a" = 200 ] && [ "$(jq_ "d['machines'][3]['on']")" = False ] && [ "$(jq_ "d['machines'][3]['error']")" = None ] \
  && [ "$(jq_ "d['machines'][0]['state'] is not None")" = True ]
check "turned off: not asked, no error; the others still show" $?
req DELETE /api/v1/machines/down; a=$RC
req DELETE /api/v1/machines/down; b=$RC
req GET /api/v1/state
[ "$a$b" = 200404 ] && [ "$(jq_ "[m['name'] for m in d['machines']]")" = "['alpha', 'beta', 'old']" ]
check "removed: 200, then 404, and gone from the state" $?

# 9. groups saved and read back; a bad group is refused
req PUT /api/v1/groups '{"groups":[{"name":"team one","agents":["alpha/abcd","beta/wxyz"]}]}'; a=$RC
req GET /api/v1/groups
[ "$a" = 200 ] && [ "$(jq_ "d['groups'][0]['agents']")" = "['alpha/abcd', 'beta/wxyz']" ]
check "groups: saved and read back" $?
req PUT /api/v1/groups '{"groups":[{"name":"x","agents":["bad"]}]}'; a=$RC
req PUT /api/v1/groups '{"groups":"no"}'; b=$RC
[ "$a$b" = 400400 ]
check "groups: a bad agent name and a bad list: 400" $?

# 9b. settings: the two link addresses, saved and read back in the state; a bad one or an unknown key is refused
req GET /api/v1/settings; a=$RC
[ "$a" = 200 ] && [ "$(jq_ "d")" = "{'grafana': '', 'langfuse': '', 'repo': '', 'owner_key': '', 'install_cmd': '', 'incus_url': '', 'incus_project': '', 'ssh_key': '', 'ssh_user': ''}" ]
check "settings: empty at first, 200" $?
req PUT /api/v1/settings '{"grafana":"https://logs.example.net/","langfuse":" http://127.0.0.1:3000 "}'; a=$RC
req GET /api/v1/state; b=$RC
[ "$a$b" = 200200 ] && [ "$(jq_ "d['settings']")" = "{'grafana': 'https://logs.example.net', 'langfuse': 'http://127.0.0.1:3000', 'repo': '', 'owner_key': '', 'install_cmd': '', 'incus_url': '', 'incus_project': '', 'ssh_key': '', 'ssh_user': ''}" ]
check "settings: saved, trailing slash and spaces cleaned, in the state" $?
req PUT /api/v1/settings '{"grafana":"javascript:alert(1)"}'; a=$RC
req PUT /api/v1/settings '{"grafana":"https://u:p@h.example.net"}'; b=$RC
req PUT /api/v1/settings '{"logs":"https://h.example.net"}'; c=$RC
req PUT /api/v1/settings '{"grafana":"https://h.example.net?q=1"}'; e=$RC
req PUT /api/v1/settings '[1]'; f=$RC
[ "$a$b$c$e$f" = 400400400400400 ]
check "settings: a non-link, a link with a user or query, an unknown key, not an object: 400" $?
req GET /api/v1/settings
[ "$(jq_ "d['grafana']")" = "https://logs.example.net" ]
check "settings: a refused save leaves the saved ones" $?
req PUT /api/v1/settings '{"grafana":"","langfuse":""}'; a=$RC
[ "$a" = 200 ] && [ "$(jq_ "d")" = "{'grafana': '', 'langfuse': '', 'repo': '', 'owner_key': '', 'install_cmd': '', 'incus_url': '', 'incus_project': '', 'ssh_key': '', 'ssh_user': ''}" ]
check "settings: an empty address clears the link" $?

# 10. a foreign Origin is refused; this centre's own origin is taken
a=$(curl -s -o /dev/null -w '%{http_code}' -H 'Origin: http://evil.example' "$B/api/v1/state")
b=$(curl -s -o /dev/null -w '%{http_code}' -H "Origin: $B" "$B/api/v1/state")
[ "$a" = 403 ] && [ "$b" = 200 ]
check "origin: a foreign origin 403, the centre's own 200" $?

# 11. the second centre is reported in other_centres, and this one in the second's
req GET /api/v1/state
[ "$(jq_ "[c['address'] for c in d['other_centres']]")" = "['http://127.0.0.1:$D']" ]
check "other centres: the second centre is reported" $?
s2=$(curl -s "http://127.0.0.1:$D/api/v1/state")
printf '%s' "$s2" | python3 -I -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if [c["address"] for c in d["other_centres"]]==["http://127.0.0.1:'"$C"'"] else 1)'
check "other centres: this centre is reported by the second" $?
# the other centre's machine name is in its entry (the page prints it): a name, not missing
printf '%s' "$s2" | python3 -I -c 'import json,sys; d=json.load(sys.stdin); sys.exit(0 if all(isinstance(c.get("machine"), str) and c["machine"] for c in d["other_centres"]) else 1)'
check "other centres: each entry names its machine" $?
[ "$(python3 -I -c '
import sys; sys.path.insert(0, sys.argv[1]); import find
asked = []
find.ask = lambda addr, port: asked.append((addr, port)) or {"kind": "centre"}
st = {"Self": {"HostName": "me", "TailscaleIPs": ["100.64.0.1"], "Online": True},
      "Peer": {"p": {"HostName": "peer", "TailscaleIPs": ["100.64.0.2"], "Online": True}}}
got = find.scan(st, 8766, [8765, 8766])
print(sorted(asked) == [("100.64.0.1", 8765), ("100.64.0.2", 8765), ("100.64.0.2", 8766)]
      and [c["address"] for c in got["centres"]] == ["http://100.64.0.1:8765", "http://100.64.0.2:8765", "http://100.64.0.2:8766"])
' "$REPO/centre")" = True ]
check "discovery: the centre does not ask its own port on its own addresses; the other ports and machines are asked" $?

# 12. a body over 1 MB: 413; a machine that is not there: 404
head -c 1200000 /dev/zero | tr '\0' 'a' > "$T/big"
a=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' --data-binary "@$T/big" "$B/api/v1/machines")
req PUT /api/v1/machines/nope '{"on":true}'; b=$RC
[ "$a$b" = 413404 ]
check "body over 1 MB: 413; unknown machine: 404" $?

# 13. the repository: the repo field is checked and kept; export has no key; save, then load on an empty centre
#     (machines off, no keys) and on this one (keys kept); a wrong file changes nothing; gh failing; no repo: 400
req PUT /api/v1/settings '{"grafana":"","langfuse":"","repo":"owner/name"}'; a=$RC
req GET /api/v1/settings
[ "$a" = 200 ] && [ "$(jq_ "d['repo']")" = "owner/name" ]
check "repo: set with PUT and read back" $?
codes=""
for r in "-x/y" "a" "a/b/c" ".x/y" "a/" "a b/c"; do req PUT /api/v1/settings "{\"repo\":\"$r\"}"; codes="$codes$RC"; done
req GET /api/v1/settings
[ "$codes" = 400400400400400400 ] && [ "$(jq_ "d['repo']")" = "owner/name" ]
check "repo: a leading dash or dot, one part, three parts, a space: 400; the saved one stays" $?
req PUT /api/v1/settings '{"grafana":"","langfuse":"","repo":""}'; a=$RC
req POST /api/v1/repo/save; b=$RC
req POST /api/v1/repo/load; c=$RC
[ "$a$b$c" = 200400400 ] && [ ! -e "$T/ghstore/centre.json" ]
check "no repo set: save and load give 400, nothing asked of gh" $?
req PUT /api/v1/settings '{"grafana":"","langfuse":"","repo":"owner/name"}'; a=$RC
[ "$a" = 200 ]
check "repo: set again" $?

# export and save: the file has the machines, groups and links, and no key
req POST /api/v1/repo/save; a=$RC
[ "$a" = 200 ] && [ "$(jq_ "d['ok']")" = True ] && [ -s "$T/ghstore/centre.json" ]
check "save: 200 and the file is in the repository" $?
grep -q "$KEYV" "$T/ghstore/centre.json"; [ $? = 1 ]
check "save: the machine's key is not in the file" $?
python3 -I -c 'import json,sys; d=json.load(open(sys.argv[1])); m=d["machines"]
ok = d["format"] == 1 and [x["name"] for x in m] == ["alpha","beta","old"] and all(set(x) == {"name","address","on","added"} for x in m) \
  and d["groups"][0]["name"] == "team one" and set(d["links"]) == {"grafana","langfuse"}
sys.exit(0 if ok else 1)' "$T/ghstore/centre.json"
check "save: the file holds the machines, the groups and the links, with the fields listed" $?

# save then load on a second, empty centre (its own HOME): the machines come in off, with no keys
E=$(freeport)
env HOME="$T/home4" CENTRE_GH="$T/gh" FAKE_GH_DIR="$T/ghstore" AGENT_KIT_FIND_PORTS="$P1,$P2,$OLD" \
  AGENT_KIT_FIND_CENTRE_PORTS="$C,$D" PATH="$BIN:$PATH" python3 -I -B "$REPO/centre/centre.py" --port "$E" > "$T/centre3.log" 2>&1 &
PIDS="$PIDS $!"
for _ in $(seq 50); do curl -s -o /dev/null "http://127.0.0.1:$E/" 2>/dev/null && break; sleep 0.1; done
MAIN=$B; B="http://127.0.0.1:$E"
req PUT /api/v1/settings '{"grafana":"","langfuse":"","repo":"owner/name"}'; a=$RC
req POST /api/v1/repo/load; b=$RC
req GET /api/v1/state
[ "$a$b" = 200200 ] && [ "$(jq_ "[m['name'] for m in d['machines']]")" = "['alpha', 'beta', 'old']" ] \
  && [ "$(jq_ "[m['on'] for m in d['machines']]")" = "[False, False, False]" ] \
  && [ "$(jq_ "[m['has_key'] for m in d['machines']]")" = "[False, False, False]" ] \
  && [ "$(jq_ "[g['name'] for g in d['groups']]")" = "['team one']" ]
check "load on an empty centre: machines and groups come in; machines off, no keys" $?
grep -rq "$KEYV" "$T/home4"; [ $? = 1 ]
check "load on an empty centre: no key anywhere in its folder" $?
B=$MAIN

# load on this centre: the machines are the same, the keys are kept
req POST /api/v1/repo/load; a=$RC
req GET /api/v1/state
[ "$a" = 200 ] && [ "$(jq_ "[m['name'] for m in d['machines']]")" = "['alpha', 'beta', 'old']" ] \
  && [ "$(jq_ "d['machines'][2]['has_key']")" = True ] && grep -q "$KEYV" "$HOME/.config/agent-kit/centre/keys.json"
check "load on this centre: the keys are kept" $?

# a wrong file changes nothing: a bad name, a wrong format, not JSON
printf '%s' '{"format":1,"machines":[{"name":"bad name!","address":"http://127.0.0.1:1","on":true,"added":"x"}],"groups":[],"links":{}}' > "$T/ghstore/centre.json"
req POST /api/v1/repo/load; a=$RC
printf '%s' '{"format":2}' > "$T/ghstore/centre.json"
req POST /api/v1/repo/load; b=$RC
printf '%s' 'not json' > "$T/ghstore/centre.json"
req POST /api/v1/repo/load; c=$RC
req GET /api/v1/state
[ "$a$b$c" = 400400502 ] && [ "$(jq_ "[m['name'] for m in d['machines']]")" = "['alpha', 'beta', 'old']" ] \
  && [ "$(jq_ "d['machines'][2]['has_key']")" = True ] && [ "$(jq_ "d['groups'][0]['name']")" = "team one" ]
check "wrong file: a bad name, a wrong format, not JSON: refused, nothing changed" $?
req POST /api/v1/repo/save; a=$RC
[ "$a" = 200 ]
check "the good file is written again" $?

# gh failing: 502 with the error text, the centre still answers
touch "$T/ghstore/fail"
req POST /api/v1/repo/save; a=$RC; ea=$(jq_ "d['error']"); oka=$(jq_ "d['ok']")
req POST /api/v1/repo/load; b=$RC
req GET /api/v1/state; c=$RC
rm -f "$T/ghstore/fail"
[ "$a$b$c" = 502502200 ] && [ "$oka" = False ] && [ -n "$ea" ]
check "gh failing: 502 with ok false, no crash, the centre answers" $?

# 16a. the survey: only a machine that lets the centre in is listed; one that does not is a line of the log
req POST /api/v1/survey; a=$RC
[ "$a" = 200 ] && [ "$(jq_ "d['machines'], d['asked'], [(x['name'], x['address'], x['error']) for x in d['log']]")" \
  = "([], 2, [('this-box', '127.0.0.1', 'the fake does not know this command'), ('peer-a', '127.0.0.1', 'the fake does not know this command')])" ] \
  && [ "$(jq_ "all(isinstance(x['time'], int) for x in d['log'])")" = True ]
check "survey: no machine lets the centre in: the list is empty and each machine is a line of the log" $?
grep -q '^survey: peer-a (127.0.0.1): the fake does not know this command$' "$T/centre.log"
check "survey: the line is in the centre's own output too" $?
printf 'user\tagent\t/home/agent\nkit\tnew\tv2.0.0\nend\n' > "$T/fake/survey"
req POST /api/v1/survey; a=$RC; rm -f "$T/fake/survey"
[ "$a" = 200 ] && [ "$(jq_ "[(m['ok'], m['sign_in'], m['users'][0]['user']) for m in d['machines']], d['asked'], len(d['log'])")" \
  = "([(True, 'root', 'agent')], 2, 2)" ]
check "survey: a machine that lets the centre in is listed; the log keeps its earlier lines" $?
req GET /api/v1/survey
[ "$RC" = 200 ] && [ "$(jq_ "len(d['machines']), len(d['log'])")" = "(1, 2)" ]
check "survey: the last answer and the log are read with no call to a machine" $?

# 17. the centre's key is made once, with its modes; no private part in any answer
LEAKS=0; SECRETS='PRIVFAKE|PW-test-7731|KEYFAKE-0'
leaks() { grep -Eq "$SECRETS" "$T/body" && LEAKS=1; }
req GET /api/v1/ssh/key; a=$RC; pub=$(jq_ 'd["public"]'); leaks
req GET /api/v1/ssh/key; b=$RC; leaks
[ "$a$b" = 200200 ] && [ "${pub%% *}" = ssh-ed25519 ] && [ "$(wc -l < "$T/fake/keygen.log")" = 1 ] && [ "$LEAKS" = 0 ] \
  && [ "$(stat -c %a "$HOME/.config/agent-kit/centre/ssh")" = 700 ] && [ "$(stat -c %a "$HOME/.config/agent-kit/centre/ssh/id_ed25519")" = 600 ]
check "ssh key: made once, folder 700, private 600, no private part in any answer" $?

# 18. plan: the steps as data, in order; the owner's key step only when a key is set; a wrong address refused
python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import ssh_add, store
p = ssh_add.plan("box.example", "agent", ssh_add.INSTALL_CMD, "ssh-ed25519 AAAA agent-kit-centre", "ssh-ed25519 BBBB me")
q = ssh_add.plan("box.example", "agent", "", "ssh-ed25519 AAAA agent-kit-centre")
ok = [s["step"] for s in p] == ["authorize centre key", "authorize owner key", "install", "read key"]
ok = ok and [s["step"] for s in q] == ["authorize centre key", "install", "read key"]
ok = ok and [s["timeout"] for s in p] == [20, 20, 900, 20] and [s["sign_in"] for s in p] == [True, True, False, False]
ok = ok and "install.sh" in ssh_add.INSTALL_CMD and "~/start.sh" in ssh_add.INSTALL_CMD and "\n" not in ssh_add.INSTALL_CMD
try:
    ssh_add.plan("-oProxyCommand=x", "agent", "", "ssh-ed25519 AAAA")
    ok = False
except store.Invalid:
    pass
sys.exit(0 if ok else 1)' "$REPO/centre"
check "plan: the steps in order, the owner's key step only when set, a wrong address refused" $?

# 19. the owner's key and the install command: checked; a good pair is kept and read back
codes=""; long=$(head -c 501 /dev/zero | tr '\0' a)
for body in '{"owner_key":"ssh-dss AAAAB3Nza"}' '{"owner_key":"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIabc\nevil"}' \
  '{"owner_key":"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIabc bad/comment"}' '{"install_cmd":"a\nb"}' '{"install_cmd":"a\u0000b"}' \
  "{\"install_cmd\":\"$long\"}"; do
  req PUT /api/v1/settings "$body"; codes="$codes$RC"
done
KEYOK="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIabcdef owner@box"
req PUT /api/v1/settings "{\"grafana\":\"\",\"langfuse\":\"\",\"repo\":\"\",\"owner_key\":\"$KEYOK\",\"install_cmd\":\"\"}"; a=$RC
req GET /api/v1/settings
[ "$codes" = 400400400400400400 ] && [ "$a" = 200 ] && [ "$(jq_ "d['owner_key']")" = "$KEYOK" ] && [ "$(jq_ "d['install_cmd']")" = "" ]
check "settings: a bad owner key or install command 400 (two lines, a NUL, 501 characters); a good owner key kept" $?

# a helper: wait for a job to end; every answer on the way is checked for secrets
wait_job() {
  STATE=running
  for _ in $(seq 150); do
    req GET "/api/v1/machines/ssh/$1"; leaks; STATE=$(jq_ 'd["state"]')
    [ "$STATE" = running ] || break
    sleep 0.1
  done
}

# 20. a full run with no password: the centre's key, the owner's key, the install, the key read; the machine is added
: > "$T/fake/ssh.log"
req POST /api/v1/machines/ssh '{"name":"gamma","address":"ssh-box"}'; a=$RC; leaks; job=$(jq_ 'd["id"]')
wait_job "$job"
steps=$(jq_ "[s['step']+'='+str(s['ok']) for s in d['steps']]")
[ "$a" = 202 ] && [ "$STATE" = done ] && [ "$steps" = "['authorize centre key=True', 'authorize owner key=True', 'install=True', 'read key=True', 'add machine=True']" ] \
  && python3 -I -c 'import json,sys
c = sys.argv[1]; L = [json.loads(x) for x in open(sys.argv[2])]; a = L[0]["argv"]
m = {x["name"]: x for x in json.load(open(c + "/machines.json"))}; k = json.load(open(c + "/keys.json"))
ok = len(L) == 4 and not any(x["askpass"] for x in L) and "BatchMode=yes" in a and a[a.index("-i") + 1].endswith("/ssh/id_ed25519")
ok = ok and "agent@ssh-box" in a and a[-2] == "--" and "install.sh && chmod" in L[2]["argv"][-1]
ok = ok and m["gamma"]["address"] == "http://ssh-box:8765" and m["gamma"]["on"] is True and k["gamma"] == "KEYFAKE-0123456789abc"
sys.exit(0 if ok else 1)' "$HOME/.config/agent-kit/centre" "$T/fake/ssh.log"
check "ssh add: a full run adds the machine, on, with the key the fake printed; the steps and the commands are right" $?

# 21. a failing install: the step is named, nothing is added
printf 'install\n' > "$T/fake/fail"
req POST /api/v1/machines/ssh '{"name":"gamma2","address":"ssh-box2"}'; a=$RC; leaks; job=$(jq_ 'd["id"]')
wait_job "$job"; rm -f "$T/fake/fail"
last=$(jq_ "d['steps'][-1]['step']+'|'+str(d['steps'][-1]['ok'])+'|'+d['error']")
[ "$a" = 202 ] && [ "$STATE" = failed ] && [ "$last" = "install|False|boom: install failed" ] \
  && ! grep -q '"gamma2"' "$HOME/.config/agent-kit/centre/machines.json" && ! grep -q 'gamma2' "$HOME/.config/agent-kit/centre/keys.json"
check "ssh add: a failing install names its step, adds nothing" $?

# 22. a password: asked once, used only for the two sign-in steps through SSH_ASKPASS; not in the fake's log, not under
#     HOME, not in any answer; the temp folder is gone; the install and the rest use the key
PW='PW-test-7731-secret'; printf '%s' "$PW" > "$T/expect"
req PUT /api/v1/settings "{\"grafana\":\"\",\"langfuse\":\"\",\"repo\":\"\",\"owner_key\":\"$KEYOK\",\"install_cmd\":\"./install.sh --owner-test\"}"
: > "$T/fake/ssh.log"; LEAKS=0
req POST /api/v1/machines/ssh "{\"name\":\"delta\",\"address\":\"ssh-box3\",\"user\":\"helper\",\"password\":\"$PW\"}"; a=$RC
grep -q "$PW" "$T/body" && LEAKS=1; job=$(jq_ 'd["id"]')
wait_job "$job"
[ "$a" = 202 ] && [ "$STATE" = done ] && [ "$LEAKS" = 0 ] \
  && python3 -I -c 'import json,sys; L = [json.loads(x) for x in open(sys.argv[1])]
ok = len(L) == 4 and [x["askpass"] for x in L] == [True, True, False, False] and "helper@ssh-box3" in L[0]["argv"]
ok = ok and "PubkeyAuthentication=no" in L[0]["argv"] and "BatchMode=yes" not in L[1]["argv"] and "--owner-test" in L[2]["argv"][-1]
sys.exit(0 if ok else 1)' "$T/fake/ssh.log"
check "password: the two sign-in steps use SSH_ASKPASS; the rest use the key; the install is the one set" $?
if grep -rqs "$PW" "$HOME" "$T/fake/ssh.log" "$T/centre.log" "$T/body" "$T/tmp"; then PWLEAK=1; else PWLEAK=0; fi
[ "$PWLEAK" = 0 ] && [ -z "$(ls -A "$T/tmp")" ]
check "password: not in the fake's log, the centre's log, any file under HOME or any answer; the temp folder is gone" $?
[ "$LEAKS" = 0 ] && ! grep -rqs 'PRIVFAKE' "$T/fake/ssh.log"
check "secrets: no private key, API key or password in any SSH answer" $?

# 23. a wrong address, user or password, or a name there already: refused before any ssh runs (the fake's log stays empty)
: > "$T/fake/ssh.log"; codes=""
for body in '{"name":"omega","address":"-oProxyCommand=x"}' '{"name":"omega","address":"a b"}' '{"name":"omega","address":"a;b"}' \
  '{"name":"omega","address":"box","user":"Root"}' '{"name":"omega","address":"box","user":"1abc"}' \
  '{"name":"omega","address":"box","user":"a b"}' '{"name":"gamma","address":"box"}' '{"name":"omega","address":"box","password":"x\ny"}'; do
  req POST /api/v1/machines/ssh "$body"; codes="$codes$RC"
done
[ "$codes" = 400400400400400400400400 ] && [ ! -s "$T/fake/ssh.log" ]
check "ssh add: a wrong address, user or password, a name there already: 400, no ssh run" $?

# 24. Incus: a local TLS fake (its own certificate, pinned by the centre as server.crt) answers the Incus API. The centre's
#     client certificate and key are in its incus folder. Settings are checked; names and images are checked before any
#     request (the fake's log does not grow); the method, path, project and body reach the fake; a failure is 502; the
#     certificate and key text never reaches an answer, the centre's log or the fake's log.
INC="$T/incus"; IF="$HOME/.config/agent-kit/centre/incus"
mkdir -p "$INC" "$IF" && chmod 700 "$IF" && touch "$INC/requests.log"
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$INC/server.key" -out "$INC/server.crt" -days 2 -subj /CN=127.0.0.1 \
  -addext "subjectAltName=IP:127.0.0.1" 2>/dev/null
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$IF/client.key" -out "$IF/client.crt" -days 2 -subj /CN=centre 2>/dev/null
chmod 600 "$IF/client.key"; cp "$INC/server.crt" "$IF/server.crt"
cat > "$INC/fake.py" <<'PY'
import http.server, json, os, ssl, sys
port, log, d = int(sys.argv[1]), sys.argv[2], sys.argv[3]
ANS = {
    "/1.0/instances": [{"name": "m1", "status": "Running", "type": "container", "profiles": ["default"]}],
    "/1.0/profiles": [{"name": "default", "description": "d", "config": {"cloud-init.user-data": "#cloud-config\npackages: [git]"}}],
    "/1.0/images": [{"fingerprint": "abc123def4567890", "properties": {"description": "Debian 13"}, "aliases": [{"name": "debian/13"}]}],
}
class H(http.server.BaseHTTPRequestHandler):
    def handle_any(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n).decode() if n else ""
        with open(log, "a") as f:
            f.write(json.dumps({"method": self.command, "path": self.path, "body": body}) + "\n")
        path = self.path.split("?")[0]
        if os.path.exists(os.path.join(d, "fail")):
            obj, code = {"type": "error", "error": "the fake failed", "error_code": 500}, 500
        elif self.command == "GET" and path in ANS:
            obj, code = {"type": "sync", "metadata": ANS[path]}, 200
        elif self.command in ("POST", "PUT"):
            obj, code = {"type": "async", "metadata": {"id": "op1"}}, 202
        else:
            obj, code = {"type": "error", "error": "not found"}, 404
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)
    do_GET = do_POST = do_PUT = handle_any
    def log_message(self, *a):
        return
srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), H)
ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
ctx.load_cert_chain(os.path.join(d, "server.crt"), os.path.join(d, "server.key"))
srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
srv.serve_forever()
PY
IP=$(freeport)
python3 -I -B "$INC/fake.py" "$IP" "$INC/requests.log" "$INC" > "$INC/fake.out" 2>&1 &
PIDS="$PIDS $!"
for _ in $(seq 50); do curl -sk -o /dev/null "https://127.0.0.1:$IP/" 2>/dev/null && break; sleep 0.1; done
SET="{\"grafana\":\"\",\"langfuse\":\"\",\"repo\":\"\",\"owner_key\":\"\",\"install_cmd\":\"\",\"incus_url\":\"https://127.0.0.1:$IP\",\"incus_project\":\"dash-1\"}"
nlog() { wc -l < "$INC/requests.log"; }
last() { python3 -I -c 'import json,sys; r=json.loads(open(sys.argv[1]).read().splitlines()[-1]); print(r["method"], r["path"], r["body"])' "$INC/requests.log"; }

req PUT /api/v1/settings '{"grafana":"","langfuse":"","repo":"","owner_key":"","install_cmd":"","incus_url":"http://127.0.0.1:1","incus_project":""}'; a=$RC
req PUT /api/v1/settings '{"grafana":"","langfuse":"","repo":"","owner_key":"","install_cmd":"","incus_url":"https://127.0.0.1:1","incus_project":"a b"}'; b=$RC
req PUT /api/v1/settings "$SET"; c=$RC
[ "$a$b$c" = 400400200 ]
check "incus settings: http:// and a project with a space refused; the https address with project dash-1 saved" $?

req GET /api/v1/incus; a=$RC
[ "$a" = 200 ] && [ "$(jq_ "d['files']['client.key']")" = True ] && [ "$(jq_ "d['project']")" = dash-1 ] && ! grep -q 'PRIVATE KEY\|BEGIN CERTIFICATE' "$T/body"
check "incus: the address, project and the files present; no key or certificate text in the answer" $?

n0=$(nlog)
req GET /api/v1/incus/instances; a=$RC
[ "$a" = 200 ] && [ "$(jq_ "[i['name'] for i in d['instances']]")" = "['m1']" ] && [ "$(nlog)" = "$((n0+1))" ] \
  && last | grep -q '^GET /1.0/instances?recursion=1&project=dash-1 '
check "incus instances: 200, the machine read, GET with the project" $?

req GET /api/v1/incus/profiles; a=$RC
[ "$a" = 200 ] && [ "$(jq_ "'packages' in d['profiles'][0]['cloud_init']")" = True ]
check "incus profiles: 200, the cloud-init of the profile read" $?

req GET /api/v1/incus/images; a=$RC
[ "$a" = 200 ] && [ "$(jq_ "d['images'][0]['aliases']")" = "['debian/13']" ]
check "incus images: 200, the alias and fingerprint read" $?

n0=$(nlog)
req POST /api/v1/incus/instances '{"name":"w1","profile":"default","image":"abc123def4567890"}'; a=$RC
[ "$a" = 201 ] && last | grep -q '^POST /1.0/instances?project=dash-1 .*"fingerprint": "abc123def4567890"' && last | grep -q '"name": "w1"'
check "incus create: 201, a POST with the profile, the fingerprint and start" $?

req POST /api/v1/incus/instances/m1/start; a=$RC
[ "$a" = 200 ] && last | grep -q '^PUT /1.0/instances/m1/state?project=dash-1 .*"action": "start"'
check "incus start: 200, a PUT of the state with start" $?

req POST /api/v1/incus/instances/m1/stop; a=$RC
[ "$a" = 200 ] && last | grep -q '"action": "stop"'
check "incus stop: 200, a PUT of the state with stop" $?

n0=$(nlog); codes=""
for body in '{"name":"../x","profile":"default","image":"abc123def4567890"}' '{"name":"a b","profile":"default","image":"abc123def4567890"}' \
  '{"name":"a?b","profile":"default","image":"abc123def4567890"}' '{"name":"w2","profile":"default","image":"../etc"}' \
  '{"name":"w3","profile":"default","image":"/x"}' '{"name":"w4","profile":"a/b","image":"abc123def4567890"}'; do
  req POST /api/v1/incus/instances "$body"; codes="$codes$RC"
done
for n in '..%2Fx' 'a%20b' 'a%3Fb'; do req POST "/api/v1/incus/instances/$n/start"; codes="$codes$RC"; done
[ "$codes" = 400400400400400400400400400 ] && [ "$(nlog)" = "$n0" ]
check "incus names and images: a wrong name or image is 400 and no request reaches Incus" $?

req PUT /api/v1/settings '{"grafana":"","langfuse":"","repo":"","owner_key":"","install_cmd":"","incus_url":"","incus_project":""}'; a=$RC
req GET /api/v1/incus/instances; b=$RC
[ "$a$b" = 200400 ] && [ "$(jq_ "d['error']")" = "Incus is not set: name its address in the settings" ]
check "incus not set: the instances are 400 with the text that says so" $?
req PUT /api/v1/settings "$SET"

touch "$INC/fail"; req GET /api/v1/incus/instances; a=$RC
rm -f "$INC/fail"
[ "$a" = 502 ] && [ "$(jq_ "d['ok']")" = False ] && [ "$(jq_ "d['error']")" = "the fake failed" ]
check "incus failure: 502 with the server's error text, ok false" $?

chmod 644 "$IF/client.key"; req GET /api/v1/incus/instances; a=$RC
chmod 600 "$IF/client.key"
[ "$a" = 502 ] && [ "$(jq_ "d['error']")" = "client.key must give no access to the group or others (chmod 600)" ]
check "incus key: a key readable by others is refused (502), nothing sent" $?

[ "$(python3 -I -c 'import sys, ssl; sys.path.insert(0, sys.argv[1]); import incus
c = incus.ssl_context(sys.argv[2]); print(c.verify_mode == ssl.CERT_REQUIRED and c.check_hostname is False)' "$REPO/centre" "$HOME")" = True ] \
  && ! grep -q 'CERT_NONE' "$REPO/centre/incus.py"
check "incus tls: the context checks the server (CERT_REQUIRED), no CERT_NONE anywhere" $?

OWNER="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOWNERKEYFAKE owner@test"
req PUT /api/v1/settings "{\"grafana\":\"\",\"langfuse\":\"\",\"repo\":\"\",\"owner_key\":\"$OWNER\",\"install_cmd\":\"\",\"incus_url\":\"https://127.0.0.1:$IP\",\"incus_project\":\"dash-1\"}"; a=$RC
req POST /api/v1/incus/instances '{"name":"w2","profile":"default","image":"abc123def4567890"}'; b=$RC
body=$(last); req PUT /api/v1/settings "$SET"; c=$RC
[ "$a$b$c" = 200201200 ] && [ "${body#POST /1.0/instances}" != "$body" ] \
  && ! printf '%s' "$body" | grep -q -e 'ssh-' -e 'AAAA' -e 'OWNERKEYFAKE' -e 'agent-kit-centre'
check "incus no key: with the owner key set, a machine made in Incus gets no key, neither the owner's nor the centre's" $?

[ "$(python3 -I -c '
import json, signal, socket, sys, threading
signal.alarm(20)   # a request that ignores the timeout fails the case instead of hanging the suite
sys.path.insert(0, sys.argv[1]); import incus
seen = []
def fake(req, ctx, timeout):
    seen.append((req.get_method(), timeout, json.loads(req.data) if req.data else None))
    return b"{\"metadata\": {}}"
s = {"incus_url": "https://127.0.0.1:1", "incus_project": ""}
incus.OPEN = fake
incus.state(sys.argv[2], s, "m1", "stop"); incus.instances(sys.argv[2], s)
limits = seen == [("PUT", 15, {"action": "stop", "timeout": 30}), ("GET", 15, None)]
incus.OPEN = None; incus.TIMEOUT = 1
lsn = socket.socket(); lsn.bind(("127.0.0.1", 0)); lsn.listen(1)
held = []
threading.Thread(target=lambda: held.append(lsn.accept()), daemon=True).start()
got = incus.instances(sys.argv[2], dict(s, incus_url="https://127.0.0.1:%d" % lsn.getsockname()[1]))
print(limits and got["ok"] is False and got["error"].startswith("Incus did not answer"))
' "$REPO/centre" "$HOME")" = True ]
check "incus time limits: each request waits 15 s, a start or stop asks Incus for 30 s; a silent server is given up, not hung" $?

MARK="INCUSMARK$RANDOM$RANDOM"; printf '\n%s\n' "$MARK" >> "$IF/client.crt"; printf '\n%s\n' "$MARK" >> "$IF/client.key"
req GET /api/v1/incus/instances; a=$RC
req POST /api/v1/incus/instances/m1/stop; b=$RC
if grep -rqs "$MARK" "$T/body" "$T/centre.log" "$T/centre2.log" "$INC/requests.log" "$INC/fake.out"; then LEAK=1; else LEAK=0; fi
[ "$a$b" = 200200 ] && [ "$LEAK" = 0 ]
check "incus secrets: the certificate and key files never reach an answer, the centre's log or the fake's log" $?

echo "passed $PASS, failed $FAIL"; [ "$FAIL" = 0 ]
