"""Bounded, local-only evidence readers for untapped-resume."""
from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import subprocess
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_FILE = 5_000_000
MAX_ZIP_TOTAL = 20_000_000
MAX_ZIP_ENTRIES = 2000
MAX_TEXT = 600
LINKEDIN_CSVS = ("Positions.csv", "Education.csv", "Skills.csv", "Certifications.csv", "Projects.csv")
SKIP_DIRS = {".git", "node_modules"}
TEXT_EXTS = {".md", ".txt"}


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _dates(s: str) -> list[str]:
    # Preserve only explicit date-like strings; never infer missing dates.
    found = re.findall(r"\b(?:(?:19|20)\d{2}(?:-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])|[-/](?:0?[1-9]|1[0-2]))|(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(?:19|20)\d{2})\b", s, re.I)
    # An isolated four-digit metric is not a date. Accept years only in explicit
    # date fields or year ranges, preserving just the stated values.
    found += re.findall(r"\b(?:start(?:ed)?(?: date| on)?|end(?: date)?|finished on|date|graduated)\s*:\s*((?:19|20)\d{2})(?![\d/-])", s, re.I)
    for start, end in re.findall(r"\b((?:19|20)\d{2})\s*(?:to|[-\u2013\u2014])\s*((?:19|20)\d{2})\b", s, re.I):
        found.extend((start, end))
    return list(dict.fromkeys(found))


def _item(path: str, kind: str, title: str, content: str) -> dict:
    content = _clean(content)
    return {"id": hashlib.sha256((path + "\0" + kind + "\0" + title).encode("utf-8", "replace")).hexdigest()[:16],
            "kind": kind, "title": _clean(title)[:180] or Path(path).name,
            "text_excerpt": content[:MAX_TEXT], "dates_if_stated": _dates(content), "source_path": path}


def _docx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        info = z.getinfo("word/document.xml")
        if info.file_size > MAX_FILE: raise ValueError("DOCX document XML too large")
        root = ET.fromstring(z.read(info))
    return " ".join((n.text or "") for n in root.iter() if n.tag.endswith("}t"))


def _csv_rows(raw: str, filename: str) -> list[list[str]]:
    rows = list(csv.reader(io.StringIO(raw)))
    expected = {"positions.csv": {"company name", "title"}, "education.csv": {"school name", "degree name"},
                "skills.csv": {"name", "skill"}, "certifications.csv": {"name", "authority"},
                "projects.csv": {"title", "description"}}.get(filename.lower(), set())
    for i, row in enumerate(rows[:40]):
        normalized = {re.sub(r"\s+", " ", c.strip().lower()) for c in row}
        if expected & normalized:
            return rows[i:]
    # Skills exports can be a single-column list without a header.
    if filename.lower() == "skills.csv":
        for row in rows[:40]:
            if len(row) == 1 and row[0].strip().lower() in {"skill", "name"}:
                return rows[rows.index(row):]
        return [["Skill"], *[[c] for row in rows for c in row if c.strip()]]
    raise ValueError(f"Could not find CSV header in {filename}")


def _row_text(header, row) -> str:
    return "; ".join(f"{_clean(header[i]) if i < len(header) else 'field'}: {_clean(v)}" for i, v in enumerate(row) if _clean(v))


def _linkedin(data: bytes, archive: Path) -> list[dict]:
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos = z.infolist()
        if len(infos) > MAX_ZIP_ENTRIES or sum(x.file_size for x in infos) > MAX_ZIP_TOTAL:
            raise ValueError("ZIP expansion limit exceeded")
        bybase = {Path(x.filename).name.lower(): x for x in infos if not x.is_dir()}
        for name in LINKEDIN_CSVS:
            info = bybase.get(name.lower())
            if not info: continue
            if info.file_size > MAX_FILE: raise ValueError("CSV entry too large: " + name)
            raw = z.read(info).decode("utf-8-sig", "replace")
            rows = _csv_rows(raw, name)
            if len(rows) > 5001: raise ValueError(f"{name} exceeds 5000 data rows")
            if not rows: continue
            header = rows[0]
            for rownum, row in enumerate(rows[1:], 2):
                content = _row_text(header, row)
                if content:
                    locator = str(archive.resolve()) + "::member=" + info.filename + f"#row={rownum}"
                    out.append(_item(locator, "linkedin_" + Path(name).stem.lower(), name + " row " + str(rownum), content))
    return out


def _git_stats(root: Path, notes: list[str]) -> dict | None:
    if not (root / ".git").exists(): return None
    try:
        def run(args):
            return subprocess.run(["git", "-c", "protocol.allow=never", "-c", "core.fsmonitor=false", "-C", str(root),
                                   args[0], "--no-ext-diff", "--no-textconv", *args[1:]], capture_output=True,
                                  text=True, encoding="utf-8", errors="replace", timeout=10, check=True,
                                  env=dict(os.environ, GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")).stdout.strip()
        hashes = run(["log", "--no-show-signature", "--format=%H"]).splitlines()
        dates = run(["log", "--no-show-signature", "--format=%aI"]).splitlines()
        exts = {}
        names = set(run(["log", "--no-show-signature", "--name-only", "--format="]).splitlines())
        for name in names:
            ext = Path(name).suffix.lower()
            if ext: exts[ext] = exts.get(ext, 0) + 1
        body = f"Repository metadata; commits: {len(hashes)}"
        if dates: body += f"; commit date range: {min(dates)} to {max(dates)}"
        if exts: body += "; unique tracked file extensions: " + ", ".join(f"{k} ({v})" for k,v in sorted(exts.items()))
        return {"commit_count": len(hashes), "date_range": [min(dates), max(dates)] if dates else None,
                "languages_by_extension": dict(sorted(exts.items())), "item": _item(str(root.resolve()) + "::git-summary", "git_stats", "Git repository metadata", body)}
    except (OSError, subprocess.SubprocessError) as e:
        notes.append(f"Could not read git history: {e}")
        return None


def scan_evidence(folder, max_files=500) -> dict:
    root = Path(folder).expanduser().resolve()
    if not root.is_dir(): raise ValueError("folder must be an existing directory")
    if type(max_files) is not int or not 1 <= max_files <= 10000: raise ValueError("max_files must be an integer from 1 to 10000")
    notes, items = [], []
    git = _git_stats(root, notes)
    paths = []
    truncated = False
    for base, dirs, files in os.walk(root, followlinks=False,
                                   onerror=lambda error: notes.append(f"Could not scan directory: {error}")):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (Path(base) / d).is_symlink())
        for f in sorted(files):
            p = Path(base) / f
            if p.is_symlink(): continue
            paths.append(p)
            if len(paths) > max_files:
                paths.pop(); truncated = True; break
        if truncated: break
    if truncated: notes.append(f"File limit reached: scanned first {max_files} files in deterministic directory order")
    for p in paths:
        rel = p.relative_to(root).as_posix()
        absolute = str(p.resolve())
        ext = p.suffix.lower()
        try:
            if p.stat().st_size > MAX_FILE:
                notes.append(f"Skipped oversized file: {rel}"); continue
            if ext in TEXT_EXTS or p.name.lower().startswith("readme"):
                content = p.read_text(encoding="utf-8", errors="replace")
                if content.strip(): items.append(_item(absolute, "document", p.name, content))
            elif ext == ".docx": items.append(_item(absolute, "document", p.name, _docx(p.read_bytes())))
            elif ext == ".pdf":
                try:
                    from pdf_writer import extract_pdf
                    parsed = extract_pdf(p)
                    content = parsed.get("text", "") if isinstance(parsed, dict) else ""
                    items.append(_item(absolute, "document", p.name, content))
                    if isinstance(parsed, dict) and parsed.get("warnings"): notes.extend(f"{rel}: {x}" for x in parsed["warnings"])
                except Exception as e: notes.append(f"Could not extract PDF {rel}: {e}")
            elif ext == ".zip":
                try:
                    with zipfile.ZipFile(p) as z:
                        infos = z.infolist()
                        if len(infos) > MAX_ZIP_ENTRIES or sum(x.file_size for x in infos) > MAX_ZIP_TOTAL:
                            raise ValueError("ZIP expansion limit exceeded")
                        bases = {Path(x.filename).name.lower() for x in infos}
                    if any(n.lower() in bases for n in LINKEDIN_CSVS): items.extend(_linkedin(p.read_bytes(), p))
                except Exception as e: notes.append(f"Could not read ZIP {rel}: {e}")
        except Exception as e: notes.append(f"Could not read {rel}: {e}")
    if git: items.append(git["item"])
    return {"items": items, "notes": notes}


def read_source_text(source_path) -> str:
    """Resolve a scanner source locator to bounded source text for trace checks."""
    locator = str(source_path)
    if "::" in locator:
        base, ref = locator.split("::", 1)
        if ref == "git-summary":
            root = Path(base)
            notes = []
            summary = _git_stats(root, notes)
            return summary["item"]["text_excerpt"] if summary else ""
        if ref.startswith("member="):
            member, _, rowpart = ref[len("member="):].partition("#row=")
            with zipfile.ZipFile(base) as z:
                info = z.getinfo(member)
                if info.file_size > MAX_FILE: raise ValueError("ZIP entry too large")
                raw = z.read(info).decode("utf-8-sig", "replace")
            if rowpart:
                rows = _csv_rows(raw, Path(member).name)
                row_index = int(rowpart)
                if row_index < 1 or row_index > len(rows): return ""
                header = rows[0] if rows else []
                return "; ".join(f"{_clean(header[i]) if i < len(header) else 'field'}: {_clean(v)}" for i,v in enumerate(rows[row_index-1]) if _clean(v))
            return raw[:MAX_FILE]
        if ref.startswith("git:"):
            commit = ref[4:]
            if not re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})", commit): raise ValueError("Invalid git commit hash")
            return subprocess.run(["git", "-c", "protocol.allow=never", "-c", "core.fsmonitor=false", "-C", base,
                                   "show", "--no-ext-diff", "--no-textconv", "--no-show-signature", "--format=fuller", "--stat", commit, "--"],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, check=True,
                                  env=dict(os.environ, GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")).stdout[:MAX_FILE]
    p = Path(locator)
    if p.stat().st_size > MAX_FILE: raise ValueError("source file too large")
    ext = p.suffix.lower()
    data = p.read_bytes()
    if ext in TEXT_EXTS or p.name.lower().startswith("readme"):
        return data.decode("utf-8", "replace")[:MAX_FILE]
    if ext == ".docx": return _docx(data)[:MAX_FILE]
    if ext == ".pdf":
        from pdf_writer import extract_pdf
        parsed = extract_pdf(p)
        return (parsed.get("text", "") if isinstance(parsed, dict) else "")[:MAX_FILE]
    if ext == ".zip":
        raise ValueError("ZIP locator must include ::member=<csv path>")
    return ""
