#!/usr/bin/env bash
# tests/dashboard-notes.test.sh - dashboard/notes.py: the notes of a folder (CONTRACT.md "Notes"): the branch notes in a
# working copy of its own, the pull before a read, the push after a save, a plain file for a folder with no repository.
# Real git in a temp folder, the origin is a bare repository in the same folder. HOME is a temp folder.
# Exit 0 when every case passes.
REPO=$(cd "$(dirname "$0")/.." && pwd -P)
T=$(mktemp -d) || exit 1; T=$(cd "$T" && pwd -P); trap 'rm -rf "$T"' EXIT
export HOME="$T/home"; mkdir -p "$HOME" || exit 1
export GIT_CONFIG_NOSYSTEM=1
cat > "$T/case.py" <<'PY'
import os, subprocess, sys
sys.path.insert(0, os.path.join(sys.argv[1], "dashboard"))
import notes

T, HOME = sys.argv[2], os.environ["HOME"]
fails = []
def check(name, cond):
    print(("ok   - " if cond else "FAIL - ") + name)
    if not cond:
        fails.append(name)
def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True)
def out(cwd, *args):
    return git(cwd, *args).stdout.strip()
def refused(f):
    try:
        f()
    except notes.Refused:
        return True
    return False

# a repository with one commit on main (the owner's identity is in the commit only, not in the config), and a
# bare repository as origin
origin = os.path.join(T, "origin.git")
proj = os.path.join(T, "proj")
subprocess.run(["git", "init", "-q", "--bare", "-b", "main", origin], check=True)
os.makedirs(proj)
subprocess.run(["git", "-C", proj, "init", "-q", "-b", "main"], check=True)
with open(os.path.join(proj, "README.md"), "w") as f:
    f.write("project\n")
git(proj, "add", "README.md")
subprocess.run(["git", "-C", proj, "-c", "user.name=owner", "-c", "user.email=owner@example.com", "commit", "-q",
                "-m", "First"], check=True)
git(proj, "remote", "add", "origin", origin)
git(proj, "push", "-q", "origin", "main")
before_main = out(proj, "rev-parse", "main")

# first read: empty, and the branch notes is made
r = notes.read(proj, HOME)
check("first read is empty and not saved yet", r == {"text": "", "saved": None})
check("first read makes the branch notes", git(proj, "rev-parse", "-q", "--verify", "refs/heads/notes").returncode == 0)

# write, then read
w = notes.write(proj, HOME, "# Plan\nfirst note\n")
check("write gives the time of the save and pushed true", isinstance(w.get("saved"), int) and w.get("pushed") is True)
check("read after write gives the text", notes.read(proj, HOME, gap=0)["text"] == "# Plan\nfirst note\n")
wc, is_repo = notes.place(proj, HOME)
check("place: a folder in a repository", is_repo is True)
check("place: the name and 8 hex digits of the path's sha1", os.path.basename(wc).startswith("proj-")
      and len(os.path.basename(wc)) == len("proj-") + 8)

# the commit is on notes; the project is untouched
check("the commit is on notes with the message Notes", out(wc, "log", "-1", "--format=%s") == "Notes")
check("no identity in the repository: the agent-kit author", out(wc, "log", "-1", "--format=%ae") == "agent-kit@localhost")
check("project HEAD still on main", out(proj, "rev-parse", "--abbrev-ref", "HEAD") == "main")
check("main not moved", out(proj, "rev-parse", "main") == before_main)
check("project working tree clean", out(proj, "status", "--porcelain") == "")
check("NOTES.md is not in the project's working tree", not os.path.exists(os.path.join(proj, "NOTES.md")))

# the branch was pushed to origin
check("the branch notes was pushed to origin", out(origin, "rev-parse", "refs/heads/notes") == out(wc, "rev-parse", "HEAD"))

# a second clone writes a note: seen after a pull (gap 0 for the test)
clone = os.path.join(T, "clone2")
subprocess.run(["git", "clone", "-q", origin, clone], check=True, capture_output=True)
git(clone, "checkout", "-q", "-b", "notes", "origin/notes")
def clone_write(text):
    with open(os.path.join(clone, "NOTES.md"), "w") as f:
        f.write(text)
    git(clone, "add", "NOTES.md")
    subprocess.run(["git", "-C", clone, "-c", "user.name=other", "-c", "user.email=other@example.com", "commit", "-q",
                    "-m", "Notes"], check=True)
    git(clone, "push", "-q", "origin", "notes")
clone_write("from the other machine\n")
check("a note from a second clone is seen after a pull", notes.read(proj, HOME, gap=0)["text"] == "from the other machine\n")
clone_write("a second change\n")
check("a read within the minute does not pull again", notes.read(proj, HOME)["text"] == "from the other machine\n")
check("the next read after the minute pulls", notes.read(proj, HOME, gap=0)["text"] == "a second change\n")

# a folder with no repository: a plain file, no git
plain = os.path.join(T, "plain")
os.makedirs(plain)
check("a folder with no repository: empty first read", notes.read(plain, HOME) == {"text": "", "saved": None})
notes.write(plain, HOME, "plain text\n")
pw, is_repo = notes.place(plain, HOME)
check("a folder with no repository: place says no repository", is_repo is False)
check("a folder with no repository: a plain NOTES.md", open(os.path.join(pw, "NOTES.md"), encoding="utf-8").read()
      == "plain text\n")
check("a folder with no repository: no git in the place", not os.path.exists(os.path.join(pw, ".git")))
check("a folder with no repository: read gives the text", notes.read(plain, HOME)["text"] == "plain text\n")

# refused texts leave the note as it was
check("text over 1 MB is refused", refused(lambda: notes.write(proj, HOME, "x" * (1024 * 1024 + 1))))
check("text with NUL is refused", refused(lambda: notes.write(proj, HOME, "a\0b")))
check("text that is not text is refused", refused(lambda: notes.write(proj, HOME, None)))
check("the note is unchanged after the refusals", notes.read(proj, HOME, gap=0)["text"] == "a second change\n")

# a repository with no origin: saved, no push
solo = os.path.join(T, "solo")
os.makedirs(solo)
subprocess.run(["git", "-C", solo, "init", "-q", "-b", "main"], check=True)
git(solo, "config", "user.name", "Solo Owner")
git(solo, "config", "user.email", "solo@example.com")
with open(os.path.join(solo, "a.txt"), "w") as f:
    f.write("a\n")
git(solo, "add", "a.txt")
git(solo, "commit", "-q", "-m", "First")
w = notes.write(solo, HOME, "alone\n")
check("no origin: saved, and no pushed key", isinstance(w.get("saved"), int) and "pushed" not in w)
check("no origin: the commit has the repository's identity",
      out(notes.place(solo, HOME)[0], "log", "-1", "--format=%an") == "Solo Owner")
check("no origin: read gives the text", notes.read(solo, HOME)["text"] == "alone\n")

# a failed push is reported and the save is kept
git(solo, "remote", "add", "origin", os.path.join(T, "missing.git"))
w = notes.write(solo, HOME, "kept\n")
check("a failed push: pushed false, the save kept", w.get("pushed") is False and notes.read(solo, HOME)["text"] == "kept\n")

# two machines: a clone of one project on each, a HOME of its own on each, one origin. B has the notes as they were
# before A's save, so its save is pushed after a pull --rebase.
def two_machines(name):
    org = os.path.join(T, name + ".git")
    seed = os.path.join(T, name + "-seed")
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", org], check=True)
    os.makedirs(seed)
    subprocess.run(["git", "-C", seed, "init", "-q", "-b", "main"], check=True)
    with open(os.path.join(seed, "README.md"), "w") as f:
        f.write("project\n")
    git(seed, "add", "README.md")
    subprocess.run(["git", "-C", seed, "-c", "user.name=owner", "-c", "user.email=owner@example.com", "commit", "-q",
                    "-m", "First"], check=True)
    git(seed, "remote", "add", "origin", org)
    git(seed, "push", "-q", "origin", "main")
    machines = []
    for who in ("a", "b"):
        folder = os.path.join(T, name + "-" + who)
        home = os.path.join(T, name + "-" + who + "-home")
        os.makedirs(home)
        subprocess.run(["git", "clone", "-q", org, folder], check=True, capture_output=True)
        machines.append((folder, home))
    return org, machines[0], machines[1]

BASE = "line one\nline two\nline three\n"

# no clash: A changes line one, B (older copy) changes line three; B's save goes on top of A's
org, (fa, ha), (fb, hb) = two_machines("rebase-ok")
notes.write(fa, ha, BASE)
notes.read(fb, hb)
notes.write(fa, ha, "LINE ONE\nline two\nline three\n")
a_head = out(notes.place(fa, ha)[0], "rev-parse", "HEAD")
w = notes.write(fb, hb, "line one\nline two\nLINE THREE\n")
b_head = out(notes.place(fb, hb)[0], "rev-parse", "HEAD")
check("no clash: pushed true", w.get("pushed") is True)
check("no clash: origin's notes is B's commit on top of A's", out(org, "rev-parse", "refs/heads/notes") == b_head
      and out(org, "rev-parse", "refs/heads/notes^") == a_head)
check("no clash: origin holds both changes", git(org, "show", "refs/heads/notes:NOTES.md").stdout
      == "LINE ONE\nline two\nLINE THREE\n")
check("no clash: B's notes working copy has no rebase in progress",
      not any(os.path.isdir(os.path.join(notes.place(fb, hb)[0], out(notes.place(fb, hb)[0], "rev-parse", "--git-path", d)))
              for d in ("rebase-merge", "rebase-apply")))

# clash: A and B both change line two
org, (fa, ha), (fb, hb) = two_machines("rebase-clash")
notes.write(fa, ha, BASE)
notes.read(fb, hb)
notes.write(fa, ha, "line one\nA CHANGE\nline three\n")
a_head = out(notes.place(fa, ha)[0], "rev-parse", "HEAD")
wb = notes.place(fb, hb)[0]
w = notes.write(fb, hb, "line one\nB CHANGE\nline three\n")
check("clash: pushed false", w.get("pushed") is False)
check("clash: B's text still in B's NOTES.md", open(os.path.join(wb, "NOTES.md"), encoding="utf-8").read()
      == "line one\nB CHANGE\nline three\n")
check("clash: no rebase in progress in B's notes working copy",
      not any(os.path.isdir(os.path.join(wb, out(wb, "rev-parse", "--git-path", d))) for d in ("rebase-merge", "rebase-apply")))
check("clash: origin still holds A's commit", out(org, "rev-parse", "refs/heads/notes") == a_head)
check("clash: B's working copy is clean", out(wb, "status", "--porcelain") == "")

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
