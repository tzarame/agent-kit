"""files.py - a file manager for ONE folder: the folder an agent runs in (PLAN.md "Files", CONTRACT.md "Local dashboard").
Every path is checked by inside() first: relative, no way out of the root, symlinks followed and compared as real
paths. Nothing is hidden: files with secrets are listed and read, as the owner decided.
Times are given as strings of st_mtime_ns: a JS number would lose the last digits.
Errors are one class, Error, with a kind: outside, missing, changed, too_large, binary, not_file, exists."""
import os, stat, tempfile

LIMIT = 1024 * 1024   # text up to 1 MB
SNIFF = 8192          # a NUL in the first 8 KB makes a file binary
NEW_MODE = 0o644      # the mode of a file made by write()


class Error(Exception):
    def __init__(self, kind, message=""):
        super().__init__(message or kind)
        self.kind = kind


def inside(root, path):
    """The real absolute path of path (relative to root). Raises Error("outside") when it leaves root."""
    if not isinstance(path, str) or "\0" in path:
        raise Error("outside", "a NUL in the name")
    if os.path.isabs(path):
        raise Error("outside", "an absolute path")
    real_root = os.path.realpath(root)
    real = os.path.realpath(os.path.join(real_root, path))
    if real != real_root and not real.startswith(real_root + os.sep):
        raise Error("outside", "the path leaves the folder")
    return real


def listing(root, path=""):
    """The entries of a folder: [{"name","kind","size","mtime"}], folders first, then by name.
    kind is dir, file or link (a link is not entered here; read and listing follow it through inside())."""
    real = inside(root, path)
    if not os.path.exists(real):
        raise Error("missing", "no such folder")
    if not os.path.isdir(real):
        raise Error("not_file", "not a folder")
    out = []
    with os.scandir(real) as it:
        for e in it:
            try:
                st = os.lstat(e.path)
            except FileNotFoundError:
                continue   # gone since the scan
            if stat.S_ISLNK(st.st_mode):
                kind = "link"
            elif stat.S_ISDIR(st.st_mode):
                kind = "dir"
            else:
                kind = "file"
            out.append({"name": e.name, "kind": kind, "size": st.st_size, "mtime": str(st.st_mtime_ns)})
    return sorted(out, key=lambda x: (x["kind"] != "dir", x["name"]))


def read(root, path):
    """{"text","mtime","size"} of a text file up to 1 MB, UTF-8. Line endings are kept as they are."""
    real = inside(root, path)
    try:
        fd = os.open(real, os.O_RDONLY | os.O_NONBLOCK)   # no wait on a FIFO; a folder opens, then is refused
    except FileNotFoundError:
        raise Error("missing", "no such file")
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        os.close(fd)
        raise Error("not_file", "not a file")
    with os.fdopen(fd, "rb") as f:
        data = f.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise Error("too_large", "more than 1 MB")
    if b"\0" in data[:SNIFF]:
        raise Error("binary", "a binary file")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Error("binary", "not UTF-8")
    return {"text": text, "mtime": str(st.st_mtime_ns), "size": st.st_size}


def write(root, path, text, mtime):
    """Saves text when the file's mtime is still `mtime` (a string of st_mtime_ns, as read gave it).
    mtime None makes a new file, only when no file is there. Atomic: a temporary file in the same folder, then
    os.replace. A symlink is followed: its target inside root is written, the link stays. Returns {"mtime"}."""
    if not isinstance(text, str):
        raise Error("binary", "text needed")
    data = text.encode("utf-8")
    if len(data) > LIMIT:
        raise Error("too_large", "more than 1 MB")
    if b"\0" in data:
        raise Error("binary", "a NUL in the text")
    real = inside(root, path)
    folder = os.path.dirname(real)
    if not os.path.isdir(folder):
        raise Error("missing", "no such folder")
    try:
        st = os.stat(real)
    except FileNotFoundError:
        st = None
    if mtime is None:
        if st is not None:
            raise Error("exists", "a file is there")
        mode = NEW_MODE
    else:
        if st is None:
            raise Error("changed", "the file is gone")
        if not stat.S_ISREG(st.st_mode):
            raise Error("not_file", "not a file")
        try:
            wanted = int(mtime)
        except (TypeError, ValueError):
            raise Error("changed", "the mtime is not a number")
        if wanted != st.st_mtime_ns:
            raise Error("changed", "the file changed")
        mode = stat.S_IMODE(st.st_mode)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-", suffix=".save")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, real)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return {"mtime": str(os.stat(real).st_mtime_ns)}
