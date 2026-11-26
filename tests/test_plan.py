"""test_plan.py - kit/plan.py: the start's keys, and the session's config, environment and command line from plain
values, as the scenarios of session-settings and agent-launch say.
    python3 -m unittest discover -s tests"""
import json, unittest

from kit import config, engines, plan
from kit.plan import PlanError

KIT = config.defaults()
# what a start with the kit's defaults does not give: Claude Code's own are kept
NOT_BY_DEFAULT = ("--model", "--effort", "--autocompact", "--system-prompt", "--append-system-prompt", "--tools",
                  "--mcp-config", "--strict-mcp-config", "--no-chrome")
PLUGINS = {"agent-kit": "/k/plugins/agent-kit", "dev": "/k/plugins/dev", "qa": "/k/plugins/qa",
           "langfuse": "/s/plugins/langfuse"}
TEXTS = {"system_prompt": "The rules.\n", "system_prompt_append": "More.\n"}
ROLES = {"dev": "---\nname: dev\ndescription: d\n---\n\nYou are a developer.\n",
         "qa": "---\nname: qa\ndescription: q\n---\nYou are a tester.\n",
         "design": "---\nname: design\ndescription: The designer.\n---\n\nYou are a designer.\n"}
# the agents of the sources, as kit/io.py reads them
AGENTS = {"dev": {"role": "/k/agents/dev.md", "plugins": ["dev"]},
          "qa": {"role": "/k/agents/qa.md", "plugins": ["qa"]}}
# the agents a session may have as subagents, besides those
SUBS = dict(AGENTS, design={"role": "/k/agents/design.md", "plugins": ["langfuse"], "model": "opus"},
            bare={"plugins": ["qa"]})
# a project of the kit's prompt and the agent dev
KITLIKE = {"system_prompt": "/k/prompt.md", "agent": "dev"}
PROMPT = ["--system-prompt", "The rules.\n\nYou are a developer.\n", "--system-prompt-snapshot", "off"]


def start(project=None, user=None, args=("web",), sid="ab12"):
    """the plan of `kit start ARGS` with the user's config, as kit start layers it"""
    user = dict(user or {}, version=KIT["version"])
    if project is not None:
        user = dict(user, projects={"web": dict({"folder": "/h/web"}, **project)})
    config.check(user, "config.json")
    name, _, layer, given, _, _ = plan.parse_start(list(args))
    entry = config.project(user, name) or {"folder": "/h/" + name}
    fields = config.session(KIT, user, name)
    aname = layer.get("agent") or fields["agent"]
    if aname:
        fields = config.over_agent(fields, config.agent(user, aname, AGENTS.get, AGENTS))
    texts = dict(TEXTS)
    if fields["role"]:
        texts["role"] = ROLES[fields["role"].rsplit("/", 1)[1][:-3]]
    texts["subagents"] = plan.subagents(config.over(fields, layer),
                                        lambda n: config.agent(user, n, SUBS.get, SUBS),
                                        lambda path: ROLES[path.rsplit("/", 1)[1][:-3]])
    return engines.make(name, entry, fields, sid, PLUGINS, layer, given, None, texts=texts,
                     mcp_file="/c/sessions/%s.mcp.json" % sid)


def flag(argv, name):
    """the value after the flag, or None when the command line has no such flag"""
    return argv[argv.index(name) + 1] if name in argv else None


class TheKeys(unittest.TestCase):
    def test_a_model_and_an_effort(self):
        self.assertEqual(plan.parse_start(["web", "--opus", "--high"]),
                         ("web", None, {"model": "opus", "effort": "high"}, ["--opus", "--high"], False, False))

    def test_the_last_key_wins(self):
        _, _, layer, _, _, _ = plan.parse_start(["--sonnet", "web", "--fable", "--max", "--low"])
        self.assertEqual(layer, {"model": "fable", "effort": "low"})

    def test_eco_and_profile_are_gone_for_an_agent(self):
        for key in (["--eco"], ["--profile", "cheap"]):
            with self.assertRaises(PlanError) as e:
                plan.parse_start(["web"] + key)
            self.assertIn("%s is gone" % key[0], str(e.exception))
            self.assertIn("--agent NAME", str(e.exception))

    def test_the_agent_over_the_project_and_the_keys_over_the_agent(self):
        user = {"agents": {"cheap": {"model": "haiku", "effort": "low", "compact_window": 100000},
                           "big": {"model": "opus"}}}
        s = start({"model": "sonnet", "effort": "high", "agent": "cheap"}, user)
        self.assertEqual([flag(s["argv"], f) for f in ("--model", "--effort", "--autocompact")],
                         ["haiku", "low", "100000"])
        self.assertEqual(s["config"]["agent"], "cheap")
        s = start({"agent": "cheap"}, user, args=("web", "--agent", "big", "--max"))
        self.assertEqual([flag(s["argv"], f) for f in ("--model", "--effort")], ["opus", "max"])
        self.assertEqual(s["keys"], ["--agent", "big", "--max"])
        s = start({"agent": "cheap"}, user, args=("web", "--window", "132k"))
        self.assertEqual((flag(s["argv"], "--autocompact"), s["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"]),
                         (None, "132000"))
        s = start(user=dict(user, session={"agent": "big"}))
        self.assertEqual(flag(s["argv"], "--model"), "opus")
        with self.assertRaises(config.ConfigError) as e:
            start(user=user, args=("web", "--agent", "nope"))
        self.assertIn("agent: nope: no such agent; there are big, cheap, dev, qa", str(e.exception))

    def test_an_agent_built_over_another(self):
        user = {"agents": {"kit": {"agent": "dev", "system_prompt": "/k/prompt.md", "plugins": ["langfuse"]},
                           "mine": {"agent": "kit", "model": "opus", "role": "/k/agents/qa.md"}}}
        s = start({"plugins": ["qa"]}, user, args=("web", "--agent", "kit"))
        self.assertEqual(s["argv"][s["argv"].index("--system-prompt"):][:4], PROMPT)
        self.assertEqual(dirs(s["argv"]),
                         ["/k/plugins/agent-kit", "/k/plugins/qa", "/k/plugins/dev", "/s/plugins/langfuse"])
        self.assertEqual(s["config"]["agent"], "kit")
        s = start(user=user, args=("web", "--agent", "mine"))
        self.assertEqual((flag(s["argv"], "--model"), flag(s["argv"], "--system-prompt")),
                         ("opus", "The rules.\n\nYou are a tester.\n"))

    def test_an_agent_built_over_itself(self):
        for agents in ({"a": {"agent": "a"}}, {"a": {"agent": "b"}, "b": {"agent": "a"}}):
            with self.assertRaises(config.ConfigError) as e:
                start(user={"agents": agents}, args=("web", "--agent", "a"))
            self.assertIn("built over itself", str(e.exception))

    def test_the_config_s_agent_over_the_source_s(self):
        s = start(user={"agents": {"dev": {"model": "haiku", "plugins": ["langfuse"]}}}, args=("web", "--agent", "dev"))
        self.assertEqual(flag(s["argv"], "--model"), "haiku")
        self.assertEqual(flag(s["argv"], "--append-system-prompt"), "You are a developer.\n")
        self.assertEqual(dirs(s["argv"]), ["/k/plugins/agent-kit", "/k/plugins/dev", "/s/plugins/langfuse"])

    def test_the_window(self):
        self.assertEqual(plan.parse_start(["web", "--window", "132k"])[2],
                         {"context_window": 132000, "compact_window": None})
        self.assertEqual(plan.parse_start(["web", "--window", "200000"])[2]["context_window"], 200000)
        self.assertEqual(plan.parse_start(["web", "--window", "1k", "--window", "default"])[2], {})

    def test_the_compaction_key(self):
        self.assertEqual(plan.parse_start(["web", "--compact", "200k"])[2],
                         {"context_window": None, "compact_window": 200000})
        both = plan.parse_start(["web", "--window", "132k", "--compact", "200k"])[2]
        self.assertEqual(both, {"context_window": None, "compact_window": 200000})
        self.assertEqual(plan.parse_start(["web", "--compact", "1k", "--compact", "default"])[2], {})
        s = start(args=("web", "--compact", "200k"))
        self.assertEqual(s["argv"][s["argv"].index("--autocompact") + 1], "200000")
        self.assertNotIn("CLAUDE_CODE_AUTO_COMPACT_WINDOW", s["env"])
        for bad in (["--compact"], ["--compact", "abc"], ["--compact", "0"]):
            with self.assertRaises(plan.PlanError) as e:
                plan.parse_start(["web"] + bad)
            self.assertIn("--compact", str(e.exception))
        for bad in ("big", "0", "-1", "100000k", "1.5k"):
            with self.assertRaises(PlanError):
                plan.parse_start(["web", "--window", bad])
        with self.assertRaises(PlanError):
            plan.parse_start(["web", "--window"])

    def test_a_dry_run(self):
        self.assertTrue(plan.parse_start(["web", "--dry-run"])[4])

    def test_a_new_conversation(self):
        self.assertEqual(plan.parse_start(["web", "--new"])[3:], (["--new"], False, True))
        self.assertFalse(plan.parse_start(["web"])[5])

    def test_the_editor_is_parked(self):
        for key in ("--vscode", "--code-server"):
            with self.assertRaises(PlanError) as e:
                plan.parse_start(["web", key])
            self.assertIn(key, str(e.exception))
            self.assertIn("the editor is parked", str(e.exception))

    def test_a_key_of_a_parked_part(self):
        for key in ("--label", "--save", "--no-dashboard", "--clear", "-n", "--reset", "--role", "--addon"):
            with self.assertRaises(PlanError) as e:
                plan.parse_start(["web", key])
            self.assertIn(key, str(e.exception))

    def test_a_role_or_an_add_on_is_a_plugin_now(self):
        for key in ("--qa", "--design", "--development", "--gstack", "--langfuse"):
            with self.assertRaises(PlanError) as e:
                plan.parse_start(["web", key])
            self.assertIn(key, str(e.exception))
            self.assertIn("--plugin NAME", str(e.exception))

    def test_the_plugins_for_one_session(self):
        self.assertEqual(plan.parse_start(["web", "--plugin", "qa", "--plugin", "langfuse"])[2:4],
                         ({"plugins": ["qa", "langfuse"]}, ["--plugin", "qa", "--plugin", "langfuse"]))
        for bad in (["web", "--plugin"], ["web", "--plugin", "a b"]):
            with self.assertRaises(PlanError):
                plan.parse_start(bad)

    def test_an_unknown_key(self):
        with self.assertRaises(PlanError) as e:
            plan.parse_start(["web", "--nope"])
        self.assertIn("unknown option --nope", str(e.exception))

    def test_the_project(self):
        for args in ([], ["--opus"], ["a", "b"], ["../x"], [".web"], ["/web"], ["o/.web"], ["a/b/web"], ["-o/web"]):
            with self.assertRaises(PlanError):
                plan.parse_start(args)

    def test_a_repository_to_clone(self):
        self.assertEqual(plan.parse_start(["acme/web.site", "--opus"])[:3], ("web.site", "acme/web.site",
                                                                             {"model": "opus"}))


class TheCommandLine(unittest.TestCase):
    def test_the_options_of_a_session(self):
        s = start()
        self.assertEqual(s["argv"], [
            "claude", "--permission-mode", "auto", "--continue", "--name", "web-ab12",
            "--plugin-dir", "/k/plugins/agent-kit",
            "--remote-control", "--remote-control-session-name-prefix", "web",
            "--prompt-suggestions", "false",
            "--settings", '{"syncClaudeAiSkills":false,"syncClaudeAiPlugins":false}'])
        for o in NOT_BY_DEFAULT:
            self.assertNotIn(o, s["argv"])

    def test_the_project_s_model_and_effort(self):
        s = start({"model": "sonnet", "effort": "high"})
        self.assertEqual((flag(s["argv"], "--model"), flag(s["argv"], "--effort")), ("sonnet", "high"))

    def test_a_model_for_one_session(self):
        s = start({"model": "haiku"}, args=("web", "--opus"))
        self.assertEqual(flag(s["argv"], "--model"), "opus")
        self.assertEqual(s["keys"], ["--opus"])
        self.assertEqual(flag(start({"model": "haiku"})["argv"], "--model"), "haiku")
        self.assertEqual(flag(start(args=("web", "--max"))["argv"], "--effort"), "max")

    def test_the_names_of_a_session(self):
        s = start(sid="x9y8")
        self.assertEqual(flag(s["argv"], "--name"), "web-x9y8")
        self.assertEqual(flag(s["argv"], "--remote-control-session-name-prefix"), "web")
        s = start({"name_prefix": "my", "name_postfix": "a1"}, sid="x9y8")
        self.assertEqual(flag(s["argv"], "--name"), "my-web-x9y8-a1")
        self.assertEqual(flag(s["argv"], "--remote-control-session-name-prefix"), "my-web-a1")
        s = start({"remote_control": False})
        self.assertNotIn("--remote-control", s["argv"])
        self.assertNotIn("--remote-control-session-name-prefix", s["argv"])

    def test_the_conversation_continues(self):
        self.assertIn("--continue", start()["argv"])

    def test_a_folder_with_no_conversation_starts_one(self):
        s = engines.make("web", {"folder": "/w"}, KIT["session"], "ab12", PLUGINS, talked=False)
        self.assertNotIn("--continue", s["argv"])
        self.assertEqual(s["argv"][3:5], ["--name", "web-ab12"])

    def test_the_prompt_suggestions(self):
        self.assertNotIn("--prompt-suggestions", start({"prompt_suggestions": True})["argv"])

    def test_an_agent_as_a_subagent_is_given_to_claude_with_its_model_effort_and_plugins(self):
        doc = start(dict(KITLIKE, subagents=[{"agent": "design", "model": "fable", "effort": "low"}]))
        given = json.loads(flag(doc["argv"], "--agents"))
        self.assertEqual(given, {"design": {"description": "The designer.", "prompt": "You are a designer.\n",
                                            "model": "fable", "effort": "low"}})
        self.assertIn(PLUGINS["langfuse"], doc["argv"])          # its skills come with it
        self.assertEqual(flag(doc["argv"], "--system-prompt"), PROMPT[1])   # the session stays the developer

    def test_a_subagent_by_its_name_has_the_agents_own_model_and_no_effort(self):
        doc = start(dict(KITLIKE, subagents=["design", "qa"]))
        given = json.loads(flag(doc["argv"], "--agents"))
        self.assertEqual(given["design"]["model"], "opus")
        self.assertNotIn("effort", given["design"])
        self.assertNotIn("model", given["qa"])

    def test_no_subagents_no_key(self):
        self.assertNotIn("--agents", start(KITLIKE)["argv"])

    def test_an_agent_is_the_session_or_its_subagent_and_a_subagent_needs_a_role(self):
        for subs, word in ((["dev"], "the session's agent already"), (["bare"], "has no role"),
                           (["nobody"], "no such agent")):
            with self.assertRaises((plan.PlanError, config.ConfigError)) as e:
                start(dict(KITLIKE, subagents=subs))
            self.assertIn(word, str(e.exception))

    def test_the_list_of_subagents_is_checked(self):
        for bad in ("design", ["design", "design"], [{"model": "fable"}], [{"agent": "design", "tools": []}],
                    [{"agent": "design", "effort": 1}], [1]):
            with self.assertRaises(config.ConfigError, msg=bad):
                start(dict(KITLIKE, subagents=bad))

    def test_the_engine_claude_is_the_default_and_builds_the_command(self):
        self.assertEqual(sorted(engines.ENGINES), sorted(config.ENGINES))
        s = start({})
        self.assertEqual((s["config"]["engine"], s["argv"][0]), ("claude", "claude"))
        self.assertEqual(start({"engine": "claude"})["argv"], s["argv"])

    def test_the_fallback_model_and_the_permission_mode(self):
        s = start({"fallback_model": "sonnet,haiku", "permission_mode": "plan"})
        self.assertEqual(flag(s["argv"], "--fallback-model"), "sonnet,haiku")
        self.assertEqual(flag(s["argv"], "--permission-mode"), "plan")
        self.assertNotIn("--fallback-model", start()["argv"])


class TheWindow(unittest.TestCase):
    def test_the_window_by_the_model(self):
        by_model = {"context_window": {"haiku": 113000, "*": 200000}}
        for model, w in (("haiku", "113000"), ("claude-haiku-4-5", "113000"), ("sonnet", "200000"),
                         ("opus", "200000"), ("fable", "200000"), ("claude-opus-4-7", "200000")):
            s = start(dict(by_model, model=model))
            self.assertEqual(s["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], w, model)
            self.assertNotIn("CLAUDE_CODE_AUTO_COMPACT_WINDOW", start({"model": model})["env"])
        self.assertEqual(start(by_model)["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], "200000")
        s = start({"context_window": {"haiku": 113000, "opus": None}, "model": "opus"})
        self.assertIn("CLAUDE_CODE_AUTO_COMPACT_WINDOW", s["unset"])
        s = start({"context_window": {"haiku": 113000}, "model": "sonnet"})
        self.assertIn("CLAUDE_CODE_AUTO_COMPACT_WINDOW", s["unset"])
        s = start({"context_window": {"haiku": 1000, "claude-haiku-4-5": 2000}, "model": "claude-haiku-4-5"})
        self.assertEqual(s["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], "2000")

    def test_a_window_of_the_key_wins_over_the_model(self):
        s = start(args=("web", "--window", "300k"))
        self.assertEqual(s["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], "300000")

    def test_the_hard_window(self):
        s = start({"context_window": 132000})
        self.assertEqual(s["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], "132000")
        self.assertNotIn("--autocompact", s["argv"])
        self.assertNotIn("CLAUDE_CODE_AUTO_COMPACT_WINDOW", s["unset"])

    def test_the_soft_window(self):
        s = start({"compact_window": 200000})
        self.assertEqual(flag(s["argv"], "--autocompact"), "200000")
        self.assertNotIn("CLAUDE_CODE_AUTO_COMPACT_WINDOW", s["env"])
        self.assertIn("CLAUDE_CODE_AUTO_COMPACT_WINDOW", s["unset"])

    def test_no_window(self):
        s = start({"context_window": None})
        self.assertNotIn("--autocompact", s["argv"])
        self.assertIn("CLAUDE_CODE_AUTO_COMPACT_WINDOW", s["unset"])

    def test_the_project_gives_the_variable(self):
        s = start({"compact_window": 200000, "env": {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "300000"}})
        self.assertEqual(s["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], "300000")
        self.assertNotIn("CLAUDE_CODE_AUTO_COMPACT_WINDOW", s["unset"])

    def test_a_window_for_one_session(self):
        s = start({"compact_window": 200000}, args=("web", "--window", "132000"))
        self.assertEqual(s["env"]["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], "132000")
        self.assertNotIn("--autocompact", s["argv"])

    def test_both_windows(self):
        with self.assertRaises(PlanError) as e:
            engines.make("web", {"folder": "/w"}, dict(KIT["session"], context_window=132000, compact_window=200000),
                      "ab12", PLUGINS)
        self.assertIn("context_window", str(e.exception))
        self.assertIn("compact_window", str(e.exception))


class ThePluginsLines(unittest.TestCase):
    def test_a_plugin_of_the_session_brings_its_own_lines(self):
        """after the agent's text, in the plugins' order; the subagents' hook is told the files for all"""
        own = {"langfuse": {"system-prompt.md": "For all.\n", "agent.md": "For the session.\n"},
               "dev": {"agent.md": "Dev only.\n"}, "qa": {"system-prompt.md": "Not in this session.\n"},
               "agent-kit": {"system-prompt.md": "The kit's own, given by its field.\n"}}
        user = dict({"version": KIT["version"]}, projects={"web": dict({"folder": "/h/web", "plugins": ["langfuse"]},
                                                                      **KITLIKE)})
        config.check(user, "config.json")
        fields = config.over_agent(config.session(KIT, user, "web"), config.agent(user, "dev", AGENTS.get, AGENTS))
        texts = dict(TEXTS, role=ROLES["dev"], plugins=own)
        s = engines.make("web", {"folder": "/h/web"}, fields, "ab12", PLUGINS, {}, (), None, texts=texts)
        self.assertEqual(s["config"]["plugins"], ["langfuse", "dev"])
        self.assertEqual(flag(s["argv"], "--append-system-prompt"),
                         "For all.\n\nFor the session.\n\nDev only.\n")
        self.assertEqual(flag(s["argv"], "--system-prompt"), PROMPT[1])
        self.assertEqual(s["env"]["AGENT_KIT_PLUGIN_PROMPTS"], "/s/plugins/langfuse/system-prompt.md")
        with self.assertRaisesRegex(plan.PlanError, "a colon in its path"):
            engines.make("web", {"folder": "/h/web"}, fields, "ab12", dict(PLUGINS, langfuse="/s/a:b/langfuse"), {}, (),
                      None, texts=texts)
        s = start(KITLIKE)
        self.assertNotIn("AGENT_KIT_PLUGIN_PROMPTS", s["env"])
        self.assertIn("AGENT_KIT_PLUGIN_PROMPTS", s["unset"])


class TheEnvironment(unittest.TestCase):
    def test_the_idle_compaction_and_the_lives_of_the_cache(self):
        """the idle threshold is a variable, dropped from an inherited environment when the kit leaves it out; the
        switch and the two lives are settings, and none is given when the field has Claude Code's own"""
        s = start()
        self.assertNotIn("idleCompaction", s["argv"][s["argv"].index("--settings") + 1])
        self.assertNotIn("CacheTtl", s["argv"][s["argv"].index("--settings") + 1])
        s = start({"idle_compact_from": 150000})
        self.assertEqual(s["env"]["CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS"], "150000")
        for project in ({"idle_compact_from": None}, {"idle_compact": False}):
            s = start(project)
            self.assertNotIn("CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS", s["env"])
            self.assertIn("CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS", s["unset"])
        s = start({"idle_compact": False, "cache_life": "5m", "subagent_cache_life": "1h"})
        got = json.loads(s["argv"][s["argv"].index("--settings") + 1])
        self.assertEqual((got["idleCompaction"], got["promptCacheTtl"], got["subagentPromptCacheTtl"]),
                         (False, "5m", "1h"))
        for bad in ({"idle_compact_from": 99999}, {"idle_compact_from": "100000"}, {"cache_life": "2h"},
                    {"subagent_cache_life": 5}, {"idle_compact": None}):
            with self.assertRaises(config.ConfigError):
                config.entry_fields(bad, "web")

    def test_the_environment_of_a_start(self):
        s = start()
        self.assertEqual(s["env"], {"CLAUDE_CODE_DISABLE_ADVISOR_TOOL": "1", "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
                                    "CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS": "100000",
                                    "AGENT_KIT_SESSION": "ab12", "AGENT_KIT_PROMPT": "0",
                                    "AGENT_KIT_DESIGN_DIR": "design"})
        self.assertEqual(s["unset"], ["CLAUDE_CODE_AUTO_COMPACT_WINDOW", "AGENT_KIT_ROLE", "AGENT_KIT_PLUGIN_PROMPTS",
                                      "CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_SUBAGENT_EFFORT"])
        s = start({"subagent_model": "haiku", "subagent_effort": "low"})
        self.assertEqual((s["env"]["CLAUDE_CODE_SUBAGENT_MODEL"], s["env"]["CLAUDE_CODE_SUBAGENT_EFFORT"]),
                         ("haiku", "low"))

    def test_the_machine_s_variables(self):
        machine = {"AGENT_KIT_MACHINE": "me@box", "GIT_CONFIG_COUNT": "3", "CLAUDE_CODE_SUBAGENT_MODEL": "x"}
        s = engines.make("web", {"folder": "/w"}, KIT["session"], "ab12", PLUGINS, machine=machine)
        self.assertEqual((s["env"]["AGENT_KIT_MACHINE"], s["env"]["GIT_CONFIG_COUNT"]), ("me@box", "3"))
        self.assertEqual(s["env"]["CLAUDE_CODE_SUBAGENT_MODEL"], "x")
        s = engines.make("web", {"folder": "/w"}, dict(KIT["session"], subagent_model="haiku"), "ab12", PLUGINS,
                      machine=machine)
        self.assertEqual(s["env"]["CLAUDE_CODE_SUBAGENT_MODEL"], "haiku")
        s = engines.make("web", {"folder": "/w"}, dict(KIT["session"], env={"AGENT_KIT_MACHINE": "other"}), "ab12",
                      PLUGINS, machine=machine)
        self.assertEqual(s["env"]["AGENT_KIT_MACHINE"], "other")

    def test_a_project_s_variable(self):
        s = start({"subagent_model": "sonnet", "env": {"CLAUDE_CODE_SUBAGENT_MODEL": "opus"}})
        self.assertEqual(s["env"]["CLAUDE_CODE_SUBAGENT_MODEL"], "opus")

    def test_a_token_of_the_project(self):
        s = start({"env": {"GH_TOKEN": "ghs_secret123"}})
        self.assertEqual(s["env"]["GH_TOKEN"], "ghs_secret123")
        self.assertNotIn("ghs_secret123", json.dumps(s["argv"]))
        self.assertEqual(json.loads(flag(s["argv"], "--settings")),
                         {"syncClaudeAiSkills": False, "syncClaudeAiPlugins": False})


class TheAdvisor(unittest.TestCase):
    def test_the_advisor_by_default(self):
        s = start()
        self.assertEqual(s["env"]["CLAUDE_CODE_DISABLE_ADVISOR_TOOL"], "1")
        self.assertNotIn("--advisor", s["argv"])

    def test_an_advisor_for_a_project(self):
        s = start({"advisor": "opus"})
        self.assertEqual(flag(s["argv"], "--advisor"), "opus")
        self.assertNotIn("CLAUDE_CODE_DISABLE_ADVISOR_TOOL", s["env"])
        self.assertIn("CLAUDE_CODE_DISABLE_ADVISOR_TOOL", s["unset"])

    def test_the_advisor_of_claude_code(self):
        s = start({"advisor": "default"})
        self.assertNotIn("--advisor", s["argv"])
        self.assertNotIn("CLAUDE_CODE_DISABLE_ADVISOR_TOOL", s["env"])


class TheSync(unittest.TestCase):
    def test_a_project_that_wants_the_skills(self):
        s = start({"claude_ai_skills": True})
        self.assertEqual(flag(s["argv"], "--settings"), '{"syncClaudeAiPlugins":false}')
        self.assertEqual(s["env"]["ENABLE_CLAUDEAI_MCP_SERVERS"], "false")

    def test_a_project_that_wants_all_of_it(self):
        s = start({"claude_ai_skills": True, "claude_ai_plugins": True, "claude_ai_connectors": True})
        self.assertNotIn("--settings", s["argv"])
        self.assertNotIn("ENABLE_CLAUDEAI_MCP_SERVERS", s["env"])
        self.assertIn("ENABLE_CLAUDEAI_MCP_SERVERS", s["unset"])

    def test_a_project_with_a_style(self):
        s = start({"output_style": "Explanatory"})
        self.assertEqual(json.loads(flag(s["argv"], "--settings")),
                         {"syncClaudeAiSkills": False, "syncClaudeAiPlugins": False, "outputStyle": "Explanatory"})
        self.assertNotIn("outputStyle", flag(start()["argv"], "--settings"))


def dirs(argv):
    return [argv[i + 1] for i, a in enumerate(argv) if a == "--plugin-dir"]


class TheAgent(unittest.TestCase):
    def test_the_key(self):
        self.assertEqual(plan.parse_start(["web", "--agent", "qa"])[2:4], ({"agent": "qa"}, ["--agent", "qa"]))
        for bad in (["web", "--agent"], ["web", "--agent", "a b"]):
            with self.assertRaises(PlanError):
                plan.parse_start(bad)

    def test_the_default_prompt_is_claude_code_s(self):
        s = start()
        for o in ("--system-prompt", "--system-prompt-snapshot", "--append-system-prompt"):
            self.assertNotIn(o, s["argv"])
        self.assertEqual(s["env"][plan.PROMPT_VAR], "0")
        self.assertIn(plan.ROLE_VAR, s["unset"])

    def test_the_prompt_file_then_the_agent(self):
        s = start(KITLIKE)
        self.assertEqual(s["argv"][s["argv"].index("--system-prompt"):][:4], PROMPT)
        self.assertEqual(s["env"][plan.PROMPT_VAR], "1")
        self.assertNotIn("--append-system-prompt", s["argv"])
        self.assertEqual(flag(start(dict(KITLIKE, agent=None))["argv"], "--system-prompt"), "The rules.\n")

    def test_the_agent_of_the_key_wins_over_the_project_s(self):
        s = start(KITLIKE, args=("web", "--agent", "qa"))
        self.assertEqual(flag(s["argv"], "--system-prompt"), "The rules.\n\nYou are a tester.\n")
        self.assertEqual(dirs(s["argv"]), ["/k/plugins/agent-kit", "/k/plugins/qa"])

    def test_an_agent_with_claude_code_s_prompt_is_added_to_it(self):
        s = start({"agent": "dev"})
        self.assertNotIn("--system-prompt", s["argv"])
        self.assertEqual(flag(s["argv"], "--append-system-prompt"), "You are a developer.\n")
        s = start({"agent": "dev", "system_prompt_append": "~/more.md"})
        self.assertEqual(flag(s["argv"], "--append-system-prompt"), "More.\n\nYou are a developer.\n")
        s = start(dict(KITLIKE, system_prompt_append="~/more.md"))
        self.assertEqual((flag(s["argv"], "--system-prompt"), flag(s["argv"], "--append-system-prompt")),
                         (PROMPT[1], "More.\n"))

    def test_an_agent_there_is_not(self):
        for agent in ("nope", "langfuse"):                  # langfuse is a plugin, not an agent
            with self.assertRaises(config.ConfigError) as e:
                start({"agent": agent})
            self.assertIn("agent: %s: no such agent; there are dev, qa" % agent, str(e.exception))

    def test_a_wrong_system_prompt(self):
        for bad in ("mine", "kit", "prompt.md"):
            with self.assertRaises(config.ConfigError):
                start({"system_prompt": bad})

    def test_the_body_of_an_agent_s_file(self):
        self.assertEqual(plan.body("---\nname: a\n---\n\nText.\n---\nmore\n"), "Text.\n---\nmore")
        self.assertEqual(plan.body("No header.\n"), "No header.")


class ThePlugins(unittest.TestCase):
    def test_agent_kit_first_then_the_project_s_then_the_agent_s(self):
        self.assertEqual(dirs(start({"plugins": ["qa", "langfuse"], "agent": "dev"})["argv"]),
                         ["/k/plugins/agent-kit", "/k/plugins/qa", "/s/plugins/langfuse", "/k/plugins/dev"])

    def test_no_plugin_but_agent_kit_and_the_agent_s(self):
        self.assertEqual(dirs(start({"plugins": []})["argv"]), ["/k/plugins/agent-kit"])
        self.assertEqual(dirs(start({"plugins": []}, args=("web", "--agent", "dev"))["argv"]),
                         ["/k/plugins/agent-kit", "/k/plugins/dev"])
        self.assertEqual(dirs(start({"plugins": ["agent-kit", "dev", "dev"]})["argv"]),
                         ["/k/plugins/agent-kit", "/k/plugins/dev"])

    def test_a_key_of_a_plugin_there_already(self):
        self.assertEqual(start({"plugins": ["qa"]}, args=("web", "--plugin", "qa"))["config"]["plugins"], ["qa"])

    def test_the_key_adds_to_the_project(self):
        self.assertEqual(dirs(start({"plugins": ["langfuse"]}, args=("web", "--plugin", "qa"))["argv"]),
                         ["/k/plugins/agent-kit", "/s/plugins/langfuse", "/k/plugins/qa"])

    def test_a_plugin_there_is_not(self):
        with self.assertRaises(PlanError) as e:
            start({"plugins": ["nope"]})
        self.assertIn("nope", str(e.exception))
        self.assertIn("dev", str(e.exception))

    def test_no_agent_kit(self):
        with self.assertRaises(PlanError) as e:
            engines.make("web", {"folder": "/w"}, KIT["session"], "ab12", {"dev": "/k/plugins/dev"})
        self.assertIn("agent-kit", str(e.exception))


class TheToolsAndSkills(unittest.TestCase):
    def test_the_built_in_tools_are_the_list_given(self):
        s = start({"tools": ["Read", "Bash", "Skill"]})
        self.assertEqual(flag(s["argv"], "--tools"), "Read,Bash,Skill")
        self.assertEqual(flag(start({"tools": []})["argv"], "--tools"), "")

    def test_the_tools_only_the_subagents_have(self):
        """--tools is the pool; the session is started as an agent whose tools are its own list"""
        s = start(dict(KITLIKE, tools=["Bash", "Read", "Agent"], subagent_tools=["WebSearch", "Read", "WebFetch"]))
        self.assertEqual(flag(s["argv"], "--tools"), "Bash,Read,Agent,WebSearch,WebFetch")
        self.assertEqual(flag(s["argv"], "--agent"), "kit-session")
        self.assertEqual(json.loads(flag(s["argv"], "--agents"))["kit-session"]["tools"], ["Bash", "Read", "Agent"])
        # the agent the session is started as carries the session's prompt: Claude Code takes the agent's
        self.assertEqual(json.loads(flag(s["argv"], "--agents"))["kit-session"]["prompt"],
                         flag(s["argv"], "--system-prompt"))
        self.assertEqual(s["argv"][s["argv"].index("--system-prompt"):][:2], PROMPT[:2])
        both = start(dict(KITLIKE, tools=["Read", "Agent"], subagent_tools=["WebSearch"], subagents=["qa"]))
        self.assertEqual(sorted(json.loads(flag(both["argv"], "--agents"))), ["kit-session", "qa"])

    def test_no_tool_for_the_subagents_only_no_agent_of_the_session(self):
        for project in ({"tools": ["Read", "Agent"]}, dict(KITLIKE, tools=["Read"], subagent_tools=["Read"]),
                        {"tools": ["Read"], "subagent_tools": ["Read"]}):     # with Claude Code's prompt too
            argv = start(project)["argv"]
            self.assertNotIn("--agent", argv)
            self.assertNotIn("--agents", argv)
            self.assertEqual(flag(argv, "--tools"), ",".join(project["tools"]))

    def test_the_subagents_tools_need_the_session_s_tools_and_the_kit_s_prompt(self):
        for project, word in ((dict(KITLIKE, subagent_tools=["WebSearch"]), "tools names no tool"),
                              (dict(KITLIKE, tools=[], subagent_tools=["WebSearch"]), "tools names no tool"),
                              ({"tools": ["Read"], "subagent_tools": ["WebSearch"]}, "system_prompt is not set")):
            with self.assertRaises(PlanError) as e:
                start(project)
            self.assertIn("subagent_tools", str(e.exception))
            self.assertIn(word, str(e.exception))

    def test_no_subagent_under_the_session_s_own_name(self):
        f = dict(KIT["session"], subagents=[plan.SESSION_AGENT])
        texts = {"subagents": {plan.SESSION_AGENT: {"description": "d", "prompt": "p\n", "model": None,
                                                    "effort": None, "plugins": []}}}
        with self.assertRaises(PlanError) as e:
            engines.make("web", {"folder": "/w"}, f, "ab12", PLUGINS, texts=texts)
        self.assertIn("kit-session", str(e.exception))

    def test_the_bundled_skills(self):
        s = start({"bundled_skills": False, "bundled_skills_off": ["simplify", "code-review"]})
        got = json.loads(flag(s["argv"], "--settings"))
        self.assertEqual((got["disableBundledSkills"], got["skillOverrides"]),
                         (True, {"simplify": "off", "code-review": "off"}))
        self.assertNotIn("skillOverrides", flag(start()["argv"], "--settings"))

    def test_the_built_in_plugins_and_subagents_turned_off(self):
        s = start({"builtin_plugins_off": ["cc-plugin-easel"], "subagents_off": ["Plan", "claude"]})
        got = json.loads(flag(s["argv"], "--settings"))
        self.assertEqual(got["enabledPlugins"], {"cc-plugin-easel@builtin": False})
        self.assertEqual(got["permissions"], {"deny": ["Agent(Plan)", "Agent(claude)"]})
        plain = flag(start()["argv"], "--settings")
        self.assertNotIn("enabledPlugins", plain)
        self.assertNotIn("permissions", plain)


SERVERS = {"docs": {"command": "docs-server", "args": ["--key", "arg_secret"], "env": {"DOCS_TOKEN": "tok_secret"}},
           "web": {"type": "http", "url": "https://mcp.example/x?token=url_secret",
                   "headers": {"Authorization": "Bearer hdr_secret"}}}


class TheMCPServers(unittest.TestCase):
    def test_the_servers_in_their_own_file(self):
        s = start({"mcp_servers": SERVERS})
        self.assertEqual(flag(s["argv"], "--mcp-config"), "/c/sessions/ab12.mcp.json")
        self.assertEqual(s["mcp"], {"file": "/c/sessions/ab12.mcp.json", "content": {"mcpServers": SERVERS}})
        self.assertNotIn("secret", json.dumps(s["argv"]))
        self.assertNotIn("--strict-mcp-config", s["argv"])

    def test_only_the_servers_given(self):
        s = start({"mcp_servers": SERVERS, "mcp_strict": True})
        self.assertIn("--strict-mcp-config", s["argv"])
        s = start({"mcp_strict": True})
        self.assertEqual(("--strict-mcp-config" in s["argv"], "--mcp-config" in s["argv"], s["mcp"]),
                         (True, False, None))

    def test_the_projects_own_config_is_read_unless_turned_off(self):
        self.assertNotIn("--setting-sources", start({})["argv"])
        self.assertEqual(flag(start({"project_config": False})["argv"], "--setting-sources"), "user")

    def test_the_log_shows_no_secret_of_a_server(self):
        s = start({"mcp_servers": SERVERS})
        text = json.dumps(plan.shown(s))
        for secret in ("tok_secret", "hdr_secret", "arg_secret", "url_secret"):
            self.assertNotIn(secret, text)
        self.assertNotIn("docs-server", text)
        self.assertNotIn("tok_secret", json.dumps(plan.kept(s)))
        self.assertEqual(plan.kept(s)["mcp"], {"file": "/c/sessions/ab12.mcp.json"})
        self.assertEqual(plan.shown(s)["mcp"]["content"]["mcpServers"]["web"]["type"], "http")
        self.assertEqual(plan.shown(s)["mcp"]["content"]["mcpServers"]["docs"]["env"]["DOCS_TOKEN"],
                         plan.fingerprint("tok_secret"))


class TheSessionsConfig(unittest.TestCase):
    def test_what_it_holds(self):
        s = start({"repo": "o/web", "model": "sonnet"}, args=("web", "--high"))
        self.assertEqual((s["id"], s["project"], s["folder"], s["repo"]), ("ab12", "web", "/h/web", "o/web"))
        self.assertEqual((s["config"]["model"], s["config"]["effort"]), ("sonnet", "high"))
        self.assertEqual(s["keys"], ["--high"])
        self.assertEqual(set(s), {"id", "project", "folder", "repo", "config", "keys", "env", "unset", "mcp", "argv"})

    def test_two_sessions_of_one_project(self):
        a, b = start(sid="aaaa"), start(sid="bbbb", args=("web", "--opus"))
        self.assertEqual((flag(a["argv"], "--model"), flag(b["argv"], "--model")), (None, "opus"))
        self.assertEqual(flag(b["argv"], "--name"), "web-bbbb")


class TheFingerprint(unittest.TestCase):
    def test_a_token_in_the_project_s_variables(self):
        s = start({"env": {"GH_TOKEN": "ghs_secret123", "OPENAI_API_KEY": "sk-zzz", "PLAIN": "seen"}})
        shown = plan.shown(s)
        text = json.dumps(shown)
        self.assertNotIn("ghs_secret123", text)
        self.assertNotIn("sk-zzz", text)
        self.assertEqual(shown["env"]["GH_TOKEN"], plan.fingerprint("ghs_secret123"))
        self.assertEqual(shown["config"]["env"]["OPENAI_API_KEY"], plan.fingerprint("sk-zzz"))
        self.assertRegex(shown["env"]["GH_TOKEN"], r"^sha256:[0-9a-f]{12}$")
        self.assertEqual(shown["env"]["PLAIN"], "seen")
        self.assertEqual(shown["argv"], s["argv"])
        self.assertEqual(s["env"]["GH_TOKEN"], "ghs_secret123")


if __name__ == "__main__":
    unittest.main()
