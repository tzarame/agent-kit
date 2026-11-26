#!/usr/bin/env bash
# tests/dashboard-page.test.sh - the dashboard page (dashboard/page.html): served with its policy, the panels and states
# it names are in it, the rules of the page hold in its source (no innerHTML, no eval, no document.write, no outside
# address in src or href, no input in the console panel), its script parses, and the Markdown renderer works on a fake
# document (when node is on PATH). Dash.py runs on a free port of 127.0.0.1 with HOME a temp folder. Exit 0 when every case passes.
REPO=$(cd "$(dirname "$0")/.." && pwd -P)
PAGE="$REPO/dashboard/page.html"
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
# the text of the script of the page, and of one function of it, for the source rules
script() { python3 -I -c 'import sys,re; s=open(sys.argv[1],encoding="utf-8").read(); m=re.search(r"<script>(.*?)</script>", s, re.S); sys.stdout.write(m.group(1))' "$PAGE"; }
fn() { python3 -I -c 'import sys,re; s=open(sys.argv[1],encoding="utf-8").read(); a=s.index("function "+sys.argv[2]+"("); b=s.index("\nfunction ", a+10) if "\nfunction " in s[a+10:] else len(s); sys.stdout.write(s[a:b])' "$PAGE" "$1"; }

# 1. the page served at / with its policy and the panels it names
python3 -I "$REPO/dashboard/dash.py" --port "$PORT" > "$T/server.log" 2>&1 &
SRV=$!
for _ in $(seq 50); do curl -s -o /dev/null "$B/api/v1/hello" && break; sleep 0.1; done
hdr=$(curl -s -D - -o "$T/page" "$B/")
code=$(printf '%s' "$hdr" | head -1 | tr -d '\r')
printf '%s' "$code" | grep -q ' 200' && printf '%s' "$hdr" | grep -qi "^content-security-policy: .*default-src 'self'" \
  && grep -q '<title>Agents' "$T/page"
check "page: 200 with the policy header and the title" $?
for w in Notes Console Files Terminal Telemetry Costs "Machine tools" "Tools of "; do
  grep -q "$w" "$T/page"; check "page: names $w" $?
done
cmp -s "$T/page" "$PAGE"; check "page: served as the file on disk" $?
! grep -q '/profiles' "$T/page" && ! grep -q '<dialog' "$T/page"
check "page: no form of an agent and no call that writes a project: the kit's config is the kit's" $?
fn agentCard > "$T/card0.js"
grep -q '"Start a session"' "$T/card0.js" && grep -q 'pickKey("Model"' "$T/card0.js" && grep -q ': as the project' "$T/page" \
  && grep -q 'a.sessions.map' "$T/card0.js" \
  && grep -q "not the project's settings" "$T/card0.js" && grep -q 'stopSession(a, s)' "$T/card0.js" \
  && grep -q '"/sessions/" + s.id + "/stop"' "$T/page" && grep -q 'window.confirm("Stop the session' "$T/page"
check "page: a start with the keys of this start; each session with its settings, its mark and its Stop, confirmed" $?
grep -q 'r.ok === false' "$T/page" && grep -q 'the kit said: ' "$T/page"
check "page: a start or a stop the kit refused is said" $?

# 2. the source rules
S="$T/script.js"; script > "$S"
! grep -Eq 'innerHTML|outerHTML|insertAdjacentHTML' "$S"; check "source: no innerHTML" $?
! grep -Eq '(^|[^A-Za-z_])eval\(' "$S"; check "source: no eval(" $?
! grep -q 'document\.write' "$S"; check "source: no document.write" $?
! grep -Eq '(src|href)[[:space:]]*=[[:space:]]*["'\'']?https?://' "$PAGE"; check "source: no outside address in src or href" $?
! grep -Eq 'setAttribute\([^)]*(src|href)[^)]*https?://' "$S"; check "source: no outside address set by setAttribute" $?
fn consolePanel > "$T/console.js"
[ -s "$T/console.js" ] && ! grep -Eq '<input|"input"' "$T/console.js"
check "source: the console panel has no input" $?
grep -q 'data-kind="costs"' "$PAGE"; check "page: the Costs button in the part Where the spend goes" $?
fn costsPanel > "$T/costs.js"
grep -q '/costs?since=' "$T/costs.js" && grep -q 'nothing spent in this period' "$T/costs.js" \
  && grep -q 'estimate at API prices' "$T/costs.js" && grep -q 'no price for: ' "$T/costs.js" \
  && grep -q 'Loading...' "$T/costs.js" && grep -q 'role: "status"' "$T/costs.js"
check "costs: asks /costs, and says loading, empty, error and unpriced states" $?
grep -q 'cls: "wrap"' "$T/costs.js"; check "costs: each table in a box of its own (it scrolls inside the box)" $?
grep -q '/analyst?since=' "$T/costs.js" && grep -q 'Where tokens leak' "$T/costs.js" \
  && grep -q 'Nothing found in this period' "$T/costs.js"
check "costs: asks /analyst for the same period, and says when nothing was found" $?
grep -q 'Read from the cache: ' "$T/costs.js" && grep -q 'after a pause, ' "$T/costs.js" \
  && grep -q 'w.calls && w.read_share !== null' "$T/costs.js"
check "costs: the watched numbers of the period stand above the findings" $?
for r in $(sed -n 's/^RULES = (\(.*\))$/\1/p' "$REPO/dashboard/analyst.py" | tr -d '",'); do
  grep -q "\[\"$r\", " "$PAGE" || { echo "no label for the rule $r"; false; break; }
done
check "costs: the page has a label for every rule of the analyst" $?
grep -Eq 'min-height: *44px' "$PAGE"; check "layout: 44 px targets (buttons, fields, checks) in the base rules" $?
grep -q '\.check input, input\[type=checkbox\]' "$PAGE" && grep -q 'overflow-wrap: *anywhere' "$PAGE"
check "markdown: checkboxes at normal size; long paths wrap" $?
! grep -v 'minmax\|@media\|matchMedia' "$PAGE" | grep -Eq 'min-width: *[0-9]{3,}px'
check "layout: no fixed width wider than 360 px" $?
grep -Eq 'button:focus-visible' "$PAGE"; check "layout: visible focus on buttons" $?
grep -q '// markdown:begin' "$PAGE" && grep -q '// markdown:end' "$PAGE"; check "source: Markdown renderer between its markers" $?
fn telemetryPanel > "$T/tel.js"
grep -q 'Check receivers and agents' "$T/tel.js" && grep -q '"/telemetry/check"' "$T/tel.js" && grep -q '"/telemetry/arrives"' "$T/tel.js"
check "telemetry: the Check button asks the check and the arrives routes" $?
grep -q 'no data for ' "$T/tel.js" && grep -q 'no record yet' "$T/tel.js"
check "telemetry: the no-data mark and the no-record text" $?
grep -q 'Checking the receivers' "$T/tel.js" && grep -q 'role: "status"' "$T/tel.js" && grep -q 'accessText(e)' "$T/tel.js" \
  && grep -q 'checkBtn.disabled = false' "$T/tel.js"
check "telemetry: loading, error and the button's release" $?
grep -q 'checks.replaceChildren' "$T/tel.js" && ! grep -Eq 'innerHTML|textContent *= *rc|eval' "$T/tel.js"
check "telemetry: results are built as nodes, the key text not put in as markup" $?
fn agentCard > "$T/card.js"
! grep -q 'a.telemetry\|last_event\|a.answers\|a.kit' "$T/card.js" && grep -q 'gives these settings to no session yet' "$T/tel.js"
check "telemetry: no chip of it on the agent card; the panel says no session gets the settings" $?
grep -q '\.checks p { overflow-wrap:anywhere' "$PAGE"; check "layout: the check results wrap inside 360 px" $?
fn filesPanel > "$T/files.js"
grep -q 'Formatted / Source' "$T/files.js" && grep -q 'aria-pressed", String(md)' "$T/files.js" && grep -q 'renderMarkdown(r.text)' "$T/files.js"
check "files: a Markdown file opens formatted, with the Formatted / Source toggle" $?
grep -q 'tokText(c.brief_tokens)' "$T/costs.js" && grep -q 'tokText(c.report_tokens)' "$T/costs.js"
check "costs: the brief and report sizes shown as token estimates" $?

# 2b. the statistics, the settings and the collapsible sections
for w in Statistics "stat-agents" "stat-machine" 'id="stamp"' 'data-key="machine"' 'data-key="tmux"'; do
  grep -q "$w" "$PAGE"; check "stats: names $w" $?
done
grep -q 'restart to apply' "$T/card.js" && grep -q 'data-mark": "restart"\|"data-mark": "restart"' "$T/card.js"
check "card: the restart-to-apply chip and its Restart button" $?
fn renderStatsMachine > "$T/stm.js"; grep -q '"low"' "$T/stm.js"; check "stats: the machine row marks a low disk" $?
fn statAgent > "$T/stat.js"
grep -q 'bar(' "$T/stat.js" && grep -q 'subagents' "$T/stat.js" && grep -q 'NO_DATA' "$T/stat.js" && grep -q 'const NO_DATA = "no data: the kit does not write it yet"' "$PAGE"
check "stats: context bar against the window, main and subagents, no data for the telemetry" $?
fn loadCosts > "$T/lc.js"; grep -q '/costs?since=' "$T/lc.js" && grep -q 'agent=' "$T/lc.js"
check "stats: today's costs read per agent" $?
! grep -q '"/version"\|"/update"\|update-btn\|checkVersion' "$PAGE"
check "updates: the page has no update button and asks no update route" $?
grep -q 'localStorage' "$PAGE" && grep -q 'dash-sec-' "$PAGE" && grep -q 'min-width: 721px' "$PAGE"
check "sections: open state in localStorage, closed on narrow widths by default" $?

# 2c. the frame of the design: the menu, the bar at the top, the key numbers, the parts
grep -q '<nav class="nav" aria-label="Sections">' "$PAGE" && grep -q 'class="topbar"' "$PAGE" && grep -q 'id="tiles"' "$PAGE" \
  && grep -q 'id="refresh"' "$PAGE" && grep -q -- '--cy:#22E3FF' "$PAGE"
check "frame: the menu, the bar with Refresh, the key numbers and the design's colours" $?
bad=0
for h in $(grep -o '<a href="#[a-z-]*"' "$PAGE" | sed 's/.*#//; s/"//'); do grep -q "id=\"$h\"" "$PAGE" || { echo "no part $h"; bad=1; }; done
[ "$bad" = 0 ]; check "frame: every link of the menu leads to a part of the page" $?
[ "$(grep -o '<a href="#[a-z-]*"' "$PAGE" | sed 's/.*#//; s/"//' | tr '\n' ' ')" = "agents-sec spend analyst settings machines files " ]
check "frame: the menu is the design's: Agents, Spend, Analyst, Settings, Machines, Files" $?
grep -q '@media (max-width: 820px)' "$PAGE" && grep -q 'position:fixed; left:0; right:0; bottom:0' "$PAGE" \
  && grep -q '<a href="#files" class="wide"' "$PAGE" && grep -q '\.nav a\.wide { display:none; }' "$PAGE"
check "frame: on a phone the menu is a row of five tabs at the bottom, without Files" $?
grep -q 'id="new-session"' "$PAGE" && grep -q 'id="new-box"' "$PAGE" && fn newSessionBox | grep -q 'act(a, "start", startKeys(model, effort))'
check "frame: New session opens a box on the page that starts a session of a project" $?
fn agentCard > "$T/card2.js"
grep -q '"RUNNING" : "STOPPED"' "$T/card2.js" && grep -q '\["Open"\]' "$T/card2.js" && grep -q 'showSettings(a)' "$T/card2.js" \
  && grep -q 'act(a, "stop"), disabled: !a.running' "$T/card2.js" && grep -q 'openCards.has(a.id) || !!open' "$T/card2.js"
check "card: the state, one line of the settings, the context, and Open, Settings, Stop; an open card stays open" $?
grep -q 'id="spend-bars"' "$PAGE" && grep -q 'id="settings-kv" class="kv"' "$PAGE" && grep -q 'id="leaks"' "$PAGE" \
  && grep -q '<th>Rule</th><th>Session</th><th>What</th><th class="num">Tokens</th>' "$PAGE" && grep -q 'data-slot="files"' "$PAGE"
check "parts: where the spend goes, the settings, the analyst's table, the files" $?
for r in $(python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import analyst; print(" ".join(analyst.RULES))' "$REPO/dashboard"); do
  grep -A3 '^const LEAK_TAGS' "$PAGE" | grep -q "$r: \[" || { echo "no tag for $r"; bad=1; }
done
[ "$bad" = 0 ]; check "analyst: a tag for every rule" $?
fn loadToday | grep -q '"/analyst?since="' && grep -q 'setInterval(loadToday, 60000)' "$PAGE"
check "analyst: today's findings are read at the start and each minute" $?
if command -v node >/dev/null 2>&1; then
  { echo 'const LEAK_RULES = [["cache_miss"], ["cold_start"], ["big_result"], ["compact_often"], ["tool_loop"], ["subagent_share"]];'
    fn keyNumbers; fn leakWho; fn spendRows; fn settingsView; cat <<'JS'
const agents = [{ id: "a", name: "a", dir: "/home/u/a.b", running: true, role: "dev", model: "opus", effort: "high", subm: "haiku", sube: "low",
    window: 100, compact: null, context: { tokens: 50 }, sessions: [{ id: "s1", settings: { model: "fable", advisor: null, idle_compact: true } }, { id: "s2" }] },
  { id: "b", name: "b", dir: "/home/u/b", running: false, window: 200, context: { tokens: 180 }, sessions: [] }];
const want = (name, ok) => { if (!ok) { console.log("FAIL " + name); process.exitCode = 1; } };
let n = keyNumbers(agents, null);
want("before the analyst answers: dashes, and the sessions from the state",
  n.read === null && n.perTurn === null && n.leaks === null && n.up === 1 && n.agents === 2 && n.sessions === 2);
const rules = { cache_miss: { count: 0 }, cold_start: { count: 2 }, big_result: { count: 3 }, tool_loop: { count: 1 } };
n = keyNumbers(agents, { rules, findings: [1, 2, 3, 4, 5, 6],
  watch: { calls: 40, read_share: 0.98, turns: 10, turn_calls: 4, turn_median: 2, turn_p90: 8 } });
want("the share read, the calls for a turn, the leaks and the two rules with the most",
  n.read === 0.98 && n.perTurn === 4 && n.median === 2 && n.p90 === 8 && n.leaks === 6
  && JSON.stringify(n.top) === '[["big_result",3],["cold_start",2]]');
n = keyNumbers([], { rules: {}, findings: [], watch: { calls: 0, read_share: null, turns: 0, turn_calls: null } });
want("a day with no call: no share, no calls for a turn, no leak", n.read === null && n.perTurn === null && n.leaks === 0 && n.top.length === 0);

want("a finding is named by the agent of its folder", leakWho({ folder: "-home-u-a-b", session: "0123456789", agent: null }, agents) === "a");
want("a subagent's finding says so", leakWho({ folder: "-home-u-b", session: "0123456789", agent: "agent-1" }, agents) === "b (subagent)");
want("another folder: the start of the session's name", leakWho({ folder: "-x", session: "0123456789", agent: null }, agents) === "01234567");

const part = (u) => ({ usd: u });
let s = spendRows(agents, new Map());
want("no costs read yet", s.known === false && s.rows.length === 0);
s = spendRows(agents, new Map([["a", { main: part(6), subagents: part(2) }], ["b", { main: part(0), subagents: part(2) }]]));
want("the spend by share, the largest first and full width, nothing for a zero",
  s.total === 10 && s.rows.length === 3 && s.rows[0].label === "a, main conversation" && s.rows[0].share === 0.6
  && s.rows[0].width === 1 && s.rows[1].share === 0.2 && Math.abs(s.rows[1].width - 1 / 3) < 1e-9);
s = spendRows(agents, new Map([["a", { main: part(0), subagents: part(0) }]]));
want("nothing spent: known, no row", s.known === true && s.rows.length === 0);

let v = settingsView(agents[0]);
want("the settings of a running agent are its session's, as started",
  v.from === "as started · s1" && JSON.stringify(v.rows) === '[["model","fable"],["advisor",null],["idle_compact",true]]');
v = settingsView(agents[1]);
want("of a stopped one, the project's", v.from === "the project's" && v.rows[0][0] === "agent" && v.rows.some(([k, x]) => k === "context_window" && x === 200));
JS
  } > "$T/key.js"
  node "$T/key.js" > "$T/key.out" 2>&1; rc=$?; cat "$T/key.out"
  check "key numbers, the names of findings, the spend's rows and the settings shown" $rc
fi

# 3. script parses, renderer on a fake document
if command -v node >/dev/null 2>&1; then
  node --check "$S" 2>"$T/check.err"; check "script: node --check passes" $?
  cat > "$T/md.js" <<'JS'
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const cut = (a, b) => { const i = src.indexOf(a); const j = src.indexOf(b, i); if (i < 0 || j < 0) throw new Error("marker " + a); return src.slice(i, j); };
class Node { constructor(tag) { this.tag = tag; this.kids = []; this.attrs = {}; this.text = ""; this.disabled = false; this.checked = false; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  append(...xs) { for (const x of xs) this.kids.push(x); }
  addEventListener() {} }
const doc = { createElement: (t) => new Node(t), createTextNode: (s) => ({ tag: "#text", text: String(s), kids: [] }) };
const lib = new Function("document", cut("function el(", "function notice(") + cut("// markdown:begin", "// markdown:end") + "; return { renderMarkdown, el };")(doc);
const txt = (n) => n.tag === "#text" ? n.text : n.kids.map(txt).join("");
const find = (n, tag, out = []) => { if (n.tag === tag) out.push(n); for (const k of n.kids || []) find(k, tag, out); return out; };
const out = lib.renderMarkdown("# Title\n- [x] done\n- [ ] open\n\nSome **bold** and `code` and [site](https://example.com/x) and [bad](javascript:alert(1)).\n```\n<b>raw</b>\n```\n1. one\n2. two");
const fail = [];
const ok = (name, cond) => { if (cond) console.log("ok   - " + name); else { console.log("FAIL - " + name); fail.push(name); } };
ok("heading h1 with its text", find({ kids: out }, "h1").length === 1 && txt(find({ kids: out }, "h1")[0]) === "Title");
const boxes = find({ kids: out }, "input");
ok("task items: checked and open", boxes.length === 2 && boxes[0].checked === true && boxes[1].checked === false && boxes[0].disabled === true);
const links = find({ kids: out }, "a");
ok("https link kept with its address", links.length === 1 && links[0].attrs.href === "https://example.com/x" && links[0].attrs.rel === "noopener noreferrer");
ok("javascript link is plain text, no anchor for it", !links.some((a) => /javascript/.test(a.attrs.href || "")) && txt({ kids: out }).includes("[bad](javascript:alert(1)"));
const pres = find({ kids: out }, "pre");
ok("code fence shows its text as text", pres.length === 1 && txt(pres[0]) === "<b>raw</b>");
ok("bold, code and ordered list", find({ kids: out }, "strong").length === 1 && find({ kids: out }, "code").length >= 1 && find({ kids: out }, "ol").length === 1);
ok("no markup from the note is built as an element", find({ kids: out }, "b").length === 0 && find({ kids: out }, "script").length === 0);
const sc = lib.renderMarkdown("Text <script>alert(1)</script> and <b>x</b>");
ok("script and b in a paragraph stay text", find({ kids: sc }, "script").length === 0 && find({ kids: sc }, "b").length === 0 && txt({ kids: sc }) === "Text <script>alert(1)</script> and <b>x</b>");
const hs = lib.renderMarkdown("## Two\n#### Four");
ok("headings 2 and 4", find({ kids: hs }, "h2").length === 1 && find({ kids: hs }, "h4").length === 1);
const ln = lib.renderMarkdown("- one\n- two\n\n3. three");
ok("unordered list with two items, then an ordered list", find({ kids: ln }, "ul").length === 1 && find({ kids: ln }, "ul")[0].kids.length === 2 && find({ kids: ln }, "ol").length === 1);
if (fail.length) process.exit(1);
JS
  node "$T/md.js" "$PAGE" > "$T/md.out" 2>&1
  rc=$?
  cat "$T/md.out"
  check "markdown: renderer on a fake document" $rc
else
  echo "ok - skipped: no node"
fi

echo "passed $PASS, failed $FAIL"
[ "$FAIL" = 0 ]
