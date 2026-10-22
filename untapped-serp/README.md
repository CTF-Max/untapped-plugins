# Untapped SERP

Real Google results and search volume for your AI agent (Codex or Claude Code), through **your own DataForSEO
account**, with a daily spend cap. Built by [Find Untapped Growth](https://finduntappedgrowth.com/).

Built-in web search gives an agent a handful of results from its own index. This plugin gives it what Google
actually shows for a phrase in a place: positions, People Also Ask, the local pack, which sites an AI Overview
cites, the featured snippet, and every spot a given domain holds. It also gives Google Ads monthly search volume.

## Tools

| Tool | What it does | Cost to you (DataForSEO list price, read 2026-10-09) |
|---|---|---|
| `google_serp` | Live Google organic results for one keyword + location + device | $0.002 per 10 results (depth 10 = $0.002); search operators like `site:` cost 5× |
| `google_search_volume` | Monthly volume, CPC, competition, 12-month trend for 1–100 keywords (1000 with `allow_large_batch`) | $0.09 per call, any number of keywords |
| `serp_estimate` | Cost reserve for a call and whether today's cap allows it | free |
| `serp_spend` | Spend today / this month, the cap, the last 10 calls, whether credentials are set | free |

Prices: [SERP](https://dataforseo.com/pricing/serp/google-organic-serp-api) ·
[depth billing](https://dataforseo.com/help-center/serp-api-pricing-depth-update-faq) ·
[Google Ads volume](https://dataforseo.com/pricing/keywords-data/google-ads). The plugin records the cost each
response reports, so your ledger reflects what DataForSEO charged, not our estimate.

## Install

- **Claude Code:** `/plugin install untapped-serp --marketplace CTF-Max/untapped-plugins`
  (or, from a terminal: `claude plugin marketplace add CTF-Max/untapped-plugins`, then
  `claude plugin install untapped-serp@untapped-plugins`).
- **Codex:** `codex plugin marketplace add CTF-Max/untapped-plugins`, then `codex plugin add untapped-serp@untapped-plugins`.
- Needs Python 3.10+ on PATH as `python`. Standard library only: nothing to `pip install`.

## Setup

1. Create a DataForSEO account and copy your API login and password (dashboard → API Access).
2. Give them to the plugin:
   - **Claude Code** asks for them in the plugin's settings when you enable it (later: `/plugin` → untapped-serp →
     configure). They are kept in your computer's secure credential store, not in a settings file.
   - **Codex:** set them as environment variables, then restart Codex:
     ```powershell
     setx DATAFORSEO_LOGIN "you@example.com"
     setx DATAFORSEO_PASSWORD "your-api-password"
     ```
     (macOS/Linux: `export` them in your shell profile.)

## Settings

| Setting (Claude Code) / variable | Default | Meaning |
|---|---|---|
| Daily spend cap / `UNTAPPED_SERP_DAILY_CAP_USD` | `1.00` | Paid calls stop once charged + in-flight spend for the UTC day would pass this |
| `UNTAPPED_SERP_SANDBOX` | off | `1` = use DataForSEO's free sandbox (dummy data, labelled `sandbox: true`) |
| `UNTAPPED_SERP_HOME` | `~/.untapped-plugins/serp` (Windows: `C:\Users\<you>\.untapped-plugins\serp`) | Where the cache + spend ledger live |

## Money safety

- Same request again within its cache window (SERP 24 h, volume 30 days) = no new charge. `max_age_hours: 0` forces fresh.
- A call whose outcome is unknown (timeout, dropped connection) is **never retried automatically**; its reserve
  stays counted against today's cap.
- Only two HTTPS endpoints on `api.dataforseo.com` (or `sandbox.dataforseo.com`) are ever called; proxies and
  redirects are refused so your credentials can't be sent anywhere else.
- `dry_run: true` or `serp_estimate` shows the cost without calling.

## Limits worth knowing

- One SERP = one location, one device, one moment. Rankings move by street and by hour.
- Google Ads volumes are rounded buckets and are often `null` (no data) for small local phrases; null is never zero.
- `target: "not in top N"` means not found in the results fetched, not "not indexed".

## Development

```
python -m unittest discover -s untapped-serp/tests   # offline, 21 tests
python tools/sync_shared.py --check                  # shared MCP lib copies are current
python tools/serp_smoke.py                           # free sandbox round trip
```
