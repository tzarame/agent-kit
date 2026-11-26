"""dash.py - the entry of the local dashboard: arguments, settings, the key, the server.
    python3 dashboard/dash.py [--port N] [--bind ADDR]     serve (default 127.0.0.1:8765); --bind tailscale: on the
                                                           machine's Tailscale address, 127.0.0.1 when it has none
    python3 dashboard/dash.py key [--new]                  print the API key (make it with --new)
Port: --port, else AGENT_KIT_DASH_PORT, else PORT of dashboard.env, else 8765. Standard library only."""
import argparse, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import access, envfile, http_api, machine   # noqa: E402

DEFAULT_PORT = 8765
REPO = os.path.dirname(HERE)


def kit_dir(home):
    return os.path.join(home, ".config", "agent-kit")


def version():
    try:
        r = subprocess.run(["git", "-C", REPO, "describe", "--tags", "--always", "--dirty"], capture_output=True,
                           text=True, timeout=5, stdin=subprocess.DEVNULL)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "dev"


def tailscale_address():
    """the machine's first Tailscale IPv4 address; None when Tailscale is not there, is down or gives another thing"""
    try:
        r = subprocess.run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    first = r.stdout.split()[0] if r.returncode == 0 and r.stdout.split() else ""
    parts = first.split(".")
    return first if len(parts) == 4 and all(p.isdigit() and int(p) < 256 for p in parts) else None


def settings(home, env, arg_port):
    """the dashboard's settings: dashboard.env, then the environment, then the arguments."""
    raw = envfile.read_env(os.path.join(kit_dir(home), "dashboard.env"))
    port = arg_port
    if port is None:
        port = os.environ.get("AGENT_KIT_DASH_PORT") or raw.get("PORT") or DEFAULT_PORT
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise SystemExit("the port is not a number: %r" % (port,))
    if not 0 < port < 65536:
        raise SystemExit("the port is out of range: %d" % port)
    centres = [c for c in raw.get("CENTRES", "").replace(",", " ").split() if c]
    return {"port": port, "centres": centres, "home_dir": raw.get("HOME_DIR") or home,
            "on": raw.get("ON", "yes") != "no"}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dash.py", description="the local agent dashboard")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--bind", default="127.0.0.1")
    sub = ap.add_subparsers(dest="cmd")
    k = sub.add_parser("key", help="print the API key")
    k.add_argument("--new", action="store_true", help="make a new key (the old one stops working)")
    args = ap.parse_args(argv)

    home = os.path.expanduser("~")
    kit = kit_dir(home)
    key = access.load_key(os.path.join(kit, "dashboard-key"), new=bool(args.cmd == "key" and args.new))
    if args.cmd == "key":
        print(key)
        return 0

    cfg = settings(home, os.environ, args.port)
    if not cfg["on"] and args.port is None:
        print("the dashboard is off (ON=no in dashboard.env); give --port to run it anyway")
        return 0
    with open(os.path.join(HERE, "page.html"), "rb") as f:
        page = f.read()
    bind = args.bind
    if bind == "tailscale":
        bind = tailscale_address() or "127.0.0.1"
        if bind == "127.0.0.1":
            print("no Tailscale address: the dashboard is on this machine only", flush=True)
    api = http_api.Api(home, key, cfg, version(), page)
    httpd = http_api.serve(bind, cfg["port"], api)
    print("dashboard on http://%s:%d/" % (bind, httpd.server_address[1]), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
