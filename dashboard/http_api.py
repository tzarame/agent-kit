"""http_api.py - the routes of /api/v1 and the page, JSON in and out. No logic of its own: each route calls one
module (projects, runner, tmuxs, machine, context, notes, console, terminal, files, telemetry). Every path but hello
goes through access.decide first."""
import json, os, re, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

import access, analyst, analyst_ask, console, context, costs, files, langfuse_costs, machine, notes, projects, runner, telemetry, terminal, tmuxs

API = "/api/v1"
MAX_BODY = 1024 * 1024
FILE_STATUS = {"outside": 403, "missing": 404, "changed": 409, "exists": 409, "too_large": 413, "binary": 415,
               "not_file": 400}
DAY = 86400
COSTS_DEFAULT = 7 * DAY    # the period when since is not given
COSTS_MAX = 366 * DAY      # the longest period a costs query may ask for
NAME = r"([A-Za-z0-9_][A-Za-z0-9._-]{0,63})"   # an agent is a project of the kit, by its name
ROUTES = [
    ("GET", r"/state", "r_state"),
    ("POST", r"/agents/" + NAME + r"/(start|stop|restart)", "r_agent"),
    ("POST", r"/sessions/([a-z0-9]{4})/stop", "r_session_stop"),
    ("DELETE", r"/tmux/([^/]+)", "r_tmux_close"),
    ("GET", r"/notes/" + NAME, "r_notes_read"),
    ("PUT", r"/notes/" + NAME, "r_notes_write"),
    ("GET", r"/agents/" + NAME + r"/console", "r_console"),
    ("GET", r"/terminal", "r_terminal_list"),
    ("POST", r"/terminal", "r_terminal_open"),
    ("GET", r"/terminal/(term-[a-z0-9]{4})", "r_terminal_screen"),
    ("POST", r"/terminal/(term-[a-z0-9]{4})", "r_terminal_send"),
    ("DELETE", r"/terminal/(term-[a-z0-9]{4})", "r_terminal_close"),
    ("GET", r"/agents/" + NAME + r"/files", "r_files_read"),
    ("PUT", r"/agents/" + NAME + r"/files", "r_files_write"),
    ("GET", r"/telemetry", "r_telemetry"),
    ("PUT", r"/telemetry", "r_telemetry_install"),
    ("DELETE", r"/telemetry", "r_telemetry_remove"),
    ("POST", r"/telemetry/check", "r_telemetry_check"),
    ("GET", r"/telemetry/arrives", "r_telemetry_arrives"),
    ("GET", r"/costs", "r_costs"),
    ("GET", r"/analyst", "r_analyst"),
]


class BadBody(ValueError):
    pass


def _folder_name(path):
    """The name of an agent's folder under ~/.claude/projects (as context.py makes it)."""
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(path))


def _object(body):
    try:
        data = json.loads(body.decode("utf-8") or "null")
    except (UnicodeDecodeError, ValueError):
        raise BadBody("the body is not JSON")
    if not isinstance(data, dict):
        raise BadBody("the body is not a JSON object")
    return data


def _params(query):
    """the name=value pairs of a query string, the first of each name, percent-decoded once; {} when there are none"""
    out = {}
    for part in query.split("&"):
        name, _, value = part.partition("=")
        if name and name not in out:
            out[name] = unquote(value)
    return out


def _files_path(query):
    """the path= of a query string; "" when there is none"""
    return _params(query).get("path", "")


def _seconds(text, default):
    """a UNIX time given as whole seconds; the default when it is not given. ValueError when it is not one."""
    if text is None:
        return default
    if not re.fullmatch(r"[0-9]{1,12}", text):
        raise ValueError("since and until: whole seconds since 1970")
    return int(text)


class Api:
    """What the routes need: the home folder, the key, the settings (port, centres, home_dir), the version, the page."""

    def __init__(self, home, key, cfg, version, page):
        self.key, self.cfg, self.version, self.page = key, cfg, version, page
        self.tailnet = access.Tailnet()
        self.root = os.environ.get("AGENT_KIT_ROOT") or home
        self.home = home

    def access_settings(self):
        return {"port": self.cfg["port"], "centres": self.cfg["centres"], "key": self.key}

    def hello(self):
        return {"kind": "dashboard", "machine": machine.name(), "version": self.version, "api": 1}

    def dispatch(self, method, path, body, query=""):
        """-> (status, object). path is the part after /api/v1."""
        for m, pattern, fn in ROUTES:
            found = re.fullmatch(pattern, path) if m == method else None
            if found:
                try:
                    return getattr(self, fn)(body, query, *found.groups())
                except BadBody as e:
                    return 400, {"error": str(e)}
                except notes.Refused as e:
                    return 400, {"error": str(e)}
                except notes.Failed as e:
                    return 500, {"error": str(e)}
                except telemetry.Invalid as e:
                    return 400, {"error": str(e)}
                except terminal.TerminalError as e:
                    return 400, {"error": str(e)}
                except files.Error as e:
                    return FILE_STATUS[e.kind], {"error": str(e), "kind": e.kind}
        return 404, {"error": "no such path"}

    def _profile(self, pid):
        return projects.get(self.home, pid, self.root)

    def _live(self):
        """(every tmux session, marked; the kit's sessions that run, by project)"""
        known = projects.sessions(self.home)
        tmux = tmuxs.sessions({s["id"]: s["project"] for s in known})
        names = {t["name"] for t in tmux}
        live = {}
        for s in known:
            if s["id"] in names:
                live.setdefault(s["project"], []).append(s)
        return tmux, live

    def _agent(self, p, sessions):
        """a project and its sessions that run; a session differs when it runs with other fields than a new one
        of the project would get"""
        view = dict(p)
        shown = [k for k, _ in projects.FIELDS]
        view["sessions"] = [dict(s, differs=any(s[k] != p[k] for k in shown)) for s in sessions]
        view["running"] = bool(sessions)
        view["context"] = context.tokens(self.home, p["dir"])
        # no data: the kit does not write a session's reports, and gives a session no telemetry settings yet
        view["last_event"] = view["answers"] = None
        view["telemetry"] = "nodata"
        return view

    def r_state(self, body, query):
        profs = projects.list_all(self.home, self.root)
        tmux, live = self._live()
        mach = machine.snapshot(self.cfg["home_dir"], [p["dir"] for p in profs])
        return 200, {"machine": mach, "agents": [self._agent(p, live.get(p["id"], [])) for p in profs], "tmux": tmux}

    def r_agent(self, body, query, pid, action):
        if self._profile(pid) is None:
            return 404, {"error": "no such agent"}
        data = _object(body) if body.strip() else {}
        if set(data) - {"model", "effort"}:
            return 400, {"error": "only model and effort are given here"}
        model, effort = data.get("model"), data.get("effort")
        if model is not None and model not in runner.MODELS:
            return 400, {"error": "model: one of %s" % " ".join(runner.MODELS)}
        if effort is not None and effort not in runner.EFFORTS:
            return 400, {"error": "effort: one of %s" % " ".join(runner.EFFORTS)}
        if action != "start":
            res = runner.stop([s["id"] for s in self._live()[1].get(pid, [])])
            if action == "stop" or not res["ok"]:
                return 200, res
        return 200, runner.start(pid, model, effort)

    def r_session_stop(self, body, query, sid):
        if not any(s["id"] == sid for found in self._live()[1].values() for s in found):
            return 404, {"error": "no such session"}
        return 200, runner.stop([sid])

    def r_tmux_close(self, body, query, name):
        if not tmuxs.valid(name):
            return 400, {"error": "not a session name"}
        if not tmuxs.close(name):
            return 404, {"error": "no such session"}
        return 200, {"closed": name}

    def r_notes_read(self, body, query, pid):
        p = self._profile(pid)
        if p is None:
            return 404, {"error": "no such agent"}
        return 200, notes.read(p["dir"], self.home)

    def r_notes_write(self, body, query, pid):
        p = self._profile(pid)
        if p is None:
            return 404, {"error": "no such agent"}
        return 200, notes.write(p["dir"], self.home, _object(body).get("text"))

    def r_console(self, body, query, pid):
        if self._profile(pid) is None:
            return 404, {"error": "no such agent"}
        found = sorted(self._live()[1].get(pid, []), key=lambda s: s["started"])
        want = _params(query).get("session")
        if want is not None:
            found = [s for s in found if s["id"] == want]
        s = console.screen(found[-1]["id"]) if found else None   # the newest session, when none is named
        if s is None:
            return 404, {"error": "not running"}
        return 200, dict(s, session=found[-1]["id"])

    def r_terminal_list(self, body, query):
        return 200, {"terminals": terminal.listing()}

    def r_terminal_open(self, body, query):
        if len(terminal.listing()) >= terminal.MAX_OPEN:
            return 409, {"error": "at most %d terminals are open; close one first" % terminal.MAX_OPEN}
        return 201, terminal.open(self.home)

    def r_terminal_screen(self, body, query, tid):
        s = terminal.screen(tid)
        if s is None:
            return 404, {"error": "no such terminal"}
        return 200, s

    def r_terminal_send(self, body, query, tid):
        if tid not in terminal.listing():
            return 404, {"error": "no such terminal"}
        data = _object(body)
        text, key = data.get("text"), data.get("key")
        if text is not None and not isinstance(text, str):
            return 400, {"error": "text: a string needed"}
        terminal.send(tid, text=text, key=key)
        return 200, {"sent": tid}

    def r_terminal_close(self, body, query, tid):
        if tid not in terminal.listing():
            return 404, {"error": "no such terminal"}
        terminal.close(tid)
        return 200, {"closed": tid}

    def r_files_read(self, body, query, pid):
        p = self._profile(pid)
        if p is None:
            return 404, {"error": "no such agent"}
        path = _files_path(query)
        try:
            return 200, {"kind": "dir", "entries": files.listing(p["dir"], path)}
        except files.Error as e:
            if e.kind != "not_file":
                raise
        return 200, dict(kind="file", **files.read(p["dir"], path))

    def r_files_write(self, body, query, pid):
        p = self._profile(pid)
        if p is None:
            return 404, {"error": "no such agent"}
        data = _object(body)
        return 200, files.write(p["dir"], _files_path(query), data.get("text"), data.get("mtime"))

    def r_telemetry(self, body, query):
        return 200, telemetry.status(self.home)

    def r_telemetry_install(self, body, query):
        telemetry.install(self.home, _object(body))
        return 200, telemetry.status(self.home)

    def r_telemetry_remove(self, body, query):
        telemetry.remove(self.home)
        return 200, telemetry.status(self.home)

    def r_telemetry_check(self, body, query):
        return 200, telemetry.check(self.home)

    def r_telemetry_arrives(self, body, query):
        live = self._live()[1]
        agents = [{"id": p["id"], "running": p["id"] in live,
                   "started": max((s["started"] for s in live.get(p["id"], [])), default=None)}
                  for p in projects.list_all(self.home, self.root)]
        return 200, telemetry.arrives(self.home, agents)

    def _period(self, q):
        """(since, until, the agent's folder or None) of a query, or (status, answer) when it is wrong."""
        try:
            until = _seconds(q.get("until"), int(time.time()))
            since = _seconds(q.get("since"), until - COSTS_DEFAULT)
        except ValueError as e:
            return 400, {"error": str(e)}
        if since > until:
            return 400, {"error": "since is after until"}
        if until - since > COSTS_MAX:
            return 400, {"error": "the period is over 366 days"}
        folder = None
        if "agent" in q:
            p = self._profile(q["agent"])
            if p is None:
                return 404, {"error": "no such agent"}
            folder = _folder_name(p["dir"])
        return since, until, folder

    def r_analyst(self, body, query):
        got = self._period(_params(query))
        if len(got) == 2:
            return got
        return 200, analyst.report(os.path.join(self.home, ".claude", "projects"), *got,
                                   answers=analyst_ask.answers(self.home))

    def r_costs(self, body, query):
        q = _params(query)
        got = self._period(q)
        if len(got) == 2:
            return got
        since, until, folder = got
        out = costs.report(os.path.join(self.home, ".claude", "projects"), since, until, folder, {})   # no labels
        if q.get("langfuse") == "1":
            out["langfuse"] = langfuse_costs.report(self.home, since, until)   # the whole Langfuse project, not one agent
        return 200, out


def make_handler(api):
    class Handler(BaseHTTPRequestHandler):
        server_version = "agent-kit-dashboard"
        sys_version = ""

        def log_message(self, fmt, *args):
            return   # no request log: the paths hold the owner's ids

        def do_GET(self):
            self._route("GET")

        def do_POST(self):
            self._route("POST")

        def do_PUT(self):
            self._route("PUT")

        def do_DELETE(self):
            self._route("DELETE")

        def _route(self, method):
            parts = urlsplit(self.path)
            path = parts.path
            if path == API + "/hello" and method == "GET":
                return self._json(200, api.hello())   # the only path with no access check
            if path != "/" and not path.startswith(API + "/"):
                return self._json(404, {"error": "no such path"})
            ok, status, reason = access.decide(self.client_address[0], self.headers, api.access_settings(), api.tailnet)
            if not ok:
                return self._json(status, {"error": reason})
            if path == "/":
                if method != "GET":
                    return self._json(405, {"error": "GET only"})
                return self._send(200, api.page, "text/html; charset=utf-8", csp=True)
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._json(400, {"error": "bad Content-Length"})
            if length > MAX_BODY:
                self.close_connection = True
                return self._json(413, {"error": "the body is over 1 MB"})
            body = self.rfile.read(length) if length > 0 else b""
            status, obj = api.dispatch(method, path[len(API):], body, parts.query)
            self._json(status, obj)

        def _json(self, status, obj):
            self._send(status, json.dumps(obj).encode("utf-8"), "application/json")

        def _send(self, status, raw, ctype, csp=False):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if csp:
                self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                            "script-src 'self' 'unsafe-inline'; connect-src 'self'")
            self.end_headers()
            self.wfile.write(raw)

    return Handler


def serve(bind, port, api):
    httpd = ThreadingHTTPServer((bind, port), make_handler(api))
    httpd.daemon_threads = True
    return httpd
