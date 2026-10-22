"""untapped-index-watch MCP server: is every page in Google's index, and what changed since the last check."""
import sys

sys.dont_write_bytecode = True

import datetime as dt
import sqlite3
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import google_auth as ga  # noqa: E402
from mcp_stdio import ToolError, serve  # noqa: E402

VERSION = "0.1.1"
INSPECT_URL = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
DEFAULT_MAX, HARD_MAX = 50, 500        # Google allows 2,000 inspections per property per day
STALE_CRAWL_DAYS = 45
SITEMAP_BYTES = 10_000_000
FIELDS = ("verdict", "coverage_state", "indexing_state", "robots_state", "page_fetch_state", "last_crawl",
          "google_canonical", "user_canonical", "error")

# What each Google coverage state usually means and what to do (SOP-MEASURE-INDEX-001, Find Untapped Growth).
ADVICE = [
    ("unknown to google", "Google hasn't found the page yet (new page, sitemap not submitted, few links).",
     "Submit the sitemap in Search Console, link the page from a page Google already crawls, then use URL "
     "Inspection → Request indexing in the browser."),
    ("discovered - currently not indexed", "Google knows the URL but hasn't crawled it: low priority for a young "
     "or low-authority site.", "Link to it from the homepage or a strong page; make sure it isn't a thin "
     "near-duplicate; request indexing once. Persistent = an authority problem, not a penalty."),
    ("crawled - currently not indexed", "Google read it and chose not to index it.",
     "Treat it as a quality or duplicate signal: make it unique and useful for one buyer question, or merge it."),
    ("duplicate", "Google treats another URL as the main copy.",
     "Fix the duplicate (trailing slash, http/https, near-identical page) or the canonical tag."),
    ("page with redirect", "The URL redirects. Usually your redirects working, not an error.",
     "Nothing, if the redirect is intended. Remove redirected URLs from the sitemap."),
    ("noindex", "The page asks not to be indexed.", "Intended? If not, remove the noindex and redeploy."),
    ("blocked by robots.txt", "robots.txt blocks Googlebot.", "Intended? If not, fix robots.txt."),
    ("not found (404)", "The URL returns 404.", "Fix or 301 the URL, and drop it from the sitemap."),
    ("soft 404", "The page looks empty or like an error page to Google.", "Add real content or return a real 404."),
    ("server error", "Your server failed when Google fetched it.", "Open the URL logged out; check hosting/firewall."),
]
TOOLS = ga.AUTH_TOOLS + [
    {"name": "gsc_sites", "description": "Free. List the Search Console properties your Google sign-in can see.",
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {}}},
    {"name": "index_check",
     "description": "Check whether each page of a site is in Google's index (Search Console URL Inspection), flag "
                    "what needs attention with what to do, and compare with the last check. URLs come from the "
                    "sitemap (default /sitemap.xml) or a list. Free (Google quota: 2,000 per site per day).",
     "inputSchema": {"type": "object", "required": ["site"], "additionalProperties": False, "properties": {
         "site": {"type": "string", "description": "example.com, sc-domain:example.com or https://example.com/"},
         "sitemap_url": {"type": "string"},
         "urls": {"type": "array", "items": {"type": "string"}, "maxItems": HARD_MAX},
         "max_urls": {"type": "integer", "minimum": 1, "maximum": HARD_MAX, "description": "default 50"},
     }}},
    {"name": "index_history",
     "description": "Free, local. Past index checks for a site (counts per run), or one URL's history.",
     "inputSchema": {"type": "object", "required": ["site"], "additionalProperties": False, "properties": {
         "site": {"type": "string"}, "url": {"type": "string"}}}},
]


def utc_now():
    return dt.datetime.now(dt.timezone.utc)


def data_home():
    override = ga.env_value("UNTAPPED_INDEX_HOME")
    if override:
        return Path(override)
    return ga.google_home().parent / "index-watch"


def fetch_sitemap(url, fetch=None, depth=0, seen=None):
    """All <loc> page URLs in a sitemap or sitemap index (max 20 child sitemaps, 10 MB each)."""
    seen = seen if seen is not None else set()
    if url in seen or len(seen) > 20:
        return []
    seen.add(url)
    if not url.startswith(("https://", "http://")):
        raise ToolError("sitemap_url must be an http(s) URL.")
    raw = (fetch or default_fetch)(url)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise ToolError("The sitemap at %s is not valid XML." % url[:200]) from None
    # Only <url><loc> / <sitemap><loc>: image and video extensions have their own *:loc tags deeper down.
    locs = [loc.text.strip() for entry in root for loc in entry
            if loc.tag.rsplit("}", 1)[-1] == "loc" and loc.text and loc.text.strip()]
    if root.tag.endswith("sitemapindex"):
        if depth >= 2:
            return []
        pages = []
        for child in locs:
            pages += fetch_sitemap(child, fetch, depth + 1, seen)
        return pages
    return locs


def default_fetch(url):
    # Sites behind Cloudflare often 403 Python's default User-Agent.
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; UntappedIndexWatch/0.1)"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read(SITEMAP_BYTES + 1)
    except Exception as exc:
        raise ToolError("Could not fetch the sitemap %s (%s)." % (url[:200], type(exc).__name__)) from None
    if len(body) > SITEMAP_BYTES:
        raise ToolError("Sitemap larger than 10 MB; pass urls instead.")
    return body


def default_sitemap(prop):
    if prop.startswith("sc-domain:"):
        return "https://" + prop[len("sc-domain:"):] + "/sitemap.xml"
    return prop.rstrip("/") + "/sitemap.xml"


def slim_inspection(response):
    s = (response.get("inspectionResult") or {}).get("indexStatusResult") or {}
    # *_UNSPECIFIED = Google has no data (often: not crawled yet), not a problem in itself.
    s = {k: ("" if isinstance(v, str) and v.endswith("_UNSPECIFIED") else v) for k, v in s.items()}
    return {"verdict": s.get("verdict", ""), "coverage_state": s.get("coverageState", ""),
            "indexing_state": s.get("indexingState", ""), "robots_state": s.get("robotsTxtState", ""),
            "page_fetch_state": s.get("pageFetchState", ""), "last_crawl": s.get("lastCrawlTime", ""),
            "google_canonical": s.get("googleCanonical", ""), "user_canonical": s.get("userCanonical", ""),
            "error": ""}


def indexed(row):
    return bool(row) and row.get("verdict") == "PASS" and not row.get("error")


def flags(now, before, today):
    """Plain-language reasons to look at a page. Empty list = nothing to do."""
    if now.get("error"):
        return ["UNKNOWN: inspection failed (%s). This is not 'not indexed'; check again later." % now["error"]]
    out = []
    if before and indexed(before) and not indexed(now):
        out.append("DROPPED OUT of the index (now: %s)" % (now.get("coverage_state") or now.get("verdict")))
    elif not indexed(now):
        out.append("not indexed: %s" % (now.get("coverage_state") or now.get("verdict") or "no data"))
    if now.get("indexing_state") not in ("", "INDEXING_ALLOWED"):
        out.append("indexing blocked by the page itself: %s" % now["indexing_state"])
    if now.get("robots_state") not in ("", "ALLOWED"):
        out.append("robots.txt: %s" % now["robots_state"])
    if now.get("page_fetch_state") not in ("", "SUCCESSFUL"):
        out.append("Google could not fetch it: %s" % now["page_fetch_state"])
    gc, uc = now.get("google_canonical"), now.get("user_canonical")
    if gc and uc and gc != uc:
        out.append("Google chose a different canonical: %s" % gc)
    if now.get("last_crawl"):
        try:
            crawled = dt.datetime.fromisoformat(now["last_crawl"].replace("Z", "+00:00"))
            days = (today - crawled).days
            if days > STALE_CRAWL_DAYS:
                out.append("not crawled for %d days" % days)
        except ValueError:
            pass
    if before and indexed(before) and indexed(now) and gc and before.get("google_canonical") not in ("", gc):
        out.append("canonical changed: %s -> %s" % (before.get("google_canonical"), gc))
    return out


def advice(row):
    if row.get("error"):
        return None
    text = " ".join(str(row.get(k, "")) for k in ("coverage_state", "indexing_state", "robots_state",
                                                  "page_fetch_state")).lower()
    for needle, means, do in ADVICE:
        if needle in text:
            return {"usually_means": means, "do": do}
    if row.get("indexing_state") not in ("", "INDEXING_ALLOWED", None):
        return {"usually_means": ADVICE[5][1], "do": ADVICE[5][2]}
    return None


class Store:
    def __init__(self, home=None):
        self.home = Path(home) if home else data_home()
        self.home.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.home / "index_watch.sqlite3"), isolation_level=None, timeout=30)
        self.db.execute("CREATE TABLE IF NOT EXISTS inspections (checked_utc TEXT, property TEXT, url TEXT, "
                        + ", ".join(f + " TEXT" for f in FIELDS) + ")")
        self.db.execute("CREATE INDEX IF NOT EXISTS by_url ON inspections (property, url, checked_utc)")

    def previous(self, prop, url, before_utc):
        cur = self.db.execute("SELECT " + ", ".join(FIELDS) + " FROM inspections WHERE property=? AND url=? "
                              "AND checked_utc<? AND error='' ORDER BY checked_utc DESC LIMIT 1", (prop, url, before_utc))
        row = cur.fetchone()
        return dict(zip(FIELDS, row)) if row else None

    def add(self, stamp, prop, url, row):
        self.db.execute("INSERT INTO inspections VALUES (?,?,?," + ",".join("?" * len(FIELDS)) + ")",
                        (stamp, prop, url) + tuple(row.get(f, "") for f in FIELDS))

    def runs(self, prop):
        cur = self.db.execute("SELECT checked_utc, COUNT(*), SUM(verdict='PASS' AND error=''), SUM(error!='') "
                              "FROM inspections WHERE property=? GROUP BY checked_utc ORDER BY checked_utc DESC "
                              "LIMIT 30", (prop,))
        return [{"checked_utc": r[0], "checked": r[1], "indexed": r[2], "unknown": r[3],
                 "not_indexed": r[1] - r[2] - r[3]} for r in cur]

    def url_history(self, prop, url):
        cur = self.db.execute("SELECT checked_utc, " + ", ".join(FIELDS) + " FROM inspections WHERE property=? "
                              "AND url=? ORDER BY checked_utc DESC LIMIT 30", (prop, url))
        return [dict(zip(("checked_utc",) + FIELDS, r)) for r in cur]


class Server:
    def __init__(self, auth=None, store=None, fetch=None, clock=utc_now):
        self.auth = auth or ga.GoogleAuth()
        self._store = store
        self.fetch = fetch
        self.clock = clock

    @property
    def store(self):
        if self._store is None:
            self._store = Store()
        return self._store

    def call(self, name, args):
        handled = ga.handle_auth_tool(self.auth, name, args) if name.startswith("google_") else None
        if handled is not None:
            return handled
        if name == "gsc_sites":
            return ga.list_sites(self.auth)
        if name == "index_check":
            return self.index_check(**args)
        if name == "index_history":
            prop = ga.resolve_property(self.auth, args.get("site"))
            if args.get("url"):
                return {"property": prop, "url": args["url"], "history": self.store.url_history(prop, args["url"])}
            return {"property": prop, "runs": self.store.runs(prop)}
        raise ToolError("Unknown tool: " + str(name)[:60])

    def index_check(self, site, sitemap_url=None, urls=None, max_urls=DEFAULT_MAX):
        if type(max_urls) is not int or not 1 <= max_urls <= HARD_MAX:
            raise ToolError("max_urls must be 1 to %d." % HARD_MAX)
        prop = ga.resolve_property(self.auth, site)
        if urls:
            if not isinstance(urls, list) or not all(isinstance(u, str) and u.startswith("http") for u in urls):
                raise ToolError("urls must be a list of full http(s) URLs.")
            source, found = "urls", list(dict.fromkeys(u.strip() for u in urls))
        else:
            source = sitemap_url or default_sitemap(prop)
            found = list(dict.fromkeys(fetch_sitemap(source, self.fetch)))
        if not found:
            raise ToolError("No URLs to check (the sitemap had no <loc> entries).")
        todo, skipped = found[:max_urls], max(0, len(found) - max_urls)
        now = self.clock()
        stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        rows, stopped = [], None
        for url in todo:
            if stopped:
                break
            try:
                row = slim_inspection(self.auth.api("POST", INSPECT_URL, {
                    "inspectionUrl": url, "siteUrl": prop, "languageCode": "en-US"}))
            except ga.ApiError as exc:
                if exc.status in (401, 403) and not rows:
                    raise  # sign-in or permission problem: nothing will work, say so plainly
                row = dict.fromkeys(FIELDS, "")
                row["error"] = str(exc)[:200]
                if exc.status == 429 or "quota" in str(exc).lower():
                    stopped = "Google's inspection quota was reached; the rest were not checked."
            before = self.store.previous(prop, url, stamp)
            self.store.add(stamp, prop, url, row)
            rows.append((url, row, before))

        attention, ok, by_state = [], 0, {}
        dropped, gained = [], []
        for url, row, before in rows:
            state = "UNKNOWN (inspection failed)" if row["error"] else (row["coverage_state"] or row["verdict"] or "no data")
            by_state[state] = by_state.get(state, 0) + 1
            if before and indexed(before) and not indexed(row) and not row["error"]:
                dropped.append(url)
            if before and not indexed(before) and indexed(row):
                gained.append(url)
            f = flags(row, before, now)
            if f:
                item = {"url": url, "flags": f, "coverage_state": row["coverage_state"], "last_crawl": row["last_crawl"]}
                a = advice(row)
                if a:
                    item.update(a)
                attention.append(item)
            else:
                ok += 1
        n_unknown = sum(1 for _, r, _ in rows if r["error"])
        n_indexed = sum(1 for _, r, _ in rows if indexed(r))
        out = {"property": prop, "url_source": source, "checked_utc": stamp, "urls_found": len(found),
               "checked": len(rows), "not_checked": skipped + (len(todo) - len(rows)),
               "summary": {"indexed": n_indexed, "not_indexed": len(rows) - n_indexed - n_unknown,
                           "unknown": n_unknown, "by_coverage_state": by_state},
               "needs_attention": attention, "fine": ok, "newly_dropped": dropped, "newly_indexed": gained,
               "note": "UNKNOWN means the inspection call failed, not that the page is missing. "
                       "Request indexing is a manual browser step in Search Console; there is no API for it."}
        if stopped:
            out["stopped"] = stopped
        if skipped:
            out["truncated"] = "%d more URLs were not checked; raise max_urls (up to %d)." % (skipped, HARD_MAX)
        return out


def main():
    server = Server()
    serve(TOOLS, server.call, name="untapped-index-watch", version=VERSION, sanitize=ga.Redactor(server.auth))


if __name__ == "__main__":
    main()
