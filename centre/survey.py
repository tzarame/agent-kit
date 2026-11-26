"""survey.py - what is on a machine, read over SSH; it writes nothing there. One bash script (SCRIPT) goes on ssh's
stdin to `bash -s` and prints lines of tab-separated fields; parse() makes the answer of them. The sign-in is ssh's
own (the key of the user who runs the centre), or the key file of the setting ssh_key. Root is tried first, as it
sees every user of the machine; then the user of the setting ssh_user, else the one who runs the centre.
run() never raises: {"ok": true, "sign_in", "users": [...]} or {"ok": false, "error"}. split() parts the answers:
the machines that let the centre in are the survey's list, and each one that did not is a line of the log. Of a
file of the old kit only
its name leaves the machine: such a file may hold the values of a project's environment."""
import getpass, subprocess
import ssh_add

TIMEOUT = 30
MAX_OUT = 512 * 1024
KINDS = ("new", "old", "none")
LOG_MAX = 200           # the lines of the log kept; the oldest are dropped
SCRIPT = r'''#!/bin/bash
# the centre's survey: prints, changes nothing
clean() { local v=${1//[$'\t\r\n']/ }; printf '%s' "${v:0:300}"; }
line() { local out="" f; for f in "$@"; do out+="$(clean "$f")"$'\t'; done; printf '%s\n' "${out%$'\t'}"; }
section() {
  local h=$HOME c=$HOME/.config/agent-kit k=$HOME/.agent-kit kind=none ver="" f s
  line user "$(id -un)" "$h"
  if [ -f "$k/kit/__main__.py" ]; then kind=new; elif [ -d "$k/launcher" ]; then kind=old; fi
  if [ -f "$k/VERSION" ]; then ver=$(head -n 1 "$k/VERSION" 2>/dev/null)
  elif [ -d "$k/.git" ]; then ver=$(git -C "$k" describe --tags --always 2>/dev/null </dev/null); fi
  line kit "$kind" "$ver"
  for f in "$c"/profiles/*.env "$c"/projects/*.env; do
    [ -f "$f" ] && { s=${f%/*}; line oldfile "${s##*/}" "$(basename "$f" .env)"; }
  done
  [ -f "$c/config.json" ] && line config yes
  if command -v tmux >/dev/null 2>&1; then
    tmux list-sessions -F '#{session_name}	#{session_path}' 2>/dev/null </dev/null | while IFS=$'\t' read -r s f; do
      kind=other
      case "$s" in agent-*) kind=old ;; esac
      [ -f "$c/sessions/$s.json" ] && kind=new
      line tmux "$s" "$f" "$kind"
    done
  fi
  s=no; [ -s "$h/.claude/.credentials.json" ] && s=yes; line signed claude "$s"
  s=no; [ -s "$h/.config/gh/hosts.yml" ] && s=yes; line signed gh "$s"
}
if [ "$(id -u)" = 0 ]; then
  body="$(declare -f clean line section); section"
  for d in /home/*; do
    [ -d "$d" ] || continue
    [ -e "$d/.agent-kit" ] || [ -e "$d/.config/agent-kit" ] || [ -e "$d/.claude" ] || continue
    u=$(stat -c %U "$d" 2>/dev/null) || continue
    [ "$u" != root ] && [ "$u" != UNKNOWN ] || continue
    runuser -u "$u" -- env -i HOME="$d" PATH=/usr/local/bin:/usr/bin:/bin bash -c "$body" </dev/null
  done
  if [ -e /root/.agent-kit ] || [ -e /root/.config/agent-kit ]; then section; fi
else
  section
fi
line end
'''


def parse(text):
    """the users of the script's output; None when the output did not reach its end"""
    users, cur, ended = [], None, False
    for raw in text.splitlines():
        f = raw.split("\t")
        if f[0] == "end":
            ended = True
        elif f[0] == "user" and len(f) == 3:
            cur = {"user": f[1], "home": f[2], "kit": "none", "version": "", "old_files": [], "config": False,
                   "sessions": [], "claude": False, "gh": False}
            users.append(cur)
        elif cur is None:
            continue
        elif f[0] == "kit" and len(f) == 3 and f[1] in KINDS:
            cur["kit"], cur["version"] = f[1], f[2]
        elif f[0] == "oldfile" and len(f) == 3:
            cur["old_files"].append(f[1] + "/" + f[2])
        elif f[0] == "config":
            cur["config"] = True
        elif f[0] == "tmux" and len(f) == 4:
            cur["sessions"].append({"name": f[1], "folder": f[2], "kind": f[3]})
        elif f[0] == "signed" and len(f) == 3 and f[1] in ("claude", "gh"):
            cur[f[1]] = f[2] == "yes"
    return users if ended else None


def argv(host, user, key=""):
    """the ssh command of the survey: no password is ever asked (BatchMode)"""
    out = [ssh_add.ssh_program(), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
           "-o", "ConnectTimeout=10"]
    if key:
        out += ["-o", "IdentitiesOnly=yes", "-i", key]
    return out + [user + "@" + host, "--", "bash -s"]


def sign_ins(settings):
    """the users tried, in order: root, then the setting's user or the centre's own"""
    other = settings.get("ssh_user") or getpass.getuser()
    return ["root"] + ([other] if other != "root" else [])


def run(host, settings):
    try:
        ssh_add.check_host(host)
    except Exception as e:
        return {"ok": False, "error": str(e)[:ssh_add.ERR_MAX]}
    error = "ssh failed"
    for user in sign_ins(settings):
        try:
            p = subprocess.run(argv(host, user, settings.get("ssh_key", "")), input=SCRIPT, capture_output=True,
                               text=True, timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            error = "timed out after %d seconds" % TIMEOUT
            continue
        except OSError:
            return {"ok": False, "error": "ssh could not run"}
        users = parse(p.stdout[:MAX_OUT]) if p.returncode == 0 else None
        if users is not None:
            return {"ok": True, "sign_in": user, "users": users}
        error = ssh_add.short(p.stderr) if p.stderr.strip() else "the survey gave no answer"
    return {"ok": False, "error": error}


def split(members, answers, now):
    """members: [(name, address)], answers: run()'s answer for each, now: the time of the survey.
    -> ({address: the answer of a machine that let the centre in}, [a log line for each that did not])"""
    seen, lines = {}, []
    for (name, address), got in zip(members, answers):
        if got.get("ok"):
            seen[address] = dict(got, name=name, address=address)
        else:
            lines.append({"time": int(now), "name": name, "address": address, "error": got.get("error") or "no answer"})
    return seen, lines
