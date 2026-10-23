"""One registry for every plugin's manifests. Writes, per plugin: .codex-plugin/plugin.json, .codex-mcp.json,
.claude-plugin/plugin.json; and both marketplaces. Run after any change here:  python plugins/tools/manifests.py
(--check exits 1 if a file on disk differs from what this would write).
"""
import json
import sys
from pathlib import Path

LANE = Path(__file__).resolve().parents[1]
AUTHOR = {"name": "Find Untapped Growth", "url": "https://finduntappedgrowth.com/"}
HOME = "https://finduntappedgrowth.com/"
REPO = "https://github.com/CTF-Max/untapped-plugins"  # public repo (Max 2026-10-22: GitHub profile CTF-Max)
VERSION = "0.2.0"
LICENSE = "MIT"
GOOGLE_CLIENT_SETTING = {
    "google_client_json": {
        "type": "file", "title": "Google OAuth client file",
        "description": "The Desktop-app OAuth client JSON you downloaded from Google Cloud console (APIs & Services "
                       "→ Credentials). Shared by every Untapped Google plugin. Leave empty if you set "
                       "UNTAPPED_GOOGLE_CLIENT_SECRET instead.",
    },
}
BASE_ENV = ["PATH", "SYSTEMROOT", "LOCALAPPDATA", "HOME", "USERPROFILE"]
GOOGLE_ENV = ["UNTAPPED_GOOGLE_CLIENT_SECRET", "UNTAPPED_GOOGLE_HOME"]

PLUGINS = [
    {
        "name": "untapped-agency-compare", "version": "0.4.0",
        "server": "server/agency_server.py", "category": "Research",
        "display": "Untapped Agency Compare", "short": "Compare agency services and terms with sources",
        "description": "Compare marketing agencies side by side using published claims and questions for missing facts. "
                       "Does not rank agencies or verify unpublished claims. Made by Find Untapped Growth, an agency included in every table.",
        "long": "See services, contract terms, ownership, reporting, prices, guarantees and review ratings with sources "
                "and dates. Get questions for missing facts. Does not rank agencies or verify claims an agency does not "
                "publish. Made by Find Untapped Growth, an agency included under the same criteria in every table.",
        "keywords": ["marketing agencies", "comparison", "agency contracts", "ownership", "published prices"],
        "env": [], "bundle_data": ["data/criteria.json", "data/futg_facts.json"],
        "prompts": ["Compare these agencies using the pages I provide",
                    "What questions should I ask each agency before signing?",
                    "Show the criteria for comparing marketing agencies"],
    },
    {
        "name": "untapped-resume", "version": "0.3.0", "server": "server/resume_server.py", "category": "Productivity",
        "display": "Untapped Resume", "short": "Tailor a resume and portfolio to one job, with evidence",
        "description": "Build a source-backed resume, portfolio and LinkedIn kit for one job from local evidence. "
                       "Free. Cannot post to LinkedIn; paste + upload takes about 2 minutes. Does not guarantee interviews.",
        "long": "Reads your project files, git history, old resumes and LinkedIn export locally. Helps your agent "
                "match one job, write a plain resume and portfolio, and prepare a LinkedIn kit, cover letter and "
                "gap plan. Missing evidence stays missing. Cannot post to LinkedIn; paste + upload takes about "
                "2 minutes. Does not guarantee interviews.",
        "keywords": ["resume", "portfolio", "linkedin", "job application", "evidence", "career"],
        "env": [],
        "prompts": ["Tailor my resume to this job using my project folder",
                    "Build a portfolio from my three most relevant projects",
                    "Check my resume for missing evidence and job requirements"],
    },
    {
        "name": "untapped-serp", "version": VERSION, "server": "server/serp_server.py", "category": "Research",
        "display": "Untapped SERP", "short": "Real Google results and search volume",
        "description": "Live Google results and search volume for your agent, through your own DataForSEO account, "
                       "with a daily spend cap.",
        "long": "Gives your agent live Google organic results (positions, People Also Ask, local pack, AI Overview "
                "cited domains, where your domain ranks) and Google Ads search volume, billed to your own DataForSEO "
                "account. Results are cached and a daily cap stops runaway spend. Credentials stay in your "
                "environment variables.",
        "keywords": ["google", "search results", "rank tracking", "search volume", "keyword research",
                     "local search", "dataforseo"],
        # Claude Code: the plugin's settings dialog, stored in the OS keychain; the server reads UNTAPPED_DATAFORSEO_*
        # first and falls back to DATAFORSEO_* (Codex, terminals).
        "settings": {
            "dataforseo_login": {"type": "string", "title": "DataForSEO API login", "sensitive": True,
                                 "description": "From the DataForSEO dashboard → API Access."},
            "dataforseo_password": {"type": "string", "title": "DataForSEO API password", "sensitive": True,
                                    "description": "From the DataForSEO dashboard → API Access."},
            "daily_cap_usd": {"type": "number", "title": "Daily spend cap (US dollars)", "default": 1, "min": 0,
                              "description": "Paid calls stop once today's spend would pass this."},
        },
        "claude_env": {"UNTAPPED_DATAFORSEO_LOGIN": "${user_config.dataforseo_login}",
                       "UNTAPPED_DATAFORSEO_PASSWORD": "${user_config.dataforseo_password}",
                       "UNTAPPED_SERP_DAILY_CAP_USD": "${user_config.daily_cap_usd}",
                       "UNTAPPED_SERP_SANDBOX": "${UNTAPPED_SERP_SANDBOX}",
                       "UNTAPPED_SERP_HOME": "${UNTAPPED_SERP_HOME}"},
        "env": ["DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD", "UNTAPPED_SERP_DAILY_CAP_USD", "UNTAPPED_SERP_SANDBOX",
                "UNTAPPED_SERP_HOME"],
        "prompts": ["Where does example.com rank on Google for 'plumber near me' in Austin, Texas?",
                    "Get Google search volume for these 20 keywords",
                    "How much have I spent on Google lookups today?"],
    },
    {
        "name": "untapped-index-watch", "version": VERSION, "server": "server/index_server.py", "category": "Research",
        "display": "Untapped Index Watch", "short": "Is every page in Google's index?",
        "description": "Checks every sitemap URL against Search Console's URL Inspection, says what each problem "
                       "usually means and what to do, and shows what changed since the last check. Free.",
        "long": "Signs in to your own Search Console (read-only), inspects each page in your sitemap, and reports "
                "indexed / not indexed / unknown with plain-language flags (dropped out, Google picked another "
                "canonical, not crawled for weeks, blocked by noindex or robots.txt) and the usual fix. Keeps a "
                "local history so you can see pages drop out or get picked up.",
        "keywords": ["google", "search console", "indexing", "index coverage", "sitemap", "website health"],
        "settings": GOOGLE_CLIENT_SETTING,
        "env": GOOGLE_ENV + ["UNTAPPED_INDEX_HOME"],
        "prompts": ["Are all my pages indexed on Google? My site is example.com",
                    "Which pages dropped out of Google's index since last week?",
                    "Why isn't my new page showing up on Google?"],
    },
    {
        "name": "untapped-search-console", "version": VERSION, "server": "server/gsc_server.py",
        "category": "Research",
        "display": "Untapped Search Console", "short": "What people search to find you, and what's close",
        "description": "Reads your own Search Console: the queries and pages that bring clicks, the ones close to "
                       "page one, what moved since last month, and the site's true totals. Free.",
        "long": "Signs in to your own Search Console (read-only) and answers the questions owners ask: which "
                "searches bring clicks (protect them), which are close to page one (where work pays), which rank "
                "near the top but don't get chosen (fix the title), and what gained or lost since the previous "
                "period. Windows end three days back so late data never looks like a drop.",
        "keywords": ["google", "search console", "search traffic", "queries", "clicks", "impressions"],
        "settings": GOOGLE_CLIENT_SETTING,
        "env": GOOGLE_ENV,
        "prompts": ["What searches bring people to example.com?",
                    "Which of my queries are close to page one?",
                    "What changed in my Google traffic compared with last month?"],
    },
    {
        "name": "untapped-site-audit", "version": VERSION, "server": "server/audit_server.py",
        "category": "Research",
        "display": "Untapped Site Audit", "short": "Audit a site in the order that finds the bottleneck",
        "description": "A guided live-site audit (indexed, seen, buyer phrases, on-page targeting, visitors, "
                       "buyers) plus free on-page checks across a sitemap: titles, H1s, canonicals, noindex, "
                       "schema, thin pages, duplicates.",
        "long": "Walks your agent through a website audit in the order that finds the real bottleneck, so it "
                "never tunes titles on pages Google hasn't indexed. Includes free tools that read every page in "
                "a sitemap and flag missing or duplicate titles, H1s and descriptions, wrong canonicals, noindex "
                "pages in the sitemap, redirects, robots.txt blocks, broken schema and thin pages. Works with "
                "Untapped Index Watch, Search Console and SERP when installed.",
        "keywords": ["website audit", "site audit", "google", "local search", "on-page checks", "sitemap"],
        "env": ["UNTAPPED_AUDIT_ALLOW_PRIVATE"],
        "prompts": ["Audit example.com and tell me what's holding it back",
                    "Check every page in my sitemap for title and H1 problems",
                    "Why isn't my website bringing in customers?"],
    },
]



def skills_only(path):
    """A skills-only plugin keeps its listing in its portable plugin.json (the ChatGPT source, tools/build_chatgpt.py);
    the Claude and Codex manifests are made from it, so the copy is never edited twice."""
    manifest = json.loads((LANE / path / "plugin.json").read_text(encoding="utf-8"))
    ui = manifest["extensions"]["com.openai"]["interface"]
    return {"name": manifest["name"], "version": manifest["version"], "path": path, "category": ui["category"],
            "display": ui["displayName"], "short": ui["shortDescription"], "description": manifest["description"],
            "long": ui["longDescription"], "keywords": manifest["keywords"], "prompts": ui["defaultPrompt"],
            "capabilities": ui["capabilities"], "icon": ui["logo"], "composer_icon": ui["composerIcon"]}


PLUGINS += [skills_only("chatgpt/untapped-reviews-maps")]
PUBLIC_PLUGINS = [p for p in PLUGINS if p.get("public", True)]  # listed in the marketplaces
# A held plugin is not in the public export, so only plugins whose folder exists here are built and checked.
PRESENT_PLUGINS = [p for p in PLUGINS if p.get("public", True) or (LANE / p.get("path", p["name"])).is_dir()]


def dump(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"


def folder(p):
    return p.get("path", p["name"])


def skills_only_files(p):
    docs = "%s/tree/main/%s" % (REPO, folder(p))
    codex = {"name": p["name"], "version": p["version"], "description": p["description"], "author": AUTHOR,
             "homepage": HOME, "repository": REPO, "license": LICENSE, "keywords": p["keywords"], "skills": "./skills/",
             "interface": {"displayName": p["display"], "shortDescription": p["short"], "longDescription": p["long"],
                           "developerName": AUTHOR["name"], "category": p["category"],
                           "capabilities": p["capabilities"], "websiteURL": HOME, "defaultPrompt": p["prompts"],
                           "brandColor": "#0F766E", "composerIcon": p["composer_icon"], "logo": p["icon"]}}
    claude = {"name": p["name"], "displayName": p["display"], "version": p["version"],
              "description": p["description"], "author": AUTHOR, "homepage": HOME, "repository": REPO,
              "license": LICENSE, "keywords": p["keywords"][:6], "icon": p["icon"],
              "documentationUrl": docs + "#readme", "supportUrl": REPO + "/issues",
              "privacyPolicyUrl": "%s/blob/main/%s/PRIVACY.md" % (REPO, folder(p))}
    root = LANE / folder(p)
    return {root / ".codex-plugin" / "plugin.json": dump(codex), root / ".claude-plugin" / "plugin.json": dump(claude)}


def files_for(p):
    if "path" in p:
        return skills_only_files(p)
    env = p["env"]
    icon = "./assets/%s.svg" % p["name"]
    codex = {
        "name": p["name"], "version": p["version"], "description": p["description"], "author": AUTHOR,
        "homepage": HOME, "repository": REPO, "license": LICENSE, "keywords": p["keywords"],
        "skills": "./skills/", "mcpServers": "./.codex-mcp.json",
        "interface": {"displayName": p["display"], "shortDescription": p["short"], "longDescription": p["long"],
                      "developerName": AUTHOR["name"], "category": p["category"], "capabilities": ["Read"],
                      "websiteURL": HOME, "defaultPrompt": p["prompts"], "brandColor": "#0F766E",
                      "composerIcon": icon, "logo": icon},
    }
    codex_mcp = {"mcpServers": {p["name"]: {"command": "python", "args": [p["server"]], "cwd": ".",
                                            "env_vars": BASE_ENV + env}}}
    # Claude: a plugin with its own claude_env takes it whole, so no credential is read from the user's environment.
    claude_env = dict(p["claude_env"]) if "claude_env" in p else {v: "${" + v + "}" for v in env}
    if p.get("settings", {}).get("google_client_json"):
        claude_env["UNTAPPED_GOOGLE_CLIENT_JSON"] = "${user_config.google_client_json}"
    claude = {"name": p["name"], "displayName": p["display"], "version": p["version"],
              "description": p["description"], "author": AUTHOR, "homepage": HOME, "repository": REPO,
              "license": LICENSE, "keywords": p["keywords"][:6],
              # Read by Anthropic's directory listing only (Claude Code ignores them).
              "icon": icon, "documentationUrl": "%s/tree/main/%s#readme" % (REPO, p["name"]),
              "supportUrl": REPO + "/issues", "privacyPolicyUrl": "%s/blob/main/%s/PRIVACY.md" % (REPO, p["name"]),
              "mcpServers": {p["name"]: {"command": "python", "args": ["${CLAUDE_PLUGIN_ROOT}/" + p["server"]],
                                         "env": claude_env}}}
    if p.get("settings"):
        claude["userConfig"] = p["settings"]
    root = LANE / p["name"]
    return {root / ".codex-plugin" / "plugin.json": dump(codex), root / ".codex-mcp.json": dump(codex_mcp),
            root / ".claude-plugin" / "plugin.json": dump(claude)}


def marketplaces():
    codex = {"name": "untapped-plugins", "interface": {"displayName": "Find Untapped Growth"},
             "plugins": [{"name": p["name"], "source": {"source": "local", "path": "./" + folder(p)},
                          "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                          "category": p["category"]} for p in PUBLIC_PLUGINS]}
    claude = {"name": "untapped-plugins", "owner": AUTHOR,
              "metadata": {"description": "Google search tools for AI agents (live results, indexing, Search Console, "
                                          "site audits, reviews and Maps help), from Find Untapped Growth."},
              "plugins": [{"name": p["name"], "source": "./" + folder(p), "description": p["description"],
                           "version": p["version"]} for p in PUBLIC_PLUGINS]}
    return {LANE / ".agents" / "plugins" / "marketplace.json": dump(codex),
            LANE / ".claude-plugin" / "marketplace.json": dump(claude)}


def skill_header_problems():
    """Plain (unquoted) YAML values in SKILL.md headers: a ': ' or ' #' inside one makes the whole header unreadable,
    and Claude then loads the skill with no description (found 2026-10-22 by `claude plugin validate --strict`)."""
    problems = []
    for skill in sorted([*LANE.glob("*/skills/*/SKILL.md"), *LANE.glob("chatgpt/*/skills/*/SKILL.md")]):
        parts = skill.read_text(encoding="utf-8").split("---", 2)
        if len(parts) < 3 or parts[0].strip():
            problems.append("%s: no --- header" % skill.relative_to(LANE))
            continue
        for line in parts[1].strip().splitlines():
            key, _, value = line.partition(": ")
            value = value.strip()
            if not value or value[0] in "\"'|>":
                continue
            if ": " in value or " #" in value or value.endswith(":"):
                problems.append("%s: '%s' needs quotes or rewording" % (skill.relative_to(LANE), key))
    return problems


def main():
    check = "--check" in sys.argv
    headers = skill_header_problems()
    if headers:
        print("Skill headers that won't parse: " + "; ".join(headers))
        return 1
    wanted = marketplaces()
    for p in PRESENT_PLUGINS:
        wanted.update(files_for(p))
    drift = []
    for path, text in wanted.items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current != text:
            drift.append(str(path.relative_to(LANE)))
            if not check:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
    if check and drift:
        print("Manifests out of date: " + ", ".join(drift))
        return 1
    print(("Manifests current" if check else "Wrote %d file(s)" % len(drift)) + " (%d plugins)." % len(PRESENT_PLUGINS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
