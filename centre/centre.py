"""centre.py - the entry of the control centre: arguments, settings, the key, the server.
    python3 centre/centre.py [--port N] [--bind ADDR]     serve (default 127.0.0.1:8766)
Port: --port, else AGENT_KIT_CENTRE_PORT, else 8766. The key is ~/.config/agent-kit/centre/key (made at the
first start). Standard library only."""
import argparse, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.append(os.path.join(HERE, "..", "dashboard"))
import access, http_api   # noqa: E402

DEFAULT_PORT = 8766
REPO = os.path.dirname(HERE)


def version():
    """the repository's latest tag, else dev"""
    try:
        r = subprocess.run(["git", "-C", REPO, "describe", "--tags", "--abbrev=0"], capture_output=True, text=True,
                           timeout=5, stdin=subprocess.DEVNULL)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return "dev"


def port_of(arg, env):
    port = arg if arg is not None else (env.get("AGENT_KIT_CENTRE_PORT") or DEFAULT_PORT)
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise SystemExit("the port is not a number: %r" % (port,))
    if not 0 < port < 65536:
        raise SystemExit("the port is out of range: %d" % port)
    return port


def main(argv=None):
    ap = argparse.ArgumentParser(prog="centre.py", description="the control centre of the agent dashboards")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--bind", default="127.0.0.1")
    args = ap.parse_args(argv)

    home = os.path.expanduser("~")
    key = access.load_key(os.path.join(home, ".config", "agent-kit", "centre", "key"))
    cfg = {"port": port_of(args.port, os.environ)}
    with open(os.path.join(HERE, "page.html"), "rb") as f:
        page = f.read()
    api = http_api.Api(home, key, cfg, version(), page)
    httpd = http_api.serve(args.bind, cfg["port"], api)
    print("centre on http://%s:%d/" % (args.bind, httpd.server_address[1]), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
