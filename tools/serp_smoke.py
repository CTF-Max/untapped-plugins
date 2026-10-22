"""Smoke-test untapped-serp through its real MCP server.

  python plugins/tools/serp_smoke.py            # FREE: DataForSEO sandbox (dummy data)
  python plugins/tools/serp_smoke.py --live     # PAID: ~$0.09 (1 SERP at $0.002 + 1 volume call at $0.09), cap $0.15

Writes a summary (never credentials) to plugins/smoke/untapped-serp/<UTC stamp>_<mode>.json.
"""
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

LANE = Path(__file__).resolve().parents[1]
SERVER = LANE / "untapped-serp" / "server" / "serp_server.py"
KEYWORD = "google business profile management"
LOCATION = "Palm Coast,Florida,United States"
VOLUME = ["google business profile management", "google business profile help", "local seo palm coast",
          "website design palm coast", "google maps ranking", "why is my business not showing on google maps"]


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows console is cp1252
    live = "--live" in sys.argv
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", UNTAPPED_SERP_DAILY_CAP_USD="0.15")
    env.pop("UNTAPPED_SERP_SANDBOX", None)
    if not live:
        env["UNTAPPED_SERP_SANDBOX"] = "1"
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18",
         "capabilities": {}, "clientInfo": {"name": "serp_smoke", "version": "1"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "google_serp", "arguments": {
            "keyword": KEYWORD, "location_name": LOCATION, "target_domain": "finduntappedgrowth.com", "max_age_hours": 0}}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "google_search_volume", "arguments": {
            "keywords": VOLUME, "max_age_hours": 0}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "serp_spend", "arguments": {}}},
    ]
    proc = subprocess.run([sys.executable, str(SERVER)], env=env, capture_output=True, timeout=180,
                          input=("".join(json.dumps(m) + "\n" for m in msgs)).encode("utf-8"))
    replies = {r["id"]: r.get("result", {}).get("structuredContent", r.get("error"))
               for r in map(json.loads, proc.stdout.decode("utf-8").splitlines())}
    serp, vol, spend = replies.get(2) or {}, replies.get(3) or {}, replies.get(4) or {}
    summary = {
        "mode": "live" if live else "sandbox", "utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "serp": {k: serp.get(k) for k in ("error", "check_url", "se_results_count", "features", "target", "cost_usd")}
        | {"top10": [(o["rank_group"], o["domain"]) for o in serp.get("organic", [])],
           "people_also_ask": serp.get("people_also_ask"), "local_pack": [p.get("title") for p in serp.get("local_pack", [])],
           "ai_overview": serp.get("ai_overview")},
        "volume": {"error": vol.get("error"), "cost_usd": vol.get("cost_usd"),
                   "rows": [(k["keyword"], k["search_volume"], k["cpc"]) for k in vol.get("keywords", [])]},
        "spend": {k: spend.get(k) for k in ("charged_today_usd", "held_uncertain_today_usd", "daily_cap_usd")},
        "server_stderr_bytes": len(proc.stderr),
    }
    out = LANE / "smoke" / "untapped-serp" / (summary["utc"].replace(":", "") + "_" + summary["mode"] + ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))  # ASCII-escaped: Windows consoles crash on emoji in titles
    print("\nSaved:", out)
    return 0 if not (serp.get("error") or vol.get("error")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
