"""test_gh_app.py - the agent on GitHub as the App (install/gh-app.sh): runs the cases of tests/gh-app.sh.test.sh,
which has a home folder of its own, a key made with openssl, and fake curl and gh; nothing reaches GitHub.
    python3 -m unittest discover -s tests"""
import os, shutil, subprocess, unittest

from kit.io import ROOT


@unittest.skipUnless(all(shutil.which(t) for t in ("bash", "openssl", "git")), "bash, openssl or git is missing")
class TheApp(unittest.TestCase):
    def test_the_cases_of_gh_app(self):
        r = subprocess.run(["bash", os.path.join(ROOT, "tests", "gh-app.sh.test.sh")], stdin=subprocess.DEVNULL,
                           capture_output=True, encoding="utf-8", timeout=120, start_new_session=True,
                           env={k: v for k, v in os.environ.items()
                                if k not in ("AGENT_KIT_MACHINE", "GH_TOKEN") and not k.startswith("GIT_CONFIG_")})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"passed [1-9][0-9]*, failed 0\n$")


if __name__ == "__main__":
    unittest.main()
