"""remote.py - the one place that calls a dashboard: call(machine, method, path, body) -> (status, JSON). Only paths
under /api/v1/ go out, and no scheme, no host, no "..". The machine's key goes in its Authorization header and
nowhere else. A machine that does not answer gives (502, {"error": ...}), never an exception."""
import http.client, json, re
from urllib.error import HTTPError, URLError
from urllib.parse import unquote
from urllib.request import ProxyHandler, Request, build_opener

TIMEOUT = 10
SLOW_TIMEOUT = 120          # an agent's start, stop, restart
SLOW = re.compile(r"/api/v1/agents/[a-z0-9]{4}/(start|stop|restart)")
METHODS = ("GET", "POST", "PUT", "DELETE")
MAX_ANSWER = 4 * 1024 * 1024
OPENER = build_opener(ProxyHandler({}))


def check_path(path):
    """None when the path may go out, else the reason"""
    if not isinstance(path, str):
        return "the path is text"
    base, _, query = path.partition("?")
    if not re.fullmatch(r"/api/v1(?:/[A-Za-z0-9._~%-]+)*/?", base):
        return "only paths of the API, under /api/v1/"
    if any(unquote(seg) in (".", "..") for seg in base.split("/")):
        return "no . or .. in the path"
    if query and not re.fullmatch(r"[^\s#]*", query):
        return "the query has a space or a #"
    return None


def call(machine, method, path, body=None):
    """machine: {"name", "address", "key" (optional)}. body: a JSON value or None. -> (status, JSON value)."""
    name = machine.get("name", "")
    if method not in METHODS:
        return 400, {"error": "no such method: %s" % method}
    bad = check_path(path)
    if bad:
        return 400, {"error": bad}
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if machine.get("key"):
        headers["Authorization"] = "Bearer " + machine["key"]
    base = path.partition("?")[0]
    timeout = SLOW_TIMEOUT if SLOW.fullmatch(base) else TIMEOUT
    req = Request(machine["address"].rstrip("/") + path, data=data, method=method, headers=headers)
    try:
        with OPENER.open(req, timeout=timeout) as r:
            status, raw = r.status, r.read(MAX_ANSWER)
    except HTTPError as e:
        status, raw = e.code, e.read(MAX_ANSWER)
    except (URLError, OSError, http.client.HTTPException) as e:
        reason = getattr(e, "reason", None) or e
        return 502, {"error": "machine %s does not answer: %s" % (name, reason)}
    try:
        return status, json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return 502, {"error": "machine %s answered with no JSON" % name}
