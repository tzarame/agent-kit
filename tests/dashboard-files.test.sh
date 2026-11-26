#!/usr/bin/env bash
# tests/dashboard-files.test.sh - dashboard/files.py: the file manager of one folder (PLAN.md "Files").
# No server: the functions are called directly on a temp folder. HOME is a temp folder too.
# Exit 0 when every case passes.
REPO=$(cd "$(dirname "$0")/.." && pwd -P)
T=$(mktemp -d) || exit 1; T=$(cd "$T" && pwd -P); trap 'rm -rf "$T"' EXIT
export HOME="$T/home"; mkdir -p "$HOME" || exit 1
mkdir -p "$T/outside/secret" "$T/root" || exit 1
echo "top secret" > "$T/outside/secret/key.txt"
echo "outside file" > "$T/outside/out.txt"
cat > "$T/case.py" <<'PY'
import os, stat, sys
sys.path.insert(0, os.path.join(sys.argv[1], "dashboard"))
import files

T = sys.argv[2]
ROOT = os.path.join(T, "root")
OUT = os.path.join(T, "outside")
fails = []

def want(name, ok):
    if not ok:
        fails.append(name)
    print(("ok   - " if ok else "FAIL - ") + name)

def kind_of(fn, *args):
    try:
        fn(*args)
    except files.Error as e:
        return e.kind
    return None

def put(rel, data, mode=None):
    p = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "wb") as f:
        f.write(data)
    if mode is not None:
        os.chmod(p, mode)
    return p

def mt(rel):
    return str(os.stat(os.path.join(ROOT, rel)).st_mtime_ns)

# a folder with files, a sub folder, a file with a secret
put("b.txt", b"bee\n")
put("a.md", "# Title\ntext\n".encode())
put("sub/inner.txt", b"inner\n")
put(".git/config", b"[core]\n")
put(".env", b"TOKEN=abc\n")

# list: folders first, then by name; nothing hidden
ents = files.listing(ROOT)
names = [e["name"] for e in ents]
want("list: folders first, then by name, .git and .env shown", names == [".git", "sub", ".env", "a.md", "b.txt"])
sub = [e for e in ents if e["name"] == "sub"][0]
bee = [e for e in ents if e["name"] == "b.txt"][0]
want("list: kind dir and file, size and mtime", sub["kind"] == "dir" and bee["kind"] == "file" and bee["size"] == 4 and bee["mtime"] == mt("b.txt"))
want("list: a sub folder", [e["name"] for e in files.listing(ROOT, "sub")] == ["inner.txt"])

# read
r = files.read(ROOT, "a.md")
want("read: text, mtime as a string of ns, size", r == {"text": "# Title\ntext\n", "mtime": mt("a.md"), "size": 13})

# write with the right mtime
w = files.write(ROOT, "b.txt", "bee changed\n", mt("b.txt"))
want("write: the right mtime saves", open(os.path.join(ROOT, "b.txt")).read() == "bee changed\n" and w["mtime"] == mt("b.txt"))

# write with an old mtime is refused, the file untouched
before = open(os.path.join(ROOT, "b.txt"), "rb").read(), mt("b.txt")
old = str(int(mt("b.txt")) - 1000)
want("write: an old mtime is refused with changed", kind_of(files.write, ROOT, "b.txt", "other\n", old) == "changed")
want("write: the file is untouched after a refusal", (open(os.path.join(ROOT, "b.txt"), "rb").read(), mt("b.txt")) == before)
want("write: a mtime that is not a number is refused", kind_of(files.write, ROOT, "b.txt", "x", "abc") == "changed")

# outside root: refused for read, write, listing
bad = ["../x", "/etc/passwd", "a/../../x", "../outside/out.txt"]
for p in bad:
    want("outside: %s refused for read" % p, kind_of(files.read, ROOT, p) == "outside")
    want("outside: %s refused for write" % p, kind_of(files.write, ROOT, p, "x", None) == "outside")
    want("outside: %s refused for listing" % p, kind_of(files.listing, ROOT, p) == "outside")
want("outside: a NUL in the name refused", kind_of(files.read, ROOT, "a\0b") == "outside")
want("outside: a NUL in the name refused for write", kind_of(files.write, ROOT, "a\0b", "x", None) == "outside")
want("inside: a/../x is allowed", files.inside(ROOT, "sub/../b.txt") == os.path.realpath(os.path.join(ROOT, "b.txt")))

# symlinks
os.symlink(os.path.join(OUT, "out.txt"), os.path.join(ROOT, "link-file"))
os.symlink(os.path.join(T, "outside"), os.path.join(ROOT, "link-dir"))
os.symlink("sub/inner.txt", os.path.join(ROOT, "link-in"))
os.symlink("../../outside/out.txt", os.path.join(ROOT, "sub", "rel-out"))
want("symlink to a file outside: read refused", kind_of(files.read, ROOT, "link-file") == "outside")
want("symlink to a file outside: write refused", kind_of(files.write, ROOT, "link-file", "x", None) == "outside")
want("symlink to a file outside: listing refused", kind_of(files.listing, ROOT, "link-file") == "outside")
want("symlink to a folder outside: listing refused", kind_of(files.listing, ROOT, "link-dir") == "outside")
want("symlink to a folder outside, then a file under it: read refused", kind_of(files.read, ROOT, "link-dir/secret/key.txt") == "outside")
want("symlink to a folder outside, then a file under it: write refused", kind_of(files.write, ROOT, "link-dir/secret/key.txt", "x", None) == "outside")
want("symlink to a folder outside, then a file under it: listing refused", kind_of(files.listing, ROOT, "link-dir/secret") == "outside")
want("relative symlink to outside: read refused", kind_of(files.read, ROOT, "sub/rel-out") == "outside")
want("the link to outside is shown as a link in listing", [e for e in files.listing(ROOT) if e["name"] == "link-dir"][0]["kind"] == "link")
want("symlink inside root is followed: read", files.read(ROOT, "link-in")["text"] == "inner\n")
w = files.write(ROOT, "link-in", "via link\n", mt("sub/inner.txt"))
want("symlink inside root is followed: write goes to the target, the link stays",
     open(os.path.join(ROOT, "sub", "inner.txt")).read() == "via link\n" and os.path.islink(os.path.join(ROOT, "link-in")))

# binary, too large
put("bin.dat", b"abc\0def")
put("latin.txt", b"caf\xe9\n")
want("binary: a NUL in the first 8 KB refused", kind_of(files.read, ROOT, "bin.dat") == "binary")
want("binary: not UTF-8 refused", kind_of(files.read, ROOT, "latin.txt") == "binary")
put("big.txt", b"a" * (files.LIMIT + 1))
put("edge.txt", b"a" * files.LIMIT)
want("too large: more than 1 MB refused for read", kind_of(files.read, ROOT, "big.txt") == "too_large")
want("too large: exactly 1 MB is read", len(files.read(ROOT, "edge.txt")["text"]) == files.LIMIT)
want("too large: more than 1 MB refused for write", kind_of(files.write, ROOT, "a.md", "a" * (files.LIMIT + 1), mt("a.md")) == "too_large")
want("binary: a NUL in the text refused for write", kind_of(files.write, ROOT, "a.md", "a\0b", mt("a.md")) == "binary")

# folders and other kinds
want("a folder: read refused with not_file", kind_of(files.read, ROOT, "sub") == "not_file")
want("a folder: write refused with not_file", kind_of(files.write, ROOT, "sub", "x", mt("sub")) == "not_file")
want("a file: listing refused with not_file", kind_of(files.listing, ROOT, "a.md") == "not_file")
want("a missing file: read refused with missing", kind_of(files.read, ROOT, "nope.txt") == "missing")
want("a missing folder: listing refused with missing", kind_of(files.listing, ROOT, "nope") == "missing")

# mode is kept
p = put("secret.env", b"KEY=1\n", mode=0o600)
files.write(ROOT, "secret.env", "KEY=2\n", mt("secret.env"))
want("mode: 600 stays 600 after a save", stat.S_IMODE(os.stat(p).st_mode) == 0o600 and open(p).read() == "KEY=2\n")

# new files
w = files.write(ROOT, "new.txt", "fresh\n", None)
want("new file: made when none is there", open(os.path.join(ROOT, "new.txt")).read() == "fresh\n" and w["mtime"] == mt("new.txt"))
want("new file: over an existing one refused with exists", kind_of(files.write, ROOT, "new.txt", "again\n", None) == "exists")
want("new file: the existing one is untouched", open(os.path.join(ROOT, "new.txt")).read() == "fresh\n")
want("new file: in a folder that does not exist refused with missing", kind_of(files.write, ROOT, "no/such/x.txt", "x", None) == "missing")
leftovers = [n for n in os.listdir(ROOT) if n.startswith(".tmp-")]
want("no temporary file is left in the folder", leftovers == [])

if fails:
    print("\n".join(fails))
sys.exit(1 if fails else 0)
PY
out=$(python3 -I "$T/case.py" "$REPO" "$T" 2>&1); rc=$?
echo "$out"
PASS=$(printf '%s\n' "$out" | grep -c '^ok   - ')
FAIL=$(printf '%s\n' "$out" | grep -c '^FAIL - ')
[ "$rc" = 0 ] || [ "$FAIL" != 0 ] || FAIL=1
echo "passed $PASS, failed $FAIL"; [ "$FAIL" = 0 ]
