"""the engine OpenCode: the plan of a session, with no file read and no process started."""
import json, unittest

from kit import config, engines, plan

KIT = config.defaults()
PLUGINS = {"agent-kit": "/k/plugins/agent-kit", "dev": "/k/plugins/dev"}
ROLE = "---\nname: dev\ndescription: The developer.\n---\n\nYou are a developer.\n"
SUB = {"design": {"description": "The designer.", "prompt": "You are a designer.\n", "model": "openai/gpt-5",
                  "effort": "low", "plugins": ["dev"]}}


def make(texts=None, **fields):
    f = dict(dict(KIT["session"], engine="opencode", model="openai/gpt-5", permission_mode="manual"), **fields)
    return engines.make("web", {"folder": "/h/web"}, f, "ab12", PLUGINS, machine={"GH_X": "1"}, texts=texts,
                        folders="/c/engines", base=KIT["session"])


class TheCommand(unittest.TestCase):
    def test_the_command_the_folder_and_the_configuration(self):
        doc = make()
        self.assertEqual(doc["argv"], ["opencode", "--standalone"])
        env = doc["env"]
        self.assertEqual(env["OPENCODE_CONFIG_DIR"], "/c/engines/opencode/ab12")
        self.assertEqual(json.loads(env["OPENCODE_CONFIG_CONTENT"]),
                         {"update": "disable", "model": "openai/gpt-5", "default_agent": "kit"})
        self.assertEqual((env["AGENT_KIT_SESSION"], env["GH_X"], env["OPENCODE_DISABLE_AUTOUPDATE"]),
                         ("ab12", "1", "1"))
        self.assertEqual((doc["folder"], doc["mcp"]), ("/h/web", None))

    def test_the_way_to_drive_claude_is_never_on(self):
        self.assertIn("OPENCODE_CLAUDE_PATH", make()["unset"])
        self.assertEqual(make()["env"]["OPENCODE_DISABLE_CLAUDE_CODE"], "1")
        self.assertFalse(any("ANTHROPIC" in k or k.startswith("CLAUDE") for k in make()["env"]))

    def test_bypass_is_auto_and_the_other_modes_are_refused(self):
        self.assertEqual(make(permission_mode="bypassPermissions")["argv"], ["opencode", "--standalone", "--auto"])
        for mode in ("auto", "plan", "acceptEdits"):
            with self.assertRaises(plan.PlanError) as e:
                make(permission_mode=mode)
            self.assertIn("permission_mode: %s: OpenCode has manual and bypassPermissions" % mode, str(e.exception))

    def test_a_model_is_required_and_names_its_provider(self):
        for model in (None, "fable", "/gpt"):
            with self.assertRaises(plan.PlanError) as e:
                make(model=model)
            self.assertIn("provider/model", str(e.exception))

    def test_the_users_variables_come_last(self):
        self.assertEqual(make(env={"A": "b"})["env"]["A"], "b")


class TheAgents(unittest.TestCase):
    def test_the_sessions_agent_is_a_file_with_the_rules_the_role_and_the_effort(self):
        texts = {"system_prompt": "The rules.\n", "role": ROLE, "system_prompt_append": "More.\n",
                 "plugins": {"dev": {"agent.md": "Of the plugin.\n"}}}
        doc = make(texts, agent="dev", role="/k/agents/dev.md", system_prompt="/k/p.md",
                   system_prompt_append="/k/a.md", plugins=["dev"], effort="high")
        self.assertEqual(doc["files"], [{
            "file": "/c/engines/opencode/ab12/agents/dev.md",
            "text": '---\ndescription: "The developer."\nmode: primary\nmodel: openai/gpt-5\nvariant: high\n---\n'
                    "The rules.\n\nYou are a developer.\n\nMore.\n\nOf the plugin.\n"}])
        self.assertEqual(json.loads(doc["env"]["OPENCODE_CONFIG_CONTENT"])["default_agent"], "dev")

    def test_a_subagent_is_a_file_of_the_same_folder_with_its_own_model(self):
        doc = make({"subagents": SUB}, subagents=[{"agent": "design", "model": "openai/gpt-5", "effort": "low"}])
        self.assertEqual(doc["files"][1], {
            "file": "/c/engines/opencode/ab12/agents/design.md",
            "text": '---\ndescription: "The designer."\nmode: subagent\nmodel: openai/gpt-5\nvariant: low\n---\n'
                    "You are a designer.\n"})

    def test_a_subagent_with_no_model_has_the_sessions_and_one_of_no_provider_is_refused(self):
        doc = make({"subagents": {"design": dict(SUB["design"], model=None, effort=None)}}, subagents=["design"])
        self.assertNotIn("model:", doc["files"][1]["text"])
        with self.assertRaises(plan.PlanError) as e:
            make({"subagents": {"design": dict(SUB["design"], model="fable")}}, subagents=["design"])
        self.assertIn("subagents: design: model: fable", str(e.exception))

    def test_a_plugin_there_is_not(self):
        with self.assertRaises(plan.PlanError):
            make(plugins=["nope"])


class TheFields(unittest.TestCase):
    def test_a_field_of_claude_set_off_its_default_is_refused_by_its_name(self):
        with self.assertRaises(plan.PlanError) as e:
            make(tools=["Bash"], remote_control=False)
        self.assertIn("engine: opencode does not have remote_control, tools", str(e.exception))
        with self.assertRaises(plan.PlanError) as e:
            make(subagent_tools=["WebSearch"])
        self.assertIn("engine: opencode does not have subagent_tools", str(e.exception))

    def test_the_defaults_of_the_other_fields_pass(self):
        self.assertEqual(make()["config"]["remote_control"], KIT["session"]["remote_control"])

    def test_claude_takes_every_field(self):
        f = dict(KIT["session"], tools=["Bash"])
        self.assertIn("--tools", engines.make("web", {"folder": "/w"}, f, "ab12", PLUGINS, base=KIT["session"])["argv"])


class TheStubs(unittest.TestCase):
    def test_codex_is_a_name_of_the_config_and_a_start_with_it_is_refused(self):
        config.check({"version": KIT["version"], "session": {"engine": "codex"}}, "config.json")
        with self.assertRaises(plan.PlanError) as e:
            engines.make("web", {"folder": "/w"}, dict(KIT["session"], engine="codex"), "ab12", PLUGINS,
                         folders="/c/engines", base=KIT["session"])
        self.assertIn("engine: codex: not built yet", str(e.exception))

    def test_every_engine_of_the_config_has_a_module(self):
        self.assertEqual(sorted(engines.ENGINES), sorted(config.ENGINES))


if __name__ == "__main__":
    unittest.main()
