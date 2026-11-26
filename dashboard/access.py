"""access.py - who may call the dashboard (CONTRACT.md "Access"). The decision is pure: the client's address, the
headers, the settings and a Tailnet object come in; (allowed, status, reason) goes out. Tailscale is asked only
through Tailnet, which keeps each answer a minute. The API key is made and read here too."""
import hmac, ipaddress, json, os, secrets, socket, subprocess, time

TAILNET = ipaddress.ip_network("100.64.0.0/10")
PRIVATE = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7", "fe80::/10")]
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")
ALLOW = (True, 200, "ok")


def deny(status, reason):
    return (False, status, reason)


def address(text):
    a = ipaddress.ip_address(str(text).split("%")[0])
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    return a


class Tailnet:
    """Asks the tailscale command who is who. An answer, or a failure (None), is kept a minute."""

    def __init__(self, ttl=60):
        self.ttl = ttl
        self.cache = {}

    def _run(self, *args):
        r = subprocess.run(["tailscale", *args], capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            raise RuntimeError("tailscale failed")
        return json.loads(r.stdout)

    def _cached(self, key, fn):
        hit = self.cache.get(key)
        if hit and time.monotonic() - hit[0] < self.ttl:
            return hit[1]
        try:
            value = fn()
        except (OSError, subprocess.SubprocessError, RuntimeError, ValueError, KeyError, TypeError):
            value = None   # no tailscale, or it failed: rule 2 denies
        self.cache[key] = (time.monotonic(), value)
        return value

    def self_user(self):
        """(user id, login name) of this machine's own user, or None."""
        def ask():
            st = self._run("status", "--json")
            uid = st["Self"]["UserID"]
            return (uid, st["User"][str(uid)]["LoginName"].lower())
        return self._cached("self", ask)

    def addr_user(self, addr):
        """the user id of the Tailscale address, or None."""
        return self._cached("addr " + addr, lambda: self._run("whois", "--json", addr)["UserProfile"]["ID"])

    def same_addr(self, addr):
        me, theirs = self.self_user(), self.addr_user(addr)
        if me is None or theirs is None:
            return None
        return me[0] == theirs

    def same_login(self, login):
        me = self.self_user()
        if me is None:
            return None
        return me[1] == str(login).lower()


def decide(client, headers, settings, tailnet):
    """Rules 1 to 4 of CONTRACT.md, then the Origin check. Returns (allowed, status, reason)."""
    verdict = _rules(client, headers, settings, tailnet)
    if not verdict[0]:
        return verdict
    return _origin(headers, settings)


def _rules(client, headers, settings, tailnet):
    ip = address(client)
    login = headers.get("Tailscale-User-Login")
    host = headers.get("Host") or ""
    # 1. loopback, no Tailscale header: allowed without a key. A page of another site that rebinds a name to
    #    127.0.0.1 sends its own name as Host, so only the loopback names are taken.
    if ip.is_loopback and not login:
        if host.split(":")[0] in LOOPBACK_HOSTS or host.startswith("[::1]"):
            return ALLOW
        return deny(403, "not a local name")
    # a page of another site that rebinds its name to this machine sends that name as Host: only an address, a
    # tailnet name or this machine's own name is taken
    if not _own_host(host):
        return deny(403, "not this machine's name")
    # 2. loopback with the headers of tailscale serve, or a Tailscale address: the same user as this machine's own
    if (ip.is_loopback and login) or ip in TAILNET:
        # the login header is believed only from loopback (tailscale serve sets it); from the network anyone can write it
        same = tailnet.same_login(login) if ip.is_loopback else tailnet.same_addr(str(ip))
        if same is None:
            return deny(403, "tailscale does not answer")
        if same:
            return (True, 200, "tailscale, same user")
        return deny(403, "another user")
    # 3. a private address: the API key
    if any(ip in net for net in PRIVATE):
        return _key(headers, settings)
    # 4. anything else
    return deny(403, "not from localhost, Tailscale or the local network")


def _key(headers, settings):
    auth = headers.get("Authorization") or ""
    if not auth.startswith("Bearer "):
        return deny(401, "key needed")
    key = settings.get("key") or ""
    if key and hmac.compare_digest(auth[len("Bearer "):].encode(), key.encode()):
        return (True, 200, "key")
    return deny(401, "wrong key")


def _origin(headers, settings):
    """A request with an Origin is taken only from the dashboard's own addresses, from CENTRES, or from the page's
    own address (an IP address or a tailnet name, as the request named it). No Access-Control-Allow-Origin is sent."""
    origin = headers.get("Origin")
    if origin is None:
        return ALLOW
    port = settings.get("port")
    own = ["http://127.0.0.1:%s" % port, "http://localhost:%s" % port, "http://[::1]:%s" % port]
    if origin in own or origin in (settings.get("centres") or []):
        return ALLOW
    host = (headers.get("Host") or "").strip()
    name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
    if origin in ("http://" + host, "https://" + host) and _page_host(name):
        return ALLOW
    return deny(403, "origin not allowed")


def _own_host(host):
    name = (host.split("]")[0] + "]" if host.startswith("[") else host.rsplit(":", 1)[0]).lower()
    me = socket.gethostname().lower()
    return _page_host(name) or name in ("localhost", me, me + ".local", me.split(".")[0])


def _page_host(name):
    """an IP address, or a name in the tailnet (tailscale serve gives one), never any other name."""
    try:
        ipaddress.ip_address(name.strip("[]"))
        return True
    except ValueError:
        return name.endswith(".ts.net")


def load_key(path, new=False):
    """The API key, made at the first need (or again with new=True): random, kept with mode 600."""
    if new or not os.path.exists(path):
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        tmp = "%s.tmp%d" % (path, os.getpid())
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(32) + "\n")
        os.replace(tmp, path)
    with open(path) as f:
        return f.read().strip()
