"""costs.py - what the agents and their subagents spent, from Claude Code's conversation files (PLAN.md "Costs").
Tokens are exact; money is an estimate at the API prices in prices.json. Files are read line by line; a broken
line is skipped. A reply (one message.id, written on several lines) is counted once, by its own timestamp.
A subagent's file is in <folder>/<SESSION>/subagents/agent-*.jsonl, with agent-*.meta.json beside it."""
import datetime, glob, json, os, re

PRICES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prices.json")
KINDS = ("input", "cache_write_5m", "cache_write_1h", "cache_read", "output")


def load_prices(path=PRICES):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _num(x):
    return int(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else 0


def tokens(usage):
    """The five kinds of one reply's usage. Without the 5m/1h split, all cache writes count as 5 minutes."""
    total = _num(usage.get("cache_creation_input_tokens"))
    cc = usage.get("cache_creation")
    if isinstance(cc, dict) and ("ephemeral_5m_input_tokens" in cc or "ephemeral_1h_input_tokens" in cc):
        w5, w1 = _num(cc.get("ephemeral_5m_input_tokens")), _num(cc.get("ephemeral_1h_input_tokens"))
    else:
        w5, w1 = total, 0
    return {"input": _num(usage.get("input_tokens")), "cache_write_5m": w5, "cache_write_1h": w1,
            "cache_read": _num(usage.get("cache_read_input_tokens")), "output": _num(usage.get("output_tokens"))}


def _entry(model, prices):
    """The price entry of the longest prefix of the model's id, or None."""
    best = None
    for key in prices["models"]:
        if isinstance(model, str) and model.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    return prices["models"][best] if best else None


def _usd(tok, model, prices):
    e = _entry(model, prices)
    if e is None:
        return None
    c = prices["cache"]
    over = e.get("over")   # a dearer tier for a long prompt: the prompt is all that was sent, cached or not
    if over and tok["input"] + tok["cache_write_5m"] + tok["cache_write_1h"] + tok["cache_read"] > over["prompt"]:
        e = dict(e, input=over["input"], output=over["output"])
    rate = {"input": e["input"], "output": e["output"], "cache_write_5m": e["input"] * c["write_5m"],
            "cache_write_1h": e["input"] * c["write_1h"], "cache_read": e["input"] * e.get("read", c["read"])}
    return sum(tok[k] * rate[k] for k in KINDS) / 1000000.0


def price(usage, model, prices):
    """Dollars of one reply's usage at the model's prices, or None when the model is not in the price list."""
    return _usd(tokens(usage), model, prices)


def task_label(branch):
    """The issue number of a branch: a whole part of 1-6 digits between / and -. None when there is none."""
    if not isinstance(branch, str):
        return None
    for part in re.split(r"[/-]", branch):
        if re.fullmatch(r"[0-9]{1,6}", part):
            return part
    return None


def label_task(label):
    """The task name of a profile's label: a leading # dropped, so #267 is the task 267. None when there is no label."""
    if not isinstance(label, str):
        return None
    s = label[1:] if label.startswith("#") else label
    return s or None


def est_tokens(text):
    """An estimate of a text's tokens: its characters divided by 4, rounded up. None when there is no text.
    It is an estimate, not a count: no tokenizer is run on the machine."""
    if text is None:
        return None
    return -(-len(text) // 4)


def _empty():
    t = {k: 0 for k in KINDS}
    t["usd"] = 0.0
    t["usd_partial"] = False
    return t


def _add(t, u):
    """Adds the T-like u to t. The money is the sum of the priced part; usd_partial is True once any part has no price."""
    for k in KINDS:
        t[k] += u[k]
    if u["usd"] is None:
        t["usd_partial"] = True
    else:
        t["usd"] += u["usd"]
        t["usd_partial"] = t["usd_partial"] or u.get("usd_partial", False)
    return t


def _ts(text):
    if not isinstance(text, str):
        return None
    try:
        dt = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.timestamp()


def _text(content):
    """The text of a message's content (a string, or text blocks), or None when there is none."""
    if isinstance(content, str):
        return content or None
    if isinstance(content, list):
        s = "".join(b["text"] for b in content
                    if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))
        return s or None
    return None


def _meta_type(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    t = d.get("agentType") if isinstance(d, dict) else None
    return t if isinstance(t, str) else None


def scan(path, since, until):
    """One conversation file, read line by line: its replies in the period (one per message.id, the last line
    seen), the branch, the first user text and the last assistant text. None when the file cannot be read."""
    replies = {}
    branch = brief = report = None
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return None
    with f:
        for n, line in enumerate(f):
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if not isinstance(d, dict):
                continue
            if isinstance(d.get("gitBranch"), str):
                branch = d["gitBranch"]
            msg = d.get("message") if isinstance(d.get("message"), dict) else {}
            if d.get("type") == "user" and brief is None:
                brief = _text(msg.get("content"))
            if d.get("type") == "assistant" and _text(msg.get("content")):
                report = _text(msg.get("content"))
            usage = msg.get("usage")
            ts = _ts(d.get("timestamp"))
            if d.get("type") != "assistant" or not isinstance(usage, dict) or ts is None or not (since <= ts <= until):
                continue
            replies[msg.get("id") or ("line", n)] = {"model": msg.get("model"), "usage": usage}
    return {"branch": branch, "brief": brief, "report": report, "replies": list(replies.values())}


def _sum(replies, prices, unpriced):
    t = _empty()
    for r in replies:
        tok = tokens(r["usage"])
        usd = _usd(tok, r["model"], prices)
        if usd is None:
            unpriced.add(str(r["model"]))
        _add(t, dict(tok, usd=usd))
    return t


def report(projects_dir, since, until, folder=None, labels=None):
    """Tokens and dollars of the period: by folder (agent), by task, and each subagent call.
    labels: folder name -> the label of the profile that runs in it (None: no label for that folder). A session's
    task is that label when there is one, else the branch's issue number, else session:ID."""
    prices = load_prices()
    unpriced = set()
    out = {"since": since, "until": until, "total": _empty(), "agents": [], "tasks": [], "unpriced": []}
    tasks = {}

    def task(label):
        if label not in tasks:
            tasks[label] = {"task": label, "main": _empty(), "subagents": _empty(), "calls": []}
        return tasks[label]

    names = sorted(os.listdir(projects_dir)) if os.path.isdir(projects_dir) else []
    for name in names:
        fdir = os.path.join(projects_dir, name)
        if (folder and name != folder) or not os.path.isdir(fdir):
            continue
        agent = {"folder": name, "main": _empty(), "subagents": _empty()}
        out["agents"].append(agent)
        branches = {}
        fl = label_task((labels or {}).get(name))
        for path in sorted(glob.glob(os.path.join(glob.escape(fdir), "*.jsonl"))):
            if os.path.getmtime(path) < since:
                continue
            got = scan(path, since, until)
            if got is None:
                continue
            session = os.path.basename(path)[:-len(".jsonl")]
            branches[session] = got["branch"]
            if not got["replies"]:
                continue
            t = _sum(got["replies"], prices, unpriced)
            _add(agent["main"], t)
            _add(out["total"], t)
            _add(task(fl or task_label(got["branch"]) or "session:" + session)["main"], t)

        for path in sorted(glob.glob(os.path.join(glob.escape(fdir), "*", "subagents", "*.jsonl"))):
            if os.path.getmtime(path) < since:
                continue
            got = scan(path, since, until)
            if got is None or not got["replies"]:
                continue
            session = os.path.basename(os.path.dirname(os.path.dirname(path)))
            label = fl or task_label(branches.get(session) or got["branch"]) or "session:" + session
            t = _sum(got["replies"], prices, unpriced)
            base = path[:-len(".jsonl")]
            call = {"agent": os.path.basename(base), "type": _meta_type(base + ".meta.json"), "tokens": t,
                    "brief_chars": None if got["brief"] is None else len(got["brief"]),
                    "report_chars": None if got["report"] is None else len(got["report"]),
                    "brief_tokens": est_tokens(got["brief"]), "report_tokens": est_tokens(got["report"])}
            _add(agent["subagents"], t)
            _add(out["total"], t)
            _add(task(label)["subagents"], t)
            task(label)["calls"].append(call)

    out["tasks"] = sorted(tasks.values(), key=lambda x: x["task"])
    out["unpriced"] = sorted(unpriced)
    return out
