"""incus.py - the centre's Incus: the machines made and run with Incus, reached over Incus's HTTPS REST API (version 1.0)
inside Tailscale. A FIRST VERSION, NOT YET TRIED ON A REAL INCUS SERVER: the shapes below are assumed from Incus's
documented API and have not been seen; every answer is read defensively (a missing field is "" or [], never a crash).

The client certificate and its key are files the owner puts on the centre machine, in ~/.config/agent-kit/centre/incus/:
client.crt and client.key (client.key: no access for the group or others), and optionally server.crt, the server's certificate, which is
trusted and pinned (the host name is not checked then, since Incus certificates are self-signed). Without server.crt the
server is checked against the system's authorities. Certificate checking is never turned off. The files' content never
leaves this module: files() says only whether each one is there.

Every request carries ?project=NAME: the settings' incus_project, "default" when empty. call() never raises: it returns
{"ok": true, "data": the answer's metadata} or {"ok": false, "error": "short text"}; an input refused before any request
also has "invalid": true. instances(), profiles() and images() return {"ok": true, "instances"|"profiles"|"images": [...]}.

Assumed shapes (Incus REST API 1.0, not checked against a server):
- a sync answer is {"type": "sync", "metadata": ...}; an error answer has "error": "text" and an HTTP status of 4xx or 5xx.
- start, stop and create answer with an async operation, {"type": "async", "metadata": {"id": ...}}. The operation is NOT
  waited for: its own result (a failed start, say) is not read in this version.
- GET /1.0/instances?recursion=1: a list of {name, status, type, profiles: [names]}.
- GET /1.0/profiles?recursion=1: a list of {name, description, config: {"cloud-init.user-data": text}}.
- GET /1.0/images?recursion=1: a list of {fingerprint, properties: {description}, aliases: [{name}]}; a description
  at the top level is read too.

Not in this version: deleting a machine (destructive, so left out on purpose), waiting for an operation, a retry of a
failed call (the owner starts it again), more than one project."""
import json, os, re, ssl, urllib.error, urllib.parse, urllib.request
import store

FOLDER = ("agent-kit", "centre", "incus")   # under the home: ~/.config/agent-kit/centre/incus
CLIENT_CRT, CLIENT_KEY, SERVER_CRT = "client.crt", "client.key", "server.crt"
DEFAULT_PROJECT = "default"
TIMEOUT = 15        # seconds for one request
STOP_TIMEOUT = 30   # seconds Incus gives a machine to start or stop
MAX_ANSWER = 4 * 1024 * 1024
ERR_MAX = 200
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}")
FINGERPRINT_RE = re.compile(r"[0-9a-f]{12,64}")
ALIAS_RE = re.compile(r"[A-Za-z0-9._/-]{1,100}")
NOT_SET = "Incus is not set: name its address in the settings"
OPEN = None   # the test hook: OPEN(request, context, timeout) -> the answer's bytes; None for the real one


class Failed(Exception):
    """a step that cannot be done; its text is the answer's error"""


def folder(home):
    return os.path.join(home, ".config", *FOLDER)


def files(home):
    """which certificate files are there: {name: bool}. Never their content."""
    d = folder(home)
    return {n: os.path.isfile(os.path.join(d, n)) for n in (CLIENT_CRT, CLIENT_KEY, SERVER_CRT)}


def ssl_context(home):
    """the TLS context: the client certificate, and the server checked against server.crt (pinned) or the system's
    authorities. Raises Failed. Certificate checking stays on (verify_mode is CERT_REQUIRED)."""
    d = folder(home)
    crt, key, server = (os.path.join(d, n) for n in (CLIENT_CRT, CLIENT_KEY, SERVER_CRT))
    if not os.path.isfile(crt) or not os.path.isfile(key):
        raise Failed("the client certificate and its key are not there: put client.crt and client.key in the centre's incus folder")
    if os.stat(key).st_mode & 0o077:
        raise Failed("client.key must give no access to the group or others (chmod 600)")
    pinned = os.path.isfile(server)
    try:
        ctx = ssl.create_default_context(cafile=server if pinned else None)
        if pinned:
            ctx.check_hostname = False   # the pinned certificate is the check: Incus's own is self-signed
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_cert_chain(crt, key)
    except (OSError, ssl.SSLError):
        raise Failed("the client certificate or its key could not be read")
    return ctx


def refused(text):
    return {"ok": False, "invalid": True, "error": text}


def name_refused(text, what):
    """None when the text is a machine or profile name; else the refusal"""
    if isinstance(text, str) and NAME_RE.fullmatch(text):
        return None
    return refused("%s: letters, digits and dash, not starting with a dash, up to 63 characters" % what)


def short(text):
    return (text or "").strip()[:ERR_MAX]


def _open(req, ctx, timeout):
    """the real request: no proxy from the environment (the address is inside Tailscale), the context given"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=ctx))
    with opener.open(req, timeout=timeout) as r:
        return r.read(MAX_ANSWER + 1)


def _http_error(e):
    """the server's error text when its answer has one, else the status"""
    try:
        obj = json.loads(e.read(65536).decode("utf-8"))
        text = obj.get("error") if isinstance(obj, dict) else None
    except (OSError, AttributeError, ValueError):
        text = None
    return short(text) if isinstance(text, str) and text.strip() else "Incus answered HTTP %d" % e.code


def call(home, settings, method, path, body=None):
    """one request to Incus: -> {"ok": true, "data": metadata} or {"ok": false, "error": text}. Never raises."""
    try:
        url = store.check_incus_url((settings or {}).get("incus_url"))
        project = store.check_incus_project((settings or {}).get("incus_project")) or DEFAULT_PROJECT
    except store.Invalid as e:
        return refused(short(str(e)))
    if not url:
        return refused(NOT_SET)
    try:
        ctx = ssl_context(home)
    except Failed as e:
        return {"ok": False, "error": short(str(e))}
    sep = "&" if "?" in path else "?"
    full = "%s%s%s%s" % (url, path, sep, urllib.parse.urlencode({"project": project}))
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(full, data=data, method=method,
                                 headers={"Accept": "application/json", "Content-Type": "application/json"})
    try:
        raw = (OPEN or _open)(req, ctx, TIMEOUT)
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": _http_error(e)}
    except OSError as e:
        return {"ok": False, "error": "Incus did not answer: %s" % type(e).__name__}
    if len(raw) > MAX_ANSWER:
        return {"ok": False, "error": "Incus answered with more than 4 MB"}
    try:
        obj = json.loads(raw.decode("utf-8")) if raw.strip() else {}
    except (UnicodeDecodeError, ValueError):
        obj = None
    if not isinstance(obj, dict):
        return {"ok": False, "error": "Incus answered in a form the centre does not read"}
    return {"ok": True, "data": obj.get("metadata")}


def listed(data):
    return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []


def text_of(x):
    return x if isinstance(x, str) else ""


def strings(x):
    return [s for s in x if isinstance(s, str)] if isinstance(x, list) else []


def instances(home, settings):
    got = call(home, settings, "GET", "/1.0/instances?recursion=1")
    if not got["ok"]:
        return got
    return {"ok": True, "instances": [{"name": text_of(i.get("name")), "status": text_of(i.get("status")),
                                       "type": text_of(i.get("type")), "profiles": strings(i.get("profiles"))}
                                      for i in listed(got["data"])]}


def profiles(home, settings):
    got = call(home, settings, "GET", "/1.0/profiles?recursion=1")
    if not got["ok"]:
        return got
    out = []
    for p in listed(got["data"]):
        config = p.get("config") if isinstance(p.get("config"), dict) else {}
        out.append({"name": text_of(p.get("name")), "description": text_of(p.get("description")),
                    "cloud_init": text_of(config.get("cloud-init.user-data"))})
    return {"ok": True, "profiles": out}


def images(home, settings):
    got = call(home, settings, "GET", "/1.0/images?recursion=1")
    if not got["ok"]:
        return got
    out = []
    for im in listed(got["data"]):
        props = im.get("properties") if isinstance(im.get("properties"), dict) else {}
        aliases = [a.get("name") if isinstance(a, dict) else a for a in (im.get("aliases") or []) if isinstance(a, (str, dict))]
        out.append({"fingerprint": text_of(im.get("fingerprint")),
                    "description": text_of(im.get("description")) or text_of(props.get("description")),
                    "aliases": [text_of(a) for a in aliases if text_of(a)]})
    return {"ok": True, "images": out}


def state(home, settings, name, action):
    """start or stop a machine: PUT /1.0/instances/NAME/state. The name is checked before any request."""
    bad = name_refused(name, "the machine name")
    if bad:
        return bad
    if action not in ("start", "stop"):
        return refused("the action is start or stop")
    return call(home, settings, "PUT", "/1.0/instances/%s/state" % name, {"action": action, "timeout": STOP_TIMEOUT})


def create(home, settings, name, profile, image):
    """make a machine from a profile and an image (a fingerprint, or an alias), and start it. Checked before any request.
    An alias with ".." or a leading "/" is refused too, on top of the pattern."""
    bad = name_refused(name, "the machine name") or name_refused(profile, "the profile name")
    if bad:
        return bad
    if isinstance(image, str) and FINGERPRINT_RE.fullmatch(image):
        source = {"type": "image", "fingerprint": image}
    elif isinstance(image, str) and ALIAS_RE.fullmatch(image) and ".." not in image and not image.startswith("/"):
        source = {"type": "image", "alias": image}
    else:
        return refused("the image: a fingerprint of 12 to 64 hex characters, or an alias")
    body = {"name": name, "profiles": [profile], "source": source, "start": True}
    return call(home, settings, "POST", "/1.0/instances", body)
