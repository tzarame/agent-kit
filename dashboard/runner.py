"""runner.py - start and stop a session by calling the kit's command. It never types into a session and never
writes the kit's files. AGENT_KIT_KIT holds the command line of the kit (the tests give a fake one); with none,
kit/__main__.py of this repository is run."""
import os, shlex, subprocess, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = ("opus", "sonnet", "haiku", "fable")
EFFORTS = ("low", "medium", "high", "xhigh", "max")


def _kit():
    cmd = os.environ.get("AGENT_KIT_KIT")
    return shlex.split(cmd) if cmd else [sys.executable, "-I", os.path.join(REPO, "kit", "__main__.py")]


def call_kit(args):
    """The one place that calls the kit. With no terminal and no TMUX the kit starts a session and opens none."""
    env = dict(os.environ)
    env.pop("TMUX", None)
    try:
        r = subprocess.run(_kit() + args, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL,
                           env=env)
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "rc": None, "out": str(e)[-400:]}
    return {"ok": r.returncode == 0, "rc": r.returncode, "out": (r.stdout + r.stderr)[-400:]}


def start(project, model=None, effort=None):
    """a new session of the project; the model and the effort, when given, for this start only"""
    return call_kit(["start", project] + ["--" + k for k in (model, effort) if k])


def stop(sids):
    """stops each of the sessions; the answer of the first that failed, else of the last"""
    res = {"ok": True, "rc": 0, "out": ""}
    for sid in sids:
        res = call_kit(["kill", sid])
        if not res["ok"]:
            break
    return res
