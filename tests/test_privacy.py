"""test_privacy.py - .github/privacy-scan.py on diffs of the test: a finding with its place, a token masked, the
allowlist with its reasons, the machine's own list of words, and a list that cannot be read.
    python3 -m unittest discover -s tests"""
import os, subprocess, sys, tempfile, unittest

from kit.io import ROOT

SCAN = os.path.join(ROOT, ".github", "privacy-scan.py")
DIFF = """--- a/notes.md
+++ b/notes.md
@@ -3,0 +4,%d @@
%s"""


@unittest.skipUnless(os.path.isfile(SCAN), "the version to install has no scanner: it is a tool of the development")
class ThePrivacyScan(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.t = self._t.name

    def tearDown(self):
        self._t.cleanup()

    def file(self, name, text):
        path = os.path.join(self.t, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def scan(self, lines, allow="", deny=None):
        diff = self.file("d.diff", DIFF % (len(lines), "".join("+%s\n" % x for x in lines)))
        args = ["--diff", diff, "--allow", self.file("allow.txt", allow),
                "--deny", self.file("deny.txt", deny) if deny is not None else os.path.join(self.t, "none")]
        r = subprocess.run([sys.executable, "-I", SCAN] + args, capture_output=True, encoding="utf-8", timeout=60)
        return r.returncode, r.stdout, r.stderr

    def test_findings_with_their_place(self):
        rc, out, _ = self.scan(["plain words", "the host 10.1.2.3 and bob@corp.test", "see box.home.arpa"])
        self.assertEqual(rc, 1)
        self.assertIn("notes.md:5: ipv4: 10.1.2.3", out)
        self.assertIn("notes.md:5: e-mail: bob@corp.test", out)
        self.assertIn("notes.md:6: private host: box.home.arpa", out)
        self.assertIn("FAIL, 3 finding(s)", out)

    def test_a_token_is_masked(self):
        token = "gh" + "p_" + "a" * 30
        rc, out, _ = self.scan(["token = %s" % token, "a tailnet host 100.99.1.1"])
        self.assertEqual(rc, 1)
        self.assertIn("notes.md:4: token: ghp_***", out)
        self.assertNotIn(token, out)
        self.assertIn("tailnet address: 100.99.1.1", out)

    def test_the_allowlist(self):
        lines = ["the host 10.1.2.3", "and 10.1.2.30"]
        rc, out, _ = self.scan(lines, allow="# a comment\n10\\.1\\.2\\.3 # a made-up host\n")
        self.assertEqual(rc, 1)                       # the whole text must match: 10.1.2.30 is not allowed
        self.assertNotIn("ipv4: 10.1.2.3\n", out)
        self.assertIn("notes.md:5: ipv4: 10.1.2.30", out)
        rc, out, _ = self.scan(lines[:1], allow="10\\.1\\.2\\.3 # a made-up host\n")
        self.assertEqual((rc, out), (0, "privacy-scan: ok, no finding outside the allowlist (1 on it)\n"))

    def test_an_allowlist_line_with_no_reason(self):
        rc, _, err = self.scan(["x"], allow="10\\.1\\.2\\.3\n")
        self.assertEqual(rc, 2)
        self.assertIn("an allowlist line needs", err)

    def test_the_machines_own_words(self):
        rc, out, _ = self.scan(["the account SecretName has it"], deny="# names\nsecretname\n")
        self.assertEqual(rc, 1)
        self.assertIn("notes.md:4: denied word: Se***", out)
        self.assertNotIn("SecretName has", out)
        self.assertEqual(self.scan(["the account SecretName has it"])[0], 0)     # no list, no words


if __name__ == "__main__":
    unittest.main()
