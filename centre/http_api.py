"""http_api.py - the centre's API under /api/v1 and its page, JSON in and out. The logic is in Api: it reads the
settings (store), finds the machines (find) and calls the dashboards (remote). Access is the dashboard's own rules,
imported from ../dashboard/access.py. Every path but hello goes through access.decide first."""
import json, os, platform, re, secrets, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(HERE, "..", "dashboard"))   # appended, so this folder's modules win
import access, find, incus, remote, repo, ssh_add, store, survey   # noqa: E402

API = "/api/v1"
CENTRE_API = 1
MAX_BODY = 1024 * 1024
SURVEY_AT_ONCE = 8
JOBS_MAX = 20   # the SSH adds kept in memory; the oldest is dropped
ROUTES = [
    ("GET", r"/state", "r_state"),
    ("POST", r"/machines", "r_machine_add"),
    ("PUT", r"/machines/([^/]+)", "r_machine_change"),
    ("DELETE", r"/machines/([^/]+)", "r_machine_delete"),
    ("GET", r"/groups", "r_groups"),
    ("PUT", r"/groups", "r_groups_save"),
    ("GET", r"/settings", "r_settings"),
    ("PUT", r"/settings", "r_settings_save"),
    ("POST", r"/repo/save", "r_repo_save"),
    ("POST", r"/repo/load", "r_repo_load"),
    ("GET", r"/ssh/key", "r_ssh_key"),
    ("POST", r"/machines/ssh", "r_ssh_add"),
    ("GET", r"/machines/ssh/([0-9a-f]{16})", "r_ssh_job"),
    ("GET", r"/survey", "r_survey"),
    ("POST", r"/survey", "r_survey_run"),
    ("GET", r"/incus", "r_incus"),
    ("GET", r"/incus/instances", "r_incus_instances"),
    ("GET", r"/incus/profiles", "r_incus_profiles"),
    ("GET", r"/incus/images", "r_incus_images"),
    ("POST", r"/incus/instances", "r_incus_create"),
    ("POST", r"/incus/instances/([^/]+)/(start|stop)", "r_incus_state"),
]
PASS = r"/machines/([^/]+)(/api/v1(?:/.*)?)"


class BadBody(ValueError):
    pass


def _json(body):
    """the body as JSON, None when empty"""
    if not body.strip():
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise BadBody("the body is not JSON")


def _object(body):
    data = _json(body)
    if not isinstance(data, dict):
        raise BadBody("the body is not a JSON object")
    return data


def version_key(text):
    """(tag numbers, commits after the tag) of "v0.12" or "v0.12-3-gabc1234[-dirty]"; None for any other text"""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)(?:-(\d+)-g[0-9a-f]+)?(?:-dirty)?", str(text))
    if not m:
        return None
    return (tuple(int(x) for x in m.group(1).split(".")), int(m.group(2) or 0))


def older(hello, centre_version):
    """a dashboard is older when its api number or its version is lower than the centre's"""
    api = hello.get("api")
    if isinstance(api, int) and api < CENTRE_API:
        return True
    mine, theirs = version_key(hello.get("version")), version_key(centre_version)
    return mine is not None and theirs is not None and mine < theirs


def answer_error(status, obj):
    if isinstance(obj, dict) and isinstance(obj.get("error"), str):
        return obj["error"]
    return "the dashboard answered %d" % status


class Api:
    """what the routes need: the home folder (settings in .config/agent-kit/centre), the key, the port, the version,
    the page."""

    def __init__(self, home, key, cfg, version, page):
        self.key, self.cfg, self.version, self.page = key, cfg, version, page
        self.home = home
        self.tailnet = access.Tailnet()
        self.store = store.Store(os.path.join(home, ".config", "agent-kit", "centre"))
        self.machine_name = platform.node()
        self.surveys = {}   # address -> the last survey's answer, of the machines that let the centre in
        self.survey_log = []   # the machines that did not, as lines; the newest last
        self.jobs, self.jobs_lock = {}, threading.Lock()   # SSH adds: id -> {id, machine, state, steps, error}

    def access_settings(self):
        return {"port": self.cfg["port"], "centres": [], "key": self.key}

    def hello(self):
        return {"kind": "centre", "machine": self.machine_name, "version": self.version, "api": CENTRE_API}

    def dispatch(self, method, path, query, body):
        """-> (status, object). path is the part after /api/v1."""
        try:
            found = re.fullmatch(PASS, path)
            if found:
                return self.r_pass(method, body, found.group(1), found.group(2), query)
            for m, pattern, fn in ROUTES:
                found = re.fullmatch(pattern, path) if m == method else None
                if found:
                    return getattr(self, fn)(body, *found.groups())
        except BadBody as e:
            return 400, {"error": str(e)}
        except store.Invalid as e:
            return 400, {"error": str(e)}
        except store.Missing:
            return 404, {"error": "no such machine"}
        return 404, {"error": "no such path"}

    def _view(self, m):
        """a machine as the browser sees it: never the key, only whether one is kept"""
        return {"name": m["name"], "address": m["address"], "on": m["on"], "added": m["added"],
                "has_key": self.store.key(m["name"]) is not None}

    def _target(self, m):
        return {"name": m["name"], "address": m["address"], "key": self.store.key(m["name"])}

    def _machine_view(self, m):
        """a machine with its dashboard's state, or the error text when it does not answer; an off machine is not asked"""
        view = self._view(m)
        view.update({"version": None, "api": None, "older": False, "state": None, "error": None})
        if not m["on"]:
            return view
        target = self._target(m)
        status, hello = remote.call(target, "GET", API + "/hello")
        if status != 200 or not isinstance(hello, dict) or hello.get("kind") != "dashboard":
            view["error"] = answer_error(status, hello) if status != 200 else "it is not a dashboard"
            return view
        view.update({"version": hello.get("version"), "api": hello.get("api"), "older": older(hello, self.version)})
        status, state = remote.call(target, "GET", API + "/state")
        if status != 200:
            view["error"] = answer_error(status, state)
        else:
            view["state"] = state
        return view

    def r_state(self, body):
        machines = self.store.machines()
        with ThreadPoolExecutor(max_workers=len(machines) + 1) as pool:
            jobs = [pool.submit(self._machine_view, m) for m in machines]
            seen = pool.submit(find.find, self.cfg["port"])
            views = [j.result() for j in jobs]
            found = seen.result()
        added = {m["address"] for m in machines}
        return 200, {
            "centre": {"machine": self.machine_name, "version": self.version, "api": CENTRE_API},
            "machines": views,
            "groups": self.store.groups(),
            "settings": self.store.settings(),
            "found": [d for d in found["dashboards"] if d["address"] not in added],
            "other_centres": found["centres"],
            "install_cmd": ssh_add.install_command(self.store.settings()),
        }

    def r_machine_add(self, body):
        data = _object(body)
        key = data.get("key")
        if key is not None and not isinstance(key, str):
            raise BadBody("key: text")
        m = self.store.add(data.get("name"), data.get("address"), key or None)
        return 201, self._view(m)

    def r_machine_change(self, body, name):
        data = _object(body)
        if set(data) - {"on", "key", "address"}:
            raise BadBody("only on, key and address can change")
        return 200, self._view(self.store.update(name, data))

    def r_machine_delete(self, body, name):
        self.store.remove(name)
        return 200, {"deleted": name}

    def r_groups(self, body):
        return 200, {"groups": self.store.groups()}

    def r_groups_save(self, body):
        data = _object(body)
        return 200, {"groups": self.store.set_groups(data.get("groups"))}

    def r_settings(self, body):
        return 200, self.store.settings()

    def r_settings_save(self, body):
        return 200, self.store.set_settings(_object(body))

    def _repo_name(self):
        name = self.store.settings()["repo"]
        if not name:
            raise BadBody("no repository is set: name one in the links form")
        return name

    def r_repo_save(self, body):
        name = self._repo_name()
        data = repo.export({"machines": self.store.machines(), "groups": self.store.groups(),
                            "settings": self.store.settings()})
        result = repo.save(name, data)
        return (200 if result["ok"] else 502), result

    def r_repo_load(self, body):
        name = self._repo_name()
        got = repo.load(name)
        if not got["ok"]:
            return 502, got
        result = repo.apply(self.store, got["data"])
        return (200 if result["ok"] else 400), result

    def r_ssh_key(self, body):
        """the centre's public key only; the private key is never sent"""
        try:
            return 200, {"public": ssh_add.ensure_key(self.home)}
        except ssh_add.Failed as e:
            return 502, {"error": str(e)}

    def r_ssh_add(self, body):
        """202 with a job id at once; the install runs in a thread and GET .../machines/ssh/ID says how it goes"""
        data = _object(body)
        name, host, user, password = ssh_add.check_request(self.store, data.get("name"), data.get("address"),
                                                           data.get("user"), data.get("password"))
        job = {"id": secrets.token_hex(8), "machine": name, "state": "running", "steps": [], "error": None}
        with self.jobs_lock:
            self.jobs[job["id"]] = job
            while len(self.jobs) > JOBS_MAX:
                self.jobs.pop(next(iter(self.jobs)))
        threading.Thread(target=self._ssh_job, args=(job, name, host, user, password), daemon=True).start()
        return 202, self._job_view(job)

    def _ssh_job(self, job, name, host, user, password):
        def progress(item):
            with self.jobs_lock:
                job["steps"].append(item)
        result = ssh_add.run(self.store, self.home, name, host, user, password, progress)
        with self.jobs_lock:
            job["state"] = "done" if result["ok"] else "failed"
            job["error"] = result.get("error")

    def _job_view(self, job):
        with self.jobs_lock:
            return dict(job, steps=list(job["steps"]))

    def r_ssh_job(self, body, job_id):
        job = self.jobs.get(job_id)
        if job is None:
            return 404, {"error": "no such job"}
        return 200, self._job_view(job)

    def r_survey(self, body):
        """the last survey of each machine, with no call to any machine"""
        with self.jobs_lock:
            return 200, {"machines": list(self.surveys.values()), "log": list(self.survey_log)}

    def r_survey_run(self, body):
        """asks every online machine of the network over SSH what is on it; nothing is changed there. The answer
        lists only the machines that let the centre in; each one that did not is a line of the log (kept here, and
        written to the centre's own output)"""
        members = find.members(find.status())
        settings = self.store.settings()
        with ThreadPoolExecutor(max_workers=max(1, min(SURVEY_AT_ONCE, len(members)))) as pool:
            answers = list(pool.map(lambda m: survey.run(m[1], settings), members))
        seen, lines = survey.split(members, answers, time.time())
        for x in lines:
            sys.stderr.write("survey: %s (%s): %s\n" % (x["name"], x["address"], x["error"]))
        sys.stderr.flush()
        with self.jobs_lock:
            self.surveys = seen
            self.survey_log = (self.survey_log + lines)[-survey.LOG_MAX:]
            log = list(self.survey_log)
        return 200, {"machines": list(seen.values()), "log": log, "asked": len(members)}

    def _incus(self, got, ok_status):
        """an Incus answer as the status: refused input or no address is 400, an Incus failure 502"""
        if got["ok"]:
            return ok_status, got
        return (400 if got.get("invalid") else 502), got

    def r_incus(self, body):
        s = self.store.settings()
        return 200, {"url": s["incus_url"], "project": s["incus_project"] or incus.DEFAULT_PROJECT,
                     "files": incus.files(self.home)}

    def r_incus_instances(self, body):
        return self._incus(incus.instances(self.home, self.store.settings()), 200)

    def r_incus_profiles(self, body):
        return self._incus(incus.profiles(self.home, self.store.settings()), 200)

    def r_incus_images(self, body):
        return self._incus(incus.images(self.home, self.store.settings()), 200)

    def r_incus_create(self, body):
        data = _object(body)
        got = incus.create(self.home, self.store.settings(), data.get("name"), data.get("profile"), data.get("image"))
        return self._incus(got, 201)

    def r_incus_state(self, body, name, action):
        return self._incus(incus.state(self.home, self.store.settings(), name, action), 200)

    def r_pass(self, method, body, name, rest, query):
        """ANY /machines/NAME/api/v1/...: sent to that machine's dashboard, its status and JSON unchanged"""
        m = self.store.machine(name)
        if m is None:
            return 404, {"error": "no such machine"}
        if not m["on"]:
            return 400, {"error": "the machine is off: turn it on first"}
        path = rest + ("?" + query if query else "")
        return remote.call(self._target(m), method, path, _json(body))


def make_handler(api):
    class Handler(BaseHTTPRequestHandler):
        server_version = "agent-kit-centre"
        sys_version = ""

        def log_message(self, fmt, *args):
            return   # no request log: the paths hold the owner's machine names

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
            status, obj = api.dispatch(method, path[len(API):], parts.query, body)
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
