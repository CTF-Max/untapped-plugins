"""Offline tests for untapped-index-watch + the shared Google sign-in. Run:
python -m unittest discover -s plugins/untapped-index-watch/tests"""
import datetime as dt
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.parse
import urllib.request
from pathlib import Path

sys.dont_write_bytecode = True
PLUGIN = Path(__file__).resolve().parents[1]
LANE = PLUGIN.parent
sys.path.insert(0, str(PLUGIN / "server"))

import google_auth as ga  # noqa: E402
import index_server as ix  # noqa: E402
from mcp_stdio import ToolError, serve  # noqa: E402

CLIENT_SECRET = "GOCSPX-client-SECRET-4471"
REFRESH = "1//refresh-SECRET-8812"
ACCESS = "ya29.access-SECRET-5520"
NOW = dt.datetime(2026, 10, 9, 12, 0, tzinfo=dt.timezone.utc)
ENV_VARS = ("UNTAPPED_GOOGLE_CLIENT_SECRET", "UNTAPPED_GOOGLE_CLIENT_JSON", "UNTAPPED_GOOGLE_HOME", "UNTAPPED_INDEX_HOME")

SITEMAP_INDEX = b"""<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://example.com/pages.xml</loc></sitemap></sitemapindex>"""
PAGES = b"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
 xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
<url><loc>https://example.com/</loc><image:image><image:loc>https://example.com/a.jpg</image:loc></image:image></url>
<url><loc>https://example.com/new/</loc></url>
<url><loc>https://example.com/broken/</loc></url>
<url><loc>https://example.com/</loc></url></urlset>"""


def inspection(verdict, coverage, last_crawl="2026-10-01T00:00:00Z", gc="", uc="", indexing="INDEXING_ALLOWED"):
    return {"inspectionResult": {"indexStatusResult": {
        "verdict": verdict, "coverageState": coverage, "indexingState": indexing, "robotsTxtState": "ALLOWED",
        "pageFetchState": "SUCCESSFUL" if last_crawl else "PAGE_FETCH_STATE_UNSPECIFIED",
        "lastCrawlTime": last_crawl, "googleCanonical": gc, "userCanonical": uc}}}


class FakeHttp:
    """Routes (method, url) to queued (status, body) replies; records every call."""

    def __init__(self):
        self.routes, self.calls = {}, []

    def on(self, method, url, *replies):
        self.routes.setdefault((method, url), []).extend(replies)

    def __call__(self, method, url, data, headers, timeout=60):
        self.calls.append({"method": method, "url": url, "data": data, "headers": headers})
        key = (method, url.split("?")[0])
        queue = self.routes.get(key)
        if not queue:
            raise AssertionError("unexpected call %s %s" % key)
        status, body = queue.pop(0) if len(queue) > 1 else queue[0]
        return status, json.dumps(body).encode() if not isinstance(body, bytes) else body


class Base(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ENV_VARS}
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        secret_file = tmp / "client.json"
        secret_file.write_text(json.dumps({"installed": {"client_id": "cid.apps.googleusercontent.com",
                                                         "client_secret": CLIENT_SECRET}}), encoding="utf-8")
        os.environ["UNTAPPED_GOOGLE_CLIENT_SECRET"] = str(secret_file)
        os.environ.pop("UNTAPPED_GOOGLE_CLIENT_JSON", None)
        os.environ["UNTAPPED_GOOGLE_HOME"] = str(tmp / "google")
        os.environ["UNTAPPED_INDEX_HOME"] = str(tmp / "index")
        self.http = FakeHttp()
        self.clock_value = 1_000_000.0
        self.opened = []
        self.auth = ga.GoogleAuth(http=self.http, browser=self.opened.append, clock=lambda: self.clock_value)

    def tearDown(self):
        if getattr(self, "server", None) and self.server._store:
            self.server._store.db.close()
        self.tmp.cleanup()
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def signed_in(self, expires_in=3600):
        self.auth.save_token({"refresh_token": REFRESH, "access_token": ACCESS,
                              "expires_at": self.clock_value + expires_in, "scope": ga.SCOPE})

    def make_server(self, sitemap_bodies=None):
        bodies = dict(sitemap_bodies or {"https://example.com/sitemap.xml": SITEMAP_INDEX,
                                         "https://example.com/pages.xml": PAGES})
        self.fetched = []

        def fetch(url):
            self.fetched.append(url)
            return bodies[url]

        self.server = ix.Server(auth=self.auth, fetch=fetch, clock=lambda: self.now)
        self.now = NOW
        return self.server


class AuthTests(Base):
    def test_login_round_trip_over_real_loopback(self):
        self.http.on("POST", ga.TOKEN_URL, (200, {"access_token": ACCESS, "refresh_token": REFRESH,
                                                  "expires_in": 3599, "scope": ga.SCOPE}))
        started = self.auth.start_login()
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(started["auth_url"]).query)
        self.assertEqual(self.opened, [started["auth_url"]])
        self.assertEqual(params["scope"], [ga.SCOPE])
        self.assertEqual(params["code_challenge_method"], ["S256"])
        redirect = params["redirect_uri"][0]
        self.assertTrue(redirect.startswith("http://127.0.0.1:"))
        # A forged callback with the wrong state is refused and the login stays pending.
        with urllib.request.urlopen(redirect + "?code=evil&state=wrong", timeout=10) as r:
            self.assertIn(b"state mismatch", r.read())
        self.assertEqual(self.auth.login_state(), "pending")
        with urllib.request.urlopen(redirect + "?code=good&state=" + params["state"][0], timeout=10) as r:
            self.assertIn(b"Signed in", r.read())
        self.assertEqual(self.auth.login_state(), "signed_in")
        sent = urllib.parse.parse_qs(self.http.calls[0]["data"].decode())
        self.assertEqual(sent["code"], ["good"])
        self.assertEqual(len(sent["code_verifier"][0]) >= 43, True)
        self.assertTrue(self.auth.status()["signed_in"])

    def test_refresh_when_expired_and_invalid_grant_signs_out(self):
        self.signed_in(expires_in=10)
        self.http.on("POST", ga.TOKEN_URL, (200, {"access_token": "ya29.new-token-1234", "expires_in": 3600}))
        self.assertEqual(self.auth.access_token(), "ya29.new-token-1234")
        self.clock_value += 7200
        self.http.routes[("POST", ga.TOKEN_URL)] = [(400, {"error": "invalid_grant"})]
        with self.assertRaisesRegex(ToolError, "google_login"):
            self.auth.access_token()
        self.assertFalse(self.auth.token_path.exists())

    def test_claude_setting_path_wins_and_unresolved_placeholder_is_unset(self):
        os.environ["UNTAPPED_GOOGLE_CLIENT_JSON"] = "${user_config.google_client_json}"
        self.assertEqual(self.auth.client()[1], CLIENT_SECRET)  # falls back to UNTAPPED_GOOGLE_CLIENT_SECRET
        other = Path(os.environ["UNTAPPED_GOOGLE_CLIENT_SECRET"]).with_name("from_settings.json")
        other.write_text(json.dumps({"installed": {"client_id": "cid-2", "client_secret": "s2"}}), encoding="utf-8")
        os.environ["UNTAPPED_GOOGLE_CLIENT_JSON"] = str(other)
        self.assertEqual(self.auth.client(), ("cid-2", "s2"))

    def test_web_client_type_refused(self):
        Path(os.environ["UNTAPPED_GOOGLE_CLIENT_SECRET"]).write_text('{"web": {"client_id": "x"}}', encoding="utf-8")
        with self.assertRaisesRegex(ToolError, "Desktop app"):
            self.auth.start_login()

    def test_api_host_pinned(self):
        self.signed_in()
        with self.assertRaisesRegex(ToolError, "Refused"):
            self.auth.api("GET", "https://evil.example.com/steal")
        self.assertEqual(self.http.calls, [])

    def test_bare_domain_resolves_to_owned_property(self):
        self.signed_in()
        self.http.on("GET", "https://www.googleapis.com/webmasters/v3/sites", (200, {"siteEntry": [
            {"siteUrl": "sc-domain:other.com", "permissionLevel": "siteOwner"},
            {"siteUrl": "sc-domain:example.com", "permissionLevel": "siteFullUser"}]}))
        self.assertEqual(ga.resolve_property(self.auth, "www.Example.com"), "sc-domain:example.com")
        with self.assertRaisesRegex(ToolError, "No verified"):
            ga.resolve_property(self.auth, "nope.com")


class IndexCheckTests(Base):
    def queue_inspections(self, *results):
        self.http.routes[("POST", ix.INSPECT_URL)] = list(results)

    def test_first_run_flags_advice_and_unknown(self):
        self.signed_in()
        srv = self.make_server()
        self.queue_inspections(
            (200, inspection("PASS", "Submitted and indexed", gc="https://example.com/", uc="https://example.com/")),
            (200, inspection("NEUTRAL", "Discovered - currently not indexed", last_crawl="")),
            (500, {"error": {"code": 500, "message": "Internal error encountered."}}))
        out = srv.call("index_check", {"site": "sc-domain:example.com"})
        self.assertEqual(self.fetched, ["https://example.com/sitemap.xml", "https://example.com/pages.xml"])
        self.assertEqual(out["urls_found"], 3)  # duplicate + image:loc ignored
        self.assertEqual(out["summary"]["indexed"], 1)
        self.assertEqual(out["summary"]["not_indexed"], 1)
        self.assertEqual(out["summary"]["unknown"], 1)
        items = {i["url"]: i for i in out["needs_attention"]}
        self.assertEqual(items["https://example.com/new/"]["flags"], ["not indexed: Discovered - currently not indexed"])
        self.assertIn("Link to it", items["https://example.com/new/"]["do"])
        self.assertTrue(items["https://example.com/broken/"]["flags"][0].startswith("UNKNOWN"))
        sent = json.loads(self.http.calls[0]["data"])
        self.assertEqual(sent, {"inspectionUrl": "https://example.com/", "siteUrl": "sc-domain:example.com",
                                "languageCode": "en-US"})

    def test_second_run_reports_dropped_canonical_and_stale(self):
        self.signed_in()
        srv = self.make_server()
        self.queue_inspections((200, inspection("PASS", "Submitted and indexed")),
                               (200, inspection("PASS", "Submitted and indexed")),
                               (200, inspection("PASS", "Submitted and indexed")))
        srv.call("index_check", {"site": "sc-domain:example.com"})
        self.now = NOW + dt.timedelta(days=60)
        self.queue_inspections((200, inspection("NEUTRAL", "Crawled - currently not indexed")),
                               (200, inspection("PASS", "Submitted and indexed", gc="https://example.com/other/",
                                                uc="https://example.com/new/")),
                               (500, {"error": {"message": "backend"}}))
        out = srv.call("index_check", {"site": "sc-domain:example.com"})
        self.assertEqual(out["newly_dropped"], ["https://example.com/"])
        items = {i["url"]: i for i in out["needs_attention"]}
        self.assertTrue(items["https://example.com/"]["flags"][0].startswith("DROPPED OUT"))
        self.assertIn("quality or duplicate", items["https://example.com/"]["do"])
        self.assertTrue(any("different canonical" in f for f in items["https://example.com/new/"]["flags"]))
        self.assertTrue(any("not crawled for" in f for f in items["https://example.com/new/"]["flags"]))
        self.assertNotIn("https://example.com/broken/", out["newly_dropped"])  # UNKNOWN never counts as dropped
        runs = srv.call("index_history", {"site": "sc-domain:example.com"})["runs"]
        self.assertEqual([(r["indexed"], r["unknown"]) for r in runs], [(1, 1), (3, 0)])

    def test_quota_stops_early_and_max_urls_truncates(self):
        self.signed_in()
        srv = self.make_server()
        self.queue_inspections((429, {"error": {"code": 429, "message": "Quota exceeded", "status": "RESOURCE_EXHAUSTED"}}))
        out = srv.call("index_check", {"site": "sc-domain:example.com", "max_urls": 2})
        self.assertEqual(out["checked"], 1)
        self.assertIn("quota", out["stopped"])
        self.assertIn("1 more URLs", out["truncated"])
        self.assertEqual(out["not_checked"], 2)

    def test_signed_out_is_a_plain_error(self):
        srv = self.make_server()
        with self.assertRaisesRegex(ToolError, "google_login"):
            srv.call("index_check", {"site": "sc-domain:example.com"})

    def test_secrets_never_leak(self):
        self.signed_in(expires_in=10)  # forces a refresh, whose error echoes secrets
        self.http.on("POST", ga.TOKEN_URL, (400, {"error": {"message": "bad %s %s %s" % (CLIENT_SECRET, REFRESH, ACCESS)}}))
        srv = self.make_server()
        out, msgs = io.StringIO(), [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "index_check",
                                                                            "arguments": {"site": "sc-domain:example.com"}}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "google_login_status", "arguments": {}}}]
        serve(ix.TOOLS, srv.call, sanitize=ga.Redactor(self.auth), output_stream=out,
              input_stream=io.StringIO("".join(json.dumps(m) + "\n" for m in msgs)))
        text = out.getvalue()
        for secret in (CLIENT_SECRET, REFRESH, ACCESS, "SECRET"):
            self.assertNotIn(secret, text)
        self.assertIn("[REDACTED]", text)


class PackagingTests(unittest.TestCase):
    def test_subprocess_lists_tools(self):
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, UNTAPPED_GOOGLE_HOME=tmp, UNTAPPED_INDEX_HOME=tmp, PYTHONDONTWRITEBYTECODE="1")
            proc = subprocess.run([sys.executable, str(PLUGIN / "server" / "index_server.py")], env=env, timeout=30,
                                  input="".join(json.dumps(m) + "\n" for m in msgs), capture_output=True, text=True)
        tools = {t["name"] for t in json.loads(proc.stdout.splitlines()[1])["result"]["tools"]}
        self.assertEqual(tools, {"google_login", "google_login_status", "google_logout", "gsc_sites",
                                 "index_check", "index_history"})
        self.assertEqual(proc.stderr, "")

    def test_manifests_and_shared_copies_current(self):
        for tool in ("manifests.py", "sync_shared.py"):
            proc = subprocess.run([sys.executable, str(LANE / "tools" / tool), "--check"],
                                  capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertTrue((PLUGIN / "skills" / "index-watch" / "SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()
