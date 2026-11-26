"""test_plugins.py - the kit's plugins (plugins/): each a folder Claude Code takes with --plugin-dir, listed in the
marketplace; a skill in one plugin only; each hook's script there and sound; what the hooks give (the rules, the deny
of qa); the cases of the gate owner-run (tests/owner-run.test.sh, tests/owner-stop.test.sh); the program of the
plugin openspec, with a made-up install script.
    python3 -m unittest discover -s tests"""
import json, os, re, shutil, subprocess, tempfile, unittest

from kit import config, plan

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGINS = os.path.join(ROOT, "content", "plugins")
NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
HOOK_FILE = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"' ]+)")
# the programs the gate's tests link into their PATH; bwrap is not one: its cases are skipped without it
GATE_TOOLS = ("bash", "sh", "sed", "sha256sum", "cut", "cat", "mkdir", "mv", "rm", "cp", "id", "date", "readlink",
              "stat", "cmp", "diff", "grep", "tail", "head", "mktemp", "python3", "dirname", "timeout")


def plugins():
    """each folder of plugins/: (its name, its path)"""
    for n in sorted(os.listdir(PLUGINS)):
        p = os.path.join(PLUGINS, n)
        if os.path.isdir(p):
            yield n, p


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def header(path):
    """the fields of a markdown file's header between the two --- lines"""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    return dict(l.split(": ", 1) for l in m.group(1).splitlines() if ": " in l) if m else {}


class ThePlugins(unittest.TestCase):
    def test_each_folder_is_a_plugin(self):
        found = list(plugins())
        self.assertIn("agent-kit", dict(found))
        for name, path in found:
            self.assertRegex(name, NAME)
            m = load(os.path.join(path, ".claude-plugin", "plugin.json"))
            self.assertEqual(m["name"], name)
            self.assertTrue(m.get("description"), name)

    def test_the_marketplace_lists_each_plugin(self):
        doc = load(os.path.join(ROOT, ".claude-plugin", "marketplace.json"))
        listed = {p["name"]: p for p in doc["plugins"]}
        self.assertEqual(set(listed), {n for n, _ in plugins()})
        for name, path in plugins():
            self.assertEqual(os.path.normpath(os.path.join(ROOT, listed[name]["source"])), path)
            self.assertEqual(listed[name]["description"],
                             load(os.path.join(path, ".claude-plugin", "plugin.json"))["description"])

    def test_a_skill_is_in_one_plugin(self):
        seen = {}
        for name, path in plugins():
            skills = os.path.join(path, "skills")
            for s in sorted(os.listdir(skills)) if os.path.isdir(skills) else ():
                h = header(os.path.join(skills, s, "SKILL.md"))
                self.assertEqual(h.get("name"), s, "%s:%s" % (name, s))
                self.assertTrue(h.get("description"), "%s:%s" % (name, s))
                self.assertNotIn(s, seen, "the skill %s is in %s and in %s" % (s, seen.get(s), name))
                seen[s] = name
                self.assertFalse([k for k in h if k.startswith("role-")], "%s:%s has a role's field" % (name, s))

    def test_the_agents_of_the_kit_s_source(self):
        folder, names = os.path.join(ROOT, "content", "agents"), dict(plugins())
        found = sorted(n[:-5] for n in os.listdir(folder) if n.endswith(".json"))
        self.assertEqual(found, ["design", "dev", "dev-eco", "qa", "spec", "toolsmith"])
        # the cheap developer: dev on haiku with a small window and the fewest tools (ToolSearch stays: an MCP
        # server's tools are reached by it); the one agent that names a model
        with open(os.path.join(folder, "dev-eco.json"), encoding="utf-8") as fh:
            eco = json.load(fh)
        self.assertEqual(eco, {"agent": "dev", "model": "haiku", "context_window": 133000,
                               "tools": ["Bash", "Read", "Edit", "Write", "Skill", "Agent", "ToolSearch"]})
        config.agent_fields(dict(eco), "dev-eco")
        for name in [n for n in found if n != "dev-eco"]:
            with open(os.path.join(folder, name + ".json"), encoding="utf-8") as fh:
                doc = json.load(fh)
            checked = config.agent_fields(dict(doc, role="/" + doc["role"], system_prompt="/x.md"), name)
            self.assertEqual(checked["plugins"], doc["plugins"])
            # the kit's own prompt in place of Claude Code's, a short list of tools, the web for the subagents only
            self.assertEqual(doc["system_prompt"], "../plugins/agent-kit/system-prompt.md", name)
            self.assertTrue(os.path.exists(os.path.join(folder, doc["system_prompt"])), name)
            self.assertEqual(doc["subagent_tools"], ["WebSearch", "WebFetch"], name)
            self.assertFalse({"WebSearch", "WebFetch", "Workflow", "SendFeedback"} & set(doc["tools"]), name)
            self.assertLessEqual({"ReadNotifications", "ListAgents", "PushNotification", "SendUserFile",
                                  "CronCreate", "EnterWorktree"}, set(doc["tools"]), name)
            self.assertEqual("Artifact" in doc["tools"], name == "design", name)
            self.assertEqual(doc["context_window"], {"haiku": 133000, "*": 256000}, name)
            self.assertEqual(doc["role"], name + ".md")
            self.assertIn(name, doc["plugins"])
            for p in doc["plugins"]:
                self.assertIn(p, names, name)
            with open(os.path.join(folder, doc["role"]), encoding="utf-8") as fh:
                self.assertTrue(plan.body(fh.read()).startswith("You are "), name)
            self.assertFalse(os.path.exists(os.path.join(names[name], "agents", name + ".md")), name)
            self.assertNotIn("subagents", doc, "%s: no agent of the kit has another as a subagent" % name)
            self.assertFalse({"model", "effort"} & set(doc), "%s: the model is chosen by hand" % name)
        self.assertEqual(json.load(open(os.path.join(folder, "spec.json")))["plugins"], ["spec", "openspec", "dev"])
        self.assertIsNone(config.defaults()["session"]["agent"])

    def test_each_hook_s_script_is_there(self):
        for name, path in plugins():
            hooks = os.path.join(path, "hooks", "hooks.json")
            if not os.path.exists(hooks):
                continue
            for event, groups in load(hooks)["hooks"].items():
                for g in groups:
                    for h in g["hooks"]:
                        files = HOOK_FILE.findall(h["command"])
                        self.assertTrue(files, "%s %s: %s" % (name, event, h["command"]))
                        for f in files:
                            p = os.path.join(path, f)
                            self.assertTrue(os.path.isfile(p), "%s %s: %s is missing" % (name, event, f))
                            r = subprocess.run(["bash", "-n", p], capture_output=True, text=True)
                            self.assertEqual(r.returncode, 0, r.stderr)


def text(*path):
    with open(os.path.join(PLUGINS, *path), encoding="utf-8") as f:
        return f.read()


class TheHooks(unittest.TestCase):
    """the hooks' scripts run as Claude Code runs them: bash, the event's JSON on stdin, in the session's folder"""
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = os.path.realpath(t.name)
        self.cwd = os.path.join(self.tmp, "project")
        os.mkdir(self.cwd)

    def hook(self, plugin, script, stdin, env=None):
        """(the exit code, the output) of the plugin's script on stdin"""
        r = subprocess.run(["bash", os.path.join(PLUGINS, plugin, "scripts", script)], input=stdin, cwd=self.cwd,
                           capture_output=True, encoding="utf-8", timeout=30, start_new_session=True,
                           env=dict({"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self.tmp},
                                    **(env or {})))
        self.assertEqual(r.stderr, "")
        return r.returncode, r.stdout

    def test_the_session_gets_the_common_rules_and_its_own(self):
        rc, out = self.hook("agent-kit", "session-rules.sh", '{"hook_event_name":"SessionStart","source":"compact"}')
        rules = text("agent-kit", "system-prompt.md") + text("agent-kit", "agent.md")
        self.assertEqual((rc, out), (0, rules))
        role = os.path.join(ROOT, "content", "agents", "qa.md")
        rc, out = self.hook("agent-kit", "session-rules.sh", "{}", {"AGENT_KIT_ROLE": role})
        with open(role, encoding="utf-8") as f:
            self.assertEqual((rc, out), (0, rules + "\n" + plan.body(f.read()) + "\n"))
        self.assertTrue(out.endswith("refuses the tools that write.\n"))
        self.assertNotIn("description:", out)

    def test_the_hook_gives_nothing_in_a_session_of_the_kit(self):
        for v in ("1", "0"):
            self.assertEqual(self.hook("agent-kit", "session-rules.sh", "{}", {"AGENT_KIT_PROMPT": v}), (0, ""))

    def test_a_subagent_of_a_session_with_claude_code_s_prompt_gets_nothing(self):
        self.assertEqual(self.hook("agent-kit", "subagent-rules.sh", "{}", {"AGENT_KIT_PROMPT": "0"}), (0, ""))
        self.assertTrue(self.hook("agent-kit", "subagent-rules.sh", "{}", {"AGENT_KIT_PROMPT": "1"})[1])

    def test_the_cheap_subagent_has_its_model_and_its_window(self):
        """the small window is for the cheap model only: the universal subagent names neither"""
        def head(name):
            lines = text("agent-kit", "agents/%s.md" % name).split("---")[1].strip().split("\n")
            return dict(line.split(": ", 1) for line in lines)
        self.assertEqual((head("runner")["name"], head("runner")["model"], head("runner")["autoCompactWindow"]),
                         ("runner", "haiku", "140000"))
        self.assertGreaterEqual(int(head("runner")["autoCompactWindow"]), 100000)
        self.assertFalse({"model", "autoCompactWindow"} & set(head("subagent")))
        self.assertEqual((head("web")["tools"], head("web")["model"]), ("WebSearch, WebFetch", "haiku"))
        self.assertEqual((head("reviewer")["tools"], head("reviewer")["model"]), ("Bash, Read", "sonnet"))
        for name in ("web", "Explore", "runner", "reviewer"):   # the session is told of each
            self.assertIn("`%s`" % name, text("agent-kit", "agent.md"))
        self.assertIn("several subagents in one message", text("agent-kit", "agent.md"))
        self.assertIn("Change no file", text("agent-kit", "agents/reviewer.md"))

    def test_a_subagent_gets_the_common_rules_and_its_own(self):
        rc, out = self.hook("agent-kit", "subagent-rules.sh", '{"hook_event_name":"SubagentStart"}')
        self.assertEqual(rc, 0)
        rules = text("agent-kit", "system-prompt.md").strip() + "\n" + text("agent-kit", "subagent.md").strip()
        self.assertEqual(json.loads(out),
                         {"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": rules}})

    def test_a_subagent_gets_the_lines_of_the_session_s_plugins(self):
        """between the common rules and its own; a file that is gone is left out"""
        own = text("openspec", "system-prompt.md").strip()
        self.assertIn("openspec/", own)
        self.assertNotIn("openspec", text("agent-kit", "system-prompt.md") + text("agent-kit", "agent.md"))
        self.assertIn("review", text("openspec", "agent.md"))
        paths = os.path.join(dict(plugins())["openspec"], "system-prompt.md") + ":" + os.path.join(self.tmp, "gone.md")
        rc, out = self.hook("agent-kit", "subagent-rules.sh", "{}", {"AGENT_KIT_PLUGIN_PROMPTS": paths})
        rules = "\n".join([text("agent-kit", "system-prompt.md").strip(), own, text("agent-kit", "subagent.md").strip()])
        self.assertEqual((rc, json.loads(out)["hookSpecificOutput"]["additionalContext"]), (0, rules))

    def no_code(self, doc):
        """the decision of qa's hook on this input (a dict, or text as it is): "deny", or "" when it passes"""
        rc, out = self.hook("qa", "no-code.sh", doc if isinstance(doc, str) else json.dumps(doc))
        self.assertEqual(rc, 0)
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else ""

    def test_qa_changes_no_file_of_the_project(self):
        link = os.path.join(self.tmp, "link")
        os.symlink(self.cwd, link)
        for name, tool in (("Write", {"file_path": os.path.join(self.cwd, "a.py")}),
                           ("Edit", {"file_path": "src/a.py"}),
                           ("NotebookEdit", {"notebook_path": os.path.join(self.cwd, "n.ipynb")})):
            self.assertEqual(self.no_code({"tool_name": name, "tool_input": tool, "cwd": self.cwd}), "deny", name)
        self.assertEqual(self.no_code({"tool_input": {"file_path": os.path.join(self.cwd, "a.py")}, "cwd": link}),
                         "deny", "the folder by a link")

    def test_qa_may_write_elsewhere(self):
        for path in (os.path.join(self.tmp, "scratch.py"), "../scratch.py"):
            self.assertEqual(self.no_code({"tool_input": {"file_path": path}, "cwd": self.cwd}), "", path)

    def only_plans(self, doc):
        """the decision of spec's hook on this input: "deny", or "" when it passes"""
        rc, out = self.hook("spec", "openspec-only.sh", doc if isinstance(doc, str) else json.dumps(doc))
        self.assertEqual(rc, 0)
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"] if out else ""

    def test_spec_writes_only_its_plans(self):
        link = os.path.join(self.tmp, "link")
        os.symlink(self.cwd, link)
        for tool in ({"file_path": os.path.join(self.cwd, "openspec", "changes", "web", "design.md")},
                     {"file_path": "openspec/config.yaml"}, {"file_path": os.path.join(self.tmp, "note.md")},
                     {"file_path": "../note.md"}):
            self.assertEqual(self.only_plans({"tool_input": tool, "cwd": self.cwd}), "", tool)
        for tool, cwd in (({"file_path": "src/app.py"}, self.cwd), ({"file_path": "openspec-x/a.md"}, self.cwd),
                          ({"file_path": "openspec/../src/app.py"}, self.cwd),
                          ({"notebook_path": os.path.join(self.cwd, "n.ipynb")}, self.cwd),
                          ({"file_path": os.path.join(self.cwd, "README.md")}, link)):
            self.assertEqual(self.only_plans({"tool_input": tool, "cwd": cwd}), "deny", tool)
        for doc in ("", "not json", {"tool_input": {"file_path": 5}, "cwd": self.cwd}):
            self.assertEqual(self.only_plans(doc), "", doc)
        os.makedirs(os.path.join(self.cwd, "src"))
        os.symlink(os.path.join(self.tmp, "outside.txt"), os.path.join(self.cwd, "src", "out.txt"))
        os.makedirs(os.path.join(self.cwd, "openspec"))
        os.symlink(os.path.join(self.cwd, "src"), os.path.join(self.cwd, "openspec", "code"))
        for path in ("src/out.txt", "openspec/code/app.py"):
            self.assertEqual(self.only_plans({"tool_input": {"file_path": path}, "cwd": self.cwd}), "deny", path)

    def test_input_it_cannot_read_passes(self):
        for doc in ("", "not json", "[]", {}, {"tool_input": "x", "cwd": self.cwd},
                    {"tool_input": {"file_path": 5}, "cwd": self.cwd}, {"tool_input": {"file_path": "a.py"}}):
            self.assertEqual(self.no_code(doc), "", doc)


@unittest.skipUnless(all(shutil.which(t) for t in GATE_TOOLS), "a program the gate's tests link is missing")
class TheGate(unittest.TestCase):
    """the cases of the gate owner-run, in bash: a home folder of their own, a fake tailscale and ip; nothing leaves
    the machine"""
    def cases(self, name):
        r = subprocess.run(["bash", os.path.join(ROOT, "tests", name)], stdin=subprocess.DEVNULL,
                           capture_output=True, encoding="utf-8", timeout=120, start_new_session=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"passed [1-9][0-9]*, failed 0(, skipped [0-9]+)?\n$")

    def test_owner_run(self):
        self.cases("owner-run.test.sh")

    def test_the_hooks_of_the_gate(self):
        self.cases("owner-stop.test.sh")


INSTALLER = """echo "$OPENSPEC_VERSION" > "$OPENSPEC_INSTALL_DIR/asked"
printf '#!/bin/sh\\necho "telemetry=$OPENSPEC_TELEMETRY $*"\\n' > "$OPENSPEC_INSTALL_DIR/openspec"
chmod 755 "$OPENSPEC_INSTALL_DIR/openspec"
"""


class TheOpenSpecPlugin(unittest.TestCase):
    """bin/openspec with a made-up install script: nothing is downloaded"""
    BIN = os.path.join(PLUGINS, "openspec", "bin", "openspec")

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.home = self._t.name
        self.installer = os.path.join(self.home, "install.sh")
        with open(self.installer, "w", encoding="utf-8") as f:
            f.write(INSTALLER)

    def tearDown(self):
        self._t.cleanup()

    def run_it(self, *args):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self.home,
               "AGENT_KIT_OPENSPEC_URL": "file://" + self.installer}
        r = subprocess.run([self.BIN, *args], env=env, capture_output=True, encoding="utf-8", timeout=60)
        return r.returncode, r.stdout, r.stderr

    def version(self):
        with open(self.BIN, encoding="utf-8") as f:
            return re.search(r"^VERSION=(\S+)$", f.read(), re.M).group(1)

    @unittest.skipUnless(os.path.isdir(os.path.join(ROOT, ".claude", "skills")), "the version to install has no skills of the repository")
    def test_the_skills_are_those_of_the_repository(self):
        ours, theirs = os.path.join(PLUGINS, "openspec", "skills"), os.path.join(ROOT, ".claude", "skills")
        names = sorted(n for n in os.listdir(theirs) if n.startswith("openspec-"))
        self.assertEqual(sorted(os.listdir(ours)), names)
        for n in names:
            with open(os.path.join(ours, n, "SKILL.md"), "rb") as a:
                with open(os.path.join(theirs, n, "SKILL.md"), "rb") as b:
                    self.assertEqual(a.read(), b.read(), n)

    def test_the_first_call_installs_its_version_once(self):
        folder = os.path.join(self.home, ".local", "share", "agent-kit", "openspec", self.version())
        rc, out, err = self.run_it("list", "--json")
        self.assertEqual((rc, out), (0, "telemetry=0 list --json\n"))
        self.assertIn("downloading OpenSpec %s" % self.version(), err)
        with open(os.path.join(folder, "asked"), encoding="utf-8") as f:
            self.assertEqual(f.read().strip(), self.version())
        self.assertEqual(sorted(os.listdir(folder)), ["asked", "openspec"])     # no file of the download is left
        os.remove(self.installer)                                               # a second call downloads nothing
        self.assertEqual(self.run_it("list"), (0, "telemetry=0 list\n", ""))

    def test_init_writes_no_file_of_claude_code(self):
        self.assertEqual(self.run_it("init", "proj")[1], "telemetry=0 init proj --tools none\n")
        self.assertEqual(self.run_it("init", "--tools", "claude", "proj")[1], "telemetry=0 init --tools claude proj\n")

    def test_a_download_that_fails(self):
        os.remove(self.installer)
        rc, out, err = self.run_it("list")
        self.assertEqual((rc, out), (1, ""))
        self.assertIn("is not installed (the download failed)", err)
        folder = os.path.join(self.home, ".local", "share", "agent-kit", "openspec", self.version())
        self.assertEqual(os.listdir(folder), [])


if __name__ == "__main__":
    unittest.main()
