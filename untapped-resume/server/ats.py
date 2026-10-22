"""Conservative text and provenance checks, not an interview prediction service."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

from docx_writer import HEADINGS
from evidence import read_source_text
from pdf_writer import extract_pdf

STOP = set("a an the and or of to in on for with as at by from is are was were be been being "
           "have has had must should required requirement requirements preferred experience "
           "knowledge proficiency proficient ability able skills skill strong excellent good "
           "working work using used use candidate candidates you your we our will plus demonstrated "
           "i my me this that it possess minimum least".split())


def words(text):
    return {word.casefold().strip(".-") for word in re.findall(r"[\w]+(?:[.+#/-][\w+#]+)*[+#]*", text)
            if word.casefold() not in STOP}


def normalized(text):
    return " ".join(text.split()).casefold()


def ats_check(pdf_path, job_json, sources_path):
    if not isinstance(job_json, dict) or not isinstance(job_json.get("must_have", []), list):
        raise ValueError("job_json must contain a must_have array from read_job.")
    requirements = job_json.get("must_have", [])
    if not all(isinstance(r, str) and r.strip() for r in requirements):
        raise ValueError("must_have entries must be nonempty strings.")
    pdf = extract_pdf(pdf_path)
    path = Path(sources_path)
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError("Sources sidecar exceeds 10 MB.")
    sidecar = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(sidecar, dict) or not isinstance(sidecar.get("lines"), list):
        raise ValueError("Expected the sources.json sidecar written by render_resume.")
    indexed = defaultdict(list)
    for row in sidecar["lines"]:
        if isinstance(row, dict) and isinstance(row.get("text"), str):
            indexed[row["text"]].append(row)
    flags, traced, cache, supported = [], [], {}, set()
    for i, text in enumerate(pdf["lines"], 1):
        candidates = indexed.get(text, [])
        row = candidates.pop(0) if candidates else None
        if row and row.get("structural") is True and text in HEADINGS and row.get("source") is None:
            continue
        reason = None
        source = row.get("source") if row else None
        if not isinstance(source, dict) or not all(isinstance(source.get(k), str) and source[k].strip()
                                                   for k in ("source_path", "quote")):
            reason = "No usable source reference for this extracted line."
        else:
            location = source["source_path"]
            if location not in cache:
                try:
                    cache[location] = normalized(read_source_text(location))
                except (ValueError, OSError, KeyError, RuntimeError, subprocess.SubprocessError,
                        zipfile.BadZipFile, ET.ParseError):
                    cache[location] = None
            original = cache[location]
            quote = source["quote"]
            if not original:
                reason = "Source is missing or could not be read."
            elif normalized(quote) not in original:
                reason = "Quoted evidence was not found in the source."
            else:
                claim_words = words(text.lstrip("- "))
                evidence_words = words(quote)
                supported.update(claim_words & evidence_words)
                unknown = sorted(claim_words - evidence_words)
                if unknown:
                    reason = "Words not verified in the quoted evidence; review the claim: " + ", ".join(unknown)
                else:
                    traced.append({"line": i, "text": text, "source": source})
        if reason:
            flags.append({"kind": "untraceable_line", "line": i, "text": text, "reason": reason})
    expected_sha = sidecar.get("sha256", {}).get("pdf")
    actual_sha = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()
    if expected_sha and expected_sha != actual_sha:
        flags.append({"kind": "file_changed", "reason": "PDF differs from the file recorded in sources.json."})
    for key, reason in (("hidden_text", "Possible hidden, white, transparent, or unusually small text."),
                        ("images", "PDF includes images."), ("tables", "PDF includes table structure.")):
        if pdf[key]:
            flags.append({"kind": key, "reason": reason})
    if pdf["pages"] != 1 or len(pdf["lines"]) > 52:
        flags.append({"kind": "length", "reason": f"Detected {pdf['pages']} pages and {len(pdf['lines'])} text lines."})
    for warning in pdf["warnings"]:
        flags.append({"kind": "extraction_uncertain", "reason": warning})
    counts = Counter(word.casefold() for word in re.findall(r"\b\w+\b", pdf["text"]) if word.casefold() not in STOP)
    if counts and counts.most_common(1)[0][1] >= 12:
        flags.append({"kind": "repetition", "reason": "Repeated terms need review for keyword stuffing.",
                      "terms": [{"term": k, "count": v} for k, v in counts.items() if v >= 12]})
    coverage = []
    for requirement in requirements:
        needed = words(requirement)
        matched = needed & supported
        status = "covered" if needed and matched == needed else "partly" if matched else "no evidence yet"
        # A damaged/unsupported extraction can never justify a full coverage claim.
        if status == "covered" and (pdf["warnings"] or pdf["hidden_text"]):
            status = "partly"
        coverage.append({"requirement": requirement, "status": status,
                         "matched_terms": sorted(matched), "missing_terms": sorted(needed - matched)})
    earned = sum(1 if r["status"] == "covered" else .5 if r["status"] == "partly" else 0 for r in coverage)
    return {"coverage": coverage, "score_percent": round(100 * earned / len(coverage), 1) if coverage else None,
            "scoring": "Literal must-have term coverage in resume text and readable quoted sources; partly = half credit.",
            "flags": flags, "traced_lines": traced, "pages": pdf["pages"], "text": pdf["text"],
            "limitations": ["This is a conservative text heuristic, not proof that claims are true or requirements met.",
                            "Review paraphrases, negation, years, credentials, dates and ownership against original evidence.",
                            "PDF reading and graphics detection are best effort; untagged tables and complex hidden text may escape detection."]}
