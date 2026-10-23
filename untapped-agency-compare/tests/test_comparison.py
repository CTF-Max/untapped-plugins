"""Offline tests for extraction, fair comparison, and the MCP stdio surface."""
from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest
from unittest import mock


PLUGIN = Path(__file__).resolve().parents[1]
ROOT = PLUGIN.parent  # the plugins folder in the studio; the repo root in the public export
SERVER = PLUGIN / "server"
FIXTURES = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(SERVER))

import agency_server  # noqa: E402
import compare as comparison  # noqa: E402
from extract import extract_offer, plain_text  # noqa: E402


CRITERIA = agency_server.criteria()["criteria"]
CRITERION_IDS = [item["id"] for item in CRITERIA]
URLS = {
    "agency_paragraphs.html": "https://cedar.example.invalid/about",
    "agency_list.html": "https://harborlight.example.invalid/services",
    "agency_table.html": "https://maplebridge.example.invalid/terms",
    "agency_sparse.html": "https://quietcurrent.example.invalid/",
}
READ_DATE = "2026-10-22"


_USE_FIXTURE_URL = object()


def load_extract(filename, source_url=_USE_FIXTURE_URL):
    raw = (FIXTURES / filename).read_text(encoding="utf-8")
    return extract_offer(raw, URLS[filename] if source_url is _USE_FIXTURE_URL else source_url, READ_DATE)


def stated_text_fact(quote, criterion="services", url="https://example.invalid/offer"):
    return {"status": "stated", "candidates": [{
        "quote": quote, "source_url": url, "date_read": READ_DATE,
    }]}


class ExtractionTests(unittest.TestCase):
    def test_three_page_shapes_extract_quoted_facts_for_each_criterion(self):
        results = {name: load_extract(name) for name in (
            "agency_paragraphs.html", "agency_list.html", "agency_table.html")}
        all_facts = {}
        for result in results.values():
            for criterion, fact in result["facts"].items():
                self.assertTrue(fact["candidates"], (result["source_url"], criterion))
                all_facts.setdefault(criterion, []).extend(fact["candidates"])

        self.assertEqual(set(CRITERION_IDS), set(all_facts))
        for criterion in CRITERION_IDS:
            self.assertTrue(all_facts[criterion], criterion)
            for candidate in all_facts[criterion]:
                rendered_text = plain_text("\n".join(
                    (FIXTURES / name).read_text(encoding="utf-8")
                    for name in ("agency_paragraphs.html", "agency_list.html", "agency_table.html")))
                self.assertIn(candidate["quote"], rendered_text)
                self.assertEqual(candidate["date_read"], READ_DATE)
                self.assertTrue(candidate["source_url"].startswith("https://"))

    def test_review_output_is_numeric_and_never_carries_review_prose(self):
        result = load_extract("agency_paragraphs.html")
        reviews = result["facts"]["reviews"]["candidates"]
        self.assertEqual(len(reviews), 1)
        self.assertEqual((reviews[0]["rating"], reviews[0]["count"]), (4.7, 128))
        self.assertEqual(reviews[0]["quote"], "4.7 out of 5 from 128 reviews")
        serialized = json.dumps(reviews)
        self.assertNotIn("doubled our sales", serialized)

    def test_sparse_page_and_page_without_source_have_only_not_stated(self):
        sparse = load_extract("agency_sparse.html")
        self.assertTrue(all(f["status"] == "not stated" and not f["candidates"]
                            for f in sparse["facts"].values()))
        no_source = load_extract("agency_paragraphs.html", source_url=None)
        self.assertTrue(all(f["status"] == "not stated" and not f["candidates"]
                            for f in no_source["facts"].values()))

    def test_headings_questions_and_review_prose_are_not_offer_evidence(self):
        text = "Services\nPricing:\nWho owns my domain?\nCustomer reviews\nThey guarantee amazing services for $10."
        result = extract_offer(text, "https://example.invalid/", READ_DATE)
        self.assertTrue(all(f["status"] == "not stated" for f in result["facts"].values()))

    def test_negation_and_qualifications_survive_unchanged(self):
        quote = "We do not guarantee a refund unless cancellation occurs within 30 days."
        result = extract_offer(quote, "https://example.invalid/", READ_DATE)
        for key in ("guarantees", "cancellation"):
            self.assertEqual(result["facts"][key]["candidates"][0]["quote"], quote)


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.futg = json.loads((PLUGIN / "data" / "futg_facts.json").read_text(encoding="utf-8"))

    def build(self, agencies, priorities=None):
        return comparison.compare(agencies, CRITERIA, [self.futg], priorities)

    def test_futg_checked_in_record_is_always_included_and_authoritative(self):
        spoof = {"name": self.futg["name"], "facts": {"services": stated_text_fact(
            "Spoofed evidence", url="https://attacker.example.invalid/")}}
        result = self.build([spoof, {"name": "Alpha Agency", "facts": {}}])
        self.assertIn("Find Untapped Growth", result["columns"])
        self.assertEqual(result["columns"], sorted(result["columns"], key=str.casefold))
        futg_services = next(row for row in result["rows"] if row["criterion"] == "services")["cells"][self.futg["name"]]
        self.assertEqual(futg_services["status"], self.futg["facts"]["services"]["status"])
        self.assertEqual([c["quote"] for c in futg_services["candidates"]],
                         [c["quote"] for c in self.futg["facts"]["services"]["candidates"]])
        self.assertNotIn("attacker", json.dumps(futg_services))

    def test_all_agencies_use_same_normalization_and_priorities_only_reorder_rows(self):
        agency = {"name": "Zeta", "facts": {"services": stated_text_fact("We provide services.")}}
        spy = mock.Mock(wraps=comparison.normalize_agency)
        with mock.patch.object(comparison, "normalize_agency", spy):
            default = self.build([agency])
            priority = self.build([agency], ["prices", "services"])
        calls = [call.args[0]["name"] for call in spy.call_args_list]
        self.assertIn("Find Untapped Growth", calls)
        self.assertIn("Zeta", calls)
        self.assertEqual(default["columns"], priority["columns"])
        self.assertEqual([r["criterion"] for r in priority["rows"][:2]], ["prices", "services"])
        self.assertEqual({r["criterion"] for r in default["rows"]}, {r["criterion"] for r in priority["rows"]})

    def test_every_stated_cell_has_source_and_date_and_missing_cells_have_questions(self):
        candidate = stated_text_fact("We provide services.")
        result = self.build([{"name": "Zeta", "facts": {"services": candidate}}])
        for row in result["rows"]:
            for name, fact in row["cells"].items():
                if fact["status"] == "stated":
                    for evidence in fact["candidates"]:
                        self.assertTrue(evidence["source_url"].startswith("https://"))
                        self.assertRegex(evidence["date_read"], r"^\d{4}-\d{2}-\d{2}$")
                        cell = comparison.cell_text(fact)
                        self.assertIn(evidence["source_url"], cell)
                        self.assertIn(evidence["date_read"], cell)
                else:
                    question_ids = {item["criterion"] for item in result["questions"][name]}
                    self.assertIn(row["criterion"], question_ids)
        for agency_name, questions in result["questions"].items():
            self.assertEqual(len(questions), sum(row["cells"][agency_name]["status"] == "not stated"
                                                  for row in result["rows"]))
        self.assertIn("Made by Find Untapped Growth", result["markdown"])
        self.assertIn("Made by Find Untapped Growth", result["html"])

    def test_priorities_reorder_rows_without_weights_or_winner(self):
        result = self.build([], ["guarantees", "prices"])
        self.assertEqual([row["criterion"] for row in result["rows"][:2]], ["guarantees", "prices"])
        self.assertNotIn("overall winner", result["markdown"].lower())
        self.assertNotIn("overall score:", result["markdown"].lower())

    def test_html_markdown_escape_and_csv_formula_defense(self):
        dangerous = "<script>alert(1)</script> | =2+2"
        agency = {"name": "=HYPERLINK(\"https://bad.invalid\")", "facts": {"services": stated_text_fact(dangerous)}}
        result = self.build([agency])
        self.assertNotIn("<script>alert(1)</script>", result["html"])
        self.assertIn("&lt;script&gt;", result["html"])
        self.assertIn("\\|", result["markdown"])
        rows = list(csv.reader(io.StringIO(result["csv"])))
        self.assertTrue(any(cell.startswith("'") and cell.lstrip("'").startswith("=")
                            for row in rows for cell in row))

    def test_invalid_comparison_inputs_are_rejected(self):
        for agencies, priorities in (({}, None), ([], ["unknown"]), ([{"name": " ", "facts": {}}], None),
                                     ([{"name": "bad", "facts": {"made_up": {}}}], None)):
            with self.subTest(agencies=agencies, priorities=priorities):
                with self.assertRaises((ValueError, TypeError)):
                    self.build(agencies, priorities)
        invalid_review = {"reviews": stated_text_fact("They were wonderful.", "reviews")}
        with self.assertRaises(ValueError):
            self.build([{"name": "Rival", "facts": invalid_review}])

    def test_compare_module_contains_no_maker_branch_outside_footer_constant(self):
        source = (SERVER / "compare.py").read_text(encoding="utf-8")
        for line in source.splitlines():
            lowered = line.lower()
            if "futg" in lowered or "find untapped growth" in lowered:
                self.assertRegex(line, r"^FOOTER\s*=")

    def test_unsourced_and_invalid_date_claims_rejected_equally(self):
        for name in ("Rival", self.futg["name"]):
            for changes in ({"source_url": ""}, {"source_url": "javascript:alert(1)"},
                            {"date_read": ""}, {"date_read": "2026-02-30"}, {"date_read": "2999-01-01"}):
                fact = stated_text_fact("Services: design.")
                fact["candidates"][0].update(changes)
                with self.subTest(name=name, changes=changes), self.assertRaises(ValueError):
                    self.build([{"name": name, "facts": {"services": fact}}])

    def test_checked_in_maker_claims_require_own_public_source_and_date(self):
        from urllib.parse import urlsplit
        from extract import read_date
        self.assertEqual(set(self.futg["facts"]), set(CRITERION_IDS))
        for fact in self.futg["facts"].values():
            for candidate in fact["candidates"]:
                self.assertEqual(urlsplit(candidate["source_url"]).hostname, "finduntappedgrowth.com")
                self.assertEqual(read_date(candidate["date_read"]), candidate["date_read"])

    def test_review_prose_cannot_leak_through_compare(self):
        fact = stated_text_fact('4.2/5, 31 reviews. "They guarantee sales for $10!"')
        result = self.build([{"name": "Rival", "facts": {"reviews": fact}}])
        for key in ("markdown", "csv", "html"):
            expected = comparison.md("4.2/5, 31 reviews") if key == "markdown" else "4.2/5, 31 reviews"
            self.assertIn(expected, result[key])
            self.assertNotIn("guarantee sales", result[key])

    def test_csv_and_html_have_same_columns_cells_and_footer_as_markdown(self):
        result = self.build([{"name": "Zeta", "facts": {}}, {"name": "Alpha", "facts": {}}])
        parsed = list(csv.reader(io.StringIO(result["csv"])))
        self.assertEqual(parsed[0][1:], result["columns"])
        for key in ("markdown", "csv", "html"):
            self.assertEqual(result[key].count("Made by Find Untapped Growth"), 1)
            self.assertIn("Sources and dates read", result[key])
        self.assertIn("<tfoot>", result["html"])
        self.assertNotRegex(result["html"], r"<(?:script|iframe)\b")


class MCPAndRepositoryChecks(unittest.TestCase):
    def test_stdio_subprocess_handshake_and_all_four_tools_round_trip(self):
        fixture = (FIXTURES / "agency_paragraphs.html").read_text(encoding="utf-8")
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "criteria", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "read_agency_page", "arguments": {"text": fixture, "source_url": URLS["agency_paragraphs.html"]}}},
        ]
        pasted_text = agency_server.read_agency_page(text=fixture, source_url=URLS["agency_paragraphs.html"])["page_text"]
        requests.extend([
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "extract_offer", "arguments": {"page_text": pasted_text, "source_url": URLS["agency_paragraphs.html"], "date_read": READ_DATE}}},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "compare", "arguments": {"agencies_json": [{"name": "Cedar Street Studio", "facts": load_extract("agency_paragraphs.html")["facts"]}], "priorities": ["services"]}}},
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "not_a_tool", "arguments": {}}},
        ])
        proc = subprocess.run([sys.executable, "-B", str(SERVER / "agency_server.py")],
                              input="".join(json.dumps(item) + "\n" for item in requests),
                              text=True, capture_output=True, cwd=PLUGIN, timeout=10,
                              env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        packets = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual([packet["id"] for packet in packets], list(range(1, 8)))
        self.assertEqual(packets[0]["result"]["serverInfo"]["name"], "untapped-agency-compare")
        self.assertEqual({tool["name"] for tool in packets[1]["result"]["tools"]},
                         {"read_agency_page", "extract_offer", "compare", "criteria"})
        for packet in packets[2:6]:
            self.assertFalse(packet["result"]["isError"], packet)
        self.assertTrue(packets[6]["result"]["isError"])
        self.assertIn("Unknown tool", packets[6]["result"]["structuredContent"]["error"])

    def test_sync_and_manifest_checks_when_present(self):
        targets = [
            (ROOT / "tools" / "sync_shared.py", ["--check"]),
            (ROOT / "tools" / "sync_agency_compare.py", ["--check"]),
            (ROOT / "tools" / "manifests.py", ["--check"]),
        ]
        for script, args in targets:
            with self.subTest(script=script):
                if not script.exists():
                    self.fail(f"Required check script is missing: {script.relative_to(ROOT)}")
                proc = subprocess.run([sys.executable, "-B", str(script), *args], cwd=ROOT,
                                      capture_output=True, text=True, timeout=30,
                                      env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
                self.assertEqual(proc.returncode, 0, f"{script}:\n{proc.stdout}\n{proc.stderr}")

    def test_forbidden_listing_word_absent_from_plugin_docs_and_registry(self):
        banned = "S" + "E" + "O"
        candidates = [path for path in PLUGIN.rglob("*") if path.is_file() and
                      (path.suffix.lower() in {".md", ".json"}) and
                      (path.suffix.lower() == ".md" or path.name == "plugin.json")]
        for path in candidates:
            self.assertNotRegex(path.read_text(encoding="utf-8"), re.compile(banned, re.I), str(path))
        marketplace = ROOT / ".claude-plugin" / "marketplace.json"
        if marketplace.exists():
            entry = next((item for item in json.loads(marketplace.read_text(encoding="utf-8")).get("plugins", [])
                          if item.get("name") == "untapped-agency-compare"), None)
            if entry is not None:
                self.assertNotRegex(json.dumps(entry), re.compile(banned, re.I), str(marketplace))
        for path in (ROOT / "registry").glob("*agency-compare*.json"):
            self.assertNotRegex(path.read_text(encoding="utf-8"), re.compile(banned, re.I), str(path))


if __name__ == "__main__":
    unittest.main()
