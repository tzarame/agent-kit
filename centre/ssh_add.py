"""ssh_add.py - add a machine over SSH. A FIRST VERSION, not yet tried on a real machine.

The centre keeps its own ed25519 key (ensure_key), signs in to the machine once (with a password through SSH_ASKPASS,
or with the key when the machine has it), puts the centre's public key and, when the settings hold one, the owner's
public key into the user's authorized_keys, runs the kit's install command, reads the dashboard's API key with
`dash.py key`, and adds the machine to the store, turned on. plan() gives the steps as data; run() runs them with the
ssh program, arguments as a list and no shell on the centre's side. Nothing is added unless every step passed. run()
never raises: {"ok": true, "machine", "steps"} or {"ok": false, "error", "steps"}.
Not in this version: making the user, sudo or root, a machine made by Incus, a dashboard on another port than the
default (8765), a second try of a failed run (the owner starts it again)."""
import contextlib, os, re, secrets, shlex, shutil, subprocess, tempfile
import store

KEY_FOLDER = ("agent-kit", "centre", "ssh")   # under the home: ~/.config/agent-kit/centre/ssh
KEY_FILE = "id_ed25519"
INSTALL_CMD = ("curl -fsSL https://raw.githubusercontent.com/OWNER/agent-plugins/main/claude/install/install.sh "
               "-o install.sh && chmod +x install.sh && ./install.sh && ~/start.sh")
DASH_KEY_CMD = "python3 ~/.agent-kit/dashboard/dash.py key"
DASH_PORT = 8765   # the dashboard's default port (dashboard/dash.py); the store's address needs a port
DEFAULT_USER = "agent"
SHORT, LONG = 20, 900   # seconds: a small step, the install
ERR_MAX = 200
ADDRESS_RE = re.compile(r"[A-Za-z0-9.:-]{1,253}")
USER_RE = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
API_KEY_RE = re.compile(r"[A-Za-z0-9._~+/=-]{8,256}")


class Failed(Exception):
    """a step that cannot be done; its text is the answer's error"""


def ssh_program():
    return os.environ.get("CENTRE_SSH") or "ssh"


def ssh_keygen_program():
    return os.environ.get("CENTRE_SSH_KEYGEN") or "ssh-keygen"


def short(text):
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    return (lines[-1] if lines else "ssh failed")[:ERR_MAX]


def install_command(settings):
    """the command the SSH add runs on the machine: the owner's install_cmd when set, else INSTALL_CMD"""
    return settings.get("install_cmd") or INSTALL_CMD


def check_host(text):
    if not isinstance(text, str) or text.startswith("-") or not ADDRESS_RE.fullmatch(text):
        raise store.Invalid("the address: a host name or an IP address, letters, digits, dots, colons and dashes")
    return text


def check_user(text):
    if not isinstance(text, str) or not USER_RE.fullmatch(text):
        raise store.Invalid("the user: lower case letters, digits, underscore and dash; not starting with a digit")
    return text


def check_password(text):
    if text is None or text == "":
        return None
    if not isinstance(text, str) or len(text) > 1024 or any(c in text for c in "\r\n\0"):
        raise store.Invalid("the password: one line of text")
    return text


def check_request(st, name, address, user, password):
    """the four values of the form, checked before any ssh runs: -> (name, host, user, password)"""
    name = store.check_name(name)
    if st.machine(name) is not None:
        raise store.Invalid("a machine named %s is there already" % name)
    host = check_host(address)
    user = check_user(DEFAULT_USER if user in (None, "") else user)
    return name, host, user, check_password(password)


def dashboard_address(host):
    """the store's address of the dashboard on a host: http://HOST:8765 (brackets for an IPv6 address)"""
    return "http://[%s]:%d" % (host, DASH_PORT) if ":" in host else "http://%s:%d" % (host, DASH_PORT)


def key_paths(home):
    folder = os.path.join(home, ".config", *KEY_FOLDER)
    return folder, os.path.join(folder, KEY_FILE)


def ensure_key(home):
    """the centre's ed25519 key, made once; -> its public key line. The private key stays in its folder (mode 600)."""
    folder, priv = key_paths(home)
    try:
        os.makedirs(folder, mode=0o700, exist_ok=True)
        os.chmod(folder, 0o700)
        if not os.path.exists(priv):
            p = subprocess.run([ssh_keygen_program(), "-t", "ed25519", "-N", "", "-C", "agent-kit-centre", "-f", priv],
                               capture_output=True, text=True, timeout=SHORT, stdin=subprocess.DEVNULL)
            if p.returncode != 0:
                raise Failed("ssh-keygen: " + short(p.stderr))
        os.chmod(priv, 0o600)
        with open(priv + ".pub", encoding="utf-8") as f:
            pub = f.read().strip()
    except (OSError, subprocess.SubprocessError) as e:
        raise Failed("the centre's key could not be made: %s" % type(e).__name__)
    if not pub.startswith("ssh-"):
        raise Failed("the centre's public key is not readable")
    return pub


def authorize_cmd(pub):
    """the remote command that puts one public key line in the user's authorized_keys, once"""
    q = shlex.quote(pub)
    return ("mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
            " && (grep -qxF -- %s ~/.ssh/authorized_keys || echo %s >> ~/.ssh/authorized_keys)" % (q, q))


def plan(address, user, install_cmd, centre_key, owner_key=""):
    """the steps as data, in order. sign_in: the step that may use the password (the two keys). Pure: no ssh here."""
    check_host(address)
    check_user(user)
    install_cmd = store.check_install_cmd(install_cmd) or INSTALL_CMD
    steps = [{"step": "authorize centre key", "remote": authorize_cmd(centre_key), "timeout": SHORT, "sign_in": True}]
    if owner_key:
        steps.append({"step": "authorize owner key", "remote": authorize_cmd(store.check_owner_key(owner_key)),
                      "timeout": SHORT, "sign_in": True})
    steps.append({"step": "install", "remote": install_cmd, "timeout": LONG, "sign_in": False})
    steps.append({"step": "read key", "remote": DASH_KEY_CMD, "timeout": SHORT, "sign_in": False})
    return steps


def ssh_argv(host, user, step, key, password):
    """the ssh command of one step: with the key (BatchMode), or for a sign-in with a password (askpass)"""
    argv = [ssh_program(), "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10"]
    if step["sign_in"] and password:
        argv += ["-o", "PreferredAuthentications=password,keyboard-interactive", "-o", "PubkeyAuthentication=no"]
    else:
        argv += ["-o", "BatchMode=yes", "-i", key]
    return argv + [user + "@" + host, "--", step["remote"]]


@contextlib.contextmanager
def sign_in_helper(password):
    """a temp folder (mode 700) with the password in a file (mode 600) and a helper that prints it for SSH_ASKPASS.
    The folder is removed when the block ends, whatever happened."""
    folder = tempfile.mkdtemp(prefix="agent-kit-ssh-")
    try:
        pw, helper = os.path.join(folder, "password"), os.path.join(folder, "askpass")
        fd = os.open(pw, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(password)
        fd = os.open(helper, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\nexec cat %s\n" % shlex.quote(pw))
        yield helper
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def run_step(host, user, step, key, password, helper):
    """-> (ok, error text, stdout). Never raises."""
    use_password = step["sign_in"] and bool(password)
    env = dict(os.environ)
    if use_password:
        env.update({"SSH_ASKPASS": helper, "SSH_ASKPASS_REQUIRE": "force"})
    try:
        p = subprocess.run(ssh_argv(host, user, step, key, password), capture_output=True, text=True,
                           timeout=step["timeout"], stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        return False, "timed out after %d seconds" % step["timeout"], ""
    except OSError:
        return False, "ssh could not run", ""
    if p.returncode != 0:
        return False, short(p.stderr) if p.stderr.strip() else "ssh failed with code %d" % p.returncode, ""
    return True, "", p.stdout


def run(st, home, name, address, user, password=None, progress=None):
    """add a machine over SSH (see the module's docstring). st: the store; home: the home folder; progress: called
    with each step's record as it is done. -> the answer dict; never raises."""
    steps = []
    secret = [password or ""]

    def say(text):
        # the password never reaches an answer, an error text or a step
        text = text.replace(secret[0], "***") if secret[0] else text
        return text[:ERR_MAX]

    def record(item):
        steps.append(item)
        if progress:
            progress(dict(item))

    def fail(step, text):
        record({"step": step, "ok": False, "error": say(text)})
        return {"ok": False, "error": say(text), "steps": steps}

    try:
        name, host, user, password = check_request(st, name, address, user, password)
        secret[0] = password or ""
        pub = ensure_key(home)
        settings = st.settings()
        key = key_paths(home)[1]
        with (sign_in_helper(password) if password else contextlib.nullcontext(None)) as helper:
            for step in plan(host, user, install_command(settings), pub, settings["owner_key"]):
                ok, text, out = run_step(host, user, step, key, password, helper)
                if not ok:
                    return fail(step["step"], text)
                if step["step"] == "read key":
                    lines = [x.strip() for x in out.splitlines() if x.strip()]
                    api_key = lines[-1] if lines else ""
                    if not API_KEY_RE.fullmatch(api_key):
                        return fail(step["step"], "the dashboard answered no key")
                record({"step": step["step"], "ok": True})
        st.add(name, dashboard_address(host), api_key)
        record({"step": "add machine", "ok": True})
        return {"ok": True, "machine": name, "steps": steps}
    except store.Invalid as e:
        return {"ok": False, "error": say(str(e)), "steps": steps}
    except Failed as e:
        return {"ok": False, "error": say(str(e)), "steps": steps}
    except Exception as e:   # the answer is never a traceback; the error names the kind only
        return {"ok": False, "error": say("the SSH add stopped: %s" % type(e).__name__), "steps": steps}
