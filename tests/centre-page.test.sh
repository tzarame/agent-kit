#!/usr/bin/env bash
# tests/centre-page.test.sh - the control centre's page (centre/page.html): served with its policy, the parts and states
# it names are in it, the rules of the page hold in its source (no innerHTML, no eval, no document.write, no outside
# address in src or href), its script parses, the address builder and the state word work on a fake document (when node
# is on PATH). The centre runs on a free port of 127.0.0.1 with HOME a temp folder and a fake tailscale on PATH.
# Exit 0 when every case passes.
REPO=$(cd "$(dirname "$0")/.." && pwd -P)
PAGE="$REPO/centre/page.html"
# node: on PATH, else the one the editor's server keeps in the real home (HOME is replaced below)
REAL_HOME=$(getent passwd "$(id -un)" | cut -d: -f6)
command -v node >/dev/null 2>&1 || for d in "$REAL_HOME"/.vscode-server/cli/servers/Stable-*/server; do
  [ -x "$d/node" ] && { PATH="$d:$PATH"; break; }
done
T=$(mktemp -d) || exit 1; T=$(cd "$T" && pwd -P)
cleanup() { [ -n "$SRV" ] && kill "$SRV" 2>/dev/null; rm -rf "$T"; }
trap cleanup EXIT
export HOME="$T/home"; BIN="$T/bin"; mkdir -p "$HOME" "$BIN" || exit 1
printf '#!/bin/sh\nexit 1\n' > "$BIN/tailscale"; chmod +x "$BIN/tailscale"
export SHELL=/bin/sh
PORT=$(python3 -I -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')
B="http://127.0.0.1:$PORT"
PASS=0; FAIL=0; SRV=""
check() { if [ "$2" = 0 ]; then PASS=$((PASS+1)); echo "ok   - $1"; else FAIL=$((FAIL+1)); echo "FAIL - $1"; fi; }
# the text of the script of the page, for the source rules
script() { python3 -I -c 'import sys,re; s=open(sys.argv[1],encoding="utf-8").read(); m=re.search(r"<script>(.*?)</script>", s, re.S); sys.stdout.write(m.group(1))' "$PAGE"; }

# 1. the page served at / with its policy, and the parts and states it names
python3 -I "$REPO/centre/centre.py" --port "$PORT" > "$T/server.log" 2>&1 &
SRV=$!
for _ in $(seq 50); do curl -s -o /dev/null "$B/api/v1/hello" && break; sleep 0.1; done
hdr=$(curl -s -D - -o "$T/page" "$B/")
code=$(printf '%s' "$hdr" | head -1 | tr -d '\r')
printf '%s' "$code" | grep -q ' 200' && printf '%s' "$hdr" | grep -qi "^content-security-policy: .*default-src 'self'" \
  && grep -q '<title>Control centre' "$T/page"
check "page: 200 with the policy header and the title" $?
for w in "By machine" "By group" "Found on the network" "Add a machine" "Create group" "Another centre is running on" \
  "not in this version" "does not answer" "key refused" "older version" "Turn off" "Turn on" "Remove" "Machine tools of " \
  "Terminal" "Telemetry" "Costs" "estimate at API prices" "Update all" "are outdated" "update to " "up to date" "restart to apply" "Update" "Notes" "Console" "Files" "New agent" "tmux sessions" "Delete group" "Take out" "Add to group" \
  "Data arrives" "Check" "Last record" "Logs in Grafana" "Traces in Langfuse" "Links of the agents" "Save links" \
  "Repository for the settings (owner/name)" "Save to the repository" "Load from the repository" \
  "Add over SSH" "asked once, not kept" "Install and add" "Copy" "Owner's public key" "Install command" \
  "Incus address (https://...)" "Incus project" "Incus is not set: name its address in the settings" "Incus machines" \
  "Make a machine" "Cloud-init of the profile" "Refresh"; do
  grep -qF "$w" "$T/page"; check "page: names $w" $?
done
cmp -s "$T/page" "$PAGE"; check "page: served as the file on disk" $?
grep -q 'Label (task label for the costs, for example 267)' "$T/page" && grep -q 'name="label"' "$T/page"
check "page: a Label field with its hint, in the agent's form" $?
grep -q 'value="code-server"' "$T/page" && grep -q 'value="vscode"' "$T/page" && grep -q 'value="tmux"' "$T/page"
check "page: the launch select offers tmux, code-server and vscode" $?

# 2. the source rules
S="$T/script.js"; script > "$S"
! grep -Eq 'innerHTML|outerHTML|insertAdjacentHTML' "$S"; check "source: no innerHTML" $?
! grep -Eq '(^|[^A-Za-z_])eval\(' "$S"; check "source: no eval(" $?
! grep -q 'document\.write' "$S"; check "source: no document.write" $?
! grep -Eq '(src|href)[[:space:]]*=[[:space:]]*["'\'']?https?://' "$PAGE"; check "source: no outside address in src or href" $?
! grep -Eq 'setAttribute\([^)]*(src|href)[^)]*https?://' "$S"; check "source: no outside address set by setAttribute" $?
grep -q 'function api(machine, path)' "$S" && grep -q '"/machines/" + encodeURIComponent(machine) + API + path' "$S"
check "source: one address builder for the machines' dashboards" $?
grep -q 'sessionStorage' "$S"; [ $? = 1 ]; check "source: no key kept in the browser" $?
grep -q 'data-kind' "$PAGE" && grep -q 'aria-expanded' "$S"; check "source: tool buttons say whether their panel is open" $?
grep -q 'max-width: 560px' "$PAGE" && grep -A4 'max-width: 560px' "$PAGE" | grep -q 'form .grid'
check "layout: forms in one column on phones" $?
grep -q 'min-height:44px' "$PAGE"; check "layout: 44 px targets" $?
! grep -v 'minmax\|@media' "$PAGE" | grep -Eq 'min-width: *[0-9]{3,}px'
check "layout: no fixed width wider than 360 px" $?
grep -q 'overflow-x:hidden' "$PAGE"; check "layout: no page horizontal scroll" $?
grep -q 'button:focus-visible' "$PAGE"; check "layout: visible focus on buttons" $?
grep -q 'role="alert"' "$PAGE" && grep -q 'role="status"' "$PAGE"; check "page: alerts and status lines are announced" $?
grep -q 'data-fid' "$PAGE" && grep -q 'function keepFocus(fn)' "$S"; check "source: focus kept by a stable data-fid after a rebuild" $?
grep -q '<pre id="incus-cloud"' "$PAGE" && grep -q 'role="status"' "$PAGE" && grep -q 'id="incus-say" class="note" role="status"' "$PAGE"; check "incus: cloud-init in a pre, status line announced" $?
! grep -q 'incus.*innerHTML\|innerHTML.*incus' "$S" && grep -q '\$("incus-cloud").textContent = ' "$S"; check "incus: cloud-init and the lists are set as text only" $?
grep -q 'overflow-wrap:anywhere' "$PAGE" && grep -q '\.mcard dl { grid-template-columns:minmax(0, 11rem) minmax(0, 1fr); }' "$PAGE"
check "layout: long disk path wraps, label column fixed" $?
grep -q 'form.row > .grow { flex:1 1 14rem; }' "$PAGE"; check "layout: a key form's label takes its own line on phones" $?
grep -q "target: \"_blank\", rel: \"noopener noreferrer\"" "$S" && [ "$(grep -c 'Logs in Grafana\|Traces in Langfuse' "$S")" = 2 ]
check "links: agent links open in a new tab with noopener noreferrer" $?
grep -q 'settings.grafana' "$S" && grep -q 'settings.langfuse' "$S" && grep -q 'isLink(settings.grafana)' "$S"
check "links: built from the centre's settings, only when a http or https address" $?
grep -q 'Load the settings from' "$S" && grep -q 'repo-load' "$S" && grep -q 'repo: f.elements.repo' "$PAGE"
check "repo: load asks with confirm() that it replaces the machines; buttons read from the saved repository" $?
grep -q 'function checkTelemetry' "$S" && grep -q '"/telemetry/check"' "$S" && grep -q '"/telemetry/arrives"' "$S"
check "telemetry: arrivals read and the check asked through the pass-through" $?
grep -Pzq 'runOn = false;\n  paintTop\(\);\n  await loadVersions\(\);' "$S"; check "source: versions read again when an update run ends" $?
grep -q 'does not answer/.test(v.error)' "$PAGE"; check "page: no 'does not answer' twice in one line" $?
grep -q '// pure:begin' "$PAGE" && grep -q '// pure:end' "$PAGE"; check "source: pure functions between their markers" $?
grep -q '// markdown:begin' "$PAGE" && grep -q '// markdown:end' "$PAGE"; check "source: Markdown renderer between its markers" $?

grep -q 'const PARKED = new Set(\["update", "agent-form", "ssh-add", "incus"\]);' "$S" \
  && [ "$(grep -c 'data-parked="' "$PAGE")" -ge 10 ] && grep -q 'if (parked("update")) return;' "$S" \
  && grep -q 'if (parked("incus") || !settings.incus_url) return;' "$S" && grep -q 'if (!parked("ssh-add")) call(null, "GET", "/ssh/key")' "$S"
check "parked: the update, the agent's form, the SSH add and Incus are not shown and nothing is asked for them" $?
grep -q 'f.elements.password.value = ""' "$S"; check "source: the SSH add clears the password field, whatever the answer" $?
grep -q 'navigator.clipboard.writeText' "$S"; check "source: the public key is copied with the clipboard" $?
grep -q '"/machines/ssh"' "$S" && grep -q '"/ssh/key"' "$S" && grep -q '"/machines/ssh/" + ' "$S"
check "source: the SSH add, its job and the public key read through the centre's own routes" $?
! grep -q 'localStorage' "$S"; check "source: nothing kept in localStorage" $?

# 3. script parses; the address builder and the state word on a fake document
grep -q 'id="survey-log"' "$PAGE" && grep -q 'list.filter((x) => x.ok)' "$PAGE" && ! grep -q 'no SSH sign-in' "$PAGE"
check "survey: the list holds only the machines that let the centre in; the others have the log" $?
grep -q 'prefillSsh(name, m.address, user)' "$PAGE" && grep -q '"survey-add:" + name' "$PAGE"
check "survey: a listed machine has an Add that fills the SSH form" $?
if command -v node >/dev/null 2>&1; then
  node --check "$S" 2>"$T/check.err"; check "script: node --check passes" $?
  cat > "$T/pure.js" <<'JS'
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const i = src.indexOf("// pure:begin"), j = src.indexOf("// pure:end");
if (i < 0 || j < 0) throw new Error("pure markers");
const p = new Function(src.slice(i, j) + "; return { isOutdated, answered, costParts, sumCosts, sumLeaks, LEAK_RULES, outdatedSummary, isLink };")();
const fail = [];
const ok = (name, cond) => { if (cond) console.log("ok   - " + name); else { console.log("FAIL - " + name); fail.push(name); } };
const near = (a, b) => Math.abs(a - b) < 1e-9;
ok("isLink: http and https with a host only", p.isLink("https://grafana.example.net") && p.isLink("http://10.0.0.5:3000/x") && !p.isLink("javascript:alert(1)") && !p.isLink("ftp://h") && !p.isLink("") && !p.isLink("https://") && !p.isLink("not a link"));
ok("outdated only when the dashboard says so", p.isOutdated({ outdated: true, installed: "1", latest: "2" }) && !p.isOutdated({ outdated: false }) && !p.isOutdated(null) && !p.isOutdated({ missing: true }));
ok("an answer with missing or unreachable is not an answer", p.answered({ outdated: false }) && !p.answered({ missing: true }) && !p.answered({ unreachable: "x" }) && !p.answered(undefined));
const d1 = { agents: [{ main: { usd: 1.5 }, subagents: { usd: 0.25 } }, { main: { usd: null }, subagents: { usd: 0.5 } }], total: { usd: 2.25 }, unpriced: ["x"] };
const cp = p.costParts(d1);
ok("costParts sums main and subagents, skipping nulls", near(cp.main, 1.5) && near(cp.subagents, 0.75) && cp.usd === 2.25);
ok("costParts keeps a null total as not priced", p.costParts({ agents: [], total: { usd: null } }).usd === null);
const rows = [
  { name: "a", parts: { main: 1, subagents: 2, usd: 3 } },
  { name: "b", parts: null },
  { name: "c", parts: { main: 4, subagents: 0, usd: null } },
  { name: "d", parts: { main: 0.5, subagents: 0.5, usd: 1 } },
];
const t = p.sumCosts(rows);
ok("sumCosts counts only machines with costs, of all added", t.counted === 3 && t.of === 4);
ok("sumCosts adds money and leaves unpriced out of the total", near(t.usd, 4) && near(t.main, 5.5) && near(t.subagents, 2.5));
ok("sumCosts names the unpriced machine", JSON.stringify(t.unpriced) === '["c"]');
const L = p.sumLeaks([
  { name: "a", leaks: { rules: { cache_miss: { count: 2, tokens: 100 }, big_result: { count: 1, tokens: 7 } } } },
  { name: "b", leaks: null },
  { name: "c", leaks: { rules: { cache_miss: { count: 3, tokens: 50 }, new_rule: { count: 9, tokens: 9 } } } },
  { name: "d", leaks: { error: "x" } },
]);
ok("sumLeaks counts by rule over the machines that answer, a rule not known as 0", L.counted === 2 && L.of === 4
  && L.count.cache_miss === 5 && L.count.big_result === 1 && L.count.tool_loop === 0 && L.tokens === 157
  && L.machines[1].name === "c" && L.machines[1].tokens === 50);
const pyRules = (fs.readFileSync(process.argv[3], "utf8").match(/^RULES = \((.*)\)$/m) || [, ""])[1].replace(/[" ]/g, "").split(",");
ok("the centre's page knows every rule of the analyst", JSON.stringify(p.LEAK_RULES.map((r) => r[0])) === JSON.stringify(pyRules));
ok("sumCosts with nothing counted has no money", p.sumCosts([{ name: "x", parts: null }]).counted === 0);
const allNull = p.sumCosts([{ name: "y", parts: { main: 1, subagents: 0, usd: null } }]);
const part = p.sumCosts([{ name: "p", parts: p.costParts({ agents: [], total: { usd: 2, usd_partial: true } }) }]);
ok("sumCosts counts a partial machine's money and names it", near(part.usd, 2) && JSON.stringify(part.unpriced) === '["p"]');
ok("sumCosts with every machine unpriced says no price", allNull.usd === null && allNull.counted === 1);
const o = p.outdatedSummary([{ name: "a", ver: { outdated: true } }, { name: "b", ver: { outdated: false } }, { name: "c", ver: null }]);
ok("outdatedSummary counts outdated of those that answered", o.n === 1 && o.m === 2 && o.unknown === 1);
if (fail.length) process.exit(1);
JS
  node "$T/pure.js" "$S" "$REPO/dashboard/analyst.py" > "$T/pure.out" 2>&1
  rc=$?
  cat "$T/pure.out"
  check "pure: cost sums and outdated decision in node" $rc
  cat > "$T/helpers.js" <<'JS'
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const cut = (a, b) => { const i = src.indexOf(a); const j = src.indexOf(b, i); if (i < 0 || j < 0) throw new Error("marker " + a); return src.slice(i, j); };
const lib = new Function(cut('const API = "/api/v1";', "const $ = ") +
  cut("function api(", "async function call(") + cut("function statusOf(", "async function changeMachine(") +
  cut("function txt(", "\n") + "\n" + cut("function addUserOf(", "function renderSurvey(") + "; return { api, statusOf, addUserOf, isAdded, logText };")();
const fail = [];
const ok = (name, cond) => { if (cond) console.log("ok   - " + name); else { console.log("FAIL - " + name); fail.push(name); } };
ok("api of the centre itself", lib.api(null, "/state") === "/api/v1/state");
ok("api of a machine goes through the pass-through", lib.api("box-1", "/agents/abcd/console") === "/api/v1/machines/box-1/api/v1/agents/abcd/console");
ok("api encodes the machine name", lib.api("a/b c", "/state") === "/api/v1/machines/a%2Fb%20c/api/v1/state");
ok("off machine says off", lib.statusOf({ on: false }).text === "off");
ok("answering machine says answers", lib.statusOf({ on: true, state: {}, older: false, version: "0.12" }).text === "answers");
ok("state null, version present says key refused", lib.statusOf({ on: true, state: null, version: "0.12", error: "wrong key" }).text === "key refused");
ok("state null, no version says does not answer", lib.statusOf({ on: true, state: null, version: null, error: "timed out" }).text === "does not answer");
ok("old dashboard with no such path says older version", lib.statusOf({ on: true, state: null, version: "0.1", older: true, error: "no such path" }).text === "older version");
ok("survey: added with the user the centre signed in as", lib.addUserOf({ sign_in: "tz", users: [{ user: "agent", kit: "new" }] }) === "tz");
ok("survey: after root, the first user with the kit", lib.addUserOf({ sign_in: "root", users: [{ user: "a", kit: "none" }, { user: "b", kit: "new" }] }) === "b");
ok("survey: after root with no kit, the first user; with no user, agent", lib.addUserOf({ sign_in: "root", users: [{ user: "a", kit: "none" }] }) === "a" && lib.addUserOf({ sign_in: "root", users: [] }) === "agent");
ok("survey: a machine of an added address is added", lib.isAdded({ address: "192.0.2.5" }, [{ address: "http://192.0.2.5:8765" }]) && lib.isAdded({ address: "fd7a::5" }, [{ address: "http://[fd7a::5]:8765" }]));
ok("survey: another address, or a bad one, is not added", !lib.isAdded({ address: "192.0.2.6" }, [{ address: "http://192.0.2.5:8765" }, { address: "junk" }]));
ok("survey: a log line names the machine, its address and the error", lib.logText({ time: 1700000000, name: "box", address: "192.0.2.9", error: "Permission denied" }).endsWith("box (192.0.2.9): Permission denied"));
if (fail.length) process.exit(1);
JS
  node "$T/helpers.js" "$S" > "$T/helpers.out" 2>&1
  rc=$?
  cat "$T/helpers.out"
  check "helpers: address builder and state word on a fake document" $rc
else
  echo "ok - skipped: no node"
fi

echo "passed $PASS, failed $FAIL"
[ "$FAIL" = 0 ]
