"""Offline tests for untapped-search-console. Run: python -m unittest discover -s plugins/untapped-search-console/tests"""
import datetime as dt
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

import google_auth as ga  # noqa: E402
import gsc_server as gs  # noqa: E402
from mcp_stdio import ToolError  # noqa: E402

TODAY = dt.date(2026, 10, 9)
QUERY_URL = "https://www.googleapis.com/webmasters/v3/sites/sc-domain%3Aexample.com/searchAnalytics/query"


def row(keys, clicks, impressions, position):
    return {"keys": keys, "clicks": clicks, "impressions": impressions,
            "ctr": clicks / impressions if impressions else 0, "position": position}


class FakeGoogle:
    """Answers searchAnalytics queries from a function of the request body."""

    def __init__(self, answer):
        self.answer, self.bodies = answer, []

    def __call__(self, method, url, data, headers, timeout=60):
        assert method == "POST" and url == QUERY_URL, url
        assert headers["Authorization"] == "Bearer ya29.token-for-tests"
        body = json.loads(data)
        self.bodies.append(body)
        return 200, json.dumps({"rows": self.answer(body)}).encode()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = os.environ.get("UNTAPPED_GOOGLE_CLIENT_SECRET")
        client = Path(self.tmp.name) / "client.json"
        client.write_text(json.dumps({"installed": {"client_id": "cid", "client_secret": "csecret-123"}}),
                          encoding="utf-8")
        os.environ["UNTAPPED_GOOGLE_CLIENT_SECRET"] = str(client)

    def tearDown(self):
        self.tmp.cleanup()
        if self.saved is None:
            os.environ.pop("UNTAPPED_GOOGLE_CLIENT_SECRET", None)
        else:
            os.environ["UNTAPPED_GOOGLE_CLIENT_SECRET"] = self.saved

    def server(self, answer):
        self.google = FakeGoogle(answer)
        auth = ga.GoogleAuth(home=Path(self.tmp.name) / "google", http=self.google, browser=lambda u: False,
                             clock=lambda: 1000.0)
        auth.save_token({"refresh_token": "1//r-123456", "access_token": "ya29.token-for-tests",
                         "expires_at": 99999.0, "scope": ga.SCOPE})
        return gs.Server(auth=auth, today=TODAY)


class PerformanceTests(Base):
    def test_request_shape_rows_and_sums(self):
        srv = self.server(lambda b: [row(["gbp help", "https://example.com/a/"], 3, 100, 4.0),
                                     row(["gbp manager", "https://example.com/b/"], 1, 300, 8.0)])
        out = srv.call("gsc_performance", {"site": "sc-domain:example.com", "dimensions": ["query", "page"],
                                           "page_contains": "/a", "device": "MOBILE", "row_limit": 50})
        body = self.google.bodies[0]
        self.assertEqual((body["startDate"], body["endDate"]), ("2026-09-09", "2026-10-06"))  # 28 days, 3-day lag
        self.assertEqual(body["dimensions"], ["query", "page"])
        self.assertEqual(body["rowLimit"], 50)
        self.assertEqual(body["dimensionFilterGroups"][0]["filters"],
                         [{"dimension": "page", "operator": "contains", "expression": "/a"},
                          {"dimension": "device", "operator": "equals", "expression": "MOBILE"}])
        self.assertEqual(out["rows"][0], {"query": "gbp help", "page": "https://example.com/a/", "clicks": 3,
                                          "impressions": 100, "ctr_pct": 3.0, "position": 4.0})
        self.assertEqual(out["returned_rows_sum"], {"clicks": 4, "impressions": 400, "ctr_pct": 1.0,
                                                    "position_weighted": 7.0})
        self.assertIn("not final", out["note"])

    def test_validation(self):
        srv = self.server(lambda b: [])
        for bad in ({"dimensions": ["keyword"]}, {"days": 0}, {"row_limit": 9999}, {"country": "us"},
                    {"device": "phone"}, {"search_type": "maps"}):
            with self.assertRaises(ToolError, msg=str(bad)):
                srv.call("gsc_performance", dict(site="sc-domain:example.com", **bad))
        self.assertEqual(self.google.bodies, [])

    def test_totals_measured_zero(self):
        srv = self.server(lambda b: [])
        out = srv.call("gsc_totals", {"site": "sc-domain:example.com", "days": 90})
        self.assertTrue(out["measured_zero"])
        self.assertEqual(out["days"], 90)
        self.assertNotIn("dimensions", self.google.bodies[0])


class WorkingAndCompareTests(Base):
    def test_whats_working_groups(self):
        srv = self.server(lambda b: [row(["earns"], 2, 50, 6.0), row(["top no click"], 0, 40, 2.1),
                                     row(["close a"], 0, 30, 11.0), row(["close b"], 0, 20, 5.0),
                                     row(["far"], 0, 60, 35.0), row(["rare"], 0, 2, 9.0)])
        out = srv.call("gsc_whats_working", {"site": "sc-domain:example.com"})
        self.assertEqual([r["query"] for r in out["earning"]], ["earns"])
        self.assertEqual([r["query"] for r in out["top3_no_clicks"]], ["top no click"])
        self.assertEqual([r["query"] for r in out["close"]], ["close b", "close a"])  # nearest page one first
        self.assertEqual([r["query"] for r in out["invisible"]], ["far"])
        self.assertEqual(out["below_min_impressions"], 1)
        self.assertEqual(self.google.bodies[0]["rowLimit"], 1000)

    def test_compare_windows_and_movers(self):
        def answer(b):
            current = b["startDate"] == "2026-09-09"
            if "dimensions" not in b:
                return [row([], 10 if current else 4, 900 if current else 500, 12.0)]
            if current:
                return [row(["up"], 3, 300, 7.0), row(["down"], 0, 10, 30.0), row(["fresh"], 1, 80, 9.0)]
            return [row(["up"], 1, 100, 12.0), row(["down"], 0, 90, 18.0), row(["gone"], 0, 70, 15.0)]
        srv = self.server(answer)
        out = srv.call("gsc_compare", {"site": "sc-domain:example.com"})
        self.assertEqual((out["current"]["from"], out["current"]["to"]), ("2026-09-09", "2026-10-06"))
        self.assertEqual((out["previous"]["from"], out["previous"]["to"]), ("2026-08-12", "2026-09-08"))
        self.assertEqual((out["current"]["clicks"], out["previous"]["clicks"]), (10, 4))
        self.assertEqual([c["query"] for c in out["gainers"]], ["up"])
        self.assertEqual(out["gainers"][0]["impressions_change"], 200)
        self.assertEqual([c["query"] for c in out["losers"]], ["down"])
        self.assertEqual([c["query"] for c in out["new"]], ["fresh"])
        self.assertEqual([c["query"] for c in out["lost"]], ["gone"])


class PackagingTests(unittest.TestCase):
    def test_subprocess_lists_tools(self):
        msgs = [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}]
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, UNTAPPED_GOOGLE_HOME=tmp, PYTHONDONTWRITEBYTECODE="1")
            proc = subprocess.run([sys.executable, str(PLUGIN / "server" / "gsc_server.py")], env=env, timeout=30,
                                  input=json.dumps(msgs[0]) + "\n", capture_output=True, text=True)
        tools = {t["name"] for t in json.loads(proc.stdout)["result"]["tools"]}
        self.assertEqual(tools, {"google_login", "google_login_status", "google_logout", "gsc_sites",
                                 "gsc_performance", "gsc_totals", "gsc_whats_working", "gsc_compare"})
        self.assertEqual(proc.stderr, "")

    def test_manifests_and_shared_copies_current(self):
        for tool in ("manifests.py", "sync_shared.py"):
            proc = subprocess.run([sys.executable, str(LANE / "tools" / tool), "--check"],
                                  capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
