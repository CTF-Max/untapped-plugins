"""untapped-serp MCP server: live Google results and search volume through the user's own DataForSEO account."""
import sys

sys.dont_write_bytecode = True  # an installed plugin folder stays clean

import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dataforseo as dfs  # noqa: E402
from ledger import Ledger  # noqa: E402
from mcp_stdio import ToolError, serve  # noqa: E402

VERSION = "0.1.1"
DEFAULT_CAP_USD = "1.00"

LOCATION_PROPS = {
    "location_name": {"type": "string", "description": "e.g. 'Palm Coast,Florida,United States' (default 'United States')"},
    "location_code": {"type": "integer", "description": "DataForSEO location code (instead of location_name)"},
    "language_code": {"type": "string", "description": "default 'en'"},
}
TOOLS = [
    {
        "name": "google_serp",
        "description": "Live Google organic results for one keyword in one place: positions, People Also Ask, "
                       "local pack, AI Overview cited domains, featured snippet, and every position a target domain "
                       "holds. Paid (user's DataForSEO account, about $0.002 per 10 results); cached 24 h.",
        "inputSchema": {"type": "object", "required": ["keyword"], "additionalProperties": False, "properties": {
            "keyword": {"type": "string", "maxLength": 700},
            **LOCATION_PROPS,
            "location_coordinate": {"type": "string", "description": "'lat,lng[,radius_km]' (instead of location_name)"},
            "device": {"type": "string", "enum": ["desktop", "mobile"]},
            "depth": {"type": "integer", "minimum": 10, "maximum": 100, "description": "results to fetch; billed per 10"},
            "target_domain": {"type": "string", "description": "hostname to locate, e.g. example.com"},
            "max_age_hours": {"type": "number", "minimum": 0, "description": "reuse a cached result this fresh; 0 = fresh call"},
            "dry_run": {"type": "boolean", "description": "show the request and its cost reserve without calling"},
        }},
    },
    {
        "name": "google_search_volume",
        "description": "Google Ads monthly search volume, CPC and competition for up to 100 keywords (1000 with "
                       "allow_large_batch). Paid (about $0.09 per call, any keyword count); cached 30 days. "
                       "null volume means no data, never zero.",
        "inputSchema": {"type": "object", "required": ["keywords"], "additionalProperties": False, "properties": {
            "keywords": {"type": "array", "items": {"type": "string", "maxLength": 80}, "minItems": 1, "maxItems": 1000},
            **LOCATION_PROPS,
            "allow_large_batch": {"type": "boolean"},
            "max_age_hours": {"type": "number", "minimum": 0},
            "dry_run": {"type": "boolean"},
        }},
    },
    {
        "name": "serp_spend",
        "description": "Free. Today's and this month's DataForSEO spend through this plugin, the daily cap, cache "
                       "hits, the last 10 calls, and whether the credential variables are set (never their values).",
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    {
        "name": "serp_estimate",
        "description": "Free. The cost reserve for a would-be google_serp or google_search_volume call and whether "
                       "today's cap allows it. Never calls the API.",
        "inputSchema": {"type": "object", "required": ["tool", "arguments"], "additionalProperties": False, "properties": {
            "tool": {"type": "string", "enum": ["google_serp", "google_search_volume"]},
            "arguments": {"type": "object"},
        }},
    },
]


def cap_units():
    raw = dfs.env_value("UNTAPPED_SERP_DAILY_CAP_USD", DEFAULT_CAP_USD)
    try:
        return dfs.units(raw)
    except ToolError:
        raise ToolError("UNTAPPED_SERP_DAILY_CAP_USD must be a non-negative number of US dollars.") from None


def sandbox_on():
    return dfs.env_value("UNTAPPED_SERP_SANDBOX", "") in ("1", "true", "yes")


def label(tool, request):
    if tool == "google_serp":
        return request["keyword"][:120]
    return "%d keyword(s)" % len(request["keywords"])


class Server:
    def __init__(self, ledger=None, client=None):
        self._ledger = ledger
        self.client = client

    @property
    def ledger(self):
        if self._ledger is None:
            self._ledger = Ledger()
        return self._ledger

    def call(self, name, args):
        if name == "serp_spend":
            if args:
                raise ToolError("serp_spend takes no arguments.")
            out = self.ledger.summary()
            out.update(daily_cap_usd=cap_units() / 1e9, sandbox=sandbox_on(), ledger_path=str(self.ledger.path),
                       credentials_set=dict(zip(("login", "password"), map(bool, dfs.credentials()))))
            return out
        if name == "serp_estimate":
            if set(args) != {"tool", "arguments"} or args["tool"] not in dfs.ENDPOINTS \
                    or not isinstance(args["arguments"], dict):
                raise ToolError("serp_estimate needs tool (google_serp | google_search_volume) and arguments.")
            inner = dict(args["arguments"])
            inner["dry_run"] = True
            return self.call(args["tool"], inner)
        if name not in dfs.ENDPOINTS:
            raise ToolError("Unknown tool: " + str(name)[:60])
        return self.paid(name, args)

    def paid(self, tool, args):
        request, max_age = dfs.normalize(tool, args)
        target = args.get("target_domain", "").strip().lower().rstrip(".") if tool == "google_serp" else ""
        sandbox = sandbox_on()
        endpoint = dfs.ENDPOINTS[tool]
        key = json.dumps({"endpoint": endpoint, "request": request, "sandbox": sandbox},
                         sort_keys=True, separators=(",", ":"))
        reserve, cap = dfs.reserve(tool, request), cap_units()
        charged, held = self.ledger.committed()

        if args.get("dry_run"):
            hit = self.ledger.cached(key, max_age)
            return {"dry_run": True, "endpoint": endpoint, "request": request, "sandbox": sandbox,
                    "reserve_usd": reserve / 1e9, "would_use_cache": hit is not None,
                    "charged_today_usd": charged / 1e9, "held_today_usd": held / 1e9, "daily_cap_usd": cap / 1e9,
                    "cap_allows": hit is not None or charged + held + reserve <= cap,
                    "price_source": dfs.PRICES[tool]["source"]}

        hit = self.ledger.cached(key, max_age)
        if hit is not None:
            fetched_at, result = hit
            self.ledger.cache_hit(tool, label(tool, request))
            out = self.finish(tool, result, target, request)
            out.update(cost_usd=0.0, cached={"hit": True, "fetched_at_unix": fetched_at})
            return self.with_spend(out, sandbox)

        client = self.client or dfs.Client(sandbox=sandbox)
        client.credentials()  # missing credentials fail here, before any reserve is held
        call_id = self.ledger.reserve(tool, label(tool, request), reserve, cap)
        try:
            response = client.post(endpoint, request)
        except ToolError:
            self.ledger.uncertain(call_id)
            raise
        try:
            cost = dfs.response_cost(response)
        except ToolError:
            self.ledger.uncertain(call_id)
            raise
        self.ledger.complete(call_id, cost)  # record the charge before any status error is raised
        rows = dfs.results(response)
        slim = dfs.slim_serp(rows, request) if tool == "google_serp" else dfs.slim_volume(rows, request)
        self.ledger.store(key, tool, slim)
        out = self.finish(tool, slim, target, request)
        out.update(cost_usd=cost / 1e9, cached={"hit": False})
        return self.with_spend(out, sandbox)

    @staticmethod
    def finish(tool, slim, target, request):
        out = json.loads(json.dumps(slim))  # never mutate the cached copy
        if tool == "google_serp":
            out = dfs.apply_target(out, target, request["depth"])
        return out

    def with_spend(self, out, sandbox):
        charged, held = self.ledger.committed()
        out.update(spend_today_usd=charged / 1e9, held_today_usd=held / 1e9)
        if sandbox:
            out["sandbox"] = True
            out["sandbox_note"] = "DataForSEO sandbox: dummy data, not real Google results."
        return out


def main():
    server = Server()
    serve(TOOLS, server.call, name="untapped-serp", version=VERSION, sanitize=dfs.Redactor())


if __name__ == "__main__":
    main()
