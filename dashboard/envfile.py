"""envfile.py - the reader of the dashboard's own KEY=value files (dashboard.env, telemetry.env): read with shlex,
one word a value."""
import shlex


class Invalid(ValueError):
    pass


def _values(text):
    """KEY=value lines to a dict of raw strings; comments and blank lines skipped."""
    out = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, eq, rest = line.partition("=")
        if not eq:
            raise Invalid("a line with no =")
        try:
            words = shlex.split(rest)
        except ValueError:
            raise Invalid("a value that cannot be read")
        if len(words) > 1:
            raise Invalid("%s: more than one word" % key)
        out[key.strip()] = words[0] if words else ""
    return out


def read_env(path):
    """The raw KEY=value file of the kit (dashboard.env and the like): a dict of strings, {} when missing."""
    try:
        with open(path, encoding="utf-8") as f:
            return _values(f.read())
    except FileNotFoundError:
        return {}
