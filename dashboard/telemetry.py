"""telemetry.py - "install telemetry" (PLAN.md section 6, CONTRACT.md "Telemetry"): writes
~/.config/agent-kit/telemetry.env, the ready lines NAME=value that a Claude Code session needs (RESEARCH.md section 2).
Logs go to one receiver (VictoriaLogs), traces to one (VictoriaTraces or Langfuse). The keys are never given back:
status() returns only whether it is set up and the receivers' names.
No text of the user's prompts is sent: OTEL_LOG_USER_PROMPTS is never set. The kit's own system prompt is sent
(launcher/launch-record.sh)."""
import base64, calendar, json, os, re, tempfile, time
import urllib.error, urllib.request
from urllib.parse import urlencode, urlsplit

import machine   # name: the machine's name, as the sessions give it in host.name
import envfile   # read_env: the dashboard's KEY=value reader

CHECK_TIMEOUT = 8          # seconds for one request of check() or arrives()
LATE_LIMIT = 600           # seconds with no record before a running agent is late
MAX_BODY = 1024 * 1024
# The read requests of check() and arrives(), each from the product's documentation (read only, GET):
#   VictoriaLogs: https://docs.victoriametrics.com/victorialogs/querying/ : GET /select/logsql/query?query=...&limit=N
#     (the page gives the query in the URL as an HTTP GET). The login is a flag of VictoriaLogs itself, Basic auth:
#     -httpAuth.username / -httpAuth.password, "The authentication is disabled if empty."
#     https://docs.victoriametrics.com/victorialogs/ . No status code for a refused key is stated: a 401 or 403 is
#     "not checked", with the code in the detail.
#   VictoriaTraces: https://docs.victoriametrics.com/victoriatraces/querying/ : GET /select/jaeger/api/services
#     ("for querying all the services"; the page gives no method, its examples are plain curl, so GET). The login is
#     -httpAuth.username / -httpAuth.password: https://docs.victoriametrics.com/victoriatraces/ . No status code for
#     a refused key is stated: a 401 or 403 is "not checked", with the code in the detail.
#   Langfuse: https://langfuse.com/docs/api-and-data-platform/features/public-api : GET /api/public/projects with Basic
#     auth: the example is curl -u public-key:secret-key ("Use the same credentials and regional base URL for the rest of
#     the Public API"). No status code or body for wrong or missing credentials is stated: a 401 or 403 is "not checked".
LOGS_QUERY_PATH = "/select/logsql/query"
TRACES_QUERY_PATH = "/select/jaeger/api/services"
LANGFUSE_READ_PATH = "/api/public/projects"
MACHINE_RE = re.compile(r"[A-Za-z0-9._:/-]+\Z")

ENV_PATH = (".config", "agent-kit", "telemetry.env")
LOGS_PATH = "/insert/opentelemetry/v1/logs"      # VictoriaLogs
TRACES_PATH = "/insert/opentelemetry/v1/traces"  # VictoriaTraces
LANGFUSE_PATH = "/api/public/otel/v1/traces"     # Langfuse
TRACES = ("victoria", "langfuse", "")
FIELDS = ("logs_url", "logs_user", "logs_password", "traces_to", "traces_url", "traces_user", "traces_password",
          "langfuse_url", "langfuse_public_key", "langfuse_secret_key",
          "read_langfuse_url", "read_langfuse_public_key", "read_langfuse_secret_key")
BAD_CHARS = "\"'$\\"   # never in a value: a single-quoted value must stay one piece for bash and shlex


class Invalid(ValueError):
    pass


def file_of(home):
    return os.path.join(home, *ENV_PATH)


def _printable(name, v):
    """printable ASCII, no space, quote, $ or backslash"""
    if any(c in BAD_CHARS or c == " " or not 33 <= ord(c) <= 126 for c in v):
        raise Invalid("%s: printable ASCII, no spaces, quotes, $ or backslash" % name)
    return v


def _address(name, v):
    """an http or https address with a host; no user in it (a password would be written there)"""
    v = _printable(name, v)
    try:
        u = urlsplit(v)
        port = u.port
    except ValueError:
        raise Invalid("%s: not an address" % name)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise Invalid("%s: an http or https address with a host" % name)
    if u.username is not None or u.password is not None:
        raise Invalid("%s: no user or password in the address: use the user and password fields" % name)
    return v.rstrip("/")


def _basic(name, user, password):
    """Basic auth: user and password both or neither; the user has no colon (it is the part before user:password)"""
    if not user and not password:
        return ""
    if not user or not password:
        raise Invalid("%s: give the user and the password, or neither" % name)
    _printable(name + " user", user)
    if ":" in user:
        raise Invalid("%s user: no colon" % name)
    _printable(name + " password", password)
    return base64.b64encode(("%s:%s" % (user, password)).encode("ascii")).decode("ascii")


def build(form):
    """the lines of telemetry.env as (NAME, value) pairs, from the form. Raises Invalid with the first problem."""
    unknown = set(form) - set(FIELDS)
    if unknown:
        raise Invalid("%s: not a field" % sorted(unknown)[0])
    f = {k: str(form.get(k) or "").strip() for k in FIELDS}
    traces_to = f["traces_to"]
    if traces_to not in TRACES:
        raise Invalid("traces_to: victoria, langfuse or empty")
    if not f["logs_url"]:
        raise Invalid("logs_url: the VictoriaLogs address is needed")
    logs_url = _address("logs_url", f["logs_url"])
    logs_auth = _basic("logs", f["logs_user"], f["logs_password"])
    lines = [("CLAUDE_CODE_ENABLE_TELEMETRY", "1"), ("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf"),
             ("OTEL_LOGS_EXPORTER", "otlp"), ("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", logs_url + LOGS_PATH)]
    if logs_auth:
        lines.append(("OTEL_EXPORTER_OTLP_LOGS_HEADERS", "Authorization=Basic " + logs_auth))
    receivers = ["victorialogs"]
    if traces_to:
        lines.append(("CLAUDE_CODE_ENHANCED_TELEMETRY_BETA", "1"))   # traces are beta in Claude Code
        lines.append(("OTEL_TRACES_EXPORTER", "otlp"))
    if traces_to == "victoria":
        if not f["traces_url"]:
            raise Invalid("traces_url: the VictoriaTraces address is needed")
        traces_url = _address("traces_url", f["traces_url"])
        auth = _basic("traces", f["traces_user"], f["traces_password"])
        lines.append(("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", traces_url + TRACES_PATH))
        if auth:
            lines.append(("OTEL_EXPORTER_OTLP_TRACES_HEADERS", "Authorization=Basic " + auth))
        receivers.append("victoriatraces")
    if traces_to == "langfuse":
        if not f["langfuse_url"]:
            raise Invalid("langfuse_url: the Langfuse address is needed")
        if not f["langfuse_public_key"] or not f["langfuse_secret_key"]:
            raise Invalid("langfuse keys: the public and the secret key are needed")
        lf_url = _address("langfuse_url", f["langfuse_url"])
        auth = _basic("langfuse", f["langfuse_public_key"], f["langfuse_secret_key"])
        lines.append(("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", lf_url + LANGFUSE_PATH))
        # Langfuse's header version is in the same value (RESEARCH.md section 2)
        lines.append(("OTEL_EXPORTER_OTLP_TRACES_HEADERS", "Authorization=Basic " + auth + ",x-langfuse-ingestion-version=4"))
        receivers.append("langfuse")
    # Langfuse's reading key (a key of Viewer permissions), whatever receiver the traces go to: not a receiver. The
    # sessions with the langfuse add-on read Langfuse with it (npx langfuse-cli); claude-wrapper.sh takes the three
    # variables away from the other sessions
    read = [f["read_langfuse_url"], f["read_langfuse_public_key"], f["read_langfuse_secret_key"]]
    if any(read):
        if not all(read):
            raise Invalid("read_langfuse: give the Langfuse address, the public and the secret key of the reading key, or none")
        lines.append(("LANGFUSE_PUBLIC_KEY", _printable("read_langfuse_public_key", read[1])))
        lines.append(("LANGFUSE_SECRET_KEY", _printable("read_langfuse_secret_key", read[2])))
        lines.append(("LANGFUSE_BASE_URL", _address("read_langfuse_url", read[0])))
    # the dashboard's own lines: names and the logs address only, no secret
    lines.append(("AGENT_KIT_TELEMETRY_RECEIVERS", ",".join(receivers)))
    lines.append(("AGENT_KIT_TELEMETRY_LOGS_QUERY", logs_url))
    return lines


def install(home, form):
    """validates the form, then writes the file (mode 600, atomic; folder 700). Nothing is written on an error."""
    lines = build(form)
    text = "# agent-kit telemetry: written by the dashboard\n" + "".join(
        "%s='%s'\n" % (k, v) for k, v in lines)
    path = file_of(home)
    folder = os.path.dirname(path)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    os.chmod(folder, 0o700)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-", suffix=".env")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def status(home):
    """{"set_up": bool, "receivers": [names]} and nothing else"""
    path = file_of(home)
    if not os.path.isfile(path):
        return {"set_up": False, "receivers": []}
    try:
        raw = envfile.read_env(path)
    except envfile.Invalid:
        raw = {}
    names = [n for n in raw.get("AGENT_KIT_TELEMETRY_RECEIVERS", "").split(",")
             if n in ("victorialogs", "victoriatraces", "langfuse")]
    return {"set_up": True, "receivers": names}


def remove(home):
    try:
        os.unlink(file_of(home))
    except FileNotFoundError:
        pass


def _settings(home):
    """telemetry.env as a dict; {} when there is no file or it does not read"""
    path = file_of(home)
    if not os.path.isfile(path):
        return {}
    try:
        return envfile.read_env(path)
    except envfile.Invalid:
        return {}


def _basic_of(header):
    """the Basic key of a header line (Authorization=Basic X, maybe more after a comma); "" when there is none"""
    m = re.search(r"Authorization=Basic ([A-Za-z0-9+/=]+)", header or "")
    return m.group(1) if m else ""


def _base(s, endpoint_key, path):
    """the address of a receiver from its traces endpoint (the path it ends with is taken off); "" when not there"""
    v = s.get(endpoint_key, "")
    return v[:-len(path)] if v.endswith(path) else ""


def _names(s):
    return [n for n in s.get("AGENT_KIT_TELEMETRY_RECEIVERS", "").split(",")
            if n in ("victorialogs", "victoriatraces", "langfuse")]


def _probe(name, s):
    """(url, key) of the receiver's read request; ("", "") when no address is kept for it"""
    if name == "victorialogs":
        base = s.get("AGENT_KIT_TELEMETRY_LOGS_QUERY", "")
        url = base + LOGS_QUERY_PATH + "?" + urlencode({"query": "*", "limit": 1}) if base else ""
        return url, _basic_of(s.get("OTEL_EXPORTER_OTLP_LOGS_HEADERS"))
    if name == "victoriatraces":
        base = _base(s, "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "/insert/opentelemetry/v1/traces")
        return (base + TRACES_QUERY_PATH if base else ""), _basic_of(s.get("OTEL_EXPORTER_OTLP_TRACES_HEADERS"))
    base = _base(s, "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "/api/public/otel/v1/traces")
    return (base + LANGFUSE_READ_PATH if base else ""), _basic_of(s.get("OTEL_EXPORTER_OTLP_TRACES_HEADERS"))


def _request(url, key, timeout=CHECK_TIMEOUT):
    """(status, body) of one GET with the Basic key when given; status None when there is no answer. Redirects are
    followed only to the same host. Errors are not printed: a URL can hold a password."""
    headers = {"Authorization": "Basic " + key} if key else {}
    opener = urllib.request.build_opener(_SameHost(url))
    try:
        with opener.open(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
            return r.status, r.read(MAX_BODY)
    except urllib.error.HTTPError as e:   # before URLError: it is one
        return e.code, b""
    except (OSError, ValueError):
        return None, b""


class _SameHost(urllib.request.HTTPRedirectHandler):
    def __init__(self, url):
        self.host = urlsplit(url).netloc

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).netloc != self.host:
            return None   # not followed: the 3xx is the answer
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _verdict(status):
    # 401 and 403 are "refused" by HTTP's own meaning of them (RFC 9110, 15.5.2 and 15.5.4): the three products'
    # documentation states no code for a refused key, so the code is always in the detail
    if status is None:
        return "unreachable", "no answer"
    if 200 <= status < 300:
        return "accepted", "answered %d" % status
    if status >= 500:
        return "unreachable", "answered %d" % status
    if status in (401, 403):
        return "refused", "answered %d" % status
    return "not checked", "answered %d: not an answer about the key" % status


def check(home):
    """{"receivers": {NAME: {"key": accepted|refused|unreachable|not checked, "detail": text}}} for the receivers set
    up. One read request each, with the kept key. No key kept for a receiver: no request, "not checked"."""
    s = _settings(home)
    out = {}
    for name in _names(s):
        url, key = _probe(name, s)
        if not url:
            out[name] = {"key": "not checked", "detail": "no address kept for it"}
        elif not key:
            out[name] = {"key": "not checked", "detail": "no user and password kept: nothing to check"}
        else:
            verdict, detail = _verdict(_request(url, key)[0])
            out[name] = {"key": verdict, "detail": detail}
    return {"receivers": out}


def _epoch(text):
    """a VictoriaLogs time (2026-11-19T10:00:00.123Z) as whole seconds; None when it is not one"""
    m = re.match(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.\d+)?(?:Z|\+00:00)\Z", text or "")
    return calendar.timegm(time.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S")) if m else None


def _last_logs(s):
    """{agent ID: last record as seconds} of this machine in VictoriaLogs, the last 7 days; (None, reason) on a failure"""
    machine_name = machine.name()
    if not MACHINE_RE.match(machine_name):
        return None, "the machine's name has characters the query does not take"
    base = s.get("AGENT_KIT_TELEMETRY_LOGS_QUERY", "")
    # the fields the sessions send (launcher/claude-wrapper.sh: host.name and agent.id in OTEL_RESOURCE_ATTRIBUTES)
    # LogsQL as the docs show it: _time:1w, and stats by (...) with a bare alias as in "_time:5m | stats by (host)
    # count() logs" (https://docs.victoriametrics.com/victorialogs/logsql/; the max stats page could not be read in full)
    query = 'host.name:"%s" _time:1w | stats by (agent.id) max(_time) last' % machine_name
    url = base + LOGS_QUERY_PATH + "?" + urlencode({"query": query})
    status, body = _request(url, _basic_of(s.get("OTEL_EXPORTER_OTLP_LOGS_HEADERS")))
    if status is None or not 200 <= status < 300:
        return None, "VictoriaLogs did not answer with data"
    found = {}
    for line in body.decode("utf-8", "replace").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        when = _epoch(row.get("last")) if isinstance(row, dict) else None
        if when is not None and row.get("agent.id"):
            found[row["agent.id"]] = when
    return found, None


def arrives(home, agents, now=None):
    """the time of the last record of each agent of this machine, from VictoriaLogs when it is a receiver:
    {"agents": {ID: {"last": seconds or None, "late": bool}}, "limit": LATE_LIMIT} and "reason" when there is no
    last time. agents: a list of {"id", "running", "started" (seconds or None)}. A running agent is late when no
    record came since its start, or since its last record, for longer than LATE_LIMIT."""
    now = time.time() if now is None else now
    s = _settings(home)
    names = _names(s)
    found, reason = {}, None
    if "victorialogs" in names:
        found, reason = _last_logs(s)
        if found is None:
            found = {}
    elif "langfuse" in names:
        reason = "no VictoriaLogs receiver: Langfuse's documented trace list has no filter by agent"
    else:
        reason = "no receiver for the logs is set up"
    out = {}
    for a in agents:
        last = found.get(a["id"])
        basis = max(last or 0, a.get("started") or 0)
        late = bool(a.get("running") and basis and now - basis > LATE_LIMIT)
        out[a["id"]] = {"last": last, "late": late}
    res = {"agents": out, "limit": LATE_LIMIT}
    if reason:
        res["reason"] = reason
    return res
