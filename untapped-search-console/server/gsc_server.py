"""untapped-search-console MCP server: what people search to find a site, what's close to page one, what moved."""
import sys

sys.dont_write_bytecode = True

import datetime as dt
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import google_auth as ga  # noqa: E402
from mcp_stdio import ToolError, serve  # noqa: E402

VERSION = "0.1.1"
DIMENSIONS = ("query", "page", "country", "device", "date", "searchAppearance")
SEARCH_TYPES = ("web", "image", "video", "news", "discover", "googleNews")
DEVICES = ("DESKTOP", "MOBILE", "TABLET")
LAG_NOTE = ("The window ends {lag} days ago on purpose: the last ~2 days of Search Console data are not final, and "
            "a window ending today shows a dip that is only late data.")
SITE = {"type": "string", "description": "example.com, sc-domain:example.com or https://example.com/"}
WINDOW = {
    "days": {"type": "integer", "minimum": 1, "maximum": 480, "description": "default 28"},
    "end_lag_days": {"type": "integer", "minimum": 0, "maximum": 30, "description": "default 3 (final data only)"},
}
FILTERS = {
    "query_contains": {"type": "string"}, "page_contains": {"type": "string"},
    "country": {"type": "string", "description": "ISO 3166-1 alpha-3, e.g. usa"},
    "device": {"type": "string", "enum": list(DEVICES)},
    "search_type": {"type": "string", "enum": list(SEARCH_TYPES)},
}
TOOLS = ga.AUTH_TOOLS + [
    {"name": "gsc_sites", "description": "Free. List the Search Console properties your Google sign-in can see.",
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}}},
    {"name": "gsc_performance",
     "description": "Free. Clicks, impressions, CTR and position from Search Console, by query, page, country, "
                    "device or date (or a combination), with optional filters.",
     "inputSchema": {"type": "object", "required": ["site"], "additionalProperties": False, "properties": {
         "site": SITE, **WINDOW, **FILTERS,
         "dimensions": {"type": "array", "items": {"type": "string", "enum": list(DIMENSIONS)}, "maxItems": 3,
                        "description": "default ['query']"},
         "row_limit": {"type": "integer", "minimum": 1, "maximum": 5000, "description": "default 100"}}}},
    {"name": "gsc_totals",
     "description": "Free. The site's true totals (clicks, impressions) for a window, not a sum of top rows.",
     "inputSchema": {"type": "object", "required": ["site"], "additionalProperties": False,
                     "properties": {"site": SITE, **WINDOW, "search_type": FILTERS["search_type"]}}},
    {"name": "gsc_whats_working",
     "description": "Free. Splits the site's search queries into earning (getting clicks: protect), close "
                    "(position 4-20, no clicks yet: where work pays), top3_no_clicks (ranking but not chosen: fix "
                    "the title/snippet) and invisible (past 20: long game or wrong query).",
     "inputSchema": {"type": "object", "required": ["site"], "additionalProperties": False, "properties": {
         "site": SITE, **WINDOW, "min_impressions": {"type": "integer", "minimum": 1, "description": "default 5"},
         "page_contains": FILTERS["page_contains"]}}},
    {"name": "gsc_compare",
     "description": "Free. This window vs the previous window of the same length, by query or page: gainers, "
                    "losers, new and lost, plus true site totals for both windows.",
     "inputSchema": {"type": "object", "required": ["site"], "additionalProperties": False, "properties": {
         "site": SITE, **WINDOW, "dimension": {"type": "string", "enum": ["query", "page"]},
         "page_contains": FILTERS["page_contains"]}}},
]


def window(days=28, end_lag_days=3, today=None):
    if type(days) is not int or not 1 <= days <= 480:
        raise ToolError("days must be 1 to 480.")
    if type(end_lag_days) is not int or not 0 <= end_lag_days <= 30:
        raise ToolError("end_lag_days must be 0 to 30.")
    end = (today or dt.date.today()) - dt.timedelta(days=end_lag_days)
    return end - dt.timedelta(days=days - 1), end


def query_url(prop):
    return ("https://www.googleapis.com/webmasters/v3/sites/%s/searchAnalytics/query"
            % urllib.parse.quote(prop, safe=""))


def row_out(row, dims):
    out = dict(zip(dims, row.get("keys") or []))
    out.update(clicks=row.get("clicks", 0), impressions=row.get("impressions", 0),
               ctr_pct=round(100 * row.get("ctr", 0), 2), position=round(row.get("position", 0), 1))
    return out


class Server:
    def __init__(self, auth=None, today=None):
        self.auth = auth or ga.GoogleAuth()
        self.today = today

    def call(self, name, args):
        handled = ga.handle_auth_tool(self.auth, name, args) if name.startswith("google_") else None
        if handled is not None:
            return handled
        if name == "gsc_sites":
            return ga.list_sites(self.auth)
        handler = {"gsc_performance": self.performance, "gsc_totals": self.totals,
                   "gsc_whats_working": self.whats_working, "gsc_compare": self.compare}.get(name)
        if not handler:
            raise ToolError("Unknown tool: " + str(name)[:60])
        return handler(**args)

    def query(self, prop, start, end, dims, row_limit, query_contains=None, page_contains=None, country=None,
              device=None, search_type="web"):
        if search_type not in SEARCH_TYPES:
            raise ToolError("search_type must be one of " + ", ".join(SEARCH_TYPES))
        filters = []
        for dim, value in (("query", query_contains), ("page", page_contains)):
            if value is not None:
                if not isinstance(value, str) or not value.strip() or len(value) > 300:
                    raise ToolError(dim + "_contains must be a short nonempty string.")
                filters.append({"dimension": dim, "operator": "contains", "expression": value.strip()})
        if country is not None:
            if not isinstance(country, str) or len(country) != 3 or not country.isalpha():
                raise ToolError("country must be a 3-letter ISO code like usa.")
            filters.append({"dimension": "country", "operator": "equals", "expression": country.lower()})
        if device is not None:
            if device not in DEVICES:
                raise ToolError("device must be DESKTOP, MOBILE or TABLET.")
            filters.append({"dimension": "device", "operator": "equals", "expression": device})
        body = {"startDate": start.isoformat(), "endDate": end.isoformat(), "dimensions": list(dims),
                "rowLimit": row_limit, "type": search_type}
        if filters:
            body["dimensionFilterGroups"] = [{"filters": filters}]
        return [row_out(r, dims) for r in self.auth.api("POST", query_url(prop), body).get("rows", [])]

    def meta(self, prop, start, end, lag):
        return {"property": prop, "from": start.isoformat(), "to": end.isoformat(),
                "days": (end - start).days + 1, "note": LAG_NOTE.format(lag=lag) if lag else
                "Includes the last days, which are NOT final yet: expect them to rise."}

    def performance(self, site, days=28, end_lag_days=3, dimensions=None, row_limit=100, **filters):
        dims = dimensions or ["query"]
        if not isinstance(dims, list) or not 1 <= len(dims) <= 3 or any(d not in DIMENSIONS for d in dims):
            raise ToolError("dimensions: 1 to 3 of " + ", ".join(DIMENSIONS))
        if type(row_limit) is not int or not 1 <= row_limit <= 5000:
            raise ToolError("row_limit must be 1 to 5000.")
        prop = ga.resolve_property(self.auth, site)
        start, end = window(days, end_lag_days, self.today)
        rows = self.query(prop, start, end, dims, row_limit, **filters)
        clicks, impressions = sum(r["clicks"] for r in rows), sum(r["impressions"] for r in rows)
        out = self.meta(prop, start, end, end_lag_days)
        out.update(dimensions=dims, rows=rows, rows_returned=len(rows), row_limit=row_limit,
                   returned_rows_sum={"clicks": clicks, "impressions": impressions,
                                      "ctr_pct": round(100 * clicks / impressions, 2) if impressions else 0.0,
                                      "position_weighted": round(sum(r["position"] * r["impressions"] for r in rows)
                                                                 / impressions, 1) if impressions else None},
                   scope_note="Sums cover the returned rows only (Google also hides rare queries for privacy); "
                              "use gsc_totals for the site's true totals. Position is an impression-weighted "
                              "average of averages: directional only.")
        return out

    def totals(self, site, days=28, end_lag_days=3, search_type="web"):
        prop = ga.resolve_property(self.auth, site)
        start, end = window(days, end_lag_days, self.today)
        out = self.meta(prop, start, end, end_lag_days)
        out.update(self.raw_totals(prop, start, end, search_type))
        return out

    def raw_totals(self, prop, start, end, search_type="web"):
        rows = self.auth.api("POST", query_url(prop), {"startDate": start.isoformat(), "endDate": end.isoformat(),
                                                       "rowLimit": 1, "type": search_type}).get("rows", [])
        row = rows[0] if rows else {}
        return {"clicks": row.get("clicks", 0), "impressions": row.get("impressions", 0),
                "ctr_pct": round(100 * row.get("ctr", 0), 2), "position": round(row.get("position", 0), 1) or None,
                "measured_zero": not rows}

    def whats_working(self, site, days=28, end_lag_days=3, min_impressions=5, page_contains=None):
        if type(min_impressions) is not int or min_impressions < 1:
            raise ToolError("min_impressions must be a positive integer.")
        prop = ga.resolve_property(self.auth, site)
        start, end = window(days, end_lag_days, self.today)
        rows = self.query(prop, start, end, ["query"], 1000, page_contains=page_contains)
        groups = {"earning": [], "top3_no_clicks": [], "close": [], "invisible": []}
        below = 0
        for r in rows:
            if r["impressions"] < min_impressions:
                below += 1
            elif r["clicks"] > 0:
                groups["earning"].append(r)
            elif r["position"] < 4:
                groups["top3_no_clicks"].append(r)
            elif r["position"] <= 20:
                groups["close"].append(r)
            else:
                groups["invisible"].append(r)
        order = {"earning": lambda r: -r["clicks"], "top3_no_clicks": lambda r: -r["impressions"],
                 "close": lambda r: r["position"], "invisible": lambda r: -r["impressions"]}
        out = self.meta(prop, start, end, end_lag_days)
        out.update({k: sorted(v, key=order[k])[:25] for k, v in groups.items()})
        out.update(counts={k: len(v) for k, v in groups.items()}, below_min_impressions=below,
                   min_impressions=min_impressions, queries_returned=len(rows),
                   what_to_do={"earning": "Protect: don't rewrite these pages' titles or H1s casually.",
                               "top3_no_clicks": "Seen near the top but not chosen: rewrite the title and meta "
                                                 "description to match the query's intent.",
                               "close": "Where work pays: strengthen the page that ranks (answer the query in "
                                        "a section, add internal links to it) before writing a new page.",
                               "invisible": "Long game, or the wrong query for this site: check the intent."})
        return out

    def compare(self, site, days=28, end_lag_days=3, dimension="query", page_contains=None):
        if dimension not in ("query", "page"):
            raise ToolError("dimension must be query or page.")
        prop = ga.resolve_property(self.auth, site)
        start, end = window(days, end_lag_days, self.today)
        p_end = start - dt.timedelta(days=1)
        p_start = p_end - dt.timedelta(days=days - 1)
        now = {r[dimension]: r for r in self.query(prop, start, end, [dimension], 1000, page_contains=page_contains)}
        before = {r[dimension]: r for r in self.query(prop, p_start, p_end, [dimension], 1000,
                                                      page_contains=page_contains)}
        changes = []
        for key in set(now) | set(before):
            a, b = now.get(key), before.get(key)
            changes.append({dimension: key,
                            "clicks": (a or {}).get("clicks", 0), "clicks_before": (b or {}).get("clicks", 0),
                            "impressions": (a or {}).get("impressions", 0),
                            "impressions_before": (b or {}).get("impressions", 0),
                            "position": (a or {}).get("position"), "position_before": (b or {}).get("position"),
                            "status": "new" if not b else "lost" if not a else "both"})
        for c in changes:
            c["impressions_change"] = c["impressions"] - c["impressions_before"]
            c["clicks_change"] = c["clicks"] - c["clicks_before"]
        both = [c for c in changes if c["status"] == "both"]
        out = {"property": prop, "dimension": dimension,
               "current": {"from": start.isoformat(), "to": end.isoformat(),
                           **self.raw_totals(prop, start, end)},
               "previous": {"from": p_start.isoformat(), "to": p_end.isoformat(),
                            **self.raw_totals(prop, p_start, p_end)},
               "gainers": sorted([c for c in both if c["impressions_change"] > 0],
                                 key=lambda c: -c["impressions_change"])[:15],
               "losers": sorted([c for c in both if c["impressions_change"] < 0],
                                key=lambda c: c["impressions_change"])[:15],
               "new": sorted([c for c in changes if c["status"] == "new"], key=lambda c: -c["impressions"])[:15],
               "lost": sorted([c for c in changes if c["status"] == "lost"],
                              key=lambda c: -c["impressions_before"])[:15],
               "note": "new/lost compare the top 1,000 rows of each window, so 'lost' can mean 'fell below the top "
                       "1,000', and Google hides rare queries. " + LAG_NOTE.format(lag=end_lag_days)}
        return out


def main():
    server = Server()
    serve(TOOLS, server.call, name="untapped-search-console", version=VERSION, sanitize=ga.Redactor(server.auth))


if __name__ == "__main__":
    main()
