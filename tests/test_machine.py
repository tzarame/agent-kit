"""test_machine.py - kit setup-files (kit/machine.py), as set-up and config.md say: the command ~/.local/bin/kit, the
PATH line of ~/.bashrc, the first config, the marks of Claude Code's first run and the user's fields in Claude Code's
files, the other keys kept, a link kept, a file that is not JSON left as it is, the log and the dry run. Each test has
a home folder of its own and a fake claude.
    python3 -m unittest discover -s tests"""
import json, os, stat, subprocess, unittest

from kit import config, machine, plan
from kit.io import ROOT
from test_sessions import FakeIo, Home, a_later_release


class Io(FakeIo):
    def __init__(self, home):
        FakeIo.__init__(self, home)
        self.version = "2.1.327"
        self.lingers = True

    def linger(self):
        return "ada", self.lingers

    def claude_version(self):
        return self.version


class TheSetUpFiles(Home):
    def setUp(self):
        Home.setUp(self)
        self.io = Io(self.home)

    def run_(self, *args):
        return machine.setup_files(self.io, list(args))

    def json(self, path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def test_a_first_set_up(self):
        self.assertEqual(self.run_(), 0)
        with open(self.io.command, encoding="utf-8") as f:
            self.assertEqual(f.read(), machine.command_text(self.io.main))
        self.assertEqual(stat.S_IMODE(os.stat(self.io.command).st_mode), 0o755)
        self.assertEqual(self.json(self.io.config), config.defaults())
        self.assertEqual(self.json(self.io.claude_state),
                         {"hasCompletedOnboarding": True, "lastOnboardingVersion": "2.1.327", "theme": "dark"})
        self.assertEqual(stat.S_IMODE(os.stat(self.io.claude_state).st_mode), 0o600)
        self.assertEqual(self.json(self.io.claude_settings), {"disableClaudeAiConnectors": True})
        [record] = self.log()
        self.assertEqual(record["command"], "setup-files")
        kinds = [next(iter(c)) for c in record["changes"]]
        self.assertEqual(kinds, ["write", "append", "write", "link", "copy", "set", "set"])
        self.assertEqual(record["changes"][0]["content"], machine.command_text(self.io.main))
        with open(self.io.bashrc, encoding="utf-8") as f:
            self.assertEqual(f.read(), machine.BASHRC)
        umask = os.umask(0o22)
        os.umask(umask)
        self.assertEqual(stat.S_IMODE(os.stat(self.io.bashrc).st_mode), 0o644 & ~umask)
        self.assertEqual(self.io.out.getvalue().count("kit setup-files: "), 7)

    def test_the_path_line_is_added_once_at_the_end(self):
        self.put(self.io.bashrc, "alias ll='ls -l'\n")
        self.run_()
        self.run_()
        with open(self.io.bashrc, encoding="utf-8") as f:
            self.assertEqual(f.read(), "alias ll='ls -l'\n" + machine.BASHRC)
        r = subprocess.run(["bash", "-c", 'source "$1"; echo "$PATH"', "-", self.io.bashrc], capture_output=True,
                           text=True, env={"PATH": "/usr/bin:/bin", "HOME": self.home})
        self.assertEqual(r.stdout.strip(), self.home + "/.local/bin:/usr/bin:/bin")

    def test_a_link_stays_a_link(self):
        target = self.put(os.path.join(self.home, "dotfiles", "settings.json"), json.dumps({"model": "opus"}))
        os.makedirs(os.path.dirname(self.io.claude_settings))
        os.symlink(target, self.io.claude_settings)
        self.assertEqual(self.run_(), 0)
        self.assertTrue(os.path.islink(self.io.claude_settings))
        self.assertEqual(self.json(target), {"model": "opus", "disableClaudeAiConnectors": True})

    def test_the_command_runs_the_kit(self):
        self.run_()
        r = subprocess.run([self.io.command, "help"], capture_output=True, text=True,
                           env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": self.home})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(r.stdout.startswith("usage: kit COMMAND"))

    def test_a_second_set_up_changes_nothing(self):
        self.run_()
        self.assertEqual(self.run_(), 0)
        self.assertEqual(len(self.log()), 1)

    def test_the_other_keys_and_the_mode_are_kept(self):
        account = {"oauthAccount": {"emailAddress": "someone@example.com"}, "theme": "light", "numStartups": 7}
        self.put(self.io.claude_state, json.dumps(account))
        os.chmod(self.io.claude_state, 0o640)
        self.put(self.io.claude_settings, json.dumps({"model": "opus", "env": {"GH_TOKEN": "t0ken-value"}}))
        self.assertEqual(self.run_(), 0)
        self.assertEqual(self.json(self.io.claude_state), dict(account, hasCompletedOnboarding=True,
                                                                 lastOnboardingVersion="2.1.327"))
        self.assertEqual(stat.S_IMODE(os.stat(self.io.claude_state).st_mode), 0o640)
        self.assertEqual(self.json(self.io.claude_settings),
                         {"model": "opus", "env": {"GH_TOKEN": "t0ken-value"}, "disableClaudeAiConnectors": True})
        with open(self.io.log_path, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("someone@example.com", text)    # the account's keys are not logged
        self.assertNotIn("t0ken-value", text)            # a token only as its fingerprint
        state, settings = [c for c in self.log()[0]["changes"] if "set" in c]
        self.assertEqual(state, {"set": {"hasCompletedOnboarding": True, "lastOnboardingVersion": "2.1.327"},
                                 "in": self.io.claude_state, "content": "the other keys kept"})
        self.assertEqual(settings["content"]["env"]["GH_TOKEN"], plan.fingerprint("t0ken-value"))

    def test_an_account_past_its_first_run_is_left(self):
        account = {"oauthAccount": {"emailAddress": "someone@example.com"},     # no theme: the default one stays
                   "hasCompletedOnboarding": True, "lastOnboardingVersion": "2.1.100"}
        self.put(self.io.claude_state, json.dumps(account))
        before = os.stat(self.io.claude_state).st_mtime_ns
        self.assertEqual(self.run_(), 0)
        self.assertEqual(self.json(self.io.claude_state), account)
        self.assertEqual(os.stat(self.io.claude_state).st_mtime_ns, before)
        self.assertFalse([c for c in self.log()[0]["changes"] if c.get("in") == self.io.claude_state])

    def test_a_file_that_is_not_json_is_left(self):
        for text in ("{not json", "[1, 2]"):
            self.put(self.io.claude_settings, text)
            self.io.err.truncate(0)
            self.assertEqual(self.run_(), 0)
            with open(self.io.claude_settings, encoding="utf-8") as f:
                self.assertEqual(f.read(), text)
            self.assertIn('left as it is. Set by hand: "disableClaudeAiConnectors": true', self.io.err.getvalue())

    def test_the_user_wants_the_connectors(self):
        self.put(self.io.config, json.dumps({"user": {"claude_ai_connectors": True}}))
        self.assertEqual(self.run_(), 0)
        self.assertFalse(os.path.lexists(self.io.claude_settings))
        self.assertEqual(self.json(self.io.config), {"version": 3, "user": {"claude_ai_connectors": True}})

    def test_the_copy_of_an_older_release_is_migrated(self):
        self.put(self.io.config, json.dumps({"session": {"model": "haiku"}}))
        with a_later_release():
            self.assertEqual(self.run_("--dry-run"), 0)
            self.assertIn('would {"migrate": "%s"' % self.io.config, self.io.err.getvalue())
            self.assertEqual(self.json(self.io.config), {"session": {"model": "haiku"}})
            self.assertEqual(self.run_(), 0)
            self.assertEqual(self.run_(), 0)
        self.assertEqual(self.json(self.io.config), {"version": 2, "session": {"model": "sonnet"}})
        self.assertEqual(self.json(self.io.config + ".v1"), {"session": {"model": "haiku"}})
        changes = [c for r in self.log() for c in r["changes"] if "migrate" in c]
        self.assertEqual(changes, [{"migrate": self.io.config, "keep": self.io.config + ".v1",
                                    "changes": [{"version": 1, "to": 2},
                                                {"set": "session.model", "from": "haiku", "to": "sonnet"}]}])

    def test_the_unit_of_the_autostart(self):
        self.assertEqual(self.run_(), 0)
        with open(self.io.unit, encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(text, machine.unit_text(self.io.command))
        self.assertIn('ExecStart="%s" autostart\n' % self.io.command, text)
        self.assertIn("WantedBy=default.target\n", text)
        self.assertNotIn("User=", text)
        self.assertEqual(stat.S_IMODE(os.stat(self.io.unit).st_mode), 0o644)
        self.assertEqual(os.readlink(self.io.unit_link), "../kit-autostart.service")
        self.assertTrue(os.path.samefile(self.io.unit_link, self.io.unit))
        self.assertTrue(self.io.unit.startswith(os.path.join(self.home, ".local", "share", "systemd", "user")))
        self.assertNotIn("linger", self.io.err.getvalue())

    def test_the_unit_is_one_systemd_takes(self):
        if not any(os.access(os.path.join(d, "systemd-analyze"), os.X_OK) for d in ("/usr/bin", "/bin")):
            self.skipTest("no systemd-analyze")
        self.run_()
        os.chmod(self.io.command, 0o755)
        folder = os.path.dirname(self.io.unit)
        runtime = os.path.join(self.home, "run")
        os.mkdir(runtime, 0o700)
        v = subprocess.run(["systemd-analyze", "--user", "verify", "--man=no", self.io.unit], capture_output=True,
                           encoding="utf-8", timeout=60,
                           env={"PATH": "/usr/bin:/bin", "SYSTEMD_LOG_LEVEL": "notice", "HOME": self.home,
                                "SYSTEMD_UNIT_PATH": folder + ":", "XDG_RUNTIME_DIR": runtime})
        self.assertEqual(v.returncode, 0, v.stdout + v.stderr)
        self.assertNotIn("kit-autostart", v.stderr)

    def test_a_link_of_the_owner_is_left(self):
        os.makedirs(os.path.dirname(self.io.unit_link))
        os.symlink("/dev/null", self.io.unit_link)
        self.assertEqual(self.run_(), 0)
        self.assertEqual(os.readlink(self.io.unit_link), "/dev/null")
        self.assertNotIn("link", [next(iter(c)) for c in self.log()[0]["changes"]])

    def test_no_linger_and_the_old_unit_are_said(self):
        self.io.lingers = False
        old = os.path.join(self.home, *machine.OLD_UNIT)
        os.makedirs(os.path.dirname(old))
        os.symlink("../agent-kit-autostart.service", old)
        self.assertEqual(self.run_(), 0)
        self.assertIn("As root: loginctl enable-linger ada\n", self.io.err.getvalue())
        self.assertIn("systemctl --user disable agent-kit-autostart\n", self.io.err.getvalue())
        self.assertTrue(os.path.islink(old))

    def test_no_claude(self):
        self.io.version = None
        self.assertEqual(self.run_(), 0)
        self.assertFalse(os.path.lexists(self.io.claude_state))
        self.assertIn("Claude Code does not answer", self.io.err.getvalue())

    def test_a_dry_run_changes_nothing(self):
        self.assertEqual(self.run_("--dry-run"), 0)
        self.assertEqual(os.listdir(self.home), [])
        err = self.io.err.getvalue()
        for what in ('"write"', '"append"', '"copy"', self.io.claude_state, self.io.claude_settings):
            self.assertIn(what, err)

    def test_a_wrong_config_or_key(self):
        self.put(self.io.config, json.dumps({"user": {"claude_ai_connectors": "no"}}))
        self.assertEqual(self.run_(), 2)
        self.assertFalse(os.path.lexists(self.io.command))
        self.assertIn("error", self.log()[0])
        self.assertEqual(self.run_("--force"), 2)
        self.assertIn("kit setup-files: unknown option --force", self.io.err.getvalue())

    def test_the_command_quotes_the_path(self):
        self.assertIn("exec python3 -I '/a b/kit/__main__.py' \"$@\"", machine.command_text("/a b/kit/__main__.py"))
        main = os.path.join(ROOT, "kit", "__main__.py")
        self.assertTrue(machine.command_text(main).startswith("#!/usr/bin/env bash\n"))


if __name__ == "__main__":
    unittest.main()
