"""Offline tests for untapped-serp. Run: python -m unittest discover -s plugins/untapped-serp/tests"""
import io
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
FIX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(PLUGIN / "server"))

import dataforseo as dfs  # noqa: E402
import serp_server  # noqa: E402
from ledger import Ledger  # noqa: E402
from mcp_stdio import ToolError, serve  # noqa: E402

LOGIN, PASSWORD = "login-SECRET-7781@example.com", "pw-SECRET-9931"
CRED_VARS = ("DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD", "UNTAPPED_DATAFORSEO_LOGIN", "UNTAPPED_DATAFORSEO_PASSWORD",
             "UNTAPPED_SERP_DAILY_CAP_USD", "UNTAPPED_SERP_SANDBOX")


def fixture(name):
    return (FIX / name).read_bytes()


class FakeTransport:
    """Records every call; returns queued bytes or raises queued exceptions."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, url, payload, headers, timeout):
        self.calls.append({"url": url, "payload": json.loads(payload), "headers": headers, "timeout": timeout})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class Base(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in CRED_VARS}
        os.environ["DATAFORSEO_LOGIN"], os.environ["DATAFORSEO_PASSWORD"] = LOGIN, PASSWORD
        for k in ("UNTAPPED_DATAFORSEO_LOGIN", "UNTAPPED_DATAFORSEO_PASSWORD", "UNTAPPED_SERP_DAILY_CAP_USD",
                  "UNTAPPED_SERP_SANDBOX"):
            os.environ.pop(k, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(self.tmp.name)

    def tearDown(self):
        self.ledger.db.close()
        self.tmp.cleanup()
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def server(self, *replies, sandbox=False):
        transport = FakeTransport(*replies)
        return serp_server.Server(self.ledger, dfs.Client(sandbox=sandbox, transport=transport)), transport


class SerpTests(Base):
    def test_slim_serp_features_and_target(self):
        srv, t = self.server(fixture("serp_organic.json"))
        out = srv.call("google_serp", {"keyword": "nail salon near me", "location_name": "Palm Coast,Florida,United States",
                                       "target_domain": "NYNailsSpaBunnel.com"})
        self.assertEqual(len(t.calls), 1)
        self.assertEqual([o["domain"] for o in out["organic"]], ["www.example.com", "book.nynailsspabunnel.com"])
        self.assertEqual(out["people_also_ask"], ["How much is a manicure in Palm Coast?", "Do nail salons take walk-ins?"])
        self.assertEqual(out["local_pack"][0]["rating"], {"value": 4.8, "votes_count": 120, "rating_max": 5})
        self.assertTrue(out["ai_overview"]["present"])
        self.assertEqual(out["ai_overview"]["cited_domains"], ["nynailsspabunnel.com", "www.yelp.com"])
        self.assertEqual(out["featured_snippet"], [{"domain": "wiki.example.org", "url": "https://wiki.example.org/manicure"}])
        kinds = sorted(h["type"] for h in out["target"])
        self.assertEqual(kinds, ["ai_overview_reference", "local_pack", "organic"])  # subdomain counts as the site
        self.assertEqual(out["cost_usd"], 0.002)
        self.assertNotIn("_positions", out)
        self.assertEqual(out["features"], ["ai_overview", "local_pack", "organic", "people_also_ask", "featured_snippet"])
        self.assertEqual(out["check_url"][:29], "https://www.google.com/search")

    def test_target_not_found(self):
        srv, _ = self.server(fixture("serp_organic.json"))
        out = srv.call("google_serp", {"keyword": "nail salon near me", "target_domain": "nowhere.com"})
        self.assertEqual(out["target"], "not in top 10")

    def test_request_sent_is_pinned_and_minimal(self):
        srv, t = self.server(fixture("serp_organic.json"))
        srv.call("google_serp", {"keyword": "  nail salon near me ", "device": "mobile", "depth": 20, "target_domain": "x.com"})
        call = t.calls[0]
        self.assertEqual(call["url"], "https://api.dataforseo.com/v3/serp/google/organic/live/advanced")
        self.assertEqual(call["payload"], [{"keyword": "nail salon near me", "device": "mobile", "depth": 20,
                                            "language_code": "en", "location_name": "United States"}])
        self.assertEqual(call["timeout"], 60)

    def test_sandbox_host_and_label(self):
        os.environ["UNTAPPED_SERP_SANDBOX"] = "1"
        srv, t = self.server(fixture("serp_organic.json"), sandbox=True)
        out = srv.call("google_serp", {"keyword": "nail salon near me"})
        self.assertTrue(t.calls[0]["url"].startswith("https://sandbox.dataforseo.com/v3/"))
        self.assertTrue(out["sandbox"])

    def test_unpinned_endpoint_refused(self):
        client = dfs.Client(transport=FakeTransport())
        with self.assertRaises(ToolError):
            client.post("/v3/anything/else", {})
        self.assertEqual(client.transport.calls, [])


class CacheAndMoneyTests(Base):
    def test_cache_hit_costs_nothing_and_skips_network(self):
        srv, t = self.server(fixture("serp_organic.json"))
        args = {"keyword": "nail salon near me", "target_domain": "example.com"}
        first = srv.call("google_serp", args)
        second = srv.call("google_serp", dict(args, target_domain="nynailsspabunnel.com"))
        self.assertEqual(len(t.calls), 1)
        self.assertFalse(first["cached"]["hit"])
        self.assertTrue(second["cached"]["hit"])
        self.assertEqual(second["cost_usd"], 0.0)
        self.assertEqual(len(second["target"]), 3)  # target applied fresh on the cached copy
        self.assertEqual(second["spend_today_usd"], 0.002)

    def test_max_age_zero_forces_fresh_call(self):
        srv, t = self.server(fixture("serp_organic.json"), fixture("serp_organic.json"))
        srv.call("google_serp", {"keyword": "nail salon near me"})
        srv.call("google_serp", {"keyword": "nail salon near me", "max_age_hours": 0})
        self.assertEqual(len(t.calls), 2)

    def test_cap_refusal_never_calls_network(self):
        os.environ["UNTAPPED_SERP_DAILY_CAP_USD"] = "0.001"
        srv, t = self.server(fixture("serp_organic.json"))
        with self.assertRaisesRegex(ToolError, "Daily cap reached"):
            srv.call("google_serp", {"keyword": "nail salon near me"})
        self.assertEqual(t.calls, [])
        self.assertEqual(srv.call("serp_spend", {})["last_calls"][0]["status"], "REFUSED")

    def test_uncertain_outcome_holds_reserve(self):
        os.environ["UNTAPPED_SERP_DAILY_CAP_USD"] = "0.003"
        srv, t = self.server(TimeoutError("read timed out"), fixture("serp_organic.json"))
        with self.assertRaisesRegex(ToolError, "UNCERTAIN"):
            srv.call("google_serp", {"keyword": "a"})
        self.assertEqual(len(t.calls), 1)  # no automatic retry
        with self.assertRaisesRegex(ToolError, "Daily cap reached"):
            srv.call("google_serp", {"keyword": "b"})  # 0.002 held + 0.002 > 0.003
        self.assertEqual(srv.call("serp_spend", {})["held_uncertain_today_usd"], 0.002)

    def test_status_error_still_records_cost(self):
        body = json.loads(fixture("serp_organic.json"))
        body["tasks"][0].update(status_code=40501, status_message="Invalid Field: 'location_name'.", result=None)
        srv, _ = self.server(json.dumps(body).encode())
        with self.assertRaisesRegex(ToolError, "40501"):
            srv.call("google_serp", {"keyword": "x", "location_name": "Nowhere"})
        self.assertEqual(srv.call("serp_spend", {})["charged_today_usd"], 0.002)

    def test_no_results_is_empty_not_error(self):
        body = json.loads(fixture("serp_organic.json"))
        body["tasks"][0].update(status_code=40102, status_message="No Search Results.", result=None)
        srv, _ = self.server(json.dumps(body).encode())
        out = srv.call("google_serp", {"keyword": "zzqx", "target_domain": "a.com"})
        self.assertEqual(out["organic"], [])
        self.assertEqual(out["target"], "not in top 10")

    def test_missing_credentials_hold_nothing(self):
        os.environ.pop("DATAFORSEO_LOGIN")
        srv, t = self.server()
        with self.assertRaisesRegex(ToolError, "DataForSEO API login and password"):
            srv.call("google_serp", {"keyword": "x"})
        spend = srv.call("serp_spend", {})
        self.assertEqual((spend["held_uncertain_today_usd"], spend["last_calls"]), (0.0, []))
        self.assertEqual(spend["credentials_set"], {"login": False, "password": True})

    def test_claude_settings_win_whole_and_unresolved_placeholders_are_unset(self):
        # Claude Code passes the plugin settings as UNTAPPED_DATAFORSEO_*; an unset option may arrive literally.
        os.environ["UNTAPPED_DATAFORSEO_LOGIN"] = "${user_config.dataforseo_login}"
        os.environ["UNTAPPED_DATAFORSEO_PASSWORD"] = "${user_config.dataforseo_password}"
        os.environ["UNTAPPED_SERP_DAILY_CAP_USD"] = "${user_config.daily_cap_usd}"
        self.assertEqual(serp_server.dfs.credentials(), (LOGIN, PASSWORD))
        self.assertEqual(serp_server.cap_units(), serp_server.dfs.units(serp_server.DEFAULT_CAP_USD))
        os.environ["UNTAPPED_DATAFORSEO_LOGIN"] = "settings-login"
        os.environ["UNTAPPED_DATAFORSEO_PASSWORD"] = ""
        self.assertEqual(serp_server.dfs.credentials(), ("settings-login", ""))  # never mixed with DATAFORSEO_*

    def test_dry_run_and_estimate_are_free(self):
        srv, t = self.server()
        dry = srv.call("google_serp", {"keyword": "x", "depth": 30, "dry_run": True})
        self.assertEqual(dry["reserve_usd"], 0.006)
        est = srv.call("serp_estimate", {"tool": "google_serp", "arguments": {"keyword": "site:example.com plumber"}})
        self.assertEqual(est["reserve_usd"], 0.01)  # operator multiplier
        self.assertTrue(est["cap_allows"])
        self.assertEqual(t.calls, [])

    def test_volume_nulls_stay_null(self):
        srv, t = self.server(fixture("volume.json"))
        out = srv.call("google_search_volume", {"keywords": ["Nail salon Palm Coast", "gel x palm coast fl",
                                                             "nail salon palm coast "]})
        self.assertEqual(t.calls[0]["payload"][0]["keywords"], ["gel x palm coast fl", "nail salon palm coast"])
        rows = {r["keyword"]: r for r in out["keywords"]}
        self.assertIsNone(rows["gel x palm coast fl"]["search_volume"])
        self.assertEqual(rows["gel x palm coast fl"]["status"], "no data")
        self.assertEqual(rows["nail salon palm coast"]["monthly_searches"][0], {"year": 2026, "month": 9, "search_volume": 590})
        self.assertIn("never zero", out["caveat"])
        self.assertEqual(out["cost_usd"], 0.09)

    def test_volume_batch_guard(self):
        srv, _ = self.server()
        with self.assertRaisesRegex(ToolError, "allow_large_batch"):
            srv.call("google_search_volume", {"keywords": ["k%d" % i for i in range(101)]})


class SecretTests(Base):
    def run_rpc(self, srv, messages):
        out = io.StringIO()
        src = io.StringIO("".join(json.dumps(m) + "\n" for m in messages))
        serve(serp_server.TOOLS, srv.call, sanitize=dfs.Redactor(), input_stream=src, output_stream=out)
        return out.getvalue()

    def test_secrets_never_leak_from_any_error_path(self):
        auth = dfs.base64.b64encode((LOGIN + ":" + PASSWORD).encode()).decode()
        leaky = json.loads(fixture("serp_organic.json"))
        leaky["tasks"][0].update(status_code=40100, status_message="bad auth for %s / %s / %s" % (LOGIN, PASSWORD, auth))
        srv, _ = self.server(RuntimeError("Authorization: Basic " + auth + " " + PASSWORD),
                             json.dumps(leaky).encode(), b"not json " + PASSWORD.encode())
        calls = [{"jsonrpc": "2.0", "id": i, "method": "tools/call",
                  "params": {"name": "google_serp", "arguments": {"keyword": "q%d" % i, "max_age_hours": 0}}}
                 for i in range(3)]
        calls.append({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "serp_spend", "arguments": {}}})
        text = self.run_rpc(srv, calls)
        for secret in (LOGIN, PASSWORD, auth, "SECRET"):
            self.assertNotIn(secret, text)
        self.assertEqual(text.count('"isError":true'), 3)

    def test_subprocess_handshake_and_stderr_clean(self):
        env = dict(os.environ, UNTAPPED_SERP_HOME=self.tmp.name, PYTHONDONTWRITEBYTECODE="1")
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                 "params": {"name": "google_serp", "arguments": {"keyword": "x", "dry_run": True}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "serp_spend", "arguments": {}}}]
        proc = subprocess.run([sys.executable, str(PLUGIN / "server" / "serp_server.py")], env=env, timeout=30,
                              input="".join(json.dumps(m) + "\n" for m in msgs), capture_output=True, text=True)
        replies = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertEqual([r["id"] for r in replies], [1, 2, 3, 4])
        self.assertEqual(replies[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual({t["name"] for t in replies[1]["result"]["tools"]},
                         {"google_serp", "google_search_volume", "serp_spend", "serp_estimate"})
        self.assertFalse(replies[2]["result"]["isError"])
        self.assertEqual(replies[2]["result"]["structuredContent"]["reserve_usd"], 0.002)
        self.assertNotIn(PASSWORD, proc.stdout + proc.stderr)
        self.assertFalse((PLUGIN / "server" / "__pycache__").exists() and
                         any((PLUGIN / "server" / "__pycache__").glob("serp_server*")))

    def test_non_latin_text_survives_a_legacy_console_codec(self):
        env = dict(os.environ, UNTAPPED_SERP_HOME=self.tmp.name, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="cp1252")
        msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "google_serp", "arguments": {"keyword": "ネイル・サロン café", "dry_run": True}}}
        proc = subprocess.run([sys.executable, str(PLUGIN / "server" / "serp_server.py")], env=env, timeout=30,
                              input=(json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8"), capture_output=True)
        reply = json.loads(proc.stdout.decode("utf-8"))
        self.assertEqual(reply["result"]["structuredContent"]["request"]["keyword"], "ネイル・サロン café")
        self.assertEqual(proc.stderr, b"")


class PackagingTests(unittest.TestCase):
    def test_manifests_parse_and_paths_exist(self):
        codex = json.loads((PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        for key in ("skills", "mcpServers"):
            self.assertTrue((PLUGIN / codex[key]).exists(), key)
        for key in ("composerIcon", "logo"):
            self.assertTrue((PLUGIN / codex["interface"][key]).exists(), key)
        mcp = json.loads((PLUGIN / ".codex-mcp.json").read_text(encoding="utf-8"))["mcpServers"]["untapped-serp"]
        self.assertTrue((PLUGIN / mcp["args"][0]).exists())
        self.assertIn("DATAFORSEO_PASSWORD", mcp["env_vars"])
        claude = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(claude["name"], codex["name"])
        self.assertEqual(claude["version"], codex["version"])
        self.assertTrue((PLUGIN / "skills" / "google-serp" / "SKILL.md").exists())
        for market in (LANE / ".agents" / "plugins" / "marketplace.json", LANE / ".claude-plugin" / "marketplace.json"):
            data = json.loads(market.read_text(encoding="utf-8"))
            self.assertIn("untapped-serp", [p["name"] for p in data["plugins"]])

    def test_shared_copies_current(self):
        proc = subprocess.run([sys.executable, str(LANE / "tools" / "sync_shared.py"), "--check"],
                              capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
