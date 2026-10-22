"""Read and summarize one job posting; URL transport is injectable for offline use."""
from __future__ import annotations

import html
import html.parser
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

MAX_BODY = 1_000_000
STOP = set("a an and are as at be by for from in into is it of on or that the their this to with will you your we our".split())


class _Text(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.parts=[]; self.hidden=0
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "svg"): self.hidden += 1
        if tag in ("p", "br", "li", "div", "h1", "h2", "h3"): self.parts.append("\n")
    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self.hidden: self.hidden -= 1
        if tag in ("p", "li", "div", "h1", "h2", "h3"): self.parts.append("\n")
    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)


def _plain(raw: str) -> str:
    p = _Text(); p.feed(raw)
    return re.sub(r"[ \t]+", " ", html.unescape(" ".join(p.parts))).strip()


def _sections(text: str):
    lines = [re.sub(r"^[\s•*\-–—]+", "", x).strip() for x in text.splitlines()]
    must, nice = [], []
    mode = None
    headings = {"requirements", "qualifications", "minimum qualifications", "preferred qualifications", "nice to have", "must have", "responsibilities", "benefits", "about us", "about the role", "what you will do"}
    for line in lines:
        if not line: continue
        low = line.lower().strip(": ").replace("-", " ")
        if low in headings:
            mode = "nice" if "preferred" in low or "nice" in low else ("must" if low in {"requirements", "qualifications", "minimum qualifications", "must have"} else None)
            continue
        if re.search(r"\b(preferred|ideally|nice[- ]to[- ]have|bonus|desired|optional|a plus)\b", low):
            nice.append(line)
        elif re.search(r"\b(must|required|requirements?|minimum|proficien\w+|experience with|experience in)\b", low):
            must.append(line)
        elif mode == "nice": nice.append(line)
        elif mode == "must": must.append(line)
    return list(dict.fromkeys(must)), list(dict.fromkeys(nice))


def _fields(text: str):
    title = company = None
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"(?:job\s+)?title\s*[:\-]\s*(.+)", line, re.I)
        if m and not title: title=m.group(1).strip()
        m = re.match(r"company\s*[:\-]\s*(.+)", line, re.I)
        if m and not company: company=m.group(1).strip()
    if not title:
        m = re.search(r"^(.{2,100}?)\s+at\s+(.{2,100})$", text, re.I | re.M)
        if m: title, company = m.group(1).strip(), company or m.group(2).strip()
    return title, company


def _terms(text: str):
    words = re.findall(r"[A-Za-z][A-Za-z+#.\-]{1,}", text.lower())
    counts = Counter(w.strip(".-") for w in words if w not in STOP and len(w.strip(".-")) > 2)
    repeated = [{"term": k, "count": v} for k,v in sorted(counts.items(), key=lambda x: (-x[1], x[0])) if v > 1][:40]
    must, nice = _sections(text)
    reqs = must + nice
    candidates = set()
    for phrase in reqs:
        candidates.update(re.findall(r"(?<!\w)(?:C\+\+|C#|\.NET|[A-Za-z][A-Za-z0-9+#.-]{1,})(?!\w)", phrase))
    candidates = {x for x in candidates if x.lower() not in STOP and len(x) > 1}
    return repeated, sorted(candidates, key=str.lower)


def _fetch(url: str, timeout: int = 20):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname: raise ValueError("URL must use HTTPS")
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if urllib.parse.urlparse(newurl).scheme.lower() != "https": raise ValueError("Refusing non-HTTPS redirect")
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent":"UntappedResume/0.1"})
    with opener.open(req, timeout=timeout) as res:
        if len(res.geturl()) and urllib.parse.urlparse(res.geturl()).scheme.lower() != "https": raise ValueError("Refusing non-HTTPS redirect")
        body = res.read(MAX_BODY + 1)
        if len(body) > MAX_BODY: raise ValueError("Job page exceeds size limit")
        return body, res.headers.get("Content-Type", "")


def read_job(text=None, url=None, transport=None) -> dict:
    if (text is None) == (url is None): raise ValueError("Provide exactly one of text or url")
    source = "text"
    if url is not None:
        if not isinstance(url, str): raise ValueError("url must be a string")
        if urllib.parse.urlparse(url).scheme.lower() != "https": raise ValueError("URL must use HTTPS")
        body, content_type = (transport(url, timeout=20) if transport else _fetch(url, 20))
        if not isinstance(body, (bytes, bytearray)) or len(body) > MAX_BODY: raise ValueError("Invalid or oversized response body")
        raw = bytes(body).decode("utf-8", "replace")
        text = _plain(raw) if "html" in (content_type or "").lower() or re.search(r"<\s*(?:html|body|div|p)\b", raw, re.I) else raw
        source = url
    if not isinstance(text, str): raise ValueError("text must be a string")
    if len(text) > MAX_BODY: raise ValueError("Job text exceeds size limit")
    text = re.sub(r"\r\n?", "\n", text).strip()
    if not text: raise ValueError("Job posting is empty")
    title, company = _fields(text)
    must, nice = _sections(text)
    repeated, skills = _terms(text)
    # Skill terms remain posting-derived words; the writing agent validates semantics.
    return {"title": title, "company": company, "must_have": must, "nice_to_have": nice,
            "repeated_terms": repeated, "employer_skill_words": skills, "text": text, "source": source}
