"""Offline tests for untapped-site-audit. Run: python -m unittest discover -s plugins/untapped-site-audit/tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
PLUGIN = Path(__file__).resolve().parents[1]
LANE = PLUGIN.parent
sys.path.insert(0, str(PLUGIN / "server"))

import audit_server as au  # noqa: E402
from mcp_stdio import ToolError  # noqa: E402

HTML = {"content-type": "text/html; charset=utf-8"}
WORDS = " ".join(["word"] * 300)


def page(title, h1s, canonical, desc="A clear description of the plumbing service in Austin that is long enough to fit the snippet range.",
         robots="", extra=""):
    h = "".join("<h1>%s</h1>" % h for h in h1s)
    return ("<html lang='en'><head><title>%s</title><meta name='description' content='%s'>%s"
            "<link rel='canonical' href='%s'>"
            "<script type='application/ld+json'>{\"@context\":\"https://schema.org\",\"@graph\":[{\"@type\":\"LocalBusiness\"},"
            "{\"@type\":[\"Service\",\"WebPage\"]}]}</script></head><body>%s<h2>Prices</h2><p>%s</p>"
            "<a href='/about/'>About</a><a href='https://www.example.com/x'>x</a><a href='https://other.com/'>o</a>"
            "<a href='mailto:a@b.c'>m</a><img src='a.jpg'><img src='b.jpg' alt='b'>%s<script>var notcounted = 1;</script>"
            "</body></html>") % (title, desc, ("<meta name='robots' content='%s'>" % robots) if robots else "",
                                 canonical, h, WORDS, extra)


SITE = {
    "https://example.com/sitemap.xml": (200, {"content-type": "application/xml"}, b"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://example.com/</loc></url>
<url><loc>https://example.com/plumbing/</loc></url><url><loc>https://example.com/hidden/</loc></url>
<url><loc>https://example.com/old/</loc></url><url><loc>https://example.com/private/</loc></url></urlset>"""),
    "https://example.com/robots.txt": (200, {"content-type": "text/plain"}, b"User-agent: *\nDisallow: /private/\n"),
    "https://example.com/": (200, HTML, page("Plumber in Austin, TX | Example Plumbing Co", ["Austin plumber"],
                                             "https://example.com/").encode()),
    "https://example.com/plumbing/": (200, HTML, page("Plumber in Austin, TX | Example Plumbing Co",
                                                      ["Austin plumber", "Second H1"], "https://example.com/").encode()),
    "https://example.com/hidden/": (200, {**HTML, "x-robots-tag": "noindex"}, page("Hidden page title that is long enough",
                                                                                ["Hidden"], "https://example.com/hidden/").encode()),
    "https://example.com/old/": (301, {"location": "/plumbing/"}, b""),
    "https://example.com/private/": (200, HTML, page("Short", [], "https://example.com/private/", desc="").encode()),
}


class FakeWeb:
    def __init__(self, site):
        self.site, self.calls = site, []

    def __call__(self, url):
        self.calls.append(url)
        if url not in self.site:
            return 404, {"content-type": "text/html"}, b"not found", None
        status, headers, body = self.site[url]
        return status, headers, body, None


class PageFactsTests(unittest.TestCase):
    def test_facts_extracted(self):
        web = FakeWeb(SITE)
        f = au.page_facts("https://example.com/", web)
        self.assertEqual(f["title"], "Plumber in Austin, TX | Example Plumbing Co")
        self.assertEqual(f["h1"], ["Austin plumber"])
        self.assertEqual(f["h2"], ["Prices"])
        self.assertEqual(f["schema_types"], ["LocalBusiness", "Service", "WebPage"])
        self.assertEqual((f["internal_links"], f["external_links"]), (2, 1))  # www. counts as internal; mailto ignored
        self.assertEqual((f["images"], f["images_missing_alt"]), (2, 1))
        self.assertTrue(300 <= f["word_count"] < 330)  # script text not counted
        self.assertTrue(f["robots_txt_allows_googlebot"])
        self.assertEqual(f["problems"], [])

    def test_problems_found(self):
        web = FakeWeb(SITE)
        f = au.page_facts("https://example.com/private/", web)
        joined = " | ".join(f["problems"])
        for expected in ("title is 5 characters", "no meta description", "no H1", "robots.txt blocks Googlebot"):
            self.assertIn(expected, joined)
        moved = au.page_facts("https://example.com/old/", web)
        self.assertEqual(moved["redirects"], [{"url": "https://example.com/old/", "status": 301,
                                                "to": "https://example.com/plumbing/"}])
        self.assertIn("canonical points elsewhere: https://example.com/", " | ".join(moved["problems"]))
        self.assertIn("2 H1s", " | ".join(moved["problems"]))
        hidden = au.page_facts("https://example.com/hidden/", web)
        self.assertTrue(hidden["noindex"])

    def test_private_addresses_refused(self):
        os.environ.pop("UNTAPPED_AUDIT_ALLOW_PRIVATE", None)
        for url in ("http://127.0.0.1:8080/", "http://localhost/", "http://192.168.1.1/admin", "file:///c:/x"):
            with self.assertRaises(ToolError, msg=url):
                au.check_public(url)


class AuditTests(unittest.TestCase):
    def test_sitemap_audit_cross_page_problems(self):
        web = FakeWeb(SITE)
        srv = au.Server(get=web, sleep=lambda s: None)
        out = srv.call("audit_pages", {"site": "example.com"})
        self.assertEqual((out["urls_found"], out["audited"]), (5, 5))
        problems = {(p["problem"], tuple(p["urls"])) for p in out["site_problems"]}
        self.assertIn(("duplicate title", ("https://example.com/", "https://example.com/plumbing/")), problems)
        self.assertIn(("duplicate H1", ("https://example.com/", "https://example.com/plumbing/")), problems)
        self.assertIn(("sitemap lists a noindex page", ("https://example.com/hidden/",)), problems)
        self.assertTrue(any(p[0].startswith("sitemap lists a page that is not a direct 200") and
                            p[1] == ("https://example.com/old/",) for p in problems))
        self.assertEqual(web.calls.count("https://example.com/robots.txt"), 1)  # read once per site
        private = next(p for p in out["pages"] if p["url"] == "https://example.com/private/")
        self.assertTrue(any("robots.txt blocks" in x for x in private["problems"]))

    def test_max_pages_and_url_list(self):
        srv = au.Server(get=FakeWeb(SITE), sleep=lambda s: None)
        out = srv.call("audit_pages", {"site": "https://example.com", "max_pages": 2})
        self.assertEqual((out["audited"], out["not_audited"]), (2, 3))
        listed = srv.call("audit_pages", {"urls": ["https://example.com/hidden/"]})
        self.assertEqual(listed["site_problems"], [])  # noindex is only a problem when the sitemap lists it


class PackagingTests(unittest.TestCase):
    def test_subprocess_lists_tools(self):
        proc = subprocess.run([sys.executable, str(PLUGIN / "server" / "audit_server.py")], timeout=30,
                              input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n",
                              capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual({t["name"] for t in json.loads(proc.stdout)["result"]["tools"]}, {"page_facts", "audit_pages"})
        self.assertEqual(proc.stderr, "")

    def test_manifests_and_shared_copies_current(self):
        for tool in ("manifests.py", "sync_shared.py"):
            proc = subprocess.run([sys.executable, str(LANE / "tools" / tool), "--check"],
                                  capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
