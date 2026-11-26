"""store.py - the centre's settings in ~/.config/agent-kit/centre/: machines.json (the machines added), groups.json
(the groups of agents), settings.json (the link addresses, the repository, the SSH add's owner key and install command), keys.json (machine name -> API key,
never sent to a browser). Every file is written whole,
atomically, mode 600, in a folder of mode 700. Only this module reads or writes these files."""
import json, os, re, threading, time
from urllib.parse import urlsplit

NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
AGENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}/[a-z0-9]{4}")
BAD_ADDRESS = "the address is http://HOST:PORT"


LINK_FIELDS = ("grafana", "langfuse")   # base addresses the agents' links open; "" when not set
# repo: owner/name of the GitHub repository for the settings; owner_key: the owner's public key put on machines added
# over SSH; install_cmd: the command that installs the kit there (the default when ""). All "" when not set.
# incus_url: https://HOST[:PORT] of the Incus server; incus_project: its project ("" means "default"). Not secrets.
# ssh_key: the file of the private key the centre signs in with over SSH ("" is ssh's own choice); ssh_user: the user
# it signs in as when root is refused ("" is the user who runs the centre).
SETTING_FIELDS = LINK_FIELDS + ("repo", "owner_key", "install_cmd", "incus_url", "incus_project", "ssh_key", "ssh_user")
SSH_KEY_RE = re.compile(r"/[A-Za-z0-9._/@+-]{1,400}")
SSH_USER_RE = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
INCUS_PROJECT_RE = re.compile(r"[A-Za-z0-9_-]{1,63}")
REPO_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,38}/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}")
OWNER_KEY_RE = re.compile(r"(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256) [A-Za-z0-9+/=]+( [A-Za-z0-9._@+=-]{1,64})?")


class Invalid(ValueError):
    pass


class Missing(LookupError):
    pass


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def check_name(name):
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        raise Invalid("the name: letters, digits, dot, dash, underscore; up to 64 characters")
    return name


def check_address(text):
    """http://HOST:PORT and nothing else: the address a dashboard is reached at."""
    if not isinstance(text, str):
        raise Invalid(BAD_ADDRESS)
    try:
        p = urlsplit(text)
        port = p.port
    except ValueError:
        raise Invalid(BAD_ADDRESS)
    host = p.hostname or ""
    if (p.scheme != "http" or not host or port is None or not 0 < port < 65536 or p.username or p.password
            or p.query or p.fragment or p.path not in ("", "/") or not re.fullmatch(r"[A-Za-z0-9.:-]+", host)):
        raise Invalid(BAD_ADDRESS)
    return "http://[%s]:%d" % (host, port) if ":" in host else "http://%s:%d" % (host, port)


def check_link(name, text):
    """an http or https base address with a host, no user, query or fragment; "" clears it"""
    if not isinstance(text, str):
        raise Invalid("%s: an address, as text" % name)
    text = text.strip()
    if not text:
        return ""
    try:
        p = urlsplit(text)
        p.port
    except ValueError:
        raise Invalid("%s: an http or https address" % name)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise Invalid("%s: an http or https address, with no user, query or fragment" % name)
    return text.rstrip("/")


def check_repo(text):
    """"" or owner/name of a GitHub repository"""
    if not isinstance(text, str):
        raise Invalid("repo: owner/name, as text")
    text = text.strip()
    if text and not REPO_RE.fullmatch(text):
        raise Invalid("repo: owner/name of a GitHub repository, letters, digits, dot, dash, underscore")
    return text


def check_owner_key(text):
    """"" or one line: a public key of ssh-ed25519, ssh-rsa or ecdsa-sha2-nistp256, then an optional comment"""
    if not isinstance(text, str) or any(c in text for c in "\r\n\0"):
        raise Invalid("owner_key: one line of a public key")
    text = text.strip()
    if text and not OWNER_KEY_RE.fullmatch(text):
        raise Invalid("owner_key: a public key line: ssh-ed25519, ssh-rsa or ecdsa-sha2-nistp256, then the key")
    return text


def check_install_cmd(text):
    """"" or one line of up to 500 characters: the command that installs the kit on a machine added over SSH"""
    if not isinstance(text, str) or any(c in text for c in "\r\n\0"):
        raise Invalid("install_cmd: one line, no newline")
    text = text.strip()
    if len(text) > 500:
        raise Invalid("install_cmd: up to 500 characters")
    return text


def check_ssh_key(text):
    """"" or the full path of a key file: letters, digits and . _ / @ + -"""
    if not isinstance(text, str) or (text.strip() and not SSH_KEY_RE.fullmatch(text.strip())):
        raise Invalid("ssh_key: the full path of a key file: letters, digits and . _ / @ + -")
    return text.strip()


def check_ssh_user(text):
    if not isinstance(text, str) or (text.strip() and not SSH_USER_RE.fullmatch(text.strip())):
        raise Invalid("ssh_user: lower case letters, digits, underscore and dash")
    return text.strip()


def check_incus_url(text):
    """"" or https://HOST[:PORT] and nothing else: the address of the Incus server (https only)"""
    if not isinstance(text, str):
        raise Invalid("incus_url: an address, as text")
    text = text.strip()
    if not text:
        return ""
    try:
        p = urlsplit(text)
        p.port
    except ValueError:
        raise Invalid("incus_url: https://HOST[:PORT]")
    host = p.hostname or ""
    if (p.scheme != "https" or not host or p.username or p.password or p.query or p.fragment
            or p.path not in ("", "/") or not re.fullmatch(r"[A-Za-z0-9.:-]+", host)):
        raise Invalid("incus_url: https://HOST[:PORT], https only, with no user, path, query or fragment")
    return text.rstrip("/")


def check_incus_project(text):
    """"" (the default project) or a project name of letters, digits, underscore and dash, up to 63 characters"""
    if not isinstance(text, str):
        raise Invalid("incus_project: a project name, as text")
    text = text.strip()
    if text and not INCUS_PROJECT_RE.fullmatch(text):
        raise Invalid("incus_project: letters, digits, underscore and dash; up to 63 characters")
    return text


def clean_machines(data):
    """the machines of a saved file, each checked; a wrong one refuses the whole list"""
    if not isinstance(data, list):
        raise Invalid("machines: a list")
    clean, names = [], set()
    for m in data:
        if not isinstance(m, dict) or not isinstance(m.get("on"), bool):
            raise Invalid("a machine needs a name, an address, and on: true or false")
        name = check_name(m.get("name"))
        if name in names:
            raise Invalid("a machine named %s is there twice" % name)
        names.add(name)
        added = m.get("added") if isinstance(m.get("added"), str) else now()
        clean.append({"name": name, "address": check_address(m.get("address")), "on": m["on"], "added": added})
    return clean


def clean_groups(groups):
    if not isinstance(groups, list):
        raise Invalid("groups: a list")
    clean = []
    for g in groups:
        name = g.get("name") if isinstance(g, dict) else None
        agents = g.get("agents", []) if isinstance(g, dict) else None
        if not isinstance(name, str) or not name.strip() or len(name) > 64:
            raise Invalid("a group needs a name of 1 to 64 characters")
        if not isinstance(agents, list) or not all(isinstance(a, str) and AGENT_RE.fullmatch(a) for a in agents):
            raise Invalid("agents: a list of MACHINE/ID")
        clean.append({"name": name.strip(), "agents": agents})
    return clean


def clean_settings(data):
    if not isinstance(data, dict) or set(data) - set(SETTING_FIELDS):
        raise Invalid("settings: only %s" % ", ".join(SETTING_FIELDS))
    clean = {k: check_link(k, data.get(k, "")) for k in LINK_FIELDS}
    clean["repo"] = check_repo(data.get("repo", ""))
    clean["owner_key"] = check_owner_key(data.get("owner_key", ""))
    clean["install_cmd"] = check_install_cmd(data.get("install_cmd", ""))
    clean["incus_url"] = check_incus_url(data.get("incus_url", ""))
    clean["incus_project"] = check_incus_project(data.get("incus_project", ""))
    clean["ssh_key"] = check_ssh_key(data.get("ssh_key", ""))
    clean["ssh_user"] = check_ssh_user(data.get("ssh_user", ""))
    return clean


class Store:
    def __init__(self, folder):
        self.dir = folder
        self.lock = threading.RLock()

    def _read(self, name, default):
        try:
            with open(os.path.join(self.dir, name), encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return default

    def _write(self, name, data):
        os.makedirs(self.dir, mode=0o700, exist_ok=True)
        os.chmod(self.dir, 0o700)
        path = os.path.join(self.dir, name)
        tmp = "%s.tmp%d" % (path, os.getpid())
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)

    # machines: each {name, address, on, added}
    def machines(self):
        return self._read("machines.json", [])

    def machine(self, name):
        return next((m for m in self.machines() if m["name"] == name), None)

    def add(self, name, address, key=None):
        with self.lock:
            name, address = check_name(name), check_address(address)
            machines = self.machines()
            if any(m["name"] == name for m in machines):
                raise Invalid("a machine named %s is there already" % name)
            m = {"name": name, "address": address, "on": True, "added": now()}
            machines.append(m)
            self._write("machines.json", machines)
            if key:
                self._set_key(name, key)
            return m

    def update(self, name, changes):
        """changes: any of on (true|false), address, key ("" removes the key)."""
        with self.lock:
            machines = self.machines()
            m = next((x for x in machines if x["name"] == name), None)
            if m is None:
                raise Missing(name)
            if "on" in changes:
                if not isinstance(changes["on"], bool):
                    raise Invalid("on: true or false")
                m["on"] = changes["on"]
            if "address" in changes:
                m["address"] = check_address(changes["address"])
            if "key" in changes and not isinstance(changes["key"], str):
                raise Invalid("key: text")
            self._write("machines.json", machines)
            if "key" in changes:
                self._set_key(name, changes["key"])
            return m

    def remove(self, name):
        with self.lock:
            machines = self.machines()
            left = [m for m in machines if m["name"] != name]
            if len(left) == len(machines):
                raise Missing(name)
            self._write("machines.json", left)
            keys = self.keys()
            if name in keys:
                del keys[name]
                self._write("keys.json", keys)

    # keys: machine name -> key; read by remote.py only, never returned by the API
    def keys(self):
        return self._read("keys.json", {})

    def key(self, name):
        return self.keys().get(name)

    def _set_key(self, name, key):
        keys = self.keys()
        if key:
            keys[name] = key
        else:
            keys.pop(name, None)
        self._write("keys.json", keys)

    # groups: each {name, agents: ["MACHINE/ID", ...]}; for the eye only
    def groups(self):
        return self._read("groups.json", [])

    def set_groups(self, groups):
        with self.lock:
            clean = clean_groups(groups)
            self._write("groups.json", clean)
            return clean

    # settings: {grafana, langfuse, repo, owner_key, install_cmd, incus_url, incus_project}: the base addresses of the
    # logs and traces viewers (links only), the GitHub repository the centre keeps its settings in, the SSH add's two
    # settings, and the Incus server's address and project (the centre's own; a repository load keeps them)
    def settings(self):
        data = self._read("settings.json", {})
        return {k: data.get(k, "") if isinstance(data, dict) else "" for k in SETTING_FIELDS}

    def set_settings(self, data):
        with self.lock:
            clean = clean_settings(data)
            self._write("settings.json", clean)
            return clean

    def replace(self, machines, groups, links):
        """the machines, groups and links of a saved file. All is checked before anything is written. A machine
        already here keeps its key; a new one comes in turned off with no key; the repo, owner_key and install_cmd fields stay as they are."""
        with self.lock:
            if not isinstance(links, dict):
                raise Invalid("links: an object")
            clean_m, clean_g = clean_machines(machines), clean_groups(groups)
            cur = self.settings()
            clean_s = clean_settings(dict(links, repo=cur["repo"], owner_key=cur["owner_key"], install_cmd=cur["install_cmd"],
                                          incus_url=cur["incus_url"], incus_project=cur["incus_project"],
                                          ssh_key=cur["ssh_key"], ssh_user=cur["ssh_user"]))
            old, keys = {m["name"] for m in self.machines()}, self.keys()
            for m in clean_m:
                if m["name"] not in old:
                    m["on"] = False
            kept = {m["name"]: keys[m["name"]] for m in clean_m if m["name"] in old and m["name"] in keys}
            self._write("machines.json", clean_m)
            self._write("groups.json", clean_g)
            self._write("settings.json", clean_s)
            self._write("keys.json", kept)
            return clean_m
