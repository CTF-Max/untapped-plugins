"""One normalization and rendering path for every agency; no ratings or weights."""
import csv
import html
import io
import json
import re

from extract import read_date, review_candidate, source_url

FOOTER = "Made by Find Untapped Growth — https://finduntappedgrowth.com/"


def normalize_agency(agency, criteria):
    if not isinstance(agency, dict) or set(agency) - {"name", "facts", "approval"}:
        raise ValueError("Each agency needs name and facts only.")
    name = agency.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 160 or any(ord(c) < 32 for c in name):
        raise ValueError("Agency name must be 1–160 characters without control characters.")
    facts = agency.get("facts", {})
    if not isinstance(facts, dict) or set(facts) - {c["id"] for c in criteria}:
        raise ValueError("facts must map known criterion IDs to evidence.")
    out = {"name": name.strip(), "facts": {}}
    for criterion in criteria:
        key = criterion["id"]
        fact = facts.get(key, {"status": "not stated", "candidates": []})
        if not isinstance(fact, dict) or set(fact) - {"status", "candidates"}:
            raise ValueError("A fact needs status and candidates.")
        candidates = fact.get("candidates", [])
        if not isinstance(candidates, list) or len(candidates) > 100:
            raise ValueError("candidates must be a list of at most 100 quotes.")
        if fact.get("status") not in {"stated", "not stated"}:
            raise ValueError("Fact status must be stated or not stated.")
        if (fact["status"] == "stated") != bool(candidates):
            raise ValueError("stated requires evidence; not stated cannot carry claims.")
        clean = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise ValueError("Each candidate must be an evidence object.")
            quote = candidate.get("quote")
            if not isinstance(quote, str) or not quote.strip() or len(quote) > 12000:
                raise ValueError("Each candidate requires a nonempty exact quote (up to 12000 characters).")
            evidence = {"quote": quote, "source_url": source_url(candidate.get("source_url")),
                        "date_read": read_date(candidate.get("date_read"))}
            if key == "reviews":
                numeric = review_candidate(quote)
                if not numeric:
                    raise ValueError("Reviews require a rating out of 5 and a review count, not review text.")
                evidence.update(numeric)
            if evidence not in clean:
                clean.append(evidence)
        out["facts"][key] = {"status": "stated" if clean else "not stated", "candidates": clean}
    return out


def md(value):
    value = html.escape(str(value), quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+.!|>-])", r"\\\1", value).replace("\r", " ").replace("\n", "<br>")


def csv_safe(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def cell_text(fact):
    if fact["status"] == "not stated":
        return "not stated"
    return "\n".join(f'{c["quote"]} [source: {c["source_url"]}; read: {c["date_read"]}]'
                     for c in fact["candidates"])


def compare(agencies_json, criteria, included_agencies=(), priorities=None):
    if isinstance(agencies_json, str):
        if len(agencies_json) > 4 * 1024 * 1024:
            raise ValueError("Agency JSON exceeds 4 MiB.")
        agencies_json = json.loads(agencies_json)
    if not isinstance(agencies_json, list) or len(agencies_json) > 20:
        raise ValueError("Provide a list of at most 20 agencies.")
    priorities = [] if priorities is None else priorities
    ids = [c["id"] for c in criteria]
    if not isinstance(priorities, list) or any(not isinstance(p, str) or p not in ids for p in priorities):
        raise ValueError("priorities must be a list of criterion IDs.")
    order = list(dict.fromkeys(priorities + ids))
    # Checked-in included records are authoritative; caller duplicates cannot replace them.
    required = [normalize_agency(a, criteria) for a in included_agencies]
    required_names = {a["name"].casefold() for a in required}
    supplied = [normalize_agency(a, criteria) for a in agencies_json]
    all_agencies = required + [a for a in supplied if a["name"].casefold() not in required_names]
    if len({a["name"].casefold() for a in all_agencies}) != len(all_agencies):
        raise ValueError("Agency names must be unique (case insensitive). Merge their page evidence first.")
    all_agencies.sort(key=lambda a: a["name"].casefold())
    columns = [a["name"] for a in all_agencies]
    by_id = {c["id"]: c for c in criteria}
    rows = [{"criterion": key, "label": by_id[key]["label"],
             "cells": {a["name"]: a["facts"][key] for a in all_agencies}} for key in order]
    questions = {a["name"]: [{"criterion": key, "question": by_id[key]["question"]} for key in order
                            if a["facts"][key]["status"] == "not stated"] for a in all_agencies}
    sources = sorted({(c["source_url"], c["date_read"]) for a in all_agencies
                      for f in a["facts"].values() for c in f["candidates"]})
    source_text = "Sources and dates read: " + ("; ".join(f"{url} ({day})" for url, day in sources) or "not stated")
    note = "Published claims, not independently verified. Not stated means absent from supplied evidence. " \
           "Priorities change row order only; no overall score or winner."
    grid = [["Criterion"] + columns] + [[row["label"]] + [cell_text(row["cells"][n]) for n in columns] for row in rows]
    markdown = ["| " + " | ".join(md(v) for v in grid[0]) + " |", "| " + " | ".join(["---"] * len(grid[0])) + " |"]
    markdown += ["| " + " | ".join(md(v) for v in row) + " |" for row in grid[1:]]
    markdown += ["", FOOTER, "", md(source_text), "", note, "", "Questions to ask"]
    for name in columns:
        markdown += ["", md(name)] + ["- " + md(q["question"]) for q in questions[name]]
        if not questions[name]:
            markdown += ["- No missing cells in the supplied evidence; confirm claims and terms directly."]
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    for row in grid + [[FOOTER], [source_text], [note], ["Questions to ask", "Agency", "Question"]]:
        writer.writerow([csv_safe(v) for v in row])
    for name, items in questions.items():
        for q in items:
            writer.writerow(["Question", csv_safe(name), csv_safe(q["question"])])
    esc = html.escape
    rendered = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">' \
               '<title>Agency comparison</title><style>body{font:16px system-ui;margin:2rem;color:#172c31}' \
               'table{border-collapse:collapse}td,th{border:1px solid #aaa;padding:.7rem;text-align:left;vertical-align:top}' \
               'td{white-space:pre-wrap;min-width:14rem}footer{margin:1rem 0}section{overflow:auto}</style><body>' \
               '<h1>Agency comparison</h1><section><table><thead><tr>'
    rendered += "".join("<th scope=\"col\">" + esc(v) + "</th>" for v in grid[0]) + "</tr></thead><tbody>"
    for row in grid[1:]:
        rendered += '<tr><th scope="row">' + esc(row[0]) + "</th>" + "".join("<td>" + esc(v) + "</td>" for v in row[1:]) + "</tr>"
    maker, link = FOOTER.split(" — ", 1)
    rendered += '</tbody><tfoot><tr><td colspan="' + str(len(grid[0])) + '">' + esc(maker) + ' — <a href="' + esc(link, quote=True) + '">' + esc(link) + "</a><br>" + esc(source_text) + "</td></tr></tfoot></table></section><p>" + esc(note) + "</p><h2>Questions to ask</h2>"
    for name, items in questions.items():
        rendered += "<h3>" + esc(name) + "</h3><ul>" + "".join("<li>" + esc(q["question"]) + "</li>" for q in items) + "</ul>"
    rendered += "</body></html>"
    return {"columns": columns, "rows": rows, "questions": questions, "sources": [{"source_url": u, "date_read": d} for u, d in sources],
            "footer": FOOTER, "markdown": "\n".join(markdown) + "\n", "csv": stream.getvalue(), "html": rendered}
