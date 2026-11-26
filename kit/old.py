"""old.py - the old kit's files of a project, written by bash: projects/NAME.env and the profiles of profiles/. The
first start of a project with no entry reads one into the entry, once; the files are kept as they are. Standard
library only."""
import os

from kit import config, quoted

# the old file gives the window, the environment and the autostart. The model and the effort (MODEL, EFFORT, SUBM,
# SUBE) are not read, as the release's defaults are Claude Code's own (agents); the fields of parked parts
# (SUBS, SUBTXT, TOOLS, ROLE, MODE, ADDONS, LAUNCH, DASHBOARD, FRESH, LABEL) are left out
OLD_YES = {"AUTOSTART": "autostart"}               # yes or no in the old file, true or false here


def old_entry(values, folder):
    """the entry of a project from the values of its old file: the folder and the fields the old file gives"""
    entry = {"folder": folder}
    for k, field in OLD_YES.items():
        if values.get(k) in ("yes", "no"):
            entry[field] = values[k] == "yes"
    win = values.get("WIN", "")
    if win not in ("", "default"):
        n = win[:-1] + "000" if win[-1:] in ("k", "K") else win
        if not n.isdigit():
            raise ValueError("WIN=%s is not a number of tokens" % win)
        entry["context_window"] = int(n)
    env = {}
    for line in values.get("ENVS", "").split("\n"):
        if line.strip():
            k, eq, v = line.partition("=")
            if not eq or not config.ENV_NAME.fullmatch(k):
                raise ValueError("ENVS: %r is not KEY=VALUE" % line)
            env[k] = v
    if env:
        entry["env"] = env
    return entry


def _old_values(path):
    try:
        with open(path, encoding="utf-8") as f:
            return quoted.parse_q(f.read())
    except (OSError, UnicodeDecodeError) as e:
        raise config.ConfigError("%s: %s" % (path, getattr(e, "strerror", None) or "not UTF-8 text"))
    except ValueError as e:
        raise config.ConfigError("%s: %s" % (path, e))


def read_old(conf_dir, name, folder):
    """the entry of the project from its old file: projects/NAME.env, else the profile of profiles/ whose DIR is the
    folder (the one named NAME when several are). None when there is none. The old files are kept as they are"""
    old = os.path.join(conf_dir, "projects", name + ".env")
    path = old if os.path.isfile(old) else None
    if path is None:
        hits = []
        pdir = os.path.join(conf_dir, "profiles")
        for f in sorted(os.listdir(pdir)) if os.path.isdir(pdir) else []:
            p = os.path.join(pdir, f)
            if f.endswith(".env") and os.path.isfile(p):
                v = _old_values(p)
                if v.get("DIR") and os.path.realpath(v["DIR"]) == os.path.realpath(folder):
                    hits.append((v.get("NAME") == name, p))
        named = [p for is_name, p in hits if is_name]
        path = named[0] if named else (hits[0][1] if len(hits) == 1 else None)
    if path is None:
        return None
    try:
        entry = old_entry(_old_values(path), folder)
    except ValueError as e:
        raise config.ConfigError("%s: %s" % (path, e))
    config.entry_fields(entry, path)
    return entry
