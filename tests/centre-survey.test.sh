#!/usr/bin/env bash
# tests/centre-survey.test.sh - the centre's survey of a machine over SSH (centre/survey.py). A fake ssh
# (CENTRE_SSH) runs the script it gets on stdin with bash, in a fake home of the "machine" named by the address and
# with a fake tmux on PATH: so the real script is run, and never the user's tmux. The survey must write nothing.
# Exit 0 when every case passes.
REPO=$(cd "$(dirname "$0")/.." && pwd -P)
T=$(mktemp -d) || exit 1; T=$(cd "$T" && pwd -P)
trap 'rm -rf "$T"' EXIT
export HOME="$T/home"; mkdir -p "$HOME" "$T/bin" "$T/m" || exit 1
PASS=0; FAIL=0
check() { if [ "$2" = 0 ]; then PASS=$((PASS+1)); echo "ok   - $1"; else FAIL=$((FAIL+1)); echo "FAIL - $1"; fi; }
# the fake tmux prints the sessions of the machine's file "tmux"
printf '#!/bin/sh\n[ -f "$HOME/tmux" ] && cat "$HOME/tmux"\nexit 0\n' > "$T/bin/tmux"; chmod +x "$T/bin/tmux"
cat > "$T/ssh" <<'PY'
#!/usr/bin/env python3
import json, os, subprocess, sys
d = os.environ["FAKE_DIR"]
argv = sys.argv[1:]
target = [a for a in argv if "@" in a][0]
user, host = target.split("@")
with open(os.path.join(d, "ssh.log"), "a") as f:
    f.write(json.dumps(argv) + "\n")
home = os.path.join(d, "m", host)
refused = open(os.path.join(home, "refuse")).read().split() if os.path.exists(os.path.join(home, "refuse")) else []
if not os.path.isdir(home) or user in refused:
    sys.stderr.write("Warning: noise\n%s: Permission denied (publickey).\n" % target)
    sys.exit(255)
if argv[-1] != "bash -s":
    sys.stderr.write("the fake does not know this command\n")
    sys.exit(1)
env = {"HOME": home, "PATH": os.path.join(d, "bin") + ":/usr/bin:/bin"}
sys.exit(subprocess.run(["bash", "-s"], stdin=sys.stdin, env=env).returncode)
PY
chmod +x "$T/ssh"
export CENTRE_SSH="$T/ssh" FAKE_DIR="$T"
# run HOST [SETTINGS JSON]: the survey's answer as JSON in $T/out
run() { python3 -I -c 'import json,sys; sys.path.insert(0, sys.argv[1]); import survey
json.dump(survey.run(sys.argv[2], json.loads(sys.argv[3])), open(sys.argv[4], "w"))' "$REPO/centre" "$1" "${2:-{\}}" "$T/out"; }
jq_() { python3 -I -c 'import json,sys; d=json.load(open(sys.argv[2])); print(eval(sys.argv[1]))' "$1" "$T/out" 2>/dev/null; }

# the machines: empty (no kit); old (the old kit, two profiles, a session, a secret in a profile); new; shut (refuses
# everyone); userbox (refuses root)
mkdir -p "$T/m/empty" "$T/m/old/.agent-kit/launcher" "$T/m/old/.config/agent-kit/profiles" "$T/m/old/.config/agent-kit/projects" \
  "$T/m/old/.claude" "$T/m/new/.agent-kit/kit" "$T/m/new/.config/agent-kit/sessions" "$T/m/new/.config/gh" "$T/m/shut" "$T/m/userbox"
printf 'NAME=web\nDIR=/home/a/web\nROLE=development\nENVS=TOKEN=SECRETMARK\n' > "$T/m/old/.config/agent-kit/profiles/ab12.env"
printf 'ROLE=qa\n' > "$T/m/old/.config/agent-kit/projects/api.env"
printf 'agent-ab12\t/home/a/web\nscratch\t/tmp\n' > "$T/m/old/tmux"
printf '{"x":1}\n' > "$T/m/old/.claude/.credentials.json"
: > "$T/m/new/.agent-kit/kit/__main__.py"; printf 'v2.0.0\nmore\n' > "$T/m/new/.agent-kit/VERSION"
printf '{}\n' > "$T/m/new/.config/agent-kit/config.json"; printf '{}\n' > "$T/m/new/.config/agent-kit/sessions/inzn.json"
printf 'inzn\t/home/a/kit\n' > "$T/m/new/tmux"; printf 'github.com:\n' > "$T/m/new/.config/gh/hosts.yml"
printf 'root agent\n' > "$T/m/shut/refuse"; printf 'root\n' > "$T/m/userbox/refuse"
before=$(cd "$T/m" && find . | sort | xargs ls -ld --time-style=+%s 2>/dev/null | md5sum)

run empty
[ "$(jq_ "d['ok'], d['sign_in'], len(d['users']), d['users'][0]['kit'], d['users'][0]['sessions'], d['users'][0]['claude']")" = "(True, 'root', 1, 'none', [], False)" ]
check "a machine with no kit: signed in as root, one user, no kit, no session, not signed in to Claude" $?

run old
[ "$(jq_ "d['users'][0]['kit'], d['users'][0]['old_files'], d['users'][0]['claude'], d['users'][0]['gh']")" = "('old', ['profiles/ab12', 'projects/api'], True, False)" ] \
  && [ "$(jq_ "[(s['name'], s['folder'], s['kind']) for s in d['users'][0]['sessions']]")" = "[('agent-ab12', '/home/a/web', 'old'), ('scratch', '/tmp', 'other')]" ]
check "the old kit: its kind, the names of its files, its session marked old and another session marked other" $?
! grep -q SECRETMARK "$T/out"
check "the old kit: no value of a profile leaves the machine" $?

run new
[ "$(jq_ "d['users'][0]['kit'], d['users'][0]['version'], d['users'][0]['config'], d['users'][0]['gh'], d['users'][0]['sessions']")" = "('new', 'v2.0.0', True, True, [{'name': 'inzn', 'folder': '/home/a/kit', 'kind': 'new'}])" ]
check "the new kit: its version from VERSION, the config, the sign-in of gh, its session marked new" $?

run shut '{"ssh_user":"agent"}'
[ "$(jq_ "d['ok'], d['error']")" = "(False, 'agent@shut: Permission denied (publickey).')" ]
check "a machine that refuses: not ok, the last line of ssh's error" $?

: > "$T/ssh.log"; run userbox '{"ssh_user":"agent","ssh_key":"/keys/id_x"}'
[ "$(jq_ "d['ok'], d['sign_in']")" = "(True, 'agent')" ] && python3 -I -c 'import json,sys
L=[json.loads(x) for x in open(sys.argv[1])]
ok = len(L) == 2 and "root@userbox" in L[0] and "agent@userbox" in L[1]
ok = ok and all("BatchMode=yes" in a and a[a.index("-i") + 1] == "/keys/id_x" and "IdentitiesOnly=yes" in a for a in L)
sys.exit(0 if ok else 1)' "$T/ssh.log"
check "root refused: the user of the settings is tried; each call has BatchMode and the key file of the settings" $?

: > "$T/ssh.log"; run '-oProxyCommand=x'
[ "$(jq_ "d['ok']")" = False ] && [ ! -s "$T/ssh.log" ]
check "an address that starts with a dash: refused, ssh is not run" $?

after=$(cd "$T/m" && find . | sort | xargs ls -ld --time-style=+%s 2>/dev/null | md5sum)
[ "$before" = "$after" ]
check "the survey wrote nothing on any machine" $?

python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import survey
ok = survey.parse("user\ta\t/home/a\nkit\told\t\n") is None and survey.parse("junk\nend\n") == []
ok = ok and survey.parse("kit\tnew\tv1\nuser\ta\t/h\ntmux\tx\ty\nkit\tweird\t1\nend")[0]["kit"] == "none"
sys.exit(0 if ok else 1)' "$REPO/centre"
check "parse: an output cut before its end is no answer; a line of an unknown shape is skipped" $?

python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import survey
seen, lines = survey.split([("a", "192.0.2.1"), ("b", "192.0.2.2"), ("c", "192.0.2.3")],
    [{"ok": True, "sign_in": "root", "users": []}, {"ok": False, "error": "Permission denied (publickey)."}, {"ok": False}], 1700000000.9)
ok = seen == {"192.0.2.1": {"ok": True, "sign_in": "root", "users": [], "name": "a", "address": "192.0.2.1"}}
ok = ok and lines == [{"time": 1700000000, "name": "b", "address": "192.0.2.2", "error": "Permission denied (publickey)."},
                      {"time": 1700000000, "name": "c", "address": "192.0.2.3", "error": "no answer"}]
sys.exit(0 if ok else 1)' "$REPO/centre"
check "split: a machine that let the centre in is in the list; one that did not is a line of the log with its error" $?

echo "passed $PASS, failed $FAIL"; [ "$FAIL" = 0 ]
