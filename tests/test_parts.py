"""test_parts.py - the parts of the kit (kit-parts): the imports of kit/ go one way, __main__ -> cli -> sessions and
machine -> plan and io -> old -> quoted -> config -> files, the plan reads no file and starts no process, and no file
of the core names a path under the parked folder.
    python3 -m unittest discover -s tests"""
import ast, os, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.join(ROOT, "kit")
# the rank of each part: a module may import a module of the kit of a lower rank only
RANKS = {"kit.__main__": 8, "kit.cli": 7, "kit.sessions": 6, "kit.machine": 6, "kit.engines": 5.5, "kit.plan": 5, "kit.io": 5,
         "kit.old": 4, "kit.quoted": 3, "kit.config": 2, "kit.files": 1}
# what the plan may import: no os, subprocess, pathlib, time, random or secrets
PLAN_MAY = {"json", "re", "hashlib", "dataclasses", "typing", "kit", "kit.config"}
# the folders of the core checked for the parked folder's name
CORE = ("kit", "tests", "install", "plugins", "agents", ".github")
PARKED = "parked" + "/"


def part(module):
    """the part of a module of the kit: kit.sessions.start is of kit.sessions"""
    for p in sorted(RANKS, key=len, reverse=True):
        if module == p or module.startswith(p + "."):
            return p
    return None


def modules():
    """each module of kit/: (its name, its file)"""
    for folder, _, files in os.walk(KIT):
        for f in sorted(files):
            if f.endswith(".py"):
                rel = os.path.relpath(os.path.join(folder, f), ROOT)[:-3].replace(os.sep, ".")
                yield (rel[:-9] if rel.endswith(".__init__") else rel), os.path.join(folder, f)


def imports(name, path):
    """the names a module imports, relative imports made absolute"""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    pkg = name if path.endswith("__init__.py") else name.rpartition(".")[0]
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                up = pkg.split(".")
                base = ".".join(up[:len(up) - node.level + 1] + ([base] if base else []))
            out.add(base)
            out.update(base + "." + a.name for a in node.names if (base + "." + a.name).startswith("kit."))
        elif isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("__import__", "exec", "eval"):
            out.add("<%s>" % node.func.id)
    return out


class TheParts(unittest.TestCase):
    def test_the_parts_depend_one_way(self):
        found = list(modules())
        self.assertTrue(found)
        for name, path in found:
            mine = part(name)
            if mine is None:
                continue
            for imp in imports(name, path):
                other = part(imp)
                if other is not None and other != mine:
                    self.assertLess(RANKS[other], RANKS[mine], "%s imports %s, against the order" % (name, imp))

    def test_the_plan_reads_no_file_and_starts_no_process(self):
        for imp in imports("kit.plan", os.path.join(KIT, "plan.py")):
            self.assertIn(imp, PLAN_MAY, "kit.plan imports %s" % imp)

    def test_an_engine_reads_no_file_and_starts_no_process(self):
        found = [(n, p) for n, p in modules() if part(n) == "kit.engines"]
        self.assertIn("kit.engines.claude", [n for n, _ in found])
        for name, path in found:
            for imp in imports(name, path):
                self.assertTrue(imp in PLAN_MAY or imp == "kit.plan" or part(imp) == "kit.engines",
                                "%s imports %s" % (name, imp))

    def test_the_test_finds_a_dependency_against_the_order(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "config.py")
            with open(p, "w") as f:
                f.write("from kit import plan\nimport os\n")
            self.assertIn("kit.plan", imports("kit.config", p))
            self.assertEqual(part("kit.sessions.start"), "kit.sessions")

    def test_no_core_file_names_the_parked_folder(self):
        for top in CORE:
            for folder, dirs, files in os.walk(os.path.join(ROOT, top)):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for f in files:
                    p = os.path.join(folder, f)
                    with open(p, encoding="utf-8", errors="replace") as fh:
                        for n, line in enumerate(fh, 1):
                            self.assertNotIn(PARKED, line, "%s:%d names the parked folder" %
                                             (os.path.relpath(p, ROOT), n))

class TheReference(unittest.TestCase):
    FIELDS = ("context_window", "compact_window", "idle_compact", "idle_compact_from", "cache_life",
              "subagent_cache_life", "subagent_model")

    def test_each_field_of_the_context_has_a_row_and_the_help_names_the_reference(self):
        """docs/context-cost.md says when to set each field of the window and the cache; the fields' table and
        kit help point to it"""
        from kit import cli
        self.assertIn("docs/context-cost.md", cli.USAGE)
        with open(os.path.join(ROOT, "docs", "context-cost.md"), encoding="utf-8") as f:
            reference = [line for line in f if line.startswith("| ")]
        with open(os.path.join(ROOT, "docs", "config.md"), encoding="utf-8") as f:
            table = f.read().split("\n")
        with open(os.path.join(KIT, "defaults.json"), encoding="utf-8") as f:
            defaults = f.read()
        for field in self.FIELDS:
            self.assertIn('"%s"' % field, defaults, field)
            self.assertEqual(len([r for r in reference if "the kit: `%s`" % field in r]), 1, field)
            row = [r for r in table if r.startswith("| `%s` | " % field)]
            self.assertEqual(len(row), 1, field)
            self.assertIn("docs/context-cost.md", row[0], field)

if __name__ == "__main__":
    unittest.main()
