"""notes.py - the notes of a folder (CONTRACT.md "Notes"). For a folder in a git repository: NOTES.md on the branch
notes of that repository, in a working copy of its own made with git worktree, so the agent's working tree and its
branch are never touched. For a folder with no repository: a plain NOTES.md in the same place, no git.
Plain functions, no HTTP: http_api.py calls them."""
import hashlib, os, subprocess, tempfile, threading, time

BRANCH = "notes"
FILE = "NOTES.md"
MAX_BYTES = 1024 * 1024
PULL_GAP = 60          # seconds: a read pulls at most this often
GIT_TIMEOUT = 15
PULL_TIMEOUT = 15
PUSH_TIMEOUT = 20
AUTHOR = ("agent-kit", "agent-kit@localhost")   # when the repository sets no identity
ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0")
LOCKS = {}             # one lock per working copy
LOCKS_GUARD = threading.Lock()
LAST_PULL = {}         # working copy -> time of its last pull


class Refused(ValueError):
    pass


class Failed(RuntimeError):
    pass


def _git(cwd, args, timeout=GIT_TIMEOUT):
    """one git call, args as a list; returns (rc, stdout). A timeout or a missing git is rc 1."""
    try:
        r = subprocess.run(["git", "-C", cwd] + args, capture_output=True, text=True, errors="replace",
                           timeout=timeout, env=ENV)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return r.returncode, r.stdout.strip()


def _top(folder):
    rc, out = _git(folder, ["rev-parse", "--show-toplevel"])
    return out if rc == 0 and out else None


def _where(folder, home):
    """the working copy of the folder's notes, and the repository's top (None when the folder has none)"""
    top = _top(folder)
    key = os.path.realpath(top or folder)
    name = os.path.basename(key.rstrip("/")) or "root"
    sha = hashlib.sha1(os.fsencode(key)).hexdigest()[:8]
    return os.path.join(home, ".local", "share", "agent-kit", "notes", "%s-%s" % (name, sha)), top


def place(folder, home):
    """-> (the notes' working copy path, whether the folder is in a git repository)"""
    path, top = _where(folder, home)
    return path, top is not None


def _lock(path):
    with LOCKS_GUARD:
        return LOCKS.setdefault(path, threading.Lock())


def _remote(top):
    return _git(top, ["remote", "get-url", "origin"])[0] == 0


def _author(cwd):
    """-c for the identity the repository does not set"""
    args = []
    for key, value in (("user.name", AUTHOR[0]), ("user.email", AUTHOR[1])):
        rc, out = _git(cwd, ["config", key])
        if rc != 0 or not out:
            args += ["-c", "%s=%s" % (key, value)]
    return args


def _ensure(top, path):
    """the working copy of the notes, made on first use: the branch from its local copy or from origin, else an
    orphan branch with an empty first commit"""
    if os.path.isfile(os.path.join(path, ".git")):
        return
    has_local = _git(top, ["rev-parse", "--verify", "-q", "refs/heads/" + BRANCH])[0] == 0
    if not has_local and _remote(top):
        found = _git(top, ["ls-remote", "--exit-code", "--heads", "origin", BRANCH], PULL_TIMEOUT)[0] == 0
        if found:
            rc, out = _git(top, ["fetch", "-q", "origin", "%s:refs/heads/%s" % (BRANCH, BRANCH)], PULL_TIMEOUT)
            if rc != 0:
                raise Failed("fetch of the notes failed: " + out)
            has_local = True
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if has_local:
        rc, out = _git(top, ["worktree", "add", path, BRANCH])
        if rc != 0:
            raise Failed("worktree of the notes failed: " + out)
        return
    rc, out = _git(top, ["worktree", "add", "--orphan", "-b", BRANCH, path])
    if rc != 0 and not os.path.exists(path):   # an old git without --orphan
        rc, out = _git(top, ["worktree", "add", "--detach", path])
        if rc == 0:
            rc, out = _git(path, ["checkout", "-q", "--orphan", BRANCH])
        if rc == 0:
            _git(path, ["rm", "-r", "-q", "--cached", "."])   # no files of the project in the notes
            _git(path, ["clean", "-q", "-f", "-d"])
    if rc != 0:
        raise Failed("worktree of the notes failed: " + out)
    rc, out = _git(path, _author(path) + ["commit", "-q", "--allow-empty", "-m", "Notes: start"])
    if rc != 0:
        raise Failed("first commit of the notes failed: " + out)


def _pull(top, path, gap):
    """fast-forward only, at most once per gap seconds; a failed pull is not an error for the reader"""
    now = time.time()
    if now - LAST_PULL.get(path, 0) < gap or not _remote(top):
        return
    LAST_PULL[path] = now
    _git(path, ["pull", "-q", "--ff-only", "origin", BRANCH], PULL_TIMEOUT)


def _saved(path):
    """the time of the last commit of the notes, or None"""
    rc, out = _git(path, ["log", "-1", "--format=%ct", "--", FILE])
    return int(out) if rc == 0 and out else None


def _load(file):
    try:
        with open(file, encoding="utf-8", errors="replace") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _mtime(file):
    try:
        return int(os.path.getmtime(file))
    except OSError:
        return None


def _write_atomic(file, data):
    """atomic: a temporary file in the same folder, then renamed over the old one"""
    folder = os.path.dirname(file)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-", suffix=".md")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, file)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read(folder, home, gap=PULL_GAP):
    """-> {"text": str, "saved": time of the last save or None}"""
    path, top = _where(folder, home)
    file = os.path.join(path, FILE)
    if top is None:
        return {"text": _load(file), "saved": _mtime(file)}
    with _lock(path):
        _ensure(top, path)
        _pull(top, path, gap)
        return {"text": _load(file), "saved": _saved(path)}


def write(folder, home, text):
    """-> {"saved": time, and "pushed": true or false when the repository has an origin}"""
    if not isinstance(text, str):
        raise Refused("text: text needed")
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError:
        raise Refused("text: valid UTF-8 needed")
    if len(data) > MAX_BYTES:
        raise Refused("text: up to 1 MB")
    if "\0" in text:
        raise Refused("text: no NUL characters")
    path, top = _where(folder, home)
    if top is None:
        with _lock(path):
            _write_atomic(os.path.join(path, FILE), data)
        return {"saved": int(time.time())}
    with _lock(path):
        _ensure(top, path)
        _write_atomic(os.path.join(path, FILE), data)
        if _git(path, ["add", FILE])[0] != 0:
            raise Failed("git add of the notes failed")
        rc = _git(path, ["diff", "--cached", "--quiet", "--", FILE])[0]
        if rc not in (0, 1):
            raise Failed("git diff of the notes failed")
        if rc == 1:
            rc, out = _git(path, _author(path) + ["commit", "-q", "-m", "Notes"])
            if rc != 0:
                raise Failed("commit of the notes failed: " + out)
            saved = int(time.time())
        else:
            saved = _saved(path) or int(time.time())
        if not _remote(top):
            return {"saved": saved}
        rc, _ = _git(path, ["push", "-q", "origin", BRANCH], PUSH_TIMEOUT)
        if rc != 0:
            # another machine saved first: put this save on top of its one and push again; on a clash leave it local
            if _git(path, _author(path) + ["pull", "-q", "--rebase", "origin", BRANCH], PULL_TIMEOUT)[0] == 0:
                rc, _ = _git(path, ["push", "-q", "origin", BRANCH], PUSH_TIMEOUT)
            else:
                _git(path, ["rebase", "--abort"])
        return {"saved": saved, "pushed": rc == 0}
