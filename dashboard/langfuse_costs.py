"""langfuse_costs.py - the period's cost as Langfuse has it, a second source beside costs.py (PLAN.md "Costs").
Asks Langfuse's Metrics API v2 for the sum of totalCost per model and per day, with the keys kept in telemetry.env
(Basic auth, the same request as telemetry's check()). Never raises: the answer is
{"source": "langfuse", "usd": number, "by_model": [{"model", "usd"}]} or {"source": "langfuse", "error": text}.
The error text never holds a key."""
import datetime, json
from urllib.parse import urlencode

import telemetry

METRICS_PATH = "/api/public/v2/metrics"   # https://langfuse.com/docs/metrics/features/metrics-api (v1 daily is sunset)
TRACES_PATH = "/api/public/otel/v1/traces"  # the Langfuse traces endpoint in telemetry.env: its address is the base
ROW_LIMIT = 1000                          # the most rows one answer gives (the same page: maximum 1,000)


def _iso(seconds):
    return datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _query(since, until):
    return json.dumps({"view": "observations", "metrics": [{"measure": "totalCost", "aggregation": "sum"}],
                       "dimensions": [{"field": "providedModelName"}], "timeDimension": {"granularity": "day"},
                       "fromTimestamp": _iso(since), "toTimestamp": _iso(until),
                       "config": {"row_limit": ROW_LIMIT}})


def _error(text):
    return {"source": "langfuse", "error": text}


def _report(home, since, until):
    s = telemetry._settings(home)
    base = telemetry._base(s, "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", TRACES_PATH)
    key = telemetry._basic_of(s.get("OTEL_EXPORTER_OTLP_TRACES_HEADERS"))
    if not base or not key:
        return _error("no Langfuse address and keys kept")
    url = base + METRICS_PATH + "?" + urlencode({"query": _query(since, until)})
    status, body = telemetry._request(url, key)
    if status is None:
        return _error("not reachable")
    if status in (401, 403):
        return _error("refused: answered %d" % status)
    if not 200 <= status < 300:
        return _error("answered %d" % status)
    try:
        rows = json.loads(body.decode("utf-8", "replace")).get("data")
    except (ValueError, AttributeError):
        rows = None
    if not isinstance(rows, list):
        return _error("the answer has no data")
    by_model = {}
    for row in rows:
        usd = row.get("sum_totalCost") if isinstance(row, dict) else None
        if not isinstance(usd, (int, float)) or isinstance(usd, bool):
            continue
        model = row.get("providedModelName") or "(no model)"
        by_model[model] = by_model.get(model, 0.0) + usd
    return {"source": "langfuse", "usd": sum(by_model.values(), 0.0),
            "by_model": [{"model": m, "usd": by_model[m]} for m in sorted(by_model)]}


def report(home, since, until):
    """The Langfuse cost of the period, or {"source", "error"}. Nothing is raised."""
    try:
        return _report(home, since, until)
    except Exception:   # never a 5xx from the costs route: whatever went wrong is one error line
        return _error("the answer could not be read")
