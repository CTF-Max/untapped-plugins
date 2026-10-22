"""untapped-site-audit MCP server: on-page facts per URL and cross-page problems across a sitemap."""
import sys

sys.dont_write_bytecode = True

import html.parser
import ipaddress
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp_stdio import ToolError, serve  # noqa: E402

VERSION = "0.1.1"
UA = "Mozilla/5.0 (compatible; UntappedSiteAudit/0.1; +https://finduntappedgrowth.com/)"
MAX_BYTES = 5_000_000
MAX_REDIRECTS = 5
DEFAULT_PAGES, HARD_PAGES = 25, 200
TITLE_RANGE, META_RANGE = (30, 60), (70, 160)
TOOLS = [
    {"name": "page_facts",
     "description": "Free. Fetch one page and report what search engines read: status, redirect chain, title, "
                    "meta description, robots (meta + header + robots.txt for Googlebot), canonical, H1/H2s, "
                    "schema types, hreflang, word count, links, images without alt, and problems found.",
     "inputSchema": {"type": "object", "required": ["url"], "additionalProperties": False,
                     "properties": {"url": {"type": "string"}}}},
    {"name": "audit_pages",
     "description": "Free. page_facts for every URL in a sitemap (default /sitemap.xml) or a list, plus problems "
                    "across pages: duplicate titles/H1s/meta, noindex or non-200 pages listed in the sitemap, "
                    "canonicals pointing elsewhere, missing titles/H1s/meta.",
     "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
         "site": {"type": "string", "description": "https://example.com (reads /sitemap.xml)"},
         "sitemap_url": {"type": "string"},
         "urls": {"type": "array", "items": {"type": "string"}, "maxItems": HARD_PAGES},
         "max_pages": {"type": "integer", "minimum": 1, "maximum": HARD_PAGES, "description": "default 25"}}}},
]


def allow_private():
    return os.environ.get("UNTAPPED_AUDIT_ALLOW_PRIVATE", "") in ("1", "true", "yes")


def check_public(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ToolError("Only http(s) URLs can be audited.")
    if allow_private():
        return
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80))
    except socket.gaierror:
        raise ToolError("Could not resolve %s." % parts.hostname) from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ToolError("Refused: %s is a private/local address (set UNTAPPED_AUDIT_ALLOW_PRIVATE=1 to audit a "
                            "local preview)." % parts.hostname)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_get(url):
    """(status, headers dict lower-cased, body bytes, error). Never follows redirects itself."""
    check_public(url)
    opener = urllib.request.build_opener(NoRedirect())
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xml;q=0.9,*/*;q=0.8"})
    try:
        with opener.open(req, timeout=20) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read(MAX_BYTES), None
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read(MAX_BYTES), None
    except Exception as exc:
        return None, {}, b"", type(exc).__name__


def fetch(url, get=http_get):
    """Follow up to 5 redirects by hand so the chain is visible."""
    chain = []
    for _ in range(MAX_REDIRECTS + 1):
        status, headers, body, error = get(url)
        if status in (301, 302, 303, 307, 308) and headers.get("location"):
            nxt = urllib.parse.urljoin(url, headers["location"])
            chain.append({"url": url, "status": status, "to": nxt})
            url = nxt
            continue
        return {"final_url": url, "status": status, "headers": headers, "body": body, "error": error, "chain": chain}
    return {"final_url": url, "status": None, "headers": {}, "body": b"", "error": "too many redirects", "chain": chain}


class PageParser(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.in_title = "", False
        self.meta, self.links, self.anchors, self.images = {}, [], [], []
        self.headings, self.current = [], None
        self.jsonld, self.in_jsonld, self.lang = [], False, ""
        self.skip_depth, self.words = 0, 0

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "html":
            self.lang = a.get("lang", "")
        elif tag == "title":
            self.in_title = True
        elif tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            if key and key not in self.meta:
                self.meta[key] = a.get("content", "")
        elif tag == "link":
            self.links.append(a)
        elif tag == "a" and a.get("href"):
            self.anchors.append(a["href"])
        elif tag == "img":
            self.images.append(a)
        elif tag in ("h1", "h2"):
            self.current = [tag, ""]
        elif tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self.in_jsonld = True
            self.jsonld.append("")
        if tag in self.SKIP:
            self.skip_depth += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag in ("h1", "h2") and self.current and self.current[0] == tag:
            self.headings.append((tag, " ".join(self.current[1].split())))
            self.current = None
        elif tag == "script":
            self.in_jsonld = False
        if tag in self.SKIP and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.in_jsonld:
            self.jsonld[-1] += data
            return
        if self.current is not None:
            self.current[1] += data
        if not self.skip_depth:
            self.words += len(re.findall(r"\w+", data))


def schema_types(blocks):
    types, broken = [], 0
    for raw in blocks:
        try:
            data = json.loads(raw)
        except ValueError:
            broken += 1
            continue
        queue = [data]  # breadth-first keeps the page's order
        while queue:
            item = queue.pop(0)
            if isinstance(item, list):
                queue.extend(item)
            elif isinstance(item, dict):
                t = item.get("@type")
                for name in (t if isinstance(t, list) else [t]):
                    if isinstance(name, str) and name not in types:
                        types.append(name)
                queue.extend(v for k, v in item.items() if isinstance(v, (dict, list)))
    return types, broken


def robots_allows(url, get=http_get, cache=None):
    """True/False for Googlebot, or None if robots.txt couldn't be read. cache: {robots_url: parser|'all'|None}."""
    parts = urllib.parse.urlsplit(url)
    robots_url = "%s://%s/robots.txt" % (parts.scheme, parts.netloc)
    cache = cache if cache is not None else {}
    if robots_url not in cache:
        status, _, body, error = get(robots_url)
        if error or status is None:
            cache[robots_url] = None
        elif status >= 400:
            cache[robots_url] = "all"  # no robots.txt = everything allowed
        else:
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(body.decode("utf-8", "replace").splitlines())
            cache[robots_url] = rp
    rule = cache[robots_url]
    if rule is None:
        return None, robots_url
    return (True if rule == "all" else rule.can_fetch("Googlebot", url)), robots_url


def page_facts(url, get=http_get, robots_cache=None):
    if not isinstance(url, str) or len(url) > 2000:
        raise ToolError("url must be a full http(s) URL.")
    got = fetch(url.strip(), get)
    out = {"url": url, "final_url": got["final_url"], "status": got["status"], "redirects": got["chain"]}
    if got["error"]:
        out["error"] = got["error"]
        out["problems"] = ["could not fetch (%s)" % got["error"]]
        return out
    ctype = got["headers"].get("content-type", "")
    if "html" not in ctype:
        out["content_type"] = ctype
        out["problems"] = [] if got["status"] == 200 else ["status %s" % got["status"]]
        return out
    charset = re.search(r"charset=([\w-]+)", ctype)
    try:
        text = got["body"].decode(charset.group(1) if charset else "utf-8", "replace")
    except LookupError:
        text = got["body"].decode("utf-8", "replace")
    p = PageParser()
    p.feed(text)
    base = got["final_url"]
    host = urllib.parse.urlsplit(base).hostname or ""
    canon = [urllib.parse.urljoin(base, l.get("href", "")) for l in p.links if "canonical" in l.get("rel", "").lower().split()]
    hreflang = [{"lang": l.get("hreflang"), "href": l.get("href")} for l in p.links if l.get("hreflang")]
    internal = external = 0
    for href in p.anchors:
        target = urllib.parse.urlsplit(urllib.parse.urljoin(base, href))
        if target.scheme not in ("http", "https"):
            continue
        if (target.hostname or "").removeprefix("www.") == host.removeprefix("www."):
            internal += 1
        else:
            external += 1
    types, broken_jsonld = schema_types(p.jsonld)
    title = " ".join(p.title.split())
    meta_desc = " ".join(p.meta.get("description", "").split())
    robots_meta = (p.meta.get("robots", "") + "," + p.meta.get("googlebot", "")).lower()
    x_robots = got["headers"].get("x-robots-tag", "").lower()
    h1 = [t for tag, t in p.headings if tag == "h1"]
    out.update({
        "title": title, "title_length": len(title), "meta_description": meta_desc,
        "meta_description_length": len(meta_desc), "meta_robots": p.meta.get("robots", ""),
        "x_robots_tag": got["headers"].get("x-robots-tag", ""), "canonical": canon[0] if canon else "",
        "h1": h1, "h2": [t for tag, t in p.headings if tag == "h2"][:20], "lang": p.lang, "hreflang": hreflang,
        "schema_types": types, "word_count": p.words, "internal_links": internal, "external_links": external,
        "images": len(p.images), "images_missing_alt": sum(1 for i in p.images if not i.get("alt", "").strip()),
        "og_title": p.meta.get("og:title", ""),
    })
    problems = []
    noindex = "noindex" in robots_meta or "noindex" in x_robots
    out["noindex"] = noindex
    if got["status"] != 200:
        problems.append("status %s" % got["status"])
    if got["chain"]:
        problems.append("redirects %d time(s) before the page" % len(got["chain"]))
    if noindex:
        problems.append("noindex: search engines are asked not to index this page")
    if not title:
        problems.append("no <title>")
    elif not TITLE_RANGE[0] <= len(title) <= TITLE_RANGE[1]:
        problems.append("title is %d characters (aim %d-%d; Google cuts long ones)" % ((len(title),) + TITLE_RANGE))
    if not meta_desc:
        problems.append("no meta description")
    elif not META_RANGE[0] <= len(meta_desc) <= META_RANGE[1]:
        problems.append("meta description is %d characters (aim %d-%d)" % ((len(meta_desc),) + META_RANGE))
    if not h1:
        problems.append("no H1")
    elif len(h1) > 1:
        problems.append("%d H1s (one is clearer)" % len(h1))
    if not canon:
        problems.append("no canonical tag")
    elif canon[0].rstrip("/") != base.rstrip("/"):
        problems.append("canonical points elsewhere: %s" % canon[0])
    if broken_jsonld:
        problems.append("%d JSON-LD block(s) are not valid JSON" % broken_jsonld)
    if p.words < 250:
        problems.append("thin: %d words of visible text" % p.words)
    allowed, robots_url = robots_allows(base, get, robots_cache)
    out["robots_txt_allows_googlebot"] = allowed
    if allowed is False:
        problems.append("robots.txt blocks Googlebot (%s)" % robots_url)
    out["problems"] = problems
    out["note"] = ("Reads the HTML as served. Content a page builds with JavaScript after loading is not seen "
                   "here (Google usually renders it, but later).")
    return out


def sitemap_urls(url, get=http_get, depth=0, seen=None):
    seen = seen if seen is not None else set()
    if url in seen or len(seen) > 20:
        return []
    seen.add(url)
    got = fetch(url, get)
    if got["error"] or got["status"] != 200:
        raise ToolError("Could not read the sitemap %s (status %s)." % (url[:200], got["status"] or got["error"]))
    try:
        root = ET.fromstring(got["body"])
    except ET.ParseError:
        raise ToolError("The sitemap at %s is not valid XML." % url[:200]) from None
    locs = [loc.text.strip() for entry in root for loc in entry
            if loc.tag.rsplit("}", 1)[-1] == "loc" and loc.text and loc.text.strip()]
    if root.tag.endswith("sitemapindex"):
        return [] if depth >= 2 else [u for child in locs for u in sitemap_urls(child, get, depth + 1, seen)]
    return locs


def duplicates(pages, field):
    seen = {}
    for p in pages:
        if p.get("redirects") or p.get("status") != 200:
            continue  # a redirected URL is not its own page; it is flagged separately
        value = p.get(field)
        if isinstance(value, list):
            value = value[0] if value else ""
        if value:
            seen.setdefault(value.strip().lower(), []).append(p["url"])
    return [{"value": k, "urls": v} for k, v in seen.items() if len(v) > 1]


class Server:
    def __init__(self, get=http_get, sleep=time.sleep):
        self.get, self.sleep = get, sleep

    def call(self, name, args):
        if name == "page_facts":
            if set(args) != {"url"}:
                raise ToolError("page_facts takes url.")
            return page_facts(args["url"], self.get)
        if name == "audit_pages":
            return self.audit(**args)
        raise ToolError("Unknown tool: " + str(name)[:60])

    def audit(self, site=None, sitemap_url=None, urls=None, max_pages=DEFAULT_PAGES):
        if type(max_pages) is not int or not 1 <= max_pages <= HARD_PAGES:
            raise ToolError("max_pages must be 1 to %d." % HARD_PAGES)
        from_sitemap = not urls
        if urls:
            if not isinstance(urls, list) or not all(isinstance(u, str) for u in urls):
                raise ToolError("urls must be a list of URLs.")
            found = list(dict.fromkeys(u.strip() for u in urls))
            source = "urls"
        else:
            if not (sitemap_url or site):
                raise ToolError("Give site, sitemap_url or urls.")
            source = sitemap_url or (site.rstrip("/") if site.startswith("http") else "https://" + site.strip("/")) \
                + "/sitemap.xml"
            found = list(dict.fromkeys(sitemap_urls(source, self.get)))
        todo = found[:max_pages]
        pages, robots_cache = [], {}
        for i, url in enumerate(todo):
            if i:
                self.sleep(0.5)  # polite: one request at a time
            pages.append(page_facts(url, self.get, robots_cache))
        site_problems = []
        for field, label in (("title", "duplicate title"), ("h1", "duplicate H1"),
                             ("meta_description", "duplicate meta description")):
            for d in duplicates(pages, field):
                site_problems.append({"problem": label, "value": d["value"][:120], "urls": d["urls"]})
        if from_sitemap:
            for p in pages:
                if p.get("noindex"):
                    site_problems.append({"problem": "sitemap lists a noindex page", "urls": [p["url"]]})
                if p.get("status") != 200 or p.get("redirects"):
                    site_problems.append({"problem": "sitemap lists a page that is not a direct 200 (status %s%s)"
                                                     % (p.get("status"), ", redirects" if p.get("redirects") else ""),
                                          "urls": [p["url"]]})
        counts = {}
        for p in pages:
            for prob in p.get("problems", []):
                key = re.sub(r"\d+", "N", prob.split(":")[0].split(" (")[0])
                counts[key] = counts.get(key, 0) + 1
        return {"source": source, "urls_found": len(found), "audited": len(pages),
                "not_audited": max(0, len(found) - len(pages)),
                "robots_txt_read": {u: ("unreadable" if r is None else "none (all allowed)" if r == "all" else "read")
                                    for u, r in robots_cache.items()},
                "site_problems": site_problems, "problem_counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
                "pages": [{k: p.get(k) for k in ("url", "status", "title", "h1", "canonical", "word_count",
                                                 "schema_types", "problems")} for p in pages]}


def main():
    server = Server()
    serve(TOOLS, server.call, name="untapped-site-audit", version=VERSION)


if __name__ == "__main__":
    main()
