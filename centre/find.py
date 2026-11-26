"""find.py - finds the dashboards and the other centres of the Tailscale network. The online machines come from
`tailscale status --json` (this machine's own included); each is asked GET /api/v1/hello on the ports of the
settings, in parallel threads, with a timeout of 2 s. Only offers: the owner adds a found machine, not this module.
Ports: AGENT_KIT_FIND_PORTS (dashboards, default 8765), AGENT_KIT_FIND_CENTRE_PORTS (centres, default 8766)."""
import json, os, subprocess
from concurrent.futures import ThreadPoolExecutor
from urllib.request import ProxyHandler, build_opener

TIMEOUT = 2
OPENER = build_opener(ProxyHandler({}))   # a proxy from the environment is not used for the network's machines


def ports(env_name, default):
    out = []
    for text in os.environ.get(env_name, default).replace(",", " ").split():
        if text.isdigit() and 0 < int(text) < 65536:
            out.append(int(text))
    return out


def status():
    """tailscale's status as a dict, or None when tailscale is not there or fails"""
    try:
        r = subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=5,
                           stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            return None
        return json.loads(r.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def members(st):
    """[(name, address)] of the online machines of a status: this machine's own first, then the peers"""
    if not isinstance(st, dict):
        return []
    out = []
    for m in [st.get("Self")] + list((st.get("Peer") or {}).values()):
        ips = (m or {}).get("TailscaleIPs") or []
        if isinstance(m, dict) and m.get("Online") and ips:
            out.append((m.get("HostName") or "", ips[0]))
    return out


def own_addresses(st):
    me = st.get("Self") if isinstance(st, dict) else None
    return {"127.0.0.1", "::1"} | set((me or {}).get("TailscaleIPs") or [])


def base(addr, port):
    return "http://[%s]:%d" % (addr, port) if ":" in addr else "http://%s:%d" % (addr, port)


def ask(addr, port):
    """the hello of the server at addr:port, or None when it does not answer as the API does"""
    try:
        with OPENER.open(base(addr, port) + "/api/v1/hello", timeout=TIMEOUT) as r:
            data = json.loads(r.read(65536).decode("utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def scan(st, own_port, port_list):
    """{"dashboards": [...], "centres": [...]}: each answer with kind dashboard or centre. This centre itself
    (its own port on one of this machine's addresses) is not asked."""
    own = own_addresses(st)
    jobs, seen = [], set()
    for name, addr in members(st):
        for port in port_list:
            if (addr, port) not in seen and not (addr in own and port == own_port):
                seen.add((addr, port))
                jobs.append((name, addr, port))
    with ThreadPoolExecutor(max_workers=max(1, min(32, len(jobs)))) as pool:
        answers = list(pool.map(lambda j: ask(j[1], j[2]), jobs))
    dashboards, centres = [], []
    for (name, addr, port), hello in zip(jobs, answers):
        if not hello:
            continue
        found = {"name": name, "address": base(addr, port), "machine": hello.get("machine"),
                 "version": hello.get("version"), "api": hello.get("api")}
        if hello.get("kind") == "dashboard":
            dashboards.append(found)
        elif hello.get("kind") == "centre":
            centres.append(found)
    return {"dashboards": dashboards, "centres": centres}


def find(own_port):
    dash = ports("AGENT_KIT_FIND_PORTS", "8765")
    cent = ports("AGENT_KIT_FIND_CENTRE_PORTS", "8766")
    return scan(status(), own_port, list(dict.fromkeys(dash + cent)))
