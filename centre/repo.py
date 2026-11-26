"""repo.py - the centre's settings in a GitHub repository: one file, centre.json, on the repository's default branch,
read and written through the gh command (gh holds its own sign-in; no token is read or kept here). The file holds the
machines (name, address, on, added), the groups and the links, never a key. Every call returns a dict and never
raises: {"ok": true, ...} or {"ok": false, "error": "short text"}."""
import base64, json, os, subprocess
import store

FILE = "centre.json"
FORMAT = 1
TIMEOUT = 20   # seconds for one gh call


def fail(text):
    return {"ok": False, "error": text}


def export(store_data):
    """the file's object from the store's machines, groups and settings: only the fields listed here are copied"""
    return {
        "format": FORMAT,
        "machines": [{"name": m["name"], "address": m["address"], "on": m["on"], "added": m["added"]}
                     for m in store_data["machines"]],
        "groups": [{"name": g["name"], "agents": list(g["agents"])} for g in store_data["groups"]],
        "links": {k: store_data["settings"].get(k, "") for k in store.LINK_FIELDS},
    }


def apply(target, data):
    """the file's object put into the store (target: a Store). All is checked first, so a wrong file changes nothing."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        return fail("the file is not a centre file of format %d" % FORMAT)
    try:
        machines = target.replace(data.get("machines"), data.get("groups"), data.get("links"))
    except store.Invalid as e:
        return fail(str(e))
    return {"ok": True, "machines": len(machines)}


def gh(args, stdin=None):
    """-> (stdout, None), or (None, the error text of gh). The command is CENTRE_GH when set (for tests), else gh."""
    cmd = os.environ.get("CENTRE_GH") or "gh"
    try:
        p = subprocess.run([cmd] + args, input=stdin, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        return None, "gh could not run: %s" % type(e).__name__
    if p.returncode != 0:
        return None, p.stderr.strip() or "gh failed"
    return p.stdout, None


def short(text):
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    return (lines[-1] if lines else "gh failed")[:200]


def path(repo):
    """the API path of the file in owner/name; store.Invalid when no repository or a wrong name"""
    if not repo:
        raise store.Invalid("no repository is set")
    return "repos/%s/contents/%s" % (store.check_repo(repo), FILE)


def contents(api_path):
    """-> (the object, None); (None, None) when the file is not there yet; (None, error text) on a gh failure"""
    out, err = gh(["api", api_path])
    if err is not None:
        return (None, None) if "HTTP 404" in err else (None, short(err))
    return json.loads(out), None


def save(repo, data):
    try:
        api_path = path(repo)
        current, err = contents(api_path)
        if err is not None:
            return fail(err)
        body = {"message": "Save the centre's settings",
                "content": base64.b64encode((json.dumps(data, indent=2) + "\n").encode("utf-8")).decode("ascii")}
        if current is not None:
            body["sha"] = current["sha"]
        out, err = gh(["api", "-X", "PUT", api_path, "--input", "-"], json.dumps(body))
        if err is not None:
            return fail(short(err))
        return {"ok": True, "repo": repo}
    except store.Invalid as e:
        return fail(str(e))
    except (ValueError, TypeError, KeyError, AttributeError):
        return fail("the repository answered in a form the centre does not read")


def load(repo):
    try:
        current, err = contents(path(repo))
        if err is not None:
            return fail(err)
        if current is None:
            return fail("the repository has no %s yet: save there first" % FILE)
        raw = base64.b64decode(current["content"]).decode("utf-8")
        return {"ok": True, "repo": repo, "data": json.loads(raw)}
    except store.Invalid as e:
        return fail(str(e))
    except (ValueError, TypeError, KeyError, AttributeError):
        return fail("the file in the repository is not a centre file")
