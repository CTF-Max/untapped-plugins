"""Pinned, single-attempt DataForSEO client and compact response adapters."""
import base64
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal

from mcp_stdio import ToolError

ENDPOINTS = {
    "google_serp": "/v3/serp/google/organic/live/advanced",
    "google_search_volume": "/v3/keywords_data/google_ads/search_volume/live",
}
PRICES = {
    "google_serp": {
        "usd_per_10_results": "0.002",
        "operator_multiplier": 5,
        "operators": ["allinanchor", "allintext", "allintitle", "allinurl", "cache",
                      "define", "definition", "filetype", "id", "inanchor", "info",
                      "intext", "intitle", "inurl", "link", "site"],
        "source": "https://dataforseo.com/pricing/serp/google-organic-serp-api",
        "depth_source": "https://dataforseo.com/help-center/serp-api-pricing-depth-update-faq",
        "docs": "https://docs.dataforseo.com/v3/serp/google/organic/live/advanced/",
        "read_date": "2026-10-09",
        "note": "Reserve full price per started page; no historical 25% additional-page discount. "
                "Conservatively multiply for every operator occurrence, including encoded operators.",
    },
    "google_search_volume": {
        "usd_per_task": "0.09",
        "max_keywords": 1000,
        "source": "https://dataforseo.com/pricing/keywords-data/google-ads",
        "docs": "https://docs.dataforseo.com/v3/keywords_data-google_ads-search_volume-live/",
        "read_date": "2026-10-09",
        "note": "Current pricing supersedes the older 0.075 example response in the API docs.",
    },
}
UNITS = 1_000_000_000  # integer nanodollars; never binary floats for cap decisions


def units(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > Decimal("1000000000"):
            raise ValueError
        return int((amount * UNITS).to_integral_value(rounding="ROUND_CEILING"))
    except Exception:
        raise ToolError("Invalid non-negative USD amount.") from None


def usd(value):
    return float(Decimal(value) / UNITS)


def env_value(name, default=""):
    value = os.environ.get(name, "")
    # Claude hosts may pass unresolved optional substitutions (${NAME}, ${user_config.key}) literally.
    return default if not value or (value.startswith("${") and value.endswith("}")) else value


def credentials():
    """(login, password). The Claude Code plugin settings arrive as UNTAPPED_DATAFORSEO_*; Codex and terminals use
    DATAFORSEO_*. A pair is taken whole from one source, never mixed."""
    for prefix in ("UNTAPPED_DATAFORSEO_", "DATAFORSEO_"):
        login, password = env_value(prefix + "LOGIN"), env_value(prefix + "PASSWORD")
        if login or password:
            return login, password
    return "", ""


class Redactor:
    def __init__(self):
        login, password = credentials()
        values = [login, password]
        if login and password:
            values += [login + ":" + password,
                       base64.b64encode((login + ":" + password).encode()).decode()]
        variants = set()
        for value in filter(None, values):
            variants.update((value, urllib.parse.quote(value, safe=""),
                             urllib.parse.quote_plus(value), json.dumps(value)[1:-1]))
        self.values = sorted(variants, key=len, reverse=True)

    def __call__(self, value):
        if isinstance(value, str):
            for secret in self.values:
                value = value.replace(secret, "[REDACTED]")
            return value
        if isinstance(value, list):
            return [self(item) for item in value]
        if isinstance(value, dict):
            return {self(key): self(item) for key, item in value.items()}
        return value


def string(value, name, maximum=700):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ToolError(name + " must be a nonempty string within its length limit.")
    return value.strip()


def normalize(tool, args):
    if tool not in ENDPOINTS or not isinstance(args, dict):
        raise ToolError("Unknown tool or invalid arguments.")
    common = {"location_name", "location_code", "language_code", "max_age_hours", "dry_run"}
    extra = {"keyword", "location_coordinate", "device", "depth", "target_domain"} if tool == "google_serp" else {"keywords", "allow_large_batch"}
    if set(args) - common - extra:
        raise ToolError("Unsupported argument; consult the tool input schema.")
    age = args.get("max_age_hours", 24 if tool == "google_serp" else 720)
    if isinstance(age, bool) or not isinstance(age, (float, int)) or not math.isfinite(age) or age < 0:
        raise ToolError("max_age_hours must be a finite non-negative number.")
    if type(args.get("dry_run", False)) is not bool:
        raise ToolError("dry_run must be a boolean.")
    request = {"language_code": string(args.get("language_code", "en"), "language_code", 20).lower()}
    locations = [key for key in ("location_name", "location_code", "location_coordinate") if key in args]
    if len(locations) > 1:
        raise ToolError("Specify only one location selector.")
    loc = locations[0] if locations else "location_name"
    value = args.get(loc, "United States")
    if loc == "location_code":
        if type(value) is not int or value <= 0:
            raise ToolError("location_code must be a positive integer.")
    elif loc == "location_coordinate":
        value = string(value, loc, 100)
        try:
            parts = [float(v.strip()) for v in value.split(",")]
            if len(parts) not in (2, 3) or not all(math.isfinite(v) for v in parts):
                raise ValueError
            if not (-90 <= parts[0] <= 90 and -180 <= parts[1] <= 180):
                raise ValueError
            if len(parts) == 3 and parts[2] <= 0:
                raise ValueError
            value = ",".join(format(v, ".12g") for v in parts)
        except ValueError:
            raise ToolError("location_coordinate must be lat,lng[,positive radius].") from None
    else:
        value = string(value, loc, 300)
    request[loc] = value
    if tool == "google_serp":
        request["keyword"] = string(args.get("keyword"), "keyword")
        request["depth"] = args.get("depth", 10)
        if type(request["depth"]) is not int or not 10 <= request["depth"] <= 100:
            raise ToolError("depth must be an integer from 10 to 100.")
        request["device"] = args.get("device", "desktop")
        if request["device"] not in ("desktop", "mobile"):
            raise ToolError("device must be desktop or mobile.")
        if "target_domain" in args:
            domain = string(args["target_domain"], "target_domain", 253).lower().rstrip(".")
            if not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", domain) or ".." in domain:
                raise ToolError("target_domain must be a hostname without a URL or path.")
    else:
        keywords = args.get("keywords")
        large = args.get("allow_large_batch", False)
        if type(large) is not bool:
            raise ToolError("allow_large_batch must be a boolean.")
        if not isinstance(keywords, list) or not 1 <= len(keywords) <= 1000:
            raise ToolError("keywords must contain 1 to 1000 entries.")
        normalized = sorted(set(string(v, "keyword", 80).lower() for v in keywords))
        if any(len(v.split()) > 10 for v in normalized):
            raise ToolError("Google Ads keywords must contain at most 10 words each.")
        if len(normalized) > 100 and not large:
            raise ToolError("Over 100 unique keywords requires allow_large_batch=true (hard maximum 1000).")
        request["keywords"] = normalized
    return request, age


def reserve(tool, request):
    price = PRICES[tool]
    if tool == "google_search_volume":
        return units(price["usd_per_task"])
    decoded = request["keyword"]
    # Decode repeatedly to over-reserve rather than miss encoded chargeable syntax.
    for _ in range(len(decoded) + 1):
        next_value = urllib.parse.unquote_plus(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    count = len(re.findall(r"(?:" + "|".join(price["operators"]) + r")\s*:", decoded, re.I))
    return units(price["usd_per_10_results"]) * math.ceil(request["depth"] / 10) * price["operator_multiplier"] ** count


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def urllib_transport(url, payload, headers, timeout):
    # Proxy env vars and redirects cannot divert credentials to a different host.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    with opener.open(request, timeout=timeout) as response:
        return response.read()


class Client:
    def __init__(self, sandbox=False, transport=None):
        self.sandbox = sandbox
        self.transport = transport or urllib_transport

    @property
    def host(self):
        return "https://sandbox.dataforseo.com" if self.sandbox else "https://api.dataforseo.com"

    def credentials(self):
        login, password = credentials()
        if not login or not password:
            raise ToolError("Add your DataForSEO API login and password: in Claude Code, the plugin's settings (/plugin); "
                            "in Codex, the DATAFORSEO_LOGIN and DATAFORSEO_PASSWORD environment variables.")
        return login, password

    def post(self, endpoint, request):
        if endpoint not in ENDPOINTS.values():
            raise ToolError("Endpoint refused: only the two pinned DataForSEO HTTPS endpoints are allowed.")
        login, password = self.credentials()
        auth = base64.b64encode((login + ":" + password).encode("utf-8")).decode("ascii")
        try:
            raw = self.transport(self.host + endpoint, json.dumps([request]).encode("utf-8"),
                                 {"Authorization": "Basic " + auth, "Content-Type": "application/json"}, 60)
            return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except Exception:
            # Never inspect or log HTTP bodies, headers, URLs, or exception strings.
            raise ToolError("DataForSEO transport or JSON failure; outcome UNCERTAIN. No retry was sent.") from None


def response_cost(response):
    if not isinstance(response, dict):
        raise ToolError("Malformed DataForSEO response; outcome UNCERTAIN.")
    if "cost" in response:
        return units(response["cost"])
    tasks = response.get("tasks")
    if isinstance(tasks, list) and tasks and all(isinstance(t, dict) and "cost" in t for t in tasks):
        return sum(units(t["cost"]) for t in tasks)
    raise ToolError("Response has no reliable cost; outcome UNCERTAIN.")


def results(response):
    for item in [response] + (response.get("tasks") or []):
        if not isinstance(item, dict) or type(item.get("status_code")) is not int:
            raise ToolError("Malformed DataForSEO status.")
        code = item["status_code"]
        if code not in (20000, 40102):
            message = item.get("status_message")
            raise ToolError("DataForSEO status " + str(code) + ": " + (message[:500] if isinstance(message, str) else "Task failed."))
    tasks = response.get("tasks")
    if response["status_code"] == 40102:
        return []
    if not isinstance(tasks, list) or len(tasks) != 1:
        raise ToolError("Expected one DataForSEO task.")
    if tasks[0]["status_code"] == 40102:
        return []
    result = tasks[0].get("result")
    if not isinstance(result, list):
        raise ToolError("Malformed DataForSEO task result.")
    return result


def walk(value, parent=None):
    if isinstance(value, dict):
        current = dict(parent or {})
        for key in ("type", "rank_group", "rank_absolute"):
            if value.get(key) is not None:
                current[key] = value[key]
        yield value, current
        for child in value.values():
            if isinstance(child, (dict, list)):
                yield from walk(child, current)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child, parent)


def domain_of(item):
    domain = item.get("domain")
    if isinstance(domain, str) and domain:
        return domain.lower().rstrip(".")
    url = item.get("url")
    if isinstance(url, str):
        return (urllib.parse.urlsplit(url).hostname or "").lower().rstrip(".")
    return ""


def slim_serp(rows, request):
    root = rows[0] if rows else {}
    items = root.get("items") or []
    output = {key: root.get(key) for key in ("check_url", "datetime", "se_results_count")}
    output.update(location={key: root.get(key, value) for key, value in request.items() if key.startswith("location_")},
                  features=[], organic=[], people_also_ask=[], local_pack=[],
                  ai_overview={"present": False, "cited_domains": [], "cited_urls": []},
                  featured_snippet=[], _positions=[])
    if root.get("location_code") is not None:
        output["location"]["location_code"] = root["location_code"]
    # Features = the SERP's top-level blocks in page order; nested *_element types are parts, not features.
    for item in items:
        kind = item.get("type") if isinstance(item, dict) else None
        if kind and kind not in output["features"]:
            output["features"].append(kind)
    for item, position in walk(items):
        kind = item.get("type")
        domain = domain_of(item)
        if domain:
            p = {**position, "domain": domain, "url": item.get("url")}
            if p not in output["_positions"]:
                output["_positions"].append(p)
        if kind == "organic":
            result = {k: item.get(k) for k in ("rank_group", "rank_absolute", "domain", "url", "title", "description")}
            if isinstance(result["description"], str):
                result["description"] = result["description"][:300]
            output["organic"].append(result)
        if kind == "people_also_ask_element" and item.get("title"):
            output["people_also_ask"].append(item["title"])
        if kind == "local_pack":
            result = {k: item.get(k) for k in ("title", "domain")}
            if item.get("rating") is not None:
                rating = item["rating"]
                result["rating"] = {k: rating.get(k) for k in ("value", "votes_count", "rating_max")} if isinstance(rating, dict) else rating
            output["local_pack"].append(result)
        if kind == "featured_snippet":
            output["featured_snippet"].append({"domain": domain, "url": item.get("url")})
        if kind == "ai_overview":
            ai = output["ai_overview"]
            ai["present"] = True
            for citation, _ in walk(item):
                cite_domain, url = domain_of(citation), citation.get("url")
                if cite_domain and cite_domain not in ai["cited_domains"]:
                    ai["cited_domains"].append(cite_domain)
                if url and url not in ai["cited_urls"]:
                    ai["cited_urls"].append(url)
    return output


def apply_target(output, target, depth):
    positions = output.pop("_positions", [])
    if target:
        target = target.lower().rstrip(".")
        hits = [p for p in positions if p["domain"] == target or p["domain"].endswith("." + target)]
        output["target"] = hits if hits else "not in top " + str(depth)
    else:
        output["target"] = None
    return output


def slim_volume(rows, request):
    mapped = {row["keyword"].strip().lower(): row for row in rows if isinstance(row, dict) and isinstance(row.get("keyword"), str)}
    output = []
    for keyword in request["keywords"]:
        row = mapped.get(keyword, {})
        item = {"keyword": keyword, **{key: row.get(key) for key in ("search_volume", "competition", "competition_index", "cpc")}}
        item["status"] = "no data" if item["search_volume"] is None else "available"
        months = sorted(row.get("monthly_searches") or [], key=lambda m: (m["year"], m["month"]), reverse=True)[:12]
        item["monthly_searches"] = [{k: m.get(k) for k in ("year", "month", "search_volume")} for m in months]
        output.append(item)
    return {"keywords": output, "caveat": "Google Ads volumes are rounded buckets; low-volume terms often return null. "
            "Similar keywords may share combined volumes; null means no data, never zero."}
