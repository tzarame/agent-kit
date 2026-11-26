"""test_setup.py - install/setup.sh, as set-up and agent-launch say: the keys of setup.sh
(install/keys.sh) against those of kit start, a wrong key refused before any step, --help, root, the dry run that
changes nothing, a first set-up with the start last, GitHub not signed in, no project, a missing package or Claude
Code, and the update of the kit's copy (install/common.sh repo_update) with the run of the new release. Each test has
a folder of its own: the home, the projects' folder, and a PATH of the system's tools with fake git, gh, claude, curl,
sudo, tmux and id; nothing reaches the network, the machine's packages, the user's tmux or the kit's own copy. The
update is tried on a repository of the test, with the real git.
    python3 -m unittest discover -s tests"""
import json, os, re, shlex, shutil, stat, subprocess, tempfile, unittest

from kit import config, plan
from kit.io import ROOT

SETUP = os.path.join(ROOT, "install", "setup.sh")
KEYS = os.path.join(ROOT, "install", "keys.sh")
TOOLS = ("bash", "sh", "env", "dirname", "readlink", "mktemp", "rm", "mkdir", "chmod", "grep", "sed", "sort", "tail",
         "head", "df", "awk", "cut", "seq", "sleep", "tr", "uname", "cat", "date", "ls", "mv", "stat", "paste",
         "python3")
# the fakes: each writes its words to FAKE_LOG, then answers; FAKE_GH and FAKE_CLAUDE are the exit codes of their
# auth status (1, not signed in, by default)
FAKES = {
    "git": 'case "$*" in *describe*) echo v0.0.0-test ;; *rev-parse*) echo 0123abcd ;; esac',
    "gh": 'case "$*" in "auth status") exit "${FAKE_GH:-1}" ;; "api user --jq .login") echo someone ;;\n'
          '  "repo clone "*) mkdir -p "$4" ;; esac',
    "claude": 'case "$*" in --version) echo "2.1.327 (Claude Code)" ;; "auth status") exit "${FAKE_CLAUDE:-1}" ;;\n'
              '  "plugin list --json") echo "${FAKE_PLUGINS:-[]}" ;;\n'
              '  "plugin marketplace list --json") echo "${FAKE_MARKETS:-[]}" ;; esac',
    "curl": "exit 22",
    "sudo": "exit 1",
    "tmux": 'case "$1" in has-session|list-sessions) exit 1 ;; esac',
}
BASH = shutil.which("bash")
HAVE = BASH and all(shutil.which(t) for t in TOOLS + ("id",))


def fake(folder, name, body):
    p = os.path.join(folder, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write("#!/bin/sh\n" + body)
    os.chmod(p, 0o755)


def tools(folder, *more):
    """a folder for the PATH: the system's tools (and more) as links, and a fake id whose -u is FAKE_UID or 1000, so
    the set-up runs as a normal user in a container run as root too"""
    os.mkdir(folder)
    for name in TOOLS + more:
        os.symlink(shutil.which(name), os.path.join(folder, name))
    fake(folder, "id", 'if [ "$*" = -u ]; then echo "${FAKE_UID:-1000}"; exit 0; fi\nexec %s "$@"\n'
         % shlex.quote(shutil.which("id")))
    return folder


def keys_sh():
    """{NAME: its words} of the lines NAME=VALUE of install/keys.sh"""
    found = {}
    with open(KEYS, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"([A-Z_]+)=(.*)", line)
            if m:
                found[m.group(1)] = " ".join(shlex.split(m.group(2), comments=True)).split()
    return found


def refusal(args):
    """the message of kit start for these words, as setup.sh says it"""
    try:
        plan.parse_start(args)
    except plan.PlanError as e:
        return str(e).replace("kit start: ", "setup.sh: ", 1)
    return None


def tree(top):
    """{the path under top: (its mode, its text or its link's target)} of each file and folder"""
    found = {}
    for folder, dirs, files in os.walk(top):
        for n in dirs + files:
            p = os.path.join(folder, n)
            st = os.lstat(p)
            if stat.S_ISLNK(st.st_mode):
                what = os.readlink(p)
            elif stat.S_ISREG(st.st_mode):
                with open(p, "rb") as f:
                    what = f.read()
            else:
                what = None
            found[os.path.relpath(p, top)] = (stat.S_IMODE(st.st_mode), what)
    return found


@unittest.skipUnless(HAVE, "bash or a tool of the set-up is missing")
class TheSetUp(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        t = os.path.realpath(self._t.name)
        self.home, self.root, self.tmp = (os.path.join(t, n) for n in ("home", "projects", "tmp"))
        for d in (self.home, self.root, self.tmp):
            os.mkdir(d)
        self.bin = tools(os.path.join(t, "bin"))
        self.log_file = os.path.join(t, "fake.log")
        for name, body in FAKES.items():
            fake(self.bin, name, 'echo "%s $*" >> "$FAKE_LOG"\n%s\n' % (name, body))

    def tearDown(self):
        self._t.cleanup()

    def run_(self, *args, env=None, script=SETUP):
        e = {"PATH": self.bin, "HOME": self.home, "TMPDIR": self.tmp, "TMUX_TMPDIR": self.tmp,
             "AGENT_KIT_ROOT": self.root, "FAKE_LOG": self.log_file, "NO_COLOR": "1", "LANG": "C.UTF-8",
             "GIT_CONFIG_NOSYSTEM": "1"}
        e.update(env or {})
        r = subprocess.run([BASH, script] + list(args), env=e, stdin=subprocess.DEVNULL, capture_output=True,
                           encoding="utf-8", timeout=60, start_new_session=True)
        self.assertNotIn("command not found", r.stdout + r.stderr)
        return r

    def calls(self):
        """the words each fake got, but git's (the version of the copy)"""
        try:
            with open(self.log_file, encoding="utf-8") as f:
                return [line.rstrip("\n") for line in f if not line.startswith("git ")]
        except FileNotFoundError:
            return []

    def project(self, name="demo"):
        os.makedirs(os.path.join(self.root, name, ".git"))

    def signed_in(self):
        return {"FAKE_GH": "0", "FAKE_CLAUDE": "0"}

    # the keys

    def test_the_lists_are_those_of_kit_start(self):
        k = keys_sh()
        for name in ("MODELS", "EFFORTS", "EDITOR", "PARKED", "ROLES_ADDONS"):
            self.assertEqual(tuple(k[name]), getattr(plan, name), name)
        self.assertEqual(k["WINDOW_MAX"], [str(config.WINDOW_MAX)])
        self.assertEqual(k["WORD"], ["^" + config.WORD.pattern + "$"])
        self.assertEqual(k["NAME"], ["^" + config.NAME.pattern + "$"])
        self.assertFalse(set(k["SETUP_PARKED"]) & set(plan.EDITOR + plan.PARKED + plan.ROLES_ADDONS))

    def test_a_wrong_key_is_refused_as_kit_start_refuses_it(self):
        cases = [[k, "demo"] for k in plan.EDITOR + plan.PARKED + plan.ROLES_ADDONS + ("--bogus", "-x", "--")] + [
            ["--window"], ["--compact"], ["--compact", "abc"], ["--window", "0", "demo"], ["--window", "abc"],
            ["--window", "123456789"],
            ["--window", "100000k"], ["--window", "012"], ["--window", "1.5k"], ["--window", "-5"],
            ["--plugin"], ["--plugin", "a b"], ["--plugin", ""], ["--agent"], ["--agent", "a b"], ["--eco"],
            ["--profile"], ["--profile", "cheap"],
            ["a", "b"], ["demo", "--opus", "other"]]
        for args in cases:
            want = refusal(args)
            self.assertIsNotNone(want, args)
            r = self.run_(*args)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (2, "", want + "\n"), args)
        self.assertEqual(self.calls(), [])
        self.assertEqual(os.listdir(self.home), [])

    def test_a_right_key_is_taken_as_kit_start_takes_it(self):
        # --help is read after the keys: each key is checked, then the usage is printed and nothing else runs
        cases = [["--opus", "--max"], ["--window", "132k"], ["--window", "132K"], ["--window", "99999999"],
                 ["--window", "99999k"], ["--window", "1"], ["--window", "default"], ["--compact", "200k"],
                 ["--plugin", "qa"],
                 ["--agent", "qa"], ["--new"],
                 ["--plugin", "-x"], ["--plugin", "a/b:c.d_e"], ["--dry-run"], ["--sonnet", "--haiku"]]
        for args in cases:
            self.assertIsNone(refusal(args + ["demo"]), args)
            r = self.run_(*args + ["--help"])
            self.assertEqual(r.returncode, 0, (args, r.stderr))
            self.assertTrue(r.stdout.startswith("usage: setup.sh"), args)
        self.assertEqual(self.calls(), [])

    def test_the_keys_of_the_set_up_only(self):
        k = keys_sh()
        for args, want in [(["--repo"], "--repo needs a repository: owner/name or a link"),
                           (["--repo", "--opus"], "--repo needs a repository: owner/name or a link"),
                           (["--repo", "https://github.com/o/n.git", "demo"], "one project only, not o/n and demo"),
                           (["--app-client-id"], "--app-client-id needs the Client ID of your GitHub App"),
                           (["--app-client-id", "a b"], "--app-client-id needs the Client ID of your GitHub App"),
                           (["--app-key"], "--app-key needs the file of the App's private key"),
                           (["status"], "status: no longer a command of setup.sh: kit list shows the sessions, kit "
                                        "kill ID stops one"),
                           (["list", "demo"], "list: no longer a command of setup.sh: kit list shows the sessions, "
                                              "kit kill ID stops one")] + \
                [([key], "%s: a set-up key of a parked part" % key) for key in k["SETUP_PARKED"]]:
            r = self.run_(*args)
            self.assertEqual((r.returncode, r.stderr), (2, "setup.sh: %s\n" % want), args)
        self.assertEqual(self.calls(), [])
        self.assertEqual(os.listdir(self.home), [])

    def test_help(self):
        for args in (["--help"], ["demo", "-h"]):
            r = self.run_(*args)
            self.assertEqual(r.returncode, 0)
            self.assertTrue(r.stdout.startswith("usage: setup.sh [PROJECT | owner/name] [KEYS]"))
        self.assertEqual(self.calls(), [])

    def test_root_is_refused(self):
        r = self.run_("demo", env={"FAKE_UID": "0"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("setup.sh: run this as your normal user, not as root", r.stderr)
        self.assertEqual(self.calls(), [])

    # the steps

    def test_a_dry_run_changes_nothing(self):
        self.project()
        before = (tree(self.home), tree(self.root))
        for args in (["demo", "--opus", "--dry-run"], ["https://github.com/someone/other.git", "--dry-run"]):
            r = self.run_(*args, env=self.signed_in())
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("dry run: nothing is changed", r.stdout)
            self.assertIn("the kit's copy not checked for an update (--dry-run)", r.stdout)
            self.assertIn("kit setup-files --dry-run: would", r.stdout)
            self.assertIn("kit start --dry-run: would", r.stderr)
        self.assertIn('would {"clone": "someone/other", "into": "%s"}' % os.path.join(self.root, "other"), r.stderr)
        self.assertEqual((tree(self.home), tree(self.root)), before)
        for word in ("sudo", "curl", "tmux new-session", "gh auth setup-git", "gh repo clone"):
            self.assertFalse([c for c in self.calls() if c.startswith(word)], word)

    def test_the_key_of_a_new_conversation_goes_to_kit_start(self):
        self.project()
        r = self.run_("demo", "--new", "--dry-run", env=self.signed_in())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r'"keys": \[\s*"--new"\s*\]')

    def test_a_first_set_up_then_the_start(self):
        self.project()
        r = self.run_("demo", "--haiku", "--no-update", env=self.signed_in())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = r.stdout
        self.assertLess(out.index("== Summary"), out.index("== Start"))
        self.assertIn("all done", out)
        self.assertRegex(out, r"started ([a-z0-9]{4}); open it: kit attach \1\n")
        self.assertTrue(os.access(os.path.join(self.home, ".local", "bin", "kit"), os.X_OK))
        with open(os.path.join(self.home, ".bashrc"), encoding="utf-8") as f:
            self.assertIn("agent-kit", f.read())
        conf = os.path.join(self.home, ".config", "agent-kit")
        with open(os.path.join(conf, "config.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["projects"]["demo"]["folder"], os.path.join(self.root, "demo"))
        [sid] = re.findall(r"started ([a-z0-9]{4});", out)
        with open(os.path.join(conf, "sessions", sid + ".json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["config"]["model"], "haiku")
        calls = self.calls()
        self.assertIn("gh auth setup-git", calls)
        self.assertEqual([c for c in calls if c.startswith("tmux new-session")][0].split()[:5],
                         ["tmux", "new-session", "-d", "-s", sid])
        self.assertFalse([c for c in calls if c.startswith(("sudo", "curl"))])
        # a second run changes no file of the kit
        r = self.run_("--no-start", "--no-update", env=self.signed_in())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # ... and says none; the word about linger is of the machine the test runs on, not of a file
        said = [line for line in r.stdout.splitlines() if "kit setup-files: " in line and "linger" not in line]
        self.assertEqual(said, [])
        self.assertIn("Set up; not started (--no-start)", r.stdout)

    def test_github_not_signed_in(self):
        r = self.run_("--no-start", "--no-update")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("not signed in to GitHub: sign in with gh auth login in a terminal", r.stdout)
        self.assertNotIn("curl", " ".join(self.calls()))
        r = self.run_("--no-start", "--no-update", "--app-client-id", "Iv1.abc")
        self.assertIn("no answer from GitHub (no network?)", r.stdout)
        with open(os.path.join(self.home, ".config", "agent-kit", "app-client-id"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "Iv1.abc\n")
        self.assertIn("the App's Client ID Iv1.abc written to", self.kit_log()[-1]["change"])
        r = self.run_("--no-start", "--no-update")   # the kept ID
        self.assertIn("no answer from GitHub (no network?)", r.stdout)
        # kit update's set-up waits for no code: the sign-in is named as missing, and GitHub is not asked
        open(self.log_file, "w", encoding="utf-8").close()
        r = self.run_("--no-start", "--no-update", env={"AGENT_KIT_NO_ASK": "1"})
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("not signed in to GitHub: sign in with gh auth login in a terminal", r.stdout)
        self.assertNotIn("curl", " ".join(self.calls()))
        self.assertIn("Sign in to Claude: run claude auth login", r.stdout)
        self.assertIn("not done:", r.stdout)
        self.assertIn("setup.sh: GitHub is not signed in", r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.home, ".local", "bin", "kit")))
        self.assertNotIn("gh auth setup-git", self.calls())

    def kit_log(self):
        with open(os.path.join(self.home, ".config", "agent-kit", "kit.log"), encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def test_the_old_plugins(self):
        old = {"FAKE_PLUGINS": '[{"id": "core@agent-kit", "scope": "user"}, {"id": "x@other", "scope": "user"}]',
               "FAKE_MARKETS": '[{"name": "agent-kit"}, {"name": "other"}]', "FAKE_GH": "0"}
        r = self.run_("--no-start", "--no-update", env=old)
        self.assertIn("the old kit's plugins are in Claude Code: core@agent-kit user", r.stdout)
        self.assertIn("--remove-old-plugins", r.stdout)
        self.assertFalse([c for c in self.calls() if "uninstall" in c or "marketplace remove" in c])
        r = self.run_("--no-start", "--no-update", "--dry-run", "--remove-old-plugins", env=old)
        self.assertIn("the old kit's plugins not removed (--dry-run)", r.stdout)
        self.assertFalse([c for c in self.calls() if "uninstall" in c or "marketplace remove" in c])
        r = self.run_("--no-start", "--no-update", "--remove-old-plugins", env=old)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("claude plugin uninstall core@agent-kit --scope user", self.calls())
        self.assertIn("claude plugin marketplace remove agent-kit", self.calls())
        self.assertFalse([c for c in self.calls() if "x@other" in c])
        changes = [x["change"] for x in self.kit_log() if x.get("command") == "setup"]
        self.assertIn("the old plugin core@agent-kit (user) removed from Claude Code", changes)
        self.assertIn("the old marketplace agent-kit removed from Claude Code", changes)
        r = self.run_("--no-start", "--no-update", "--remove-old-plugins", env={"FAKE_GH": "0"})   # nothing old
        self.assertNotIn("old", r.stdout)

    def test_the_apps_key(self):
        r = self.run_("--no-start", "--no-update", "--app-key", os.path.join(self.home, "none.pem"))
        self.assertIn("--app-key: no file", r.stdout)
        key = os.path.join(self.home, "key.pem")
        with open(key, "w", encoding="utf-8") as f:
            f.write("not a key\n")
        r = self.run_("--no-start", "--no-update", "--app-key", key)   # no Client ID: the key is not taken
        self.assertIn("the App's key not taken: gh-app.sh: ", r.stdout)
        r = self.run_("--no-start", "--no-update", "--dry-run", "--app-key", key, "--app-client-id", "Iv1.abc")
        self.assertIn("the App's key not copied (--dry-run)", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".config", "agent-kit", "app-key.pem")))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".config", "agent-kit", "app-client-id")))

    def test_no_gh(self):
        os.remove(os.path.join(self.bin, "gh"))
        r = self.run_("--no-start", "--no-update", env={"FAKE_CLAUDE": "0"})
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("gh is not installed, so GitHub is skipped", r.stdout)
        self.assertTrue(os.path.exists(os.path.join(self.home, ".local", "bin", "kit")))

    def test_no_project_named(self):
        self.project()
        r = self.run_("--no-update", env=self.signed_in())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Set up; no project named", r.stdout)
        self.assertFalse([c for c in self.calls() if c.startswith("tmux new-session")])

    def test_a_missing_package(self):
        os.remove(os.path.join(self.bin, "tmux"))
        r = self.run_("--dry-run", env=self.signed_in())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("missing: tmux; would be installed (--dry-run)", r.stdout)
        self.assertEqual(os.listdir(self.home), [])
        # with no password-free sudo, no apt-get and no terminal: the root command is said, and the set-up stops
        open(self.log_file, "w").close()
        r = self.run_("demo", "--no-update", env=self.signed_in())
        self.assertEqual(r.returncode, 1)
        self.assertIn("Install them as root on the machine (for example from the provider's console): apt-get "
                      "install tmux", r.stderr)
        self.assertIn("setup.sh: the set-up cannot go on without: tmux.", r.stderr)
        self.assertNotIn("== GitHub", r.stdout)
        self.assertEqual([c for c in self.calls() if not c.startswith("gh ")], ["sudo -n true"])

    def test_no_claude_code(self):
        os.remove(os.path.join(self.bin, "claude"))
        r = self.run_("--dry-run", env=self.signed_in())
        self.assertIn("not installed; would be installed (--dry-run)", r.stdout)
        r = self.run_("demo", "--no-update", env=self.signed_in())
        self.assertEqual(r.returncode, 1)
        self.assertIn("setup.sh: the set-up cannot go on without Claude Code", r.stderr)
        self.assertNotIn("== The kit's files", r.stdout)


GIT = shutil.which("git")


@unittest.skipUnless(HAVE and GIT, "bash, git or a tool of the set-up is missing")
class TheUpdate(unittest.TestCase):
    """repo_update on a repository of the test with the tags v1.0.0 and v1.1.0, and the run of the new release. The
    PATH has the system's tools and git only: a set-up that did not move on would stop at the packages"""

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        t = os.path.realpath(self._t.name)
        self.home, self.repo = os.path.join(t, "home"), os.path.join(t, "kit")
        os.mkdir(self.home)
        self.env = {"PATH": tools(os.path.join(t, "bin"), "git"), "HOME": self.home, "TMPDIR": t,
                    "GIT_CONFIG_NOSYSTEM": "1", "NO_COLOR": "1", "LANG": "C.UTF-8"}
        shutil.copytree(os.path.join(ROOT, "install"), os.path.join(self.repo, "install"))
        self.git("init", "-q", "-b", "main")
        self.commit("v1.0.0")
        with open(os.path.join(self.repo, "install", "setup.sh"), "w", encoding="utf-8") as f:
            f.write('echo "release 1.1.0 ${AGENT_KIT_UPDATED:-} $*"\n')
        self.commit("v1.1.0")
        self.git("checkout", "-q", "--detach", "v1.0.0")

    def tearDown(self):
        self._t.cleanup()

    def git(self, *args):
        r = subprocess.run([GIT, "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
                           + list(args), env=self.env, capture_output=True, encoding="utf-8")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def commit(self, tag):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", tag)
        self.git("tag", tag)

    def update(self, repo=None):
        r = subprocess.run([BASH, "-c", 'source "$1"; REPO_ROOT=$2; repo_update; echo "updated=$REPO_UPDATED"', "-",
                            os.path.join(ROOT, "install", "common.sh"), repo or self.repo], env=self.env,
                           stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", timeout=60,
                           start_new_session=True)
        return r.stdout

    def test_moved_to_the_latest_release(self):
        out = self.update()
        self.assertIn("agent-kit updated: v1.0.0 -> v1.1.0", out)
        self.assertIn("updated=1", out)
        self.assertEqual(self.git("describe", "--tags"), "v1.1.0")
        self.assertIn("updated=0", self.update())     # at the latest already

    def test_a_branch_and_local_changes_are_kept(self):
        self.git("checkout", "-q", "-b", "work")
        out = self.update()
        self.assertIn("repository not updated (on the branch work)", out)
        self.assertEqual(self.git("symbolic-ref", "--short", "HEAD"), "work")
        self.git("checkout", "-q", "--detach", "v1.0.0")
        with open(os.path.join(self.repo, "install", "keys.sh"), "a", encoding="utf-8") as f:
            f.write("# a change\n")
        out = self.update()
        self.assertIn("repository not updated (local changes)", out)
        self.assertIn("updated=0", out)
        self.assertEqual(self.git("describe", "--tags", "--dirty"), "v1.0.0-dirty")

    def test_a_copy_ahead_of_the_release_is_not_moved_back(self):
        self.git("checkout", "-q", "--detach", "v1.1.0")
        with open(os.path.join(self.repo, "install", "keys.sh"), "a", encoding="utf-8") as f:
            f.write("# not released yet\n")
        self.git("commit", "-q", "-am", "after v1.1.0")
        head = self.git("rev-parse", "HEAD")
        out = self.update()
        self.assertIn("repository not updated (ahead of the release v1.1.0)", out)
        self.assertIn("updated=0", out)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)

    def test_the_new_release_runs_after_the_update(self):
        # the set-up of v1.0.0 moves its copy to v1.1.0, then runs that release by the same path with the
        # same keys
        r = subprocess.run([BASH, os.path.join(self.repo, "install", "setup.sh"), "demo", "--haiku"], env=self.env,
                           stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", timeout=60,
                           start_new_session=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("agent-kit updated: v1.0.0 -> v1.1.0", r.stdout)
        self.assertTrue(r.stdout.endswith("release 1.1.0 1 demo --haiku\n"), r.stdout)
        self.assertEqual(os.listdir(self.home), [])

    def clone(self):
        """a copy of the repository on its branch main, with the repository as its origin"""
        self.git("checkout", "-q", "main")
        copy = os.path.join(os.path.dirname(self.repo), "copy")
        self.git("clone", "-q", self.repo, copy)
        return copy

    def more(self):
        """one more commit on the origin's main; its name"""
        with open(os.path.join(self.repo, "install", "keys.sh"), "a", encoding="utf-8") as f:
            f.write("# after the release\n")
        self.git("commit", "-q", "-am", "after v1.1.0")
        return self.git("rev-parse", "HEAD")

    def kit_update(self, repo):
        return subprocess.run([BASH, os.path.join(repo, "install", "update.sh")], env=self.env,
                              stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", timeout=60,
                              start_new_session=True)

    def test_a_copy_on_main_follows_its_origin(self):
        copy = self.clone()
        self.assertIn("updated=0", self.update(copy))       # nothing new yet
        head = self.more()
        out = self.update(copy)
        self.assertIn("agent-kit updated: v1.1.0 -> v1.1.0-1-g", out)
        self.assertIn("updated=1", out)
        self.assertEqual(self.git("-C", copy, "rev-parse", "HEAD"), head)
        self.assertEqual(self.git("-C", copy, "symbolic-ref", "--short", "HEAD"), "main")

    def test_a_copy_on_main_with_its_own_commits_is_kept(self):
        copy = self.clone()
        self.more()
        self.git("-C", copy, "commit", "-q", "--allow-empty", "-m", "mine")
        head = self.git("-C", copy, "rev-parse", "HEAD")
        out = self.update(copy)
        self.assertIn("repository not updated (main has commits that its origin has not)", out)
        self.assertEqual(self.git("-C", copy, "rev-parse", "HEAD"), head)

    def test_kit_update_moves_the_copy_and_sets_up_with_no_start(self):
        r = self.kit_update(self.repo)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lines = r.stdout.splitlines()
        self.assertIn("release 1.1.0 1 --no-start", lines)
        self.assertEqual(lines[-1], "kit update: moved from v1.0.0 to v1.1.0")
        r = self.kit_update(self.repo)
        self.assertEqual((r.returncode, r.stdout.splitlines()[-1]), (0, "kit update: nothing new; at v1.1.0"))

    def test_kit_update_says_nothing_new_and_a_repository_that_does_not_answer(self):
        copy = self.clone()
        r = self.kit_update(copy)
        self.assertEqual((r.returncode, r.stdout.splitlines()[-1]), (0, "kit update: nothing new; at v1.1.0"))
        self.assertNotIn("release 1.1.0", r.stdout)          # the set-up did not run
        # the origin gone after a fetch that left its main ahead: the copy is not moved to what that fetch left
        self.more()
        self.git("-C", copy, "fetch", "-q")
        head = self.git("-C", copy, "rev-parse", "HEAD")
        self.git("-C", copy, "remote", "set-url", "origin", os.path.join(copy, "gone"))
        r = self.kit_update(copy)
        self.assertEqual((r.returncode, r.stdout.splitlines()[-1]),
                         (1, "kit update: not updated: the kit's repository did not answer; at v1.1.0"))
        self.assertEqual(self.git("-C", copy, "rev-parse", "HEAD"), head)

    def test_a_copy_on_main_with_no_main_of_its_origin_stays_on_its_branch(self):
        copy = self.clone()
        self.git("-C", copy, "reset", "-q", "--hard", "v1.0.0")     # behind the latest release, on main
        self.git("-C", copy, "remote", "remove", "origin")
        out = self.update(copy)
        self.assertIn("repository not updated (on main, and its origin has no main)", out)
        self.assertIn("updated=0", out)
        self.assertEqual(self.git("-C", copy, "symbolic-ref", "--short", "HEAD"), "main")
        self.assertEqual(self.git("-C", copy, "describe", "--tags"), "v1.0.0")

    def test_kit_update_asks_nothing_at_a_terminal(self):
        """the set-up is told to ask nothing, and with that word no question sees the terminal, a real one too"""
        with open(os.path.join(self.repo, "install", "setup.sh"), "w", encoding="utf-8") as f:
            f.write('echo "no ask: ${AGENT_KIT_NO_ASK:-}"\n')
        self.git("commit", "-q", "-am", "v1.2.0")
        self.git("tag", "v1.2.0")
        self.git("checkout", "-q", "--detach", "v1.0.0")
        self.assertIn("no ask: 1", self.kit_update(self.repo).stdout.splitlines())
        import fcntl, pty, termios
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)

        def own_terminal():
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
        for word, seen in (("", "tty"), ("1", "none")):
            r = subprocess.run([BASH, "-c", 'source "$1"; has_tty && echo tty || echo none', "-",
                                os.path.join(ROOT, "install", "common.sh")], env={**self.env, "AGENT_KIT_NO_ASK": word},
                               stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", timeout=60,
                               preexec_fn=own_terminal, pass_fds=(slave,))
            self.assertEqual(r.stdout.strip(), seen, r.stderr)

    def test_kit_update_names_why_a_copy_was_kept(self):
        copy = self.clone()
        self.more()
        self.git("-C", copy, "commit", "-q", "--allow-empty", "-m", "mine")
        r = self.kit_update(copy)
        self.assertEqual((r.returncode, r.stdout.splitlines()[-1]),
                         (1, "kit update: not updated: main has commits that its origin has not; at v1.1.0-1-g"
                          + self.git("-C", copy, "rev-parse", "--short", "HEAD")))
        self.git("-C", copy, "checkout", "-q", "-b", "work")
        r = self.kit_update(copy)
        self.assertIn("kit update: not updated: on the branch work; at ", r.stdout.splitlines()[-1])
        self.assertEqual(r.returncode, 1)

    def test_kit_update_has_its_own_exit_code_when_the_set_up_left_work(self):
        with open(os.path.join(self.repo, "install", "setup.sh"), "w", encoding="utf-8") as f:
            f.write("exit 3\n")
        self.git("commit", "-q", "-am", "v1.2.0")
        self.git("tag", "v1.2.0")
        self.git("checkout", "-q", "--detach", "v1.0.0")
        r = self.kit_update(self.repo)
        self.assertEqual((r.returncode, r.stdout.splitlines()[-1]),
                         (3, "kit update: moved from v1.0.0 to v1.2.0, but the set-up left work not done (exit 3)"))


if __name__ == "__main__":
    unittest.main()
