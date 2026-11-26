"""io.py - what the kit does outside the code, for the sessions and the set-up's files: the paths under
~/.config/agent-kit and of Claude Code, the plugins' folders, the processes (tmux, gh, install/gh-app.sh, claude), a
file written whole, the terminal, the clock and kit.log. A test gives a subclass with a sandbox home and fake
processes. Standard library only."""
import datetime, json, os, pwd, re, secrets, subprocess, sys

from kit import config, files

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # the kit's repository
ID_CHARS = "abcdefghijklmnopqrstuvwxyz0123456789"
LOG_MAX = 1 << 20                                   # above 1 MiB, kit.log is moved to kit.log.1
# what install/gh-app.sh env sets; an inherited one would make it print nothing, or count from it
MACHINE_VARS = ("AGENT_KIT_MACHINE", "GIT_CONFIG_COUNT")
GIT_PAIR = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")


def why(e):
    """the message of an error: of an OSError, the file and the system's words"""
    if isinstance(e, OSError) and e.strerror:
        return "%s: %s" % (e.filename, e.strerror) if e.filename else e.strerror
    return str(e)


class Io:
    def __init__(self, environ=None, home=None):
        self.environ = dict(os.environ if environ is None else environ)
        self.home = home or self.environ.get("HOME") or os.path.expanduser("~")
        self.kit = ROOT
        self.main = os.path.join(ROOT, "kit", "__main__.py")
        self.python = sys.executable or "python3"
        self.conf = os.path.join(self.home, ".config", "agent-kit")
        self.config = os.path.join(self.conf, "config.json")
        self.sessions = os.path.join(self.conf, "sessions")
        self.engines = os.path.join(self.conf, "engines")   # the engines' own files, ENGINE/ID each session
        self.log_path = os.path.join(self.conf, "kit.log")
        # the root folder of the projects: AGENT_KIT_ROOT, else the home folder
        self.root = os.path.abspath(self.expand(self.environ.get("AGENT_KIT_ROOT") or self.home))
        self.shared = os.path.join(self.home, ".local", "share", "agent-kit", "plugins")
        # the machine's own agents and plugins: no update reads or writes them
        self.own = self.conf
        self.command = os.path.join(self.home, ".local", "bin", "kit")
        self.bashrc = os.path.join(self.home, ".bashrc")
        # the user's unit of the autostart, in the user's own folder of units, and the link that enables it
        units = os.path.join(self.home, ".local", "share", "systemd", "user")
        self.unit = os.path.join(units, "kit-autostart.service")
        self.unit_link = os.path.join(units, "default.target.wants", "kit-autostart.service")
        # Claude Code's own files that the set-up writes a few keys of
        self.claude_state = os.path.join(self.home, ".claude.json")
        self.claude_settings = os.path.join(self.home, ".claude", "settings.json")
        self.out, self.err, self.inp = sys.stdout, sys.stderr, sys.stdin

    def expand(self, path):
        """the path with a leading ~ as the home folder"""
        if path == "~" or path.startswith("~/"):
            return self.home + path[1:]
        return path

    def session_file(self, sid):
        return os.path.join(self.sessions, sid + ".json")

    def mcp_file(self, sid):
        """the MCP servers of the session, given by --mcp-config"""
        return os.path.join(self.sessions, sid + ".mcp.json")

    def content(self):
        """the folder the config names to be read over the kit's content/ (content.dir), or None. A config that
        cannot be read gives None: the start reads it again and names the fault"""
        try:
            named = (config.read_json(self.config).get("content") or {}).get("dir")
        except (OSError, config.ConfigError, AttributeError):
            named = None
        return self.expand(named) if isinstance(named, str) and named.startswith(("/", "~/")) else None

    def sources(self):
        """the folders that may hold plugins/ and agents/, a later one over an earlier: the old place of the machine's
        own, the kit's content/, the folder the config names, the machine's own"""
        return [s for s in (os.path.dirname(self.shared), os.path.join(self.kit, "content"), self.content(), self.own)
                if s]

    def plugins(self):
        """{name: folder} of the plugins of the sources; a folder is a plugin when it has .claude-plugin/plugin.json"""
        found = {}
        for top in (os.path.join(s, "plugins") for s in self.sources()):
            for n in sorted(os.listdir(top)) if os.path.isdir(top) else ():
                p = os.path.join(top, n)
                if os.path.isfile(os.path.join(p, ".claude-plugin", "plugin.json")):
                    found[n] = p
        return found

    def talked(self, folder):
        """whether Claude Code has a conversation of the folder: a .jsonl file in its projects/NAME, where NAME is
        the folder's path with - for each character that is not a letter or a digit"""
        base = self.environ.get("CLAUDE_CONFIG_DIR") or os.path.join(self.home, ".claude")
        try:
            names = os.listdir(os.path.join(base, "projects", re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(folder))))
        except OSError:
            return False
        return any(n.endswith(".jsonl") for n in names)

    def agent_files(self):
        """{name: its file} of the agents of the sources: agents/NAME.json of each"""
        found = {}
        for top in self.sources():
            folder = os.path.join(top, "agents")
            for n in sorted(os.listdir(folder)) if os.path.isdir(folder) else ():
                if n.endswith(".json") and config.NAME.fullmatch(n[:-5]):
                    found[n[:-5]] = os.path.join(folder, n)
        return found

    def agent(self, name):
        """the description of a source's agent, checked, or None when no source has it. A file's field that is not
        a path from / or ~/ is a path from the folder agents/, and may not leave the source. ConfigError names the
        file and the field"""
        path = self.agent_files().get(name)
        if path is None:
            return None
        doc, folder = config.read_json(path), os.path.dirname(path)
        # the machine's own agents lie beside its keys: their files stay in agents/ itself
        own = os.path.realpath(folder) == os.path.realpath(os.path.join(self.own, "agents"))
        root = os.path.realpath(folder if own else os.path.dirname(folder))
        for field in config.FILES:
            v = doc.get(field)
            if isinstance(v, str) and v and not v.startswith(("/", "~/")):
                real = os.path.realpath(os.path.join(folder, v))
                if not real.startswith(root + os.sep):
                    raise config.ConfigError("%s: %s: %s: a file outside the source" % (path, field, v))
                doc[field] = real
        return config.agent_fields(doc, path)

    @staticmethod
    def _text(path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def machine_text(self):
        """what `install/gh-app.sh env` prints: lines of export for GitHub as the App, none when the machine has no
        App's key. The inherited variables it sets are left out of its run. OSError when it fails"""
        env = {k: v for k, v in self.environ.items() if k not in MACHINE_VARS and not k.startswith(GIT_PAIR)}
        try:
            r = subprocess.run(["bash", os.path.join(self.kit, "install", "gh-app.sh"), "env"], env=env,
                               stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            raise OSError("install/gh-app.sh env: no answer in 30 seconds")
        if r.returncode != 0:
            raise OSError("install/gh-app.sh env: %s" % (r.stderr.strip() or "exit code %d" % r.returncode))
        return r.stdout

    def claude_version(self):
        """the version Claude Code says, its first word; None when it is not installed or does not answer"""
        try:
            r = subprocess.run(["claude", "--version"], env=self.environ, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None
        words = r.stdout.split()
        return words[0] if r.returncode == 0 and words else None

    def claude(self, args, cwd):
        """claude with these words in the folder cwd: (its exit code, its output, its errors)"""
        try:
            r = subprocess.run(["claude"] + list(args), cwd=cwd, env=self.environ, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=120)
        except FileNotFoundError:
            return 127, "", "claude is not installed\n"
        except subprocess.TimeoutExpired:
            return 1, "", "claude: no answer in 120 seconds\n"
        return r.returncode, r.stdout, r.stderr

    def read(self, path):
        """the file's text; None when there is no file"""
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return None

    def put(self, path, text, mode=None):
        """the file at path with this text, written whole: a new file in its folder, moved into place; a link's
        target is written, so the link stays. Its mode is mode, else that of the file there, else 600"""
        path = os.path.realpath(path)
        if mode is None:
            try:
                mode = os.stat(path).st_mode & 0o7777
            except FileNotFoundError:
                mode = 0o600
        files.put(path, text.encode("utf-8"), mode)

    def exists(self, path):
        """whether there is a file, a folder or a link at path, also a link to nothing"""
        return os.path.lexists(path)

    def link(self, path, target):
        """a link at path to target, its folder made"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        os.symlink(target, path)

    def linger(self):
        """(the user's name, whether the user's units run from the machine's start with no login: the mark that
        loginctl enable-linger leaves)"""
        name = pwd.getpwuid(os.getuid()).pw_name
        return name, os.path.exists(os.path.join("/var/lib/systemd/linger", name))

    def append(self, path, text):
        """the text added at the end of the file at path (a link's target), which is made with mode 644 (less the
        umask) when there is none"""
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(text)

    def clone(self, repo, folder, env):
        """gh repo clone REPO FOLDER on the terminal; its exit code"""
        return subprocess.run(["gh", "repo", "clone", repo, folder], env=env).returncode

    def tmux(self, args, cwd=None):
        """tmux with these words: (its exit code, its output, its errors)"""
        try:
            r = subprocess.run(["tmux"] + list(args), cwd=cwd, env=self.environ, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True)
        except FileNotFoundError:
            return 127, "", "tmux is not installed"
        return r.returncode, r.stdout, r.stderr

    def has_session(self, sid):
        return self.tmux(["has-session", "-t", "=" + sid])[0] == 0

    def new_id(self):
        return "".join(secrets.choice(ID_CHARS) for _ in range(4))

    def now(self):
        return datetime.datetime.now().astimezone().isoformat(timespec="seconds")

    def tty(self):
        return self.inp.isatty() and self.out.isatty()

    def wait(self):
        self.inp.readline()

    def remove(self, path):
        """the file removed; False when it was not there"""
        try:
            os.unlink(path)
        except FileNotFoundError:
            return False
        return True

    def chdir(self, folder):
        os.chdir(folder)

    def exec(self, argv, env):
        """the process replaced by argv, found on env's PATH; returns only by an OSError, which names argv[0]"""
        try:
            os.execvpe(argv[0], argv, env)
        except OSError as e:
            raise OSError(e.errno, e.strerror, argv[0]) from None

    def log(self, record):
        """the record as one line of JSON, the time first, added to kit.log (mode 600); kit.log is moved to kit.log.1
        when it is above 1 MiB"""
        line = json.dumps(dict({"time": self.now()}, **record), ensure_ascii=False, separators=(",", ":")) + "\n"
        os.makedirs(self.conf, mode=0o700, exist_ok=True)
        try:
            if os.path.getsize(self.log_path) > LOG_MAX:
                os.replace(self.log_path, self.log_path + ".1")
        except FileNotFoundError:
            pass
        fd = os.open(self.log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as f:
            f.write(line)
