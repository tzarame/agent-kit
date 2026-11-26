"""run.py - kit run ID, which tmux runs: the session's config sessions/ID.json into the environment, then the
project's folder, then claude in place of the kit. Its command line has the ID only, nothing of the project."""
import os

from kit import config, plan
from kit.io import GIT_PAIR, why


def child_env(inherited, doc):
    """the environment of the session: the inherited one without the variables the kit leaves out (doc's unset) and,
    when the session has git's settings of its own (GIT_CONFIG_COUNT), without the inherited ones; then doc's env"""
    own_git = "GIT_CONFIG_COUNT" in doc["env"]
    env = {k: v for k, v in inherited.items() if k not in doc.get("unset", ())
           and not (own_git and (k == "GIT_CONFIG_COUNT" or k.startswith(GIT_PAIR)))}
    env.update(doc["env"])
    return env


def with_bin(env, home):
    """env with ~/.local/bin on its PATH, first, when it is not there: the set-up installs Claude Code and the other
    programs there, and a tmux server started over ssh or at boot has no profile's PATH"""
    local = os.path.join(home, ".local", "bin")
    path = [p for p in env.get("PATH", "/usr/local/bin:/usr/bin:/bin").split(":") if p]
    return env if local in path else dict(env, PATH=":".join([local] + path))


def _checked(doc, sid):
    """the session's config, when it is one of this ID: ValueError else"""
    if doc.get("id") != sid:
        raise ValueError("the file is the config of the session %r" % doc.get("id"))
    if not (isinstance(doc.get("argv"), list) and doc["argv"] and all(isinstance(a, str) for a in doc["argv"])):
        raise ValueError("argv: not a list of words")
    if not (isinstance(doc.get("env"), dict) and all(isinstance(v, str) for v in doc["env"].values())):
        raise ValueError("env: not an object of strings")
    if not isinstance(doc.get("folder"), str):
        raise ValueError("folder: not a path")
    return doc


def run(io, args):
    if len(args) != 1 or not plan.ID.fullmatch(args[0]):
        io.err.write("kit run: needs the ID of a session, four of a-z and 0-9; tmux runs it, kit start starts a "
                     "session\n")
        return 2
    sid = args[0]
    try:
        doc = _checked(config.read_json(io.session_file(sid)), sid)
        env = with_bin(child_env(io.environ, doc), io.home)
        io.chdir(doc["folder"])
        io.exec(doc["argv"], env)
    except (config.ConfigError, OSError, ValueError) as e:
        io.err.write("kit run %s: %s\n" % (sid, why(e)))
        if io.tty():
            io.err.write("press Enter to close the window\n")
            io.wait()
        return 1
    return 0
