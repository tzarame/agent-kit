"""test_content.py - where the kit takes agents and plugins from (the change launcher-and-agents): its folder
content/, the folder the config names over it, the machine's own folder over both, and the config's key content.
    python3 -m unittest discover -s tests"""
import json, os, tempfile, unittest

from kit import config
from kit.io import Io


def put(path, text="{}"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def agent(top, name, role="role.md", text="the role"):
    put(os.path.join(top, "agents", name + ".json"), json.dumps({"role": role}))
    if not role.startswith(("/", "~/", "..")):
        put(os.path.join(top, "agents", role), text)


def plugin(top, name):
    put(os.path.join(top, "plugins", name, ".claude-plugin", "plugin.json"), json.dumps({"name": name}))


class TheSources(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.home = os.path.realpath(self._t.name)
        self.io = Io(environ={"HOME": self.home}, home=self.home)
        self.content = os.path.join(self.home, "work", "content")
        put(self.io.config, json.dumps({"content": {"dir": "~/work/content"}}))
        self.own = os.path.join(self.home, ".config", "agent-kit")

    def tearDown(self):
        self._t.cleanup()

    def test_the_kit_s_content_and_the_folder_the_config_names(self):
        self.assertEqual(self.io.content(), self.content)
        agent(self.content, "writer")
        self.assertEqual(sorted(self.io.agent_files()), ["design", "dev", "dev-eco", "qa", "spec", "toolsmith", "writer"])
        self.assertEqual(self.io.agent_files()["qa"], os.path.join(self.io.kit, "content", "agents", "qa.json"))
        for text in ("{}", "not json"):                      # no folder named; a fault the start will name
            put(self.io.config, text)
            self.assertIsNone(self.io.content())
            self.assertEqual(sorted(self.io.agent_files()), ["design", "dev", "dev-eco", "qa", "spec", "toolsmith"])

    def test_the_content_s_agents_and_plugins_over_the_kit_s_own(self):
        agent(self.content, "writer")
        agent(self.content, "dev")
        plugin(self.content, "writing")
        plugin(self.content, "dev")
        files, plugins = self.io.agent_files(), self.io.plugins()
        self.assertEqual(files["writer"], os.path.join(self.content, "agents", "writer.json"))
        self.assertEqual(files["dev"], os.path.join(self.content, "agents", "dev.json"))
        self.assertEqual(plugins["writing"], os.path.join(self.content, "plugins", "writing"))
        self.assertEqual(plugins["dev"], os.path.join(self.content, "plugins", "dev"))
        self.assertEqual(self.io.agent("writer")["role"], os.path.join(self.content, "agents", "role.md"))

    def test_the_machine_s_own_over_the_content(self):
        agent(self.content, "writer")
        plugin(self.content, "writing")
        agent(self.own, "writer", role="mine.md")
        plugin(self.own, "writing")
        self.assertEqual(self.io.agent_files()["writer"], os.path.join(self.own, "agents", "writer.json"))
        self.assertEqual(self.io.plugins()["writing"], os.path.join(self.own, "plugins", "writing"))
        self.assertEqual(self.io.agent("writer")["role"], os.path.join(self.own, "agents", "mine.md"))

    def test_a_file_of_the_machine_s_own_agent_stays_in_its_folder(self):
        """the machine's keys lie one folder up: an agent there cannot name them as a text"""
        put(os.path.join(self.own, "github-app.pem"), "a key")
        agent(self.own, "thief", role="../github-app.pem")
        with self.assertRaisesRegex(config.ConfigError, "a file outside the source"):
            self.io.agent("thief")
        agent(self.content, "wide", role="../plugins/x.md")   # a content's agent may name a file of its plugins
        put(os.path.join(self.content, "plugins", "x.md"), "text")
        self.assertEqual(self.io.agent("wide")["role"], os.path.join(self.content, "plugins", "x.md"))


class TheConfigsKey(unittest.TestCase):
    def test_the_fields_of_content(self):
        for doc in ({}, {"dir": None}, {"dir": "~/work/agents"}, {"dir": "/srv/agents"}):
            config.check({"content": doc}, "config.json")
        for doc, said in (({"dir": "relative"}, "content.dir"), ({"dir": 1}, "content.dir"),
                          ({"repo": "a/b"}, "content.repo: a field the kit does not know"),
                          ([], "content: not an object")):
            with self.assertRaisesRegex(config.ConfigError, said):
                config.check({"content": doc}, "config.json")


if __name__ == "__main__":
    unittest.main()
