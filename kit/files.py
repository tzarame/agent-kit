"""files.py - a file written whole: a new file in the folder of its path, then moved into place, so a reader sees the
old file or the new one, never a part. The config, the sessions' configs and the set-up's files are written with it.
Standard library only."""
import os, tempfile


def new_file(path, data, mode=0o600):
    """a file of this mode with these bytes in path's folder, not yet in place; its path"""
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", dir=folder)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
    except BaseException:
        os.unlink(tmp)
        raise
    return tmp


def put(path, data, mode=0o600):
    """the file at path with these bytes and this mode, written whole: a new file moved into place."""
    tmp = new_file(path, data, mode)
    try:
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
