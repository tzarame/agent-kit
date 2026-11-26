"""test_sessions.py - kit/sessions and kit/cli.py: kit start (each check before each write, the dry run, the first
config, the clone, the session's config, the log), kit run, list, attach and kill, as kit-command, agent-launch,
profiles and session-settings say. Each test has a home folder of its own and fake processes; one test runs the real
tmux on a server of its own, and one the real install/gh-app.sh env with a dummy key, when bash and tmux are there.
    python3 -m unittest discover -s tests"""
import io as textio, json, os, re, shutil, stat, tempfile, time, unittest
from unittest import mock

from kit import cli, config, plan
from kit.sessions import autostart, run, start, tmux
from kit.io import LOG_MAX, ROOT, Io


def plan_flag(argv, name):
    """the value after the flag, or None"""
    return argv[argv.index(name) + 1] if name in argv else None


class Replaced(Exception):
    """the fake exec: the process would be replaced here"""


class FakeIo(Io):
    """the kit's io with a home folder of the test, and tmux, gh, gh-app.sh, the terminal and exec recorded"""

    def __init__(self, home, environ=None):
        Io.__init__(self, dict({"HOME": home, "PATH": "/usr/bin:/bin"}, **(environ or {})), home)
        self.out, self.err, self.inp = textio.StringIO(), textio.StringIO(), textio.StringIO()
        self.calls, self.ids, self.machine, self.listed = [], ["ab12", "cd34", "ef56"], "", ""
        self.answers, self.running, self.clone_rc, self.terminal = {}, set(), 0, False

    def machine_text(self):
        self.calls.append(("machine",))
        if isinstance(self.machine, Exception):
            raise self.machine
        return self.machine

    def clone(self, repo, folder, env):
        self.calls.append(("clone", repo, folder, env))
        if self.clone_rc == 0:
            os.makedirs(folder)
        return self.clone_rc

    def tmux(self, args, cwd=None):
        self.calls.append(("tmux", list(args), cwd))
        if args[0] == "list-sessions":
            return (0, self.listed, "") if self.listed else (1, "", "no server running")
        if args[0] == "has-session":
            return (0, "", "") if args[2] in ["=" + r for r in self.running] else (1, "", "can't find session")
        return self.answers.get(args[0], (0, "", ""))

    def new_id(self):
        return self.ids.pop(0) if self.ids else "zz99"

    def tty(self):
        return self.terminal

    def wait(self):
        self.calls.append(("wait",))

    def chdir(self, folder):
        self.calls.append(("chdir", folder))

    def exec(self, argv, env):
        self.calls.append(("exec", argv, env))
        raise Replaced()


def a_later_release():
    """the kit of a release 2 whose model's default went from haiku to sonnet, for the tests of the migration"""
    kit = dict(config.defaults(), version=2)
    return mock.patch.multiple(config, defaults=lambda path=None: json.loads(json.dumps(kit)),
                               MIGRATIONS=((2, (("default", "session.model", "haiku", "sonnet"),)),))


class Home(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.home = os.path.realpath(self._t.name)
        self.io = FakeIo(self.home)

    def tearDown(self):
        self._t.cleanup()

    def folder(self, *parts):
        p = os.path.join(self.home, *parts)
        os.makedirs(p, exist_ok=True)
        return p

    def put(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def user(self, doc):
        return self.put(self.io.config, json.dumps(doc))

    def start(self, *args):
        return start.start(self.io, list(args))

    def calls(self, kind):
        return [c for c in self.io.calls if c[0] == kind]

    def log(self):
        with open(self.io.log_path, encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def files(self):
        """each file under the home folder"""
        return sorted(os.path.relpath(os.path.join(d, f), self.home) for d, _, fs in os.walk(self.home) for f in fs)

    def session(self, sid="ab12"):
        return config.read_json(self.io.session_file(sid))


class TheStart(Home):
    def test_the_first_start(self):
        web = self.folder("web")
        self.assertEqual(self.start("web"), 0)
        self.assertEqual(self.io.out.getvalue(), "started ab12; open it: kit attach ab12\n")
        saved = config.read_json(self.io.config)
        self.assertEqual(saved["projects"], {"web": {"folder": web}})
        self.assertEqual(dict(saved, projects={}), config.defaults())
        doc = self.session()
        self.assertEqual((doc["id"], doc["project"], doc["folder"]), ("ab12", "web", web))
        self.assertEqual(doc["argv"][:3], ["claude", "--permission-mode", "auto"])
        self.assertEqual(doc["env"][plan.SESSION_VAR], "ab12")
        self.assertEqual(self.calls("tmux"), [("tmux", ["has-session", "-t", "=ab12"], None),
                                              ("tmux", tmux.new_session("ab12", "web", self.io.python, self.io.main),
                                               web)])

    def test_the_session_s_files_are_the_user_s_only(self):
        self.folder("web")
        self.start("web")
        for p in (self.io.config, self.io.session_file("ab12"), self.io.log_path):
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600, p)

    def test_the_log_has_each_change(self):
        web = self.folder("web")
        self.start("web", "--opus")
        (record,) = self.log()
        self.assertEqual((record["command"], record["project"], record["id"]), ("start", "web", "ab12"))
        self.assertEqual(record["session"]["keys"], ["--opus"])
        self.assertEqual([next(iter(c)) for c in record["changes"]], ["copy", "add", "write", "tmux"])
        self.assertEqual(record["changes"][0]["content"], config.defaults())
        self.assertEqual(record["changes"][1]["entry"], {"folder": web})
        self.assertNotIn("error", record)

    def test_a_full_log(self):
        self.folder("web")
        self.put(self.io.log_path, "x" * (LOG_MAX + 1))
        self.assertEqual(self.start("web"), 0)
        self.assertEqual(os.path.getsize(self.io.log_path + ".1"), LOG_MAX + 1)
        self.assertEqual([r["command"] for r in self.log()], ["start"])

    def test_a_token_is_only_its_fingerprint_in_the_log(self):
        self.folder("web")
        self.user({"projects": {"web": {"folder": self.home + "/web", "env": {"GH_TOKEN": "s3cret-value"}}}})
        self.assertEqual(self.start("web"), 0)
        with open(self.io.log_path, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("s3cret-value", text)
        self.assertIn(plan.fingerprint("s3cret-value"), text)
        self.assertEqual(self.session()["env"]["GH_TOKEN"], "s3cret-value")

    def test_a_new_conversation_by_its_key(self):
        web = self.folder("web")
        self.start("web")
        self.assertNotIn("--continue", self.session()["argv"])      # the folder has no conversation yet
        self.put(os.path.join(self.home, ".claude", "projects", re.sub(r"[^A-Za-z0-9]", "-", web), "c.jsonl"), "{}")
        self.start("web")
        self.assertIn("--continue", self.session("cd34")["argv"])
        self.assertEqual(self.session("cd34")["keys"], [])
        self.start("web", "--new")
        self.assertNotIn("--continue", self.session("ef56")["argv"])
        self.assertEqual(self.session("ef56")["keys"], ["--new"])
        self.io.ids = ["gh78"]
        self.start("web")                                           # the key was for that start only
        self.assertIn("--continue", self.session("gh78")["argv"])

    def test_a_dry_run_changes_nothing(self):
        self.folder("web")
        self.assertEqual(self.start("web", "--dry-run"), 0)
        doc = json.loads(self.io.out.getvalue())
        self.assertEqual((doc["id"], doc["project"]), ("ab12", "web"))
        self.assertIn("kit start --dry-run: would", self.io.err.getvalue())
        self.assertEqual(self.files(), [])
        self.assertEqual(self.calls("tmux") + self.calls("clone"), [])

    def test_a_dry_run_shows_a_token_as_its_fingerprint(self):
        self.folder("web")
        self.user({"projects": {"web": {"folder": self.home + "/web", "env": {"API_KEY": "s3cret-value"}}}})
        self.start("web", "--dry-run")
        self.assertNotIn("s3cret-value", self.io.out.getvalue() + self.io.err.getvalue())

    def test_a_broken_config_is_kept(self):
        self.folder("web")
        self.put(self.io.config, "{")
        self.assertEqual(self.start("web"), 2)
        with open(self.io.config) as f:
            self.assertEqual(f.read(), "{")
        self.assertEqual(self.files(), [".config/agent-kit/config.json"])
        self.assertEqual(self.calls("tmux"), [])

    def test_no_project_and_no_folder(self):
        self.assertEqual(self.start("web"), 2)
        self.assertIn("give owner/web to clone it", self.io.err.getvalue())
        self.assertEqual(self.files(), [])

    def test_the_folder_of_a_project_is_gone(self):
        self.user({"projects": {"web": {"folder": self.home + "/gone"}}})
        self.assertEqual(self.start("web"), 2)
        self.assertIn("the folder of web is not there: %s/gone" % self.home, self.io.err.getvalue())

    def test_a_folder_that_is_a_file(self):
        self.put(os.path.join(self.home, "web"), "")
        self.assertEqual(self.start("acme/web"), 2)
        self.assertEqual(self.calls("clone"), [])

    def test_another_agent(self):
        self.folder("web")
        rules = os.path.join(ROOT, "content", "plugins", "agent-kit", "system-prompt.md")
        self.user({"version": 3, "session": {"system_prompt": rules, "agent": "dev"}})
        self.assertEqual(self.start("web", "--agent", "design", "--dry-run"), 0)
        argv = json.loads(self.io.out.getvalue())["argv"]
        text = argv[argv.index("--system-prompt") + 1]
        with open(rules, encoding="utf-8") as f:
            self.assertTrue(text.startswith(f.read().strip()))
        self.assertIn("You are a designer.", text)
        self.assertNotIn("description:", text)
        self.assertIn(os.path.join(ROOT, "content", "plugins", "design"), argv)
        self.assertNotIn(os.path.join(ROOT, "content", "plugins", "dev"), argv)

    def test_an_agent_of_the_config_over_one_of_the_kit(self):
        web = self.folder("web")
        prompt = self.put(os.path.join(self.home, "prompts", "work.md"), "Work this way.\n")
        self.user({"version": 3, "agents": {"work": {"system_prompt": "~/prompts/work.md", "agent": "dev",
                                                     "model": "opus"}},
                   "projects": {"web": {"folder": web, "agent": "work", "model": "sonnet"}}})
        self.assertEqual(self.start("web", "--high"), 0)
        doc = self.session()
        argv = doc["argv"]
        self.assertEqual((plan_flag(argv, "--model"), plan_flag(argv, "--effort")), ("opus", "high"))
        self.assertEqual(plan_flag(argv, "--system-prompt").split("\n\n")[0], "Work this way.")
        self.assertIn("You are a developer.", plan_flag(argv, "--system-prompt"))
        self.assertTrue(os.path.isfile(prompt))
        self.assertIn(os.path.join(ROOT, "content", "plugins", "dev"), argv)
        self.assertEqual(doc["config"]["agent"], "work")

    def test_an_agent_there_is_not(self):
        web = self.folder("web")
        self.user({"version": 3, "agents": {"work": {}}, "projects": {"web": {"folder": web}}})
        self.assertEqual(self.start("web", "--agent", "nope"), 2)
        self.assertIn("agent: nope: no such agent; there are design, dev, dev-eco, qa, spec, toolsmith, work", self.io.err.getvalue())
        self.assertEqual(self.calls("tmux"), [])

    def test_a_prompt_s_file_that_is_missing(self):
        web = self.folder("web")
        self.user({"version": 2, "projects": {"web": {"folder": web, "system_prompt": "~/prompts/gone.md"}}})
        self.assertEqual(self.start("web"), 2)
        self.assertIn("system_prompt: ~/prompts/gone.md", self.io.err.getvalue())
        self.assertEqual(self.calls("tmux"), [])
        self.assertFalse(os.path.exists(self.io.sessions))

    def test_the_mcp_servers_file(self):
        web = self.folder("web")
        servers = {"docs": {"command": "docs-server", "env": {"DOCS_TOKEN": "tok_secret"}}}
        self.user({"version": 2, "projects": {"web": {"folder": web, "mcp_servers": servers, "mcp_strict": True}}})
        self.assertEqual(self.start("web"), 0)
        path = self.io.mcp_file("ab12")
        self.assertEqual(config.read_json(path), {"mcpServers": servers})
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(plan_flag(self.session()["argv"], "--mcp-config"), path)
        for kept in (self.io.log_path, self.io.session_file("ab12")):
            with open(kept, encoding="utf-8") as f:
                self.assertNotIn("tok_secret", f.read(), kept)
        self.io.listed = "ab12 web\n"
        self.assertEqual(tmux.kill(self.io, ["ab12"]), 0)
        self.assertFalse(os.path.exists(path))
        self.assertIn({"removed": path}, self.log()[-1]["changes"])

    def test_an_agent_there_is_not(self):
        self.folder("web")
        self.assertEqual(self.start("web", "--agent", "nope"), 2)
        self.assertIn("agent: nope: no such agent; there are design, dev, dev-eco, qa", self.io.err.getvalue())
        self.assertEqual(self.files(), [])

    def test_a_plugin_there_is_not(self):
        self.folder("web")
        self.assertEqual(self.start("web", "--plugin", "nope"), 2)
        self.assertIn("plugins: nope: no such plugin", self.io.err.getvalue())
        self.assertEqual(self.files(), [])

    def test_a_key_of_a_parked_part(self):
        self.folder("web")
        self.assertEqual(self.start("web", "--vscode"), 2)
        self.assertEqual(self.files(), [])

    def test_a_folder_from_the_home(self):
        src = self.folder("src", "web")
        self.user({"projects": {"web": {"folder": "~/src/web"}}})
        self.assertEqual(self.start("web"), 0)
        self.assertEqual(self.session()["folder"], src)
        self.assertEqual(self.calls("tmux")[-1][2], src)
        self.assertEqual(config.read_json(self.io.config)["projects"]["web"], {"folder": "~/src/web"})

    def test_the_root_of_the_projects(self):
        self.io = FakeIo(self.home, {"AGENT_KIT_ROOT": "~/src"})
        src = self.folder("src", "web")
        self.assertEqual(self.start("web"), 0)
        self.assertEqual(self.session()["folder"], src)

    def test_a_second_session_of_the_project(self):
        self.folder("web")
        self.start("web")
        self.io.ids = ["ab12", "cd34"]
        self.assertEqual(self.start("web"), 0)
        self.assertEqual(self.session("cd34")["project"], "web")
        self.assertEqual(self.session("ab12")["project"], "web")

    def test_an_id_that_tmux_has(self):
        self.folder("web")
        self.io.running = {"ab12"}
        self.assertEqual(self.start("web"), 0)
        self.assertEqual(self.session("cd34")["id"], "cd34")

    def test_no_free_id(self):
        self.folder("web")
        self.io.running = {"ab12", "cd34", "ef56", "zz99"}
        self.assertEqual(self.start("web"), 1)
        self.assertIn("no free ID", self.io.err.getvalue())
        self.assertEqual(self.files(), [])

    def test_the_copy_of_an_older_release_is_migrated(self):
        web = self.folder("web")
        self.user({"session": {"model": "haiku"}, "projects": {"web": {"folder": web}}})
        with open(self.io.config, encoding="utf-8") as f:
            before = f.read()
        with a_later_release():
            self.assertEqual(self.start("web"), 0)
        self.assertEqual(config.read_json(self.io.config),
                         {"version": 2, "session": {"model": "sonnet"}, "projects": {"web": {"folder": web}}})
        with open(self.io.config + ".v1", encoding="utf-8") as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(self.session()["config"]["model"], "sonnet")
        (record,) = self.log()
        self.assertEqual([next(iter(c)) for c in record["changes"]], ["migrate", "write", "tmux"])
        self.assertEqual(record["changes"][0]["changes"], [{"version": 1, "to": 2},
                                                           {"set": "session.model", "from": "haiku", "to": "sonnet"}])

    def test_a_dry_run_shows_the_migration(self):
        web = self.folder("web")
        self.user({"session": {"model": "haiku"}, "projects": {"web": {"folder": web}}})
        with a_later_release():
            self.assertEqual(self.start("web", "--dry-run"), 0)
        self.assertIn('would {"migrate": "%s"' % self.io.config, self.io.err.getvalue())
        self.assertEqual(json.loads(self.io.out.getvalue())["config"]["model"], "sonnet")
        self.assertEqual(self.files(), [".config/agent-kit/config.json"])

    def test_tmux_fails(self):
        self.folder("web")
        self.io.answers["new-session"] = (1, "", "no server")
        self.assertEqual(self.start("web"), 1)
        (record,) = self.log()
        self.assertEqual(record["error"], "kit start: tmux: no server")
        self.assertEqual(len(record["changes"]), 3)


class TheProject(Home):
    def test_a_repository_to_clone(self):
        web = os.path.join(self.home, "web")
        self.assertEqual(self.start("acme/web"), 0)
        (call,) = self.calls("clone")
        self.assertEqual(call[1:3], ("acme/web", web))
        self.assertEqual(config.read_json(self.io.config)["projects"]["web"], {"folder": web, "repo": "acme/web"})
        self.assertEqual(self.session()["repo"], "acme/web")
        self.assertEqual(self.log()[0]["changes"][1], {"clone": "acme/web", "into": web})

    def test_the_clone_has_the_machine_s_variables_only(self):
        self.io.machine = "export AGENT_KIT_MACHINE=me@box\n"
        self.start("acme/web")
        env = self.calls("clone")[0][3]
        self.assertEqual(env["AGENT_KIT_MACHINE"], "me@box")
        self.assertNotIn(plan.SESSION_VAR, env)

    def test_a_clone_that_fails(self):
        self.io.clone_rc = 128
        self.assertEqual(self.start("acme/web"), 1)
        self.assertEqual(config.read_json(self.io.config)["projects"], {})
        self.assertFalse(os.path.exists(self.io.session_file("ab12")))
        (record,) = self.log()
        self.assertIn("gh repo clone acme/web", record["error"])
        self.assertEqual([next(iter(c)) for c in record["changes"]], ["copy"])

    def test_the_repository_of_the_config(self):
        self.user({"projects": {"web": {"folder": self.home + "/web", "repo": "acme/web"}}})
        self.assertEqual(self.start("web"), 0)
        self.assertEqual(self.calls("clone")[0][1], "acme/web")

    def test_another_repository_than_the_config_s(self):
        self.user({"projects": {"web": {"folder": self.home + "/web", "repo": "acme/web"}}})
        self.assertEqual(self.start("other/web"), 2)
        self.assertIn("has the repository acme/web", self.io.err.getvalue())

    def test_the_old_file_is_read_once(self):
        self.folder("web")
        old = self.put(os.path.join(self.io.conf, "projects", "web.env"), "MODEL=opus\nEFFORT=high\nWIN=132k\n")
        self.assertEqual(self.start("web"), 0)
        self.assertEqual(config.read_json(self.io.config)["projects"]["web"],
                         {"folder": self.home + "/web", "context_window": 132000})
        self.assertEqual((self.session()["config"]["model"], self.session()["config"]["context_window"]),
                         (None, 132000))
        self.put(old, "WIN=200k\n")
        self.start("web")
        self.assertEqual(self.session("cd34")["config"]["context_window"], 132000)
        self.assertTrue(os.path.isfile(old))

    def test_a_broken_old_file(self):
        self.folder("web")
        self.put(os.path.join(self.io.conf, "projects", "web.env"), "MODEL=$(boom)\n")
        self.assertEqual(self.start("web"), 2)
        self.assertFalse(os.path.exists(self.io.config))


GH_APP_ENV = """\
export PATH=/h/.local/bin:/k/install/bin:/usr/bin
export GIT_CONFIG_KEY_0=credential.https://github.com.helper GIT_CONFIG_VALUE_0='' \
GIT_CONFIG_KEY_1=credential.https://github.com.helper \
GIT_CONFIG_VALUE_1=\\!bash\\ /k/install/gh-app.sh\\ git-credential \
GIT_CONFIG_KEY_2=credential.https://github.com.useHttpPath GIT_CONFIG_VALUE_2=true
export GIT_CONFIG_COUNT=3 AGENT_KIT_MACHINE=me@box
"""


class TheMachine(Home):
    def test_github_as_the_app(self):
        self.folder("web")
        self.io.machine = GH_APP_ENV
        self.start("web")
        env = self.session()["env"]
        self.assertEqual(env["GIT_CONFIG_VALUE_0"], "")
        self.assertEqual(env["GIT_CONFIG_VALUE_1"], "!bash /k/install/gh-app.sh git-credential")
        self.assertEqual((env["GIT_CONFIG_COUNT"], env["AGENT_KIT_MACHINE"]), ("3", "me@box"))
        self.assertEqual(env["PATH"], "/h/.local/bin:/k/install/bin:/usr/bin")

    def test_no_key_of_the_app(self):
        self.folder("web")
        self.start("web")
        self.assertNotIn("AGENT_KIT_MACHINE", self.session()["env"])

    def test_the_script_fails(self):
        self.folder("web")
        self.io.machine = OSError("install/gh-app.sh env: exit code 1")
        self.assertEqual(self.start("web"), 0)
        self.assertIn("GitHub as the App: install/gh-app.sh env: exit code 1; the session goes on without it",
                      self.io.err.getvalue())
        self.assertNotIn("AGENT_KIT_MACHINE", self.session()["env"])

    def test_a_line_that_is_not_an_export(self):
        self.folder("web")
        self.io.machine = "rm -rf /\n"
        self.assertEqual(self.start("web"), 0)
        self.assertIn("is not a line of export", self.io.err.getvalue())

    @unittest.skipUnless(shutil.which("bash"), "no bash")
    def test_the_real_script_with_a_dummy_key(self):
        """install/gh-app.sh env with a key file that is no key: it only prints, and asks GitHub nothing"""
        self.put(os.path.join(self.io.conf, "app-key.pem"), "not a key\n")
        real = Io({"HOME": self.home, "PATH": "/usr/bin:/bin", "AGENT_KIT_MACHINE": "inherited",
                   "GIT_CONFIG_COUNT": "5"}, self.home)
        real.err = textio.StringIO()
        env = start._machine(real)
        self.assertEqual(real.err.getvalue(), "")
        self.assertEqual(env["GIT_CONFIG_COUNT"], "3")
        install = os.path.join(os.path.realpath(ROOT), "install")
        self.assertEqual(env["GIT_CONFIG_VALUE_1"], "!bash %s/gh-app.sh git-credential" % install)
        self.assertEqual(env["PATH"], "%s/bin:%s/.local/bin:/usr/bin:/bin" % (install, self.home))
        self.assertNotEqual(env["AGENT_KIT_MACHINE"], "inherited")


class TheEnvironment(unittest.TestCase):
    def test_the_variables_the_kit_drops(self):
        env = run.child_env({"A": "1", plan.WINDOW_VAR: "9"}, {"env": {"B": "2"}, "unset": [plan.WINDOW_VAR]})
        self.assertEqual(env, {"A": "1", "B": "2"})

    def test_git_s_settings_of_the_session(self):
        inherited = {"GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_1": "x", "GIT_CONFIG_VALUE_1": "y", "A": "1"}
        self.assertEqual(run.child_env(inherited, {"env": {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "k"}}),
                         {"A": "1", "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "k"})
        self.assertEqual(run.child_env(inherited, {"env": {}}), inherited)

    def test_the_programs_of_the_home_folder_are_on_the_sessions_path(self):
        self.assertEqual(run.with_bin({"PATH": "/usr/bin:/bin"}, "/h")["PATH"], "/h/.local/bin:/usr/bin:/bin")
        self.assertEqual(run.with_bin({}, "/h")["PATH"], "/h/.local/bin:/usr/local/bin:/usr/bin:/bin")
        there = {"PATH": "/usr/bin:/h/.local/bin"}
        self.assertIs(run.with_bin(there, "/h"), there)


class TheRun(Home):
    def write(self, **over):
        doc = dict({"id": "ab12", "project": "web", "folder": "/h/web", "env": {"B": "2"}, "unset": ["A"],
                    "argv": ["claude", "--model", "haiku"]}, **over)
        config.write(self.io.session_file("ab12"), doc)

    def test_the_session_s_config_into_claude(self):
        self.write()
        self.io.environ = {"A": "1", "C": "3"}
        with self.assertRaises(Replaced):
            run.run(self.io, ["ab12"])
        self.assertEqual(self.io.calls, [("chdir", "/h/web"), ("exec", ["claude", "--model", "haiku"],
                                                               run.with_bin({"B": "2", "C": "3"}, self.io.home))])

    def test_not_an_id(self):
        for args in ([], ["AB12"], ["ab12", "x"], ["../x"]):
            self.assertEqual(run.run(self.io, args), 2, args)
        self.assertEqual(self.io.calls, [])

    def test_no_config_of_the_session(self):
        self.assertEqual(run.run(self.io, ["ab12"]), 1)
        self.assertIn("kit run ab12: ", self.io.err.getvalue())
        self.assertEqual(self.calls("wait"), [])

    def test_the_window_stays_open_on_an_error(self):
        self.io.terminal = True
        self.write(id="cd34")
        self.assertEqual(run.run(self.io, ["ab12"]), 1)
        self.assertIn("the config of the session 'cd34'", self.io.err.getvalue())
        self.assertEqual(self.calls("wait"), [("wait",)])

    def test_a_config_that_is_not_a_session(self):
        for over in ({"argv": []}, {"argv": "claude"}, {"env": {"A": 1}}, {"folder": None}):
            self.write(**over)
            self.assertEqual(run.run(self.io, ["ab12"]), 1, over)
        self.assertEqual(self.calls("exec"), [])


class TheSessions(Home):
    LISTED = "ab12 web\nmain \nlong-name api\ncd34 api\n"

    def test_list(self):
        self.io.listed = self.LISTED
        self.assertEqual(tmux.list_sessions(self.io, []), 0)
        self.assertEqual(self.io.out.getvalue(), "ID     PROJECT\nab12   web\ncd34   api\nopen one: kit attach ID\n")
        self.assertEqual(self.calls("tmux")[-1][1],
                         ["list-sessions", "-F", "#{session_name} #{@agent-kit}", "-f", "#{@agent-kit}"])

    def test_list_removes_the_config_of_a_gone_session(self):
        self.io.listed = self.LISTED
        for sid in ("ab12", "gone", "new1"):
            self.put(self.io.session_file(sid), "{}")
        self.put(self.io.mcp_file("gone"), "{}")
        old = time.time() - 3600
        for path in (self.io.session_file("ab12"), self.io.session_file("gone")):
            os.utime(path, (old, old))
        self.assertEqual(tmux.list_sessions(self.io, []), 0)
        self.assertTrue(os.path.exists(self.io.session_file("ab12")))      # running
        self.assertTrue(os.path.exists(self.io.session_file("new1")))      # a start on its way
        self.assertFalse(os.path.exists(self.io.session_file("gone")))
        self.assertFalse(os.path.exists(self.io.mcp_file("gone")))
        (record,) = self.log()
        self.assertEqual(record["changes"], [{"removed": self.io.session_file("gone")},
                                             {"removed": self.io.mcp_file("gone")}])

    def test_list_keeps_the_configs_when_tmux_fails(self):
        self.io.answers["list-sessions"] = (1, "", "permission denied")
        self.io.tmux = lambda args, cwd=None: (1, "", "permission denied")
        self.put(self.io.session_file("gone"), "{}")
        old = time.time() - 3600
        os.utime(self.io.session_file("gone"), (old, old))
        tmux.list_sessions(self.io, [])
        self.assertTrue(os.path.exists(self.io.session_file("gone")))
        tmux.sweep(FakeIo(self.home))                                   # no server: every session is gone
        self.assertFalse(os.path.exists(self.io.session_file("gone")))

    def test_list_with_no_server(self):
        self.assertEqual(tmux.list_sessions(self.io, []), 0)
        self.assertEqual(self.io.out.getvalue(), "no session is running; start one: kit start PROJECT\n")

    def test_attach(self):
        self.io.listed = self.LISTED
        with self.assertRaises(Replaced):
            tmux.attach(self.io, ["cd34"])
        self.assertEqual(self.calls("exec")[0][1], ["tmux", "attach-session", "-t", "=cd34"])

    def test_attach_inside_tmux(self):
        self.io = FakeIo(self.home, {"TMUX": "/tmp/x,1,0"})
        self.io.listed = self.LISTED
        self.assertEqual(tmux.attach(self.io, ["ab12"]), 0)
        self.assertEqual(self.calls("tmux")[-1][1], ["switch-client", "-t", "=ab12"])

    def test_a_session_that_is_not_the_kit_s(self):
        self.io.listed = self.LISTED
        for args in (["main"], ["zz99"], []):
            self.assertEqual(tmux.attach(self.io, args), 2)
            self.assertEqual(tmux.kill(self.io, args), 2)
        self.assertEqual(self.calls("exec"), [])
        self.assertEqual([c for c in self.calls("tmux") if c[1][0] == "kill-session"], [])

    def test_kill(self):
        self.io.listed = self.LISTED
        self.put(self.io.session_file("ab12"), "{}")
        self.assertEqual(tmux.kill(self.io, ["ab12"]), 0)
        self.assertEqual(self.io.out.getvalue(), "stopped ab12\n")
        self.assertEqual(self.calls("tmux")[-1][1], ["kill-session", "-t", "=ab12"])
        self.assertFalse(os.path.exists(self.io.session_file("ab12")))
        (record,) = self.log()
        self.assertEqual(record["changes"], [{"stopped": "ab12"}, {"removed": self.io.session_file("ab12")}])

    def test_kill_fails(self):
        self.io.listed = self.LISTED
        self.io.answers["kill-session"] = (1, "", "can't find session")
        self.put(self.io.session_file("ab12"), "{}")
        self.assertEqual(tmux.kill(self.io, ["ab12"]), 1)
        self.assertTrue(os.path.exists(self.io.session_file("ab12")))

    def test_a_start_inside_tmux(self):
        self.io = FakeIo(self.home, {"TMUX": "/tmp/x,1,0"})
        self.folder("web")
        self.assertEqual(self.start("web"), 0)
        self.assertEqual(self.calls("tmux")[-1][1], ["switch-client", "-t", "=ab12"])

    def test_a_start_on_a_terminal(self):
        self.folder("web")
        self.io.terminal = True
        with self.assertRaises(Replaced):
            self.start("web")
        self.assertEqual(self.calls("exec")[0][1], ["tmux", "attach-session", "-t", "=ab12"])


class TheAutostart(Home):
    def projects(self, **autostart):
        """a config with a folder for each project, and its autostart field when it is given"""
        entries = {}
        for name, value in autostart.items():
            entries[name] = {"folder": self.folder(name)}
            if value is not None:
                entries[name]["autostart"] = value
        self.user({"projects": entries})

    def autostart(self, *args):
        return autostart.autostart(self.io, list(args))

    def test_the_projects_with_autostart(self):
        self.projects(web=True, api=True, docs=False, old=None)
        self.io.terminal = True                  # a start of autostart opens nothing, even on a terminal
        self.assertEqual(self.autostart(), 0)
        news = [c[1] for c in self.calls("tmux") if c[1][0] == "new-session"]
        self.assertEqual([w[3] for w in news], ["ab12", "cd34"])
        self.assertEqual([w[-1] for w in news], ["api", "web"])
        self.assertEqual(self.calls("exec"), [])
        out = self.io.out.getvalue()
        self.assertIn("kit autostart: api\nstarted ab12; open it: kit attach ab12\n", out)
        self.assertNotIn("docs", out)
        last = dict(self.log()[-1])
        last.pop("time")
        self.assertEqual(last, {"command": "autostart", "started": ["api", "web"], "running": {}, "failed": []})
        self.assertEqual([r["command"] for r in self.log()], ["start", "start", "autostart"])

    def test_a_project_already_running(self):
        self.projects(web=True, api=True)
        self.io.listed = "zz11 web\nmain \n"
        self.assertEqual(self.autostart(), 0)
        news = [c[1] for c in self.calls("tmux") if c[1][0] == "new-session"]
        self.assertEqual([w[-1] for w in news], ["api"])
        self.assertIn("kit autostart: web: already running, kit attach zz11\n", self.io.out.getvalue())
        self.assertEqual(self.log()[-1]["running"], {"web": "zz11"})

    def test_inside_tmux_there_is_no_switch(self):
        self.io = FakeIo(self.home, {"TMUX": "/tmp/x,1,0"})
        self.projects(web=True)
        self.assertEqual(self.autostart(), 0)
        self.assertEqual([c for c in self.calls("tmux") if c[1][0] == "switch-client"], [])

    def test_a_start_that_fails(self):
        self.projects(web=True, api=True)
        self.io.answers["new-session"] = (1, "", "server exited unexpectedly")
        self.assertEqual(self.autostart(), 1)
        self.assertEqual(self.log()[-1]["failed"], ["api", "web"])
        self.assertIn("kit autostart: api: not started (exit code 1)", self.io.err.getvalue())

    def test_a_dry_run_changes_nothing(self):
        self.projects(web=True)
        before = self.files()
        self.assertEqual(self.autostart("--dry-run"), 0)
        self.assertEqual(self.files(), before)
        self.assertIn('kit start --dry-run: would {"tmux"', self.io.err.getvalue())
        self.assertEqual([c for c in self.calls("tmux") if c[1][0] == "new-session"], [])

    def test_no_config_and_no_project(self):
        self.assertEqual(self.autostart(), 0)
        self.assertIn("nothing to start", self.io.out.getvalue())
        self.assertFalse(os.path.lexists(self.io.config))
        self.projects(docs=False)
        self.assertEqual(self.autostart(), 0)
        self.assertIn('no project has "autostart": true', self.io.out.getvalue())

    def test_a_wrong_config_or_option(self):
        self.user({"projects": {"web": {"folder": "~/web", "autostart": "yes"}}})
        self.assertEqual(self.autostart(), 2)
        self.assertIn("error", self.log()[-1])
        self.assertEqual(self.autostart("--force"), 2)
        self.assertIn("kit autostart: unknown option --force", self.io.err.getvalue())
        self.assertEqual([c for c in self.calls("tmux") if c[1][0] == "new-session"], [])


class TheCommand(Home):
    def main(self, *argv):
        return cli.main(list(argv), self.io)

    def test_help(self):
        for argv in ((), ("help",), ("--help",), ("-h",)):
            self.io.out = textio.StringIO()
            self.assertEqual(self.main(*argv), 0)
            self.assertTrue(self.io.out.getvalue().startswith("usage: kit COMMAND"))

    def test_the_old_command(self):
        self.assertEqual(self.main("new", "web"), 2)
        self.assertIn("kit start PROJECT", self.io.err.getvalue())
        self.assertEqual(self.io.calls, [])

    def test_parked_and_unknown_commands(self):
        for cmd in ("killall", "nope"):
            self.assertEqual(self.main(cmd), 2, cmd)
        self.assertIn("kit: unknown command nope", self.io.err.getvalue())
        self.assertEqual(self.io.calls, [])

    def test_setup_is_the_set_up_with_no_start(self):
        with self.assertRaises(Replaced):
            self.main("setup", "--no-update")
        argv = self.calls("exec")[0][1]
        self.assertEqual(argv, ["bash", os.path.join(ROOT, "install", "setup.sh"), "--no-start", "--no-update"])
        self.assertTrue(os.path.isfile(argv[1]))

    def test_update_is_the_update_s_own_script_and_takes_no_word(self):
        with self.assertRaises(Replaced):
            self.main("update")
        argv = self.calls("exec")[0][1]
        self.assertEqual(argv, ["bash", os.path.join(ROOT, "install", "update.sh")])
        self.assertTrue(os.path.isfile(argv[1]))
        self.assertEqual(self.main("update", "now"), 2)

    def test_dashboard_is_the_dashboard_s_own_program_on_the_tailscale_address(self):
        with self.assertRaises(Replaced):
            self.main("dashboard", "--port", "9001")
        argv = self.calls("exec")[0][1]
        self.assertEqual(argv[1:], ["-I", os.path.join(ROOT, "dashboard", "dash.py"), "--bind", "tailscale",
                                    "--port", "9001"])
        self.assertTrue(os.path.isfile(argv[2]))

    def test_the_commands(self):
        self.assertEqual(self.main("list"), 0)
        self.assertEqual(self.main("start"), 2)
        self.assertIn("the project's name is missing", self.io.err.getvalue())

    def test_the_usage_names_each_key(self):
        self.main("help")
        for k in plan.MODELS + plan.EFFORTS:
            self.assertIn("--" + k, self.io.out.getvalue())


@unittest.skipUnless(shutil.which("tmux"), "no tmux")
class TheRealTmux(unittest.TestCase):
    """the words of tmux on a server of the test's own (TMUX_TMPDIR is the test's folder, no TMUX): a session of the
    kit is started, marked, listed and stopped; the user's tmux is not reached"""

    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.home = os.path.realpath(t.name)
        # the server's socket is TMUX_TMPDIR/tmux-UID/default, and the path of a socket has 107 bytes at most
        socket = os.path.join(self.home, "tmux-%d" % os.getuid(), "default")
        if len(socket.encode()) > 107:
            self.skipTest("the test's folder is too long for the socket of tmux: %s" % socket)
        self.io = Io({"HOME": self.home, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TMUX_TMPDIR": self.home},
                     self.home)
        self.io.out, self.io.err = textio.StringIO(), textio.StringIO()
        self.addCleanup(self.io.tmux, ["kill-server"])

    def test_a_session_of_the_kit(self):
        config.write(self.io.session_file("ab12"), {"id": "ab12", "project": "web", "folder": self.home,
                                                    "env": {}, "unset": [], "argv": ["sleep", "30"]})
        rc, _, err = self.io.tmux(tmux.new_session("ab12", "web", self.io.python, self.io.main), cwd=self.home)
        self.assertEqual((rc, err), (0, ""))
        self.io.tmux(["new-session", "-d", "-s", "main", "sleep", "30"])
        self.assertEqual(tmux.sessions(self.io), [("ab12", "web")])
        self.assertTrue(self.io.has_session("ab12"))
        self.assertEqual(tmux.kill(self.io, ["ab12"]), 0)
        self.assertEqual(tmux.sessions(self.io), [])
        self.assertTrue(self.io.has_session("main"))


if __name__ == "__main__":
    unittest.main()
