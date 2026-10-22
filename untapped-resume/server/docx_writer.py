"""Source-backed resume layout, minimal WordprocessingML, and output coordinator."""
from __future__ import annotations

import hashlib
import json
import textwrap
import unicodedata
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from pdf_writer import WIDTH, LINES_PER_PAGE, write_pdf

HEADINGS = ("Summary", "Experience", "Projects", "Education", "Skills", "Certifications")


def clean_text(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Every text field must be a nonempty string.")
    if any(unicodedata.category(c) in ("Cc", "Cf", "Cs") and c not in "\n\r\t" for c in value):
        raise ValueError("Control, invisible, and surrogate characters are not allowed.")
    if len(value) > 10000:
        raise ValueError("A text field exceeds 10,000 characters.")
    return " ".join(value.split())


def sourced(item):
    if not isinstance(item, dict) or set(item) - {"text", "source", "bullet"}:
        raise ValueError("Each line must be {text, source, optional bullet}.")
    text = clean_text(item.get("text"))
    source = item.get("source")
    if not isinstance(source, dict):
        raise ValueError("Every line/bullet needs a source object with source_path and quote.")
    for key in ("source_path", "quote"):
        if not isinstance(source.get(key), str) or not source[key].strip():
            raise ValueError("Every line/bullet needs a nonempty source_path and quote.")
    if "bullet" in item and type(item["bullet"]) is not bool:
        raise ValueError("bullet must be a boolean.")
    return text, {"source_path": source["source_path"].strip(), "quote": source["quote"].strip()}


def layout_resume(resume):
    if not isinstance(resume, dict) or set(resume) - {"name", "contact", "sections"}:
        raise ValueError("resume_json takes name, optional contact, and sections.")
    sections = resume.get("sections")
    if not isinstance(sections, dict) or not sections or set(sections) - set(HEADINGS):
        raise ValueError("Use standard section headings: " + ", ".join(HEADINGS))
    records = []

    def add(item, default_bullet=False):
        text, source = sourced(item)
        prefix = "- " if item.get("bullet", default_bullet) else ""
        wrapped = textwrap.wrap(text, width=WIDTH, initial_indent=prefix,
                                subsequent_indent="  " if prefix else "", break_long_words=True,
                                break_on_hyphens=False)
        for line in wrapped:
            records.append({"line": len(records) + 1, "text": line, "source": source,
                            "claim": text, "structural": False})

    add(resume.get("name"))
    contact = resume.get("contact", [])
    if not isinstance(contact, list):
        raise ValueError("contact must be an array of sourced lines.")
    for item in contact:
        add(item)
    for heading in HEADINGS:
        if heading not in sections:
            continue
        items = sections[heading]
        if not isinstance(items, list):
            raise ValueError("Each section must be an array of sourced lines.")
        if not items:
            continue
        records.append({"line": len(records) + 1, "text": heading, "source": None, "structural": True})
        for item in items:
            add(item, heading in ("Experience", "Projects"))
    if len(records) > 1000:
        raise ValueError("Resume exceeds 1,000 output lines; shorten it first.")
    return records


def write_docx(lines, path):
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    paras = []
    for i, line in enumerate(lines):
        pagebreak = '<w:pageBreakBefore/>' if i and i % LINES_PER_PAGE == 0 else ''
        bold = '<w:b/>' if line in HEADINGS or i == 0 else ''
        paras.append(f'<w:p><w:pPr>{pagebreak}<w:spacing w:before="0" w:after="0" w:line="260" '
                     f'w:lineRule="exact"/></w:pPr><w:r><w:rPr><w:rFonts w:ascii="Courier New" '
                     f'w:hAnsi="Courier New" w:eastAsia="Courier New"/><w:sz w:val="20"/>{bold}</w:rPr>'
                     f'<w:t xml:space="preserve">{escape(line)}</w:t></w:r></w:p>')
    document = (f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{ns}"><w:body>'
                + ''.join(paras) + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
                '<w:pgMar w:top="1080" w:right="1080" w:bottom="1080" w:left="1080"/>'
                '</w:sectPr></w:body></w:document>')
    types = ('<?xml version="1.0" encoding="UTF-8"?>'
             '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Override PartName="/word/document.xml" '
             'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
             '</Types>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/></Relationships>')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, value in (("[Content_Types].xml", types), ("_rels/.rels", rels), ("word/document.xml", document)):
            archive.writestr(name, value.encode("utf-8"))


def render_resume(resume_json, out_dir, formats=None):
    formats = ["docx", "pdf", "txt"] if formats is None else formats
    if not isinstance(formats, list) or not formats or any(f not in ("docx", "pdf", "txt") for f in formats):
        raise ValueError("formats must be a nonempty array drawn from docx, pdf, txt.")
    records = layout_resume(resume_json)
    lines = [row["text"] for row in records]
    if "pdf" in formats:
        try:
            "\n".join(lines).encode("cp1252")
        except UnicodeEncodeError:
            raise ValueError("The built-in PDF font supports Windows-1252 text only. Keep the original spelling; "
                             "request docx/txt and export a Unicode PDF in Word or LibreOffice.") from None
    out = Path(out_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    files = {}
    for fmt in dict.fromkeys(formats):
        path = out / ("resume." + fmt)
        if fmt == "docx":
            write_docx(lines, path)
        elif fmt == "pdf":
            write_pdf(lines, path)
        else:
            path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        files[fmt] = str(path)
    pages = (len(lines) + LINES_PER_PAGE - 1) // LINES_PER_PAGE
    sidecar = {"schema_version": 1, "lines": records, "pages": pages,
               "verification": "References supplied by the author; ats_check verifies quotes, not factual entailment.",
               "sha256": {fmt: hashlib.sha256(Path(path).read_bytes()).hexdigest() for fmt, path in files.items()}}
    sources = out / "sources.json"
    sources.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    warnings = [] if pages <= 1 else [f"Resume runs past one page ({pages} pages). Shorten it; no text was discarded."]
    return {"files": files, "sources_path": str(sources), "pages": pages, "warnings": warnings}
