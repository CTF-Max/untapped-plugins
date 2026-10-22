"""Live test of untapped-index-watch + untapped-search-console through their real MCP servers. Free.

  python plugins/tools/google_smoke.py --client "C:\\path\\to\\client_secret.json" --site finduntappedgrowth.com

Signs in (your browser opens once: approve read-only Search Console), then runs index_check (20 URLs) and
gsc_totals / gsc_whats_working / gsc_compare. Saves a summary, never a secret, to plugins/smoke/google/.
--client can be left out once UNTAPPED_GOOGLE_CLIENT_SECRET is set.
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

LANE = Path(__file__).resolve().parents[1]


class Mcp:
    def __init__(self, server, env):
        self.proc = subprocess.Popen([sys.executable, str(server)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, env=env)
        self.next_id = 0

    def call(self, name, args=None):
        self.next_id += 1
        msg = {"jsonrpc": "2.0", "id": self.next_id, "method": "tools/call",
               "params": {"name": name, "arguments": args or {}}}
        self.proc.stdin.write((json.dumps(msg) + "\n").encode())
        self.proc.stdin.flush()
        reply = json.loads(self.proc.stdout.readline().decode("utf-8"))
        result = reply.get("result") or {}
        return result.get("structuredContent", reply.get("error")), bool(result.get("isError"))

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(timeout=10)
        return len(self.proc.stderr.read())


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows console is cp1252
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", help="path to a Desktop-app OAuth client JSON")
    ap.add_argument("--site", default="finduntappedgrowth.com")
    a = ap.parse_args()
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    if a.client:
        env["UNTAPPED_GOOGLE_CLIENT_SECRET"] = a.client
    index = Mcp(LANE / "untapped-index-watch" / "server" / "index_server.py", env)
    status, _ = index.call("google_login_status")
    print("client configured:", status.get("client_configured"), "| signed in:", status.get("signed_in"))
    if not status.get("client_configured"):
        print(status.get("client_problem"))
        return 1
    if not status.get("signed_in"):
        started, err = index.call("google_login")
        if err:
            print("login failed to start:", started)
            return 1
        print("\nYour browser should open. If not, open this link:\n" + started["auth_url"] + "\n")
        for _ in range(300):
            time.sleep(1)
            state = index.call("google_login_status")[0].get("login")
            if state != "pending":
                break
        print("sign-in:", state)
        if state != "signed_in":
            return 1
    summary = {"utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "site": a.site}
    out, err = index.call("index_check", {"site": a.site, "max_urls": 20})
    summary["index_check"] = out if err else {k: out[k] for k in ("property", "urls_found", "checked", "summary",
                                                                  "newly_dropped", "needs_attention")}
    stderr_index = index.close()
    gsc = Mcp(LANE / "untapped-search-console" / "server" / "gsc_server.py", env)
    for tool, args in (("gsc_totals", {"site": a.site, "days": 90}),
                       ("gsc_whats_working", {"site": a.site, "days": 90}),
                       ("gsc_compare", {"site": a.site})):
        out, err = gsc.call(tool, args)
        if not err and tool == "gsc_whats_working":
            out = {k: out[k] for k in ("from", "to", "counts", "earning", "top3_no_clicks", "close")}
        if not err and tool == "gsc_compare":
            out = {k: out[k] for k in ("current", "previous", "gainers", "new", "lost")}
        summary[tool] = out
    summary["server_stderr_bytes"] = stderr_index + gsc.close()
    path = LANE / "smoke" / "google" / (summary["utc"].replace(":", "") + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2)[:4000])
    print("\nSaved:", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
