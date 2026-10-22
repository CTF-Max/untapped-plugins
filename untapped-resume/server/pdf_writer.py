"""Small, real-text PDF writer and explicitly best-effort stdlib PDF reader.

Generated PDFs use standard Courier / WinAnsi: unsupported characters fail rather
than silently replacing a person's name. General PDFs may need an exported TXT.
"""
from __future__ import annotations

import re
import zlib
from pathlib import Path

WIDTH = 84
LINES_PER_PAGE = 52
MAX_PDF = 20 * 1024 * 1024


def write_pdf(lines: list[str], path: Path) -> None:
    encoded = [line.encode("cp1252", "strict") for line in lines]
    chunks = [encoded[i:i + LINES_PER_PAGE] for i in range(0, len(encoded), LINES_PER_PAGE)] or [[]]
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>"]
    kids = []
    for chunk in chunks:
        page_id = len(objects) + 1
        stream_id = page_id + 1
        kids.append(f"{page_id} 0 R")
        objects.append((f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                        f"/Resources << /Font << /F1 3 0 R >> >> /Contents {stream_id} 0 R >>").encode())
        content = b"BT\n/F1 10 Tf\n0 g\n13 TL\n1 0 0 1 54 738 Tm\n"
        for i, line in enumerate(chunk):
            if i:
                content += b"T*\n"
            escaped = line.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
            content += b"(" + escaped + b") Tj\n"
        content += b"ET\n"
        objects.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"endstream")
    objects[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(chunks)} >>".encode()
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    start = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode())
    out.extend((f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n").encode())
    path.write_bytes(out)


def _tokens(data):
    """Tokenize strings including nested parentheses, hex strings, and escapes."""
    i = 0
    while i < len(data):
        c = data[i]
        if c in b" \t\r\n\x00\x0c":
            i += 1
            continue
        if c == 37:
            i = data.find(b"\n", i)
            if i < 0:
                return
            continue
        if c == 40:
            i += 1
            depth, value = 1, bytearray()
            while i < len(data) and depth:
                c = data[i]
                i += 1
                if c == 92 and i < len(data):
                    c = data[i]
                    i += 1
                    escapes = {110: 10, 114: 13, 116: 9, 98: 8, 102: 12}
                    if 48 <= c <= 55:
                        octal = bytes([c])
                        while i < len(data) and len(octal) < 3 and 48 <= data[i] <= 55:
                            octal += bytes([data[i]])
                            i += 1
                        value.append(int(octal, 8) % 256)
                    elif c in (10, 13):
                        if c == 13 and i < len(data) and data[i] == 10:
                            i += 1
                    else:
                        value.append(escapes.get(c, c))
                elif c == 40:
                    depth += 1
                    value.append(c)
                elif c == 41:
                    depth -= 1
                    if depth:
                        value.append(c)
                else:
                    value.append(c)
            yield ("string", bytes(value))
        elif c == 60 and data[i:i + 2] != b"<<":
            end = data.find(b">", i + 1)
            if end < 0:
                return
            raw = re.sub(rb"\s", b"", data[i + 1:end])
            try:
                yield ("string", bytes.fromhex((raw + (b"0" if len(raw) % 2 else b"")).decode()))
            except ValueError:
                pass
            i = end + 1
        elif c in b"[]<>":
            yield ("token", bytes([c]))
            i += 1
        else:
            end = i + 1
            while end < len(data) and data[end] not in b" \t\r\n()[]<>%":
                end += 1
            yield ("token", data[i:end])
            i = end


def extract_pdf(path) -> dict:
    path = Path(path)
    if path.stat().st_size > MAX_PDF:
        raise ValueError("PDF exceeds the 20 MB read limit.")
    data = path.read_bytes()
    if not data.startswith(b"%PDF-"):
        raise ValueError("Not a PDF file.")
    warnings, streams = [], []
    if b"/Encrypt" in data:
        warnings.append("Encrypted PDF: extraction cannot be verified.")
    if b"/ToUnicode" in data or b"/Type0" in data:
        warnings.append("Custom/Unicode font maps are not supported; export text for verification.")
    for match in re.finditer(rb"<<(.*?)>>\s*stream\r?\n(.*?)\r?\n?endstream", data, re.S):
        header, stream = match.groups()
        if b"/Filter" in header:
            if re.search(rb"/Filter\s*/FlateDecode\b", header):
                try:
                    dec = zlib.decompressobj()
                    stream = dec.decompress(stream, MAX_PDF + 1)
                    if len(stream) > MAX_PDF or not dec.eof:
                        raise ValueError("oversize or incomplete stream")
                except (zlib.error, ValueError):
                    warnings.append("Compressed stream could not be read within the size limit.")
                    continue
            else:
                warnings.append("Unsupported PDF stream filter; extraction is incomplete.")
                continue
        streams.append(stream)
    lines = []
    hidden = False
    for stream in streams:
        operands, parts, active = [], [], False
        # These are suspicious signals, not a full graphics interpreter.
        hidden |= bool(re.search(rb"\b[37]\s+Tr\b|(?:^|\s)1(?:\.0*)?\s+g\b|"
                                 rb"1(?:\.0*)?\s+1(?:\.0*)?\s+1(?:\.0*)?\s+rg\b|"
                                 rb"0\s+0\s+0\s+0\s+k\b", stream))
        hidden |= any(float(m) < 6 for m in re.findall(rb"/\S+\s+([\d.]+)\s+Tf\b", stream))
        for kind, token in _tokens(stream):
            if kind == "string":
                operands.append((kind, token))
                continue
            if token == b"BT":
                active = True
                operands = []
            elif token in (b"Tj", b"TJ", b"'", b'"') and active:
                if token in (b"'", b'"') and parts:
                    lines.append("".join(parts))
                    parts = []
                for k, value in operands:
                    if k == "string":
                        parts.append(value.decode("utf-16" if value.startswith((b"\xfe\xff", b"\xff\xfe"))
                                                  else "cp1252", "replace"))
                operands = []
            elif token in (b"T*", b"Td", b"TD", b"Tm", b"ET"):
                if parts:
                    lines.append("".join(parts))
                    parts = []
                if token == b"ET":
                    active = False
                operands = []
            elif token in (b"Tf", b"TL", b"Tr", b"g", b"rg", b"k", b"Tc", b"Tw", b"Tz", b"Ts"):
                operands = []
            else:
                operands.append((kind, token))
        if parts:
            lines.append("".join(parts))
    hidden |= bool(re.search(rb"/(?:ca|CA)\s+0(?:\.0*)?(?:\s|/|>)", data))
    if not lines:
        warnings.append("No extractable text; scanned or unsupported PDF. Export a text version.")
    return {"text": "\n".join(lines) + ("\n" if lines else ""), "lines": lines,
            "pages": len(re.findall(rb"/Type\s*/Page\b", data)), "warnings": list(dict.fromkeys(warnings)),
            "hidden_text": hidden, "images": bool(re.search(rb"/Subtype\s*/Image\b", data)),
            "tables": bool(re.search(rb"/S\s*/(?:Table|TR|TD)\b", data))}
