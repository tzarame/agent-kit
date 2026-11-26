"""test_mcp.py - kit/sessions/mcp.py: kit mcp list and kit mcp remove, as kit-command says, on a home folder of the
test with claude faked: nothing of the user's is read or changed.
    python3 -m unittest discover -s tests"""
import io as textio, json, os, shutil, tempfile, unittest

from kit import cli
from kit.io import Io

TOKEN = "Bearer tok_secret_123"


class FakeIo(Io):
    def __init__(self, home):
        Io.__init__(self, {"HOME": home, "PATH": "/usr/bin:/bin"}, home)
        self.out, self.err = textio.StringIO(), textio.StringIO()
        self.calls, self.rc = [], 0

    def claude(self, args, cwd):
        self.calls.append((list(args), cwd))
        return self.rc, "Removed\n", ""


class TheMcpCommand(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home)
        self.web, self.api = os.path.join(self.home, "web"), os.path.join(self.home, "api")
        os.makedirs(self.web)
        os.makedirs(self.api)
        self.put(os.path.join(self.home, ".claude.json"), {
            "mcpServers": {"docs": {"type": "http", "url": "https://docs.example",
                                    "headers": {"Authorization": TOKEN}}},
            "projects": {self.web: {"mcpServers": {"db": {"command": "db-server", "env": {"DB_PASSWORD": "pw_1"}}}},
                         "/gone": {"allowedTools": []}}})
        self.put(os.path.join(self.api, ".mcp.json"), {"mcpServers": {"search": {"command": "search-server"}}})
        self.put(os.path.join(self.home, ".config", "agent-kit", "config.json"),
                 {"version": 2, "projects": {"api": {"folder": "~/api"}}})
        self.io = FakeIo(self.home)

    def put(self, path, doc):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f)

    def run_kit(self, *args):
        self.io.out, self.io.err = textio.StringIO(), textio.StringIO()
        return cli.main(["mcp"] + list(args), self.io)

    def log(self):
        try:
            with open(self.io.log_path, encoding="utf-8") as f:
                return [json.loads(line) for line in f]
        except FileNotFoundError:
            return []

    def test_the_list_holds_names_and_no_value(self):
        before = os.stat(os.path.join(self.home, ".claude.json")).st_mtime_ns
        self.assertEqual(self.run_kit("list"), 0)
        out = self.io.out.getvalue()
        rows = [line.split() for line in out.splitlines()[1:-1]]
        self.assertEqual(rows, [["docs", "user"], ["db", "local", self.web], ["search", "project", self.api]])
        for secret in ("tok_secret", "Bearer", "pw_1", "https://docs.example", "db-server", "search-server"):
            self.assertNotIn(secret, out)
        self.assertEqual(self.io.calls, [])
        self.assertEqual(os.stat(os.path.join(self.home, ".claude.json")).st_mtime_ns, before)

    def test_no_file_no_server(self):
        os.remove(os.path.join(self.home, ".claude.json"))
        os.remove(os.path.join(self.api, ".mcp.json"))
        self.assertEqual(self.run_kit("list"), 0)
        self.assertIn("no MCP server", self.io.out.getvalue())

    def test_a_server_removed_by_claude_code_s_command(self):
        self.assertEqual(self.run_kit("remove", "search", "project", self.api), 0)
        self.assertEqual(self.io.calls, [(["mcp", "remove", "search", "-s", "project"], self.api)])
        self.assertEqual(self.run_kit("remove", "docs", "user"), 0)
        self.assertEqual(self.io.calls[-1], (["mcp", "remove", "docs", "-s", "user"], self.home))
        self.assertEqual(self.run_kit("remove", "db", "local", "~/web"), 0)
        self.assertEqual(self.io.calls[-1], (["mcp", "remove", "db", "-s", "local"], self.web))
        log = self.log()
        self.assertEqual([(r["command"], r["server"], r["scope"], r["exit"]) for r in log],
                         [("mcp remove", "search", "project", 0), ("mcp remove", "docs", "user", 0),
                          ("mcp remove", "db", "local", 0)])
        self.assertEqual(log[0]["argv"], ["claude", "mcp", "remove", "search", "-s", "project"])
        self.assertNotIn("tok_secret", json.dumps(log))

    def test_no_such_server(self):
        for args in (("none", "user"), ("db", "user"), ("db", "local", self.api), ("search", "local", self.api)):
            self.assertEqual(self.run_kit("remove", *args), 2, args)
            self.assertIn("no server %s" % args[0], self.io.err.getvalue())
        self.assertEqual((self.io.calls, self.log()), ([], []))

    def test_the_wrong_words(self):
        for args in ((), ("lists",), ("list", "x"), ("remove", "docs"), ("remove", "docs", "global"),
                     ("remove", "docs", "user", self.web), ("remove", "db", "local")):
            self.assertEqual(self.run_kit(*args), 2, args)
            self.assertIn("usage: kit mcp", self.io.err.getvalue())
        self.assertEqual(self.io.calls, [])

    def test_claude_code_s_command_fails(self):
        self.io.rc = 1
        self.assertEqual(self.run_kit("remove", "docs", "user"), 1)
        self.assertEqual((self.log()[0]["exit"], self.log()[0]["changes"]), (1, []))


if __name__ == "__main__":
    unittest.main()
