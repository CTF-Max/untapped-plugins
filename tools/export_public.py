"""Copy the public part of the plugins lane into the public repo checkout, then scan it for secrets.

  python tools/export_public.py --to "C:\\path\\to\\untapped-plugins"         # copy + scan (exit 1 on any finding)
  python tools/export_public.py --to "C:\\path\\to\\untapped-plugins" --scan  # scan only

Only names in PUBLIC are copied; plans, proposals, briefs, smoke results and build output stay private. Files in the
target that the lane no longer has are deleted (the target's .git is left alone). The scan refuses API keys, OAuth
secrets and tokens, private keys, personal e-mail addresses and Windows user paths, except the made-up values the
offline tests use (FAKE_VALUES). Run it before every push; SOP-RELEASE-PLUGIN-001 step 4.
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

LANE = Path(__file__).resolve().parents[1]
PUBLIC = [".claude-plugin", ".agents", ".gitignore", "LICENSE", "README.md", "registry", "shared", "tools",
          "untapped-serp", "untapped-index-watch", "untapped-search-console", "untapped-site-audit", "untapped-resume",
          "chatgpt/untapped-reviews-maps"]
# Built but not released: their registry entries stay private too.
PRIVATE_FILES = {"registry/untapped-agency-compare.server.json", "tools/sync_agency_compare.py",
                 # ChatGPT build + evals need the held agency plugin and the private chatgpt/ sources.
                 "tools/build_chatgpt.py", "tools/run_chatgpt_evals.py", "tools/tests/test_build_chatgpt.py",
                 "tools/schemas/agent-plugins-1.0.0-plugin.schema.json"}
SKIP_DIRS = {"__pycache__", ".pytest_cache", "dist", "smoke", ".build"}
SKIP_FILES = {"Thumbs.db", "desktop.ini", ".DS_Store"}
SKIP_SUFFIXES = {".pyc", ".mcpb", ".zip"}

SECRET_PATTERNS = {
    "OpenAI/Anthropic-style key": r"sk-(?:ant-)?[A-Za-z0-9_-]{20,}",
    "Google API key": r"AIza[0-9A-Za-z_-]{30,}",
    "Google OAuth client secret": r"GOCSPX-[A-Za-z0-9_-]+",
    "Google access token": r"ya29\.[A-Za-z0-9_.-]+",
    "Google refresh token": r"1//0?[A-Za-z0-9_-]{6,}",
    "Google OAuth client id": r"[0-9]{6,}-[a-z0-9]{20,}\.apps\.googleusercontent\.com",
    "GitHub token": r"(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}",
    "Cloudflare/AWS-style key": r"AKIA[0-9A-Z]{16}",
    "private key": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "client_secret value": r"client_secret\"?\s*[:=]\s*\"[^\"]{6,}\"",
    "password value": r"(?i)password\"?\s*[:=]\s*\"[^\"$<{][^\"]{5,}\"",
    "e-mail address": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "Windows user path": r"(?i)[A-Z]:\\+Users\\+(?!<you>|you\\)[A-Za-z0-9._-]+|/c/Users/[A-Za-z0-9._-]+",
}
# Made-up values in the offline tests and docs. Anything else that matches stops the export.
FAKE_VALUES = {
    "GOCSPX-client-SECRET-4471", "ya29.access-SECRET-5520", "1//refresh-SECRET-8812", "ya29.new-token-1234",
    "ya29.token-for-tests", "1//r-123456", 'client_secret": "csecret-123"', "login-SECRET-7781@example.com",
    "you@example.com",
}
ALLOWED_EMAIL_DOMAINS = ("example.com", "example.org", "example.test")
# The support address already published on https://finduntappedgrowth.com/faq/; the skills-only plugin lists it.
PUBLIC_EMAILS = {"max@finduntappedgrowth.com"}


def public_files(root):
    for name in PUBLIC:
        top = root / name
        if top.is_file():
            yield top
            continue
        for path in sorted(top.rglob("*")):
            rel = path.relative_to(root)
            if rel.as_posix() in PRIVATE_FILES:
                continue
            if path.is_dir() or SKIP_DIRS.intersection(rel.parts) or path.name in SKIP_FILES \
                    or path.suffix in SKIP_SUFFIXES:
                continue
            yield path


def scan(root):
    findings = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and ".git" not in p.relative_to(root).parts):
        rel = path.relative_to(root).as_posix()
        if path.stat().st_size > 256 * 1024 and path.suffix not in (".png", ".svg"):
            findings.append("%s: over 256 KiB (Anthropic directory holds it for review)" % rel)
        if path.suffix in (".png", ".jpg", ".jpeg", ".webp"):  # icons; no text to scan
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            findings.append("%s: binary file" % rel)
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for label, pattern in SECRET_PATTERNS.items():
                for match in re.finditer(pattern, line):
                    value = match.group(0)
                    if any(value in fake or fake in value for fake in FAKE_VALUES):
                        continue
                    if label == "e-mail address" and (value.lower().endswith(ALLOWED_EMAIL_DOMAINS)
                                                      or value.lower() in PUBLIC_EMAILS):
                        continue
                    findings.append("%s:%d: %s: %s" % (rel, lineno, label, value[:12] + "..."))
    return findings


def export(target):
    target.mkdir(parents=True, exist_ok=True)
    wanted = {path.relative_to(LANE) for path in public_files(LANE)}
    for rel in sorted(wanted):
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(LANE / rel, dest)
    for path in sorted(target.rglob("*"), reverse=True):
        rel = path.relative_to(target)
        if rel.parts[0] == ".git":
            continue
        if path.is_file() and rel not in wanted:
            path.unlink()
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    return len(wanted)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True, type=Path)
    ap.add_argument("--scan", action="store_true", help="scan the target only, copy nothing")
    args = ap.parse_args()
    target = args.to.resolve()
    if not args.scan and (target == LANE or LANE in target.parents):
        raise SystemExit("The public checkout must live outside the lane folder.")
    if not args.scan:
        print("Copied %d files to %s" % (export(target), target))
    findings = scan(target)
    for line in findings:
        print("FOUND " + line)
    print("Secret scan: %s" % ("%d finding(s), do not push" % len(findings) if findings else "clean"))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
