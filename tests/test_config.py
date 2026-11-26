"""test_config.py - kit/config.py: the defaults, the user's file over them, the checks, the copy and the write, the old
files. Each test works in a folder of its own; no file of the machine is read or written.
    python3 -m unittest discover -s tests"""
import hashlib, json, os, stat, tempfile, unittest

from kit import config, old, quoted
from kit.config import ConfigError


class Folder(unittest.TestCase):
    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.dir = self._t.name
        self.path = os.path.join(self.dir, "agent-kit", "config.json")

    def tearDown(self):
        self._t.cleanup()

    def put(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def user(self, doc):
        return self.put(self.path, json.dumps(doc))

    def fields(self, doc, name="web"):
        user, kit = config.read(self.user(doc))
        return config.session(kit, user, name)


class TheDefaults(unittest.TestCase):
    def test_the_defaults_have_each_field_and_no_other(self):
        kit = config.defaults()
        self.assertEqual(set(kit), {"version", "user", "session", "agents", "projects"})
        self.assertEqual(set(kit["session"]), set(config.SESSION))
        self.assertEqual(set(kit["user"]), set(config.USER))
        self.assertEqual((kit["agents"], kit["projects"]), ({}, {}))

    def test_the_defaults_of_config_md(self):
        """the release's defaults are Claude Code's own: no model, effort, window, agent or prompt of the kit"""
        s = config.defaults()["session"]
        self.assertEqual((s["model"], s["effort"], s["subagent_model"], s["subagent_effort"]), (None,) * 4)
        self.assertEqual((s["context_window"], s["compact_window"]), (None, None))
        self.assertEqual((s["advisor"], s["permission_mode"], s["prompt_suggestions"], s["remote_control"]),
                         ("off", "auto", False, True))
        self.assertEqual((s["claude_ai_skills"], s["claude_ai_plugins"], s["claude_ai_connectors"]),
                         (False, False, False))
        self.assertEqual((s["env"], s["plugins"], s["output_style"], s["fallback_model"]), ({}, [], None, None))
        self.assertEqual((s["agent"], s["system_prompt"], s["system_prompt_append"]), (None, None, None))
        self.assertEqual((s["tools"], s["mcp_servers"], s["mcp_strict"]), (None, {}, False))
        self.assertEqual((s["bundled_skills"], s["bundled_skills_off"]), (True, []))
        self.assertEqual((s["name_prefix"], s["name_postfix"]), (None, None))
        self.assertIs(config.defaults()["user"]["claude_ai_connectors"], False)


class TheFirstConfig(Folder):
    def test_no_config_yet(self):
        self.assertTrue(config.first_config(self.path))
        with open(self.path, "rb") as a, open(config.DEFAULTS, "rb") as b:
            self.assertEqual(a.read(), b.read())
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["config.json"])

    def test_a_config_of_the_user_is_not_copied_over(self):
        self.user({"session": {"model": "sonnet"}})
        before = os.stat(self.path)
        self.assertFalse(config.first_config(self.path))
        self.assertEqual(os.stat(self.path).st_mtime_ns, before.st_mtime_ns)
        user, kit = config.read(self.path)
        self.assertEqual(config.session(kit, user, "web")["model"], "sonnet")

    def test_a_field_of_a_later_release(self):
        f = self.fields({"session": {"model": "sonnet"}})
        self.assertEqual(f["fallback_model"], None)
        self.assertEqual(f["tools"], None)
        with open(self.path) as fh:
            self.assertEqual(json.load(fh), {"session": {"model": "sonnet"}})


class TheChecks(Folder):
    def refused(self, doc_or_text, *words):
        if isinstance(doc_or_text, str):
            self.put(self.path, doc_or_text)
        else:
            self.user(doc_or_text)
        with open(self.path, "rb") as f:
            before = f.read()
        with self.assertRaises(ConfigError) as e:
            config.read(self.path)
        for w in (self.path,) + words:
            self.assertIn(w, str(e.exception))
        with open(self.path, "rb") as f:
            self.assertEqual(f.read(), before)
        return str(e.exception)

    def test_a_broken_file(self):
        self.refused('{"session": {"model": "sonnet",}}', "line 1, column 31")

    def test_a_field_the_kit_does_not_know(self):
        self.refused({"projects": {"web": {"folder": "/w", "modle": "opus"}}}, "projects.web.modle")
        self.refused({"sessions": {}}, "sessions")

    def test_a_window_that_is_not_a_number(self):
        self.refused({"projects": {"web": {"folder": "/w", "context_window": "big"}}}, "context_window", "big")

    def test_a_folder_is_a_path_from_the_root_or_the_home(self):
        for bad in ("src/web", "./web", "~web", "", 5):
            self.refused({"projects": {"web": {"folder": bad}}}, "projects.web.folder", "a path from / or ~/")
        for good in ("/w", "~", "~/src/web"):
            self.user({"projects": {"web": {"folder": good}}})
            self.assertEqual(config.read(self.path)[0]["projects"]["web"]["folder"], good)

    def test_a_window_is_a_whole_number_of_at_most_8_digits(self):
        for bad in (True, 1.5, 0, -1, 100000000):
            self.refused({"session": {"context_window": bad}}, "context_window")
        self.assertEqual(self.fields({"session": {"context_window": 99999999}})["context_window"], 99999999)

    def test_a_window_by_the_model(self):
        for bad in ({}, {"haiku": "big"}, {"haiku": 0}, {"a b": 1000}, [113000]):
            self.refused({"session": {"context_window": bad}}, "context_window")
        w = {"haiku": 113000, "opus": None, "*": 200000}
        self.assertEqual(self.fields({"session": {"context_window": w}})["context_window"], w)

    def test_both_windows(self):
        self.refused({"projects": {"web": {"folder": "/w", "context_window": 132000, "compact_window": 200000}}},
                     "context_window", "compact_window")

    def test_a_model_with_a_space_or_a_quote(self):
        self.refused({"projects": {"web": {"folder": "/w", "model": "opus x"}}}, "model", '"opus x"')
        self.refused({"session": {"effort": "lo'w"}}, "effort")

    def test_other_values_not_allowed(self):
        self.refused({"session": {"output_style": "a\"b"}}, "output_style")
        self.refused({"session": {"permission_mode": "yolo"}}, "permission_mode")
        self.refused({"session": {"engine": "nobody"}}, "engine")      # an engine the kit has no module for
        self.assertEqual(config.defaults()["session"]["engine"], "claude")
        self.refused({"session": {"env": {"A B": "x"}}}, "env")
        self.refused({"projects": {"web": {"folder": "/w", "repo": "nope"}}}, "repo")
        self.refused({"projects": {"web": {"model": "opus"}}}, "projects.web", "folder")
        self.refused({"projects": {"-web": {"folder": "/w"}}}, "-web")

    def test_the_fields_of_a_prompt_and_the_tools(self):
        for bad in ("prompt.md", "kit", "claude"):
            self.refused({"version": 2, "session": {"system_prompt": bad}}, "system_prompt", "a path from / or ~/")
        self.refused({"session": {"system_prompt_append": "kit"}}, "system_prompt_append")
        self.refused({"session": {"tools": "Read,Bash"}}, "tools")
        self.refused({"session": {"mcp_servers": {"docs": "npx docs"}}}, "mcp_servers")
        self.refused({"session": {"bundled_skills_off": ["a b"]}}, "bundled_skills_off")
        self.refused({"session": {"name_prefix": "my name"}}, "name_prefix")
        good = {"system_prompt": "~/prompts/kit.md", "system_prompt_append": "/p/more.md", "tools": ["Read", "Bash"],
                "mcp_servers": {"docs": {"command": "docs-server", "env": {"TOKEN": "x"}}}, "mcp_strict": True,
                "bundled_skills": False, "bundled_skills_off": ["simplify"], "name_prefix": "my",
                "name_postfix": "a1"}
        f = self.fields({"version": 2, "session": good})
        self.assertEqual({k: f[k] for k in good}, good)

    def test_an_agent(self):
        self.refused({"agents": []}, "agents")
        self.refused({"agents": {"-x": {}}}, "agents.-x")
        self.refused({"agents": {"cheap": {"modle": "haiku"}}}, "agents.cheap.modle")
        self.refused({"agents": {"cheap": {"folder": "/w"}}}, "agents.cheap.folder")
        self.refused({"agents": {"cheap": {"role": "role.md"}}}, "agents.cheap.role")
        self.refused({"version": 3, "profiles": {}}, "profiles")
        self.refused({"version": 3, "projects": {"web": {"folder": "/w", "profile": "cheap"}}},
                     "projects.web.profile")
        user, _ = config.read(self.user({"agents": {"cheap": {"model": "haiku", "role": "~/r.md"}},
                                         "projects": {"web": {"folder": "/w", "agent": "cheap"}}}))
        self.assertEqual(config.agent(user, "cheap"), {"model": "haiku", "role": "~/r.md", "agent": "cheap"})
        with self.assertRaises(ConfigError) as e:
            config.agent(user, "fast", {}.get, ["dev"])
        self.assertIn("cheap", str(e.exception))

    def test_a_key_given_twice(self):
        self.refused('{"session": {"model": "opus", "model": "haiku"}}', "model")


class TheLayers(Folder):
    def test_a_project_with_only_its_folder(self):
        f = self.fields({"projects": {"web": {"folder": "/w"}}})
        kit = config.defaults()["session"]
        self.assertEqual(f, kit)

    def test_a_project_over_the_user_over_the_defaults(self):
        f = self.fields({"session": {"model": "sonnet", "effort": "high"},
                         "projects": {"web": {"folder": "/w", "model": "opus"}}})
        self.assertEqual((f["model"], f["effort"]), ("opus", "high"))

    def test_a_window_of_a_layer_drops_the_other(self):
        f = self.fields({"projects": {"web": {"folder": "/w", "compact_window": 200000}}})
        self.assertEqual((f["context_window"], f["compact_window"]), (None, 200000))
        f = self.fields({"session": {"compact_window": 200000}, "projects": {"web": {"folder": "/w",
                                                                                     "context_window": 132000}}})
        self.assertEqual((f["context_window"], f["compact_window"]), (132000, None))
        f = self.fields({"projects": {"web": {"folder": "/w", "context_window": None}}})
        self.assertEqual((f["context_window"], f["compact_window"]), (None, None))

    def test_env_is_merged_by_the_name(self):
        f = self.fields({"session": {"env": {"A": "1", "B": "2"}},
                         "projects": {"web": {"folder": "/w", "env": {"B": "3", "C": "4"}}}})
        self.assertEqual(f["env"], {"A": "1", "B": "3", "C": "4"})

    def test_another_project_does_not_count(self):
        f = self.fields({"projects": {"api": {"folder": "/a", "model": "opus"}}}, "web")
        self.assertEqual(f["model"], None)


class TheWrite(Folder):
    def test_a_first_start_of_a_folder(self):
        config.first_config(self.path)
        self.assertEqual(config.add_project(self.path, "web", {"folder": "/root/web"}), {"folder": "/root/web"})
        user, _ = config.read(self.path)
        self.assertEqual(user["projects"], {"web": {"folder": "/root/web"}})
        self.assertEqual(user["session"], config.defaults()["session"])
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["config.json"])

    def test_an_entry_already_there_is_kept(self):
        self.user({"projects": {"web": {"folder": "/w", "model": "opus"}}})
        self.assertEqual(config.add_project(self.path, "web", {"folder": "/x"}), {"folder": "/w", "model": "opus"})

    def test_a_broken_file_is_not_written(self):
        self.put(self.path, "{")
        with self.assertRaises(ConfigError):
            config.add_project(self.path, "web", {"folder": "/w"})
        with open(self.path) as f:
            self.assertEqual(f.read(), "{")


# a release of version 2 for the tests: the model's default changed, a field renamed and one dropped
STEPS = ((2, (("default", "session.model", "haiku", "sonnet"),
              ("default", "session.context_window", {"haiku": 113000, "*": 200000}, {"*": 180000}),
              ("rename", "session.effort", "effort_level"),
              ("drop", "user.claude_ai_connectors"))),)


class TheMigration(Folder):
    def kit(self, version=2):
        return {"version": version, "user": {}, "session": {}, "projects": {}}

    def test_a_default_the_user_kept_takes_the_new_one(self):
        doc = {"version": 1, "session": {"model": "haiku", "context_window": {"*": 200000, "haiku": 113000}}}
        new, done = config.migrate(doc, self.kit(), STEPS)
        self.assertEqual(new, {"version": 2, "session": {"model": "sonnet", "context_window": {"*": 180000}}})
        self.assertEqual(done[0], {"version": 1, "to": 2})
        self.assertIn({"set": "session.model", "from": "haiku", "to": "sonnet"}, done)
        self.assertEqual(doc["session"]["model"], "haiku")

    def test_a_value_the_user_changed_is_kept(self):
        doc = {"session": {"model": "opus", "context_window": 132000}, "projects": {"web": {"folder": "/w",
                                                                                          "model": "haiku"}}}
        new, done = config.migrate(doc, self.kit(), STEPS)
        self.assertEqual(new["session"], {"model": "opus", "context_window": 132000})
        self.assertEqual(new["projects"]["web"]["model"], "haiku")
        self.assertEqual(done, [{"version": 1, "to": 2}])

    def test_a_rename_and_a_drop_reach_the_projects(self):
        doc = {"version": 1, "user": {"claude_ai_connectors": True}, "session": {"effort": "high"},
               "projects": {"web": {"folder": "/w", "effort": "max"}}}
        new, done = config.migrate(doc, self.kit(), STEPS)
        self.assertEqual(new, {"version": 2, "user": {}, "session": {"effort_level": "high"},
                               "projects": {"web": {"folder": "/w", "effort_level": "max"}}})
        self.assertIn({"rename": "projects.web.effort", "to": "effort_level"}, done)
        self.assertIn({"drop": "user.claude_ai_connectors", "value": True}, done)

    def test_true_is_not_1(self):
        new, done = config.migrate({"session": {"x": True}}, self.kit(),
                                   ((2, (("default", "session.x", 1, 2),)),))
        self.assertEqual((new["session"], len(done)), ({"x": True}, 1))

    def test_a_copy_of_the_kit_s_version_or_later_is_left(self):
        for doc in ({"version": 2, "session": {"model": "haiku"}}, {"version": 3}, {"version": "2"}):
            self.assertEqual(config.migrate(doc, self.kit(), STEPS), (doc, []))
        self.assertEqual(config.migrate({"session": {"model": "haiku"}}, self.kit(1), STEPS)[1], [])

    def test_upgrade_keeps_the_old_file(self):
        self.user({"session": {"model": "haiku"}})
        with open(self.path, "rb") as f:
            before = f.read()
        done = config.upgrade(self.path, self.kit(), STEPS)
        self.assertEqual(len(done), 2)
        with open(self.path + ".v1", "rb") as f:
            self.assertEqual(f.read(), before)
        with open(self.path) as f:
            self.assertEqual(json.load(f), {"version": 2, "session": {"model": "sonnet"}})
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertEqual(config.upgrade(self.path, self.kit(), STEPS), [])
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.path))), ["config.json", "config.json.v1"])

    def test_a_kept_file_already_there_stays(self):
        self.put(self.path + ".v1", "older")
        self.user({"session": {"model": "haiku"}})
        config.upgrade(self.path, self.kit(), STEPS)
        with open(self.path + ".v1") as f:
            self.assertEqual(f.read(), "older")

    def test_a_migration_check_refuses_is_not_written(self):
        self.user({"session": {"model": "haiku"}})
        with self.assertRaises(ConfigError):
            config.upgrade(self.path, self.kit(), ((2, (("rename", "session.model", "modle"),)),))
        self.assertEqual(os.listdir(os.path.dirname(self.path)), ["config.json"])

    def test_read_brings_the_copy_to_the_version_but_not_the_file(self):
        self.user({"version": 1, "session": {"model": "haiku"}})
        self.assertEqual(config.read(self.path)[0]["version"], config.defaults()["version"])
        self.assertEqual(config.read(self.path)[0]["session"], {"model": None})
        with open(self.path) as f:
            self.assertEqual(json.load(f)["version"], 1)
        with self.assertRaises(ConfigError):
            self.user({"version": 0})
            config.read(self.path)

    def test_the_profiles_become_agents(self):
        doc = {"version": 2, "profiles": {"kit": {"agent": "dev", "model": "opus"}, "cheap": {"model": "haiku"},
                                          "big": {"compact_window": 100000}},
               "projects": {"a": {"folder": "/a", "profile": "kit"},
                            "b": {"folder": "/b", "profile": "cheap", "agent": "qa", "model": "opus",
                                  "context_window": 132000},
                            "c": {"folder": "/c", "profile": "kit", "agent": "qa"},
                            "d": {"folder": "/d", "profile": None, "agent": "qa"},
                            "e": {"folder": "/e", "profile": "big", "agent": "qa", "context_window": 132000}}}
        new, done = config.migrate(doc, config.defaults(), config.MIGRATIONS)
        self.assertEqual(new, {
            "version": 3,
            "agents": {"kit": {"agent": "dev", "model": "opus"}, "cheap": {"model": "haiku"},
                       "big": {"compact_window": 100000}},
            "projects": {"a": {"folder": "/a", "agent": "kit"},
                         "b": {"folder": "/b", "agent": "qa", "model": "haiku", "context_window": 132000},
                         "c": {"folder": "/c", "agent": "kit"},
                         "d": {"folder": "/d", "agent": "qa"},
                         "e": {"folder": "/e", "agent": "qa", "compact_window": 100000}}})
        config.check(new, "config.json")
        self.assertIn({"rename": "profiles.kit", "to": "agents.kit"}, done)
        self.assertIn({"rename": "projects.a.profile", "to": "agent", "value": "kit"}, done)
        self.assertIn({"put": "profiles.cheap", "into": "projects.b"}, done)
        self.assertEqual(config.migrate({"version": 2}, config.defaults(), config.MIGRATIONS)[0], {"version": 3})

    def test_the_kit_s_migrations(self):
        """each change is known, the last version is the defaults', and a default changed last is the defaults'"""
        kit, last = config.defaults(), {}
        self.assertEqual(kit["version"], max([1] + [to for to, _ in config.MIGRATIONS]))
        self.assertEqual([to for to, _ in config.MIGRATIONS], sorted({to for to, _ in config.MIGRATIONS}))
        for to, changes in config.MIGRATIONS:
            for step in changes:
                self.assertIn(step[0], ("default", "rename", "drop", "agents"))
                if step[0] == "default":
                    last[step[1]] = step[3]
        for place, value in last.items():
            group, _, field = place.partition(".")
            self.assertEqual(kit[group][field], value, place)

    def test_a_change_of_the_defaults_has_a_new_version(self):
        """the defaults of each version, by their hash: a stop before a release changes a default without a
        migration"""
        kit = config.defaults()
        h = hashlib.sha256(json.dumps(kit, sort_keys=True).encode()).hexdigest()[:16]
        self.assertEqual(DEFAULTS_HASH.get(kit["version"]), h,
                         "kit/defaults.json changed (its hash is %s). A changed default, a renamed or dropped field: "
                         "a new version, its steps in config.MIGRATIONS, its hash here. A new field only: this "
                         "version's hash here" % h)


# the version of kit/defaults.json: the hash of its fields
DEFAULTS_HASH = {1: "87c312ac4dc180a7", 2: "f78654f308e48d42", 3: "aa78e1d10c8ef2ca"}


class TheOldFiles(Folder):
    def test_printf_q_forms(self):
        self.assertEqual(quoted.parse_q(r"A=a\ b B='x y' C=$'1\n2\t\x41\101\'' D= E=c\'d"),
                         {"A": "a b", "B": "x y", "C": "1\n2\tAA'", "D": "", "E": "c'd"})
        self.assertEqual(quoted.parse_q("ID=ab12\nNAME=web\nDIR=/h/web\n"),
                         {"ID": "ab12", "NAME": "web", "DIR": "/h/web"})
        for bad in ("A=$(id)", "A=`id`", "A=x;id", "nokey", "A='open"):
            with self.assertRaises(ValueError):
                quoted.parse_q(bad)

    def test_an_old_project_file(self):
        conf = os.path.join(self.dir, "agent-kit")
        was = self.put(os.path.join(conf, "projects", "web.env"),
                       "MODEL=sonnet EFFORT=high SUBM=haiku SUBE=low WIN=400k SUBS=manual SUBTXT='' "
                       "ENVS=$'GH_TOKEN=abc\\nX=1' TOOLS=Bash\\,Read ROLE=development\n")
        e = old.read_old(conf, "web", "/h/web")
        self.assertEqual(e, {"folder": "/h/web", "context_window": 400000, "env": {"GH_TOKEN": "abc", "X": "1"}})
        self.assertTrue(os.path.isfile(was))

    def test_an_old_window_by_default(self):
        conf = os.path.join(self.dir, "agent-kit")
        for win in ("''", "default"):
            self.put(os.path.join(conf, "projects", "web.env"), "MODEL=opus WIN=%s\n" % win)
            self.assertEqual(old.read_old(conf, "web", "/h/web"), {"folder": "/h/web"})

    def test_a_profile_with_that_folder(self):
        conf = os.path.join(self.dir, "agent-kit")
        folder = os.path.join(self.dir, "web")
        os.makedirs(folder)
        self.put(os.path.join(conf, "profiles", "zz99.env"), "ID=zz99\nNAME=other\nDIR=/elsewhere\nMODEL=opus\n")
        self.put(os.path.join(conf, "profiles", "ab12.env"),
                 "ID=ab12\nNAME=web\nDIR=%s\nROLE=bare\nMODE=qa\nMODEL=sonnet\nLAUNCH=code-server\n" % folder)
        self.assertEqual(old.read_old(conf, "web", folder), {"folder": folder})

    def test_the_old_autostart(self):
        conf = os.path.join(self.dir, "agent-kit")
        for value, field in (("yes", {"autostart": True}), ("no", {"autostart": False}), ("''", {}), ("maybe", {})):
            self.put(os.path.join(conf, "projects", "web.env"), "MODEL=opus AUTOSTART=%s\n" % value)
            self.assertEqual(old.read_old(conf, "web", "/h/web"), dict({"folder": "/h/web"}, **field))

    def test_no_old_file(self):
        self.assertIsNone(old.read_old(os.path.join(self.dir, "agent-kit"), "web", "/h/web"))

    def test_an_old_file_with_a_value_not_allowed(self):
        conf = os.path.join(self.dir, "agent-kit")
        p = self.put(os.path.join(conf, "projects", "web.env"), "WIN=$'a b'\n")
        with self.assertRaises(ConfigError) as e:
            old.read_old(conf, "web", "/h/web")
        self.assertIn(p, str(e.exception))
        self.assertIn("WIN", str(e.exception))


if __name__ == "__main__":
    unittest.main()
