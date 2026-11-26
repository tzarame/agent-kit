#!/usr/bin/env bash
# tests/dashboard-access.test.sh - dashboard/access.py: who may call the dashboard (CONTRACT.md "Access"), the Origin
# check and the API key file. No server and no tailscale: Tailnet answers come from a stub. HOME is a temp folder.
# Exit 0 when every case passes.
REPO=$(cd "$(dirname "$0")/.." && pwd -P)
T=$(mktemp -d) || exit 1; T=$(cd "$T" && pwd -P); trap 'rm -rf "$T"' EXIT
export HOME="$T/home"; mkdir -p "$HOME" || exit 1
cat > "$T/case.py" <<'PY'
import os, stat, sys
sys.path.insert(0, os.path.join(sys.argv[1], "dashboard"))
import access

class Stub(access.Tailnet):
    """answers without tailscale: same_login and same_addr from the table, and the calls are counted"""
    def __init__(self, same, calls=None):
        super().__init__()
        self.same, self.calls = same, calls if calls is not None else []
    def _run(self, *args):
        self.calls.append(args)
        return {"Self": {"UserID": 1}, "User": {"1": {"LoginName": "owner@example.com"}}, "UserProfile": {"ID": 1}}
    def same_login(self, login):
        return self.same.get(login)
    def same_addr(self, addr):
        return self.same.get(addr)

KEY = "k3y-for-the-test"
S = {"port": 8765, "centres": ["http://127.0.0.1:8766"], "key": KEY}
T = Stub({"owner@example.com": True, "other@example.com": False, "100.100.1.1": True, "100.100.2.2": False})
fails = []
def want(name, client, headers, status, settings=S, tail=T):
    ok, st, why = access.decide(client, headers, settings, tail)
    if (status == 200) != ok or (ok is False and st != status):
        fails.append("%s: got %s %s" % (name, st, why))
    print(("ok   - " if (status == 200) == ok and (ok or st == status) else "FAIL - ") + name)

H = lambda **k: {("Host" if n == "host" else n): v for n, v in k.items()}
want("loopback, local name, no login: no key", "127.0.0.1", {"Host": "127.0.0.1:8765"}, 200)
want("loopback as localhost and [::1]", "::1", {"Host": "[::1]:8765"}, 200)
want("loopback with another name in Host (rebinding): 403", "127.0.0.1", {"Host": "evil.example:8765"}, 403)
want("loopback, tailscale serve headers, same user: allowed", "127.0.0.1",
     {"Host": "box.tail1.ts.net", "Tailscale-User-Login": "owner@example.com"}, 200)
want("loopback, tailscale serve headers, another user: 403", "127.0.0.1",
     {"Host": "box.tail1.ts.net", "Tailscale-User-Login": "other@example.com"}, 403)
want("tailnet address, same user: allowed", "100.100.1.1", {"Host": "100.100.1.1:8765"}, 200)
want("tailnet address, another user: 403", "100.100.2.2", {"Host": "100.100.2.2:8765"}, 403)
want("tailnet address of another user with the owner's login written as a header: 403", "100.100.2.2",
     {"Host": "100.100.2.2:8765", "Tailscale-User-Login": "owner@example.com"}, 403)
want("tailnet address, another site's name in Host (rebinding): 403", "100.100.1.1", {"Host": "evil.example:8765"}, 403)
want("private address with the key, another site's name in Host: 403", "192.168.1.5",
     {"Host": "evil.example:8765", "Authorization": "Bearer " + KEY}, 403)
want("tailnet, tailscale does not answer: 403", "100.100.9.9", {"Host": "100.100.9.9:8765"}, 403)
want("private address, no key: 401", "192.168.1.5", {"Host": "192.168.1.5:8765"}, 401)
want("private address, right key: allowed", "192.168.1.5", {"Host": "192.168.1.5:8765", "Authorization": "Bearer " + KEY}, 200)
want("private address, wrong key: 401", "10.0.0.7", {"Host": "10.0.0.7:8765", "Authorization": "Bearer nope"}, 401)
want("private address, key with no Bearer word: 401", "10.0.0.7", {"Host": "10.0.0.7:8765", "Authorization": KEY}, 401)
want("a public address: 403", "8.8.8.8", {"Host": "8.8.8.8:8765"}, 403)
want("a public address with the right key: 403", "8.8.8.8", {"Host": "8.8.8.8:8765", "Authorization": "Bearer " + KEY}, 403)
want("a public address, tailscale headers: 403", "8.8.8.8", {"Host": "8.8.8.8:8765", "Tailscale-User-Login": "owner@example.com"}, 403)
want("own loopback origin: allowed", "127.0.0.1", {"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8765"}, 200)
want("a foreign origin on loopback: 403", "127.0.0.1", {"Host": "127.0.0.1:8765", "Origin": "https://evil.example"}, 403)
want("a centre origin from settings: allowed", "127.0.0.1",
     {"Host": "127.0.0.1:8765", "Origin": "http://127.0.0.1:8766"}, 200)
want("origin equal to a tailnet name it was served under: allowed", "127.0.0.1",
     {"Host": "box.tail1.ts.net", "Tailscale-User-Login": "owner@example.com", "Origin": "https://box.tail1.ts.net"}, 200)
want("origin equal to a non-tailnet name: 403", "127.0.0.1",
     {"Host": "evil.example", "Origin": "https://evil.example"}, 403)

# the tailscale answers are kept a minute: one call for two questions
calls = []
class Counted(access.Tailnet):
    """the real Tailnet, with only the command replaced: the calls to it are counted"""
    def _run(self, *args):
        calls.append(args)
        return {"Self": {"UserID": 1}, "User": {"1": {"LoginName": "owner@example.com"}}}
c = Counted()
c.same_login("owner@example.com"); c.same_login("owner@example.com")
if len(calls) != 1:
    fails.append("cache: %d calls" % len(calls))
print(("ok   - tailscale answers are kept: one call for two questions" if len(calls) == 1 else "FAIL - tailscale answers are not kept"))

# the key file: made once, mode 600, kept; new=True makes another
kp = os.path.join(os.environ["HOME"], ".config", "agent-kit", "dashboard-key")
k1 = access.load_key(kp)
k2 = access.load_key(kp)
mode = stat.S_IMODE(os.stat(kp).st_mode)
k3 = access.load_key(kp, new=True)
ok = len(k1) >= 32 and k1 == k2 and mode == 0o600 and k3 != k1
print(("ok   - key: made with mode 600, kept, new=True changes it" if ok else "FAIL - key file"))
if not ok:
    fails.append("key file")
if fails:
    print("\n".join(fails))
sys.exit(1 if fails else 0)
PY
out=$(python3 -I "$T/case.py" "$REPO" 2>&1); rc=$?
echo "$out"
PASS=$(printf '%s\n' "$out" | grep -c '^ok   - ')
FAIL=$(printf '%s\n' "$out" | grep -c '^FAIL - ')
[ "$rc" = 0 ] || [ "$FAIL" != 0 ] || FAIL=1
echo "passed $PASS, failed $FAIL"; [ "$FAIL" = 0 ]
