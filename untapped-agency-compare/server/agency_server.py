"""Local agency comparison MCP. Only read_agency_page accesses the network."""
import sys
sys.dont_write_bytecode = True

from email.message import Message
import http.client
import ipaddress
import json
from pathlib import Path
import queue
import socket
import ssl
import threading
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_stdio import ToolError, serve
from extract import MAX_BYTES, extract_offer, plain_text, source_url as validate_url, today
from compare import compare as build_comparison

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 20
MAX_REDIRECTS = 3


def criteria():
    return {"criteria": json.loads((ROOT / "data" / "criteria.json").read_text(encoding="utf-8"))}


def read_agency_page(url=None, text=None, source_url=None):
    if (url is None) == (text is None):
        raise ValueError("Provide exactly one of url or text.")
    if text is not None:
        if source_url:
            validate_url(source_url)
        return {"page_text": plain_text(text), "source_url": source_url or "", "date_read": today(),
                "input": "pasted", "notice": "Pasted material is not independently verified. "
                "Without its original URL, facts remain not stated."}
    if source_url is not None:
        raise ValueError("source_url is for pasted text only.")
    validate_url(url)
    original = url
    host = urlsplit(url).hostname
    deadline = time.monotonic() + TIMEOUT

    def remaining():
        left = deadline - time.monotonic()
        if left <= 0:
            raise ValueError("Page read exceeded the 20 second timeout.")
        return left

    for hop in range(MAX_REDIRECTS + 1):
        parts = urlsplit(url)
        # Resolve once and connect to the checked numeric address, keeping TLS hostname
        # verification against the requested host. No proxy, cookies or credential headers.
        resolved = queue.Queue(maxsize=1)

        def resolve(hostname, result):
            try:
                result.put(socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM))
            except OSError as exc:
                result.put(exc)

        # System DNS itself has no portable timeout; a daemon lets the tool return
        # on deadline even if the OS resolver is still waiting.
        threading.Thread(target=resolve, args=(parts.hostname, resolved), daemon=True).start()
        try:
            infos = resolved.get(timeout=remaining())
        except queue.Empty:
            raise ValueError("Page read exceeded the 20 second timeout.") from None
        if isinstance(infos, OSError):
            raise infos
        addresses = list(dict.fromkeys(item[4][0] for item in infos))
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise ValueError("Only public internet addresses can be read.")
        conn = http.client.HTTPSConnection(parts.hostname, 443, timeout=remaining())
        raw_socket = None
        try:
            raw_socket = socket.create_connection((addresses[0], 443), timeout=remaining())
            conn.sock = ssl.create_default_context().wrap_socket(raw_socket, server_hostname=parts.hostname)
            conn.sock.settimeout(remaining())
            path = urlunsplit(("", "", parts.path or "/", parts.query, ""))
            conn.request("GET", path, headers={"User-Agent": "UntappedAgencyCompare/0.1.0",
                                              "Accept": "text/html, text/plain", "Accept-Encoding": "identity"})
            response = conn.getresponse()
            remaining()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location or hop == MAX_REDIRECTS:
                    raise ValueError("Page exceeded three redirects or has no redirect target.")
                next_url = urljoin(url, location)
                validate_url(next_url)
                if urlsplit(next_url).hostname != host:
                    raise ValueError("Redirects to another host are not allowed. Ask the owner for that URL.")
                url = next_url
                continue
            if response.status != 200:
                raise ValueError("Page returned HTTP %d." % response.status)
            content_type = Message()
            content_type["content-type"] = response.getheader("Content-Type", "")
            if content_type.get_content_type() not in ("text/html", "text/plain", "application/xhtml+xml"):
                raise ValueError("Only HTML or plain text pages can be read.")
            if response.getheader("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("Compressed responses are not accepted.")
            size = response.getheader("Content-Length")
            if size is not None and (not size.isdigit() or int(size) > MAX_BYTES):
                raise ValueError("Page exceeds the 2 MiB limit or has an invalid content length.")
            body = bytearray()
            while True:
                conn.sock.settimeout(remaining()) if conn.sock else None
                chunk = response.read1(min(65536, MAX_BYTES + 1 - len(body)))
                remaining()
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise ValueError("Page exceeds the 2 MiB limit.")
            charset = content_type.get_content_charset() or "utf-8"
            decoded = bytes(body).decode(charset, errors="replace")
            return {"page_text": plain_text(decoded), "source_url": url, "requested_url": original,
                    "date_read": today(), "redirects": hop, "input": "fetched",
                    "notice": "Published page only, not verification of its claims. No linked pages were read."}
        finally:
            conn.close()
            if raw_socket:
                raw_socket.close()


def compare(agencies_json, priorities=None):
    included = json.loads((ROOT / "data" / "futg_facts.json").read_text(encoding="utf-8"))
    return build_comparison(agencies_json, criteria()["criteria"], [included], priorities)


def schema(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


TOOLS = [
    {"name": "read_agency_page", "description": "Read one owner-supplied HTTPS page or pasted text. No crawling; 20 second timeout, 2 MiB limit, at most three same-host redirects.",
     "inputSchema": dict(schema({"url": {"type": "string"}, "text": {"type": "string"},
                                 "source_url": {"type": "string", "description": "Original page URL for pasted text."}}),
                         oneOf=[{"required": ["url"], "not": {"required": ["text"]}},
                                {"required": ["text"], "not": {"required": ["url"]}}])},
    {"name": "extract_offer", "description": "Extract exact-quote candidates per criterion, with source and date. Missing evidence is not stated; reviews contain only rating and count. Check context before comparing.",
     "inputSchema": schema({"page_text": {"type": "string"}, "source_url": {"type": "string"},
                             "date_read": {"type": "string", "description": "Original read date YYYY-MM-DD; defaults to today for material read now."}}, ("page_text", "source_url"))},
    {"name": "compare", "description": "Compare sourced agency facts as Markdown, CSV and self-contained HTML. Always includes the maker under identical criteria, alphabetical columns, questions for missing facts, and no overall score.",
     "inputSchema": schema({"agencies_json": {"oneOf": [{"type": "string"}, {"type": "array", "maxItems": 20,
          "items": schema({"name": {"type": "string"}, "facts": {"type": "object"}}, ("name", "facts"))}],
          "description": "List or JSON list of {name, facts}; facts are the extract_offer facts mapping, merged by criterion across supplied pages."},
          "priorities": {"type": "array", "items": {"type": "string"}, "description": "Criterion IDs to show first; never weights."}}, ("agencies_json",))},
    {"name": "criteria", "description": "Show the shared criteria, definitions and missing-fact questions before comparing agencies.", "inputSchema": schema({})},
]
for tool in TOOLS:
    tool["annotations"] = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True,
                           "openWorldHint": tool["name"] == "read_agency_page"}


def call(name, args):
    known = {t["name"]: t["inputSchema"] for t in TOOLS}
    if name not in known:
        raise ToolError("Unknown tool.")
    spec = known[name]
    if set(args) - set(spec["properties"]) or set(spec["required"]) - set(args):
        raise ToolError("Missing or unexpected tool arguments.")
    try:
        if name == "extract_offer":
            return extract_offer(args["page_text"], args["source_url"], args.get("date_read"))
        return {"read_agency_page": read_agency_page, "compare": compare, "criteria": criteria}[name](**args)
    except (ValueError, TypeError, KeyError, LookupError) as exc:
        raise ToolError(str(exc)) from None
    except (OSError, http.client.HTTPException):
        raise ToolError("Could not read the page within the network limits. Paste its text and original URL instead.") from None


if __name__ == "__main__":
    serve(TOOLS, call, name="untapped-agency-compare", version="0.1.0")
