"""the designer: the program shot against a fake browser, the folder of the design, the agent's own file"""
import json, os, re, stat, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOT = os.path.join(ROOT, "content", "plugins", "design", "bin", "shot")
# a browser that keeps its arguments and writes the picture it was asked for, unless FAKE says otherwise
FAKE = '''#!/bin/sh
printf '%s\\n' "$@" >> "$FAKE_LOG"
[ "$FAKE" = fail ] && { echo "no display" >&2; exit 7; }
[ "$FAKE" = silent ] && exit 0
for a in "$@"; do case "$a" in --screenshot=*) printf PNG > "${a#--screenshot=}";; esac; done
'''


class Shot(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.dir, True)
        self.bin = os.path.join(self.dir, "bin")
        os.mkdir(self.bin)
        self.log = os.path.join(self.dir, "log")
        self.page = os.path.join(self.dir, "my page.html")
        with open(self.page, "w") as f:
            f.write("<p>x</p>")
        self.out = os.path.join(self.dir, "out")
        self.browser("chromium")

    def browser(self, name):
        path = os.path.join(self.bin, name)
        with open(path, "w") as f:
            f.write(FAKE)
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR)

    def shot(self, *args, **env):
        e = dict({"PATH": self.bin + ":/usr/bin:/bin", "TMPDIR": self.dir, "FAKE_LOG": self.log}, **env)
        r = subprocess.run([sys.executable, "-I", SHOT] + list(args), env=e, capture_output=True, text=True)
        calls = []
        if os.path.exists(self.log):
            with open(self.log) as f:
                calls = f.read().split("--headless=new\n")[1:]
        return r.returncode, r.stdout.split("\n")[:-1], r.stderr, [c.split("\n")[:-1] for c in calls]

    def test_a_file_gets_a_picture_for_a_phone_and_for_a_desk(self):
        code, out, err, calls = self.shot(self.page, "--out", self.out)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(out, [os.path.join(self.out, "my-page-390.png"), os.path.join(self.out, "my-page-1280.png")])
        self.assertTrue(all(os.path.isfile(p) for p in out))
        self.assertEqual([c[3] for c in calls], ["--window-size=390,1600", "--window-size=1280,1600"])
        self.assertEqual(calls[0][-1], "file://" + self.page)
        for c in calls:                       # a profile of its own, removed after
            profile = [a for a in c if a.startswith("--user-data-dir=")][0].split("=", 1)[1]
            self.assertFalse(os.path.exists(profile))
            self.assertNotIn("--force-dark-mode", c)
            self.assertNotIn("--no-sandbox", c)

    def test_the_widths_the_height_the_dark_theme_and_the_name(self):
        code, out, _, calls = self.shot("https://example.test/a/b?x=1", "--width", "800", "--width", "800",
                                        "--height", "900", "--dark", "--name", "home", "--out", self.out)
        self.assertEqual((code, out), (0, [os.path.join(self.out, "home-800-dark.png")]))
        self.assertEqual(len(calls), 1)
        self.assertIn("--window-size=800,900", calls[0])
        self.assertIn("--force-dark-mode", calls[0])
        self.assertEqual(calls[0][-1], "https://example.test/a/b?x=1")

    def test_with_no_folder_the_pictures_go_to_shots_in_the_temporary_folder(self):
        code, out, _, _ = self.shot("http://example.test/", "--width", "500")
        self.assertEqual((code, out), (0, [os.path.join(self.dir, "shots", "example.test-500.png")]))

    def test_the_browser_named_in_the_variable_is_the_one_run(self):
        self.browser("other")
        os.remove(os.path.join(self.bin, "chromium"))
        self.assertEqual(self.shot(self.page, "--out", self.out, AGENT_KIT_BROWSER="other")[0], 0)
        code, out, err, _ = self.shot(self.page, "--out", self.out, AGENT_KIT_BROWSER="none-such")
        self.assertEqual((code, out), (2, []))
        self.assertIn("AGENT_KIT_BROWSER names none-such", err)
        code, _, err, _ = self.shot(self.page, "--out", self.out)
        self.assertEqual(code, 2)
        self.assertIn("install Chromium", err)

    def test_a_browser_that_fails_or_writes_nothing_is_an_error_and_no_old_picture_is_left(self):
        os.mkdir(self.out)
        old = os.path.join(self.out, "my-page-390.png")
        with open(old, "w") as f:
            f.write("old")
        code, out, err, _ = self.shot(self.page, "--out", self.out, FAKE="silent")
        self.assertEqual((code, out), (1, []))
        self.assertIn("wrote no picture", err)
        self.assertFalse(os.path.exists(old))
        code, _, err, calls = self.shot(self.page, "--out", self.out, FAKE="fail")
        self.assertEqual(code, 1)
        self.assertIn("exit code 7: no display", err)
        self.assertEqual(len(calls), 2)       # it stops at the first width that failed (one call per run)

    def test_mistakes_in_the_call(self):
        for args, said in (([], "the page is missing"), ([self.page, "--width", "0"], "--width 0"),
                           ([self.page, "--width", "x"], "--width x"), ([self.page, "--height", "5000"], "--height"),
                           ([self.page, "--name", "a/b"], "--name a/b"), ([self.page, "--out"], "needs a value"),
                           ([self.page, "--light"], "unknown option --light"), (["a.html"], "neither"),
                           ([self.page, self.page], "one page only"), (["ftp://x/y"], "neither an address")):
            code, out, err, calls = self.shot(*args)
            self.assertEqual((code, out, calls), (2, [], []), args)
            self.assertIn(said, err, args)


# the kit's own designs lie in design/, which a published copy of the kit may leave out
HAS_DESIGNS = os.path.isfile(os.path.join(ROOT, "design", "DESIGN.md"))


@unittest.skipUnless(HAS_DESIGNS, "no design/ folder in this copy")
class TheKitsDesigns(unittest.TestCase):
    def test_each_design_named_in_the_rules_is_in_the_folder(self):
        with open(os.path.join(ROOT, "design", "DESIGN.md"), encoding="utf-8") as f:
            cells = re.findall(r"^\| (`[^|]+\.html`) \|", f.read(), re.MULTILINE)   # a row names one or more
        named = [n for c in cells for n in re.findall(r"`([^`]+\.html)`", c)]
        self.assertTrue(named)
        self.assertEqual(len(named), len(set(named)))
        for name in named:
            with open(os.path.join(ROOT, "design", name), encoding="utf-8") as f:
                self.assertIn("<x-dc>", f.read(), name)
        on_disk = sorted(n for n in os.listdir(os.path.join(ROOT, "design")) if n.endswith(".html"))
        self.assertEqual(on_disk, sorted(named))    # a design in the folder is named in the rules


class TheFolderOfTheDesign(unittest.TestCase):
    def test_the_field_is_a_folder_inside_the_project(self):
        from kit import config
        check = config.SESSION["design_dir"][0]
        self.assertEqual(config.defaults()["session"]["design_dir"], "design")
        for good in ("design", "docs/design", "ui_kit-2"):
            self.assertTrue(check(good), good)
        for bad in ("", "/design", "design/", "../design", "a/../b", ".design", "a b", None, 1, ["design"]):
            self.assertFalse(check(bad), bad)

    def test_the_agent_and_its_role_name_the_folder_the_program_and_the_artifacts(self):
        with open(os.path.join(ROOT, "content", "agents", "design.json")) as f:
            d = json.load(f)
        self.assertEqual((d["role"], d["plugins"]), ("design.md", ["design"]))
        self.assertFalse({"model", "effort"} & set(d), "no profile of the kit sets the model: it is chosen by hand")
        self.assertFalse({"artifact-design", "dataviz"} & set(d["bundled_skills_off"]))
        with open(os.path.join(ROOT, "content", "agents", "design.md")) as f:
            role = f.read()
        for word in ("$AGENT_KIT_DESIGN_DIR", "`design` when it is", "DESIGN.md", "`shot PAGE`", "Artifact",
                     "not yours to change", "open one issue in the project's repository for each page", "`gh issue create`", "`design:`"):
            self.assertIn(word, role)
        with open(os.path.join(ROOT, "content", "agents", "dev.md")) as f:
            dev = f.read()
        for word in ("titled `design:`", "close the issue"):     # the developer's side of the designer's issues
            self.assertIn(word, dev)
        self.assertTrue(os.access(SHOT, os.X_OK))


if __name__ == "__main__":
    unittest.main()
