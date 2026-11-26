"""machine.py - the machine's own facts: name, user, load, cores, memory and the free disk space of the home
folder's partition and of each agent folder's partition. Only reads."""
import getpass, os, platform, shutil

LOW_FRACTION = 0.10
LOW_BYTES = 2 * 1024 ** 3


def name():
    return platform.node()


def memory(meminfo="/proc/meminfo"):
    vals = {}
    try:
        with open(meminfo) as f:
            for line in f:
                key, _, rest = line.partition(":")
                if key in ("MemTotal", "MemAvailable"):
                    vals[key] = int(rest.split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    total = vals.get("MemTotal", 0)
    return {"used": total - vals.get("MemAvailable", 0), "total": total}


def disk(path):
    """the partition of a path (or of the nearest folder that exists), with low: true under 10% or 2 GB free"""
    p = path
    while not os.path.exists(p):
        p = os.path.dirname(p)
    u = shutil.disk_usage(p)
    low = (u.total and u.free / u.total < LOW_FRACTION) or u.free < LOW_BYTES
    return {"path": path, "free": u.free, "total": u.total, "low": bool(low)}


def disks(paths):
    """one entry per partition: the first path given on it is the one shown"""
    out, seen = [], set()
    for path in paths:
        p = path
        while not os.path.exists(p):
            p = os.path.dirname(p)
        dev = os.stat(p).st_dev
        if dev in seen:
            continue
        seen.add(dev)
        out.append(disk(path))
    return out


def snapshot(home, agent_dirs):
    try:
        load = [round(x, 2) for x in os.getloadavg()]
    except OSError:
        load = None
    return {"name": name(), "user": getpass.getuser(), "load": load, "cores": os.cpu_count() or 1,
            "memory": memory(), "disks": disks([home] + list(agent_dirs))}
