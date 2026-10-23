"""Build one MCP Bundle (.mcpb) per plugin and its MCP Registry entry.

  python tools/build_mcpb.py            # writes dist/<name>-mcp-<version>.mcpb + registry/<name>.server.json
  python tools/build_mcpb.py --check    # exits 1 if a registry entry differs from what the bundles would give

A bundle holds the plugin's stdio server (standard library Python), its LICENSE and README, and a manifest.json
(MCPB spec 0.3) whose settings mirror the Claude Code plugin settings. The MCP Registry lists a bundle by its GitHub
release URL + SHA-256, so the bundles go up as assets of the release tagged v<version>; the registry entry is only
metadata. Zip entries get a fixed timestamp so the same files always give the same SHA-256.
"""
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifests as m  # noqa: E402

LANE = m.LANE
DIST = LANE / "dist"
REGISTRY = LANE / "registry"
OWNER = m.REPO.rstrip("/").split("/")[-2]
REPO_NAME = m.REPO.rstrip("/").split("/")[-1]
FIXED_TIME = (2026, 1, 1, 0, 0, 0)
SCHEMA = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"

# Same settings as the Claude Code plugin, under the names the servers read first.
BUNDLE_SETTINGS = {
    "untapped-agency-compare": ({}, {}),
    "untapped-resume": ({}, {}),
    "untapped-serp": (
        {"dataforseo_login": {"type": "string", "title": "DataForSEO API login", "sensitive": True, "required": True,
                              "description": "From the DataForSEO dashboard → API Access."},
         "dataforseo_password": {"type": "string", "title": "DataForSEO API password", "sensitive": True,
                                 "required": True, "description": "From the DataForSEO dashboard → API Access."},
         "daily_cap_usd": {"type": "number", "title": "Daily spend cap (US dollars)", "default": 1, "min": 0,
                           "description": "Paid calls stop once today's spend would pass this."}},
        {"UNTAPPED_DATAFORSEO_LOGIN": "${user_config.dataforseo_login}",
         "UNTAPPED_DATAFORSEO_PASSWORD": "${user_config.dataforseo_password}",
         "UNTAPPED_SERP_DAILY_CAP_USD": "${user_config.daily_cap_usd}"}),
    "untapped-index-watch": (
        {"google_client_json": dict(m.GOOGLE_CLIENT_SETTING["google_client_json"], required=True)},
        {"UNTAPPED_GOOGLE_CLIENT_JSON": "${user_config.google_client_json}"}),
    "untapped-search-console": (
        {"google_client_json": dict(m.GOOGLE_CLIENT_SETTING["google_client_json"], required=True)},
        {"UNTAPPED_GOOGLE_CLIENT_JSON": "${user_config.google_client_json}"}),
    "untapped-site-audit": ({}, {}),
}


def summary(text):
    """Leading sentences up to at least 40 characters ("Free." alone says nothing)."""
    out = ""
    for sentence in text.split(". "):
        out = (out + " " + sentence.rstrip(".") + ".").strip()
        if len(out) >= 40:
            break
    return out


def listed_tools(server):
    """The tools the server itself reports (name + first sentence), over a real stdio handshake."""
    msgs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "build_mcpb", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]
    out = subprocess.run([sys.executable, str(server)], input="\n".join(json.dumps(x) for x in msgs) + "\n",
                         capture_output=True, text=True, encoding="utf-8", timeout=60,
                         env=dict({k: v for k, v in os.environ.items()
                                   if not k.startswith(("DATAFORSEO_", "UNTAPPED_"))},
                                  PYTHONDONTWRITEBYTECODE="1")).stdout
    for line in out.splitlines():
        msg = json.loads(line)
        if msg.get("id") == 2:
            return [{"name": t["name"], "description": summary(t.get("description", ""))}
                    for t in msg["result"]["tools"]]
    raise SystemExit("No tools/list answer from " + str(server))


def bundle_manifest(p):
    settings, env = BUNDLE_SETTINGS[p["name"]]
    root = LANE / p["name"]
    out = {
        "manifest_version": "0.3", "name": p["name"], "display_name": p["display"], "version": p["version"],
        "description": p["description"], "long_description": p["long"], "author": m.AUTHOR,
        "repository": {"type": "git", "url": m.REPO + ".git"}, "homepage": m.HOME,
        "documentation": "%s/tree/main/%s#readme" % (m.REPO, p["name"]), "support": m.REPO + "/issues",
        "license": m.LICENSE, "keywords": p["keywords"],
        "server": {"type": "python", "entry_point": p["server"],
                   "mcp_config": {"command": "python", "args": ["${__dirname}/" + p["server"]], "env": env}},
        "tools": listed_tools(root / p["server"]),
        "compatibility": {"platforms": ["win32", "darwin", "linux"], "runtimes": {"python": ">=3.10"}},
        "privacy_policies": ["%s/blob/main/%s/PRIVACY.md" % (m.REPO, p["name"])],
    }
    if settings:
        out["user_config"] = settings
    return out


def build(p):
    root = LANE / p["name"]
    files = sorted(f for f in (root / "server").glob("*.py")) + [root / "LICENSE", root / "README.md",
                                                                  root / "PRIVACY.md"]
    files += [root / path for path in p.get("bundle_data", [])]
    DIST.mkdir(exist_ok=True)
    target = DIST / ("%s-mcp-%s.mcpb" % (p["name"], p["version"]))  # registry rule: "mcp" in the file name
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        def add(arcname, data):
            info = zipfile.ZipInfo(arcname, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
        add("manifest.json", m.dump(bundle_manifest(p)))
        for f in files:
            add(f.relative_to(root).as_posix(), f.read_bytes())
    return target, hashlib.sha256(target.read_bytes()).hexdigest()


def registry_entry(p, url, sha):
    return {
        "$schema": SCHEMA,
        "name": "io.github.%s/%s" % (OWNER, p["name"]),
        "title": p["display"],
        "description": p["short"],
        "version": p["version"],
        "websiteUrl": "%s/tree/main/%s#readme" % (m.REPO, p["name"]),
        "repository": {"url": m.REPO, "source": "github", "subfolder": p["name"]},
        "packages": [{"registryType": "mcpb", "identifier": url, "version": p["version"], "fileSha256": sha,
                      "transport": {"type": "stdio"}}],
    }


def main():
    check = "--check" in sys.argv
    names = [arg for arg in sys.argv[1:] if arg != "--check"]
    servers = [p for p in m.PRESENT_PLUGINS if "server" in p]  # skills-only plugins have no bundle
    unknown = set(names) - {p["name"] for p in servers}
    if unknown:
        raise SystemExit("Unknown plugin(s): " + ", ".join(sorted(unknown)))
    selected = [p for p in servers if not names or p["name"] in names]
    REGISTRY.mkdir(exist_ok=True)
    drift = []
    for p in selected:
        target, sha = build(p)
        url = "%s/releases/download/v%s/%s" % (m.REPO, p["version"], target.name)
        path = REGISTRY / ("%s.server.json" % p["name"])
        text = m.dump(registry_entry(p, url, sha))
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            drift.append(path.name)
            if not check:
                path.write_text(text, encoding="utf-8")
        print("%s  %s  %d bytes  sha256 %s" % (target.name, p["version"], target.stat().st_size, sha))
    if check and drift:
        print("Registry entries out of date: " + ", ".join(drift))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
