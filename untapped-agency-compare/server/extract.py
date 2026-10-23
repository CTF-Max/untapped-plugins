"""Conservative, quote-preserving candidates; never a verification of agency claims."""
from datetime import date, datetime, timezone
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit

MAX_BYTES = 2 * 1024 * 1024


def today():
    return datetime.now(timezone.utc).date().isoformat()


def source_url(value):
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError("Source must be a public HTTPS page URL.")
    parts = urlsplit(value)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.port not in (None, 443)):
        raise ValueError("Source must be an HTTPS URL without credentials, on port 443.")
    return value


def read_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("date_read must be YYYY-MM-DD.")
    if date.fromisoformat(value) > date.fromisoformat(today()):
        raise ValueError("date_read cannot be in the future.")
    return value


class PageText(HTMLParser):
    """Keep block boundaries, ignore executable content and quoted testimonials."""
    blocks = {"p", "div", "section", "article", "li", "tr", "h1", "h2", "h3", "h4", "br", "dt", "dd"}
    hidden = {"script", "style", "noscript", "template", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = []

    def handle_starttag(self, tag, attrs):
        if tag in self.hidden:
            self.skip.append(tag)
        if not self.skip:
            if tag in self.blocks:
                self.parts.append("\n")
            elif tag in {"td", "th"}:
                self.parts.append(" ")

    def handle_endtag(self, tag):
        if self.skip:
            if tag == self.skip[-1]:
                self.skip.pop()
            return
        if tag in self.blocks:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def plain_text(text):
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError("Page text must be a string of at most 2 MiB.")
    if re.search(r"</?[a-zA-Z][^>]*>", text):
        parser = PageText()
        parser.feed(text)
        text = "".join(parser.parts)
    return "\n".join(line for raw in text.splitlines() if (line := " ".join(raw.split())))


# Matches only locate candidates. The full line, including negation and qualifications,
# stays intact. No classification into favorable/unfavorable terms is performed.
PATTERNS = {
    "services": r"\b(?:services?|we (?:offer|provide|build|manage)|website design|web design|paid ads|social media management|email marketing)\b",
    "contract": r"\b(?:contracts?|month[- ]to[- ]month|minimum term|commitment|agreement term)\b",
    "cancellation": r"\b(?:cancel\w*|termination|notice period|early exit)\b",
    "domain_ownership": r"(?=.*\bdomains?\b)(?=.*\b(?:own\w*|retain\w*|keep\w*|transfer\w*|belong\w*)\b)",
    "site_ownership": r"(?=.*\b(?:websites?|sites?)\b)(?=.*\b(?:own\w*|retain\w*|keep\w*|transfer\w*|belong\w*)\b)",
    "profile_ownership": r"(?=.*\bprofiles?\b)(?=.*\b(?:own\w*|retain\w*|keep\w*|transfer\w*|belong\w*)\b)",
    "ad_account_ownership": r"(?=.*\bad(?:vertising)? accounts?\b)(?=.*\b(?:own\w*|retain\w*|keep\w*|transfer\w*|belong\w*)\b)",
    "reporting_cadence": r"(?=.*\b(?:report\w*|updates?)\b)(?=.*\b(?:daily|weekly|monthly|quarterly|annually|every|on request)\b)",
    "reporting_format": r"(?=.*\b(?:report\w*|updates?)\b)(?=.*\b(?:dashboard|pdf|email|call|meeting|spreadsheet|portal)\b)",
    "prices": r"(?:[$£€]\s*\d|\b\d[\d,.]*\s*(?:USD|GBP|EUR)\b|\b(?:pricing|prices?|fees?|quote on request)\b)",
    "guarantees": r"\b(?:guarantee\w*|money[- ]back|refund\w*)\b",
}

# Only this narrow numeric substring is ever emitted for reviews, never review prose.
REVIEW = re.compile(r"(?<![\d.])(?P<rating>[0-5](?:\.\d+)?)\s*(?:/\s*5|out of 5|stars?)"
                    r"\s*(?:[|,;:()\-–]\s*)?(?:(?:from|based on)\s+)?"
                    r"(?P<count>\d[\d,]*)\s*(?:reviews?|ratings?)\b", re.I)


def review_candidate(line):
    match = REVIEW.search(line)
    if not match or float(match["rating"]) > 5:
        return None
    return {"quote": match[0], "rating": float(match["rating"]),
            "count": int(match["count"].replace(",", ""))}


def extract_offer(page_text, source_url_value, date_read=None):
    text = plain_text(page_text)
    when = read_date(today() if date_read is None else date_read)
    url = source_url(source_url_value) if source_url_value else ""
    facts = {key: {"status": "not stated", "candidates": []} for key in (*PATTERNS, "reviews")}
    in_reviews = False
    if url:
        for line in text.splitlines():
            review = review_candidate(line)
            if review:
                facts["reviews"]["candidates"].append(dict(review, source_url=url, date_read=when))
                continue
            if re.fullmatch(r"(?:customer |client )?(?:reviews|testimonials)(?:\s*:)?", line, re.I):
                in_reviews = True
                continue
            if in_reviews or re.search(r"\b(?:review|testimonial|client says|customer says)\b", line, re.I):
                continue
            if line.endswith("?") or re.fullmatch(r"(?:our )?(?:services|contracts?|cancellation|ownership|reporting|prices?|pricing|guarantees)\s*:?", line, re.I):
                continue
            for key, pattern in PATTERNS.items():
                if re.search(pattern, line, re.I):
                    candidate = {"quote": line, "source_url": url, "date_read": when}
                    if candidate not in facts[key]["candidates"]:
                        facts[key]["candidates"].append(candidate)
        for fact in facts.values():
            if fact["candidates"]:
                fact["status"] = "stated"
    return {"facts": facts, "source_url": url, "date_read": when,
            "notice": "Candidates only. Check attribution, context and qualifications against the page. "
                      "Not stated means no supported candidate in the supplied material; it is not a negative claim."}
