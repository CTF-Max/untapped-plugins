"""Offline acceptance and regression tests. All writable fixtures stay under this plugin."""
import copy
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import uuid
import unittest
import xml.etree.ElementTree as ET
import zipfile
import zlib
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
LANE = ROOT.parent
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT / "server"))
from evidence import scan_evidence, read_source_text
from job import read_job, _fetch
from docx_writer import render_resume
from pdf_writer import extract_pdf, write_pdf
from portfolio import render_portfolio
from ats import ats_check


class PluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = ROOT / ".test-tmp"
        cls.work.mkdir(exist_ok=True)
        cls.network = patch.object(socket, "create_connection", side_effect=AssertionError("Tests must remain offline"))
        cls.network.start()

    @classmethod
    def tearDownClass(cls):
        cls.network.stop()
        try:
            cls.work.rmdir()
        except OSError:
            pass

    def setUp(self):
        # Python 3.12 Windows mkdir(0700), used by TemporaryDirectory, excludes the
        # managed sandbox identity. Normal inherited permissions work on every host.
        self.tmp = self.work / uuid.uuid4().hex
        self.tmp.mkdir()
        self.addCleanup(self.cleanup_workspace)
        self.project = self.tmp / "project"
        shutil.copytree(FIXTURES / "project", self.project)
        self.source = str(self.project / "README.md")

    def cleanup_workspace(self):
        target = self.tmp.resolve()
        if target.parent != self.work.resolve():
            raise AssertionError("Test cleanup target escaped plugin test workspace")
        def writable(function, path, error):
            os.chmod(path, 0o777)
            function(path)
        shutil.rmtree(target, onerror=writable)

    def line(self, text):
        return {"text": text, "source": {"source_path": self.source, "quote": text}}

    def resume(self):
        return {"name": self.line("Alex Rivera"), "contact": [self.line("alex@example.test")],
                "sections": {"Projects": [self.line("Built a Python inventory tool."),
                                          self.line("Wrote SQL queries and unit tests.")],
                             "Skills": [self.line("Python")]}}

    def render(self, resume=None, out=None, **kwargs):
        return render_resume(resume or self.resume(), str(out or self.tmp / "output"), **kwargs)

    def test_mcp_real_stdio_round_trip(self):
        calls = [
            {"id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"method": "notifications/initialized"}, {"id": 2, "method": "tools/list"},
            {"id": 3, "method": "tools/call", "params": {"name": "read_job", "arguments": {"text": "Title: Developer\nRequirements:\nPython"}}},
            {"id": 4, "method": "tools/call", "params": {"name": "render_resume", "arguments": {"resume_json": self.resume(), "out_dir": str(self.tmp / "mcp")}}},
            {"id": 5, "method": "tools/call", "params": {"name": "read_job", "arguments": {"text": "x", "transport": "forbidden"}}},
        ]
        wire = "\n".join(json.dumps(dict(jsonrpc="2.0", **c)) for c in calls) + "\n"
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        result = subprocess.run([sys.executable, str(ROOT / "server" / "resume_server.py")], input=wire,
                                capture_output=True, encoding="utf-8", timeout=20, cwd=self.tmp, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        packets = {p["id"]: p["result"] for p in map(json.loads, result.stdout.splitlines())}
        self.assertEqual(packets[1]["serverInfo"]["name"], "untapped-resume")
        self.assertEqual({t["name"] for t in packets[2]["tools"]},
                         {"scan_evidence", "read_job", "render_resume", "render_portfolio", "ats_check"})
        self.assertEqual(packets[3]["structuredContent"]["must_have"], ["Python"])
        self.assertTrue(Path(packets[4]["structuredContent"]["files"]["pdf"]).is_file())
        self.assertTrue(packets[5]["isError"])

    def test_scan_folder_stable_sources_dates(self):
        result = scan_evidence(self.project)
        self.assertEqual(result["notes"], [])
        self.assertEqual(len(result["items"]), 2)
        for item in result["items"]:
            self.assertLessEqual(len(item["text_excerpt"]), 600)
            self.assertTrue(Path(item["source_path"]).is_absolute())
            self.assertIn(item["text_excerpt"], " ".join(read_source_text(item["source_path"]).split()))
        undated = next(i for i in result["items"] if i["title"] == "undated.txt")
        self.assertEqual(undated["dates_if_stated"], [])
        dated = next(i for i in result["items"] if i["title"] == "README.md")
        self.assertIn("January 2025", dated["dates_if_stated"])
        self.assertEqual(result, scan_evidence(self.project))

    def test_scan_skips_internals_binaries_and_limits(self):
        for name in (".git", "node_modules"):
            target = self.project / name
            target.mkdir()
            (target / "secret.txt").write_text("must never appear")
        (self.project / "large.bin").write_bytes(b"\0" * 5_000_001)
        with patch("evidence._git_stats", return_value=None):
            result = scan_evidence(self.project)
            self.assertEqual(len(result["items"]), 2)
            self.assertTrue(any("oversized" in note for note in result["notes"]))
            limited = scan_evidence(self.project, max_files=1)
        self.assertEqual(len(limited["items"]), 1)
        self.assertTrue(any("limit" in note for note in limited["notes"]))
        for bad in (True, 0, -1, 10001, "1"):
            with self.assertRaises(ValueError):
                scan_evidence(self.project, bad)

    @unittest.skipUnless(shutil.which("git"), "git not installed; scanner degrades with a note")
    def test_tiny_git_repository_fixture(self):
        repo = self.tmp / "tiny-repo"
        repo.mkdir()
        subprocess.run(["git", "init", "--quiet", str(repo)], check=True, capture_output=True)
        # fast-import creates only the isolated fixture; no staging/commit commands touch the working repo.
        subprocess.run(["git", "-C", str(repo), "fast-import", "--quiet"], check=True,
                       input=(FIXTURES / "tiny-repo.fi").read_bytes(), capture_output=True)
        result = scan_evidence(repo)
        item = next(i for i in result["items"] if i["kind"] == "git_stats")
        self.assertIn("commits: 2", item["text_excerpt"])
        self.assertIn(".py (1)", item["text_excerpt"])
        self.assertIn("2025-01", item["text_excerpt"])
        self.assertIn(item["text_excerpt"], read_source_text(item["source_path"]))
        with patch("evidence.subprocess.run", side_effect=FileNotFoundError("git missing")):
            self.assertTrue(scan_evidence(repo)["notes"])

    def test_linkedin_zip_all_five_csvs_and_source_roundtrip(self):
        # The export is kept as plain CSVs (so the public repo's secret scan can read it) and zipped here.
        with zipfile.ZipFile(self.project / "linkedin.zip", "w") as archive:
            for csv in sorted((FIXTURES / "linkedin-export").rglob("*.csv")):
                archive.write(csv, csv.relative_to(FIXTURES / "linkedin-export").as_posix())
        items = [i for i in scan_evidence(self.project)["items"] if i["kind"].startswith("linkedin_")]
        self.assertEqual(len(items), 6)
        self.assertEqual(len({i["kind"] for i in items}), 5)
        for item in items:
            self.assertEqual(item["text_excerpt"], read_source_text(item["source_path"]))
        self.assertTrue(any("Python" in i["text_excerpt"] for i in items))

    def test_scan_docx_and_pdf(self):
        result = self.render(out=self.project)
        items = scan_evidence(self.project)["items"]
        for suffix in ("docx", "pdf"):
            item = next(i for i in items if i["title"] == "resume." + suffix)
            self.assertIn("Alex Rivera", item["text_excerpt"])
            self.assertIn("Alex Rivera", read_source_text(item["source_path"]))

    def test_broken_archive_reported(self):
        (self.project / "broken.docx").write_bytes(b"not a zip")
        (self.project / "broken.zip").write_bytes(b"not a zip")
        notes = scan_evidence(self.project)["notes"]
        self.assertEqual(len(notes), 2)

    def test_numeric_metric_is_not_a_date(self):
        (self.project / "metrics.txt").write_text("Processed 2025 rows and 5000 records.")
        item = next(i for i in scan_evidence(self.project)["items"] if i["title"] == "metrics.txt")
        self.assertEqual(item["dates_if_stated"], [])

    def test_job_plaintext_fixture(self):
        result = read_job(text=(FIXTURES / "job-python.txt").read_text())
        self.assertEqual(result["title"], "Junior Python Developer")
        self.assertEqual(result["company"], "Example Inventory")
        self.assertEqual(result["must_have"], ["Python", "SQL", "Unit tests"])
        self.assertEqual(result["nice_to_have"], ["Docker", "Open source contributions"])
        self.assertIn({"term": "python", "count": 3}, result["repeated_terms"])
        self.assertIn("SQL", result["employer_skill_words"])

    def test_job_html_injected_transport(self):
        seen = []
        def get(url, timeout):
            seen.append((url, timeout))
            return (FIXTURES / "job-analyst.html").read_bytes(), "text/html; charset=utf-8"
        result = read_job(url="https://example.test/job", transport=get)
        self.assertEqual(seen, [("https://example.test/job", 20)])
        self.assertEqual(result["title"], "Junior Data Analyst")
        self.assertEqual(result["must_have"], ["SQL required", "Python required"])
        self.assertEqual(result["nice_to_have"], ["Tableau preferred", "Git is a plus"])
        self.assertNotIn("tracking", result["text"])
        self.assertNotIn("display:none", result["text"])

    def test_job_unknown_fields_not_guessed(self):
        result = read_job(text="Join our friendly team!\nPython required\nSQL preferred")
        self.assertIsNone(result["title"])
        self.assertIsNone(result["company"])
        self.assertEqual(result["must_have"], ["Python required"])
        self.assertEqual(result["nice_to_have"], ["SQL preferred"])

    def test_job_exclusive_input_and_https(self):
        for kwargs in ({}, {"text": "x", "url": "https://example.test"}, {"text": ""},
                       {"url": "http://example.test"}, {"url": "file:///secret"}):
            with self.assertRaises(ValueError):
                read_job(**kwargs)

    def test_url_fetch_timeout_and_redirect_validation_without_network(self):
        class Response:
            headers = {"Content-Type": "text/plain"}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def geturl(self): return "https://example.test/job"
            def read(self, size): return b"Title: Developer\nPython required"
        with patch("job.urllib.request.build_opener") as factory:
            factory.return_value.open.return_value = Response()
            _fetch("https://example.test/job")
            self.assertEqual(factory.return_value.open.call_args.kwargs["timeout"], 20)
            handler = factory.call_args.args[0]()
            with self.assertRaises(ValueError):
                handler.redirect_request(None, None, 302, "Found", {}, "http://example.test/plain")

    def test_resume_refuses_missing_empty_and_string_source(self):
        for source in (None, {}, "README.md", {"source_path": self.source, "quote": " "}):
            resume = self.resume()
            resume["sections"]["Projects"][0]["source"] = source
            with self.assertRaisesRegex(ValueError, "source"):
                self.render(resume)
        self.assertFalse((self.tmp / "output").exists())

    def test_resume_refuses_invisible_characters_and_unknown_sections(self):
        resume = self.resume()
        resume["name"]["text"] = "Alex\u200b Rivera"
        with self.assertRaises(ValueError): self.render(resume)
        resume = self.resume()
        resume["sections"]["Secret keywords"] = [self.line("Python")]
        with self.assertRaises(ValueError): self.render(resume)

    def test_docx_valid_package_and_xml_plain_structure(self):
        result = self.render()
        with zipfile.ZipFile(result["files"]["docx"]) as archive:
            self.assertIsNone(archive.testzip())
            for name in archive.namelist():
                ET.fromstring(archive.read(name))
            xml = archive.read("word/document.xml")
            for forbidden in (b"<w:tbl", b"<w:drawing", b"<w:txbx", b"<w:cols"):
                self.assertNotIn(forbidden, xml)
            self.assertIn(b'Courier New', xml)

    def test_pdf_text_roundtrip_matches_txt_and_source_lines(self):
        resume = self.resume()
        resume["sections"]["Summary"] = [self.line("A (quoted) path \\ with caf\u00e9 and curly \u201cquotes\u201d.")]
        result = self.render(resume)
        extracted = extract_pdf(result["files"]["pdf"])
        self.assertEqual(extracted["text"], Path(result["files"]["txt"]).read_text(encoding="utf-8"))
        self.assertEqual(extracted["pages"], 1)
        self.assertEqual(extracted["warnings"], [])
        self.assertFalse(extracted["hidden_text"])
        sources = json.loads(Path(result["sources_path"]).read_text(encoding="utf-8"))
        self.assertEqual([row["text"] for row in sources["lines"]], extracted["lines"])

    def test_long_resume_warns_and_preserves_all_text(self):
        resume = self.resume()
        resume["sections"]["Projects"] *= 40
        result = self.render(resume)
        self.assertEqual(result["pages"], 2)
        self.assertIn("one page", result["warnings"][0])
        self.assertEqual(extract_pdf(result["files"]["pdf"])["text"], Path(result["files"]["txt"]).read_text())
        self.assertEqual(extract_pdf(result["files"]["pdf"])["pages"], 2)

    def test_unicode_pdf_fails_without_transliteration_docx_txt_survive(self):
        resume = self.resume()
        resume["name"]["text"] = "\u674e\u660e"
        with self.assertRaisesRegex(ValueError, "original spelling"):
            self.render(resume)
        self.assertFalse((self.tmp / "output").exists())
        result = self.render(resume, formats=["docx", "txt"])
        self.assertIn("\u674e\u660e", Path(result["files"]["txt"]).read_text(encoding="utf-8"))

    def test_pdf_flate_tj_hex_and_literal_reader(self):
        stream = b"BT /F1 10 Tf 0 g 1 0 0 1 54 738 Tm [(Hello) 10 <20776f726c64>] TJ T* (Next\\050line\\051) Tj ET"
        compressed = zlib.compress(stream)
        pdf = b"%PDF-1.4\n1 0 obj << /Type /Page >> endobj\n2 0 obj << /Filter /FlateDecode >>\nstream\n" + compressed + b"\nendstream\nendobj\n%%EOF"
        target = self.tmp / "flate.pdf"
        target.write_bytes(pdf)
        self.assertEqual(extract_pdf(target)["lines"], ["Hello world", "Next(line)"])

    def test_portfolio_sorted_self_contained_escaped_accessible(self):
        projects = [{"title": self.line(title), "bullets": [self.line("Built a Python inventory tool.")], "fit_score": score}
                    for title, score in (("Fourth", 10), ("Second", 80), ("First", 100), ("Third", 50))]
        data = {"name": self.line("Alex Rivera"), "intro": self.line('<script>alert("x")</script>'), "projects": projects}
        result = render_portfolio(data, self.tmp / "web")
        html = Path(result["path"]).read_text()
        self.assertLess(html.index('>First<'), html.index('>Second<'))
        self.assertLess(html.index('>Third<'), html.index('>Fourth<'))
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn('<script>', html)
        self.assertNotRegex(html, r'https?://|src=|href=')
        self.assertIn('name="viewport"', html)
        self.assertIn('<main>', html)
        self.assertIn('aria-labelledby=', html)
        self.assertNotIn('Built with', html)
        self.assertEqual(result["featured"], 3)

    def test_portfolio_refuses_unsourced_and_does_not_invent_three(self):
        data = {"name": self.line("Alex Rivera"), "projects": [{"title": self.line("Inventory"),
                "bullets": [{"text": "No source"}], "fit_score": 50}]}
        with self.assertRaises(ValueError): render_portfolio(data, self.tmp / "web")
        data["projects"][0]["bullets"] = [self.line("Python")]
        result = render_portfolio(data, self.tmp / "web")
        self.assertEqual(result["featured"], 1)
        self.assertTrue(result["warnings"])

    def test_ats_traces_and_scores_covered_partial_missing(self):
        result = self.render()
        report = ats_check(result["files"]["pdf"], {"must_have": ["Python", "SQL and Docker", "Java"]}, result["sources_path"])
        self.assertEqual([r["status"] for r in report["coverage"]], ["covered", "partly", "no evidence yet"])
        self.assertEqual(report["score_percent"], 50)
        self.assertEqual(report["flags"], [])
        self.assertTrue(report["traced_lines"])

    def test_ats_flags_unsourced_injected_line(self):
        result = self.render()
        lines = extract_pdf(result["files"]["pdf"])["lines"]
        write_pdf(lines + ["Invented employer and 100% improvement"], Path(result["files"]["pdf"]))
        report = ats_check(result["files"]["pdf"], {"must_have": []}, result["sources_path"])
        self.assertTrue(any(f["kind"] == "untraceable_line" and "Invented" in f["text"] for f in report["flags"]))
        self.assertTrue(any(f["kind"] == "file_changed" for f in report["flags"]))

    def test_ats_checks_source_contents_not_just_reference(self):
        resume = self.resume()
        resume["sections"]["Skills"] = [self.line("Java")]
        result = self.render(resume)
        report = ats_check(result["files"]["pdf"], {"must_have": ["Java"]}, result["sources_path"])
        self.assertEqual(report["coverage"][0]["status"], "no evidence yet")
        self.assertTrue(any(f["kind"] == "untraceable_line" for f in report["flags"]))
        resume["sections"]["Skills"][0]["source"]["quote"] = "Python"
        result = self.render(resume)
        report = ats_check(result["files"]["pdf"], {"must_have": ["Java"]}, result["sources_path"])
        self.assertEqual(report["coverage"][0]["status"], "no evidence yet")
        self.assertTrue(any("Words not verified" in f.get("reason", "") for f in report["flags"]))

    def test_ats_missing_source_flag(self):
        result = self.render()
        Path(self.source).unlink()
        report = ats_check(result["files"]["pdf"], {"must_have": ["Python"]}, result["sources_path"])
        self.assertEqual(report["coverage"][0]["status"], "no evidence yet")
        self.assertTrue(any("missing" in f.get("reason", "") for f in report["flags"]))

    def test_ats_flags_hidden_text_images_tables_and_length(self):
        result = self.render()
        path = Path(result["files"]["pdf"])
        original = path.read_bytes()
        for signal in (b"3 Tr", b"7 Tr", b"1 g", b"1 1 1 rg", b"/F1 1 Tf"):
            path.write_bytes(original.replace(b"0 g", signal))
            report = ats_check(path, {"must_have": ["Python"]}, result["sources_path"])
            self.assertTrue(any(f["kind"] == "hidden_text" for f in report["flags"]), signal)
            self.assertNotEqual(report["coverage"][0]["status"], "covered")
        path.write_bytes(original + b"\n<< /Subtype /Image /S /Table /Type /Page >>")
        report = ats_check(path, {"must_have": []}, result["sources_path"])
        kinds = {f["kind"] for f in report["flags"]}
        self.assertTrue({"images", "tables", "length"} <= kinds)

    def test_readme_and_plugin_listing_avoid_forbidden_word(self):
        for path in (ROOT / "README.md", ROOT / ".codex-plugin" / "plugin.json", ROOT / ".claude-plugin" / "plugin.json"):
            self.assertNotRegex(path.read_text(encoding="utf-8"), r"\bSEO\b")
        for path in (LANE / ".agents" / "plugins" / "marketplace.json", LANE / ".claude-plugin" / "marketplace.json"):
            entry = next(p for p in json.loads(path.read_text())["plugins"] if p["name"] == "untapped-resume")
            self.assertNotRegex(json.dumps(entry), r"\bSEO\b")

    def test_shared_and_manifests_current(self):
        for script in ("sync_shared.py", "manifests.py"):
            result = subprocess.run([sys.executable, str(LANE / "tools" / script), "--check"],
                                    capture_output=True, encoding="utf-8", timeout=20,
                                    env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
